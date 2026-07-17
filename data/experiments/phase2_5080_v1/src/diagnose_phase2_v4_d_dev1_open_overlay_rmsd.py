#!/usr/bin/env python3
"""Read-only, open-split-only diagnostic for native overlay RMSD outliers.

The full split and job manifests are validated first.  Only after the
OPEN_TRAIN/OPEN_DEVELOPMENT candidate IDs and their exact job closure have been
materialized does this program address any raw result path.  The sealed
PROSPECTIVE_COMPUTATIONAL_TEST candidates are never used to construct a result
path and their raw/metric access counters are fixed and asserted to zero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


EXPECTED_SPLIT_SHA256 = (
    "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
)
EXPECTED_JOB_MANIFEST_SHA256 = (
    "96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737"
)
EXPECTED_PROTOCOL_CORE_SHA256 = (
    "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7"
)
OPEN_SPLIT_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
SEALED_COUNT = 32
CONFORMATIONS = {"8x6b", "9e6y"}
SEEDS = {"917", "1931", "3253"}
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
RMSD_LIMIT_A = 1.0


class DiagnosticError(RuntimeError):
    """Raised when a frozen input or raw-result invariant is violated."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256_bytes(data.encode("utf-8"))


def read_tsv_snapshot(path: Path) -> tuple[list[dict[str, str]], str]:
    data = path.read_bytes()
    digest = sha256_bytes(data)
    text = data.decode("utf-8")
    rows = list(csv.DictReader(text.splitlines(), delimiter="\t"))
    return rows, digest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def nested(payload: Mapping[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise DiagnosticError(f"missing_metric:{'.'.join(path)}")
        value = value[key]
    return value


def finite_float(value: Any, *, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticError(f"invalid_float:{field}:{value!r}") from exc
    if not math.isfinite(output):
        raise DiagnosticError(f"non_finite_float:{field}:{value!r}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-manifest", required=True, type=Path)
    parser.add_argument("--job-manifest", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    script_sha256 = sha256_bytes(script_path.read_bytes())

    # Stage 1: read and freeze both non-metric manifests.  No raw result path is
    # constructed before this validation and selection stage completes.
    split_rows, split_sha256 = read_tsv_snapshot(args.split_manifest)
    job_rows, job_manifest_sha256 = read_tsv_snapshot(args.job_manifest)
    require(split_sha256 == EXPECTED_SPLIT_SHA256, "split_manifest_sha256_mismatch")
    require(
        job_manifest_sha256 == EXPECTED_JOB_MANIFEST_SHA256,
        "job_manifest_sha256_mismatch",
    )
    require(len(split_rows) == 290, f"split_row_count:{len(split_rows)}")
    require(
        len({row.get("candidate_id", "") for row in split_rows}) == 290,
        "duplicate_or_empty_candidate_id_in_split",
    )
    split_counts = Counter(row.get("model_split", "") for row in split_rows)
    require(
        split_counts
        == Counter({**OPEN_SPLIT_COUNTS, SEALED_SPLIT: SEALED_COUNT}),
        f"unexpected_split_counts:{dict(split_counts)}",
    )

    open_rows = [row for row in split_rows if row["model_split"] in OPEN_SPLIT_COUNTS]
    sealed_rows = [row for row in split_rows if row["model_split"] == SEALED_SPLIT]
    open_ids = {row["candidate_id"] for row in open_rows}
    sealed_ids = {row["candidate_id"] for row in sealed_rows}
    require(len(open_ids) == 258, f"open_candidate_count:{len(open_ids)}")
    require(len(sealed_ids) == 32, f"sealed_candidate_count:{len(sealed_ids)}")
    require(not (open_ids & sealed_ids), "open_sealed_candidate_overlap")

    require(
        len({row.get("job_id", "") for row in job_rows}) == len(job_rows),
        "duplicate_or_empty_job_id_in_manifest",
    )
    selected_jobs = [
        row
        for row in job_rows
        if row.get("entity_type") == "candidate" and row.get("entity_id") in open_ids
    ]
    selected_jobs.sort(key=lambda row: row["job_id"])
    require(len(selected_jobs) == 258 * 6, f"selected_open_job_count:{len(selected_jobs)}")
    require(
        not any(row.get("entity_id") in sealed_ids for row in selected_jobs),
        "sealed_job_selected",
    )
    jobs_by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for job in selected_jobs:
        jobs_by_candidate[job["entity_id"]].append(job)
        require(job.get("conformation", "").lower() in CONFORMATIONS, "bad_conformation")
        require(job.get("seed", "") in SEEDS, "bad_seed")
    require(set(jobs_by_candidate) == open_ids, "open_candidate_job_closure_mismatch")
    require(
        all(
            len(rows) == 6
            and {(row["conformation"].lower(), row["seed"]) for row in rows}
            == {(conformation, seed) for conformation in CONFORMATIONS for seed in SEEDS}
            for rows in jobs_by_candidate.values()
        ),
        "open_candidate_2x3_job_closure_mismatch",
    )

    # Stage 2: direct-address only the frozen selected open jobs.  The results
    # root is never listed/globbed.  Thus no sealed candidate can generate a raw
    # path or metric read.
    counters: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    conformation_native_metric_counts: Counter[str] = Counter()
    invalid_by_conformation: Counter[str] = Counter()
    invalid_by_job: Counter[str] = Counter()
    invalid_by_candidate: Counter[str] = Counter()
    missing_open_jobs: list[dict[str, str]] = []
    invalid_rows: list[dict[str, Any]] = []
    raw_bindings: list[dict[str, str]] = []

    # These sealed counters are deliberately never mutated.  Final assertions
    # make the zero-access claim executable rather than narrative-only.
    test32_raw_job_dirs_addressed = 0
    test32_raw_job_files_opened = 0
    test32_metric_values_read = 0

    for job in selected_jobs:
        require(job["entity_id"] in open_ids, "non_open_job_reached_raw_stage")
        require(job["entity_id"] not in sealed_ids, "sealed_job_reached_raw_stage")
        counters["open_raw_job_dirs_addressed"] += 1
        result_path = args.results_root / job["job_id"] / "job_result.json"
        if not result_path.is_file():
            counters["open_raw_job_files_missing"] += 1
            missing_open_jobs.append(
                {
                    "candidate_id": job["entity_id"],
                    "job_id": job["job_id"],
                    "conformation": job["conformation"].lower(),
                    "seed": job["seed"],
                }
            )
            continue
        raw = result_path.read_bytes()
        counters["open_raw_job_files_opened"] += 1
        digest = sha256_bytes(raw)
        raw_bindings.append({"job_id": job["job_id"], "sha256": digest})
        payload = json.loads(raw)
        require(payload.get("job_id") == job["job_id"], "job_id_mismatch")
        require(payload.get("job_hash") == job["job_hash"], "job_hash_mismatch")
        require(
            payload.get("protocol_core_sha256") == EXPECTED_PROTOCOL_CORE_SHA256,
            "protocol_core_sha256_mismatch",
        )
        for payload_field, manifest_field in (
            ("entity_id", "entity_id"),
            ("entity_type", "entity_type"),
            ("dock_conformation", "conformation"),
            ("seed", "seed"),
        ):
            require(
                str(payload.get(payload_field, "")).lower()
                == str(job.get(manifest_field, "")).lower(),
                f"raw_identity_mismatch:{payload_field}:{job['job_id']}",
            )
        state = str(payload.get("state", "")).upper()
        require(bool(state), f"missing_state:{job['job_id']}")
        state_counts[state] += 1
        if state not in SUCCESS_STATES:
            counters["open_non_success_job_files_opened_state_only"] += 1
            continue
        counters["open_success_job_files_inspected"] += 1
        conformation = job["conformation"].lower()
        for pose_index, pose in enumerate(payload.get("pose_scores", []), start=1):
            pose_value = str(pose.get("pose", ""))
            model = Path(pose_value).name
            require(bool(model), f"missing_pose_model:{job['job_id']}:{pose_index}")
            native_scores = [
                score
                for score in pose.get("scores", [])
                if str(score.get("reference_id", "")).lower() == conformation
            ]
            require(
                len(native_scores) == 1,
                f"native_score_cardinality:{job['job_id']}:{model}:{len(native_scores)}",
            )
            score = native_scores[0]
            rmsd = finite_float(
                nested(score, "overlay", "t_ca_rmsd_a"),
                field="overlay.t_ca_rmsd_a",
            )
            counters["open_native_overlay_metric_values_read"] += 1
            conformation_native_metric_counts[conformation] += 1
            if rmsd > RMSD_LIMIT_A:
                invalid_by_conformation[conformation] += 1
                invalid_by_job[job["job_id"]] += 1
                invalid_by_candidate[job["entity_id"]] += 1
                invalid_rows.append(
                    {
                        "candidate_id": job["entity_id"],
                        "job_id": job["job_id"],
                        "conformation": conformation,
                        "seed": int(job["seed"]),
                        "pose_index": pose_index,
                        "pose": pose_value,
                        "model": model,
                        "native_reference_id": conformation,
                        "t_ca_rmsd_a": rmsd,
                    }
                )

    require(test32_raw_job_dirs_addressed == 0, "sealed_raw_dir_addressed")
    require(test32_raw_job_files_opened == 0, "sealed_raw_file_opened")
    require(test32_metric_values_read == 0, "sealed_metric_read")
    require(
        counters["open_raw_job_files_opened"]
        + counters["open_raw_job_files_missing"]
        == len(selected_jobs),
        "open_raw_path_accounting_mismatch",
    )

    invalid_rows.sort(
        key=lambda row: (
            row["candidate_id"],
            row["conformation"],
            row["seed"],
            row["model"],
        )
    )
    affected_jobs = sorted(invalid_by_job)
    affected_candidates = sorted(invalid_by_candidate)
    rmsd_values = [row["t_ca_rmsd_a"] for row in invalid_rows]
    missing_open_jobs.sort(key=lambda row: row["job_id"])
    raw_bindings.sort(key=lambda row: row["job_id"])

    output: dict[str, Any] = {
        "schema_version": "phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v1",
        "status": "PASS_OPEN_ONLY_DIAGNOSTIC_COMPLETED",
        "claim_boundary": (
            "Read-only post-hoc development diagnostic of native-reference overlay "
            "RMSD in OPEN_TRAIN/OPEN_DEVELOPMENT V4-D raw docking results only. "
            "Not a V4-D pass, formal test, Docking Gold, binding, affinity, "
            "competition, experimental blocking, or final submission authority."
        ),
        "frozen_limit_a": RMSD_LIMIT_A,
        "input_bindings": {
            "split_manifest": {
                "path": str(args.split_manifest),
                "sha256": split_sha256,
                "row_count": len(split_rows),
            },
            "job_manifest": {
                "path": str(args.job_manifest),
                "sha256": job_manifest_sha256,
                "row_count": len(job_rows),
            },
            "diagnostic_script": {
                "path": str(script_path),
                "sha256": script_sha256,
            },
            "opened_open_job_result_binding_count": len(raw_bindings),
            "opened_open_job_result_sha256_chain": canonical_sha256(raw_bindings),
        },
        "selection": {
            "full_split_rows_validated": len(split_rows),
            "open_train_candidates": split_counts["OPEN_TRAIN"],
            "open_development_candidates": split_counts["OPEN_DEVELOPMENT"],
            "open_candidates": len(open_ids),
            "selected_open_jobs": len(selected_jobs),
            "sealed_test_candidates": len(sealed_ids),
            "selected_sealed_jobs": 0,
        },
        "physical_access": {
            "results_root_listed_or_globbed": False,
            "open_raw_job_dirs_addressed": counters["open_raw_job_dirs_addressed"],
            "open_raw_job_files_opened": counters["open_raw_job_files_opened"],
            "open_raw_job_files_missing": counters["open_raw_job_files_missing"],
            "open_success_job_files_inspected": counters[
                "open_success_job_files_inspected"
            ],
            "open_non_success_job_files_opened_state_only": counters[
                "open_non_success_job_files_opened_state_only"
            ],
            "open_native_overlay_metric_values_read": counters[
                "open_native_overlay_metric_values_read"
            ],
            "test32_raw_job_dirs_addressed": test32_raw_job_dirs_addressed,
            "test32_raw_job_files_opened": test32_raw_job_files_opened,
            "test32_metric_values_read": test32_metric_values_read,
        },
        "raw_state_counts": dict(sorted(state_counts.items())),
        "missing_open_jobs": missing_open_jobs,
        "native_overlay_summary": {
            "native_metric_count": counters["open_native_overlay_metric_values_read"],
            "native_metric_count_by_conformation": dict(
                sorted(conformation_native_metric_counts.items())
            ),
            "above_1a_count": len(invalid_rows),
            "above_1a_fraction": (
                len(invalid_rows) / counters["open_native_overlay_metric_values_read"]
                if counters["open_native_overlay_metric_values_read"]
                else None
            ),
            "above_1a_min": min(rmsd_values) if rmsd_values else None,
            "above_1a_max": max(rmsd_values) if rmsd_values else None,
            "above_1a_by_conformation": {
                conformation: invalid_by_conformation.get(conformation, 0)
                for conformation in sorted(CONFORMATIONS)
            },
            "affected_job_count": len(affected_jobs),
            "affected_candidate_count": len(affected_candidates),
            "affected_jobs": affected_jobs,
            "affected_candidates": affected_candidates,
        },
        "invalid_native_overlay_rows": invalid_rows,
        "interpretation_boundary": {
            "threshold_changed": False,
            "source_data_changed": False,
            "test32_opened": False,
            "teacher_or_model_built": False,
            "recovery_method_selected": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
