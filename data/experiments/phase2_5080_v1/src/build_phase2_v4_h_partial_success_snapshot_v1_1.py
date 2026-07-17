#!/usr/bin/env python3
"""Build a provenance-closed preview from currently successful V4-H jobs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "phase2_v4_h_partial_success_snapshot_v1_1"
STATUS = "COMPLETE_PARTIAL_DEVELOPMENT_PREVIEW_SNAPSHOT_NOT_TERMINAL"
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CONFORMATIONS = ("8x6b", "9e6y")
CLAIM_BOUNDARY = (
    "Partial active-campaign development preview from jobs successful at snapshot "
    "time; not terminal teacher, Docking Gold, binding, affinity, competition, "
    "experimental blocking, formal validation, or model-selection authority."
)


class SnapshotError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"empty_output:{path.name}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def load_scoring_function(adaptive_script: Path, scorer_path: Path) -> Callable[[dict[str, Any], str], float]:
    spec = importlib.util.spec_from_file_location("v4h_partial_snapshot_v1_1_adaptive", adaptive_script)
    require(spec is not None and spec.loader is not None, "cannot_load_adaptive_script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    scorer = module.load_scorer(scorer_path)
    require(callable(getattr(module, "summarize_job_fixed_top8", None)), "adaptive_scoring_function_missing")
    return lambda result, conformation: float(module.summarize_job_fixed_top8(result, conformation, scorer))


def build_snapshot(
    root: Path,
    adaptive_script: Path,
    scorer_path: Path,
    output_dir: Path,
    *,
    score_result: Callable[[dict[str, Any], str], float] | None = None,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    candidates_path = root / "inputs/candidates_290.tsv"
    jobs_path = root / "manifests/docking_jobs.tsv"
    require(candidates_path.is_file() and jobs_path.is_file(), "campaign_inputs_missing")
    require(adaptive_script.is_file() and scorer_path.is_file(), "scoring_implementation_missing")
    candidate_fields, candidates = read_tsv(candidates_path)
    required_candidate = {"candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"}
    require(required_candidate <= set(candidate_fields), "candidate_fields_missing")
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    require(len(candidate_by_id) == len(candidates) and len(candidates) > 0, "candidate_ids_invalid")
    job_fields, jobs = read_tsv(jobs_path)
    required_job = {"job_id", "entity_type", "entity_id", "conformation", "seed"}
    require(required_job <= set(job_fields), "job_fields_missing")
    jobs = [row for row in jobs if row["entity_type"] == "candidate" and row["entity_id"] in candidate_by_id]
    require(bool(jobs), "candidate_jobs_missing")

    # Freeze the successful job set first. Later completions are intentionally excluded.
    selected: list[tuple[dict[str, str], Path, str, Path, str]] = []
    for job in jobs:
        status_path = root / "status/jobs" / f"{job['job_id']}.json"
        if not status_path.is_file():
            continue
        status_sha = sha256_file(status_path)
        status = json.loads(status_path.read_text())
        if str(status.get("status", "")).upper() != "SUCCESS":
            continue
        result_path = root / "results" / job["job_id"] / "job_result.json"
        require(result_path.is_file(), f"success_result_missing:{job['job_id']}")
        selected.append((job, status_path, status_sha, result_path, sha256_file(result_path)))
    require(bool(selected), "no_successful_jobs_at_snapshot")
    scorer = score_result or load_scoring_function(adaptive_script, scorer_path)
    scores: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))
    provenance_rows: list[dict[str, Any]] = []
    score_valid_jobs = 0
    score_invalid_jobs = 0
    for job, status_path, status_sha, result_path, result_sha in selected:
        # Re-check immutable byte identities after selection and before scoring.
        require(sha256_file(status_path) == status_sha, f"status_changed_during_snapshot:{job['job_id']}")
        require(sha256_file(result_path) == result_sha, f"result_changed_during_snapshot:{job['job_id']}")
        result = json.loads(result_path.read_text())
        require(str(result.get("state", "")).upper() in SUCCESS_STATES, f"result_state_invalid:{job['job_id']}")
        conformation = job["conformation"].lower()
        require(conformation in CONFORMATIONS, f"conformation_invalid:{job['job_id']}")
        try:
            value = float(scorer(result, conformation))
            require(math.isfinite(value), f"score_nonfinite:{job['job_id']}")
        except Exception as error:
            score_invalid_jobs += 1
            provenance_rows.append({
                "schema_version": SCHEMA_VERSION,
                "job_id": job["job_id"],
                "candidate_id": job["entity_id"],
                "conformation": conformation,
                "seed": int(job["seed"]),
                "status_sha256": status_sha,
                "job_result_sha256": result_sha,
                "snapshot_job_state": "SCORING_INVALID",
                "partial_score": "",
                "scoring_error_type": type(error).__name__,
                "scoring_error_message": str(error),
                "claim_boundary": CLAIM_BOUNDARY,
            })
            continue
        score_valid_jobs += 1
        scores[job["entity_id"]][conformation].append((int(job["seed"]), value))
        provenance_rows.append({
            "schema_version": SCHEMA_VERSION,
            "job_id": job["job_id"],
            "candidate_id": job["entity_id"],
            "conformation": conformation,
            "seed": int(job["seed"]),
            "status_sha256": status_sha,
            "job_result_sha256": result_sha,
            "snapshot_job_state": "SCORE_VALID",
            "partial_score": f"{value:.12g}",
            "scoring_error_type": "",
            "scoring_error_message": "",
            "claim_boundary": CLAIM_BOUNDARY,
        })

    snapshot_rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        by_conf = scores[candidate_id]
        counts = {conformation: len(by_conf[conformation]) for conformation in CONFORMATIONS}
        analyzable = all(counts[conformation] >= 1 for conformation in CONFORMATIONS)
        medians = {
            conformation: statistics.median(value for _seed, value in by_conf[conformation])
            for conformation in CONFORMATIONS if counts[conformation]
        }
        target = min(medians.values()) if analyzable else None
        missing = [conformation.upper() for conformation in CONFORMATIONS if counts[conformation] == 0]
        snapshot_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": candidate["target_patch_id"],
            "design_mode": candidate["design_mode"],
            "preview_state": "PARTIAL_ANALYZABLE" if analyzable else "PARTIAL_INCOMPLETE",
            "successful_seed_count_8X6B": counts["8x6b"],
            "successful_seed_count_9E6Y": counts["9e6y"],
            "median_score_8X6B": f"{medians['8x6b']:.12g}" if "8x6b" in medians else "",
            "median_score_9E6Y": f"{medians['9e6y']:.12g}" if "9e6y" in medians else "",
            "R_dual_min": f"{target:.12g}" if target is not None else "",
            "partial_incomplete_reason": "MISSING_VALID_SCORE_" + "+".join(missing) if missing else "",
            "claim_boundary": CLAIM_BOUNDARY,
        })
    output_dir.mkdir(parents=True)
    provenance_path = output_dir / "successful_jobs_snapshot_v1_1.tsv"
    teacher_path = output_dir / "partial_candidate_teacher_snapshot_v1_1.tsv"
    write_tsv(provenance_path, sorted(provenance_rows, key=lambda row: row["job_id"]))
    write_tsv(teacher_path, snapshot_rows)
    state_counts = Counter(row["preview_state"] for row in snapshot_rows)
    captured_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "campaign_terminal": False,
        "captured_at_utc": captured_at,
        "candidate_rows": len(snapshot_rows),
        "successful_jobs_captured": len(provenance_rows),
        "score_valid_jobs": score_valid_jobs,
        "score_invalid_jobs": score_invalid_jobs,
        "preview_state_counts": dict(sorted(state_counts.items())),
        "source_hashes": {
            "candidates": sha256_file(candidates_path),
            "docking_jobs": sha256_file(jobs_path),
            "adaptive_script": sha256_file(adaptive_script),
            "scorer": sha256_file(scorer_path),
        },
        "outputs": {
            "successful_jobs": {"path": provenance_path.name, "sha256": sha256_file(provenance_path)},
            "partial_teacher": {"path": teacher_path.name, "sha256": sha256_file(teacher_path)},
        },
        "new_completions_after_snapshot_included": False,
        "model_or_threshold_changes_permitted_from_preview": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = output_dir / "partial_success_snapshot_v1_1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "successful_jobs_captured": len(provenance_rows),
        "score_valid_jobs": score_valid_jobs,
        "score_invalid_jobs": score_invalid_jobs,
        "preview_state_counts": dict(sorted(state_counts.items())),
        "partial_teacher_sha256": sha256_file(teacher_path),
        "receipt_sha256": sha256_file(receipt_path),
        "campaign_terminal": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--adaptive-script", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_snapshot(args.root, args.adaptive_script, args.scorer, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
