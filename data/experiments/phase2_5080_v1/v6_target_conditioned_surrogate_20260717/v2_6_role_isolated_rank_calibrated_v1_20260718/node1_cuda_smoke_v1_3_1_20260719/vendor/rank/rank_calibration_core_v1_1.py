#!/usr/bin/env python3
"""Versioned V2.6 rank/calibration primitives V1.1.

This module contains only open-development training utilities.  It never reads
outer-fold truth, V4-F/test32, candidate docking poses, M2 features, or model
metrics.  Parent identifiers are accepted only for split-safe sampling and
grouped loss reduction; they are never model inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch
from torch import Tensor
import torch.nn.functional as F


SCHEMA_VERSION = "pvrig_v2_6_rank_calibration_core_v1_1"
CLAIM_BOUNDARY = (
    "Open-development computational dual-receptor Docking-geometry surrogate utility only; "
    "not binding, affinity, competition, experimental blocking, Docking Gold, sealed V4-F "
    "evidence, or submission truth."
)

FROZEN_DELTA_NOISE = 0.019614956149
FROZEN_DELTA_NOISE_DECIMALS = 12
FROZEN_BINDING_SCHEMA = "pvrig_v2_6_delta_noise_binding_v1"
FROZEN_BINDING_STATUS = "FROZEN_V2_6_DELTA_NOISE_FROM_NONADAPTIVE_V4D_OPEN_TRAIN"
FROZEN_BINDING_SHA256 = "0a613b87509699a28d134c02514b1240e50a06a5aefddb5ca4a9d8202cde0a0c"
FROZEN_BINDING_SOURCE_SHA256 = "eb44fb5ac80e0387c75b10a9f1805eb19c2cb89b18e71af32edffcfcb50e59b2"
FROZEN_BINDING_CANDIDATE_COUNT = 225

SOFTMIN_TAU = 0.02
RANK_TAU = 0.03
RANK_PAIRS_PER_STEP = 8
MINIMUM_RANK_ELIGIBLE_PARENTS = 8
RANK_ELIGIBILITY_POLICY_ID = "V2_6_V1_1_NONADAPTIVE_V4D_A_MULTI_SEED_ONLY"
RANK_ELIGIBLE_TEACHER_SOURCE = "V4D_OPEN_MULTI_SEED"
RANK_ELIGIBLE_RELIABILITY_TIER = "A"
RANK_ELIGIBLE_DOCKING_TIER = "V4D_MULTI_SEED"
RANK_ELIGIBLE_TEACHER_RELIABILITY = "MULTI_SEED"
RANK_ELIGIBLE_RELEASE = "v4d_open_multi_seed_frozen_v1_1"
V4H_SOURCE = "V4H_ADAPTIVE_SEED_RANKING"
V4H_ALLOWED_STRATA = frozenset(
    {
        ("A", "DUAL_3_SEED", "DUAL_3_SEED"),
        ("B", "DUAL_2_SEED", "DUAL_2_SEED"),
        ("C", "DUAL_1_SEED", "DUAL_1_SEED"),
    }
)
V4H_RELEASE = "final_adaptive_seed"
CALIBRATION_HUBER_BETA = 0.03
CALIBRATION_IDENTITY_SHRINKAGE = 0.10
CALIBRATION_SLOPE_BOUNDS = (0.5, 1.5)
CALIBRATION_INTERCEPT_BOUNDS = (-0.1, 0.1)
CALIBRATION_FIT_ROLE = "OUTER_TRAIN_INNER_OOF"


class RankCalibrationError(RuntimeError):
    """A fail-closed contract violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RankCalibrationError(message)


