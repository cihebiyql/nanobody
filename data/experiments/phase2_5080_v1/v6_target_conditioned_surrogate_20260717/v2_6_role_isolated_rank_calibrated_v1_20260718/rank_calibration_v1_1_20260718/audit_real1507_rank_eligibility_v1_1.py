#!/usr/bin/env python3
"""Audit real1507 source/tier availability for V2.6 rank policy V1.1.

This tool reads only the open-development teacher table and frozen whole-parent
inner split manifest.  It does not read predictions, outer metrics, poses, or
V4-F/test32.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import rank_calibration_core_v1_1 as core


SCHEMA_VERSION = "pvrig_v2_6_real1507_rank_eligibility_audit_v1_1"
TEACHER_SHA256 = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
INNER_MANIFEST_SHA256 = "b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073"
REQUIRED_TEACHER_FIELDS = frozenset(
    {
        "schema_version", "candidate_id", "parent_framework_cluster", "teacher_source",
        "teacher_reliability", "docking_evidence_tier", "development_reliability_tier",
        "ranking_release", "successful_seed_count_8X6B", "successful_seed_count_9E6Y",
        "R_8X6B", "R_9E6Y", "R_dual_min",
    }
)
REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "schema_version", "outer_fold", "inner_fold", "candidate_id", "teacher_source",
        "parent_framework_cluster", "candidate_role", "input_table_sha256",
    }
)


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path, expected_sha256: str, required_fields: frozenset[str]) -> list[dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), f"input_not_regular_file:{path.name}")
    require(sha256_file(path) == expected_sha256, f"input_sha256_mismatch:{path.name}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"input_header_missing:{path.name}")
        require(required_fields <= set(reader.fieldnames), f"input_required_fields_missing:{path.name}")
        return list(reader)


def _candidate_label(row: Mapping[str, str]) -> core.CandidateLabel:
    return core.CandidateLabel(
        candidate_id=row["candidate_id"],
        parent_cluster_id=row["parent_framework_cluster"],
        true_r8=float(row["R_8X6B"]),
        true_r9=float(row["R_9E6Y"]),
        teacher_source=row["teacher_source"],
        development_reliability_tier=row["development_reliability_tier"],
        docking_evidence_tier=row["docking_evidence_tier"],
        teacher_reliability=row["teacher_reliability"],
        ranking_release=row["ranking_release"],
    )


def validate_teacher_rows(rows: Sequence[Mapping[str, str]]) -> tuple[list[core.CandidateLabel], dict[str, Any]]:
    require(len(rows) == 1507, f"teacher_row_count_mismatch:{len(rows)}")
    labels: list[core.CandidateLabel] = []
    seen: set[str] = set()
    source_tier_counts: Counter[tuple[str, str, str, str]] = Counter()
    source_seed_count_strata: Counter[tuple[str, int, int]] = Counter()
    for row in rows:
        require(row["schema_version"] == "pvrig_v6_training_table_v2_4", "teacher_schema_mismatch")
        label = _candidate_label(row)
        try:
            label.validate()
        except core.RankCalibrationError as exc:
            raise AuditError(str(exc)) from exc
        require(label.candidate_id not in seen, f"teacher_candidate_duplicate:{label.candidate_id}")
        seen.add(label.candidate_id)
        reported_dual = float(row["R_dual_min"])
        require(math.isfinite(reported_dual), f"teacher_dual_nonfinite:{label.candidate_id}")
        require(abs(reported_dual - label.true_dual) <= 1e-12, f"teacher_exact_min_mismatch:{label.candidate_id}")
        labels.append(label)
        source_tier_counts[
            (
                label.teacher_source,
                label.development_reliability_tier,
                label.docking_evidence_tier,
                label.teacher_reliability,
            )
        ] += 1
        source_seed_count_strata[
            (label.teacher_source, int(row["successful_seed_count_8X6B"]), int(row["successful_seed_count_9E6Y"]))
        ] += 1
    source_counts = Counter(label.teacher_source for label in labels)
    parent_counts = Counter(label.parent_cluster_id for label in labels)
    require(source_counts == {core.RANK_ELIGIBLE_TEACHER_SOURCE: 226, core.V4H_SOURCE: 1281}, "source_counts_mismatch")
    require(len(parent_counts) == 31, "teacher_parent_count_mismatch")
    require(sum(label.rank_eligible for label in labels) == 226, "rank_eligible_candidate_count_mismatch")
    expected_strata = {
        (core.RANK_ELIGIBLE_TEACHER_SOURCE, "A", "V4D_MULTI_SEED", "MULTI_SEED"): 226,
        (core.V4H_SOURCE, "A", "DUAL_3_SEED", "DUAL_3_SEED"): 123,
        (core.V4H_SOURCE, "B", "DUAL_2_SEED", "DUAL_2_SEED"): 241,
        (core.V4H_SOURCE, "C", "DUAL_1_SEED", "DUAL_1_SEED"): 917,
    }
    require(dict(source_tier_counts) == expected_strata, "source_tier_counts_mismatch")
    summary = {
        "candidate_count": len(labels),
        "parent_count": len(parent_counts),
        "source_counts": dict(sorted(source_counts.items())),
        "rank_eligible_candidate_count": 226,
        "rank_ineligible_candidate_count": 1281,
        "source_tier_counts": [
            {
                "teacher_source": key[0],
                "development_reliability_tier": key[1],
                "docking_evidence_tier": key[2],
                "teacher_reliability": key[3],
                "candidate_count": value,
            }
            for key, value in sorted(source_tier_counts.items())
        ],
        "source_successful_seed_count_strata": [
            {
                "teacher_source": key[0],
                "successful_seed_count_8X6B": key[1],
                "successful_seed_count_9E6Y": key[2],
                "candidate_count": value,
            }
            for key, value in sorted(source_seed_count_strata.items())
        ],
    }
    return labels, summary


def _pair_counts(labels: Sequence[core.CandidateLabel]) -> dict[str, Any]:
    by_parent: dict[str, list[core.CandidateLabel]] = defaultdict(list)
    for label in labels:
        if label.rank_eligible:
            by_parent[label.parent_cluster_id].append(label)
    total = eligible = discarded = 0
    eligible_parents = 0
    for parent in sorted(by_parent):
        parent_eligible = 0
        for left, right in itertools.combinations(by_parent[parent], 2):
            total += 1
            if abs(left.true_dual - right.true_dual) >= core.FROZEN_DELTA_NOISE:
                eligible += 1
                parent_eligible += 1
            else:
                discarded += 1
        if parent_eligible:
            eligible_parents += 1
    return {
        "rank_candidate_count": sum(label.rank_eligible for label in labels),
        "rank_parent_count": len(by_parent),
        "rank_eligible_parent_count": eligible_parents,
        "same_parent_unordered_pair_count": total,
        "eligible_pair_count": eligible,
        "below_noise_discard_count": discarded,
        "delta_noise": core.FROZEN_DELTA_NOISE,
    }


def _normalized_softmin_scalar(r8: float, r9: float) -> float:
    minimum = min(r8, r9)
    # Stable equivalent of normalized softmin for two finite scalars.
    return minimum - core.SOFTMIN_TAU * math.log(
        math.exp(-(r8 - minimum) / core.SOFTMIN_TAU)
        + math.exp(-(r9 - minimum) / core.SOFTMIN_TAU)
    ) + core.SOFTMIN_TAU * math.log(2.0)


def _softmin_diagnostic(labels: Sequence[core.CandidateLabel]) -> dict[str, Any]:
    bias = [_normalized_softmin_scalar(x.true_r8, x.true_r9) - x.true_dual for x in labels]
    by_parent: dict[str, list[core.CandidateLabel]] = defaultdict(list)
    for label in labels:
        by_parent[label.parent_cluster_id].append(label)
    thresholds = (0.0, 0.005, 0.01, core.FROZEN_DELTA_NOISE)
    sign_flip = {threshold: [0, 0] for threshold in thresholds}
    for siblings in by_parent.values():
        for left, right in itertools.combinations(siblings, 2):
            exact_delta = left.true_dual - right.true_dual
            soft_delta = (
                _normalized_softmin_scalar(left.true_r8, left.true_r9)
                - _normalized_softmin_scalar(right.true_r8, right.true_r9)
            )
            for threshold in thresholds:
                if exact_delta != 0.0 and abs(exact_delta) >= threshold:
                    sign_flip[threshold][1] += 1
                    if exact_delta * soft_delta < 0.0:
                        sign_flip[threshold][0] += 1
    return {
        "normalized_softmin_minus_exact_min": {
            "mean": statistics.mean(bias),
            "median": statistics.median(bias),
            "maximum": max(bias),
        },
        "within_parent_sign_flip_by_exact_delta_threshold": [
            {
                "threshold": threshold,
                "flip_count": sign_flip[threshold][0],
                "comparison_count": sign_flip[threshold][1],
                "flip_fraction": sign_flip[threshold][0] / sign_flip[threshold][1],
            }
            for threshold in thresholds
        ],
        "interpretation": "descriptive_teacher_diagnostic_only; V1.1 rank uses exact-min directly",
    }


def validate_inner_manifest(
    rows: Sequence[Mapping[str, str]], labels: Sequence[core.CandidateLabel]
) -> dict[str, Any]:
    label_index = {label.candidate_id: label for label in labels}
    require(len(rows) == 30140, f"inner_manifest_row_count_mismatch:{len(rows)}")
    partitions: dict[tuple[int, int], list[core.CandidateLabel]] = defaultdict(list)
    seen_partition_candidate: set[tuple[int, int, str]] = set()
    for row in rows:
        require(row["schema_version"] == "pvrig_v2_4_whole_parent_inner_split_manifest_v3", "inner_schema_mismatch")
        require(row["input_table_sha256"] == TEACHER_SHA256, "inner_teacher_hash_binding_mismatch")
        candidate_id = row["candidate_id"]
        require(candidate_id in label_index, f"inner_candidate_not_in_teacher:{candidate_id}")
        label = label_index[candidate_id]
        require(row["teacher_source"] == label.teacher_source, f"inner_teacher_source_mismatch:{candidate_id}")
        require(row["parent_framework_cluster"] == label.parent_cluster_id, f"inner_parent_mismatch:{candidate_id}")
        outer, inner = int(row["outer_fold"]), int(row["inner_fold"])
        require(0 <= outer < 5 and 0 <= inner < 5, "inner_fold_index_invalid")
        key = (outer, inner, candidate_id)
        require(key not in seen_partition_candidate, f"inner_partition_candidate_duplicate:{key}")
        seen_partition_candidate.add(key)
        require(row["candidate_role"] in {"train", "score"}, "inner_candidate_role_invalid")
        if row["candidate_role"] == "train":
            partitions[(outer, inner)].append(label)
    require(set(partitions) == {(outer, inner) for outer in range(5) for inner in range(5)}, "inner_partition_grid_incomplete")
    partition_audits = []
    for key in sorted(partitions):
        pair_audit = _pair_counts(partitions[key])
        require(
            pair_audit["rank_eligible_parent_count"] >= core.MINIMUM_RANK_ELIGIBLE_PARENTS,
            f"inner_rank_parent_support_below_eight:{key}",
        )
        partition_audits.append(
            {
                "outer_fold": key[0],
                "inner_fold": key[1],
                "train_candidate_count": len(partitions[key]),
                **pair_audit,
            }
        )
    return {
        "manifest_row_count": len(rows),
        "partition_count": len(partition_audits),
        "minimum_rank_eligible_parent_count": min(x["rank_eligible_parent_count"] for x in partition_audits),
        "minimum_rank_eligible_pair_count": min(x["eligible_pair_count"] for x in partition_audits),
        "partitions": partition_audits,
    }


def build_audit(teacher_path: Path, inner_manifest_path: Path) -> dict[str, Any]:
    teacher_rows = read_tsv(teacher_path, TEACHER_SHA256, REQUIRED_TEACHER_FIELDS)
    manifest_rows = read_tsv(inner_manifest_path, INNER_MANIFEST_SHA256, REQUIRED_MANIFEST_FIELDS)
    labels, teacher_summary = validate_teacher_rows(teacher_rows)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_REAL1507_EXACT_MIN_V4D_ONLY_RANK_POLICY_FEASIBLE",
        "inputs": {
            "teacher_sha256": TEACHER_SHA256,
            "inner_manifest_sha256": INNER_MANIFEST_SHA256,
        },
        "rank_eligibility_policy_id": core.RANK_ELIGIBILITY_POLICY_ID,
        "teacher": teacher_summary,
        "global_rank_pair_audit": _pair_counts(labels),
        "inner_train_partition_audit": validate_inner_manifest(manifest_rows, labels),
        "softmin_exact_min_diagnostic": _softmin_diagnostic(labels),
        "scientific_policy": {
            "scalar_supervision": "all_1507_R8_R9_rows",
            "rank_supervision": "V4D_A_multi_seed_only",
            "adaptive_v4h": "scalar_only_until_source_tier_specific_random_sentinel_noise_is_frozen",
            "rank_prediction": "FP32_exact_min_from_direct_R8_R9",
            "inference_prediction": "exact_min_from_direct_R8_R9_after_fold_local_calibration",
        },
        "claim_boundary": core.CLAIM_BOUNDARY,
        "v4_f_or_test32_results_accessed": 0,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--inner-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_audit(args.teacher, args.inner_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
