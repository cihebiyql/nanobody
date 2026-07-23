#!/usr/bin/env python3
"""Split-first loader for the V2.20 train-only residue-contact teacher.

This module is intentionally limited to label-side data preparation.  It never
opens Docking coordinates, never reads development/test poses, and never
forwards identifiers or teacher metadata into the neural model.  The outer-fit
parent allowlist is frozen before the scalar identity table or any teacher
payload is opened.  Candidate rows belonging to the outer-score parents are
identity-checked and skipped before any numeric conversion.

The resulting tensors match the contact-label keys consumed by the frozen
V2.5 ``train_v2_5_ortho_heads.py`` primitives.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor


SCHEMA_VERSION = "pvrig_v2_20_contact_teacher_store_v1"
RECEPTORS = ("8x6b", "9e6y")
DEFAULT_TARGET_NODES = {"8x6b": 103, "9e6y": 108}
DEFAULT_SOURCE_COUNTS = {"V4D": 113, "V4H": 320, "V29": 305}
TIER_WEIGHTS = {"3_SEED": 1.0, "2_SEED": 0.8}
PAIR_SEMANTICS = "SPARSE_ABSENCE_IS_EXACT_ZERO_AFTER_VALID_GROUP_CLOSURE"
PACKAGE_STATUS = "PASS_TRAIN_ONLY_738_CONTACT_TEACHER_MATERIALIZED_V1_2"

MANIFEST_NAME = "train_contact_candidate_manifest.tsv"
MARGINAL_NAME = "train_dense_marginal_contact_teacher.tsv.gz"
PAIR_NAME = "train_sparse_pair_contact_teacher.tsv.gz"
GROUP_NAME = "train_candidate_receptor_group_audit.tsv.gz"
NODE_CONTRACT_NAME = "target_node_position_baseline_contract.tsv"
RECEIPT_NAME = "MATERIALIZATION_RECEIPT.json"
ACCESS_AUDIT_NAME = "ACCESS_AUDIT.json"


class ContactTeacherStoreError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContactTeacherStoreError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular_file:{path}")


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _rows(path: Path, required: set[str], label: str) -> Iterable[dict[str, str]]:
    _regular_file(path, label)
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or ())
        require(required <= fields, f"{label}_fields_missing:{sorted(required-fields)}")
        for row in reader:
            yield {str(key): str(value) for key, value in row.items()}


@dataclass(frozen=True)
class TeacherStoreConfig:
    expected_teacher_candidates: int = 738
    expected_teacher_parents: int = 53
    expected_scalar_candidates: int = 9849
    expected_source_counts: Mapping[str, int] | None = field(
        default_factory=lambda: dict(DEFAULT_SOURCE_COUNTS)
    )
    target_nodes: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_TARGET_NODES))
    package_status: str = PACKAGE_STATUS

    def validate(self) -> None:
        require(self.expected_teacher_candidates > 0, "expected_teacher_candidates_invalid")
        require(self.expected_teacher_parents > 0, "expected_teacher_parents_invalid")
        require(self.expected_scalar_candidates >= self.expected_teacher_candidates, "expected_scalar_candidates_invalid")
        require(set(self.target_nodes) == set(RECEPTORS), "target_node_receptor_closure")
        require(all(int(self.target_nodes[name]) > 0 for name in RECEPTORS), "target_node_count_invalid")
        if self.expected_source_counts is not None:
            require(sum(int(value) for value in self.expected_source_counts.values()) == self.expected_teacher_candidates,
                    "expected_source_count_total")


@dataclass(frozen=True)
class ParentSplit:
    fit_parents: frozenset[str]
    score_parents: frozenset[str]
    split_id: str
    fold_id: int
    source_path: Path
    source_sha256: str


@dataclass(frozen=True)
class CandidateIdentity:
    candidate_id: str
    sequence_sha256: str
    sequence: str
    parent: str


@dataclass(frozen=True)
class TeacherMetadata:
    identity: CandidateIdentity
    teacher_source: str
    reliability_tier: str
    observed_seed_count_text: str
    observed_seed_ids: str
    role: str

    @property
    def tier_weight(self) -> float:
        return float(TIER_WEIGHTS[self.reliability_tier])


@dataclass
class GroupTeacher:
    receptor: str
    sequence_length: int
    target_node_count: int
    valid: bool
    technical_na_reason: str | None
    expected_sparse_rows: int
    marginal_target: np.ndarray
    marginal_uncertainty: np.ndarray
    marginal_mask: np.ndarray
    marginal_seen: np.ndarray
    pair_target: np.ndarray
    pair_uncertainty: np.ndarray
    pair_mask: np.ndarray
    sparse_seen: set[tuple[int, int]] = field(default_factory=set)


class ParseAudit:
    """Audited numeric conversion and split-before-access event recorder."""

    def __init__(self) -> None:
        self.allowlist_frozen = False
        self.events: list[str] = []
        self.numeric_int_parses = {"fit": 0, "score": 0, "label_free": 0}
        self.numeric_float_parses = {"fit": 0, "score": 0, "label_free": 0}
        self.score_rows_skipped_before_numeric_parse: dict[str, int] = {}
        self.source_rows_skipped_before_numeric_parse: dict[str, int] = {}
        self.technical_na_rows_skipped: dict[str, int] = {}

    def event(self, value: str) -> None:
        self.events.append(value)

    def freeze_allowlist(self) -> None:
        require(not self.allowlist_frozen, "allowlist_already_frozen")
        self.allowlist_frozen = True
        self.event("outer_fit_parent_allowlist_frozen")

    def _check_role(self, role: str) -> None:
        require(self.allowlist_frozen, "numeric_parse_before_outer_fit_allowlist_frozen")
        require(role in {"fit", "label_free"}, f"numeric_parse_forbidden_role:{role}")

    def integer(self, value: str, *, role: str, label: str) -> int:
        self._check_role(role)
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ContactTeacherStoreError(f"integer_parse_failed:{label}:{value}") from error
        self.numeric_int_parses[role] += 1
        return parsed

    def floating(self, value: str, *, role: str, label: str) -> float:
        self._check_role(role)
        try:
            parsed = float(value)
        except (TypeError, ValueError) as error:
            raise ContactTeacherStoreError(f"float_parse_failed:{label}:{value}") from error
        require(math.isfinite(parsed), f"float_nonfinite:{label}")
        self.numeric_float_parses[role] += 1
        return parsed

    def skip_score(self, stream: str) -> None:
        self.score_rows_skipped_before_numeric_parse[stream] = (
            self.score_rows_skipped_before_numeric_parse.get(stream, 0) + 1
        )

    def skip_technical_na(self, stream: str) -> None:
        self.technical_na_rows_skipped[stream] = self.technical_na_rows_skipped.get(stream, 0) + 1

    def skip_source(self, stream: str) -> None:
        self.source_rows_skipped_before_numeric_parse[stream] = (
            self.source_rows_skipped_before_numeric_parse.get(stream, 0) + 1
        )


def load_parent_split(path: Path, audit: ParseAudit) -> ParentSplit:
    """Open and freeze the only parent allowlist before all other inputs."""
    _regular_file(path, "outer_split")
    require(not audit.events, "split_manifest_must_be_first_access")
    audit.event("outer_split_manifest_open")
    payload = json.loads(path.read_text(encoding="utf-8"))
    fit = frozenset(str(value) for value in payload.get("train_parents", ()))
    score = frozenset(str(value) for value in payload.get("score_parents", ()))
    require(fit and score and fit.isdisjoint(score), "outer_parent_split_invalid")
    frozen = frozenset(str(value) for value in payload.get("frozen_test_parents", ()))
    require(not ((fit | score) & frozen), "outer_split_frozen_parent_overlap")
    split = ParentSplit(
        fit_parents=fit,
        score_parents=score,
        split_id=str(payload.get("split_id", "")),
        fold_id=int(payload.get("fold_id", -1)),  # structural metadata, not a teacher numeric payload
        source_path=path.resolve(),
        source_sha256=sha256_file(path),
    )
    require(split.fold_id >= 0 and split.split_id, "outer_split_identity_invalid")
    audit.freeze_allowlist()
    return split


class ContactTeacherStore:
    """Outer-fit-only in-memory contact targets with score-parent masking."""

    def __init__(self, split: ParentSplit, config: TeacherStoreConfig, audit: ParseAudit) -> None:
        config.validate()
        require(audit.allowlist_frozen, "store_constructed_before_allowlist_freeze")
        self.split = split
        self.config = config
        self._audit = audit
        self.scalar_identity: dict[str, CandidateIdentity] = {}
        self.teacher_metadata: dict[str, TeacherMetadata] = {}
        self.groups: dict[tuple[str, str], GroupTeacher] = {}
        self.target_node_identity: dict[str, dict[int, tuple[int, str]]] = {name: {} for name in RECEPTORS}
        self.package_receipt_sha256 = ""
        self.package_output_hashes: dict[str, str] = {}
        self._release_allowlist_mode = False
        self._allowed_candidates: dict[str, tuple[str, str]] = {}
        self._allowed_sources: frozenset[str] | None = None

    @classmethod
    def from_release(
        cls,
        release_dir: Path | str,
        allowed_candidates: Mapping[str, tuple[str, str]],
        allowed_sources: Sequence[str] | None = None,
        shuffle_seed: int | None = None,
    ) -> "ContactTeacherStore":
        """Load a release after freezing the caller's outer-fit allowlist.

        ``allowed_candidates`` maps candidate ID to ``(sequence_sha256,
        parent_framework_cluster)``.  It is copied and canonically hashed before
        the release directory is inspected.  ``shuffle_seed`` is deliberately
        rejected by this v1 store: target shuffling belongs in an explicitly
        versioned challenger, never in the production teacher loader.
        """
        require(shuffle_seed is None, "shuffle_seed_not_supported_in_teacher_store_v1")
        audit = ParseAudit()
        audit.event("outer_fit_candidate_allowlist_received")
        frozen: dict[str, tuple[str, str]] = {}
        for raw_candidate, raw_value in allowed_candidates.items():
            candidate_id = str(raw_candidate)
            require(candidate_id and candidate_id not in frozen, f"allowed_candidate_duplicate:{candidate_id}")
            require(isinstance(raw_value, (tuple, list)) and len(raw_value) == 2,
                    f"allowed_candidate_value:{candidate_id}")
            sequence_sha256, parent = (str(raw_value[0]), str(raw_value[1]))
            require(len(sequence_sha256) == 64 and parent, f"allowed_candidate_identity:{candidate_id}")
            frozen[candidate_id] = (sequence_sha256, parent)
        require(frozen, "allowed_candidates_empty")
        parents = frozenset(parent for _, parent in frozen.values())
        canonical = json.dumps(
            [[candidate_id, *frozen[candidate_id]] for candidate_id in sorted(frozen)],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        split = ParentSplit(
            fit_parents=parents,
            score_parents=frozenset(),
            split_id="CALLER_FROZEN_OUTER_FIT_CANDIDATE_ALLOWLIST",
            fold_id=-1,
            source_path=Path("<in-memory-allowed-candidates>"),
            source_sha256=hashlib.sha256(canonical).hexdigest(),
        )
        audit.freeze_allowlist()
        config = TeacherStoreConfig(expected_scalar_candidates=max(len(frozen), 738))
        store = cls(split, config, audit)
        store._release_allowlist_mode = True
        store._allowed_candidates = dict(frozen)
        store._allowed_sources = None if allowed_sources is None else frozenset(str(value) for value in allowed_sources)
        if store._allowed_sources is not None:
            require(store._allowed_sources and store._allowed_sources <= set(DEFAULT_SOURCE_COUNTS),
                    f"allowed_sources_invalid:{sorted(store._allowed_sources)}")
        for candidate_id, (sequence_sha256, parent) in frozen.items():
            store.scalar_identity[candidate_id] = CandidateIdentity(candidate_id, sequence_sha256, "", parent)
        store._audit.event("allowed_candidate_identity_strings_frozen_without_numeric_parse")
        store._load_package(Path(release_dir))
        store._finalize()
        return store

    @classmethod
    def from_paths(
        cls,
        *,
        outer_split_path: Path,
        scalar_identity_path: Path,
        teacher_package_dir: Path,
        config: TeacherStoreConfig | None = None,
    ) -> "ContactTeacherStore":
        audit = ParseAudit()
        split = load_parent_split(outer_split_path, audit)
        store = cls(split, config or TeacherStoreConfig(), audit)
        store._load_scalar_identity(scalar_identity_path)
        store._load_package(teacher_package_dir)
        store._finalize()
        return store

    def _load_scalar_identity(self, path: Path) -> None:
        self._audit.event("scalar_identity_table_open")
        required = {"candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster"}
        for row in _rows(path, required, "scalar_identity"):
            candidate_id = row["candidate_id"]
            require(candidate_id and candidate_id not in self.scalar_identity, f"scalar_identity_duplicate:{candidate_id}")
            parent = row["parent_framework_cluster"]
            require(parent in self.split.fit_parents or parent in self.split.score_parents,
                    f"scalar_parent_not_in_outer_split:{candidate_id}:{parent}")
            identity = CandidateIdentity(candidate_id, row["sequence_sha256"], row["sequence"], parent)
            require(len(identity.sequence_sha256) == 64 and identity.sequence, f"scalar_identity_invalid:{candidate_id}")
            self.scalar_identity[candidate_id] = identity
        require(len(self.scalar_identity) == self.config.expected_scalar_candidates,
                f"scalar_candidate_count:{len(self.scalar_identity)}")
        self._audit.event("scalar_identity_loaded_without_numeric_payload_parse")

    def _load_package(self, directory: Path) -> None:
        require(directory.is_dir() and not directory.is_symlink(), f"teacher_package_invalid:{directory}")
        self._audit.event("train_only_teacher_package_open")
        receipt_path = directory / RECEIPT_NAME
        access_path = directory / ACCESS_AUDIT_NAME
        _regular_file(receipt_path, "teacher_receipt")
        _regular_file(access_path, "teacher_access_audit")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        access = json.loads(access_path.read_text(encoding="utf-8"))
        require(receipt.get("status") == self.config.package_status, "teacher_receipt_status")
        require(receipt.get("oof_training_authorized") is False, "phase0_receipt_oof_authority_drift")
        require(access.get("status") == "PASS_SPLIT_BEFORE_ACCESS_TRAIN_ONLY", "teacher_access_audit_status")
        for name in (
            "development_pose_files_stat_hashed_opened",
            "frozen_test_pose_files_stat_hashed_opened",
            "quarantine_pose_files_stat_hashed_opened",
            "unknown_pose_files_stat_hashed_opened",
            "forbidden_pose_attempt_count",
        ):
            require(int(access.get(name, -1)) == 0, f"teacher_access_boundary_nonzero:{name}")
        counts = receipt.get("counts") or {}
        require(int(counts.get("candidates", -1)) == self.config.expected_teacher_candidates,
                "teacher_receipt_candidate_count")
        require(int(counts.get("parents", -1)) == self.config.expected_teacher_parents,
                "teacher_receipt_parent_count")
        expected_outputs = dict(receipt.get("outputs") or {})
        for name in (MANIFEST_NAME, MARGINAL_NAME, PAIR_NAME, GROUP_NAME, NODE_CONTRACT_NAME, ACCESS_AUDIT_NAME):
            path = directory / name
            _regular_file(path, f"teacher_output_{name}")
            observed = sha256_file(path)
            require(expected_outputs.get(name) == observed, f"teacher_output_sha256:{name}")
            self.package_output_hashes[name] = observed
        self.package_receipt_sha256 = sha256_file(receipt_path)
        self._load_manifest(directory / MANIFEST_NAME)
        self._load_target_node_contract(directory / NODE_CONTRACT_NAME)
        self._load_group_audit(directory / GROUP_NAME)
        self._load_marginal(directory / MARGINAL_NAME)
        self._load_pair(directory / PAIR_NAME)

    def _role_for_parent(self, parent: str, candidate_id: str) -> str:
        if self._release_allowlist_mode:
            if candidate_id in self._allowed_candidates:
                require(self._allowed_candidates[candidate_id][1] == parent,
                        f"teacher_allowed_parent_mismatch:{candidate_id}:{parent}")
                return "fit"
            require(parent not in self.split.fit_parents,
                    f"teacher_candidate_missing_from_fit_allowlist_same_parent:{candidate_id}:{parent}")
            return "score"
        if parent in self.split.fit_parents:
            return "fit"
        if parent in self.split.score_parents:
            return "score"
        raise ContactTeacherStoreError(f"teacher_parent_not_in_outer_split:{candidate_id}:{parent}")

    def _load_manifest(self, path: Path) -> None:
        required = {
            "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster", "model_split",
            "teacher_source", "reliability_tier", "observed_seed_count", "observed_seed_ids",
        }
        source_counts: dict[str, int] = {}
        for row in _rows(path, required, "teacher_manifest"):
            candidate_id = row["candidate_id"]
            require(candidate_id not in self.teacher_metadata, f"teacher_manifest_duplicate:{candidate_id}")
            manifest_identity = CandidateIdentity(
                candidate_id, row["sequence_sha256"], row["sequence"], row["parent_framework_cluster"]
            )
            require(manifest_identity.sequence and len(manifest_identity.sequence_sha256) == 64,
                    f"teacher_manifest_identity_invalid:{candidate_id}")
            require(hashlib.sha256(manifest_identity.sequence.encode("utf-8")).hexdigest() ==
                    manifest_identity.sequence_sha256, f"teacher_manifest_sequence_hash:{candidate_id}")
            if self._release_allowlist_mode:
                if candidate_id in self.scalar_identity:
                    frozen = self.scalar_identity[candidate_id]
                    require((manifest_identity.sequence_sha256, manifest_identity.parent) ==
                            (frozen.sequence_sha256, frozen.parent),
                            f"teacher_allowed_identity_mismatch:{candidate_id}")
                    self.scalar_identity[candidate_id] = manifest_identity
                scalar = manifest_identity
            else:
                require(candidate_id in self.scalar_identity, f"teacher_candidate_not_scalar:{candidate_id}")
                scalar = self.scalar_identity[candidate_id]
                require((manifest_identity.sequence_sha256, manifest_identity.sequence, manifest_identity.parent) ==
                        (scalar.sequence_sha256, scalar.sequence, scalar.parent),
                        f"teacher_scalar_identity_mismatch:{candidate_id}")
            require(row["model_split"] == "train", f"teacher_manifest_nontrain:{candidate_id}")
            role = self._role_for_parent(scalar.parent, candidate_id)
            if role == "fit" and self._allowed_sources is not None and row["teacher_source"] not in self._allowed_sources:
                role = "source_excluded"
            tier = row["reliability_tier"]
            require(tier in TIER_WEIGHTS, f"teacher_reliability_tier:{candidate_id}:{tier}")
            metadata = TeacherMetadata(
                scalar, row["teacher_source"], tier, row["observed_seed_count"], row["observed_seed_ids"], role,
            )
            if role == "fit":
                observed = self._audit.integer(row["observed_seed_count"], role="fit", label="manifest_seed_count")
                require(observed == (3 if tier == "3_SEED" else 2), f"manifest_tier_seed_mismatch:{candidate_id}")
                require(len([value for value in row["observed_seed_ids"].split(",") if value]) == observed,
                        f"manifest_seed_id_count:{candidate_id}")
            elif role == "score":
                self._audit.skip_score("manifest")
            else:
                self._audit.skip_source("manifest")
            self.teacher_metadata[candidate_id] = metadata
            source_counts[metadata.teacher_source] = source_counts.get(metadata.teacher_source, 0) + 1
        require(len(self.teacher_metadata) == self.config.expected_teacher_candidates,
                f"teacher_manifest_candidate_count:{len(self.teacher_metadata)}")
        parents = {value.identity.parent for value in self.teacher_metadata.values()}
        require(len(parents) == self.config.expected_teacher_parents, f"teacher_manifest_parent_count:{len(parents)}")
        if self.config.expected_source_counts is not None:
            require(source_counts == dict(self.config.expected_source_counts), f"teacher_source_counts:{source_counts}")

    def _load_target_node_contract(self, path: Path) -> None:
        required = {"receptor", "pvrig_node_index", "pvrig_uniprot_position", "pvrig_aa"}
        for row in _rows(path, required, "target_node_contract"):
            receptor = row["receptor"].lower()
            require(receptor in RECEPTORS, f"target_node_receptor:{receptor}")
            index = self._audit.integer(row["pvrig_node_index"], role="label_free", label="pvrig_node_index")
            position = self._audit.integer(row["pvrig_uniprot_position"], role="label_free", label="pvrig_position")
            require(index not in self.target_node_identity[receptor], f"target_node_duplicate:{receptor}:{index}")
            self.target_node_identity[receptor][index] = (position, row["pvrig_aa"])
        for receptor in RECEPTORS:
            expected = int(self.config.target_nodes[receptor])
            require(set(self.target_node_identity[receptor]) == set(range(1, expected + 1)),
                    f"target_node_index_closure:{receptor}")

    def _identity_and_role(self, row: Mapping[str, str], stream: str) -> tuple[TeacherMetadata, str]:
        candidate_id = row.get("candidate_id", "")
        require(candidate_id in self.teacher_metadata, f"{stream}_unknown_candidate:{candidate_id}")
        metadata = self.teacher_metadata[candidate_id]
        identity = metadata.identity
        require(row.get("sequence_sha256") == identity.sequence_sha256, f"{stream}_sequence_sha256:{candidate_id}")
        require(row.get("parent_framework_cluster") == identity.parent, f"{stream}_parent:{candidate_id}")
        if "teacher_source" in row:
            require(row.get("teacher_source") == metadata.teacher_source, f"{stream}_source:{candidate_id}")
        if "reliability_tier" in row:
            require(row.get("reliability_tier") == metadata.reliability_tier, f"{stream}_tier:{candidate_id}")
        return metadata, metadata.role

    def _load_group_audit(self, path: Path) -> None:
        required = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier",
            "receptor", "observed_seed_count", "sequence_length", "target_node_count",
            "dense_pair_universe_size", "sparse_nonzero_pair_rows", "dense_marginal_rows",
            "technical_failure_zero_imputations", "pair_table_semantics",
        }
        for row in _rows(path, required, "group_audit"):
            metadata, role = self._identity_and_role(row, "group_audit")
            if role == "score":
                self._audit.skip_score("group_audit")
                continue
            if role == "source_excluded":
                self._audit.skip_source("group_audit")
                continue
            receptor = row["receptor"].lower()
            require(receptor in RECEPTORS, f"group_receptor:{receptor}")
            key = (metadata.identity.candidate_id, receptor)
            require(key not in self.groups, f"group_duplicate:{key}")
            length = self._audit.integer(row["sequence_length"], role="fit", label="group_sequence_length")
            nodes = self._audit.integer(row["target_node_count"], role="fit", label="group_target_nodes")
            dense_pairs = self._audit.integer(row["dense_pair_universe_size"], role="fit", label="group_dense_pairs")
            sparse_rows = self._audit.integer(row["sparse_nonzero_pair_rows"], role="fit", label="group_sparse_rows")
            dense_marginal = self._audit.integer(row["dense_marginal_rows"], role="fit", label="group_dense_marginal")
            failures = self._audit.integer(row["technical_failure_zero_imputations"], role="fit", label="group_failures")
            observed = self._audit.integer(row["observed_seed_count"], role="fit", label="group_seed_count")
            expected_observed = self._audit.integer(
                metadata.observed_seed_count_text, role="fit", label="metadata_seed_count_recheck"
            )
            require(observed == expected_observed, f"group_seed_count_mismatch:{key}")
            require(length == len(metadata.identity.sequence), f"group_sequence_length_mismatch:{key}")
            require(nodes == int(self.config.target_nodes[receptor]), f"group_target_node_count:{key}:{nodes}")
            require(dense_pairs == length * nodes, f"group_dense_pair_universe:{key}")
            require(dense_marginal == length, f"group_dense_marginal_rows:{key}")
            require(row["pair_table_semantics"] == PAIR_SEMANTICS, f"group_pair_semantics:{key}")
            valid = failures == 0
            self.groups[key] = GroupTeacher(
                receptor=receptor,
                sequence_length=length,
                target_node_count=nodes,
                valid=valid,
                technical_na_reason=None if valid else "TECHNICAL_FAILURE_NA",
                expected_sparse_rows=sparse_rows,
                marginal_target=np.zeros(length, dtype=np.float32),
                marginal_uncertainty=np.ones(length, dtype=np.float32),
                marginal_mask=np.zeros(length, dtype=np.bool_),
                marginal_seen=np.zeros(length, dtype=np.bool_),
                pair_target=np.zeros((length, nodes), dtype=np.float32),
                pair_uncertainty=np.ones((length, nodes), dtype=np.float32),
                pair_mask=np.full((length, nodes), valid, dtype=np.bool_),
            )
        expected = {
            (candidate_id, receptor)
            for candidate_id, metadata in self.teacher_metadata.items()
            if metadata.role == "fit"
            for receptor in RECEPTORS
        }
        require(set(self.groups) == expected, "fit_candidate_receptor_group_closure")

    def _load_marginal(self, path: Path) -> None:
        required = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier",
            "receptor", "observed_seed_count", "vhh_sequence_index", "vhh_aa", "vhh_region",
            "contact_marginal_mean", "contact_marginal_variance", "contact_marginal_uncertainty_weight",
            "target_mask",
        }
        for row in _rows(path, required, "marginal_teacher"):
            metadata, role = self._identity_and_role(row, "marginal_teacher")
            if role == "score":
                self._audit.skip_score("marginal_teacher")
                continue
            if role == "source_excluded":
                self._audit.skip_source("marginal_teacher")
                continue
            receptor = row["receptor"].lower()
            key = (metadata.identity.candidate_id, receptor)
            require(key in self.groups, f"marginal_group_missing:{key}")
            group = self.groups[key]
            if not group.valid:
                self._audit.skip_technical_na("marginal_teacher")
                continue
            index = self._audit.integer(row["vhh_sequence_index"], role="fit", label="marginal_sequence_index") - 1
            require(0 <= index < group.sequence_length, f"marginal_sequence_index:{key}:{index+1}")
            require(not bool(group.marginal_seen[index]), f"marginal_duplicate:{key}:{index+1}")
            require(row["vhh_aa"] == metadata.identity.sequence[index], f"marginal_vhh_aa:{key}:{index+1}")
            mask = self._audit.integer(row["target_mask"], role="fit", label="marginal_target_mask")
            require(mask == 1, f"valid_group_marginal_mask_zero:{key}:{index+1}")
            observed = self._audit.integer(row["observed_seed_count"], role="fit", label="marginal_seed_count")
            require(observed == (3 if metadata.reliability_tier == "3_SEED" else 2),
                    f"marginal_seed_count_mismatch:{key}")
            target = self._audit.floating(row["contact_marginal_mean"], role="fit", label="marginal_mean")
            variance = self._audit.floating(row["contact_marginal_variance"], role="fit", label="marginal_variance")
            uncertainty = self._audit.floating(
                row["contact_marginal_uncertainty_weight"], role="fit", label="marginal_uncertainty"
            )
            require(0.0 <= target <= 1.0 and variance >= 0.0 and 0.0 < uncertainty <= 1.0,
                    f"marginal_numeric_range:{key}:{index+1}")
            require(abs(uncertainty - 1.0 / (1.0 + 4.0 * variance)) <= 2e-5,
                    f"marginal_uncertainty_formula:{key}:{index+1}")
            group.marginal_target[index] = target
            group.marginal_uncertainty[index] = uncertainty
            group.marginal_mask[index] = True
            group.marginal_seen[index] = True

    def _load_pair(self, path: Path) -> None:
        required = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier",
            "receptor", "observed_seed_count", "vhh_sequence_index", "vhh_aa", "vhh_region",
            "pvrig_node_index", "pvrig_uniprot_position", "pvrig_aa", "contact_target_mean",
            "contact_target_variance", "contact_uncertainty_weight", "pair_table_semantics", "target_mask",
        }
        for row in _rows(path, required, "pair_teacher"):
            metadata, role = self._identity_and_role(row, "pair_teacher")
            if role == "score":
                self._audit.skip_score("pair_teacher")
                continue
            if role == "source_excluded":
                self._audit.skip_source("pair_teacher")
                continue
            receptor = row["receptor"].lower()
            key = (metadata.identity.candidate_id, receptor)
            require(key in self.groups, f"pair_group_missing:{key}")
            group = self.groups[key]
            if not group.valid:
                self._audit.skip_technical_na("pair_teacher")
                continue
            require(row["pair_table_semantics"] == PAIR_SEMANTICS, f"pair_semantics:{key}")
            vhh_index = self._audit.integer(row["vhh_sequence_index"], role="fit", label="pair_vhh_index") - 1
            node_index = self._audit.integer(row["pvrig_node_index"], role="fit", label="pair_node_index") - 1
            require(0 <= vhh_index < group.sequence_length, f"pair_vhh_index:{key}:{vhh_index+1}")
            require(0 <= node_index < group.target_node_count, f"pair_node_index:{key}:{node_index+1}")
            require((vhh_index, node_index) not in group.sparse_seen, f"pair_duplicate:{key}:{vhh_index+1}:{node_index+1}")
            require(row["vhh_aa"] == metadata.identity.sequence[vhh_index], f"pair_vhh_aa:{key}:{vhh_index+1}")
            node_identity = self.target_node_identity[receptor][node_index + 1]
            position = self._audit.integer(row["pvrig_uniprot_position"], role="fit", label="pair_uniprot_position")
            require((position, row["pvrig_aa"]) == node_identity,
                    f"pair_target_node_identity:{key}:{node_index+1}")
            require(self._audit.integer(row["target_mask"], role="fit", label="pair_target_mask") == 1,
                    f"pair_valid_mask_zero:{key}:{vhh_index+1}:{node_index+1}")
            observed = self._audit.integer(row["observed_seed_count"], role="fit", label="pair_seed_count")
            require(observed == (3 if metadata.reliability_tier == "3_SEED" else 2),
                    f"pair_seed_count_mismatch:{key}")
            target = self._audit.floating(row["contact_target_mean"], role="fit", label="pair_target")
            variance = self._audit.floating(row["contact_target_variance"], role="fit", label="pair_variance")
            uncertainty = self._audit.floating(
                row["contact_uncertainty_weight"], role="fit", label="pair_uncertainty"
            )
            require(0.0 < target <= 1.0 and variance >= 0.0 and 0.0 < uncertainty <= 1.0,
                    f"pair_numeric_range:{key}:{vhh_index+1}:{node_index+1}")
            require(abs(uncertainty - 1.0 / (1.0 + 4.0 * variance)) <= 2e-5,
                    f"pair_uncertainty_formula:{key}:{vhh_index+1}:{node_index+1}")
            group.pair_target[vhh_index, node_index] = target
            group.pair_uncertainty[vhh_index, node_index] = uncertainty
            group.sparse_seen.add((vhh_index, node_index))

    def _finalize(self) -> None:
        for key, group in self.groups.items():
            if not group.valid:
                require(not bool(np.any(group.marginal_mask)) and not bool(np.any(group.pair_mask)),
                        f"technical_na_mask_nonzero:{key}")
                continue
            require(bool(np.all(group.marginal_seen)) and bool(np.all(group.marginal_mask)),
                    f"marginal_sequence_index_closure:{key}")
            require(len(group.sparse_seen) == group.expected_sparse_rows,
                    f"sparse_pair_row_count:{key}:{len(group.sparse_seen)}:{group.expected_sparse_rows}")
            require(group.pair_target.shape == group.pair_mask.shape == group.pair_uncertainty.shape,
                    f"pair_dense_shape:{key}")
            require(bool(np.all(group.pair_mask)), f"pair_dense_zero_universe_mask_closure:{key}")
            absent = group.pair_target == 0.0
            require(bool(np.all(group.pair_uncertainty[absent] == 1.0)), f"pair_absent_zero_uncertainty:{key}")
        require(self._audit.numeric_float_parses["score"] == 0, "score_parent_float_parse_nonzero")
        require(self._audit.numeric_int_parses["score"] == 0, "score_parent_integer_parse_nonzero")
        self._audit.event("contact_teacher_store_finalized")

    @staticmethod
    def _selected_value(row: Any, *names: str) -> str:
        for name in names:
            if isinstance(row, Mapping) and name in row:
                return str(row[name])
            if hasattr(row, name):
                return str(getattr(row, name))
        raise ContactTeacherStoreError(f"selected_row_field_missing:{'/'.join(names)}")

    def _build_batch_tensors(
        self,
        candidate_ids: Sequence[str],
        sequences: Sequence[str],
        token_positions: Sequence[Sequence[int] | Tensor],
        *,
        token_width: int,
    ) -> dict[str, Tensor]:
        require(len(candidate_ids) == len(sequences) == len(token_positions),
                "batch_candidate_sequence_position_length")
        require(token_width > 0, "token_width_invalid")
        batch_size = len(candidate_ids)
        marginal_target = torch.zeros((batch_size, token_width, 2), dtype=torch.float32)
        marginal_uncertainty = torch.ones_like(marginal_target)
        marginal_mask = torch.zeros_like(marginal_target, dtype=torch.bool)
        pair_target = {
            receptor: torch.zeros(
                (batch_size, token_width, int(self.config.target_nodes[receptor])), dtype=torch.float32
            )
            for receptor in RECEPTORS
        }
        pair_uncertainty = {receptor: torch.ones_like(pair_target[receptor]) for receptor in RECEPTORS}
        pair_mask = {receptor: torch.zeros_like(pair_target[receptor], dtype=torch.bool) for receptor in RECEPTORS}
        marginal_tier = torch.zeros(batch_size, dtype=torch.float32)
        pair_tier = torch.zeros(batch_size, dtype=torch.float32)

        for item, (candidate_id, sequence, raw_positions) in enumerate(
            zip(candidate_ids, sequences, token_positions, strict=True)
        ):
            positions = raw_positions.detach().cpu().tolist() if isinstance(raw_positions, Tensor) else list(raw_positions)
            positions = [int(value) for value in positions]
            require(len(positions) == len(sequence), f"batch_token_sequence_length:{candidate_id}")
            require(len(set(positions)) == len(positions), f"batch_token_position_duplicate:{candidate_id}")
            require(all(0 <= value < token_width for value in positions), f"batch_token_position_range:{candidate_id}")
            metadata = self.teacher_metadata.get(candidate_id)
            if metadata is None or metadata.role != "fit":
                continue
            require(metadata.identity.sequence == sequence, f"batch_teacher_sequence_mismatch:{candidate_id}")
            any_valid = False
            columns = torch.tensor(positions, dtype=torch.long)
            for receptor_index, receptor in enumerate(RECEPTORS):
                group = self.groups[(candidate_id, receptor)]
                if not group.valid:
                    continue
                any_valid = True
                marginal_target[item, columns, receptor_index] = torch.from_numpy(group.marginal_target)
                marginal_uncertainty[item, columns, receptor_index] = torch.from_numpy(group.marginal_uncertainty)
                marginal_mask[item, columns, receptor_index] = torch.from_numpy(group.marginal_mask)
                pair_target[receptor][item, columns, :] = torch.from_numpy(group.pair_target)
                pair_uncertainty[receptor][item, columns, :] = torch.from_numpy(group.pair_uncertainty)
                pair_mask[receptor][item, columns, :] = torch.from_numpy(group.pair_mask)
            if any_valid:
                marginal_tier[item] = metadata.tier_weight
                pair_tier[item] = metadata.tier_weight

        return {
            "marginal_targets": marginal_target,
            "marginal_uncertainty": marginal_uncertainty,
            "marginal_mask": marginal_mask,
            "marginal_tier_weights": marginal_tier,
            "pair_targets_8x6b": pair_target["8x6b"],
            "pair_uncertainty_8x6b": pair_uncertainty["8x6b"],
            "pair_mask_8x6b": pair_mask["8x6b"],
            "pair_targets_9e6y": pair_target["9e6y"],
            "pair_uncertainty_9e6y": pair_uncertainty["9e6y"],
            "pair_mask_9e6y": pair_mask["9e6y"],
            "pair_tier_weights": pair_tier,
        }

    def v25_batch_tensors(
        self,
        candidate_ids: Sequence[str],
        token_positions: Sequence[Sequence[int] | Tensor],
        *,
        token_width: int,
    ) -> dict[str, Tensor]:
        """Return the exact contact-label keys consumed by the frozen V2.5 trainer."""
        sequences: list[str] = []
        for candidate_id in candidate_ids:
            require(candidate_id in self.scalar_identity, f"batch_candidate_unknown:{candidate_id}")
            sequences.append(self.scalar_identity[candidate_id].sequence)
        return self._build_batch_tensors(candidate_ids, sequences, token_positions, token_width=token_width)

    def augment_batch(
        self,
        batch: Mapping[str, Any],
        selected_rows: Sequence[Any],
        residue_mask: Tensor | np.ndarray,
    ) -> dict[str, Any]:
        """Return a copy of ``batch`` augmented only with V2.5 label tensors.

        Candidate/parent/source identifiers are used solely for integrity and
        mask decisions.  They are not included in the returned contact tensor
        dictionary and therefore cannot become neural forward features.
        """
        mask = residue_mask if isinstance(residue_mask, Tensor) else torch.as_tensor(residue_mask)
        require(mask.ndim == 2, "residue_mask_rank")
        require(mask.shape[0] == len(selected_rows), "residue_mask_batch_size")
        mask = mask.to(dtype=torch.bool, device="cpu")
        candidate_ids: list[str] = []
        sequences: list[str] = []
        token_positions: list[list[int]] = []
        for item, row in enumerate(selected_rows):
            candidate_id = self._selected_value(row, "candidate_id")
            sequence = self._selected_value(row, "sequence")
            sequence_sha256 = self._selected_value(row, "sequence_sha256")
            parent = self._selected_value(row, "parent", "parent_framework_cluster")
            require(hashlib.sha256(sequence.encode("utf-8")).hexdigest() == sequence_sha256,
                    f"selected_row_sequence_hash:{candidate_id}")
            if candidate_id in self._allowed_candidates:
                require((sequence_sha256, parent) == self._allowed_candidates[candidate_id],
                        f"selected_row_frozen_identity:{candidate_id}")
            positions = torch.nonzero(mask[item], as_tuple=False).flatten().tolist()
            require(len(positions) == len(sequence), f"residue_mask_sequence_closure:{candidate_id}")
            candidate_ids.append(candidate_id)
            sequences.append(sequence)
            token_positions.append([int(value) for value in positions])
        labels = self._build_batch_tensors(
            candidate_ids,
            sequences,
            token_positions,
            token_width=int(mask.shape[1]),
        )
        result = dict(batch)
        result.update(labels)
        return result

    def audit_report(self) -> dict[str, Any]:
        fit_candidates = [value for value in self.teacher_metadata.values() if value.role == "fit"]
        score_candidates = [value for value in self.teacher_metadata.values() if value.role == "score"]
        source_excluded = [value for value in self.teacher_metadata.values() if value.role == "source_excluded"]
        valid_groups = sum(group.valid for group in self.groups.values())
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_OUTER_FIT_ONLY_CONTACT_TEACHER_STORE",
            "split": {
                "split_id": self.split.split_id,
                "fold_id": self.split.fold_id,
                "sha256": self.split.source_sha256,
                "fit_parents": len(self.split.fit_parents),
                "score_parents": len(self.split.score_parents),
            },
            "counts": {
                "scalar_candidates": len(self.scalar_identity),
                "teacher_candidates_total": len(self.teacher_metadata),
                "fit_teacher_candidates": len(fit_candidates),
                "score_teacher_candidates_numeric_excluded": len(score_candidates),
                "source_excluded_teacher_candidates": len(source_excluded),
                "fit_candidate_receptor_groups": len(self.groups),
                "valid_groups": valid_groups,
                "technical_na_groups": len(self.groups) - valid_groups,
            },
            "access_order": list(self._audit.events),
            "allowlist_frozen_before_numeric_parse": self._audit.allowlist_frozen,
            "numeric_int_parses": dict(self._audit.numeric_int_parses),
            "numeric_float_parses": dict(self._audit.numeric_float_parses),
            "score_parent_numeric_int_parse_count": self._audit.numeric_int_parses["score"],
            "score_parent_numeric_float_parse_count": self._audit.numeric_float_parses["score"],
            "score_rows_skipped_before_numeric_parse": dict(sorted(self._audit.score_rows_skipped_before_numeric_parse.items())),
            "source_rows_skipped_before_numeric_parse": dict(
                sorted(self._audit.source_rows_skipped_before_numeric_parse.items())
            ),
            "technical_na_rows_skipped": dict(sorted(self._audit.technical_na_rows_skipped.items())),
            "target_nodes": dict(self.config.target_nodes),
            "tier_weights": dict(TIER_WEIGHTS),
            "package_receipt_sha256": self.package_receipt_sha256,
            "package_output_hashes": dict(sorted(self.package_output_hashes.items())),
            "claim_boundary": (
                "Outer-fit-only computational Docking residue-contact weak supervision; not binding, affinity, "
                "experimental blocking, Docking Gold, or a neural forward feature."
            ),
        }

    @property
    def audit(self) -> dict[str, Any]:
        """Immutable-by-copy public audit surface expected by V2.20 runners."""
        return self.audit_report()
