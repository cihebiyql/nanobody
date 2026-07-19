#!/usr/bin/env python3
"""Nonlaunching V2.6 real1507 trainer integration.

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
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping, Sequence

import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig_v2_6_real1507_role_isolated_trainer_v1"
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

BOUND_V25_TRAINER_SHA256 = "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0"
BOUND_V25_MODEL_SHA256 = "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521"
BOUND_V25_REAL_RUNNER_SHA256 = "f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f"
BOUND_OPTIMIZER_CORE_SHA256 = "2dadc945ec30eb802ca9f32fac84ce647783b9defc36db68f345fc00e972f363"
BOUND_RANK_V11_SHA256 = "b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
BOUND_DELTA_NOISE_SHA256 = "0a613b87509699a28d134c02514b1240e50a06a5aefddb5ca4a9d8202cde0a0c"

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
    "RoleOptimizerConfig",
    "ScalarStepOutput",
    "build_role_optimizers",
    "build_scalar_reference_optimizer",
    "role_mapping_from_v25_orthogonal_model",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
class InnerOofCalibrationInput:
    candidate_id: str
    parent_cluster_id: str
    predicted_r8: float
    predicted_r9: float
    true_r8: float
    true_r9: float


def fit_fold_local_calibration_from_inner_oof(
    rows: Sequence[InnerOofCalibrationInput],
    *,
    outer_fold: int,
    outer_score_candidate_ids: Sequence[str],
    rank_policy: RankPolicyAdapter,
) -> Any:
    """Fit the bound core's calibration using outer-train inner-OOF only."""
    require(rank_policy.sha256 == BOUND_RANK_V11_SHA256, "calibration_policy_not_frozen_v1_1")
    require(bool(rows), "inner_oof_calibration_rows_empty")
    forbidden = set(str(value) for value in outer_score_candidate_ids)
    require(not ({row.candidate_id for row in rows} & forbidden), "outer_score_candidate_in_inner_oof_calibration")
    module = rank_policy.module
    fit_role = str(getattr(module, "CALIBRATION_FIT_ROLE", "OUTER_TRAIN_INNER_OOF"))
    values = []
    for row in rows:
        reject_sealed_text(row.candidate_id, "calibration_candidate_id")
        values.append(module.CalibrationRow(
            candidate_id=row.candidate_id,
            parent_cluster_id=row.parent_cluster_id,
            outer_fold=outer_fold,
            fit_role=fit_role,
            predicted_r8=row.predicted_r8,
            predicted_r9=row.predicted_r9,
            true_r8=row.true_r8,
            true_r9=row.true_r9,
        ))
    result = module.fit_fold_local_positive_affine(
        values,
        outer_fold=outer_fold,
        forbidden_candidate_ids=forbidden,
    )
    result.validate()
    return result


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

    def validate(self) -> None:
        require(self.integration_lane in LANES, f"integration_lane_invalid:{self.integration_lane}")
        require(self.fixed_epochs > 0, "fixed_epochs_invalid")
        require(self.gradient_accumulation > 0, "gradient_accumulation_invalid")
        require(math.isfinite(self.lambda_rank) and self.lambda_rank >= 0.0, "lambda_rank_invalid")
        require(self.precision in {"fp32", "bf16"}, "precision_invalid")
        require(self.outer_fold >= 0 and self.inner_fold >= 0, "fold_invalid")
        require(self.expected_main_batches_per_epoch > 0, "expected_main_batches_invalid")

    @property
    def model_lane(self) -> str:
        return MODEL_LANE_B if self.integration_lane == LANE_B else MODEL_LANE_E

    @property
    def scalar_steps_per_epoch(self) -> int:
        return math.ceil(self.expected_main_batches_per_epoch / self.gradient_accumulation)


def _model_contact_gradient_mode(model: nn.Module) -> str:
    return str(model.head.config.contact_encoder_gradient)


def validate_model_lane(model: nn.Module, config: V26TrainerConfig) -> None:
    contact_enabled = bool(model.head.config.enable_contact_evidence)
    require(contact_enabled == (config.integration_lane != LANE_B), "model_contact_lane_mismatch")
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


def _build_epoch_pair_cache(
    *,
    rank_policy: RankPolicyAdapter,
    rank_labels: Sequence[Any],
    binding_receipt: Mapping[str, Any],
    config: V26TrainerConfig,
    epoch: int,
    forbidden_candidate_ids: Sequence[str],
) -> Any:
    module = rank_policy.module
    split_sha = module.compute_training_split_sha256(rank_labels, config.outer_fold, config.inner_fold)
    label_sha = module.compute_label_sha256(rank_labels)
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
    if config.integration_lane != LANE_B:
        require(
            float(getattr(contact_loss_config, "marginal_weight")) > 0.0
            and float(getattr(contact_loss_config, "pair_weight")) > 0.0,
            "contact_closure_weights_must_be_positive",
        )
    require(float(getattr(role_optimizer_config, "kappa")) == 0.25, "shared_contact_kappa_not_frozen")
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

    device = torch.device(device_name)
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
                main_scalar = _mean_scalars(scalar_values, "window_scalar")
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
                })
                return optimizer_api.ScalarStepOutput(
                    loss=total_scalar,
                    contact_payload=payloads if config.integration_lane != LANE_B else None,
                )

            def contact_closure(payloads: Sequence[Mapping[str, Any]]) -> Tensor:
                require(len(payloads) == len(device_window), "contact_payload_window_mismatch")
                values: list[Tensor] = []
                components: list[dict[str, float]] = []
                for payload in payloads:
                    output = _contact_only_output(model, payload)
                    _total, parts = v25_api.compute_loss(
                        output,
                        payload["batch"],
                        MODEL_LANE_E,
                        contact_loss_config,
                    )
                    values.append(parts["contact"].float())
                    components.append({
                        "marginal_contact": float(parts["marginal_contact"].detach().cpu()),
                        "pair_contact": float(parts["pair_contact"].detach().cpu()),
                        "contact": float(parts["contact"].detach().cpu()),
                    })
                result = _mean_scalars(values, "window_contact")
                contact_diagnostics.update({
                    "contact_loss": float(result.detach().cpu()),
                    "microbatch_contact_parts": components,
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
            _optimizer_state_finite(optimizers)
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
        "contact_tier_policy": CONTACT_TIER_POLICY,
        "optimizer_ownership": ownership,
        "gradient_accumulation": {
            "microbatches_per_full_window": config.gradient_accumulation,
            "reduction": "MEAN_OVER_ACTUAL_WINDOW_THEN_ONE_ROLE_ISOLATED_STEP",
            "partial_window_scale_correction": "MEAN_OVER_ACTUAL_WINDOW",
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
        "gradient_accumulation": "MEAN_ACTUAL_WINDOW_BEFORE_ONE_ROLE_ISOLATED_STEP",
        "global_all_parameter_clip_allowed": False,
        "rank_policy": "SHA_BOUND_DYNAMIC_V1_OR_V1_1_COMPATIBLE",
        "formal_rank_policy": "SHA_BOUND_FROZEN_V1_1_EXACT_MIN_ONLY",
        "calibration": "OUTER_TRAIN_INNER_OOF_POSITIVE_AFFINE_R8_R9_THEN_EXACT_MIN",
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
