#!/usr/bin/env python3
"""Read-only sidecar monitor for a local or synchronized V4-D project root.

The monitor never invokes the campaign's status or aggregation scripts and
never writes below the monitored project root.  Process IDs are deliberately
not probed because a synchronized root may belong to another host.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "phase2_v4_d_readonly_monitor_v1"
ACTIVE_STATUSES = {"QUEUED", "RUNNING"}
TERMINAL_STATUSES = {"SUCCESS", "FAILED_MAX_ATTEMPTS"}
REQUIRED_JOB_FIELDS = {"job_id", "entity_id", "entity_type", "conformation", "seed"}


class MonitorError(RuntimeError):
    """Raised when the immutable monitoring inputs are unusable."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def path_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def age_seconds(now: datetime, timestamp: datetime | None) -> float | None:
    if timestamp is None:
        return None
    return round(max(0.0, (now - timestamp).total_seconds()), 3)


def read_tsv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise MonitorError(f"cannot read TSV {path}: {exc}") from exc


def read_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"read_error:{exc}"
    except json.JSONDecodeError as exc:
        return None, f"json_error:{exc.msg}@{exc.lineno}:{exc.colno}"
    if not isinstance(payload, dict):
        return None, f"not_object:{type(payload).__name__}"
    return payload, None