def require_finite_tensor(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _deterministic_seed(*parts: object) -> int:
    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big", signed=False)


def verify_frozen_delta_noise_binding(path: Path) -> dict[str, Any]:
    """Verify the exact upstream artifact that freezes ``delta_noise``.

    The implementation constant is the preregistered 12-decimal rendering.
    The upstream JSON retains the full-precision computed value.  Both must
    agree after the explicitly frozen 12-decimal rounding operation.
    """
    require(path.is_file() and not path.is_symlink(), "delta_noise_binding_not_regular_file")
    observed_sha = sha256_file(path)
    require(observed_sha == FROZEN_BINDING_SHA256, "delta_noise_binding_sha256_mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankCalibrationError("delta_noise_binding_json_invalid") from exc
    require(payload.get("schema_version") == FROZEN_BINDING_SCHEMA, "delta_noise_binding_schema_mismatch")
    require(payload.get("status") == FROZEN_BINDING_STATUS, "delta_noise_binding_status_mismatch")
    require(payload.get("candidate_count") == FROZEN_BINDING_CANDIDATE_COUNT, "delta_noise_binding_count_mismatch")
    require(payload.get("seed_count_per_candidate") == 3, "delta_noise_binding_seed_count_mismatch")
    require(payload.get("source_sha256") == FROZEN_BINDING_SOURCE_SHA256, "delta_noise_binding_source_mismatch")
    require(payload.get("adaptive_v4h_excluded") is True, "delta_noise_binding_adaptive_cohort_not_excluded")
    require(payload.get("candidate_is_statistical_unit") is True, "delta_noise_binding_statistical_unit_invalid")
    require(payload.get("v4_f_or_test32_results_accessed") == 0, "delta_noise_binding_sealed_access_nonzero")
    value = payload.get("delta_noise")
    require(isinstance(value, (int, float)) and math.isfinite(float(value)), "delta_noise_binding_value_invalid")
    require(
        round(float(value), FROZEN_DELTA_NOISE_DECIMALS) == FROZEN_DELTA_NOISE,
        "delta_noise_binding_rounded_value_mismatch",
    )
    return {
        "binding_sha256": observed_sha,
        "source_sha256": payload["source_sha256"],
        "candidate_count": payload["candidate_count"],
        "full_precision_delta_noise": float(value),
        "frozen_12_decimal_delta_noise": FROZEN_DELTA_NOISE,
        "rounding_decimals": FROZEN_DELTA_NOISE_DECIMALS,
        "v4_f_or_test32_results_accessed": 0,
    }


def normalized_softmin(left: Tensor, right: Tensor, tau: float = SOFTMIN_TAU) -> Tensor:
    """FP32 normalized soft minimum with equality preservation."""
    require(left.shape == right.shape, "softmin_shape_mismatch")
    require(math.isfinite(float(tau)) and float(tau) > 0.0, "softmin_tau_invalid")
    values = torch.stack((left.float(), right.float()), dim=-1)
    result = -float(tau) * torch.logsumexp(-values / float(tau), dim=-1) + float(tau) * math.log(2.0)
    require(result.dtype == torch.float32, "softmin_not_fp32")
    require_finite_tensor(result, "softmin_nonfinite")
    return result


def softmin_dual(receptor_predictions: Tensor, tau: float = SOFTMIN_TAU) -> Tensor:
    require(
        receptor_predictions.ndim == 2 and receptor_predictions.shape[1] == 2,
        "receptor_prediction_shape_invalid",
    )
    return normalized_softmin(receptor_predictions[:, 0], receptor_predictions[:, 1], tau)


def exact_min_dual(receptor_predictions: Tensor) -> Tensor:
    """The only permitted inference/reporting definition of Rdual."""
    require(
        receptor_predictions.ndim == 2 and receptor_predictions.shape[1] == 2,
        "receptor_prediction_shape_invalid",
    )
    result = torch.minimum(receptor_predictions[:, 0], receptor_predictions[:, 1])
    require_finite_tensor(result, "exact_min_nonfinite")
    return result


@dataclass(frozen=True)
class CandidateLabel:
    candidate_id: str
    parent_cluster_id: str
    true_r8: float
    true_r9: float
    teacher_source: str
    development_reliability_tier: str
    docking_evidence_tier: str
    teacher_reliability: str
    ranking_release: str
    split_role: str = "TRAIN"

    @property
    def true_dual(self) -> float:
        return min(float(self.true_r8), float(self.true_r9))

    @property
    def rank_eligible(self) -> bool:
        return (
            self.teacher_source == RANK_ELIGIBLE_TEACHER_SOURCE
            and self.development_reliability_tier == RANK_ELIGIBLE_RELIABILITY_TIER
            and self.docking_evidence_tier == RANK_ELIGIBLE_DOCKING_TIER
            and self.teacher_reliability == RANK_ELIGIBLE_TEACHER_RELIABILITY
            and self.ranking_release == RANK_ELIGIBLE_RELEASE
        )

    @property
    def rank_eligibility_reason(self) -> str:
        if self.rank_eligible:
            return "ELIGIBLE_NONADAPTIVE_V4D_A_MULTI_SEED"
        if self.teacher_source == V4H_SOURCE:
            return "EXCLUDED_ADAPTIVE_V4H_SOURCE_SPECIFIC_NOISE_UNVALIDATED"
        return "INVALID_SOURCE_TIER_PROVENANCE"

    def validate(self) -> None:
        require(bool(self.candidate_id), "candidate_id_empty")
        require(bool(self.parent_cluster_id), "parent_cluster_id_empty")
        require(self.split_role == "TRAIN", f"nontrain_candidate_in_pair_cache:{self.candidate_id}")
        require(math.isfinite(float(self.true_r8)) and math.isfinite(float(self.true_r9)), "candidate_truth_nonfinite")
        if self.teacher_source == RANK_ELIGIBLE_TEACHER_SOURCE:
            require(self.rank_eligible, f"v4d_source_tier_provenance_invalid:{self.candidate_id}")
        elif self.teacher_source == V4H_SOURCE:
            require(
                (
                    self.development_reliability_tier,
                    self.docking_evidence_tier,
                    self.teacher_reliability,
                )
                in V4H_ALLOWED_STRATA,
                f"v4h_source_tier_provenance_invalid:{self.candidate_id}",
            )
            require(self.ranking_release == V4H_RELEASE, f"v4h_ranking_release_invalid:{self.candidate_id}")
        else:
            raise RankCalibrationError(f"teacher_source_not_allowed:{self.candidate_id}")


@dataclass(frozen=True)
class RankPairRecord:
    step_index: int
    pair_index_within_step: int
    parent_cluster_id: str
    left_candidate_id: str
    right_candidate_id: str
    truth_delta: float
    truth_sign: int
    pair_weight: float
    teacher_source: str = RANK_ELIGIBLE_TEACHER_SOURCE
    development_reliability_tier: str = RANK_ELIGIBLE_RELIABILITY_TIER
    rank_eligibility_policy_id: str = RANK_ELIGIBILITY_POLICY_ID

    def validate(self) -> None:
        require(self.step_index >= 0, "pair_step_index_invalid")
        require(0 <= self.pair_index_within_step < RANK_PAIRS_PER_STEP, "pair_within_step_index_invalid")
        require(bool(self.parent_cluster_id), "pair_parent_empty")
        require(bool(self.left_candidate_id) and bool(self.right_candidate_id), "pair_endpoint_empty")
        require(self.left_candidate_id != self.right_candidate_id, "pair_endpoint_self_pair")
        require(math.isfinite(self.truth_delta), "pair_truth_delta_nonfinite")
        require(self.truth_sign in {-1, 1}, "pair_truth_sign_invalid")
        require(self.truth_sign == (1 if self.truth_delta > 0.0 else -1), "pair_truth_sign_mismatch")
        require(abs(self.truth_delta) >= FROZEN_DELTA_NOISE, "pair_below_frozen_noise_margin")
        require(self.teacher_source == RANK_ELIGIBLE_TEACHER_SOURCE, "pair_teacher_source_not_rank_eligible")
        require(
            self.development_reliability_tier == RANK_ELIGIBLE_RELIABILITY_TIER,
            "pair_reliability_tier_not_rank_eligible",
        )
        require(self.rank_eligibility_policy_id == RANK_ELIGIBILITY_POLICY_ID, "pair_rank_policy_mismatch")
        expected = min(abs(self.truth_delta) / FROZEN_DELTA_NOISE, 3.0)
        require(abs(self.pair_weight - expected) <= 1e-12, "pair_weight_mismatch")


@dataclass(frozen=True)
class ParentPairEpochCache:
    base_seed: int
    outer_fold: int
    inner_fold: int
    epoch: int
    scalar_optimizer_steps: int
    rank_eligibility_policy_id: str
    rank_eligible_candidate_count: int
    rank_ineligible_candidate_count: int
    rank_ineligible_reason_counts: tuple[tuple[str, int], ...]
    training_split_sha256: str
    label_sha256: str
    eligible_pair_sha256: str
    records: tuple[RankPairRecord, ...]
    eligible_pairs_per_parent: tuple[tuple[str, int], ...]
    emitted_pairs_per_parent: tuple[tuple[str, int], ...]
    zero_eligible_pair_parents: tuple[str, ...]
    noise_margin_discard_count: int
    repeated_pair_fraction: float
    cache_content_sha256: str

    def step_pairs(self, step_index: int) -> tuple[RankPairRecord, ...]:
        require(0 <= step_index < self.scalar_optimizer_steps, "pair_step_out_of_range")
        start = step_index * RANK_PAIRS_PER_STEP
        result = self.records[start : start + RANK_PAIRS_PER_STEP]
        require(len(result) == RANK_PAIRS_PER_STEP, "pair_step_not_exactly_eight")
        require(all(record.step_index == step_index for record in result), "pair_step_record_mismatch")
        return result

    def content_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "pvrig_v2_6_parent_pair_epoch_cache_content_v1_1",
            "base_seed": self.base_seed,
            "outer_fold": self.outer_fold,
            "inner_fold": self.inner_fold,
            "epoch": self.epoch,
            "scalar_optimizer_steps": self.scalar_optimizer_steps,
            "pairs_per_step": RANK_PAIRS_PER_STEP,
            "delta_noise": FROZEN_DELTA_NOISE,
            "rank_eligibility_policy_id": self.rank_eligibility_policy_id,
            "rank_eligible_candidate_count": self.rank_eligible_candidate_count,
            "rank_ineligible_candidate_count": self.rank_ineligible_candidate_count,
            "rank_ineligible_reason_counts": dict(self.rank_ineligible_reason_counts),
            "training_split_sha256": self.training_split_sha256,
            "label_sha256": self.label_sha256,
            "eligible_pair_sha256": self.eligible_pair_sha256,
            "records": [asdict(record) for record in self.records],
            "eligible_pairs_per_parent": dict(self.eligible_pairs_per_parent),
            "emitted_pairs_per_parent": dict(self.emitted_pairs_per_parent),
            "zero_eligible_pair_parents": list(self.zero_eligible_pair_parents),
            "noise_margin_discard_count": self.noise_margin_discard_count,
            "repeated_pair_fraction": self.repeated_pair_fraction,
        }

    def verify(self) -> None:
        require(self.scalar_optimizer_steps > 0, "scalar_optimizer_steps_invalid")
        require(self.rank_eligibility_policy_id == RANK_ELIGIBILITY_POLICY_ID, "cache_rank_policy_mismatch")
        require(self.rank_eligible_candidate_count > 0, "cache_rank_eligible_count_invalid")
        require(self.rank_ineligible_candidate_count >= 0, "cache_rank_ineligible_count_invalid")
        require(
            sum(count for _, count in self.rank_ineligible_reason_counts) == self.rank_ineligible_candidate_count,
            "cache_rank_ineligible_reason_count_mismatch",
        )
        require(len(self.records) == self.scalar_optimizer_steps * RANK_PAIRS_PER_STEP, "cache_pair_count_invalid")
        for step in range(self.scalar_optimizer_steps):
            batch = self.step_pairs(step)
            require(
                len({record.parent_cluster_id for record in batch}) == RANK_PAIRS_PER_STEP,
                "pair_step_parent_diversity_below_eight",
            )
            for record in batch:
                record.validate()
        emitted_counts = [count for _, count in self.emitted_pairs_per_parent]
        require(bool(emitted_counts), "cache_no_emitted_parents")
        require(max(emitted_counts) - min(emitted_counts) <= 1, "cache_parent_round_robin_imbalanced")
        require(canonical_sha256(self.content_payload()) == self.cache_content_sha256, "cache_content_sha256_mismatch")

    def to_payload(self) -> dict[str, Any]:
        self.verify()
        payload = self.content_payload()
        payload.update(
            {
                "schema_version": "pvrig_v2_6_parent_pair_epoch_cache_v1_1",
                "status": "PASS_EXACT_MIN_V4D_ONLY_FROZEN_NOISE_SPLIT_SAFE_CACHE",
                "cache_content_sha256": self.cache_content_sha256,
                "claim_boundary": CLAIM_BOUNDARY,
                "v4_f_or_test32_results_accessed": 0,
            }
        )
        return payload

    def write_json(self, path: Path) -> None:
        payload = self.to_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _label_payload(labels: Sequence[CandidateLabel]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row.candidate_id,
            "parent_cluster_id": row.parent_cluster_id,
            "true_r8": float(row.true_r8),
            "true_r9": float(row.true_r9),
            "true_dual": row.true_dual,
            "teacher_source": row.teacher_source,
            "development_reliability_tier": row.development_reliability_tier,
            "docking_evidence_tier": row.docking_evidence_tier,
            "teacher_reliability": row.teacher_reliability,
            "ranking_release": row.ranking_release,
            "rank_eligible": row.rank_eligible,
            "rank_eligibility_reason": row.rank_eligibility_reason,
            "split_role": row.split_role,
        }
        for row in sorted(labels, key=lambda item: item.candidate_id)
    ]


