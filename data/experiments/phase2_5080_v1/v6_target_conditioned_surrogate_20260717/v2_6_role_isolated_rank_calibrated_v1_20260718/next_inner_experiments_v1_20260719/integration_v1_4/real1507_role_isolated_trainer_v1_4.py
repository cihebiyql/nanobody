#!/usr/bin/env python3
"""Nonlaunching V2.6 real1507 trainer integration V1.4 contact ablation extension.

This module joins three already-versioned surfaces without changing them:

* the V2.5 real1507 data/model adapter and positive neural-input allowlist;
* the frozen V2.6 role-isolated optimizer/RNG primitive;
* a SHA-bound rank-policy module (V1 or a future V1.1-compatible policy).

Only open-development train-partition labels are consumed.  Score-partition
truth, outer metrics, V4-F/test32, M2/126D features, identifiers as model
features, and candidate Docking poses are outside this integration.  There is
intentionally no CLI or remote launcher in this package.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import os
import sys
import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Sequence

import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig_v2_6_real1507_role_isolated_trainer_v1_4_contact_ablation"
CLAIM_BOUNDARY = (
    "Open-development sequence and label-free monomer approximation of independent "
    "8X6B/9E6Y computational Docking geometry only; not binding, affinity, experimental "
    "blocking, Docking Gold, sealed V4-F evidence, or submission truth."
)

LANE_B = "B_SCALAR_ATTENTION_ONLY"
LANE_E = "E_STRICT_DETACHED_DYNAMICS_CONTROL"
LANE_F = "F_SHARED_GATED_CONTACT_TRANSFER"
LANES = (LANE_B, LANE_E, LANE_F)
MODEL_LANE_B = "B_CLEAN_TARGET_ATTENTION"
MODEL_LANE_E = "E_DECOUPLED_CONTACT"

CONTACT_TIER_POLICY = {
    "A": {"marginal": 1.0, "pair": 1.0, "seed_count": 3},
    "B": {"marginal": 0.5, "pair": 0.25, "seed_count": 2},
    "C": {"marginal": 0.1, "pair": 0.0, "seed_count": 1},
}

FROZEN_CONTACT_SHARED_KAPPA = 0.25
FROZEN_CONTACT_SHARED_LAMBDA = 1.0
FROZEN_ENSEMBLE_SEEDS = (43, 97, 193)
FROZEN_INNER_FOLDS = (0, 1, 2, 3, 4)
RANK_TRUST_ANCHOR_SCHEMA = "pvrig_v2_6_external_rank_split_label_trust_anchor_v1"
RANK_TRUST_ANCHOR_SET_SCHEMA = "pvrig_v2_6_external_rank_trust_anchor_set_receipt_v1"
OOF_PREDICTION_RECEIPT_SCHEMA = "pvrig_v2_6_inner_oof_prediction_receipt_v1_3"

BOUND_V25_TRAINER_SHA256 = "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0"
BOUND_V25_MODEL_SHA256 = "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521"
BOUND_V25_REAL_RUNNER_SHA256 = "f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f"
BOUND_OPTIMIZER_CORE_SHA256 = "2dadc945ec30eb802ca9f32fac84ce647783b9defc36db68f345fc00e972f363"
BOUND_RANK_V11_SHA256 = "b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
BOUND_DELTA_NOISE_SHA256 = "0a613b87509699a28d134c02514b1240e50a06a5aefddb5ca4a9d8202cde0a0c"
BOUND_RANK_TRUST_ANCHOR_SET_RECEIPT_SHA256 = "2acf16069e3609a8160d9193818fa707a5105405e28354956f3431634756959e"
BOUND_TEACHER_SHA256 = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
BOUND_INNER_MANIFEST_SHA256 = "b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073"
BOUND_OUTER_MANIFEST_SHA256 = "ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55"

REQUIRED_V25_API = (
    "FORBIDDEN_NEURAL_INPUT_FIELDS",
    "OrthoLossConfig",
    "compute_loss",
    "forward_lane",
    "move_to_device",
    "neural_forward_kwargs",
)
REQUIRED_OPTIMIZER_API = (
    "ContactRngKey",
    "ROLES",
    "RoleOptimizerConfig",
    "ScalarStepOutput",
    "build_role_optimizers",
    "build_scalar_reference_optimizer",
    "role_mapping_from_v25_orthogonal_model",
    "parameter_state_sha256",
    "scalar_trajectory_sha256",
    "scalar_only_step",
    "shared_gated_contact_step",
    "strict_detached_step",
)
REQUIRED_RANK_API = (
    "CalibrationRow",
    "CandidateLabel",
    "RANK_PAIRS_PER_STEP",
    "build_parent_pair_epoch_cache",
    "compute_label_sha256",
    "compute_training_split_sha256",
    "exact_min_dual",
    "fit_fold_local_positive_affine",
    "noise_aware_pairlogit",
    "verify_frozen_delta_noise_binding",
)


class Real1507IntegrationError(RuntimeError):
    """Fail-closed integration error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Real1507IntegrationError(message)


def require_finite(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


def validate_contact_ablation_weights(marginal_weight: float, pair_weight: float) -> str:
    """Validate a new-version contact ablation without weakening V1.3 in place."""
    require(math.isfinite(marginal_weight) and math.isfinite(pair_weight), "contact_weight_nonfinite")
    require(marginal_weight >= 0.0 and pair_weight >= 0.0, "contact_weight_negative")
    require(marginal_weight > 0.0 or pair_weight > 0.0, "contact_ablation_both_zero")
    if marginal_weight > 0.0 and pair_weight > 0.0:
        return "COMBINED"
    if marginal_weight > 0.0:
        return "MARGINAL_ONLY"
    return "PAIR_ONLY"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def reject_sealed_text(value: object, field: str) -> None:
    normalized = str(value).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, f"sealed_reference_forbidden:{field}")


