#!/usr/bin/env python3
"""Freeze label-free V4-F predictions from completed V4-D surrogate artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.abc
import importlib.util
import io
import json
import math
import os
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
_SELF_SOURCE_PATH = Path(__file__).resolve()
_SELF_SOURCE_PAYLOAD = _SELF_SOURCE_PATH.read_bytes()
_SELF_COMPILED_CODE = compile(
    _SELF_SOURCE_PAYLOAD,
    sys._getframe().f_code.co_filename,
    "exec",
    dont_inherit=True,
    optimize=sys.flags.optimize,
)


def _code_fingerprint(code: Any) -> str:
    digest = hashlib.sha256()

    def update_value(value: Any) -> None:
        digest.update(type(value).__name__.encode("ascii"))
        digest.update(b"\0")
        if isinstance(value, bytes):
            digest.update(str(len(value)).encode("ascii"))
            digest.update(b":")
            digest.update(value)
        elif isinstance(value, (tuple, list)):
            digest.update(str(len(value)).encode("ascii"))
            digest.update(b"[")
            for item in value:
                update_value(item)
            digest.update(b"]")
        elif isinstance(value, (set, frozenset)):
            rendered = sorted(repr(item) for item in value)
            update_value(tuple(rendered))
        else:
            digest.update(repr(value).encode("utf-8"))
        digest.update(b"\0")

    attributes = (
        "co_argcount",
        "co_posonlyargcount",
        "co_kwonlyargcount",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_names",
        "co_varnames",
        "co_freevars",
        "co_cellvars",
        "co_filename",
        "co_name",
        "co_firstlineno",
        "co_lnotab",
        "co_linetable",
        "co_exceptiontable",
    )
    for attribute in attributes:
        if hasattr(code, attribute):
            digest.update(attribute.encode("ascii"))
            update_value(getattr(code, attribute))
    for constant in code.co_consts:
        if isinstance(constant, type(code)):
            digest.update(b"CODE")
            digest.update(bytes.fromhex(_code_fingerprint(constant)))
        else:
            digest.update(b"CONST")
            update_value(constant)
    return digest.hexdigest()


if _code_fingerprint(_SELF_COMPILED_CODE) != _code_fingerprint(
    sys._getframe().f_code
):
    raise RuntimeError("v4f_freezer_source_does_not_match_executing_module")
del _SELF_COMPILED_CODE

_EXECUTION_DEPENDENCY_FILES = {
    "train_phase2_v4_d_surrogate": SCRIPT_DIR / "train_phase2_v4_d_surrogate.py",
    "train_phase2_v4_d_frozen_embedding_surrogate": SCRIPT_DIR
    / "train_phase2_v4_d_frozen_embedding_surrogate.py",
    "train_phase2_v4_d_contact_feature_surrogate": SCRIPT_DIR
    / "train_phase2_v4_d_contact_feature_surrogate.py",
    "extract_pvrig_v2_3_residue_contact_features": SCRIPT_DIR
    / "extract_pvrig_v2_3_residue_contact_features.py",
    "score_pvrig_candidates_v2_3": SCRIPT_DIR / "score_pvrig_candidates_v2_3.py",
    "train_phase2_v2_3": SCRIPT_DIR / "train_phase2_v2_3.py",
}
_EXECUTION_DEPENDENCY_PAYLOADS = {
    name: path.resolve().read_bytes()
    for name, path in _EXECUTION_DEPENDENCY_FILES.items()
}


class _CapturedSourceLoader(importlib.abc.Loader):
    """Execute local dependencies from the exact bytes captured before import."""

    def __init__(self, fullname: str, path: Path, payload: bytes) -> None:
        self.fullname = fullname
        self.path = path.resolve()
        self.payload = payload
        self.sha256 = hashlib.sha256(payload).hexdigest()

    def create_module(self, spec: Any) -> None:
        return None

    def exec_module(self, module: Any) -> None:
        module.__file__ = str(self.path)
        module.__v4f_executed_source_sha256__ = self.sha256
        code = compile(
            self.payload,
            str(self.path),
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
        exec(code, module.__dict__)


class _CapturedSourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: Any = None,
    ) -> Any:
        source_path = _EXECUTION_DEPENDENCY_FILES.get(fullname)
        if source_path is None:
            return None
        loader = _CapturedSourceLoader(
            fullname, source_path, _EXECUTION_DEPENDENCY_PAYLOADS[fullname]
        )
        return importlib.util.spec_from_loader(
            fullname, loader, origin=str(source_path.resolve()), is_package=False
        )


if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
for _module_name in _EXECUTION_DEPENDENCY_FILES:
    sys.modules.pop(_module_name, None)
_captured_source_finder = _CapturedSourceFinder()
sys.meta_path.insert(0, _captured_source_finder)
try:
    import train_phase2_v4_d_contact_feature_surrogate as contact  # noqa: E402
    import train_phase2_v4_d_frozen_embedding_surrogate as embedding  # noqa: E402
    import train_phase2_v4_d_surrogate as base  # noqa: E402
finally:
    sys.meta_path.remove(_captured_source_finder)
for _module_name, _payload in _EXECUTION_DEPENDENCY_PAYLOADS.items():
    _loaded_module = sys.modules.get(_module_name)
    if _loaded_module is None or getattr(
        _loaded_module, "__v4f_executed_source_sha256__", None
    ) != hashlib.sha256(_payload).hexdigest():
        raise RuntimeError(f"v4f_dependency_not_loaded_from_captured_source:{_module_name}")

_EXECUTION_SOURCE_PAYLOADS = {
    _SELF_SOURCE_PATH: _SELF_SOURCE_PAYLOAD,
    **{
        _EXECUTION_DEPENDENCY_FILES[name].resolve(): payload
        for name, payload in _EXECUTION_DEPENDENCY_PAYLOADS.items()
    },
}


SCHEMA_VERSION = "phase2_v4_f_frozen_surrogate_predictions_v1"
MODEL_SPLIT = "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"
EXPECTED_MANIFEST_SHA256 = "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334"
EXPECTED_AUDIT_SHA256 = "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1"
EXPECTED_MANIFEST_RECEIPT_SHA256 = (
    "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f"
)
EXPECTED_CONTACT_FEATURE_RECEIPT_SHA256 = (
    "b12c0ff0ce6760db7169ec3616dddaf05786e5ca795354f639ef2bf87c370e2b"
)
EXPECTED_ROW_COUNT = 96
OUTPUT_FILENAMES = (
    "v4_f_96_frozen_surrogate_predictions.tsv",
    "v4_f_96_frozen_surrogate_predictions.audit.json",
    "v4_f_96_frozen_surrogate_predictions.receipt.json",
)
FORBIDDEN_MANIFEST_FIELDS = {
    "R_dual_min",
    "target_R_dual_min",
    "geometry_tier",
    "consensus_geometry_tier",
    "docking_label",
    "experimental_blocking",
}
FORBIDDEN_OUTPUT_FIELDS = {
    "R_dual_min",
    "target_R_dual_min",
    "geometry_tier",
    "consensus_geometry_tier",
    "docking_label",
    "experimental_blocking",
}
IDENTITY_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "model_split",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr3_length",
)
PREDICTION_FIELDS = IDENTITY_FIELDS + (
    "base_selected_model",
    "base_predicted_geometry_score",
    "base_prediction_uncertainty",
    "embedding_selected_model",
    "embedding_predicted_geometry_score",
    "embedding_prediction_uncertainty",
    "contact_selected_model",
    "contact_predicted_geometry_score",
    "contact_prediction_uncertainty",
)
CLAIM_BOUNDARY = (
    "Frozen label-free predictions of fixed dual-Docking computational geometry for the "
    "prospective V4-F panel; not binding, affinity, competition, Docking Gold, or "
    "experimental blocking truth."
)
PRODUCTION_ROOT = SCRIPT_DIR.parent.resolve()
PRODUCTION_PATHS = {
    "manifest": PRODUCTION_ROOT / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
    "manifest_audit": PRODUCTION_ROOT / "data_splits/pvrig_v4_f/prospective_holdout96_audit.json",
    "manifest_receipt": PRODUCTION_ROOT / "data_splits/pvrig_v4_f/prospective_holdout96_receipt.json",
    "base_out": PRODUCTION_ROOT / "runs/pvrig_v4_d_sequence_surrogate_v1",
    "embedding_out": PRODUCTION_ROOT / "runs/pvrig_v4_d_frozen_embedding_surrogate_v1",
    "contact_out": PRODUCTION_ROOT / "runs/pvrig_v4_d_contact_fusion_surrogate_v1",
    "embedding_manifest": PRODUCTION_ROOT
    / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_manifest_v3.csv",
    "embedding_summary": PRODUCTION_ROOT
    / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_summary_v3.json",
    "embedding_sequence_manifest": PRODUCTION_ROOT
    / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/sequence_manifest_v3.csv",
    "contact_receipt": PRODUCTION_ROOT
    / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
    "contact_schema": PRODUCTION_ROOT / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
    "out_dir": PRODUCTION_ROOT / "predictions/pvrig_v4_f_surrogate_predictions_v1",
}
PRIMARY_EVALUATION_POLICY = {
    "schema_version": "phase2_v4_f_primary_evaluation_policy_v1",
    "primary_model_family": "contact",
    "primary_prediction_column": "contact_predicted_geometry_score",
    "primary_uncertainty_column": "contact_prediction_uncertainty",
    "primary_model_selection": (
        "use the contact-stage selected_candidate_model frozen on OPEN_DEVELOPMENT; "
        "no post-Docking family switching or ensemble reweighting"
    ),
    "primary_endpoint": "continuous independent-dual-receptor R_dual_min",
    "endpoint_direction": "higher_is_better",
    "primary_metric": "spearman",
    "secondary_metrics": ["ndcg", "top_quartile_recall_at_20pct_budget", "mae"],
    "resampling_unit": "parent_framework_cluster",
    "confidence_interval": "two-sided parent-cluster bootstrap 95 percent CI",
    "multiplicity_policy": (
        "single preregistered contact-family primary test; base and embedding families "
        "are descriptive secondary analyses only"
    ),
    "tie_break": "candidate_id ascending after exact score and uncertainty ties",
    "full_qc_attrition": (
        "report all Full-QC failures; evaluate the primary endpoint only for the frozen "
        "policy-defined Docking set without replacement or score-based substitution"
    ),
    "forbidden_after_unseal": [
        "switch primary model family",
        "change endpoint or direction",
        "change metric hierarchy",
        "tune weights or thresholds on V4-F Docking labels",
    ],
}
class PredictionFreezeError(RuntimeError):
    pass


class WaitingForSurrogates(PredictionFreezeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


PRIMARY_EVALUATION_POLICY_SHA256 = sha256_json(PRIMARY_EVALUATION_POLICY)


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    payload: bytes
    sha256: str


class SnapshotRegistry:
    """Read each input path once and retain the exact bytes consumed by replay."""

    def __init__(self) -> None:
        self._snapshots: dict[Path, FileSnapshot] = {}

    def take(self, path: Path, label: str, *, waiting: bool = False) -> FileSnapshot:
        resolved = path.resolve()
        cached = self._snapshots.get(resolved)
        if cached is not None:
            return cached
        try:
            with resolved.open("rb") as handle:
                payload = handle.read()
        except OSError as exc:
            error = f"missing_or_unreadable:{label}:{resolved}"
            if waiting:
                raise WaitingForSurrogates(error) from exc
            raise PredictionFreezeError(error) from exc
        if not payload:
            error = f"missing_or_empty:{label}:{resolved}"
            if waiting:
                raise WaitingForSurrogates(error)
            raise PredictionFreezeError(error)
        snapshot = FileSnapshot(resolved, payload, hashlib.sha256(payload).hexdigest())
        self._snapshots[resolved] = snapshot
        return snapshot

    def seed(self, snapshot: FileSnapshot) -> None:
        resolved = snapshot.path.resolve()
        existing = self._snapshots.get(resolved)
        if existing is not None and existing != snapshot:
            raise PredictionFreezeError(f"snapshot_seed_conflict:{resolved}")
        self._snapshots[resolved] = snapshot

    def get(self, path: Path) -> FileSnapshot | None:
        return self._snapshots.get(path.resolve())

    def values(self) -> tuple[FileSnapshot, ...]:
        return tuple(self._snapshots.values())


def execution_source_snapshots() -> tuple[FileSnapshot, ...]:
    return tuple(
        FileSnapshot(path, payload, hashlib.sha256(payload).hexdigest())
        for path, payload in sorted(
            _EXECUTION_SOURCE_PAYLOADS.items(), key=lambda item: str(item[0])
        )
    )


def execution_source_hashes() -> dict[str, str]:
    return {
        str(snapshot.path): snapshot.sha256
        for snapshot in execution_source_snapshots()
    }


def verify_snapshots_current(
    snapshots: Sequence[FileSnapshot], label: str
) -> None:
    for snapshot in snapshots:
        try:
            metadata = snapshot.path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PredictionFreezeError(
                    f"{label}_not_regular:{snapshot.path}"
                )
            payload = snapshot.path.read_bytes()
        except OSError as exc:
            raise PredictionFreezeError(
                f"{label}_missing_or_unreadable:{snapshot.path}"
            ) from exc
        require(
            hashlib.sha256(payload).hexdigest() == snapshot.sha256,
            f"{label}_changed:{snapshot.path}",
        )


def verify_execution_sources_unchanged() -> None:
    verify_snapshots_current(
        execution_source_snapshots(), "executed_source"
    )


def snapshot_json(snapshot: FileSnapshot, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PredictionFreezeError(f"invalid_json:{label}:{snapshot.path}") from exc
    if not isinstance(payload, dict):
        raise PredictionFreezeError(f"json_not_object:{label}:{snapshot.path}")
    return payload


def snapshot_table(
    snapshot: FileSnapshot, delimiter: str
) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = snapshot.payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PredictionFreezeError(f"cannot_read_table:{snapshot.path}") from exc
    if not fields:
        raise PredictionFreezeError(f"table_header_missing:{snapshot.path}")
    return rows, fields


def load_json(path: Path, label: str) -> dict[str, Any]:
    registry = SnapshotRegistry()
    return snapshot_json(registry.take(path, label), label)


def read_table(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    registry = SnapshotRegistry()
    return snapshot_table(registry.take(path, "table"), delimiter)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PredictionFreezeError(message)


def execution_mode(test_only: bool) -> str:
    return "test_fixture" if test_only else "production"


def guard_execution_paths(args: argparse.Namespace, output_root: Path) -> None:
    supplied = {
        name: Path(getattr(args, name)).resolve()
        for name in (
            "manifest",
            "manifest_audit",
            "manifest_receipt",
            "base_out",
            "embedding_out",
            "contact_out",
            "embedding_manifest",
            "embedding_summary",
            "embedding_sequence_manifest",
            "contact_receipt",
            "contact_schema",
        )
    }
    supplied["out_dir"] = output_root.resolve()
    if args.test_only_allow_unfrozen_inputs:
        production_collisions = sorted(
            name for name, path in supplied.items() if path == PRODUCTION_PATHS[name].resolve()
        )
        require(
            not production_collisions,
            "test_only_mode_forbidden_on_production_paths:"
            + ",".join(production_collisions),
        )
        return
    require(args.expected_count == EXPECTED_ROW_COUNT, "production_expected_count_must_be_96")
    mismatches = sorted(
        name for name, path in supplied.items() if path != PRODUCTION_PATHS[name].resolve()
    )
    require(not mismatches, "production_path_contract_mismatch:" + ",".join(mismatches))


def input_entry(path: Path, sha256: str) -> dict[str, str]:
    require(len(sha256) == 64, f"invalid_input_sha256:{path}")
    return {"path": str(path.resolve()), "sha256": sha256}


def input_manifest_closure(payload: Mapping[str, Mapping[str, str]]) -> str:
    return sha256_json({key: dict(value) for key, value in sorted(payload.items())})


def normalize_hash_mapping(payload: Any, label: str) -> dict[Path, str]:
    require(isinstance(payload, dict) and payload, f"{label}_missing_or_empty")
    normalized: dict[Path, str] = {}
    for raw_path, raw_hash in payload.items():
        path = Path(str(raw_path)).resolve()
        digest = str(raw_hash)
        require(len(digest) == 64, f"{label}_hash_invalid:{path}")
        require(path not in normalized, f"{label}_duplicate_path:{path}")
        normalized[path] = digest
    return normalized


def required_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise PredictionFreezeError(f"missing_or_empty:{label}:{path}")


def required_surrogate_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise WaitingForSurrogates(f"missing_or_empty:{label}:{path}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PredictionFreezeError("cannot_write_empty_predictions")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())
    fsync_directory(destination.parent)


@contextmanager
def publication_lock(out_dir: Path):
    import fcntl

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir.parent / f".{out_dir.name}.prediction-freeze.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PredictionFreezeError("prediction_freezer_already_running") from exc
        yield


def validate_holdout(
    registry: SnapshotRegistry,
    manifest_path: Path,
    audit_path: Path,
    receipt_path: Path,
    *,
    enforce_production_hashes: bool,
    expected_count: int,
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, Any], dict[str, Any]]:
    snapshots = {
        "manifest": registry.take(manifest_path, "v4f_manifest"),
        "audit": registry.take(audit_path, "v4f_audit"),
        "manifest_receipt": registry.take(receipt_path, "v4f_manifest_receipt"),
    }
    hashes = {
        name: snapshot.sha256 for name, snapshot in snapshots.items()
    }
    if enforce_production_hashes:
        require(hashes["manifest"] == EXPECTED_MANIFEST_SHA256, "v4f_manifest_hash_mismatch")
        require(hashes["audit"] == EXPECTED_AUDIT_SHA256, "v4f_audit_hash_mismatch")
        require(
            hashes["manifest_receipt"] == EXPECTED_MANIFEST_RECEIPT_SHA256,
            "v4f_manifest_receipt_hash_mismatch",
        )
    rows, fields = snapshot_table(snapshots["manifest"], "\t")
    required = {
        "candidate_id",
        "sequence_sha256",
        "sequence",
        "parent_id",
        "parent_framework_cluster",
        "design_method",
        "design_mode",
        "target_patch_id",
        "cdr1",
        "cdr2",
        "cdr3",
        "cdr3_length",
        "model_split",
    }
    require(required <= set(fields), "v4f_manifest_fields_missing")
    require(not (FORBIDDEN_MANIFEST_FIELDS & set(fields)), "v4f_manifest_contains_labels")
    require(len(rows) == expected_count, f"v4f_manifest_row_count:{len(rows)}")
    ids: set[str] = set()
    sequence_hashes: set[str] = set()
    for row in rows:
        candidate_id = row["candidate_id"].strip()
        sequence = row["sequence"].strip().upper()
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        require(candidate_id and candidate_id not in ids, f"v4f_duplicate_id:{candidate_id}")
        require(digest == row["sequence_sha256"], f"v4f_sequence_hash_mismatch:{candidate_id}")
        require(digest not in sequence_hashes, f"v4f_duplicate_sequence:{candidate_id}")
        require(row["model_split"] == MODEL_SPLIT, f"v4f_split_mismatch:{candidate_id}")
        ids.add(candidate_id)
        sequence_hashes.add(digest)
    audit = snapshot_json(snapshots["audit"], "v4f_audit")
    require(audit.get("status") == "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN", "v4f_audit_status_invalid")
    expected_mode = "production" if enforce_production_hashes else "test_fixture"
    require(audit.get("execution_mode") == expected_mode, "v4f_audit_execution_mode_invalid")
    require((audit.get("output") or {}).get("sha256") == hashes["manifest"], "v4f_audit_manifest_hash_mismatch")
    require(int((audit.get("checks") or {}).get("row_count", -1)) == expected_count, "v4f_audit_count_mismatch")
    policy = audit.get("future_release_policy") or {}
    require(
        policy.get("labels")
        == "do not compute or open before model/config/test predictions are frozen",
        "v4f_audit_label_policy_invalid",
    )
    audit_without_hash = dict(audit)
    audit_payload_hash = audit_without_hash.pop("audit_payload_sha256", None)
    require(
        isinstance(audit_payload_hash, str)
        and audit_payload_hash == sha256_json(audit_without_hash),
        "v4f_audit_payload_hash_invalid",
    )
    receipt = snapshot_json(snapshots["manifest_receipt"], "v4f_manifest_receipt")
    require(receipt.get("status") == "PASS_COMPLETE_HASH_CLOSURE", "v4f_manifest_receipt_status_invalid")
    require(receipt.get("execution_mode") == expected_mode, "v4f_manifest_receipt_execution_mode_invalid")
    require(receipt.get("manifest_sha256") == hashes["manifest"], "v4f_receipt_manifest_hash_mismatch")
    require(receipt.get("audit_file_sha256") == hashes["audit"], "v4f_receipt_audit_hash_mismatch")
    require(receipt.get("audit_payload_sha256") == audit_payload_hash, "v4f_receipt_audit_payload_hash_mismatch")
    return rows, hashes, audit, receipt


STAGE_CONTRACTS = {
    "base": {
        "config": "frozen_open_model_config.json",
        "artifact": "frozen_open_model_artifact.json",
        "development_predictions": "open_development_predictions.tsv",
        "summary": "open_development_summary.json",
        "receipt": "frozen_open_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE",
    },
    "embedding": {
        "config": "frozen_embedding_model_config.json",
        "artifact": "frozen_embedding_model_artifact.json",
        "development_predictions": "open_development_embedding_predictions.tsv",
        "prospective_predictions": "frozen_prospective_test_predictions.tsv",
        "summary": "open_development_embedding_summary.json",
        "receipt": "frozen_embedding_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE",
    },
    "contact": {
        "config": "contact_fusion_open_model_config.json",
        "artifact": "contact_fusion_open_model_artifact.json",
        "development_predictions": "contact_fusion_open_development_predictions.tsv",
        "summary": "contact_fusion_open_development_summary.json",
        "receipt": "contact_fusion_frozen_artifact_sha256_receipt.json",
        "receipt_status": "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE",
    },
}


def validate_stage(
    registry: SnapshotRegistry, out_dir: Path, stage: str, *, waiting: bool
) -> dict[str, Any]:
    contract = STAGE_CONTRACTS[stage]
    paths = {
        name: (out_dir / filename).resolve()
        for name, filename in contract.items()
        if name not in {"receipt_status"}
    }
    snapshots = {
        name: registry.take(path, f"{stage}_{name}", waiting=waiting)
        for name, path in paths.items()
    }
    receipt = snapshot_json(snapshots["receipt"], f"{stage}_receipt")
    require(receipt.get("status") == contract["receipt_status"], f"{stage}_receipt_status_invalid")
    require(receipt.get("prospective_test_labels_read") is False, f"{stage}_receipt_test_labels_read")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict), f"{stage}_receipt_outputs_missing")
    expected_output_paths = {
        str(path.resolve()) for name, path in paths.items() if name != "receipt"
    }
    require(set(outputs) == expected_output_paths, f"{stage}_receipt_output_set_mismatch")
    for name, path in paths.items():
        if name == "receipt":
            continue
        require(
            outputs.get(str(path)) == snapshots[name].sha256,
            f"{stage}_{name}_receipt_hash_mismatch",
        )
    declared_inputs = normalize_hash_mapping(receipt.get("inputs"), f"{stage}_receipt_inputs")
    summary = snapshot_json(snapshots["summary"], f"{stage}_summary")
    prospective = summary.get("prospective_test") or {}
    require(prospective.get("labels_read") is False, f"{stage}_summary_test_labels_read")
    require(int(prospective.get("label_files_opened", 0)) == 0, f"{stage}_summary_test_files_opened")
    config = snapshot_json(snapshots["config"], f"{stage}_config")
    if stage == "contact":
        config_inputs = normalize_hash_mapping(
            config.get("stage_input_hashes"), "contact_config_stage_inputs"
        )
        require(config_inputs == declared_inputs, "contact_config_receipt_stage_inputs_mismatch")
        closure = contact.sha256_json(
            {str(path): digest for path, digest in declared_inputs.items()}
        )
        require(
            config.get("stage_inputs_closure_sha256") == closure
            and receipt.get("stage_inputs_closure_sha256") == closure,
            "contact_stage_inputs_closure_mismatch",
        )
    return {
        "paths": paths,
        "snapshots": snapshots,
        "hashes": {name: snapshot.sha256 for name, snapshot in snapshots.items()},
        "receipt_payload": receipt,
        "declared_inputs": declared_inputs,
        "config_payload": config,
        "scientific_gate_status": summary.get("status"),
    }


def validate_contact_artifact(snapshot: FileSnapshot, config_hash: str) -> dict[str, Any]:
    artifact = snapshot_json(snapshot, "contact_artifact")
    require(
        artifact.get("schema_version") == contact.SCHEMA_VERSION
        and artifact.get("status") == "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
        "contact_artifact_status_invalid",
    )
    require(artifact.get("config_sha256") == config_hash, "contact_artifact_config_hash_mismatch")
    require(artifact.get("prospective_test_labels_read") is False, "contact_artifact_test_labels_read")
    require(set(artifact.get("models", {})) == set(contact.MODEL_NAMES), "contact_artifact_model_set_invalid")
    selected = artifact.get("selected_candidate_model")
    require(selected in contact.CANDIDATE_MODELS, "contact_artifact_selected_model_invalid")
    return artifact


def validate_base_artifact(snapshot: FileSnapshot, config_hash: str) -> dict[str, Any]:
    artifact = snapshot_json(snapshot, "base_artifact")
    require(artifact.get("schema_version") == base.SCHEMA_VERSION, "base_artifact_schema_invalid")
    require(
        artifact.get("status")
        == "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
        "base_artifact_status_invalid",
    )
    require(artifact.get("config_sha256") == config_hash, "base_artifact_config_hash_mismatch")
    require(set(artifact.get("models", {})) == set(base.MODEL_NAMES), "base_artifact_model_set_invalid")
    selected = artifact.get("selected_candidate_model")
    require(selected in base.CANDIDATE_MODELS, "base_selected_model_invalid")
    return artifact


def validate_embedding_artifact(
    snapshot: FileSnapshot, config_hash: str
) -> dict[str, Any]:
    artifact = snapshot_json(snapshot, "embedding_artifact")
    require(
        artifact.get("schema_version") == embedding.SCHEMA_VERSION,
        "embedding_artifact_schema_invalid",
    )
    require(
        artifact.get("status") == "FROZEN_MODEL_TEST_LABELS_NOT_READ",
        "embedding_artifact_status_invalid",
    )
    require(
        artifact.get("prospective_test_labels_read") is False,
        "embedding_artifact_test_labels_read",
    )
    require(
        artifact.get("config_sha256") == config_hash,
        "embedding_artifact_config_hash_mismatch",
    )
    require(
        set(artifact.get("models", {})) == set(embedding.EMBEDDING_MODELS),
        "embedding_artifact_model_set_invalid",
    )
    require(
        artifact.get("selected_model") in embedding.EMBEDDING_MODELS,
        "embedding_artifact_selected_model_invalid",
    )
    return artifact


def validate_contact_schema_snapshots(
    schema_snapshot: FileSnapshot,
    schema_receipt_snapshot: FileSnapshot,
    contact_receipt_snapshot: FileSnapshot,
    *,
    enforce_production_hashes: bool,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    schema = snapshot_json(schema_snapshot, "contact_schema")
    schema_receipt = snapshot_json(schema_receipt_snapshot, "contact_schema_receipt")
    if enforce_production_hashes:
        require(
            schema_snapshot.sha256 == contact.EXPECTED_CONTACT_SCHEMA_SHA256,
            "contact_schema_production_hash_mismatch",
        )
        require(
            schema_receipt_snapshot.sha256
            == contact.EXPECTED_CONTACT_SCHEMA_RECEIPT_SHA256,
            "contact_schema_receipt_production_hash_mismatch",
        )
    expected_status = (
        "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA"
        if enforce_production_hashes
        else "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA"
    )
    expected_receipt_status = (
        "PASS_COMPLETE_HASH_CLOSURE"
        if enforce_production_hashes
        else "TEST_ONLY_PASS_HASH_CLOSURE"
    )
    expected_mode = "production" if enforce_production_hashes else "test_only"
    require(
        schema.get("schema_version") == contact.CONTACT_SCHEMA_VERSION
        and schema.get("status") == expected_status
        and schema.get("execution_mode") == expected_mode,
        "contact_schema_version_status_or_mode_mismatch",
    )
    require(
        schema_receipt.get("schema_version") == contact.CONTACT_SCHEMA_RECEIPT_VERSION
        and schema_receipt.get("status") == expected_receipt_status
        and schema_receipt.get("schema_file_sha256") == schema_snapshot.sha256,
        "contact_schema_receipt_closure_mismatch",
    )
    configuration = schema.get("configuration")
    require(isinstance(configuration, dict), "contact_schema_configuration_missing")
    require(
        schema.get("configuration_sha256") == contact.sha256_json(configuration)
        and schema_receipt.get("configuration_sha256")
        == schema.get("configuration_sha256")
        and configuration.get("schema_version") == contact.CONTACT_SCHEMA_VERSION
        and configuration.get("selection_uses_docking_labels") is False,
        "contact_schema_configuration_closure_mismatch",
    )
    payload_without_hash = dict(schema)
    payload_hash = payload_without_hash.pop("payload_sha256", None)
    require(
        isinstance(payload_hash, str)
        and payload_hash == contact.sha256_json(payload_without_hash)
        and schema_receipt.get("schema_payload_sha256") == payload_hash,
        "contact_schema_payload_hash_mismatch",
    )
    selected_features = tuple(str(value) for value in schema.get("selected_features") or [])
    require(
        bool(selected_features)
        and len(selected_features) == len(set(selected_features))
        and schema.get("selected_feature_count") == len(selected_features)
        and schema.get("required_shortcut_baseline") == "cdr_length_only",
        "contact_schema_selected_features_invalid",
    )
    stability = schema.get("feature_stability")
    require(isinstance(stability, list), "contact_schema_stability_missing")
    selected_from_stability: list[str] = []
    for row in stability:
        require(
            isinstance(row, dict) and isinstance(row.get("feature"), str),
            "contact_schema_stability_row_invalid",
        )
        if row.get("selected"):
            require(
                row.get("cross_seed_stable") is True
                and row.get("length_confounded") is False,
                "contact_schema_selected_feature_not_stable",
            )
            selected_from_stability.append(str(row["feature"]))
    require(
        tuple(selected_from_stability) == selected_features,
        "contact_schema_selected_feature_stability_mismatch",
    )
    require(
        all(feature in contact.contact_v3.STABLE_FEATURE_NAMES for feature in selected_features),
        "contact_schema_feature_not_in_v3_allowlist",
    )
    require(
        not (
            set(selected_features)
            & set(schema.get("diagnostic_only_length_confounded_features") or [])
        ),
        "contact_schema_selected_diagnostic_feature",
    )
    expected_means = tuple(f"{feature}_seed_mean" for feature in selected_features)
    expected_mean_std = tuple(
        column
        for feature in selected_features
        for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
    )
    feature_sets = schema.get("training_feature_sets")
    require(isinstance(feature_sets, dict), "contact_schema_training_feature_sets_missing")
    require(
        tuple(feature_sets.get("stable_seed_mean") or []) == expected_means
        and tuple(feature_sets.get("stable_seed_mean_and_std") or [])
        == expected_mean_std,
        "contact_schema_training_feature_sets_mismatch",
    )
    stable_columns = contact.validate_stable_allowlist(expected_mean_std)
    schema_input = (schema.get("inputs") or {}).get("feature_release_receipt")
    require(isinstance(schema_input, dict), "contact_schema_feature_receipt_input_missing")
    require(
        Path(str(schema_input.get("path", ""))).resolve()
        == contact_receipt_snapshot.path
        and schema_input.get("sha256") == contact_receipt_snapshot.sha256
        and schema_receipt.get("feature_release_receipt_sha256")
        == contact_receipt_snapshot.sha256,
        "contact_schema_feature_receipt_hash_or_path_mismatch",
    )
    metadata = {
        "schema_path": str(schema_snapshot.path),
        "schema_sha256": schema_snapshot.sha256,
        "schema_receipt_path": str(schema_receipt_snapshot.path),
        "schema_receipt_sha256": schema_receipt_snapshot.sha256,
        "selected_features": list(selected_features),
        "selected_feature_count": len(selected_features),
        "stable_columns": list(stable_columns),
        "selection_uses_docking_labels": False,
    }
    return stable_columns, metadata


def load_contact_replay(
    registry: SnapshotRegistry,
    receipt_path: Path,
    schema_path: Path,
    required_ids: set[str],
    *,
    enforce_production_hashes: bool,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...], dict[str, Any]]:
    receipt_snapshot = registry.take(receipt_path, "contact_feature_receipt")
    if enforce_production_hashes:
        require(
            receipt_snapshot.sha256 == EXPECTED_CONTACT_FEATURE_RECEIPT_SHA256,
            "contact_feature_receipt_production_hash_mismatch",
        )
    receipt = snapshot_json(receipt_snapshot, "contact_feature_receipt")
    require(
        receipt.get("status") == "PASS"
        and receipt.get("schema_version") == contact.contact_v3.RECEIPT_SCHEMA_VERSION
        and receipt.get("feature_schema_version") == contact.contact_v3.SCHEMA_VERSION,
        "contact_feature_receipt_status_or_schema_invalid",
    )
    feature_path = Path(str(receipt.get("output", ""))).resolve()
    audit_path = Path(str(receipt.get("audit", ""))).resolve()
    implementation_path = Path(str(receipt.get("script", ""))).resolve()
    feature_snapshot = registry.take(feature_path, "contact_feature_csv")
    audit_snapshot = registry.take(audit_path, "contact_feature_audit")
    implementation_snapshot = registry.take(
        implementation_path, "contact_feature_implementation"
    )
    require(
        receipt.get("output_sha256") == feature_snapshot.sha256,
        "contact_feature_output_hash_mismatch",
    )
    require(
        receipt.get("audit_sha256") == audit_snapshot.sha256,
        "contact_feature_audit_hash_mismatch",
    )
    require(
        receipt.get("script_sha256") == implementation_snapshot.sha256,
        "contact_feature_implementation_hash_mismatch",
    )
    source_snapshot = receipt.get("input_snapshot")
    require(isinstance(source_snapshot, dict) and source_snapshot, "contact_feature_input_snapshot_missing")
    require(
        contact.contact_v3.snapshot_content_closure(source_snapshot)
        == receipt.get("input_snapshot_content_closure_sha256"),
        "contact_feature_input_snapshot_closure_mismatch",
    )
    audit = snapshot_json(audit_snapshot, "contact_feature_audit")
    require(
        audit.get("status") == "PASS"
        and audit.get("feature_schema_version") == contact.contact_v3.SCHEMA_VERSION,
        "contact_feature_audit_status_or_schema_invalid",
    )
    require(
        audit.get("output_sha256") == feature_snapshot.sha256
        and audit.get("input_snapshot_unchanged") is True,
        "contact_feature_audit_output_or_snapshot_invalid",
    )
    contract = audit.get("label_free_contract")
    require(isinstance(contract, dict), "contact_feature_label_free_contract_missing")
    if enforce_production_hashes:
        require(
            contract.get("production_hash_locks_enforced") is True
            and contract.get("test_only_unfrozen_hash_override") is False,
            "contact_feature_production_contract_invalid",
        )
    policy = audit.get("feature_policy")
    require(isinstance(policy, dict), "contact_feature_policy_missing")
    require(
        set(policy.get("stable_default_trainer_features") or [])
        == set(contact.contact_v3.STABLE_FEATURE_NAMES)
        and set(policy.get("default_trainer_must_exclude") or [])
        == set(contact.contact_v3.DIAGNOSTIC_ONLY_FEATURES),
        "contact_feature_policy_invalid",
    )
    schema_snapshot = registry.take(schema_path, "contact_schema")
    schema_receipt_snapshot = registry.take(
        schema_path.with_suffix(".receipt.json"), "contact_schema_receipt"
    )
    stable_columns, schema_metadata = validate_contact_schema_snapshots(
        schema_snapshot,
        schema_receipt_snapshot,
        receipt_snapshot,
        enforce_production_hashes=enforce_production_hashes,
    )
    v3_stable_columns = set(
        contact.validate_stable_allowlist(
            policy.get("stable_default_trainer_columns") or []
        )
    )
    require(
        set(stable_columns) <= v3_stable_columns,
        "contact_schema_columns_not_in_v3_audit_allowlist",
    )
    require(
        not (
            set(policy.get("default_trainer_must_exclude_columns") or [])
            & set(stable_columns)
        ),
        "contact_stable_and_prohibited_columns_overlap",
    )
    rows, fieldnames = snapshot_table(feature_snapshot, ",")
    require(
        len(rows) == int(receipt.get("output_row_count", -1)),
        "contact_feature_row_count_mismatch",
    )
    require(
        bool(rows)
        and all(
            row.get("schema_version") == contact.contact_v3.SCHEMA_VERSION for row in rows
        ),
        "contact_feature_row_schema_invalid",
    )
    require(
        all(
            row.get("supersedes")
            == ";".join(contact.contact_v3.SUPERSEDED_SCHEMA_VERSIONS)
            for row in rows
        ),
        "contact_feature_supersedes_invalid",
    )
    required_fields = {"candidate_id", "sequence_sha256", *stable_columns}
    require(required_fields <= set(fieldnames), "contact_feature_columns_missing")
    by_id: dict[str, dict[str, Any]] = {}
    for source in rows:
        candidate_id = source["candidate_id"].strip()
        require(candidate_id not in by_id, f"duplicate_contact_candidate:{candidate_id}")
        row: dict[str, Any] = {
            "candidate_id": candidate_id,
            "sequence_sha256": source["sequence_sha256"].strip().lower(),
        }
        for column in stable_columns:
            row[column] = base.finite_float(source[column], f"contact:{column}")
        by_id[candidate_id] = row
    missing_ids = sorted(required_ids - set(by_id))
    require(
        not missing_ids,
        "contact_features_missing_candidates:" + ",".join(missing_ids[:5]),
    )
    metadata = {
        "receipt_path": str(receipt_snapshot.path),
        "receipt_sha256": receipt_snapshot.sha256,
        "audit_path": str(audit_snapshot.path),
        "audit_sha256": audit_snapshot.sha256,
        "feature_path": str(feature_snapshot.path),
        "feature_sha256": feature_snapshot.sha256,
        "implementation_path": str(implementation_snapshot.path),
        "implementation_sha256": implementation_snapshot.sha256,
        "stable_columns": list(stable_columns),
        "stable_columns_sha256": base.sha256_strings(stable_columns),
        "frozen_schema": schema_metadata,
        "diagnostic_columns_used": [],
        "docking_label_alias_columns_used": [],
    }
    return by_id, stable_columns, metadata


def finite_predictions(values: np.ndarray, uncertainty: np.ndarray, label: str) -> None:
    require(values.ndim == uncertainty.ndim == 1, f"{label}_prediction_dimension_invalid")
    require(len(values) == len(uncertainty), f"{label}_prediction_length_mismatch")
    require(np.all(np.isfinite(values)) and np.all(np.isfinite(uncertainty)), f"{label}_prediction_nonfinite")
    require(np.all(uncertainty >= 0), f"{label}_uncertainty_negative")


def build_predictions(
    rows: list[dict[str, str]],
    base_stage: Mapping[str, Any],
    embedding_stage: Mapping[str, Any],
    contact_stage: Mapping[str, Any],
    bank: embedding.EmbeddingBank,
    contacts: Mapping[str, Mapping[str, Any]],
    stable_columns: Sequence[str],
    contact_metadata: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_config_hash = base_stage["hashes"]["config"]
    base_artifact = validate_base_artifact(
        base_stage["snapshots"]["artifact"], base_config_hash
    )
    base_model = str(base_artifact.get("selected_candidate_model"))
    base_prediction, base_uncertainty = base.predict_serialized_model(
        base_artifact, base_model, rows
    )

    embedding_config_hash = embedding_stage["hashes"]["config"]
    embedding_artifact = validate_embedding_artifact(
        embedding_stage["snapshots"]["artifact"], embedding_config_hash
    )
    embedding_model = str(embedding_artifact["selected_model"])
    sequence_hashes = [row["sequence_sha256"] for row in rows]
    embedding_prediction, embedding_uncertainty = embedding.predict_artifact_model(
        embedding_artifact, embedding_model, bank, sequence_hashes
    )

    esm2 = bank.matrix(sequence_hashes, "esm2_ridge")
    contact_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        feature = contacts[row["candidate_id"]]
        require(
            feature["sequence_sha256"] == row["sequence_sha256"],
            f"contact_sequence_hash_mismatch:{row['candidate_id']}",
        )
        contact_rows.append(
            {**row, "_contact": {column: feature[column] for column in stable_columns}, "_embedding": esm2[index]}
        )
    contact_config_hash = contact_stage["hashes"]["config"]
    contact_artifact = validate_contact_artifact(
        contact_stage["snapshots"]["artifact"], contact_config_hash
    )
    expected_identity = {
        "embedding_bank_identity_sha256": bank.provenance["identity_sha256"],
        "contact_release_receipt_sha256": contact_metadata["receipt_sha256"],
        "contact_schema_sha256": contact_metadata["frozen_schema"]["schema_sha256"],
        "stable_contact_columns_sha256": base.sha256_strings(stable_columns),
    }
    contact_receipt = contact_stage["receipt_payload"]
    identity_contract = contact_stage["config_payload"].get("artifact_identity_contract")
    require(
        isinstance(identity_contract, dict),
        "contact_config_artifact_identity_contract_missing",
    )
    for field, expected in expected_identity.items():
        require(
            contact_artifact.get(field) == expected,
            f"contact_artifact_{field}_mismatch",
        )
        require(
            contact_receipt.get(field) == expected,
            f"contact_receipt_{field}_mismatch",
        )
        require(
            identity_contract.get(field) == expected,
            f"contact_config_{field}_mismatch",
        )
    stage_closure = contact_stage["config_payload"].get(
        "stage_inputs_closure_sha256"
    )
    require(
        contact_artifact.get("stage_inputs_closure_sha256") == stage_closure
        and contact_receipt.get("stage_inputs_closure_sha256") == stage_closure,
        "contact_artifact_stage_inputs_closure_mismatch",
    )
    require(
        tuple(contact_receipt.get("stable_contact_columns") or [])
        == tuple(stable_columns),
        "contact_receipt_stable_columns_mismatch",
    )
    replay_inputs = {
        Path(contact_metadata["receipt_path"]).resolve(): contact_metadata[
            "receipt_sha256"
        ],
        Path(contact_metadata["audit_path"]).resolve(): contact_metadata["audit_sha256"],
        Path(contact_metadata["feature_path"]).resolve(): contact_metadata[
            "feature_sha256"
        ],
        Path(contact_metadata["frozen_schema"]["schema_path"]).resolve(): contact_metadata[
            "frozen_schema"
        ]["schema_sha256"],
        Path(contact_metadata["frozen_schema"]["schema_receipt_path"]).resolve(): contact_metadata[
            "frozen_schema"
        ]["schema_receipt_sha256"],
        Path(bank.provenance["embedding_manifest"]["path"]).resolve(): bank.provenance[
            "embedding_manifest"
        ]["sha256"],
        Path(bank.provenance["embedding_summary"]["path"]).resolve(): bank.provenance[
            "embedding_summary"
        ]["sha256"],
        Path(bank.provenance["sequence_manifest"]["path"]).resolve(): bank.provenance[
            "sequence_manifest"
        ]["sha256"],
        **{
            Path(payload["path"]).resolve(): payload["sha256"]
            for payload in bank.provenance["shards"].values()
        },
    }
    declared_contact_inputs = contact_stage["declared_inputs"]
    for path, digest in replay_inputs.items():
        require(
            declared_contact_inputs.get(path) == digest,
            f"contact_stage_replay_input_not_bound:{path}",
        )
    contact_model = str(contact_artifact["selected_candidate_model"])
    contact_prediction, contact_uncertainty = contact.predict_serialized_model(
        contact_artifact, contact_model, contact_rows
    )

    for label, prediction, uncertainty in (
        ("base", base_prediction, base_uncertainty),
        ("embedding", embedding_prediction, embedding_uncertainty),
        ("contact", contact_prediction, contact_uncertainty),
    ):
        finite_predictions(prediction, uncertainty, label)
        require(len(prediction) == len(rows), f"{label}_prediction_row_count_mismatch")

    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        result = {field: row[field] for field in IDENTITY_FIELDS}
        result.update(
            {
                "base_selected_model": base_model,
                "base_predicted_geometry_score": format(float(base_prediction[index]), ".9g"),
                "base_prediction_uncertainty": format(float(base_uncertainty[index]), ".9g"),
                "embedding_selected_model": embedding_model,
                "embedding_predicted_geometry_score": format(float(embedding_prediction[index]), ".9g"),
                "embedding_prediction_uncertainty": format(float(embedding_uncertainty[index]), ".9g"),
                "contact_selected_model": contact_model,
                "contact_predicted_geometry_score": format(float(contact_prediction[index]), ".9g"),
                "contact_prediction_uncertainty": format(float(contact_uncertainty[index]), ".9g"),
            }
        )
        output.append(result)
    provenance = {
        "base_selected_model": base_model,
        "embedding_selected_model": embedding_model,
        "contact_selected_model": contact_model,
        "embedding_bank": bank.provenance,
        "contact_release": contact_metadata,
        "contact_identity_contract": expected_identity,
    }
    return output, provenance


@dataclass(frozen=True)
class ReplayContext:
    rows: list[dict[str, str]]
    holdout_hashes: dict[str, str]
    stages: dict[str, dict[str, Any]]
    prediction_rows: list[dict[str, Any]]
    provenance: dict[str, Any]
    input_hashes: dict[str, str]
    input_closure_sha256: str
    execution_source_hashes: dict[str, str]
    execution_source_closure_sha256: str


def assemble_input_hashes(
    registry: SnapshotRegistry,
    stages: Mapping[str, Mapping[str, Any]],
    bank: embedding.EmbeddingBank,
) -> dict[str, str]:
    actual: dict[Path, str] = {
        snapshot.path: snapshot.sha256 for snapshot in registry.values()
    }
    for payload in bank.provenance["shards"].values():
        path = Path(payload["path"]).resolve()
        digest = str(payload["sha256"])
        previous = actual.get(path)
        require(previous in {None, digest}, f"input_hash_conflict:{path}")
        actual[path] = digest
    for stage, payload in stages.items():
        for path, expected in payload["declared_inputs"].items():
            if path not in actual:
                actual[path] = registry.take(
                    path, f"{stage}_declared_input", waiting=False
                ).sha256
            require(
                actual[path] == expected,
                f"{stage}_declared_input_hash_mismatch:{path}",
            )
    input_hashes = {str(path): digest for path, digest in sorted(actual.items(), key=lambda item: str(item[0]))}
    require(input_hashes, "prediction_input_hashes_empty")
    return input_hashes


def verify_input_hashes(input_hashes: Mapping[str, str]) -> None:
    normalized = normalize_hash_mapping(dict(input_hashes), "prediction_input_hashes")
    for path, expected in normalized.items():
        try:
            observed = sha256_file(path)
        except OSError as exc:
            raise PredictionFreezeError(f"frozen_prediction_input_missing:{path}") from exc
        require(observed == expected, f"frozen_prediction_input_changed:{path}")


def prepare_replay(args: argparse.Namespace, *, waiting: bool) -> ReplayContext:
    registry = SnapshotRegistry()
    source_snapshots = execution_source_snapshots()
    for snapshot in source_snapshots:
        registry.seed(snapshot)
    verify_snapshots_current(source_snapshots, "executed_source")
    rows, holdout_hashes, _holdout_audit, _holdout_receipt = validate_holdout(
        registry,
        args.manifest,
        args.manifest_audit,
        args.manifest_receipt,
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
        expected_count=args.expected_count,
    )
    stages = {
        "base": validate_stage(registry, args.base_out, "base", waiting=waiting),
        "embedding": validate_stage(
            registry, args.embedding_out, "embedding", waiting=waiting
        ),
        "contact": validate_stage(
            registry, args.contact_out, "contact", waiting=waiting
        ),
    }
    manifest_snapshot = registry.take(
        args.embedding_manifest, "embedding_bank_manifest", waiting=waiting
    )
    summary_snapshot = registry.take(
        args.embedding_summary, "embedding_bank_summary", waiting=waiting
    )
    sequence_snapshot = registry.take(
        args.embedding_sequence_manifest,
        "embedding_bank_sequence_manifest",
        waiting=waiting,
    )
    bank = embedding.load_embedding_bank(
        args.embedding_manifest,
        args.embedding_summary,
        args.embedding_sequence_manifest,
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
        embedding_manifest_snapshot=embedding.FileSnapshot(
            manifest_snapshot.path, manifest_snapshot.payload, manifest_snapshot.sha256
        ),
        embedding_summary_snapshot=embedding.FileSnapshot(
            summary_snapshot.path, summary_snapshot.payload, summary_snapshot.sha256
        ),
        sequence_manifest_snapshot=embedding.FileSnapshot(
            sequence_snapshot.path, sequence_snapshot.payload, sequence_snapshot.sha256
        ),
    )
    contacts, stable_columns, contact_metadata = load_contact_replay(
        registry,
        args.contact_receipt,
        args.contact_schema,
        {row["candidate_id"] for row in rows},
        enforce_production_hashes=not args.test_only_allow_unfrozen_inputs,
    )
    prediction_rows, provenance = build_predictions(
        rows,
        stages["base"],
        stages["embedding"],
        stages["contact"],
        bank,
        contacts,
        stable_columns,
        contact_metadata,
    )
    input_hashes = assemble_input_hashes(registry, stages, bank)
    source_hashes = execution_source_hashes()
    require(
        all(input_hashes.get(path) == digest for path, digest in source_hashes.items()),
        "executed_sources_not_closed_by_prediction_inputs",
    )
    verify_snapshots_current(source_snapshots, "executed_source")
    return ReplayContext(
        rows=rows,
        holdout_hashes=holdout_hashes,
        stages=stages,
        prediction_rows=prediction_rows,
        provenance=provenance,
        input_hashes=input_hashes,
        input_closure_sha256=sha256_json(input_hashes),
        execution_source_hashes=source_hashes,
        execution_source_closure_sha256=sha256_json(source_hashes),
    )


def validate_prediction_rows(
    prediction_source: Path | FileSnapshot,
    manifest_rows: list[dict[str, str]],
    expected_count: int,
) -> list[dict[str, str]]:
    snapshot = (
        prediction_source
        if isinstance(prediction_source, FileSnapshot)
        else SnapshotRegistry().take(prediction_source, "frozen_predictions")
    )
    rows, fields = snapshot_table(snapshot, "\t")
    require(len(rows) == expected_count, "prediction_row_count_mismatch")
    require(tuple(fields) == PREDICTION_FIELDS, "prediction_output_field_contract_mismatch")
    require(not (FORBIDDEN_OUTPUT_FIELDS & set(fields)), "prediction_output_contains_label_field")
    require(
        not any(
            token in field.lower()
            for field in fields
            for token in ("ground_truth", "observed_geometry", "experimental_label")
        ),
        "prediction_output_contains_label_alias",
    )
    expected_ids = [row["candidate_id"] for row in manifest_rows]
    require([row.get("candidate_id") for row in rows] == expected_ids, "prediction_candidate_order_mismatch")
    for prediction, manifest in zip(rows, manifest_rows):
        for field in IDENTITY_FIELDS:
            require(
                prediction.get(field) == manifest.get(field),
                f"prediction_identity_field_mismatch:{field}:{manifest['candidate_id']}",
            )
        for prefix in ("base", "embedding", "contact"):
            require(prediction.get(f"{prefix}_selected_model", "").strip() != "", "prediction_model_name_missing")
            try:
                score = float(prediction[f"{prefix}_predicted_geometry_score"])
                uncertainty = float(prediction[f"{prefix}_prediction_uncertainty"])
            except (KeyError, ValueError) as exc:
                raise PredictionFreezeError("prediction_numeric_field_invalid") from exc
            require(math.isfinite(score) and math.isfinite(uncertainty), "prediction_numeric_nonfinite")
            require(uncertainty >= 0, "prediction_uncertainty_negative")
    return rows


def verify_receipt(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = args.receipt.resolve()
    guard_execution_paths(args, receipt_path.parent)
    output_registry = SnapshotRegistry()
    receipt_snapshot = output_registry.take(
        receipt_path, "prediction_receipt", waiting=True
    )
    receipt = snapshot_json(receipt_snapshot, "prediction_receipt")
    require(receipt.get("schema_version") == SCHEMA_VERSION, "prediction_receipt_schema_invalid")
    require(
        receipt.get("status") == "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
        "prediction_receipt_status_invalid",
    )
    expected_mode = execution_mode(args.test_only_allow_unfrozen_inputs)
    require(receipt.get("execution_mode") == expected_mode, "prediction_receipt_execution_mode_invalid")
    require(int(receipt.get("row_count", -1)) == args.expected_count, "prediction_receipt_count_invalid")
    require(receipt.get("v4_f_labels_read") is False, "prediction_receipt_labels_read")
    require(receipt.get("v4_f_label_paths_accepted") == 0, "prediction_receipt_label_paths_accepted")
    context = prepare_replay(args, waiting=False)
    require(receipt.get("holdout") == {
        "manifest_sha256": context.holdout_hashes["manifest"],
        "audit_sha256": context.holdout_hashes["audit"],
        "manifest_receipt_sha256": context.holdout_hashes["manifest_receipt"],
    }, "prediction_receipt_holdout_hashes_mismatch")
    outputs = receipt.get("outputs")
    require(
        isinstance(outputs, dict) and set(outputs) == {"predictions", "audit"},
        "prediction_receipt_output_set_invalid",
    )
    prediction_path = Path(str((outputs.get("predictions") or {}).get("path", "")))
    freeze_audit_path = Path(str((outputs.get("audit") or {}).get("path", "")))
    expected_root = receipt_path.resolve().parent
    require(
        prediction_path.resolve() == expected_root / OUTPUT_FILENAMES[0]
        and freeze_audit_path.resolve() == expected_root / OUTPUT_FILENAMES[1],
        "prediction_receipt_output_paths_invalid",
    )
    prediction_snapshot = output_registry.take(prediction_path, "frozen_predictions")
    audit_snapshot = output_registry.take(freeze_audit_path, "frozen_prediction_audit")
    require(
        prediction_snapshot.sha256 == (outputs["predictions"] or {}).get("sha256"),
        "prediction_receipt_output_hash_mismatch",
    )
    require(
        audit_snapshot.sha256 == (outputs["audit"] or {}).get("sha256"),
        "prediction_receipt_audit_hash_mismatch",
    )
    prediction_rows = validate_prediction_rows(
        prediction_snapshot, context.rows, args.expected_count
    )
    require(
        prediction_rows == context.prediction_rows,
        "prediction_replay_bytes_or_values_mismatch",
    )
    freeze_audit = snapshot_json(audit_snapshot, "prediction_audit")
    require(freeze_audit.get("status") == "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN", "prediction_audit_status_invalid")
    require(freeze_audit.get("execution_mode") == expected_mode, "prediction_audit_execution_mode_invalid")
    require(int(freeze_audit.get("row_count", -1)) == args.expected_count, "prediction_audit_count_invalid")
    require(freeze_audit.get("v4_f_labels_read") is False, "prediction_audit_labels_read")
    require(freeze_audit.get("v4_f_label_files_opened") == 0, "prediction_audit_label_files_opened")
    require(freeze_audit.get("v4_f_label_paths_accepted") == 0, "prediction_audit_label_paths_accepted")
    require(
        freeze_audit.get("holdout_hashes") == context.holdout_hashes,
        "prediction_audit_holdout_hashes_mismatch",
    )
    require(
        freeze_audit.get("prediction_sha256") == prediction_snapshot.sha256,
        "prediction_audit_prediction_hash_mismatch",
    )
    input_hashes = receipt.get("input_hashes")
    require(
        isinstance(input_hashes, dict) and input_hashes == context.input_hashes,
        "prediction_receipt_input_set_or_hash_mismatch",
    )
    require(
        int(receipt.get("input_count", -1)) == len(context.input_hashes),
        "prediction_receipt_input_count_mismatch",
    )
    require(
        receipt.get("input_closure_sha256") == context.input_closure_sha256,
        "prediction_receipt_input_closure_mismatch",
    )
    require(
        freeze_audit.get("input_hashes") == context.input_hashes
        and freeze_audit.get("input_count") == len(context.input_hashes)
        and freeze_audit.get("input_closure_sha256")
        == context.input_closure_sha256,
        "prediction_audit_input_closure_mismatch",
    )
    require(
        receipt.get("execution_source_hashes")
        == context.execution_source_hashes
        and freeze_audit.get("execution_source_hashes")
        == context.execution_source_hashes
        and receipt.get("execution_source_closure_sha256")
        == context.execution_source_closure_sha256
        and freeze_audit.get("execution_source_closure_sha256")
        == context.execution_source_closure_sha256,
        "execution_source_provenance_mismatch",
    )
    require(
        receipt.get("primary_evaluation_policy") == PRIMARY_EVALUATION_POLICY
        and freeze_audit.get("primary_evaluation_policy")
        == PRIMARY_EVALUATION_POLICY
        and receipt.get("primary_evaluation_policy_sha256")
        == PRIMARY_EVALUATION_POLICY_SHA256
        and freeze_audit.get("primary_evaluation_policy_sha256")
        == PRIMARY_EVALUATION_POLICY_SHA256,
        "primary_evaluation_policy_not_frozen",
    )
    freezer_hash = context.input_hashes.get(str(Path(__file__).resolve()))
    require(
        isinstance(freezer_hash, str)
        and receipt.get("freezer_implementation_sha256") == freezer_hash
        and freeze_audit.get("freezer_implementation_sha256") == freezer_hash,
        "freezer_implementation_hash_mismatch",
    )
    expected_models = {
        "base": context.provenance["base_selected_model"],
        "embedding": context.provenance["embedding_selected_model"],
        "contact": context.provenance["contact_selected_model"],
    }
    require(
        receipt.get("prediction_models") == expected_models
        and freeze_audit.get("prediction_models") == expected_models,
        "prediction_model_identity_mismatch",
    )
    verify_input_hashes(input_hashes)
    verify_execution_sources_unchanged()
    verify_snapshots_current(
        (receipt_snapshot, prediction_snapshot, audit_snapshot),
        "verified_output",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V4_F_PREDICTION_RECEIPT_VERIFIED_DOCKING_MAY_START",
        "row_count": len(prediction_rows),
        "receipt_sha256": receipt_snapshot.sha256,
        "predictions_sha256": prediction_snapshot.sha256,
        "input_closure_sha256": context.input_closure_sha256,
        "primary_evaluation_policy_sha256": PRIMARY_EVALUATION_POLICY_SHA256,
        "v4_f_labels_read": False,
    }


def run_freeze(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir = args.out_dir.resolve()
    guard_execution_paths(args, args.out_dir)
    final_paths = {name: args.out_dir / name for name in OUTPUT_FILENAMES}
    with publication_lock(args.out_dir):
        if final_paths[OUTPUT_FILENAMES[-1]].is_file():
            verify_args = argparse.Namespace(**vars(args), receipt=final_paths[OUTPUT_FILENAMES[-1]])
            return verify_receipt(verify_args)
        context = prepare_replay(args, waiting=True)
        if args.out_dir.exists():
            unexpected = sorted(
                path.name for path in args.out_dir.iterdir() if path.name not in OUTPUT_FILENAMES
            )
            require(not unexpected, "prediction_output_directory_contains_unexpected_files")
        args.out_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{args.out_dir.name}.stage.", dir=args.out_dir.parent)
        )
        try:
            prediction_path = staging / OUTPUT_FILENAMES[0]
            audit_path = staging / OUTPUT_FILENAMES[1]
            receipt_path = staging / OUTPUT_FILENAMES[2]
            write_tsv(prediction_path, context.prediction_rows)
            prediction_hash = sha256_file(prediction_path)
            expected_models = {
                "base": context.provenance["base_selected_model"],
                "embedding": context.provenance["embedding_selected_model"],
                "contact": context.provenance["contact_selected_model"],
            }
            mode = execution_mode(args.test_only_allow_unfrozen_inputs)
            freezer_hash = context.input_hashes[str(Path(__file__).resolve())]
            audit = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
                "execution_mode": mode,
                "row_count": len(context.prediction_rows),
                "holdout_hashes": context.holdout_hashes,
                "model_scientific_gate_status": {
                    stage: payload["scientific_gate_status"]
                    for stage, payload in context.stages.items()
                },
                "prediction_models": expected_models,
                "prediction_sha256": prediction_hash,
                "input_hashes": context.input_hashes,
                "input_count": len(context.input_hashes),
                "input_closure_sha256": context.input_closure_sha256,
                "execution_source_hashes": context.execution_source_hashes,
                "execution_source_closure_sha256": (
                    context.execution_source_closure_sha256
                ),
                "freezer_implementation_sha256": freezer_hash,
                "primary_evaluation_policy": PRIMARY_EVALUATION_POLICY,
                "primary_evaluation_policy_sha256": PRIMARY_EVALUATION_POLICY_SHA256,
                "v4_f_labels_read": False,
                "v4_f_label_files_opened": 0,
                "v4_f_label_paths_accepted": 0,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(audit_path, audit)
            verify_input_hashes(context.input_hashes)
            verify_execution_sources_unchanged()
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS_V4_F_96_UNLABELED_PREDICTIONS_FROZEN",
                "execution_mode": mode,
                "row_count": len(context.prediction_rows),
                "holdout": {
                    "manifest_sha256": context.holdout_hashes["manifest"],
                    "audit_sha256": context.holdout_hashes["audit"],
                    "manifest_receipt_sha256": context.holdout_hashes[
                        "manifest_receipt"
                    ],
                },
                "input_hashes": context.input_hashes,
                "input_count": len(context.input_hashes),
                "input_closure_sha256": context.input_closure_sha256,
                "execution_source_hashes": context.execution_source_hashes,
                "execution_source_closure_sha256": (
                    context.execution_source_closure_sha256
                ),
                "freezer_implementation_sha256": freezer_hash,
                "prediction_models": expected_models,
                "primary_evaluation_policy": PRIMARY_EVALUATION_POLICY,
                "primary_evaluation_policy_sha256": PRIMARY_EVALUATION_POLICY_SHA256,
                "outputs": {
                    "predictions": {
                        "path": str(final_paths[OUTPUT_FILENAMES[0]]),
                        "sha256": prediction_hash,
                    },
                    "audit": {
                        "path": str(final_paths[OUTPUT_FILENAMES[1]]),
                        "sha256": sha256_file(audit_path),
                    },
                },
                "publication": {
                    "policy": "stage_then_atomic_replace_receipt_last",
                    "receipt_published_last": True,
                },
                "v4_f_labels_read": False,
                "v4_f_label_paths_accepted": 0,
                "claim_boundary": CLAIM_BOUNDARY,
            }
            write_json(receipt_path, receipt)
            verify_input_hashes(context.input_hashes)
            verify_execution_sources_unchanged()
            args.out_dir.mkdir(parents=True, exist_ok=True)
            final_paths[OUTPUT_FILENAMES[-1]].unlink(missing_ok=True)
            fsync_directory(args.out_dir)
            failure_after = 0
            if args.test_only_allow_unfrozen_inputs:
                failure_after = int(os.environ.get("V4F_TEST_ONLY_FAIL_AFTER_PUBLISH_COUNT", "0"))
            for count, name in enumerate(OUTPUT_FILENAMES, start=1):
                durable_replace(staging / name, final_paths[name])
                if failure_after == count:
                    raise PredictionFreezeError(
                        f"test_only_injected_publication_failure_after:{count}"
                    )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    verify_args = argparse.Namespace(**vars(args), receipt=final_paths[OUTPUT_FILENAMES[-1]])
    return verify_receipt(verify_args)


def build_parser() -> argparse.ArgumentParser:
    root = SCRIPT_DIR.parent
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    verify = subparsers.add_parser("verify-receipt")
    embedding_root = root / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
    for subparser in (freeze, verify):
        subparser.add_argument(
            "--manifest",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
        )
        subparser.add_argument(
            "--manifest-audit",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_audit.json",
        )
        subparser.add_argument(
            "--manifest-receipt",
            type=Path,
            default=root / "data_splits/pvrig_v4_f/prospective_holdout96_receipt.json",
        )
        subparser.add_argument("--expected-count", type=int, default=EXPECTED_ROW_COUNT)
        subparser.add_argument("--test-only-allow-unfrozen-inputs", action="store_true")
        subparser.add_argument(
            "--base-out",
            type=Path,
            default=root / "runs/pvrig_v4_d_sequence_surrogate_v1",
        )
        subparser.add_argument(
            "--embedding-out",
            type=Path,
            default=root / "runs/pvrig_v4_d_frozen_embedding_surrogate_v1",
        )
        subparser.add_argument(
            "--contact-out",
            type=Path,
            default=root / "runs/pvrig_v4_d_contact_fusion_surrogate_v1",
        )
        subparser.add_argument(
            "--embedding-manifest",
            type=Path,
            default=embedding_root / "meanpool_embeddings/embedding_manifest_v3.csv",
        )
        subparser.add_argument(
            "--embedding-summary",
            type=Path,
            default=embedding_root / "meanpool_embeddings/embedding_summary_v3.json",
        )
        subparser.add_argument(
            "--embedding-sequence-manifest",
            type=Path,
            default=embedding_root / "sequence_manifest_v3.csv",
        )
        subparser.add_argument(
            "--contact-receipt",
            type=Path,
            default=root
            / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
        )
        subparser.add_argument(
            "--contact-schema",
            type=Path,
            default=root / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
        )
    freeze.add_argument(
        "--out-dir", type=Path, default=root / "predictions/pvrig_v4_f_surrogate_predictions_v1"
    )
    verify.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = run_freeze(args)
        else:
            result = verify_receipt(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except WaitingForSurrogates as exc:
        print(json.dumps({"status": "WAITING_V4_D_SURROGATES", "reason": str(exc)}, sort_keys=True))
        return 4
    except (PredictionFreezeError, base.SurrogateError, embedding.FrozenEmbeddingError, contact.ContactFusionError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED_V4_F_PREDICTION_FREEZE", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
