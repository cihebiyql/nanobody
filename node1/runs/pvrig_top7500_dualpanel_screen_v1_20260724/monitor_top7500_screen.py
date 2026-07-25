#!/usr/bin/env python3
"""Write an atomic live receipt for the Top7500 dual-panel processing run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_count(path: Path) -> int | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def matching_processes(pattern: str) -> list[dict[str, Any]]:
    process = subprocess.run(
        ["pgrep", "-af", pattern],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    rows = []
    for line in process.stdout.splitlines():
        pid_text, _, command = line.partition(" ")
        if pid_text.isdigit():
            rows.append({"pid": int(pid_text), "command": command})
    return rows


def manifest_index(paths: list[Path]) -> dict[str, int]:
    output: dict[str, int] = {}
    offset = 0
    for path in paths:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        for index, row in enumerate(rows, start=1 + offset):
            output[row["job_id"]] = index
        offset += len(rows)
    return output


def current_archive_progress(
    processes: list[dict[str, Any]],
    job_index: dict[str, int],
    expected_jobs: int,
) -> dict[str, Any]:
    active_indices: list[int] = []
    active_jobs: list[str] = []
    for process in processes:
        fd_root = Path(f"/proc/{process['pid']}/fd")
        if not fd_root.is_dir():
            continue
        for fd_path in fd_root.iterdir():
            try:
                target = os.readlink(fd_path)
            except OSError:
                continue
            if not target.endswith((".tar.gz", ".tgz", ".tar")):
                continue
            filename = Path(target).name
            for suffix in (".tar.gz", ".tgz", ".tar"):
                if filename.endswith(suffix):
                    job_id = filename[: -len(suffix)]
                    break
            else:
                continue
            index = job_index.get(job_id)
            if index is not None:
                active_jobs.append(job_id)
                active_indices.append(index)
    dispatched_through = max(active_indices, default=0)
    return {
        "active_archive_jobs": sorted(set(active_jobs)),
        "active_manifest_indices": sorted(set(active_indices)),
        "approximately_dispatched_jobs": dispatched_through,
        "approximate_progress_fraction": round(
            dispatched_through / expected_jobs, 6
        )
        if expected_jobs
        else None,
        "progress_semantics": (
            "Maximum manifest index among currently open archives; approximate "
            "dispatch progress, not a committed-output count."
        ),
    }


def disk_receipt(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gib": round(usage.free / (1024**3), 3),
    }


def tnp_progress(root: Path, expected: int) -> dict[str, Any]:
    output_root = root / "run/full_qc/qc_out/vhh_screen/layer3_tnp"
    valid = 0
    incomplete = 0
    completed_times: list[float] = []
    stage_marker = (
        root
        / "run/full_qc/qc_out/vhh_screen/top2000.sapiens.csv"
    )
    stage_started_at = stage_marker.stat().st_mtime if stage_marker.is_file() else None
    if output_root.is_dir():
        for candidate_dir in output_root.iterdir():
            if not candidate_dir.is_dir():
                continue
            result = (
                candidate_dir
                / f"TNP_Results_SingleSeqEntry_{candidate_dir.name}.json"
            )
            try:
                payload = json.loads(result.read_text(encoding="utf-8"))
                if not payload:
                    raise ValueError("empty TNP JSON")
            except (OSError, json.JSONDecodeError, ValueError):
                incomplete += 1
                continue
            valid += 1
            completed_times.append(result.stat().st_mtime)
    rate_per_minute = None
    eta_minutes = None
    new_results = (
        sum(timestamp >= stage_started_at for timestamp in completed_times)
        if stage_started_at is not None
        else 0
    )
    if stage_started_at is not None and new_results >= 2:
        elapsed = max(1.0, time.time() - stage_started_at)
        rate_per_minute = new_results / elapsed * 60.0
        if rate_per_minute > 0:
            eta_minutes = max(0.0, expected - valid) / rate_per_minute
    return {
        "expected_candidates": expected,
        "valid_results": valid,
        "cached_results_before_current_stage": valid - new_results,
        "new_results_current_stage": new_results,
        "incomplete_directories": incomplete,
        "fraction_complete": round(valid / expected, 6) if expected else None,
        "rate_candidates_per_minute": (
            round(rate_per_minute, 3) if rate_per_minute is not None else None
        ),
        "eta_minutes": round(eta_minutes, 2) if eta_minutes is not None else None,
        "active_tnp_processes": matching_processes(
            "/vhh-eval/bin/TNP .*pvrig_top7500_dualpanel_screen"
        ),
    }


def md_progress(root: Path) -> dict[str, Any]:
    md_root = root / "run/md"
    topology_root = md_root / "topology"
    production_root = md_root / "production"
    return {
        "topology_expected_systems": 20,
        "topology_complete_systems": len(
            list(topology_root.glob("*/COMPLETE.json"))
        ),
        "topology_failed_systems": len(
            list(topology_root.glob("*/FAILED.json"))
        ),
        "production_expected_trajectories": 60,
        "production_complete_trajectories": len(
            list(production_root.glob("*/seed_*/COMPLETE.json"))
        ),
        "production_failed_trajectories": len(
            list(production_root.glob("*/seed_*/FAILED.json"))
        ),
    }


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "NOT_STARTED", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "state": "INVALID_JSON",
            "path": str(path),
            "error": f"{type(exc).__name__}:{exc}",
        }
    payload["path"] = str(path)
    return payload


def maybe_write_history(
    root: Path,
    payload: dict[str, Any],
    history_interval: int,
) -> None:
    history_dir = root / "monitor_30min/history"
    history_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(history_dir.glob("*.json"))
    now = time.time()
    if existing and now - existing[-1].stat().st_mtime < history_interval:
        return
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S%z")
    snapshot = history_dir / f"STATUS_{timestamp}.json"
    write_atomic(snapshot, payload)
    history_tsv = root / "monitor_30min/MONITOR_HISTORY.tsv"
    header = (
        "timestamp\tstate\tfast_complete\tc2_dispatched\tc2_fraction\t"
        "old_dispatched\told_fraction\ttop200_exists\ttop80_exists\t"
        "final50_exists\n"
    )
    if not history_tsv.is_file():
        history_tsv.write_text(header, encoding="utf-8")
    c2 = payload["c2_docking_aggregate"]
    old = payload["old_priority_postscore"]
    pipeline = payload["pipeline_outputs"]
    with history_tsv.open("a", encoding="utf-8") as handle:
        handle.write(
            "\t".join(
                [
                    payload["updated_at"],
                    payload["state"],
                    str(payload["fast_screen"]["complete_chunks"]),
                    str(c2.get("approximately_dispatched_jobs", "")),
                    str(c2.get("approximate_progress_fraction", "")),
                    str(old.get("approximately_dispatched_jobs", "")),
                    str(old.get("approximate_progress_fraction", "")),
                    str(pipeline["top200"]["exists"]).lower(),
                    str(pipeline["top80"]["exists"]).lower(),
                    str(pipeline["final50"]["exists"]).lower(),
                ]
            )
            + "\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--history-interval", type=int, default=1800)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    fast_root = root / "run/union13720_cascade"
    fast_merged = fast_root / "fast_merged.tsv"
    c2_jobs = root / "run/docking_aggregate/C2_JOB_RESULTS_41760.tsv"
    old_jobs = root / "run/docking_aggregate/OLD_PRIORITY_JOB_RESULTS_25000.tsv"
    candidate_master = root / "run/candidate_aggregate/candidate_evidence_table.tsv"
    full_qc = root / "run/full_qc/FULL_QC_RESULTS.tsv"
    top200 = root / "run/top200/top200_pre_static.tsv"
    static_manifest = root / "run/static_review/STATIC_JOB_MANIFEST.tsv"
    static_live = root / "run/static_review/STATIC_LIVE_STATUS.json"
    static_metrics = root / "run/static_review/STATIC_POSE_METRICS.tsv"
    static_receipt = root / "run/static_review/STATIC_COMPLETE.json"
    top80 = root / "run/top80/top80_post_static.tsv"
    md_manifest = root / "run/md/md_manifest.tsv"
    md_production_status = root / "run/md/MD_PRODUCTION_STATUS.json"
    md_summary = root / "run/md/reports/md_candidate_summary.tsv"
    final50 = root / "run/final50/final50_ranked.tsv"
    final_receipt = root / "run/final50/FINAL50_COMPLETE.json"
    status_path = root / "STATUS.json"
    old_index = manifest_index(
        [
            Path(
                "/data1/qlyu/projects/"
                "pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722/"
                "manifests/docking_jobs.tsv"
            )
        ]
    )
    c2_index = manifest_index(
        [
            root / "inputs/C2_NEW6220_2SEED_DOCKING_JOBS.tsv",
            Path(
                "/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723/"
                "c2_new4220_dualreceptor_seed42_3047_handoff_v1/"
                "manifests/docking_jobs.tsv"
            ),
        ]
    )

    while True:
        fast_complete_chunks = len(list(fast_root.glob("fast_chunks/*/complete.json")))
        fast_failed_chunks = len(list(fast_root.glob("fast_chunks/*/failed.json")))
        prerequisite_complete = all(
            path.is_file() and path.stat().st_size > 0
            for path in (fast_merged, c2_jobs, old_jobs)
        )
        files: dict[str, Any] = {}
        for label, path in {
            "fast_merged": fast_merged,
            "c2_job_results": c2_jobs,
            "old_priority_job_results": old_jobs,
        }.items():
            files[label] = {
                "path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "lines": line_count(path),
                "sha256": sha256_file(path) if path.is_file() and path.stat().st_size else "",
            }
        c2_processes = matching_processes(
            "stream_compact_docking_results.py.*C2_JOB_RESULTS"
        )
        old_processes = matching_processes(
            "score_legacy_compact_docking.py.*OLD_PRIORITY_JOB_RESULTS"
        )
        c2_progress = current_archive_progress(c2_processes, c2_index, 41760)
        old_progress = current_archive_progress(old_processes, old_index, 25000)
        if files["c2_job_results"]["lines"] == 41761:
            c2_progress.update(
                {
                    "approximately_dispatched_jobs": 41760,
                    "approximate_progress_fraction": 1.0,
                    "progress_semantics": (
                        "Committed full output table exists with 41,760 data rows."
                    ),
                }
            )
        if files["old_priority_job_results"]["lines"] == 25001:
            old_progress.update(
                {
                    "approximately_dispatched_jobs": 25000,
                    "approximate_progress_fraction": 1.0,
                    "progress_semantics": (
                        "Committed full output table exists with 25,000 data rows."
                    ),
                }
            )
        pipeline_outputs = {}
        for label, path in {
            "candidate_master": candidate_master,
            "full_qc": full_qc,
            "top200": top200,
            "static_manifest": static_manifest,
            "static_metrics": static_metrics,
            "static_receipt": static_receipt,
            "top80": top80,
            "md_manifest": md_manifest,
            "md_production_status": md_production_status,
            "md_summary": md_summary,
            "final50": final50,
            "final_receipt": final_receipt,
        }.items():
            pipeline_outputs[label] = {
                "path": str(path),
                "exists": path.is_file() and path.stat().st_size > 0,
                "bytes": path.stat().st_size if path.is_file() else 0,
                "lines": line_count(path),
            }
        controllers = {
            "docking_to_top200": read_json(root / "run/controller/STATUS.json"),
            "top200_to_top80": read_json(
                root / "run/static_controller/STATUS.json"
            ),
            "top80_to_final50": read_json(
                root / "run/final_controller/STATUS.json"
            ),
        }
        full_qc_tnp = tnp_progress(root, 2000)
        static_panel_progress = read_json(static_live)
        md_run_progress = md_progress(root)
        final_controller_state = controllers["top80_to_final50"].get("state", "")
        screen_summary = (
            root / "run/full_qc/qc_out/vhh_screen/screen_summary.tsv"
        )
        active_tnp_count = len(full_qc_tnp["active_tnp_processes"])
        if pipeline_outputs["final_receipt"]["exists"]:
            state = "FINAL50_COMPLETE"
        elif pipeline_outputs["final50"]["exists"]:
            state = "FINAL50_PREAUDIT"
        elif pipeline_outputs["md_summary"]["exists"]:
            state = "MD20_ANALYSIS_COMPLETE"
        elif final_controller_state in {
            "PREPARING_MD20",
            "RUNNING_MD20_TOPOLOGY",
            "WAITING_FOR_GPU_CAPACITY",
            "RUNNING_MD20_PRODUCTION",
            "ANALYZING_MD20",
            "SELECTING_FINAL50",
            "RUNNING_FINAL50_QC",
            "AUDITING_FINAL50",
        }:
            state = final_controller_state
        elif pipeline_outputs["md_production_status"]["exists"]:
            md_state = controllers["top80_to_final50"].get("state", "")
            state = md_state or "MD20_RUNNING"
        elif pipeline_outputs["md_manifest"]["exists"]:
            state = "MD20_PREPARED"
        elif pipeline_outputs["top80"]["exists"]:
            state = "TOP80_COMPLETE"
        elif pipeline_outputs["static_receipt"]["exists"]:
            state = "STATIC_REVIEW_COMPLETE"
        elif controllers["top200_to_top80"].get("state") == "RUNNING_STATIC_PANEL":
            state = "STATIC_REVIEW_RUNNING"
        elif pipeline_outputs["top200"]["exists"]:
            state = "TOP200_COMPLETE"
        elif pipeline_outputs["full_qc"]["exists"]:
            state = "FULL_QC_COMPLETE"
        elif screen_summary.is_file() and active_tnp_count == 0:
            state = "FULL_QC_POSTPROCESS_RUNNING"
        elif active_tnp_count > 0:
            state = "FULL_QC_TNP_RUNNING"
        elif controllers["docking_to_top200"].get("state") == "RUNNING_FULL_QC_2000":
            state = "FULL_QC_PREPROCESS_RUNNING"
        elif pipeline_outputs["candidate_master"]["exists"]:
            state = "CANDIDATE_EVIDENCE_COMPLETE"
        elif prerequisite_complete:
            state = "DOCKING_PREREQUISITES_COMPLETE"
        else:
            state = "RUNNING"
        payload = {
            "schema_version": "pvrig.top7500_dualpanel_live_status.v1",
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "state": state,
            "scope": {
                "old_priority_candidates": 7500,
                "c2_refined_candidates": 7500,
                "overlap_candidates": 1280,
                "union_candidates": 13720,
                "top5000_included": False,
                "new_docking_launched": False,
            },
            "fast_screen": {
                "expected_chunks": 28,
                "complete_chunks": fast_complete_chunks,
                "failed_chunks": fast_failed_chunks,
                "processes": matching_processes("union13720_cascade"),
            },
            "c2_docking_aggregate": {
                "expected_jobs": 41760,
                "expected_success": 41735,
                "expected_technical_na": 25,
                "processes": c2_processes,
                **c2_progress,
            },
            "old_priority_postscore": {
                "expected_jobs": 25000,
                "expected_source_success": 24985,
                "expected_technical_na": 15,
                "operation": "geometry_postscore_of_frozen_selected_models_not_redocking",
                "processes": old_processes,
                **old_progress,
            },
            "files": files,
            "pipeline_outputs": pipeline_outputs,
            "full_qc_tnp": full_qc_tnp,
            "static_panel_progress": static_panel_progress,
            "md_run_progress": md_run_progress,
            "controllers": controllers,
            "disks": {
                "data": disk_receipt(Path("/data")),
                "data1": disk_receipt(Path("/data1")),
            },
            "claim_boundary": (
                "Docking output is computational geometry evidence. Binding, Kd, "
                "IC50 and experimental blocking remain separate evidence lanes."
            ),
        }
        write_atomic(status_path, payload)
        maybe_write_history(root, payload, max(60, args.history_interval))
        if args.once or pipeline_outputs["final_receipt"]["exists"]:
            return 0
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