def load_sha_bound_module(
    path: Path,
    expected_sha256: str,
    *,
    logical_name: str,
    required_attributes: Sequence[str],
) -> ModuleType:
    """Load a regular Python file only after exact hash and API closure."""
    reject_sealed_text(path, logical_name)
    require(path.is_file() and not path.is_symlink(), f"module_not_regular_file:{logical_name}")
    observed = sha256_file(path)
    require(observed == expected_sha256, f"module_sha256_mismatch:{logical_name}:{observed}")
    specification = importlib.util.spec_from_file_location(
        f"pvrig_v26_{logical_name}_{observed[:16]}", path
    )
    require(specification is not None and specification.loader is not None, f"module_import_spec:{logical_name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    missing = [name for name in required_attributes if not hasattr(module, name)]
    require(not missing, f"module_api_missing:{logical_name}:{','.join(missing)}")
    return module


@dataclass(frozen=True)
class OpenTrainRow:
    candidate_id: str
    parent_cluster_id: str
    teacher_source: str
    contact_tier: str
    true_r8: float
    true_r9: float

    @property
    def seed_count(self) -> int:
        return int(CONTACT_TIER_POLICY[self.contact_tier]["seed_count"])

    def validate(self) -> None:
        require(bool(self.candidate_id and self.parent_cluster_id and self.teacher_source), "train_row_identity_empty")
        reject_sealed_text(self.candidate_id, "candidate_id")
        reject_sealed_text(self.teacher_source, "teacher_source")
        require(self.contact_tier in CONTACT_TIER_POLICY, f"contact_tier_invalid:{self.candidate_id}")
        require(math.isfinite(self.true_r8) and math.isfinite(self.true_r9), f"train_truth_nonfinite:{self.candidate_id}")


@dataclass(frozen=True)
class PartitionAudit:
    row_count: int
    parent_count: int
    train_rows: int
    score_rows: int
    train_parents: int
    score_parents: int
    identity_sha256: str


def validate_whole_parent_partition(
    rows: Sequence[Any],
    train_indices: Sequence[int],
    score_indices: Sequence[int],
    manifest: Any,
) -> PartitionAudit:
    """Validate exact row and parent closure without reading score truth."""
    require(bool(rows), "partition_rows_empty")
    train = list(train_indices)
    score = list(score_indices)
    require(bool(train) and bool(score), "partition_role_empty")
    require(len(set(train)) == len(train) and len(set(score)) == len(score), "partition_index_duplicate")
    require(set(train).isdisjoint(score), "partition_index_overlap")
    require(set(train) | set(score) == set(range(len(rows))), "partition_row_closure_failed")
    require(getattr(manifest, "open_only", None) is True, "partition_not_open_only")
    require(getattr(manifest, "v4_f_test32_access_count", None) == 0, "partition_sealed_access_nonzero")

    candidate_ids = [str(row.candidate_id) for row in rows]
    parents = [str(row.parent) for row in rows]
    require(len(set(candidate_ids)) == len(candidate_ids), "partition_candidate_duplicate")
    for candidate in candidate_ids:
        reject_sealed_text(candidate, "candidate_id")
    train_parents = {parents[index] for index in train}
    score_parents = {parents[index] for index in score}
    require(train_parents.isdisjoint(score_parents), "whole_parent_split_leakage")
    require(train_parents == set(manifest.train_parents), "train_parent_manifest_mismatch")
    require(score_parents == set(manifest.score_parents), "score_parent_manifest_mismatch")
    identity = {
        "split_id": str(manifest.split_id),
        "outer_fold": int(manifest.outer_fold),
        "train": sorted((candidate_ids[index], parents[index]) for index in train),
        "score": sorted((candidate_ids[index], parents[index]) for index in score),
        "open_only": True,
        "v4_f_test32_access_count": 0,
    }
    return PartitionAudit(
        row_count=len(rows),
        parent_count=len(set(parents)),
        train_rows=len(train),
        score_rows=len(score),
        train_parents=len(train_parents),
        score_parents=len(score_parents),
        identity_sha256=canonical_sha256(identity),
    )


def extract_open_train_rows(rows: Sequence[Any], train_indices: Sequence[int]) -> tuple[OpenTrainRow, ...]:
    """Read scalar truth only for the training partition."""
    result: list[OpenTrainRow] = []
    for index in train_indices:
        row = rows[index]
        targets = row.targets
        require(len(targets) == 2, f"train_target_shape:{row.candidate_id}")
        value = OpenTrainRow(
            candidate_id=str(row.candidate_id),
            parent_cluster_id=str(row.parent),
            teacher_source=str(row.teacher_source),
            contact_tier=str(row.contact_tier),
            true_r8=float(targets[0]),
            true_r9=float(targets[1]),
        )
        value.validate()
        result.append(value)
    require(len({row.candidate_id for row in result}) == len(result), "train_candidate_duplicate")
    return tuple(result)


@dataclass(frozen=True)
class RankPolicyAdapter:
    module: ModuleType
    path: Path
    sha256: str
    policy_schema: str
    prediction_builder_name: str
    prediction_semantics: str

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> "RankPolicyAdapter":
        module = load_sha_bound_module(
            path,
            expected_sha256,
            logical_name="rank_policy",
            required_attributes=REQUIRED_RANK_API,
        )
        schema = str(getattr(module, "SCHEMA_VERSION", ""))
        require(schema.startswith("pvrig_v2_6_rank_calibration_core_v1"), "rank_policy_schema_incompatible")
        # V1.1 moves rank supervision to exact-min and intentionally may keep
        # the old softmin name only as a fail-closed deprecated function.
        if callable(getattr(module, "build_exact_min_dual_prediction_batch", None)):
            builder = "build_exact_min_dual_prediction_batch"
            semantics = "EXACT_MIN_FROM_DIRECT_R8_R9"
        else:
            require(callable(getattr(module, "build_softmin_dual_prediction_batch", None)), "rank_prediction_builder_missing")
            builder = "build_softmin_dual_prediction_batch"
            semantics = "V1_FP32_NORMALIZED_SOFTMIN_FROM_DIRECT_R8_R9"
        return cls(module, path.resolve(), expected_sha256, schema, builder, semantics)

    def identity(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "schema_version": self.policy_schema,
            "prediction_builder": self.prediction_builder_name,
            "prediction_semantics": self.prediction_semantics,
        }

    def verify_binding(self, path: Path) -> Mapping[str, Any]:
        reject_sealed_text(path, "delta_noise_binding")
        return self.module.verify_frozen_delta_noise_binding(path)

    def admits(self, row: OpenTrainRow) -> bool:
        selector = getattr(self.module, "rank_label_is_admissible", None)
        if callable(selector):
            return bool(selector(
                teacher_source=row.teacher_source,
                contact_tier=row.contact_tier,
                seed_count=row.seed_count,
            ))
        # V1.1 exact-min policy is intentionally V4D/A/multi-seed only.  V1
        # predates this provenance gate and remains supported solely so the
        # integration can be tested before V1.1 is frozen.
        if self.prediction_semantics == "EXACT_MIN_FROM_DIRECT_R8_R9":
            return (
                row.teacher_source == "V4D_OPEN_MULTI_SEED"
                and row.contact_tier == "A"
                and row.seed_count >= 3
            )
        return True

    def make_label(self, row: OpenTrainRow) -> Any:
        if row.teacher_source == "V4D_OPEN_MULTI_SEED":
            docking_evidence_tier = "V4D_MULTI_SEED"
            teacher_reliability = "MULTI_SEED"
            ranking_release = "v4d_open_multi_seed_frozen_v1_1"
        else:
            docking_evidence_tier = f"DUAL_{row.seed_count}_SEED"
            teacher_reliability = docking_evidence_tier
            ranking_release = "final_adaptive_seed"
        available = {
            "candidate_id": row.candidate_id,
            "parent_cluster_id": row.parent_cluster_id,
            "true_r8": row.true_r8,
            "true_r9": row.true_r9,
            "split_role": "TRAIN",
            "teacher_source": row.teacher_source,
            "contact_tier": row.contact_tier,
            "development_reliability_tier": row.contact_tier,
            "docking_evidence_tier": docking_evidence_tier,
            "teacher_reliability": teacher_reliability,
            "ranking_release": ranking_release,
            "seed_count": row.seed_count,
            "teacher_provenance": row.teacher_source,
            "provenance": row.teacher_source,
            "multi_seed": row.seed_count >= 2,
            "is_multi_seed": row.seed_count >= 2,
        }
        signature = inspect.signature(self.module.CandidateLabel)
        unknown_required = [
            name
            for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            and name not in available
        ]
        require(not unknown_required, "rank_candidate_label_interface_unknown:" + ",".join(unknown_required))
        kwargs = {name: available[name] for name in signature.parameters if name in available}
        return self.module.CandidateLabel(**kwargs)

    def make_labels(self, rows: Sequence[OpenTrainRow]) -> tuple[Any, ...]:
        # V1.1 requires the complete scalar train partition so its persisted
        # cache can prove both the rank-eligible V4D subset and the excluded
        # V4H scalar-only strata.  Eligibility controls pair construction, not
        # whether a train label appears in the cache provenance.
        labels = tuple(self.make_label(row) for row in rows)
        require(bool(labels), "rank_policy_admitted_no_labels")
        return labels

    def prediction_batch(self, candidate_ids: Sequence[str], receptor_predictions: Tensor) -> Any:
        builder = getattr(self.module, self.prediction_builder_name)
        return builder(candidate_ids, receptor_predictions)

    def pair_loss(self, prediction_batch: Any, records: Sequence[Any]) -> Tensor:
        return self.module.noise_aware_pairlogit(prediction_batch, records)


@dataclass(frozen=True)
class OuterTrainCalibrationMember:
    candidate_id: str
    parent_cluster_id: str
    outer_fold: int
    heldout_inner_fold: int
    split_role: str = "OUTER_TRAIN"


@dataclass(frozen=True)
class InnerOofCalibrationInput:
    candidate_id: str
    parent_cluster_id: str
    outer_fold: int
    inner_fold: int
    seed: int
    ensemble_id: str
    ensemble_member_id: str
    split_role: str
    predicted_r8: float
    predicted_r9: float
    true_r8: float
    true_r9: float


@dataclass(frozen=True)
class CalibrationFitReceiptV13:
    calibration: Any
    outer_fold: int
    ensemble_id: str
    seeds: tuple[int, ...]
    inner_folds: tuple[int, ...]
    outer_train_candidate_count: int
    outer_train_parent_count: int
    seed_prediction_row_count: int
    ensemble_candidate_count: int
    outer_train_closure_sha256: str
    seed_row_closure_sha256: str
    v4_f_test32_access_count: int = 0

    def apply(self, receptor_predictions: Tensor) -> dict[str, Tensor]:
        return self.calibration.apply(receptor_predictions)

    def to_payload(self) -> dict[str, Any]:
        require(self.v4_f_test32_access_count == 0, "calibration_receipt_sealed_access_nonzero")
        return {
            "schema_version": "pvrig_v2_6_inner_oof_calibration_receipt_v1_3",
            "status": "PASS_EXACT_THREE_SEED_OUTER_TRAIN_INNER_OOF_CLOSURE",
            "outer_fold": self.outer_fold,
            "ensemble_id": self.ensemble_id,
            "seeds": list(self.seeds),
            "inner_folds": list(self.inner_folds),
            "outer_train_candidate_count": self.outer_train_candidate_count,
            "outer_train_parent_count": self.outer_train_parent_count,
            "seed_prediction_row_count": self.seed_prediction_row_count,
            "ensemble_candidate_count": self.ensemble_candidate_count,
            "outer_train_closure_sha256": self.outer_train_closure_sha256,
            "seed_row_closure_sha256": self.seed_row_closure_sha256,
            "calibration": self.calibration.to_payload(),
            "v4_f_test32_access_count": 0,
        }


def fit_fold_local_calibration_from_inner_oof(
    rows: Sequence[InnerOofCalibrationInput],
    *,
    outer_train_members: Sequence[OuterTrainCalibrationMember],
    outer_fold: int,
    outer_score_candidate_ids: Sequence[str],
    outer_score_parent_ids: Sequence[str],
    rank_policy: RankPolicyAdapter,
) -> CalibrationFitReceiptV13:
    """Fit calibration only after exact outer-train, fold and seed closure.

    Every outer-train candidate must have exactly one held-out inner fold and
    exactly the frozen 43/97/193 prediction members.  The three predictions
    are averaged before the already-frozen positive affine calibration is
    fitted.  Candidate and parent closure are both explicit, so a caller
    cannot silently omit hard rows or add an outer-test family.
    """
    require(rank_policy.sha256 == BOUND_RANK_V11_SHA256, "calibration_policy_not_frozen_v1_1")
    require(bool(rows), "inner_oof_calibration_rows_empty")
    require(bool(outer_train_members), "outer_train_calibration_members_empty")
    forbidden = {str(value) for value in outer_score_candidate_ids}
    forbidden_parents = {str(value) for value in outer_score_parent_ids}
    require(len(forbidden) == len(tuple(outer_score_candidate_ids)), "outer_score_candidate_duplicate")
    members: dict[str, OuterTrainCalibrationMember] = {}
    for member in outer_train_members:
        reject_sealed_text(member.candidate_id, "outer_train_candidate_id")
        require(member.candidate_id not in members, f"outer_train_candidate_duplicate:{member.candidate_id}")
        require(member.outer_fold == outer_fold, f"outer_train_outer_fold_mismatch:{member.candidate_id}")
        require(member.heldout_inner_fold in FROZEN_INNER_FOLDS, f"outer_train_inner_fold_invalid:{member.candidate_id}")
        require(member.split_role == "OUTER_TRAIN", f"outer_train_split_role_invalid:{member.candidate_id}")
        require(member.candidate_id not in forbidden, f"outer_test_candidate_in_calibration_members:{member.candidate_id}")
        require(member.parent_cluster_id not in forbidden_parents, f"outer_test_parent_in_calibration_members:{member.parent_cluster_id}")
        members[member.candidate_id] = member
    require(
        {member.heldout_inner_fold for member in members.values()} == set(FROZEN_INNER_FOLDS),
        "inner_fold_coverage_not_exact_0_to_4",
    )
    ensemble_id = f"outer_{outer_fold}_inner_oof_seeds_43_97_193"
    grouped: dict[str, list[InnerOofCalibrationInput]] = {}
    observed_keys: set[tuple[str, int]] = set()
    for row in rows:
        reject_sealed_text(row.candidate_id, "calibration_candidate_id")
        require(row.candidate_id in members, f"non_outer_train_candidate_in_calibration:{row.candidate_id}")
        member = members[row.candidate_id]
        require(row.parent_cluster_id == member.parent_cluster_id, f"calibration_parent_mismatch:{row.candidate_id}")
        require(row.outer_fold == outer_fold, f"calibration_outer_fold_mismatch:{row.candidate_id}")
        require(row.inner_fold == member.heldout_inner_fold, f"calibration_inner_fold_mismatch:{row.candidate_id}")
        require(row.seed in FROZEN_ENSEMBLE_SEEDS, f"calibration_seed_invalid:{row.candidate_id}:{row.seed}")
        require(row.ensemble_id == ensemble_id, f"calibration_ensemble_id_invalid:{row.candidate_id}")
        require(
            row.ensemble_member_id == f"inner_{row.inner_fold}_seed_{row.seed}",
            f"calibration_ensemble_member_invalid:{row.candidate_id}:{row.seed}",
        )
        require(row.split_role == "INNER_OOF_SCORE", f"calibration_split_role_invalid:{row.candidate_id}")
        key = (row.candidate_id, row.seed)
        require(key not in observed_keys, f"calibration_seed_member_duplicate:{row.candidate_id}:{row.seed}")
        observed_keys.add(key)
        require(
            all(math.isfinite(float(value)) for value in (row.predicted_r8, row.predicted_r9, row.true_r8, row.true_r9)),
            f"calibration_value_nonfinite:{row.candidate_id}",
        )
        grouped.setdefault(row.candidate_id, []).append(row)
    require(set(grouped) == set(members), "outer_train_candidate_calibration_closure_mismatch")
    require(len(rows) == len(members) * len(FROZEN_ENSEMBLE_SEEDS), "calibration_seed_row_count_mismatch")
    module = rank_policy.module
    fit_role = str(getattr(module, "CALIBRATION_FIT_ROLE", "OUTER_TRAIN_INNER_OOF"))
    values = []
    for candidate_id in sorted(members):
        candidate_rows = sorted(grouped[candidate_id], key=lambda value: value.seed)
        require(tuple(value.seed for value in candidate_rows) == FROZEN_ENSEMBLE_SEEDS, f"calibration_seed_set_mismatch:{candidate_id}")
        truth_r8 = {round(float(value.true_r8), 12) for value in candidate_rows}
        truth_r9 = {round(float(value.true_r9), 12) for value in candidate_rows}
        require(len(truth_r8) == 1 and len(truth_r9) == 1, f"calibration_truth_disagreement:{candidate_id}")
        member = members[candidate_id]
        values.append(module.CalibrationRow(
            candidate_id=candidate_id,
            parent_cluster_id=member.parent_cluster_id,
            outer_fold=outer_fold,
            fit_role=fit_role,
            predicted_r8=sum(float(value.predicted_r8) for value in candidate_rows) / 3.0,
            predicted_r9=sum(float(value.predicted_r9) for value in candidate_rows) / 3.0,
            true_r8=float(candidate_rows[0].true_r8),
            true_r9=float(candidate_rows[0].true_r9),
        ))
    result = module.fit_fold_local_positive_affine(
        values,
        outer_fold=outer_fold,
        forbidden_candidate_ids=forbidden,
    )
    result.validate()
    member_payload = [asdict(members[value]) for value in sorted(members)]
    row_payload = [asdict(value) for value in sorted(rows, key=lambda item: (item.candidate_id, item.seed))]
    return CalibrationFitReceiptV13(
        calibration=result,
        outer_fold=outer_fold,
        ensemble_id=ensemble_id,
        seeds=FROZEN_ENSEMBLE_SEEDS,
        inner_folds=FROZEN_INNER_FOLDS,
        outer_train_candidate_count=len(members),
        outer_train_parent_count=len({value.parent_cluster_id for value in members.values()}),
        seed_prediction_row_count=len(rows),
        ensemble_candidate_count=len(values),
        outer_train_closure_sha256=canonical_sha256(member_payload),
        seed_row_closure_sha256=canonical_sha256(row_payload),
    )


def _read_bound_tsv(path_value: str | Path, expected_sha256: str, label: str) -> list[dict[str, str]]:
    path = Path(path_value)
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular")
    require(sha256_file(path) == expected_sha256, f"{label}_sha256_mismatch")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"{label}_empty")
    return rows


