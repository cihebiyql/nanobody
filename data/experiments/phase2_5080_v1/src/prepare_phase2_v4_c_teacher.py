#!/usr/bin/env python3
"""Build continuous V4-C teacher rows from a fresh dual-docking aggregate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "phase2_v4_c_continuous_teacher_v1"
EXPECTED_JOB_MANIFEST_SHA256 = "e159027b23e76b041a02f3034a204379053f9d0780e2f8bdfc599d431c1a425e"
EXPECTED_PROTOCOL_LOCK_SHA256 = "6ea729edc9b070bba7271bea3c64da0fffad46921ea8899548eb9b1ad8a120a7"
EXPECTED_TOTAL_JOBS = 1050
CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-computational-dual-docking continuous teacher only; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


class TeacherBuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise TeacherBuildError("refusing_to_write_empty_teacher")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def as_float(value: Any, *, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise TeacherBuildError(f"invalid_float:{field}:{value!r}") from exc
    if not math.isfinite(output):
        raise TeacherBuildError(f"non_finite_float:{field}:{value!r}")
    return output


def soft_scale(value: float, threshold: float) -> float:
    if value < 0.0 or threshold <= 0.0:
        raise TeacherBuildError("soft_scale_requires_nonnegative_value_and_positive_threshold")
    return value / (value + threshold)


def native_pose_utility(row: Mapping[str, Any]) -> float:
    full_hotspot = as_float(row.get("hotspot_overlap"), field="hotspot_overlap")
    holdout_hotspot = as_float(row.get("holdout_overlap"), field="holdout_overlap")
    total_occlusion = as_float(row.get("total_occlusion"), field="total_occlusion")
    cdr3_occlusion = as_float(row.get("cdr3_occlusion"), field="cdr3_occlusion")
    cdr3_fraction = as_float(row.get("cdr3_fraction"), field="cdr3_fraction")
    score = (
        0.15 * min(max(full_hotspot / 23.0, 0.0), 1.0)
        + 0.25 * min(max(holdout_hotspot / 11.0, 0.0), 1.0)
        + 0.25 * soft_scale(total_occlusion, 500.0)
        + 0.20 * soft_scale(cdr3_occlusion, 100.0)
        + 0.15 * soft_scale(cdr3_fraction, 0.15)
    )
    if not 0.0 <= score <= 1.0:
        raise TeacherBuildError(f"pose_utility_out_of_bounds:{score}")
    return score


def rank_weights(count: int) -> list[float]:
    if count < 1:
        raise TeacherBuildError("rank_weights_requires_positive_count")
    raw = [1.0 / math.log2(rank + 1.0) for rank in range(1, count + 1)]
    total = sum(raw)
    return [value / total for value in raw]


def mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        raise TeacherBuildError("mean_requires_values")
    return sum(values) / len(values)


def job_summary(
    job_id: str,
    dock_conformation: str,
    pose_rows: list[dict[str, str]],
    job_result: Mapping[str, str],
) -> dict[str, Any]:
    by_model: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in pose_rows:
        by_model[row["model"]][row["scoring_reference"].lower()] = row
    complete = [
        refs for refs in by_model.values() if set(refs) == set(CONFORMATIONS)
    ]
    if len(complete) < 4:
        raise TeacherBuildError(f"job_has_fewer_than_4_complete_models:{job_id}:{len(complete)}")

    def score_key(refs: Mapping[str, Mapping[str, str]]) -> tuple[float, str]:
        native = refs[dock_conformation]
        try:
            score = as_float(native.get("haddock_score"), field="haddock_score")
        except TeacherBuildError:
            score = math.inf
        return score, native.get("model", "")

    complete.sort(key=score_key)
    weights = rank_weights(len(complete))
    metric_fields = (
        "hotspot_overlap",
        "anchor_overlap",
        "holdout_overlap",
        "total_occlusion",
        "cdr3_occlusion",
        "cdr3_fraction",
        "clash_residue_pairs",
        "overlay_rmsd_a",
    )
    summary: dict[str, Any] = {
        "job_id": job_id,
        "dock_conformation": dock_conformation,
        "seed": str(job_result.get("seed", "")),
        "complete_model_count": len(complete),
        "job_utility": sum(
            weight * native_pose_utility(refs[dock_conformation])
            for weight, refs in zip(weights, complete)
        ),
        "native_cross_support_agreement": as_float(
            job_result.get("model_native_cross_support_agreement_fraction", 0.0),
            field="model_native_cross_support_agreement_fraction",
        ),
        "model_pair_consensus_fraction": as_float(
            job_result.get("model_pair_consensus_fraction", 0.0),
            field="model_pair_consensus_fraction",
        ),
        "model_strict_a_fraction": as_float(
            job_result.get("model_strict_a_fraction", 0.0),
            field="model_strict_a_fraction",
        ),
    }
    for field in metric_fields:
        summary[field] = sum(
            weight * as_float(refs[dock_conformation].get(field), field=field)
            for weight, refs in zip(weights, complete)
        )
    return summary


def build_candidate_teacher(
    split_row: Mapping[str, str],
    job_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    by_conformation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in job_summaries:
        by_conformation[row["dock_conformation"]].append(row)
    if set(by_conformation) != set(CONFORMATIONS):
        raise TeacherBuildError(f"candidate_missing_conformation:{split_row['candidate_id']}")
    for conformation in CONFORMATIONS:
        if len(by_conformation[conformation]) < 2:
            raise TeacherBuildError(
                f"candidate_has_fewer_than_2_successful_seeds:{split_row['candidate_id']}:{conformation}"
            )

    receptor_scores = {
        conformation: statistics.median(
            row["job_utility"] for row in by_conformation[conformation]
        )
        for conformation in CONFORMATIONS
    }
    receptor_sd = {
        conformation: statistics.pstdev(
            row["job_utility"] for row in by_conformation[conformation]
        )
        for conformation in CONFORMATIONS
    }
    r8 = receptor_scores["8x6b"]
    r9 = receptor_scores["9e6y"]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": split_row["candidate_id"],
        "sequence_sha256": split_row["sequence_sha256"],
        "sequence": split_row["sequence"],
        "cdr1": split_row["cdr1"],
        "cdr2": split_row["cdr2"],
        "cdr3": split_row["cdr3"],
        "phase": split_row["phase"],
        "scaffold_id": split_row["scaffold_id"],
        "h3_regime": split_row["h3_regime"],
        "near_cdr3_family_id": split_row["near_cdr3_family_id"],
        "selection_bucket": split_row["selection_bucket"],
        "model_split": split_row["model_split"],
        "R_8X6B": round(r8, 9),
        "R_9E6Y": round(r9, 9),
        "R_dual_mean": round((r8 + r9) / 2.0, 9),
        "R_dual_min": round(min(r8, r9), 9),
        "R_dual_gap": round(abs(r8 - r9), 9),
        "seed_sd_8X6B": round(receptor_sd["8x6b"], 9),
        "seed_sd_9E6Y": round(receptor_sd["9e6y"], 9),
        "successful_seed_count_8X6B": len(by_conformation["8x6b"]),
        "successful_seed_count_9E6Y": len(by_conformation["9e6y"]),
        "native_cross_support_agreement_mean": round(
            mean(row["native_cross_support_agreement"] for row in job_summaries), 9
        ),
        "model_pair_consensus_fraction_mean": round(
            mean(row["model_pair_consensus_fraction"] for row in job_summaries), 9
        ),
        "model_strict_a_fraction_mean": round(
            mean(row["model_strict_a_fraction"] for row in job_summaries), 9
        ),
    }
    for conformation in CONFORMATIONS:
        suffix = "8X6B" if conformation == "8x6b" else "9E6Y"
        for field in (
            "hotspot_overlap",
            "anchor_overlap",
            "holdout_overlap",
            "total_occlusion",
            "cdr3_occlusion",
            "cdr3_fraction",
            "clash_residue_pairs",
            "overlay_rmsd_a",
        ):
            result[f"{field}_median_{suffix}"] = round(
                statistics.median(row[field] for row in by_conformation[conformation]), 9
            )
    result["teacher_uncertainty"] = round(
        max(receptor_sd.values()) + abs(r8 - r9), 9
    )
    result["claim_boundary"] = CLAIM_BOUNDARY
    return result


def validate_evaluator(evaluator: Mapping[str, Any]) -> None:
    failures: list[str] = []
    if evaluator.get("status") != "PASS":
        failures.append(f"evaluator_status_{evaluator.get('status', 'MISSING')}")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        failures.append("evaluator_not_production_pose_backed")
    if int(evaluator.get("job_count", 0) or 0) != EXPECTED_TOTAL_JOBS:
        failures.append("evaluator_job_count_not_1050")
    if evaluator.get("job_manifest_sha256") != EXPECTED_JOB_MANIFEST_SHA256:
        failures.append("evaluator_job_manifest_sha256_mismatch")
    if evaluator.get("protocol_lock_sha256") != EXPECTED_PROTOCOL_LOCK_SHA256:
        failures.append("evaluator_protocol_lock_sha256_mismatch")
    terminal = evaluator.get("gates", {}).get("all_jobs_terminal", {}).get("status")
    if terminal != "PASS":
        failures.append(f"all_jobs_terminal_gate_{terminal or 'MISSING'}")
    if failures:
        raise TeacherBuildError("teacher_release_gate_failed:" + ",".join(failures))


def build_teacher_rows(
    split_rows: list[dict[str, str]],
    job_manifest: list[dict[str, str]],
    job_results: list[dict[str, str]],
    pose_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    jobs_by_id = {row["job_id"]: row for row in job_manifest}
    results_by_id = {row["job_id"]: row for row in job_results}
    if len(jobs_by_id) != EXPECTED_TOTAL_JOBS or len(results_by_id) != EXPECTED_TOTAL_JOBS:
        raise TeacherBuildError(
            f"expected_1050_jobs_and_results_got_{len(jobs_by_id)}_{len(results_by_id)}"
        )
    for job_id, result in results_by_id.items():
        manifest = jobs_by_id.get(job_id)
        if manifest is None or result.get("job_hash") != manifest.get("job_hash"):
            raise TeacherBuildError(f"job_hash_closure_failed:{job_id}")

    poses_by_job: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pose_rows:
        poses_by_job[row["job_id"]].append(row)
    summaries_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job_id, manifest in jobs_by_id.items():
        if manifest.get("entity_type") != "candidate":
            continue
        result = results_by_id[job_id]
        if str(result.get("state", "")).upper() not in SUCCESS_STATES:
            continue
        if str(result.get("pose_backed_2x2", "")).lower() != "true":
            continue
        summaries_by_candidate[manifest["entity_id"]].append(
            job_summary(job_id, manifest["conformation"], poses_by_job[job_id], result)
        )

    output = [
        build_candidate_teacher(split_row, summaries_by_candidate[split_row["candidate_id"]])
        for split_row in split_rows
    ]
    output.sort(key=lambda row: row["candidate_id"])
    return output


def release_rows(rows: list[dict[str, Any]], release: str, formal_unseal: bool) -> list[dict[str, Any]]:
    if release == "open":
        selected = [row for row in rows if row["model_split"] == "OPEN_DEVELOPMENT"]
        expected = 96
    elif release == "formal":
        if not formal_unseal:
            raise TeacherBuildError("formal_release_requires_explicit_formal_unseal")
        selected = [row for row in rows if row["model_split"] == "UNTOUCHED_TEST"]
        expected = 32
    else:
        raise TeacherBuildError(f"unknown_release:{release}")
    if len(selected) != expected:
        raise TeacherBuildError(f"expected_{expected}_{release}_rows_got_{len(selected)}")
    return selected


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_c/dual128_split_manifest.tsv",
    )
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--pose-scores", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--release", choices=("open", "formal"), default="open")
    parser.add_argument("--formal-unseal", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    evaluator = json.loads(args.evaluator.read_text(encoding="utf-8"))
    validate_evaluator(evaluator)
    if sha256_file(args.job_manifest) != EXPECTED_JOB_MANIFEST_SHA256:
        raise TeacherBuildError("job_manifest_file_sha256_mismatch")
    all_rows = build_teacher_rows(
        read_tsv(args.split_manifest),
        read_tsv(args.job_manifest),
        read_tsv(args.job_results),
        read_tsv(args.pose_scores),
    )
    selected = release_rows(all_rows, args.release, args.formal_unseal)
    write_tsv(args.out, selected)
    audit_path = args.out.with_suffix(args.out.suffix + ".audit.json")
    write_json(
        audit_path,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_V4_C_CONTINUOUS_TEACHER_RELEASE",
            "release": args.release,
            "row_count": len(selected),
            "formal_unseal": bool(args.formal_unseal),
            "inputs": {
                "split_manifest_sha256": sha256_file(args.split_manifest),
                "job_manifest_sha256": sha256_file(args.job_manifest),
                "job_results_sha256": sha256_file(args.job_results),
                "pose_scores_sha256": sha256_file(args.pose_scores),
                "evaluator_sha256": sha256_file(args.evaluator),
            },
            "output": {"path": str(args.out), "sha256": sha256_file(args.out)},
            "primary_target": "R_dual_min",
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "release": args.release,
                "row_count": len(selected),
                "out": str(args.out),
                "audit": str(audit_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