def _split_payload(labels: Sequence[CandidateLabel], outer_fold: int, inner_fold: int) -> dict[str, Any]:
    return {
        "outer_fold": outer_fold,
        "inner_fold": inner_fold,
        "role": "TRAIN",
        "candidate_parent": [
            [row.candidate_id, row.parent_cluster_id]
            for row in sorted(labels, key=lambda item: item.candidate_id)
        ],
    }


def compute_training_split_sha256(
    labels: Sequence[CandidateLabel], outer_fold: int, inner_fold: int
) -> str:
    """Canonical training-partition identity for launcher-side freezing."""
    return canonical_sha256(_split_payload(labels, outer_fold, inner_fold))


def compute_label_sha256(labels: Sequence[CandidateLabel]) -> str:
    """Canonical scalar-label identity for launcher-side freezing."""
    return canonical_sha256(_label_payload(labels))


def build_parent_pair_epoch_cache(
    labels: Sequence[CandidateLabel],
    *,
    base_seed: int,
    outer_fold: int,
    inner_fold: int,
    epoch: int,
    scalar_optimizer_steps: int,
    binding_receipt: Mapping[str, Any],
    expected_training_split_sha256: str,
    expected_label_sha256: str,
    forbidden_candidate_ids: Iterable[str] = (),
) -> ParentPairEpochCache:
    """Build a deterministic, balanced, exact-eight-pairs-per-step cache."""
    require(binding_receipt.get("binding_sha256") == FROZEN_BINDING_SHA256, "unverified_delta_noise_binding")
    require(binding_receipt.get("frozen_12_decimal_delta_noise") == FROZEN_DELTA_NOISE, "delta_noise_receipt_value_mismatch")
    require(binding_receipt.get("v4_f_or_test32_results_accessed") == 0, "delta_noise_receipt_sealed_access_nonzero")
    require(isinstance(base_seed, int), "base_seed_invalid")
    require(outer_fold >= 0 and inner_fold >= 0 and epoch >= 0, "fold_or_epoch_invalid")
    require(scalar_optimizer_steps > 0, "scalar_optimizer_steps_invalid")
    require(bool(labels), "pair_cache_labels_empty")
    forbidden = set(forbidden_candidate_ids)
    candidate_ids: set[str] = set()
    by_parent: dict[str, list[CandidateLabel]] = {}
    rank_ineligible_reason_counts: dict[str, int] = {}
    rank_eligible_candidate_count = 0
    for row in labels:
        row.validate()
        require(row.candidate_id not in candidate_ids, f"duplicate_candidate_label:{row.candidate_id}")
        require(row.candidate_id not in forbidden, f"forbidden_candidate_in_training_split:{row.candidate_id}")
        candidate_ids.add(row.candidate_id)
        if row.rank_eligible:
            rank_eligible_candidate_count += 1
            by_parent.setdefault(row.parent_cluster_id, []).append(row)
        else:
            reason = row.rank_eligibility_reason
            require(reason != "INVALID_SOURCE_TIER_PROVENANCE", f"invalid_rank_provenance:{row.candidate_id}")
            rank_ineligible_reason_counts[reason] = rank_ineligible_reason_counts.get(reason, 0) + 1

    require(len(expected_training_split_sha256) == 64, "expected_training_split_sha256_invalid")
    require(len(expected_label_sha256) == 64, "expected_label_sha256_invalid")
    training_split_sha256 = compute_training_split_sha256(labels, outer_fold, inner_fold)
    label_sha256 = compute_label_sha256(labels)
    require(training_split_sha256 == expected_training_split_sha256, "training_split_sha256_mismatch")
    require(label_sha256 == expected_label_sha256, "label_sha256_mismatch")
    eligible: dict[str, list[tuple[str, str, float]]] = {}
    zero_parents: list[str] = []
    discard_count = 0
    for parent in sorted(by_parent):
        rows = sorted(by_parent[parent], key=lambda item: item.candidate_id)
        parent_pairs: list[tuple[str, str, float]] = []
        for left_index, left in enumerate(rows):
            for right in rows[left_index + 1 :]:
                delta = left.true_dual - right.true_dual
                if abs(delta) < FROZEN_DELTA_NOISE:
                    discard_count += 1
                    continue
                parent_pairs.append((left.candidate_id, right.candidate_id, delta))
        if parent_pairs:
            rng = random.Random(
                _deterministic_seed(base_seed, outer_fold, inner_fold, epoch, "rank_pair_cache", parent)
            )
            rng.shuffle(parent_pairs)
            eligible[parent] = parent_pairs
        else:
            zero_parents.append(parent)
    require(
        len(eligible) >= MINIMUM_RANK_ELIGIBLE_PARENTS,
        f"rank_eligible_parent_count_below_{MINIMUM_RANK_ELIGIBLE_PARENTS}:{len(eligible)}",
    )

    parent_order = sorted(eligible)
    parent_rng = random.Random(
        _deterministic_seed(base_seed, outer_fold, inner_fold, epoch, "rank_pair_cache", "parent_order")
    )
    parent_rng.shuffle(parent_order)
    total_records = scalar_optimizer_steps * RANK_PAIRS_PER_STEP
    emitted_counts = {parent: 0 for parent in parent_order}
    repeated = 0
    records: list[RankPairRecord] = []
    eligible_payload: list[dict[str, Any]] = []
    for parent in sorted(eligible):
        for left, right, delta in eligible[parent]:
            eligible_payload.append(
                {"parent_cluster_id": parent, "left_candidate_id": left, "right_candidate_id": right, "truth_delta": delta}
            )
    for record_index in range(total_records):
        parent = parent_order[record_index % len(parent_order)]
        parent_pairs = eligible[parent]
        occurrence = emitted_counts[parent]
        pair_index = occurrence % len(parent_pairs)
        if occurrence >= len(parent_pairs):
            repeated += 1
        left, right, delta = parent_pairs[pair_index]
        step_index, within_step = divmod(record_index, RANK_PAIRS_PER_STEP)
        record = RankPairRecord(
            step_index=step_index,
            pair_index_within_step=within_step,
            parent_cluster_id=parent,
            left_candidate_id=left,
            right_candidate_id=right,
            truth_delta=float(delta),
            truth_sign=1 if delta > 0.0 else -1,
            pair_weight=min(abs(float(delta)) / FROZEN_DELTA_NOISE, 3.0),
            teacher_source=RANK_ELIGIBLE_TEACHER_SOURCE,
            development_reliability_tier=RANK_ELIGIBLE_RELIABILITY_TIER,
            rank_eligibility_policy_id=RANK_ELIGIBILITY_POLICY_ID,
        )
        record.validate()
        records.append(record)
        emitted_counts[parent] += 1
    content_without_hash = {
        "schema_version": "pvrig_v2_6_parent_pair_epoch_cache_content_v1_1",
        "base_seed": base_seed,
        "outer_fold": outer_fold,
        "inner_fold": inner_fold,
        "epoch": epoch,
        "scalar_optimizer_steps": scalar_optimizer_steps,
        "pairs_per_step": RANK_PAIRS_PER_STEP,
        "delta_noise": FROZEN_DELTA_NOISE,
        "rank_eligibility_policy_id": RANK_ELIGIBILITY_POLICY_ID,
        "rank_eligible_candidate_count": rank_eligible_candidate_count,
        "rank_ineligible_candidate_count": len(labels) - rank_eligible_candidate_count,
        "rank_ineligible_reason_counts": dict(sorted(rank_ineligible_reason_counts.items())),
        "training_split_sha256": training_split_sha256,
        "label_sha256": label_sha256,
        "eligible_pair_sha256": canonical_sha256(eligible_payload),
        "records": [asdict(record) for record in records],
        "eligible_pairs_per_parent": {parent: len(eligible[parent]) for parent in sorted(eligible)},
        "emitted_pairs_per_parent": {parent: emitted_counts[parent] for parent in sorted(emitted_counts)},
        "zero_eligible_pair_parents": sorted(zero_parents),
        "noise_margin_discard_count": discard_count,
        "repeated_pair_fraction": repeated / total_records,
    }
    cache = ParentPairEpochCache(
        base_seed=base_seed,
        outer_fold=outer_fold,
        inner_fold=inner_fold,
        epoch=epoch,
        scalar_optimizer_steps=scalar_optimizer_steps,
        rank_eligibility_policy_id=RANK_ELIGIBILITY_POLICY_ID,
        rank_eligible_candidate_count=rank_eligible_candidate_count,
        rank_ineligible_candidate_count=len(labels) - rank_eligible_candidate_count,
        rank_ineligible_reason_counts=tuple(sorted(rank_ineligible_reason_counts.items())),
        training_split_sha256=training_split_sha256,
        label_sha256=label_sha256,
        eligible_pair_sha256=content_without_hash["eligible_pair_sha256"],
        records=tuple(records),
        eligible_pairs_per_parent=tuple(sorted(content_without_hash["eligible_pairs_per_parent"].items())),
        emitted_pairs_per_parent=tuple(sorted(content_without_hash["emitted_pairs_per_parent"].items())),
        zero_eligible_pair_parents=tuple(sorted(zero_parents)),
        noise_margin_discard_count=discard_count,
        repeated_pair_fraction=repeated / total_records,
        cache_content_sha256=canonical_sha256(content_without_hash),
    )
    cache.verify()
    return cache