def _artifact_path(receipt_path: Path, raw_path: Any, label: str) -> Path:
    require(isinstance(raw_path, str) and bool(raw_path), f"{label}_path_missing")
    reject_sealed_text(raw_path, f"{label}_path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = receipt_path.parent / path
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular")
    return path


def _candidate_parent_set_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = sorted(
        (str(row["candidate_id"]), str(row["parent_framework_cluster"]))
        for row in rows
    )
    require(len(payload) == len({candidate for candidate, _parent in payload}), "candidate_set_duplicate")
    return canonical_sha256(payload)


def fit_fold_local_calibration_from_frozen_oof_artifacts(
    *,
    inner_manifest_path: str | Path,
    outer_manifest_path: str | Path,
    teacher_path: str | Path,
    prediction_receipt_paths: Sequence[str | Path],
    outer_fold: int,
    rank_policy: RankPolicyAdapter,
) -> CalibrationFitReceiptV13:
    """Derive calibration membership and values from frozen manifests/artifacts.

    No candidate membership, fold, seed, prediction, or truth value is accepted
    directly from a caller.  Inner/outer memberships come from the frozen split
    manifests; truths come from the frozen teacher; predictions are admitted
    only through checkpoint-bound prediction receipts.
    """
    require(outer_fold in FROZEN_INNER_FOLDS, "calibration_outer_fold_invalid")
    inner_rows = _read_bound_tsv(inner_manifest_path, BOUND_INNER_MANIFEST_SHA256, "inner_manifest")
    outer_rows = _read_bound_tsv(outer_manifest_path, BOUND_OUTER_MANIFEST_SHA256, "outer_manifest")
    teacher_rows = _read_bound_tsv(teacher_path, BOUND_TEACHER_SHA256, "teacher_table")

    inner_outer = [row for row in inner_rows if int(row["outer_fold"]) == outer_fold]
    outer_current = [row for row in outer_rows if int(row["outer_fold"]) == outer_fold]
    require(bool(inner_outer) and bool(outer_current), "calibration_fold_manifest_empty")
    outer_train = {row["candidate_id"]: row for row in outer_current if row["candidate_role"] == "train"}
    outer_score = {row["candidate_id"]: row for row in outer_current if row["candidate_role"] == "score"}
    require(set(outer_train).isdisjoint(outer_score), "outer_manifest_role_overlap")
    score_rows = [row for row in inner_outer if row["candidate_role"] == "score"]
    require({row["candidate_id"] for row in score_rows} == set(outer_train), "inner_score_outer_train_closure")
    require(len(score_rows) == len(outer_train), "inner_score_candidate_duplicate")
    members = [
        OuterTrainCalibrationMember(
            candidate_id=row["candidate_id"],
            parent_cluster_id=row["parent_framework_cluster"],
            outer_fold=outer_fold,
            heldout_inner_fold=int(row["inner_fold"]),
        )
        for row in score_rows
    ]
    member_by_candidate = {value.candidate_id: value for value in members}
    require(all(
        outer_train[candidate]["parent_framework_cluster"] == member.parent_cluster_id
        for candidate, member in member_by_candidate.items()
    ), "inner_outer_parent_mismatch")

    truth_by_candidate = {row["candidate_id"]: row for row in teacher_rows}
    require(set(outer_train) | set(outer_score) == set(truth_by_candidate), "outer_teacher_candidate_closure")
    required_receipts = {
        (inner_fold, seed) for inner_fold in FROZEN_INNER_FOLDS for seed in FROZEN_ENSEMBLE_SEEDS
    }
    require(len(prediction_receipt_paths) == len(required_receipts), "oof_prediction_receipt_count_mismatch")
    observed_receipts: set[tuple[int, int]] = set()
    calibration_rows: list[InnerOofCalibrationInput] = []
    for raw_receipt_path in prediction_receipt_paths:
        receipt_path = Path(raw_receipt_path)
        require(receipt_path.is_file() and not receipt_path.is_symlink(), "oof_prediction_receipt_not_regular")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise Real1507IntegrationError(f"oof_prediction_receipt_invalid_json:{error}") from error
        require(isinstance(receipt, dict), "oof_prediction_receipt_not_object")
        require(receipt.get("schema_version") == OOF_PREDICTION_RECEIPT_SCHEMA, "oof_prediction_receipt_schema")
        require(receipt.get("status") == "PASS_CHECKPOINT_BOUND_INNER_OOF_PREDICTIONS", "oof_prediction_receipt_status")
        require(receipt.get("trainer_schema_version") == SCHEMA_VERSION, "oof_prediction_receipt_trainer_schema")
        require(receipt.get("source_inner_manifest_sha256") == BOUND_INNER_MANIFEST_SHA256, "oof_prediction_receipt_inner_manifest")
        require(receipt.get("source_outer_manifest_sha256") == BOUND_OUTER_MANIFEST_SHA256, "oof_prediction_receipt_outer_manifest")
        require(receipt.get("source_teacher_sha256") == BOUND_TEACHER_SHA256, "oof_prediction_receipt_teacher")
        require(receipt.get("v4_f_test32_access_count") == 0, "oof_prediction_receipt_sealed_access")
        require(receipt.get("outer_test_truth_access_count") == 0, "oof_prediction_receipt_outer_truth_access")
        require(int(receipt.get("outer_fold", -1)) == outer_fold, "oof_prediction_receipt_outer_fold")
        inner_fold = int(receipt.get("inner_fold", -1))
        seed = int(receipt.get("seed", -1))
        key = (inner_fold, seed)
        require(key in required_receipts, "oof_prediction_receipt_fold_seed_invalid")
        require(key not in observed_receipts, "oof_prediction_receipt_fold_seed_duplicate")
        observed_receipts.add(key)

        expected_score_rows = [
            row for row in inner_outer
            if int(row["inner_fold"]) == inner_fold and row["candidate_role"] == "score"
        ]
        expected_train_rows = [
            row for row in inner_outer
            if int(row["inner_fold"]) == inner_fold and row["candidate_role"] == "train"
        ]
        expected_score_sha = _candidate_parent_set_sha256(expected_score_rows)
        expected_train_sha = _candidate_parent_set_sha256(expected_train_rows)
        require(receipt.get("score_candidate_set_sha256") == expected_score_sha, "oof_prediction_receipt_score_set")
        require(receipt.get("train_candidate_set_sha256") == expected_train_sha, "oof_prediction_receipt_train_set")

        checkpoint_receipt_path = _artifact_path(receipt_path, receipt.get("checkpoint_receipt_path"), "oof_checkpoint_receipt")
        require(sha256_file(checkpoint_receipt_path) == receipt.get("checkpoint_receipt_sha256"), "oof_checkpoint_receipt_sha256")
        checkpoint_receipt = json.loads(checkpoint_receipt_path.read_text(encoding="utf-8"))
        require(checkpoint_receipt.get("schema_version") == "pvrig_v2_6_inner_checkpoint_receipt_v1_3", "oof_checkpoint_receipt_schema")
        require(checkpoint_receipt.get("status") == "PASS_INNER_TRAIN_CHECKPOINT_FROZEN", "oof_checkpoint_receipt_status")
        for field, expected in (
            ("outer_fold", outer_fold), ("inner_fold", inner_fold), ("seed", seed),
            ("train_candidate_set_sha256", expected_train_sha),
            ("score_candidate_set_sha256", expected_score_sha),
            ("source_inner_manifest_sha256", BOUND_INNER_MANIFEST_SHA256),
            ("source_outer_manifest_sha256", BOUND_OUTER_MANIFEST_SHA256),
            ("source_teacher_sha256", BOUND_TEACHER_SHA256),
            ("trainer_schema_version", SCHEMA_VERSION),
            ("v4_f_test32_access_count", 0),
            ("outer_test_truth_access_count", 0),
        ):
            require(checkpoint_receipt.get(field) == expected, f"oof_checkpoint_receipt_field:{field}")
        checkpoint_path = _artifact_path(checkpoint_receipt_path, checkpoint_receipt.get("checkpoint_path"), "oof_checkpoint")
        require(sha256_file(checkpoint_path) == checkpoint_receipt.get("checkpoint_sha256"), "oof_checkpoint_sha256")

        prediction_path = _artifact_path(receipt_path, receipt.get("prediction_path"), "oof_prediction")
        require(sha256_file(prediction_path) == receipt.get("prediction_sha256"), "oof_prediction_sha256")
        with prediction_path.open("r", encoding="utf-8", newline="") as handle:
            predictions = list(csv.DictReader(handle, delimiter="\t"))
        require(len(predictions) == len(expected_score_rows), "oof_prediction_row_count")
        require(receipt.get("prediction_row_count") == len(predictions), "oof_prediction_receipt_row_count")
        prediction_by_candidate = {row["candidate_id"]: row for row in predictions}
        require(len(prediction_by_candidate) == len(predictions), "oof_prediction_candidate_duplicate")
        require(set(prediction_by_candidate) == {row["candidate_id"] for row in expected_score_rows}, "oof_prediction_candidate_closure")
        for candidate_id, prediction in prediction_by_candidate.items():
            member = member_by_candidate[candidate_id]
            require(prediction["parent_framework_cluster"] == member.parent_cluster_id, "oof_prediction_parent_mismatch")
            truth = truth_by_candidate[candidate_id]
            calibration_rows.append(InnerOofCalibrationInput(
                candidate_id=candidate_id,
                parent_cluster_id=member.parent_cluster_id,
                outer_fold=outer_fold,
                inner_fold=inner_fold,
                seed=seed,
                ensemble_id=f"outer_{outer_fold}_inner_oof_seeds_43_97_193",
                ensemble_member_id=f"inner_{inner_fold}_seed_{seed}",
                split_role="INNER_OOF_SCORE",
                predicted_r8=float(prediction["predicted_r8"]),
                predicted_r9=float(prediction["predicted_r9"]),
                true_r8=float(truth["R_8X6B"]),
                true_r9=float(truth["R_9E6Y"]),
            ))
    require(observed_receipts == required_receipts, "oof_prediction_receipt_fold_seed_closure")
    return fit_fold_local_calibration_from_inner_oof(
        calibration_rows,
        outer_train_members=members,
        outer_fold=outer_fold,
        outer_score_candidate_ids=tuple(sorted(outer_score)),
        outer_score_parent_ids=tuple(sorted({row["parent_framework_cluster"] for row in outer_score.values()})),
        rank_policy=rank_policy,
    )


@dataclass(frozen=True)
class V26TrainerConfig:
    integration_lane: str
    fixed_epochs: int = 1
    gradient_accumulation: int = 2
    lambda_rank: float = 0.10
    precision: str = "fp32"
    base_seed: int = 43
    outer_fold: int = 0
    inner_fold: int = 0
    expected_main_batches_per_epoch: int = 1
    rank_trust_anchor_set_receipt_path: str = ""
    rank_trust_anchor_dir: str = ""
    physical_gpu_index: int = -1
    logical_cuda_index: int = -1

    def validate(self) -> None:
        require(self.integration_lane in LANES, f"integration_lane_invalid:{self.integration_lane}")
        require(self.fixed_epochs > 0, "fixed_epochs_invalid")
        require(self.gradient_accumulation > 0, "gradient_accumulation_invalid")
        require(math.isfinite(self.lambda_rank) and self.lambda_rank >= 0.0, "lambda_rank_invalid")
        require(self.precision in {"fp32", "bf16"}, "precision_invalid")
        require(self.outer_fold >= 0 and self.inner_fold >= 0, "fold_invalid")
        require(self.expected_main_batches_per_epoch > 0, "expected_main_batches_invalid")
        require(bool(self.rank_trust_anchor_set_receipt_path), "external_rank_trust_anchor_set_receipt_path_missing")
        require(bool(self.rank_trust_anchor_dir), "external_rank_trust_anchor_dir_missing")
        reject_sealed_text(self.rank_trust_anchor_set_receipt_path, "rank_trust_anchor_set_receipt_path")
        reject_sealed_text(self.rank_trust_anchor_dir, "rank_trust_anchor_dir")
        require(self.physical_gpu_index >= -1 and self.logical_cuda_index >= -1, "cuda_device_mapping_index_invalid")

    @property
    def model_lane(self) -> str:
        return MODEL_LANE_E

    @property
    def scalar_steps_per_epoch(self) -> int:
        return math.ceil(self.expected_main_batches_per_epoch / self.gradient_accumulation)


def _model_contact_gradient_mode(model: nn.Module) -> str:
    return str(model.head.config.contact_encoder_gradient)


def validate_model_lane(model: nn.Module, config: V26TrainerConfig) -> None:
    contact_enabled = bool(model.head.config.enable_contact_evidence)
    require(contact_enabled, "canonical_e_capable_model_required")
    expected_mode = "shared" if config.integration_lane == LANE_F else "detached"
    require(_model_contact_gradient_mode(model) == expected_mode, "model_contact_gradient_mode_mismatch")
    if contact_enabled:
        # The V2.5 terminal is deterministic.  If a future contact-only module
        # adds dropout, executing the immutable V2.5 forward would advance the
        # scalar RNG before the isolated contact closure and violate B/E
        # trajectory comparability.  Fail closed until a skip-contact forward
        # API is explicitly versioned.
        contact_modules = list(model.head.contact_interaction.modules()) + list(
            model.head.contact_calibration.modules()
        )
        require(
            not any(isinstance(module, nn.Dropout) for module in contact_modules),
            "stochastic_contact_terminal_requires_skip_contact_forward_api",
        )


def validate_v25_input_firewall(v25_api: ModuleType, model: nn.Module) -> dict[str, Any]:
    forbidden = tuple(str(value) for value in v25_api.FORBIDDEN_NEURAL_INPUT_FIELDS)
    wrapper_fields = set(inspect.signature(model.forward).parameters)
    require(not (wrapper_fields & set(forbidden)), "forbidden_model_forward_feature")
    required = set(getattr(v25_api, "NEURAL_REQUIRED_BATCH_FIELDS", ()))
    require(bool(required), "v25_neural_allowlist_empty")
    require(not (required & set(forbidden)), "v25_allowlist_forbidden_overlap")
    return {
        "positive_allowlist": sorted(required | {"target_graphs"}),
        "forbidden": sorted(forbidden),
        "M2_126D_ID_pose_features_forwarded": 0,
    }


def _module_file_sha256(module: ModuleType, logical_name: str) -> str:
    path_value = getattr(module, "__file__", None)
    require(path_value is not None, f"bound_module_file_missing:{logical_name}")
    path = Path(path_value)
    require(path.is_file() and not path.is_symlink(), f"bound_module_not_regular:{logical_name}")
    return sha256_file(path)


def validate_bound_training_dependencies(
    v25_api: ModuleType,
    optimizer_api: ModuleType,
    model: nn.Module,
    rank_policy: RankPolicyAdapter,
    delta_noise_binding_path: Path,
) -> dict[str, str]:
    observed_v25 = _module_file_sha256(v25_api, "v25_trainer")
    observed_optimizer = _module_file_sha256(optimizer_api, "optimizer_core")
    model_module = sys.modules.get(model.__class__.__module__)
    require(isinstance(model_module, ModuleType), "v25_model_module_missing")
    observed_model = _module_file_sha256(model_module, "v25_model")
    require(observed_v25 == BOUND_V25_TRAINER_SHA256, "bound_v25_trainer_sha256_mismatch")
    require(observed_optimizer == BOUND_OPTIMIZER_CORE_SHA256, "bound_optimizer_core_sha256_mismatch")
    require(observed_model == BOUND_V25_MODEL_SHA256, "bound_v25_model_sha256_mismatch")
    require(rank_policy.sha256 == BOUND_RANK_V11_SHA256, "formal_rank_policy_not_frozen_v1_1")
    require(rank_policy.prediction_semantics == "EXACT_MIN_FROM_DIRECT_R8_R9", "formal_rank_policy_not_exact_min")
    require(sha256_file(delta_noise_binding_path) == BOUND_DELTA_NOISE_SHA256, "bound_delta_noise_sha256_mismatch")
    return {
        "v25_trainer_sha256": observed_v25,
        "v25_model_sha256": observed_model,
        "optimizer_core_sha256": observed_optimizer,
        "rank_v1_1_core_sha256": rank_policy.sha256,
        "delta_noise_binding_sha256": BOUND_DELTA_NOISE_SHA256,
    }


def validate_contact_tier_batch(
    batch: Mapping[str, Any], candidate_tiers: Mapping[str, str]
) -> dict[str, int]:
    candidate_ids = batch.get("candidate_ids")
    require(isinstance(candidate_ids, Sequence) and not isinstance(candidate_ids, (str, bytes)), "batch_candidate_ids_missing")
    marginal = batch.get("marginal_tier_weights")
    pair = batch.get("pair_tier_weights")
    require(isinstance(marginal, Tensor) and marginal.shape == (len(candidate_ids),), "marginal_tier_weight_shape")
    require(isinstance(pair, Tensor) and pair.shape == (len(candidate_ids),), "pair_tier_weight_shape")
    counts = {tier: 0 for tier in CONTACT_TIER_POLICY}
    for index, candidate_id in enumerate(candidate_ids):
        candidate = str(candidate_id)
        require(candidate in candidate_tiers, f"candidate_tier_missing:{candidate}")
        tier = candidate_tiers[candidate]
        require(tier in CONTACT_TIER_POLICY, f"candidate_tier_invalid:{candidate}")
        expected = CONTACT_TIER_POLICY[tier]
        require(
            math.isclose(float(marginal[index]), float(expected["marginal"]), rel_tol=0.0, abs_tol=1e-7),
            f"marginal_tier_policy_mismatch:{candidate}",
        )
        require(
            math.isclose(float(pair[index]), float(expected["pair"]), rel_tol=0.0, abs_tol=1e-7),
            f"pair_tier_policy_mismatch:{candidate}",
        )
        counts[tier] += 1
    return counts


def _mean_scalars(values: Sequence[Tensor], name: str) -> Tensor:
    require(bool(values), f"scalar_sequence_empty:{name}")
    result = torch.stack([value.float().reshape(()) for value in values]).mean()
    require_finite(result, f"mean_nonfinite:{name}")
    return result


def _raw_hierarchy_mass(batch: Mapping[str, Any]) -> float:
    candidate_ids = batch.get("candidate_ids")
    require(isinstance(candidate_ids, Sequence) and not isinstance(candidate_ids, (str, bytes)), "batch_candidate_ids_missing")
    count = len(candidate_ids)
    weights = batch.get("hierarchy_weights")
    if weights is None:
        return float(count)
    require(isinstance(weights, Tensor) and weights.shape == (count,), "hierarchy_weight_shape")
    require_finite(weights, "hierarchy_weight_nonfinite")
    require(bool(torch.all(weights > 0.0)), "hierarchy_weight_nonpositive")
    return float(weights.float().sum().detach().cpu())


def _weighted_window_mean(values: Sequence[Tensor], masses: Sequence[float], name: str) -> Tensor:
    require(len(values) == len(masses) and bool(values), f"weighted_window_empty_or_length:{name}")
    require(all(math.isfinite(value) and value >= 0.0 for value in masses), f"weighted_window_mass_invalid:{name}")
    total = float(sum(masses))
    if total <= 0.0:
        result = torch.stack([value.float().reshape(()) for value in values]).sum() * 0.0
    else:
        result = sum(
            value.float().reshape(()) * (float(mass) / total)
            for value, mass in zip(values, masses)
        )
    require_finite(result, f"weighted_window_nonfinite:{name}")
    return result


def _contact_effective_hierarchy_mass(batch: Mapping[str, Any], component: str) -> float:
    """Return the exact denominator mass used by one contact component.

    V2.5 normalizes hierarchy weights inside each microbatch.  Multiplying the
    returned microbatch mean by this raw hierarchy*tier*eligibility mass and
    normalizing across a window reproduces the loss of the concatenated
    candidate set, including uneven and partial microbatches.
    """
    require(component in {"marginal", "pair"}, "contact_mass_component_invalid")
    candidate_ids = batch.get("candidate_ids")
    require(isinstance(candidate_ids, Sequence) and not isinstance(candidate_ids, (str, bytes)), "batch_candidate_ids_missing")
    count = len(candidate_ids)
    hierarchy = batch.get("hierarchy_weights")
    if hierarchy is None:
        hierarchy_value = torch.ones(count, dtype=torch.float32)
    else:
        require(isinstance(hierarchy, Tensor) and hierarchy.shape == (count,), "hierarchy_weight_shape")
        hierarchy_value = hierarchy.detach().float().cpu()
    tier = batch.get(f"{component}_tier_weights")
    require(isinstance(tier, Tensor) and tier.shape == (count,), f"{component}_tier_weight_shape")
    availability: list[Tensor] = []
    if component == "marginal":
        targets = batch.get("marginal_targets")
        masks = batch.get("marginal_mask")
        uncertainty = batch.get("marginal_uncertainty")
        require(
            isinstance(targets, Tensor) and isinstance(masks, Tensor) and isinstance(uncertainty, Tensor),
            "marginal_targets_missing",
        )
        for receptor_index in range(2):
            target = targets[:, :, receptor_index].detach().float().cpu()
            mask = masks[:, :, receptor_index].detach().float().cpu()
            unc = uncertainty[:, :, receptor_index].detach().float().cpu()
            weighted = (unc * mask).reshape(count, -1)
            flat_target = target.reshape(count, -1)
            availability.append(
                ((weighted * flat_target).sum(1) > 1e-8)
                | ((weighted * (1.0 - flat_target)).sum(1) > 1e-8)
            )
    else:
        for receptor in ("8x6b", "9e6y"):
            targets = batch.get(f"pair_targets_{receptor}")
            masks = batch.get(f"pair_mask_{receptor}")
            uncertainty = batch.get(f"pair_uncertainty_{receptor}")
            require(
                isinstance(targets, Tensor) and isinstance(masks, Tensor) and isinstance(uncertainty, Tensor),
                f"pair_targets_missing:{receptor}",
            )
            target = targets.detach().float().cpu().reshape(count, -1)
            weighted = (uncertainty.detach().float().cpu() * masks.detach().float().cpu()).reshape(count, -1)
            availability.append(
                ((weighted * target).sum(1) > 1e-8)
                | ((weighted * (1.0 - target)).sum(1) > 1e-8)
            )
    eligible = torch.stack(availability, dim=1).sum(1) > 0
    mass = (hierarchy_value * tier.detach().float().cpu() * eligible.float()).sum()
    require_finite(mass, f"{component}_effective_mass_nonfinite")
    return float(mass)


def _detach_tree(value: Any) -> Any:
    if isinstance(value, Tensor):
        return value.detach()
    if isinstance(value, Mapping):
        return {key: _detach_tree(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_detach_tree(item) for item in value)
    if isinstance(value, list):
        return [_detach_tree(item) for item in value]
    return value


def _contact_payload(
    output: Mapping[str, Tensor], batch: Mapping[str, Any], *, detached: bool
) -> dict[str, Any]:
    payload = {
        "vhh_states": output["vhh_graph_states"],
        "target_states_8x6b": output["target_states_8x6b"],
        "target_states_9e6y": output["target_states_9e6y"],
        "residue_mask": batch["residue_mask"],
        "batch": batch,
    }
    return _detach_tree(payload) if detached else payload


def _contact_only_output(model: nn.Module, payload: Mapping[str, Any]) -> dict[str, Tensor]:
    head = model.head
    require(head.contact_interaction is not None and head.contact_calibration is not None, "contact_module_missing")
    residue_mask = payload["residue_mask"]
    contact_logits: dict[str, Tensor] = {}
    for receptor_index, receptor in enumerate(("8x6b", "9e6y")):
        target = payload[f"target_states_{receptor}"]
        raw = head.contact_interaction(payload["vhh_states"], residue_mask, target)
        contact_logits[receptor] = head.contact_calibration(raw, receptor_index).masked_fill(
            ~residue_mask.unsqueeze(-1), -1e4
        )
    marginal = torch.stack(
        [
            torch.logsumexp(contact_logits[receptor], dim=-1)
            - math.log(contact_logits[receptor].shape[-1])
            for receptor in ("8x6b", "9e6y")
        ],
        dim=-1,
    )
    batch_size = len(residue_mask)
    # Scalar values are placeholders only.  The returned contact component has
    # no dependency on them, and they contain no score-partition truth.
    receptor = torch.zeros((batch_size, 2), device=residue_mask.device, dtype=torch.float32)
    return {
        "receptor_predictions": receptor,
        "marginal_contact_logits": marginal,
        "contact_logits_8x6b": contact_logits["8x6b"],
        "contact_logits_9e6y": contact_logits["9e6y"],
    }


def _iter_windows(values: Iterable[Any], size: int) -> Iterable[list[Any]]:
    window: list[Any] = []
    for value in values:
        window.append(value)
        if len(window) == size:
            yield window
            window = []
    if window:
        yield window


def _rank_endpoint_predictions(
    *,
    records: Sequence[Any],
    candidate_to_index: Mapping[str, int],
    batch_factory: Callable[[Sequence[int], bool, int], Iterable[Mapping[str, Any]]],
    epoch: int,
    model: nn.Module,
    model_lane: str,
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    device: torch.device,
    precision: str,
    v25_api: ModuleType,
    rank_policy: RankPolicyAdapter,
) -> tuple[Any, int]:
    endpoints = sorted(
        {str(record.left_candidate_id) for record in records}
        | {str(record.right_candidate_id) for record in records}
    )
    require(all(candidate in candidate_to_index for candidate in endpoints), "rank_endpoint_not_in_train_partition")
    observed_ids: list[str] = []
    predictions: list[Tensor] = []
    for raw_batch in batch_factory([candidate_to_index[value] for value in endpoints], False, epoch):
        batch = v25_api.move_to_device(raw_batch, device)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
            output = v25_api.forward_lane(model, model_lane, batch, target_graphs)
        receptor = output["receptor_predictions"].float()
        require(receptor.ndim == 2 and receptor.shape[1] == 2, "rank_receptor_prediction_shape")
        observed_ids.extend(str(value) for value in raw_batch["candidate_ids"])
        predictions.append(receptor)
    require(observed_ids == endpoints, "rank_endpoint_batch_order_or_closure")
    receptor_predictions = torch.cat(predictions, dim=0)
    return rank_policy.prediction_batch(observed_ids, receptor_predictions), len(observed_ids)


def _optimizer_state_finite(optimizers: Sequence[Any]) -> None:
    for optimizer in optimizers:
        for state in optimizer.state.values():
            for key, value in state.items():
                if isinstance(value, Tensor):
                    require_finite(value, f"optimizer_state_nonfinite:{key}")


def _optimizer_state_sha256(model: nn.Module, optimizers: Sequence[Any]) -> str:
    """Hash optimizer state by stable model parameter name, never object id."""
    digest = hashlib.sha256()
    names_by_id = {id(parameter): name for name, parameter in model.named_parameters()}
    require(len(names_by_id) == len(tuple(model.named_parameters())), "model_parameter_name_not_unique")
    for optimizer_index, optimizer in enumerate(optimizers):
        digest.update(f"optimizer:{optimizer_index}\0".encode("ascii"))
        named_states = []
        for parameter, state in optimizer.state.items():
            require(id(parameter) in names_by_id, "optimizer_parameter_not_in_model")
            named_states.append((names_by_id[id(parameter)], parameter, state))
        for parameter_name, parameter, state in sorted(named_states, key=lambda item: item[0]):
            digest.update(f"parameter:{parameter_name}:{tuple(parameter.shape)}\0".encode("utf-8"))
            for key, value in sorted(state.items(), key=lambda item: str(item[0])):
                digest.update(str(key).encode("utf-8") + b"\0")
                if isinstance(value, Tensor):
                    digest.update(
                        value.detach().contiguous().cpu().reshape(-1).view(torch.uint8).numpy().tobytes()
                    )
                else:
                    digest.update(repr(value).encode("utf-8"))
                digest.update(b"\0")
    return digest.hexdigest()


def load_external_rank_trust_anchor(
    *,
    config: V26TrainerConfig,
    rank_policy: RankPolicyAdapter,
    rank_labels: Sequence[Any],
) -> dict[str, Any]:
    """Validate one anchor through the hard-bound frozen 25-anchor receipt."""
    receipt_path = Path(config.rank_trust_anchor_set_receipt_path)
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "external_rank_trust_anchor_set_receipt_not_regular")
    require(
        sha256_file(receipt_path) == BOUND_RANK_TRUST_ANCHOR_SET_RECEIPT_SHA256,
        "external_rank_trust_anchor_set_receipt_sha256_mismatch",
    )
    try:
        set_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Real1507IntegrationError(f"external_rank_trust_anchor_set_receipt_invalid_json:{error}") from error
    require(isinstance(set_receipt, dict), "external_rank_trust_anchor_set_receipt_not_object")
    require(set_receipt.get("schema_version") == RANK_TRUST_ANCHOR_SET_SCHEMA, "external_rank_trust_anchor_set_receipt_schema")
    require(set_receipt.get("status") == "PASS_25_EXTERNAL_PRETRAINING_TRUST_ANCHORS_FROZEN", "external_rank_trust_anchor_set_receipt_status")
    require(set_receipt.get("partition_count") == 25, "external_rank_trust_anchor_set_partition_count")
    require(set_receipt.get("rank_core_sha256") == BOUND_RANK_V11_SHA256, "external_rank_trust_anchor_set_rank_core")
    require(set_receipt.get("source_teacher_sha256") == BOUND_TEACHER_SHA256, "external_rank_trust_anchor_set_teacher")
    require(set_receipt.get("source_inner_manifest_sha256") == BOUND_INNER_MANIFEST_SHA256, "external_rank_trust_anchor_set_inner_manifest")
    require(set_receipt.get("v4_f_test32_access_count") == 0, "external_rank_trust_anchor_set_sealed_access")
    files = set_receipt.get("files")
    require(isinstance(files, dict) and len(files) == 25, "external_rank_trust_anchor_set_files")
    expected_names = {
        f"outer_{outer}_inner_{inner}.rank_trust_anchor.json"
        for outer in FROZEN_INNER_FOLDS for inner in FROZEN_INNER_FOLDS
    }
    require(set(files) == expected_names, "external_rank_trust_anchor_set_file_closure")
    filename = f"outer_{config.outer_fold}_inner_{config.inner_fold}.rank_trust_anchor.json"
    require(filename in files and valid_sha256(files[filename]), "external_rank_trust_anchor_set_partition_missing")
    anchor_dir = Path(config.rank_trust_anchor_dir)
    require(anchor_dir.is_dir() and not anchor_dir.is_symlink(), "external_rank_trust_anchor_dir_not_regular")
    path = anchor_dir / filename
    require(path.is_file() and not path.is_symlink(), "external_rank_trust_anchor_not_regular")
    observed_file_sha = sha256_file(path)
    require(observed_file_sha == files[filename], "external_rank_trust_anchor_file_sha256_mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Real1507IntegrationError(f"external_rank_trust_anchor_invalid_json:{error}") from error
    require(isinstance(payload, dict), "external_rank_trust_anchor_not_object")
    require(payload.get("schema_version") == RANK_TRUST_ANCHOR_SCHEMA, "external_rank_trust_anchor_schema")
    require(payload.get("status") == "FROZEN_EXTERNAL_PRETRAINING_TRUST_ANCHOR", "external_rank_trust_anchor_status")
    require(payload.get("created_before_runtime") is True, "external_rank_trust_anchor_not_preruntime")
    require(payload.get("outer_fold") == config.outer_fold, "external_rank_trust_anchor_outer_fold")
    require(payload.get("inner_fold") == config.inner_fold, "external_rank_trust_anchor_inner_fold")
    require(payload.get("v4_f_test32_access_count") == 0, "external_rank_trust_anchor_sealed_access")
    expected_split = payload.get("training_split_sha256")
    expected_labels = payload.get("label_sha256")
    require(valid_sha256(expected_split) and valid_sha256(expected_labels), "external_rank_trust_anchor_content_sha_invalid")
    require(payload.get("source_teacher_sha256") == BOUND_TEACHER_SHA256, "external_rank_trust_anchor_teacher_sha_invalid")
    require(payload.get("source_inner_manifest_sha256") == BOUND_INNER_MANIFEST_SHA256, "external_rank_trust_anchor_manifest_sha_invalid")
    require(payload.get("rank_core_sha256") == BOUND_RANK_V11_SHA256, "external_rank_trust_anchor_rank_core_sha_invalid")
    observed_split = rank_policy.module.compute_training_split_sha256(
        rank_labels, config.outer_fold, config.inner_fold
    )
    observed_labels = rank_policy.module.compute_label_sha256(rank_labels)
    require(observed_split == expected_split, "external_training_split_sha256_mismatch")
    require(observed_labels == expected_labels, "external_label_sha256_mismatch")
    require(payload.get("scalar_train_label_count") == len(rank_labels), "external_rank_trust_anchor_label_count")
    return {
        "schema_version": RANK_TRUST_ANCHOR_SCHEMA,
        "status": "PASS_EXTERNAL_TRUST_ANCHOR_VALIDATED",
        "path": str(path.resolve()),
        "anchor_set_receipt_path": str(receipt_path.resolve()),
        "anchor_set_receipt_sha256": BOUND_RANK_TRUST_ANCHOR_SET_RECEIPT_SHA256,
        "file_sha256": observed_file_sha,
        "training_split_sha256": expected_split,
        "label_sha256": expected_labels,
        "source_teacher_sha256": payload["source_teacher_sha256"],
        "source_inner_manifest_sha256": payload["source_inner_manifest_sha256"],
        "scalar_train_label_count": len(rank_labels),
        "created_before_runtime": True,
        "v4_f_test32_access_count": 0,
    }


def _build_epoch_pair_cache(
    *,
    rank_policy: RankPolicyAdapter,
    rank_labels: Sequence[Any],
    binding_receipt: Mapping[str, Any],
    config: V26TrainerConfig,
    epoch: int,
    forbidden_candidate_ids: Sequence[str],
    external_trust_anchor: Mapping[str, Any],
) -> Any:
    module = rank_policy.module
    split_sha = str(external_trust_anchor["training_split_sha256"])
    label_sha = str(external_trust_anchor["label_sha256"])
    cache = module.build_parent_pair_epoch_cache(
        rank_labels,
        base_seed=config.base_seed,
        outer_fold=config.outer_fold,
        inner_fold=config.inner_fold,
        epoch=epoch,
        scalar_optimizer_steps=config.scalar_steps_per_epoch,
        binding_receipt=binding_receipt,
        expected_training_split_sha256=split_sha,
        expected_label_sha256=label_sha,
        forbidden_candidate_ids=forbidden_candidate_ids,
    )
    cache.verify()
    return cache


def train_open_partition_fixed_epochs(
    *,
    model: nn.Module,
    rows: Sequence[Any],
    manifest: Any,
    train_indices: Sequence[int],
    score_indices: Sequence[int],
    batch_factory: Callable[[Sequence[int], bool, int], Iterable[Mapping[str, Any]]],
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    v25_api: ModuleType,
    optimizer_api: ModuleType,
    rank_policy: RankPolicyAdapter,
    delta_noise_binding_path: Path,
    scalar_loss_config: Any,
    contact_loss_config: Any,
    role_optimizer_config: Any,
    config: V26TrainerConfig,
    device_name: str = "cpu",
) -> dict[str, Any]:
    """Train one already-selected open whole-parent partition without metrics."""
    config.validate()
    for name in REQUIRED_V25_API:
        require(hasattr(v25_api, name), f"v25_api_missing:{name}")
    for name in REQUIRED_OPTIMIZER_API:
        require(hasattr(optimizer_api, name), f"optimizer_api_missing:{name}")
    dependency_hashes = validate_bound_training_dependencies(
        v25_api, optimizer_api, model, rank_policy, delta_noise_binding_path
    )
    audit = validate_whole_parent_partition(rows, train_indices, score_indices, manifest)
    validate_model_lane(model, config)
    require(
        float(getattr(scalar_loss_config, "marginal_weight")) == 0.0
        and float(getattr(scalar_loss_config, "pair_weight")) == 0.0,
        "scalar_closure_contact_weights_must_be_zero",
    )
    contact_ablation_mode = "SCALAR_ONLY"
    if config.integration_lane != LANE_B:
        contact_ablation_mode = validate_contact_ablation_weights(
            float(getattr(contact_loss_config, "marginal_weight")),
            float(getattr(contact_loss_config, "pair_weight")),
        )
    require(
        float(getattr(role_optimizer_config, "kappa")) == FROZEN_CONTACT_SHARED_KAPPA,
        "shared_contact_kappa_not_frozen",
    )
    require(
        float(getattr(role_optimizer_config, "lambda_contact_shared")) == FROZEN_CONTACT_SHARED_LAMBDA,
        "shared_contact_lambda_not_frozen",
    )
    firewall = validate_v25_input_firewall(v25_api, model)
    train_rows = extract_open_train_rows(rows, train_indices)
    candidate_to_index = {str(rows[index].candidate_id): index for index in train_indices}
    candidate_tiers = {row.candidate_id: row.contact_tier for row in train_rows}
    forbidden = [str(rows[index].candidate_id) for index in score_indices]
    rank_labels = rank_policy.make_labels(train_rows)
    require(all(str(label.candidate_id) in candidate_to_index for label in rank_labels), "rank_label_not_in_train")
    rank_eligible_count = sum(bool(getattr(label, "rank_eligible", True)) for label in rank_labels)
    require(rank_eligible_count > 0, "rank_policy_no_eligible_train_labels")
    binding_receipt = rank_policy.verify_binding(delta_noise_binding_path)
    rank_trust_anchor = load_external_rank_trust_anchor(
        config=config,
        rank_policy=rank_policy,
        rank_labels=rank_labels,
    )

    device = torch.device(device_name)
    if device.type == "cuda":
        require(config.physical_gpu_index >= 0 and config.logical_cuda_index >= 0, "cuda_device_mapping_missing")
        logical = torch.cuda.current_device() if device.index is None else int(device.index)
        require(logical == config.logical_cuda_index, "logical_cuda_index_mismatch")
        visible = tuple(
            int(value.strip())
            for value in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
            if value.strip()
        )
        require(len(visible) > logical, "cuda_visible_devices_mapping_missing")
        require(visible[logical] == config.physical_gpu_index, "physical_logical_gpu_mapping_mismatch")
        device_mapping = {
            "device_type": "cuda",
            "physical_gpu_index": config.physical_gpu_index,
            "logical_cuda_index": logical,
            "cuda_visible_devices": list(visible),
            "mapping_verified": True,
        }
    else:
        require(config.physical_gpu_index == -1 and config.logical_cuda_index == -1, "cpu_with_cuda_mapping_forbidden")
        device_mapping = {
            "device_type": "cpu",
            "physical_gpu_index": None,
            "logical_cuda_index": None,
            "cuda_visible_devices": [],
            "mapping_verified": True,
        }
    model.to(device)
    # Reset the scalar dropout stream *after* lane-specific model
    # construction.  Contact parameter initialization otherwise advances the
    # global RNG in E/F but not B, defeating real-model B/E trajectory tests.
    torch.manual_seed(config.base_seed)
    if device.type == "cuda":
        torch.cuda.manual_seed(config.base_seed)
    target_device = v25_api.move_to_device(target_graphs, device)
    role_mapping = optimizer_api.role_mapping_from_v25_orthogonal_model(model)
    if config.integration_lane == LANE_B:
        scalar_optimizer, ownership = optimizer_api.build_scalar_reference_optimizer(
            model, role_mapping, role_optimizer_config
        )
        contact_optimizer = None
        optimizers = [scalar_optimizer]
    else:
        scalar_optimizer, contact_optimizer, ownership = optimizer_api.build_role_optimizers(
            model, role_mapping, role_optimizer_config
        )
        optimizers = [scalar_optimizer, contact_optimizer]

    all_step_events: list[dict[str, Any]] = []
    epoch_history: list[dict[str, Any]] = []
    global_step = 0
    for epoch in range(config.fixed_epochs):
        model.train()
        model.backbone.eval()
        pair_cache = _build_epoch_pair_cache(
            rank_policy=rank_policy,
            rank_labels=rank_labels,
            binding_receipt=binding_receipt,
            config=config,
            epoch=epoch,
            forbidden_candidate_ids=forbidden,
            external_trust_anchor=rank_trust_anchor,
        )
        observed_batches = 0
        epoch_events: list[dict[str, Any]] = []
        source = batch_factory(train_indices, True, epoch)
        for step_in_epoch, raw_window in enumerate(_iter_windows(source, config.gradient_accumulation)):
            observed_batches += len(raw_window)
            expected_records = pair_cache.step_pairs(step_in_epoch)
            device_window: list[Mapping[str, Any]] = []
            tier_counts = {tier: 0 for tier in CONTACT_TIER_POLICY}
            for raw_batch in raw_window:
                counts = validate_contact_tier_batch(raw_batch, candidate_tiers)
                for tier, count in counts.items():
                    tier_counts[tier] += count
                device_window.append(v25_api.move_to_device(raw_batch, device))

            scalar_diagnostics: dict[str, Any] = {}
            contact_diagnostics: dict[str, Any] = {}

            def scalar_closure() -> Any:
                scalar_values: list[Tensor] = []
                scalar_masses: list[float] = []
                payloads: list[dict[str, Any]] = []
                parts_values: list[dict[str, float]] = []
                for batch in device_window:
                    with torch.autocast(
                        device_type=device.type,
                        dtype=torch.bfloat16,
                        enabled=config.precision == "bf16",
                    ):
                        output = v25_api.forward_lane(model, config.model_lane, batch, target_device)
                        _total, parts = v25_api.compute_loss(
                            output, batch, config.model_lane, scalar_loss_config
                        )
                    scalar_values.append(parts["scalar"].float())
                    scalar_masses.append(_raw_hierarchy_mass(batch))
                    parts_values.append({
                        "receptor": float(parts["receptor"].detach().cpu()),
                        "softmin_dual": float(parts["softmin_dual"].detach().cpu()),
                        "scalar": float(parts["scalar"].detach().cpu()),
                    })
                    if config.integration_lane != LANE_B:
                        payloads.append(_contact_payload(
                            output,
                            batch,
                            detached=config.integration_lane == LANE_E,
                        ))
                main_scalar = _weighted_window_mean(scalar_values, scalar_masses, "window_scalar")
                rank_batch, endpoint_count = _rank_endpoint_predictions(
                    records=expected_records,
                    candidate_to_index=candidate_to_index,
                    batch_factory=batch_factory,
                    epoch=epoch,
                    model=model,
                    model_lane=config.model_lane,
                    target_graphs=target_device,
                    device=device,
                    precision=config.precision,
                    v25_api=v25_api,
                    rank_policy=rank_policy,
                )
                rank_loss = rank_policy.pair_loss(rank_batch, expected_records).float()
                total_scalar = main_scalar + float(config.lambda_rank) * rank_loss
                require_finite(total_scalar, "total_scalar_nonfinite")
                scalar_diagnostics.update({
                    "main_scalar_loss": float(main_scalar.detach().cpu()),
                    "rank_loss": float(rank_loss.detach().cpu()),
                    "lambda_rank": config.lambda_rank,
                    "rank_weighted_contribution": float((config.lambda_rank * rank_loss).detach().cpu()),
                    "rank_endpoint_count": endpoint_count,
                    "rank_pairs": len(expected_records),
                    "rank_prediction_semantics": rank_policy.prediction_semantics,
                    "microbatch_loss_parts": parts_values,
                    "microbatch_hierarchy_masses": scalar_masses,
                    "window_hierarchy_mass": sum(scalar_masses),
                    "accumulation_reduction": "EXACT_RAW_HIERARCHY_MASS_WEIGHTED",
                })
                return optimizer_api.ScalarStepOutput(
                    loss=total_scalar,
                    contact_payload=payloads if config.integration_lane != LANE_B else None,
                )

            def contact_closure(payloads: Sequence[Mapping[str, Any]]) -> Tensor:
                require(len(payloads) == len(device_window), "contact_payload_window_mismatch")
                marginal_values: list[Tensor] = []
                pair_values: list[Tensor] = []
                marginal_masses: list[float] = []
                pair_masses: list[float] = []
                components: list[dict[str, float]] = []
                for payload in payloads:
                    output = _contact_only_output(model, payload)
                    _total, parts = v25_api.compute_loss(
                        output,
                        payload["batch"],
                        MODEL_LANE_E,
                        contact_loss_config,
                    )
                    marginal_values.append(parts["marginal_contact"].float())
                    pair_values.append(parts["pair_contact"].float())
                    marginal_masses.append(_contact_effective_hierarchy_mass(payload["batch"], "marginal"))
                    pair_masses.append(_contact_effective_hierarchy_mass(payload["batch"], "pair"))
                    components.append({
                        "marginal_contact": float(parts["marginal_contact"].detach().cpu()),
                        "pair_contact": float(parts["pair_contact"].detach().cpu()),
                        "contact": float(parts["contact"].detach().cpu()),
                    })
                marginal_mean = _weighted_window_mean(
                    marginal_values, marginal_masses, "window_marginal_contact"
                )
                pair_mean = _weighted_window_mean(pair_values, pair_masses, "window_pair_contact")
                result = (
                    float(getattr(contact_loss_config, "marginal_weight")) * marginal_mean
                    + float(getattr(contact_loss_config, "pair_weight")) * pair_mean
                )
                require_finite(result, "window_contact_nonfinite")
                contact_diagnostics.update({
                    "contact_loss": float(result.detach().cpu()),
                    "microbatch_contact_parts": components,
                    "marginal_effective_masses": marginal_masses,
                    "pair_effective_masses": pair_masses,
                    "window_marginal_effective_mass": sum(marginal_masses),
                    "window_pair_effective_mass": sum(pair_masses),
                    "accumulation_reduction": "EXACT_COMPONENT_SPECIFIC_HIERARCHY_TIER_ELIGIBILITY_MASS_WEIGHTED",
                })
                return result

            rng_key = optimizer_api.ContactRngKey(
                base_seed=config.base_seed,
                outer_fold=config.outer_fold,
                inner_fold=config.inner_fold,
                epoch=epoch,
                optimizer_step=step_in_epoch,
                accumulation_microstep=0,
            )
            parameter_sha_before = optimizer_api.parameter_state_sha256(
                [item for role in optimizer_api.ROLES for item in role_mapping[role]]
            )
            scalar_trajectory_sha_before = optimizer_api.scalar_trajectory_sha256(role_mapping)
            optimizer_sha_before = _optimizer_state_sha256(model, optimizers)
            batch_identity_sha256 = canonical_sha256({
                "epoch": epoch,
                "step_in_epoch": step_in_epoch,
                "candidate_ids": [
                    str(candidate)
                    for raw_batch in raw_window
                    for candidate in raw_batch["candidate_ids"]
                ],
                "hierarchy_weights": [
                    float(value)
                    for raw_batch in raw_window
                    for value in raw_batch["hierarchy_weights"].detach().float().cpu().tolist()
                ],
            })
            if config.integration_lane == LANE_B:
                core_event = optimizer_api.scalar_only_step(
                    role_mapping=role_mapping,
                    scalar_optimizer=scalar_optimizer,
                    contact_optimizer=None,
                    scalar_closure=scalar_closure,
                    config=role_optimizer_config,
                )
            elif config.integration_lane == LANE_E:
                core_event = optimizer_api.strict_detached_step(
                    role_mapping=role_mapping,
                    scalar_optimizer=scalar_optimizer,
                    contact_optimizer=contact_optimizer,
                    scalar_closure=scalar_closure,
                    contact_closure=contact_closure,
                    rng_key=rng_key,
                    device=device,
                    config=role_optimizer_config,
                )
            else:
                core_event = optimizer_api.shared_gated_contact_step(
                    role_mapping=role_mapping,
                    scalar_optimizer=scalar_optimizer,
                    contact_optimizer=contact_optimizer,
                    scalar_closure=scalar_closure,
                    contact_closure=contact_closure,
                    rng_key=rng_key,
                    device=device,
                    config=role_optimizer_config,
                )
            core_event = dict(core_event)
            if config.integration_lane == LANE_F:
                post_lambda_norm = (
                    abs(float(getattr(role_optimizer_config, "lambda_contact_shared")))
                    * float(core_event["contact_capped_gradient_norm"])
                )
                budget_limit = float(core_event["contact_budget_norm_limit"])
                tolerance = max(1e-12, abs(budget_limit) * 1e-7)
                require(
                    post_lambda_norm <= budget_limit + tolerance,
                    "post_lambda_contact_gradient_budget_violation",
                )
                core_event.update({
                    "post_lambda_contact_capped_gradient_norm": post_lambda_norm,
                    "post_lambda_contact_budget_norm_limit": budget_limit,
                    "post_lambda_contact_budget_tolerance": tolerance,
                    "post_lambda_contact_gradient_budget_pass": True,
                })
            _optimizer_state_finite(optimizers)
            parameter_sha_after = optimizer_api.parameter_state_sha256(
                [item for role in optimizer_api.ROLES for item in role_mapping[role]]
            )
            scalar_trajectory_sha_after = optimizer_api.scalar_trajectory_sha256(role_mapping)
            optimizer_sha_after = _optimizer_state_sha256(model, optimizers)
            event = {
                "epoch": epoch,
                "step_in_epoch": step_in_epoch,
                "global_step": global_step,
                "accumulated_microbatches": len(raw_window),
                "partial_accumulation_window": len(raw_window) < config.gradient_accumulation,
                "tier_candidate_counts": tier_counts,
                "scalar": dict(scalar_diagnostics),
                "contact": dict(contact_diagnostics),
                "core_gradient_event": core_event,
                "evidence_hashes": {
                    "parameter_state_before_sha256": parameter_sha_before,
                    "parameter_state_after_sha256": parameter_sha_after,
                    "scalar_trajectory_before_sha256": scalar_trajectory_sha_before,
                    "scalar_trajectory_after_sha256": scalar_trajectory_sha_after,
                    "optimizer_state_before_sha256": optimizer_sha_before,
                    "optimizer_state_after_sha256": optimizer_sha_after,
                    "batch_identity_sha256": batch_identity_sha256,
                    "rank_cache_content_sha256": str(pair_cache.cache_content_sha256),
                },
            }
            epoch_events.append(event)
            all_step_events.append(event)
            global_step += 1

        require(observed_batches == config.expected_main_batches_per_epoch, "main_batch_count_mismatch")
        require(len(epoch_events) == config.scalar_steps_per_epoch, "scalar_step_count_mismatch")
        require(len(pair_cache.records) == len(epoch_events) * int(rank_policy.module.RANK_PAIRS_PER_STEP), "rank_pair_epoch_closure")
        epoch_history.append({
            "epoch": epoch,
            "main_batches": observed_batches,
            "scalar_optimizer_steps": len(epoch_events),
            "rank_cache_content_sha256": str(pair_cache.cache_content_sha256),
            "rank_pairs": len(pair_cache.records),
            "rank_repeated_pair_fraction": float(pair_cache.repeated_pair_fraction),
            "rank_noise_margin_discard_count": int(pair_cache.noise_margin_discard_count),
        })

    exact_min_probe = torch.tensor([[0.55, 0.57], [0.31, 0.29]], dtype=torch.float32, device=device)
    exact_min = rank_policy.module.exact_min_dual(exact_min_probe).detach().cpu()
    require(torch.equal(exact_min, torch.tensor([0.55, 0.29])), "exact_min_inference_contract_failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_CPU_OR_LOCAL_NONLAUNCHING_TRAINER_INTEGRATION",
        "claim_boundary": CLAIM_BOUNDARY,
        "integration_lane": config.integration_lane,
        "model_lane": config.model_lane,
        "config": asdict(config),
        "partition_audit": asdict(audit),
        "train_truth_rows_accessed": len(train_rows),
        "score_truth_rows_accessed": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "rank_policy": rank_policy.identity(),
        "bound_dependency_hashes": dependency_hashes,
        "rank_labels": {
            "total_scalar_train_labels": len(rank_labels),
            "rank_eligible_labels": rank_eligible_count,
            "scalar_only_labels": len(rank_labels) - rank_eligible_count,
        },
        "delta_noise_binding": dict(binding_receipt),
        "external_rank_trust_anchor": dict(rank_trust_anchor),
        "device_mapping": device_mapping,
        "contact_tier_policy": CONTACT_TIER_POLICY,
        "contact_ablation": {
            "mode": contact_ablation_mode,
            "marginal_weight": float(getattr(contact_loss_config, "marginal_weight")),
            "pair_weight": float(getattr(contact_loss_config, "pair_weight")),
            "v1_3_modified_in_place": False,
        },
        "optimizer_ownership": ownership,
        "gradient_accumulation": {
            "microbatches_per_full_window": config.gradient_accumulation,
            "reduction": "EXACT_PER_CANDIDATE_RAW_HIERARCHY_MASS_WITH_COMPONENT_SPECIFIC_CONTACT_MASS",
            "partial_window_scale_correction": "NORMALIZE_BY_ACTUAL_RAW_EFFECTIVE_MASS",
            "global_all_parameter_clip_used": False,
        },
        "neural_input_firewall": firewall,
        "direct_targets": ["R_8X6B", "R_9E6Y"],
        "inference_derived_target": "exact_min(R_8X6B,R_9E6Y)",
        "independent_Rdual_output_trained": False,
        "exact_min_probe_error": 0.0,
        "optimizer_steps": global_step,
        "epoch_history": epoch_history,
        "gradient_step_diagnostics": all_step_events,
        "prediction_metrics_computed": 0,
        "remote_training_launched": False,
    }


def train_v25_real1507_context_nonlaunching(
    *,
    context: Any,
    v25_api: ModuleType,
    optimizer_api: ModuleType,
    rank_policy: RankPolicyAdapter,
    delta_noise_binding_path: Path,
    scalar_loss_config: Any,
    contact_loss_config: Any,
    role_optimizer_config: Any,
    config: V26TrainerConfig,
    device_name: str = "cpu",
) -> dict[str, Any]:
    """Bind the immutable V2.5 ``RealContext`` to the V2.6 trainer.

    The caller must create the context with the existing V2.5 loader.  This
    wrapper neither parses a new dataset nor exposes a launcher, so source
    hash/provenance validation remains owned by that loader.
    """
    required = (
        "rows", "manifest", "train_indices", "score_indices", "model",
        "batches", "target_graphs", "lane_spec",
    )
    missing = [name for name in required if not hasattr(context, name)]
    require(not missing, "v25_real_context_fields_missing:" + ",".join(missing))
    require(hasattr(context.batches, "batch_size"), "v25_real_batch_size_missing")
    expected_batches = math.ceil(len(context.train_indices) / int(context.batches.batch_size))
    require(
        config.expected_main_batches_per_epoch == expected_batches,
        "v25_real_expected_batch_count_mismatch",
    )
    require(str(context.lane_spec.model_lane) == config.model_lane, "v25_real_lane_mismatch")
    context_module = sys.modules.get(type(context).__module__)
    real_context_runner_sha256 = "SYNTHETIC_OR_EMBEDDED_CONTEXT"
    if type(context).__name__ == "RealContext":
        require(isinstance(context_module, ModuleType), "v25_real_context_module_missing")
        real_context_runner_sha256 = _module_file_sha256(context_module, "v25_real_runner")
        require(
            real_context_runner_sha256 == BOUND_V25_REAL_RUNNER_SHA256,
            "bound_v25_real_runner_sha256_mismatch",
        )
    if config.integration_lane == LANE_F:
        require(str(context.lane_spec.contact_encoder_gradient) == "shared", "v25_real_shared_lane_mismatch")
    elif config.integration_lane == LANE_E:
        require(str(context.lane_spec.contact_encoder_gradient) == "detached", "v25_real_detached_lane_mismatch")
    receipt = train_open_partition_fixed_epochs(
        model=context.model,
        rows=context.rows,
        manifest=context.manifest,
        train_indices=context.train_indices,
        score_indices=context.score_indices,
        batch_factory=context.batches,
        target_graphs=context.target_graphs,
        v25_api=v25_api,
        optimizer_api=optimizer_api,
        rank_policy=rank_policy,
        delta_noise_binding_path=delta_noise_binding_path,
        scalar_loss_config=scalar_loss_config,
        contact_loss_config=contact_loss_config,
        role_optimizer_config=role_optimizer_config,
        config=config,
        device_name=device_name,
    )
    receipt["real1507_context_adapter"] = {
        "schema_version": "pvrig_v2_6_v25_real1507_context_adapter_v1",
        "source_context_type": type(context).__name__,
        "source_split_id": str(context.manifest.split_id),
        "batch_size": int(context.batches.batch_size),
        "expected_batches_per_epoch": expected_batches,
        "input_receipt_owner": "IMMUTABLE_V2_5_REAL1507_LOADER",
        "v25_real_runner_sha256": real_context_runner_sha256,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    return receipt


def integration_contract() -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}_contract_v1",
        "status": "NONLAUNCHING_INTEGRATION_SURFACE",
        "claim_boundary": CLAIM_BOUNDARY,
        "lanes": list(LANES),
        "direct_targets": ["R_8X6B", "R_9E6Y"],
        "derived_inference_target": "exact_min(R_8X6B,R_9E6Y)",
        "attention_contact_terminal_shared": False,
        "whole_parent_split_required": True,
        "contact_tier_policy": CONTACT_TIER_POLICY,
        "contact_ablation_modes": {
            "COMBINED": {"marginal_weight": 1.0, "pair_weight": 0.5},
            "MARGINAL_ONLY": {"marginal_weight": 1.0, "pair_weight": 0.0},
            "PAIR_ONLY": {"marginal_weight": 0.0, "pair_weight": 0.5}
        },
        "gradient_accumulation": "MEAN_ACTUAL_WINDOW_BEFORE_ONE_ROLE_ISOLATED_STEP",
        "gradient_accumulation_v1_2": (
            "EXACT_RAW_HIERARCHY_MASS_FOR_SCALAR_AND_COMPONENT_SPECIFIC_"
            "HIERARCHY_TIER_ELIGIBILITY_MASS_FOR_CONTACT"
        ),
        "global_all_parameter_clip_allowed": False,
        "shared_contact_gradient_budget": {
            "kappa": FROZEN_CONTACT_SHARED_KAPPA,
            "lambda_contact_shared": FROZEN_CONTACT_SHARED_LAMBDA,
            "post_lambda_budget_telemetry_required": True,
        },
        "rank_cache_trust": "HARD_BOUND_25_ANCHOR_SET_RECEIPT_AND_PARTITION_FILE_REQUIRED",
        "calibration_ensemble": {
            "seeds": list(FROZEN_ENSEMBLE_SEEDS),
            "inner_folds": list(FROZEN_INNER_FOLDS),
            "outer_train_candidate_and_parent_closure_required": True,
            "frozen_inner_outer_teacher_manifests_required": True,
            "checkpoint_bound_prediction_receipts_required": True,
        },
        "rank_policy": "SHA_BOUND_DYNAMIC_V1_OR_V1_1_COMPATIBLE",
        "formal_rank_policy": "SHA_BOUND_FROZEN_V1_1_EXACT_MIN_ONLY",
        "calibration": "FROZEN_ARTIFACT_DERIVED_OUTER_TRAIN_INNER_OOF_POSITIVE_AFFINE_R8_R9_THEN_EXACT_MIN",
        "rank_prediction_builder_resolution": [
            "build_exact_min_dual_prediction_batch",
            "build_softmin_dual_prediction_batch_for_legacy_V1_only",
        ],
        "forbidden": [
            "outer metrics",
            "score-partition truth",
            "V4-F/test32",
            "M2/126D or IDs as neural features",
            "candidate Docking poses",
            "live Node1 DAG modification",
            "remote training launch",
        ],
    }