def safe_job_id(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise MonitorError(f"unsafe job_id in manifest: {value!r}")
    return value


def normalized_counts(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    output: dict[str, int] = {}
    try:
        for key, count in value.items():
            number = int(count)
            if number:
                output[str(key)] = number
    except (TypeError, ValueError):
        return None
    return dict(sorted(output.items()))


def nested_status_counts(
    rows: Iterable[dict[str, str]],
    statuses: dict[str, str],
    key,
) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(key(row))][statuses[row["job_id"]]] += 1
    return {
        group: dict(sorted(counts.items()))
        for group, counts in sorted(grouped.items())
    }


def load_model_splits(root: Path) -> tuple[dict[str, str] | None, dict[str, Any]]:
    path = root / "inputs/fullqc290_split_manifest.tsv"
    metadata: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return None, metadata
    rows = read_tsv(path)
    if rows and not {"candidate_id", "model_split"}.issubset(rows[0]):
        raise MonitorError(f"split manifest lacks candidate_id/model_split: {path}")
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        if candidate_id in mapping:
            duplicates.append(candidate_id)
        mapping[candidate_id] = row.get("model_split", "") or "UNSPECIFIED"
    if duplicates:
        raise MonitorError(f"duplicate candidate IDs in split manifest: {sorted(set(duplicates))[:10]}")
    metadata.update(row_count=len(rows), model_split_counts=dict(sorted(Counter(mapping.values()).items())))
    return mapping, metadata


def model_split_for(row: dict[str, str], mapping: dict[str, str] | None) -> str:
    if row["entity_type"] == "control":
        return "CONTROL"
    if mapping is None:
        return "SPLIT_MANIFEST_UNAVAILABLE"
    return mapping.get(row["entity_id"], "UNMAPPED_CANDIDATE")


def coverage_summary(
    rows: list[dict[str, str]],
    successful_seeds: dict[tuple[str, str], set[str]],
    threshold: int,
    grouping,
) -> dict[str, dict[str, int | float]]:
    pairs_by_group: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        pairs_by_group[str(grouping(row))].add((row["entity_id"], row["conformation"]))
    output: dict[str, dict[str, int | float]] = {}
    for group, pairs in sorted(pairs_by_group.items()):
        passed = sum(len(successful_seeds.get(pair, set())) >= threshold for pair in pairs)
        output[group] = {
            "at_least_threshold": passed,
            "expected": len(pairs),
            "fraction": round(passed / len(pairs), 6) if pairs else 0.0,
        }
    return output


def validate_result(
    result: dict[str, Any], row: dict[str, str]
) -> list[str]:
    reasons: list[str] = []
    expected = {
        "job_id": row["job_id"],
        "entity_id": row["entity_id"],
        "entity_type": row["entity_type"],
        "dock_conformation": row["conformation"],
    }
    for field, value in expected.items():
        if str(result.get(field, "")) != value:
            reasons.append(f"{field}_mismatch")
    try:
        if int(result.get("seed")) != int(row["seed"]):
            reasons.append("seed_mismatch")
    except (TypeError, ValueError):
        reasons.append("seed_invalid")
    if result.get("state") != "SUCCESS":
        reasons.append("state_not_success")
    try:
        if int(result.get("selected_model_count", 0)) <= 0:
            reasons.append("selected_model_count_not_positive")
    except (TypeError, ValueError):
        reasons.append("selected_model_count_invalid")
    return sorted(set(reasons))


def summarize(
    project_root: Path,
    *,
    now: datetime | None = None,
    stale_seconds: float = 3600.0,
    controller_stale_seconds: float = 180.0,
    throughput_window_seconds: float = 3600.0,
    successful_seed_threshold: int = 2,
) -> dict[str, Any]:
    if stale_seconds <= 0 or controller_stale_seconds <= 0 or throughput_window_seconds <= 0:
        raise MonitorError("time thresholds must be positive")
    if successful_seed_threshold < 1:
        raise MonitorError("successful seed threshold must be positive")
    root = project_root.expanduser().resolve()
    current = (now or utc_now()).astimezone(timezone.utc)
    manifest_path = root / "manifests/docking_jobs.tsv"
    if not manifest_path.is_file():
        raise MonitorError(f"job manifest missing: {manifest_path}")
    rows = read_tsv(manifest_path)
    if rows and not REQUIRED_JOB_FIELDS.issubset(rows[0]):
        missing = sorted(REQUIRED_JOB_FIELDS - set(rows[0]))
        raise MonitorError(f"job manifest missing required fields: {missing}")
    job_ids = [safe_job_id(row.get("job_id", "")) for row in rows]
    if len(job_ids) != len(set(job_ids)):
        duplicates = sorted(job_id for job_id, count in Counter(job_ids).items() if count > 1)
        raise MonitorError(f"duplicate job IDs in manifest: {duplicates[:10]}")
    row_by_id = {row["job_id"]: row for row in rows}
    model_splits, split_metadata = load_model_splits(root)

    input_mtimes: list[datetime] = [mtime for mtime in (path_mtime(manifest_path),) if mtime]
    statuses: dict[str, str] = {}
    states: dict[str, dict[str, Any]] = {}
    state_errors: dict[str, str] = {}
    attempts_by_job: dict[str, int] = {}
    stale_active: list[dict[str, Any]] = []
    active_without_timestamp: list[str] = []

    state_dir = root / "status/jobs"
    discovered_state_files = sorted(state_dir.glob("*.json")) if state_dir.is_dir() else []
    discovered_state_ids = {path.stem for path in discovered_state_files}
    orphan_state_files = sorted(discovered_state_ids - set(job_ids))
    for row in rows:
        job_id = row["job_id"]
        state_path = state_dir / f"{job_id}.json"
        state: dict[str, Any] = {}
        if state_path.is_file():
            state_mtime = path_mtime(state_path)
            if state_mtime:
                input_mtimes.append(state_mtime)
            loaded, error = read_json_object(state_path)
            if error:
                state_errors[job_id] = error
                statuses[job_id] = "MALFORMED_STATE"
            else:
                state = loaded or {}
                statuses[job_id] = str(state.get("status") or "PENDING")
        else:
            statuses[job_id] = "PENDING"
        states[job_id] = state
        try:
            attempts = int(state.get("attempts", 0) or 0)
            if attempts < 0:
                raise ValueError
        except (TypeError, ValueError):
            attempts = 0
            state_errors[job_id] = "invalid_attempts"
        attempts_by_job[job_id] = attempts
        if statuses[job_id] in ACTIVE_STATUSES:
            activity_timestamp = (
                parse_timestamp(state.get("updated_at"))
                or parse_timestamp(state.get("started_at"))
                or path_mtime(state_path)
            )
            activity_age = age_seconds(current, activity_timestamp)
            if activity_age is None:
                active_without_timestamp.append(job_id)
            elif activity_age > stale_seconds:
                stale_active.append(
                    {
                        "job_id": job_id,
                        "status": statuses[job_id],
                        "stage": str(state.get("stage") or ""),
                        "age_seconds": activity_age,
                        "last_activity_at": isoformat(activity_timestamp),
                    }
                )

    status_counts = dict(sorted(Counter(statuses.values()).items()))
    split_key = lambda row: model_split_for(row, model_splits)
    by_entity_type = nested_status_counts(rows, statuses, lambda row: row["entity_type"])
    by_conformation = nested_status_counts(rows, statuses, lambda row: row["conformation"])
    by_model_split = (
        nested_status_counts(rows, statuses, split_key) if model_splits is not None else None
    )

    result_root = root / "results"
    result_files = sorted(result_root.glob("*/job_result.json")) if result_root.is_dir() else []
    results: dict[str, dict[str, Any]] = {}
    result_errors: dict[str, str] = {}
    orphan_result_files: list[str] = []
    for path in result_files:
        job_id = path.parent.name
        result_mtime = path_mtime(path)
        if result_mtime:
            input_mtimes.append(result_mtime)
        if job_id not in row_by_id:
            orphan_result_files.append(str(path))
            continue
        loaded, error = read_json_object(path)
        if error:
            result_errors[job_id] = error
        else:
            results[job_id] = loaded or {}

    valid_results: set[str] = set()
    result_validation_errors: dict[str, list[str]] = {}
    for job_id, result in sorted(results.items()):
        reasons = validate_result(result, row_by_id[job_id])
        if reasons:
            result_validation_errors[job_id] = reasons
        else:
            valid_results.add(job_id)
    success_jobs = {job_id for job_id, status in statuses.items() if status == "SUCCESS"}
    missing_results_for_success = sorted(success_jobs - set(results))
    success_without_valid_result = sorted(success_jobs - valid_results)
    valid_result_without_success_state = sorted(valid_results - success_jobs)

    successful_seeds: dict[tuple[str, str], set[str]] = defaultdict(set)
    completion_timestamps: list[datetime] = []
    for row in rows:
        job_id = row["job_id"]
        if statuses[job_id] == "SUCCESS":
            successful_seeds[(row["entity_id"], row["conformation"])].add(row["seed"])
            completed = parse_timestamp(states[job_id].get("completed_at"))
            if completed is None and job_id in results:
                completed = parse_timestamp(results[job_id].get("completed_at"))
            if completed is not None:
                completion_timestamps.append(completed)
    expected_pairs = {(row["entity_id"], row["conformation"]) for row in rows}
    pairs_passing = sorted(
        pair for pair in expected_pairs
        if len(successful_seeds.get(pair, set())) >= successful_seed_threshold
    )
    seed_coverage: dict[str, Any] = {
        "successful_seed_threshold": successful_seed_threshold,
        "entity_conformations_at_least_threshold": len(pairs_passing),
        "expected_entity_conformations": len(expected_pairs),
        "fraction": round(len(pairs_passing) / len(expected_pairs), 6) if expected_pairs else 0.0,
        "by_entity_type": coverage_summary(
            rows, successful_seeds, successful_seed_threshold, lambda row: row["entity_type"]
        ),
        "by_conformation": coverage_summary(
            rows, successful_seeds, successful_seed_threshold, lambda row: row["conformation"]
        ),
        "by_model_split": (
            coverage_summary(rows, successful_seeds, successful_seed_threshold, split_key)
            if model_splits is not None else None
        ),
    }

    attempt_histogram = Counter(attempts_by_job.values())
    attempts = {
        "total_attempts": sum(attempts_by_job.values()),
        "jobs_with_attempts": sum(value > 0 for value in attempts_by_job.values()),
        "retried_jobs": sum(value > 1 for value in attempts_by_job.values()),
        "max_attempts_observed": max(attempts_by_job.values(), default=0),
        "histogram": {str(key): value for key, value in sorted(attempt_histogram.items())},
        "retried_job_ids": sorted(job_id for job_id, value in attempts_by_job.items() if value > 1),
    }

    window_start = current - timedelta(seconds=throughput_window_seconds)
    completions_in_window = [
        value for value in completion_timestamps if window_start <= value <= current
    ]
    jobs_per_hour = len(completions_in_window) * 3600.0 / throughput_window_seconds
    terminal_count = sum(status in TERMINAL_STATUSES for status in statuses.values())
    remaining = len(rows) - terminal_count
    eta_seconds = remaining * 3600.0 / jobs_per_hour if jobs_per_hour > 0 else None
    eta_at = current + timedelta(seconds=eta_seconds) if eta_seconds is not None else None
    throughput = {
        "method": "successful_state_completion_timestamps_in_fixed_rolling_window",
        "window_seconds": throughput_window_seconds,
        "window_start": isoformat(window_start),
        "completion_timestamp_count": len(completion_timestamps),
        "completed_in_window": len(completions_in_window),
        "jobs_per_hour": round(jobs_per_hour, 6),
        "terminal_jobs": terminal_count,
        "remaining_nonterminal_jobs": remaining,
        "eta_seconds": round(eta_seconds, 3) if eta_seconds is not None else None,
        "eta_at": isoformat(eta_at),
        "earliest_completion_at": isoformat(min(completion_timestamps, default=None)),
        "latest_completion_at": isoformat(max(completion_timestamps, default=None)),
    }

    controller_path = root / "status/controller.json"
    controller_payload: dict[str, Any] | None = None
    controller_error: str | None = None
    controller_mtime = path_mtime(controller_path)
    if controller_path.is_file():
        controller_payload, controller_error = read_json_object(controller_path)
        if controller_mtime:
            input_mtimes.append(controller_mtime)
    controller_age = age_seconds(current, controller_mtime)
    controller_reasons: list[str] = []
    if not controller_path.is_file():
        controller_health_status = "MISSING"
        controller_reasons.append("controller_file_missing")
    elif controller_error:
        controller_health_status = "MALFORMED"
        controller_reasons.append(controller_error)
    else:
        payload_status = str((controller_payload or {}).get("status") or "UNKNOWN")
        if payload_status in {"COMPLETE", "COMPLETE_WITH_FAILURES"}:
            if remaining == 0:
                controller_health_status = "HEALTHY_COMPLETE"
            else:
                controller_health_status = "INCONSISTENT"
                controller_reasons.append("controller_complete_but_nonterminal_jobs_remain")
        elif payload_status in {"RUNNING", "STARTING", "LAUNCHED"}:
            if controller_age is None or controller_age > controller_stale_seconds:
                controller_health_status = "STALE"
                controller_reasons.append("controller_heartbeat_mtime_stale")
            elif stale_active or active_without_timestamp:
                controller_health_status = "DEGRADED_STALE_ACTIVE"
                controller_reasons.append("stale_or_untimestamped_active_job_states")
            else:
                controller_health_status = "HEALTHY_RUNNING"
        else:
            controller_health_status = "UNKNOWN_STATUS"
            controller_reasons.append(f"unrecognized_controller_status:{payload_status}")
    controller_health = {
        "health": controller_health_status,
        "reasons": controller_reasons,
        "path": str(controller_path),
        "exists": controller_path.is_file(),
        "file_mtime": isoformat(controller_mtime),
        "age_seconds": controller_age,
        "stale_after_seconds": controller_stale_seconds,
        "payload_status": (controller_payload or {}).get("status"),
        "controller_pid": (controller_payload or {}).get("controller_pid"),
        "selected_job_count": (controller_payload or {}).get("selected_job_count"),
        "max_parallel": (controller_payload or {}).get("max_parallel"),
        "parallel_limit": (controller_payload or {}).get("parallel_limit"),
        "active_state_count": sum(status in ACTIVE_STATUSES for status in statuses.values()),
        "pid_liveness": "NOT_CHECKED_CROSS_HOST_SAFE",
    }

    summary_path = root / "status/summary.json"
    summary_payload: dict[str, Any] | None = None
    summary_error: str | None = None
    summary_mtime = path_mtime(summary_path)
    if summary_path.is_file():
        summary_payload, summary_error = read_json_object(summary_path)
    newest_source_mtime = max(input_mtimes, default=None)
    summary_reasons: list[str] = []
    summary_total_match: bool | None = None
    summary_counts_match: bool | None = None
    if not summary_path.is_file():
        summary_reasons.append("summary_missing")
    elif summary_error:
        summary_reasons.append(summary_error)
    else:
        try:
            summary_total_match = int((summary_payload or {}).get("total_jobs")) == len(rows)
        except (TypeError, ValueError):
            summary_total_match = False
        summary_counts_match = normalized_counts((summary_payload or {}).get("counts")) == normalized_counts(status_counts)
        if not summary_total_match:
            summary_reasons.append("total_jobs_mismatch")
        if not summary_counts_match:
            summary_reasons.append("status_counts_mismatch")
        if summary_mtime and newest_source_mtime and summary_mtime + timedelta(seconds=1) < newest_source_mtime:
            summary_reasons.append("summary_older_than_monitor_inputs")
    lag_seconds = None
    if summary_mtime and newest_source_mtime:
        lag_seconds = round(max(0.0, (newest_source_mtime - summary_mtime).total_seconds()), 3)
    summary_staleness = {
        "stale": bool(summary_reasons),
        "reasons": summary_reasons,
        "path": str(summary_path),
        "exists": summary_path.is_file(),
        "file_mtime": isoformat(summary_mtime),
        "age_seconds": age_seconds(current, summary_mtime),
        "newest_monitored_input_mtime": isoformat(newest_source_mtime),
        "lag_seconds": lag_seconds,
        "total_jobs_match": summary_total_match,
        "status_counts_match": summary_counts_match,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": isoformat(current),
        "project_root": str(root),
        "read_only_contract": {
            "monitored_root_writes": 0,
            "campaign_scripts_invoked": 0,
            "pid_liveness_checked": False,
            "note": "snapshot is non-atomic while a live campaign updates atomic state/result files",
        },
        "thresholds": {
            "stale_active_seconds": stale_seconds,
            "controller_stale_seconds": controller_stale_seconds,
            "throughput_window_seconds": throughput_window_seconds,
            "successful_seed_threshold": successful_seed_threshold,
        },
        "manifest": {
            "path": str(manifest_path),
            "total_jobs": len(rows),
            "unique_job_ids": len(set(job_ids)),
            "unique_entities": len({row["entity_id"] for row in rows}),
            "unique_entity_conformations": len(expected_pairs),
        },
        "split_manifest": split_metadata,
        "total_jobs": len(rows),
        "status_counts": status_counts,
        "by_entity_type": by_entity_type,
        "by_conformation": by_conformation,
        "by_model_split": by_model_split,
        "seed_coverage": seed_coverage,
        "stale": {
            "method": "state updated_at, then started_at, then state file mtime",
            "stale_after_seconds": stale_seconds,
            "active_count": sum(status in ACTIVE_STATUSES for status in statuses.values()),
            "stale_active_count": len(stale_active),
            "stale_active_jobs": stale_active,
            "active_without_timestamp_count": len(active_without_timestamp),
            "active_without_timestamp_jobs": sorted(active_without_timestamp),
        },
        "attempts": attempts,
        "throughput": throughput,
        "summary_staleness": summary_staleness,
        "controller_health": controller_health,
        "result_evidence": {
            "result_files_found": len(result_files),
            "parsed_manifest_results": len(results),
            "valid_success_results": len(valid_results),
            "malformed_results": dict(sorted(result_errors.items())),
            "validation_errors": dict(sorted(result_validation_errors.items())),
            "orphan_result_files": sorted(orphan_result_files),
            "missing_results_for_success_states": missing_results_for_success,
            "success_states_without_valid_result": success_without_valid_result,
            "valid_results_without_success_state": valid_result_without_success_state,
        },
        "state_evidence": {
            "state_files_found": len(discovered_state_files),
            "manifest_state_files_found": len(discovered_state_ids & set(job_ids)),
            "malformed_states": dict(sorted(state_errors.items())),
            "orphan_state_job_ids": orphan_state_files,
        },
    }


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def write_output(path: Path, payload: dict[str, Any], monitored_root: Path) -> None:
    destination = path.expanduser().resolve()
    root = monitored_root.expanduser().resolve()
    if destination == root or is_within(destination, root):
        raise MonitorError("--output must be outside the monitored project root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as handle:
        handle.write(serialized)
        temporary = Path(handle.name)
    os.replace(temporary, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path, help="Local, mounted, or synchronized V4-D project root")
    parser.add_argument("--output", type=Path, help="Optional JSON output outside the monitored root")
    parser.add_argument("--stale-seconds", type=float, default=3600.0)
    parser.add_argument("--controller-stale-seconds", type=float, default=180.0)
    parser.add_argument("--throughput-window-seconds", type=float, default=3600.0)
    parser.add_argument("--successful-seed-threshold", type=int, default=2)
    parser.add_argument("--now", help="UTC/ISO timestamp override for reproducible audits and tests")
    args = parser.parse_args(argv)
    try:
        now = parse_timestamp(args.now) if args.now else None
        if args.now and now is None:
            raise MonitorError(f"invalid --now timestamp: {args.now!r}")
        payload = summarize(
            args.project_root,
            now=now,
            stale_seconds=args.stale_seconds,
            controller_stale_seconds=args.controller_stale_seconds,
            throughput_window_seconds=args.throughput_window_seconds,
            successful_seed_threshold=args.successful_seed_threshold,
        )
        if args.output:
            write_output(args.output, payload, args.project_root)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (MonitorError, OSError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