def load_parent_pair_epoch_cache(
    path: Path,
    *,
    expected_training_split_sha256: str,
    expected_label_sha256: str,
) -> ParentPairEpochCache:
    """Load and replay-verify a persisted epoch cache."""
    require(path.is_file() and not path.is_symlink(), "pair_cache_not_regular_file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankCalibrationError("pair_cache_json_invalid") from exc
    require(payload.get("schema_version") == "pvrig_v2_6_parent_pair_epoch_cache_v1_1", "pair_cache_schema_invalid")
    require(
        payload.get("status") == "PASS_EXACT_MIN_V4D_ONLY_FROZEN_NOISE_SPLIT_SAFE_CACHE",
        "pair_cache_status_invalid",
    )
    require(payload.get("v4_f_or_test32_results_accessed") == 0, "pair_cache_sealed_access_nonzero")
    require(payload.get("delta_noise") == FROZEN_DELTA_NOISE, "pair_cache_delta_noise_mismatch")
    require(payload.get("rank_eligibility_policy_id") == RANK_ELIGIBILITY_POLICY_ID, "pair_cache_rank_policy_mismatch")
    require(payload.get("pairs_per_step") == RANK_PAIRS_PER_STEP, "pair_cache_pairs_per_step_mismatch")
    require(payload.get("training_split_sha256") == expected_training_split_sha256, "training_split_sha256_mismatch")
    require(payload.get("label_sha256") == expected_label_sha256, "label_sha256_mismatch")
    try:
        cache = ParentPairEpochCache(
            base_seed=int(payload["base_seed"]),
            outer_fold=int(payload["outer_fold"]),
            inner_fold=int(payload["inner_fold"]),
            epoch=int(payload["epoch"]),
            scalar_optimizer_steps=int(payload["scalar_optimizer_steps"]),
            rank_eligibility_policy_id=str(payload["rank_eligibility_policy_id"]),
            rank_eligible_candidate_count=int(payload["rank_eligible_candidate_count"]),
            rank_ineligible_candidate_count=int(payload["rank_ineligible_candidate_count"]),
            rank_ineligible_reason_counts=tuple(
                sorted((str(key), int(value)) for key, value in payload["rank_ineligible_reason_counts"].items())
            ),
            training_split_sha256=str(payload["training_split_sha256"]),
            label_sha256=str(payload["label_sha256"]),
            eligible_pair_sha256=str(payload["eligible_pair_sha256"]),
            records=tuple(RankPairRecord(**record) for record in payload["records"]),
            eligible_pairs_per_parent=tuple(sorted((str(key), int(value)) for key, value in payload["eligible_pairs_per_parent"].items())),
            emitted_pairs_per_parent=tuple(sorted((str(key), int(value)) for key, value in payload["emitted_pairs_per_parent"].items())),
            zero_eligible_pair_parents=tuple(sorted(str(value) for value in payload["zero_eligible_pair_parents"])),
            noise_margin_discard_count=int(payload["noise_margin_discard_count"]),
            repeated_pair_fraction=float(payload["repeated_pair_fraction"]),
            cache_content_sha256=str(payload["cache_content_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RankCalibrationError("pair_cache_payload_invalid") from exc
    cache.verify()
    return cache


def deduplicated_pair_endpoints(records: Sequence[RankPairRecord]) -> tuple[str, ...]:
    require(len(records) == RANK_PAIRS_PER_STEP, "pair_batch_not_exactly_eight")
    endpoints = {record.left_candidate_id for record in records} | {record.right_candidate_id for record in records}
    return tuple(sorted(endpoints))


@dataclass(frozen=True)
class ExactMinDualPredictionBatch:
    """Typed provenance barrier aligning rank optimization with inference."""

    candidate_ids: tuple[str, ...]
    values: Tensor
    provenance: str = "FP32_EXACT_MIN_FROM_DIRECT_R8_R9"

    def validate(self) -> None:
        require(bool(self.candidate_ids), "exact_min_prediction_ids_empty")
        require(len(set(self.candidate_ids)) == len(self.candidate_ids), "exact_min_prediction_ids_duplicate")
        require(self.values.shape == (len(self.candidate_ids),), "exact_min_prediction_shape_invalid")
        require(self.values.dtype == torch.float32, "exact_min_prediction_not_fp32")
        require_finite_tensor(self.values, "exact_min_prediction_nonfinite")
        require(
            self.provenance == "FP32_EXACT_MIN_FROM_DIRECT_R8_R9",
            "exact_min_prediction_provenance_invalid",
        )

    def index(self) -> dict[str, Tensor]:
        self.validate()
        return {candidate_id: self.values[index] for index, candidate_id in enumerate(self.candidate_ids)}


def build_exact_min_dual_prediction_batch(
    candidate_ids: Sequence[str], receptor_predictions: Tensor
) -> ExactMinDualPredictionBatch:
    require(len(candidate_ids) == len(receptor_predictions), "exact_min_prediction_candidate_count_mismatch")
    result = ExactMinDualPredictionBatch(
        candidate_ids=tuple(candidate_ids),
        values=exact_min_dual(receptor_predictions.float()),
    )
    result.validate()
    return result


def build_softmin_dual_prediction_batch(candidate_ids: Sequence[str], receptor_predictions: Tensor) -> None:
    """Removed V1 API retained only as an explicit fail-closed migration guard."""
    del candidate_ids, receptor_predictions
    raise RankCalibrationError("softmin_rank_builder_removed_use_exact_min_v1_1")


def noise_aware_pairlogit(
    predicted_exact_dual: ExactMinDualPredictionBatch,
    records: Sequence[RankPairRecord],
    *,
    tau_rank: float = RANK_TAU,
) -> Tensor:
    """Weighted PairLogit, reduced within parent then across parents.

    ``predicted_exact_dual`` is the typed exact-min product of direct R8/R9.
    Softmin and raw mappings are structurally rejected by the API.
    """
    require(len(records) == RANK_PAIRS_PER_STEP, "pair_batch_not_exactly_eight")
    require(math.isfinite(float(tau_rank)) and float(tau_rank) > 0.0, "rank_tau_invalid")
    require(isinstance(predicted_exact_dual, ExactMinDualPredictionBatch), "pairlogit_requires_typed_exact_min_batch")
    prediction_index = predicted_exact_dual.index()
    grouped: dict[str, list[Tensor]] = {}
    for record in records:
        record.validate()
        require(record.left_candidate_id in prediction_index, "pair_left_prediction_missing")
        require(record.right_candidate_id in prediction_index, "pair_right_prediction_missing")
        left = prediction_index[record.left_candidate_id]
        right = prediction_index[record.right_candidate_id]
        require(isinstance(left, Tensor) and isinstance(right, Tensor), "pair_prediction_not_tensor")
        require(left.numel() == 1 and right.numel() == 1, "pair_prediction_not_scalar")
        delta_prediction = left.float().reshape(()) - right.float().reshape(())
        value = F.softplus(-float(record.truth_sign) * delta_prediction / float(tau_rank))
        value = value * float(record.pair_weight)
        require_finite_tensor(value, "pairlogit_nonfinite")
        grouped.setdefault(record.parent_cluster_id, []).append(value)
    require(bool(grouped), "pairlogit_no_parent_groups")
    parent_means = [torch.stack(values).mean() for _, values in sorted(grouped.items())]
    result = torch.stack(parent_means).mean()
    require(result.dtype == torch.float32, "pairlogit_not_fp32")
    require_finite_tensor(result, "pairlogit_reduction_nonfinite")
    return result


@dataclass(frozen=True)
class CalibrationRow:
    candidate_id: str
    parent_cluster_id: str
    outer_fold: int
    fit_role: str
    predicted_r8: float
    predicted_r9: float
    true_r8: float
    true_r9: float

    def validate(self, expected_outer_fold: int, forbidden: set[str]) -> None:
        require(bool(self.candidate_id) and bool(self.parent_cluster_id), "calibration_identity_empty")
        require(self.outer_fold == expected_outer_fold, "calibration_outer_fold_mismatch")
        require(self.fit_role == CALIBRATION_FIT_ROLE, f"calibration_fit_role_invalid:{self.candidate_id}")
        require(self.candidate_id not in forbidden, f"outer_test_candidate_in_calibration:{self.candidate_id}")
        values = (self.predicted_r8, self.predicted_r9, self.true_r8, self.true_r9)
        require(all(math.isfinite(float(value)) for value in values), "calibration_value_nonfinite")


@dataclass(frozen=True)
class ReceptorAffineFit:
    slope: float
    intercept: float
    status: str
    fallback_reason: str | None
    row_count: int
    parent_count: int
    identity_objective: float
    fitted_objective: float
    raw_huber_identity: float
    raw_huber_fitted: float
    iterations: int

    def validate(self) -> None:
        require(CALIBRATION_SLOPE_BOUNDS[0] <= self.slope <= CALIBRATION_SLOPE_BOUNDS[1], "calibration_slope_bounds")
        require(
            CALIBRATION_INTERCEPT_BOUNDS[0] <= self.intercept <= CALIBRATION_INTERCEPT_BOUNDS[1],
            "calibration_intercept_bounds",
        )
        require(math.isfinite(self.identity_objective) and math.isfinite(self.fitted_objective), "calibration_objective_nonfinite")
        if self.status == "IDENTITY_FALLBACK":
            require(self.slope == 1.0 and self.intercept == 0.0, "calibration_fallback_not_identity")
            require(bool(self.fallback_reason), "calibration_fallback_reason_missing")
        else:
            require(self.status == "FITTED_POSITIVE_AFFINE", "calibration_status_invalid")
            require(self.fallback_reason is None, "calibration_fitted_has_fallback_reason")
            require(self.fitted_objective < self.identity_objective, "calibration_fit_not_better_than_identity")


@dataclass(frozen=True)
class FoldLocalPositiveAffineCalibration:
    outer_fold: int
    fit_role: str
    fit_data_sha256: str
    r8: ReceptorAffineFit
    r9: ReceptorAffineFit
    claim_boundary: str = CLAIM_BOUNDARY
    v4_f_or_test32_results_accessed: int = 0

    def validate(self) -> None:
        require(self.outer_fold >= 0, "calibration_outer_fold_invalid")
        require(self.fit_role == CALIBRATION_FIT_ROLE, "calibration_contract_fit_role_invalid")
        require(len(self.fit_data_sha256) == 64, "calibration_data_sha256_invalid")
        require(self.v4_f_or_test32_results_accessed == 0, "calibration_sealed_access_nonzero")
        self.r8.validate()
        self.r9.validate()

    def apply(self, receptor_predictions: Tensor) -> dict[str, Tensor]:
        self.validate()
        require(
            receptor_predictions.ndim == 2 and receptor_predictions.shape[1] == 2,
            "calibration_prediction_shape_invalid",
        )
        predictions = receptor_predictions.float()
        calibrated = torch.stack(
            (
                predictions[:, 0] * self.r8.slope + self.r8.intercept,
                predictions[:, 1] * self.r9.slope + self.r9.intercept,
            ),
            dim=1,
        )
        require_finite_tensor(calibrated, "calibrated_prediction_nonfinite")
        dual = exact_min_dual(calibrated)
        return {"calibrated_receptor_predictions": calibrated, "exact_min_dual": dual}

    def to_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": "pvrig_v2_6_fold_local_positive_affine_calibration_v1",
            "status": "PASS_FOLD_LOCAL_POSITIVE_AFFINE_OR_IDENTITY_FALLBACK",
            "outer_fold": self.outer_fold,
            "fit_role": self.fit_role,
            "fit_data_sha256": self.fit_data_sha256,
            "slope_bounds": list(CALIBRATION_SLOPE_BOUNDS),
            "intercept_bounds": list(CALIBRATION_INTERCEPT_BOUNDS),
            "huber_beta": CALIBRATION_HUBER_BETA,
            "identity_shrinkage": CALIBRATION_IDENTITY_SHRINKAGE,
            "r8": asdict(self.r8),
            "r9": asdict(self.r9),
            "derived_inference_target": "exact_min(calibrated_R8,calibrated_R9)",
            "claim_boundary": self.claim_boundary,
            "v4_f_or_test32_results_accessed": self.v4_f_or_test32_results_accessed,
        }


def _huber_values(residuals: Sequence[float], beta: float) -> list[float]:
    values: list[float] = []
    for residual in residuals:
        absolute = abs(residual)
        values.append(0.5 * residual * residual / beta if absolute < beta else absolute - 0.5 * beta)
    return values


def _affine_objective_and_gradient(
    predictions: Sequence[float],
    targets: Sequence[float],
    slope: float,
    intercept: float,
) -> tuple[float, float, float, float]:
    residuals = [slope * prediction + intercept - target for prediction, target in zip(predictions, targets)]
    raw_huber = sum(_huber_values(residuals, CALIBRATION_HUBER_BETA)) / len(residuals)
    objective = raw_huber + CALIBRATION_IDENTITY_SHRINKAGE * ((slope - 1.0) ** 2 + intercept**2)
    residual_gradients = [
        residual / CALIBRATION_HUBER_BETA if abs(residual) < CALIBRATION_HUBER_BETA else (1.0 if residual > 0.0 else -1.0)
        for residual in residuals
    ]
    slope_gradient = sum(gradient * prediction for gradient, prediction in zip(residual_gradients, predictions)) / len(predictions)
    intercept_gradient = sum(residual_gradients) / len(predictions)
    slope_gradient += 2.0 * CALIBRATION_IDENTITY_SHRINKAGE * (slope - 1.0)
    intercept_gradient += 2.0 * CALIBRATION_IDENTITY_SHRINKAGE * intercept
    return objective, slope_gradient, intercept_gradient, raw_huber


def _fit_one_receptor(
    predictions: Sequence[float],
    targets: Sequence[float],
    *,
    row_count: int,
    parent_count: int,
    minimum_rows: int,
    minimum_parents: int,
    max_iterations: int = 10000,
    tolerance: float = 1e-10,
) -> ReceptorAffineFit:
    identity_objective, _, _, raw_identity = _affine_objective_and_gradient(predictions, targets, 1.0, 0.0)

    def identity(reason: str, iterations: int = 0) -> ReceptorAffineFit:
        return ReceptorAffineFit(
            slope=1.0,
            intercept=0.0,
            status="IDENTITY_FALLBACK",
            fallback_reason=reason,
            row_count=row_count,
            parent_count=parent_count,
            identity_objective=identity_objective,
            fitted_objective=identity_objective,
            raw_huber_identity=raw_identity,
            raw_huber_fitted=raw_identity,
            iterations=iterations,
        )

    if row_count < minimum_rows:
        return identity("INSUFFICIENT_ROWS")
    if parent_count < minimum_parents:
        return identity("INSUFFICIENT_PARENTS")

    slope, intercept = 1.0, 0.0
    objective = identity_objective
    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        objective, slope_gradient, intercept_gradient, _ = _affine_objective_and_gradient(
            predictions, targets, slope, intercept
        )
        projected_slope = min(max(slope - slope_gradient, CALIBRATION_SLOPE_BOUNDS[0]), CALIBRATION_SLOPE_BOUNDS[1])
        projected_intercept = min(
            max(intercept - intercept_gradient, CALIBRATION_INTERCEPT_BOUNDS[0]),
            CALIBRATION_INTERCEPT_BOUNDS[1],
        )
        projected_gradient_norm = math.hypot(projected_slope - slope, projected_intercept - intercept)
        if projected_gradient_norm <= tolerance:
            converged = True
            break
        step = 1.0
        accepted = False
        for _ in range(80):
            candidate_slope = min(
                max(slope - step * slope_gradient, CALIBRATION_SLOPE_BOUNDS[0]),
                CALIBRATION_SLOPE_BOUNDS[1],
            )
            candidate_intercept = min(
                max(intercept - step * intercept_gradient, CALIBRATION_INTERCEPT_BOUNDS[0]),
                CALIBRATION_INTERCEPT_BOUNDS[1],
            )
            candidate_objective, _, _, _ = _affine_objective_and_gradient(
                predictions, targets, candidate_slope, candidate_intercept
            )
            displacement_dot_gradient = (
                slope_gradient * (candidate_slope - slope)
                + intercept_gradient * (candidate_intercept - intercept)
            )
            if candidate_objective <= objective + 1e-4 * displacement_dot_gradient:
                accepted = True
                slope, intercept = candidate_slope, candidate_intercept
                if abs(objective - candidate_objective) <= tolerance:
                    converged = True
                objective = candidate_objective
                break
            step *= 0.5
        if not accepted:
            return identity("OPTIMIZER_LINE_SEARCH_FAILED", iterations)
        if converged:
            break
    if not converged:
        return identity("OPTIMIZER_NOT_CONVERGED", iterations)
    fitted_objective, _, _, raw_fitted = _affine_objective_and_gradient(predictions, targets, slope, intercept)
    if not math.isfinite(fitted_objective) or fitted_objective >= identity_objective - 1e-12:
        return identity("NO_STRICT_OBJECTIVE_IMPROVEMENT", iterations)
    result = ReceptorAffineFit(
        slope=slope,
        intercept=intercept,
        status="FITTED_POSITIVE_AFFINE",
        fallback_reason=None,
        row_count=row_count,
        parent_count=parent_count,
        identity_objective=identity_objective,
        fitted_objective=fitted_objective,
        raw_huber_identity=raw_identity,
        raw_huber_fitted=raw_fitted,
        iterations=iterations,
    )
    result.validate()
    return result


def fit_fold_local_positive_affine(
    rows: Sequence[CalibrationRow],
    *,
    outer_fold: int,
    forbidden_candidate_ids: Iterable[str] = (),
    minimum_rows: int = 16,
    minimum_parents: int = 4,
) -> FoldLocalPositiveAffineCalibration:
    """Fit constrained R8/R9 calibration on strict inner-OOF outer-train rows."""
    require(outer_fold >= 0, "calibration_outer_fold_invalid")
    require(minimum_rows > 0 and minimum_parents > 0, "calibration_minimum_support_invalid")
    require(bool(rows), "calibration_rows_empty")
    forbidden = set(forbidden_candidate_ids)
    seen: set[str] = set()
    for row in rows:
        row.validate(outer_fold, forbidden)
        require(row.candidate_id not in seen, f"duplicate_calibration_candidate:{row.candidate_id}")
        seen.add(row.candidate_id)
    parents = {row.parent_cluster_id for row in rows}
    fit_payload = [asdict(row) for row in sorted(rows, key=lambda item: item.candidate_id)]
    r8 = _fit_one_receptor(
        [float(row.predicted_r8) for row in rows],
        [float(row.true_r8) for row in rows],
        row_count=len(rows),
        parent_count=len(parents),
        minimum_rows=minimum_rows,
        minimum_parents=minimum_parents,
    )
    r9 = _fit_one_receptor(
        [float(row.predicted_r9) for row in rows],
        [float(row.true_r9) for row in rows],
        row_count=len(rows),
        parent_count=len(parents),
        minimum_rows=minimum_rows,
        minimum_parents=minimum_parents,
    )
    result = FoldLocalPositiveAffineCalibration(
        outer_fold=outer_fold,
        fit_role=CALIBRATION_FIT_ROLE,
        fit_data_sha256=canonical_sha256(fit_payload),
        r8=r8,
        r9=r9,
    )
    result.validate()
    return result


def implementation_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "delta_noise": {
            "value": FROZEN_DELTA_NOISE,
            "decimals": FROZEN_DELTA_NOISE_DECIMALS,
            "binding_sha256": FROZEN_BINDING_SHA256,
            "estimated_from": "nonadaptive_V4D_225_three_seed_candidates",
            "not_transferred_to_adaptive_v4h_rank_pairs": True,
        },
        "dual": {
            "scalar_auxiliary_training_may_use": "FP32_normalized_softmin_tau_0.02",
            "ranking": "FP32_exact_min_only",
            "inference": "exact_min(calibrated_R8,calibrated_R9)",
            "independent_Rdual_output_allowed": False,
        },
        "rank_eligibility": {
            "policy_id": RANK_ELIGIBILITY_POLICY_ID,
            "eligible": {
                "teacher_source": RANK_ELIGIBLE_TEACHER_SOURCE,
                "development_reliability_tier": RANK_ELIGIBLE_RELIABILITY_TIER,
                "docking_evidence_tier": RANK_ELIGIBLE_DOCKING_TIER,
                "teacher_reliability": RANK_ELIGIBLE_TEACHER_RELIABILITY,
                "ranking_release": RANK_ELIGIBLE_RELEASE,
            },
            "adaptive_v4h": "scalar_only_until_random_sentinel_source_tier_noise_is_frozen",
        },
        "parent_pair_epoch_cache": {
            "pairs_per_scalar_optimizer_step": RANK_PAIRS_PER_STEP,
            "minimum_rank_eligible_parents": MINIMUM_RANK_ELIGIBLE_PARENTS,
            "parent_sampling": "balanced_round_robin_max_count_difference_1",
            "within_parent_sampling": "without_replacement_then_deterministic_cycle",
            "split_firewall": "TRAIN_only_and_explicit_forbidden_candidate_rejection",
            "external_hash_binding": "expected_training_split_sha256_and_expected_label_sha256_required",
        },
        "pairlogit": {
            "tau": RANK_TAU,
            "pair_weight": "min(abs_truth_delta/delta_noise,3)",
            "reduction": "mean_within_parent_then_mean_across_parents",
            "prediction_input": "typed_FP32_exact_min_batch_from_direct_R8_R9",
        },
        "calibration": {
            "fit_role": CALIBRATION_FIT_ROLE,
            "per_receptor_positive_affine": True,
            "slope_bounds": list(CALIBRATION_SLOPE_BOUNDS),
            "intercept_bounds": list(CALIBRATION_INTERCEPT_BOUNDS),
            "huber_beta": CALIBRATION_HUBER_BETA,
            "identity_shrinkage": CALIBRATION_IDENTITY_SHRINKAGE,
            "identity_fallback": True,
            "exact_min_after_calibration": True,
        },
        "forbidden": {
            "outer_test_fit_or_recalibration": True,
            "validation_or_outer_test_rank_pairs": True,
            "parent_id_as_predictor": True,
            "softmin_in_rank_loss": True,
            "adaptive_v4h_rank_pairs_without_source_specific_noise": True,
            "v4_f_or_test32_access": True,
        },
        "v4_f_or_test32_results_accessed": 0,
    }
