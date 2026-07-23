#!/usr/bin/env python3
"""Write an evidence-backed health snapshot for the live Top7500 Docking run."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


TARGET_JOBS = 25_000
EXPECTED_ARRAY_TASKS = 8
MAX_RELAY_LAG = 1_000
MAX_BXCPU_BYTES = 20 * 1024**3
MIN_NODE1_FREE_BYTES = 50 * 1024**3
NODE1_FINAL_RESERVE_BYTES = 50 * 1024**3
RAPID_FREE_SPACE_DROP_BYTES_PER_HOUR = 5 * 1024**3
RAPID_DROP_HORIZON_HOURS = 4
STALL_SECONDS = 20 * 60
SSH = "/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe"
ARRAY_JOB = "11942310"
AUDIT_JOB = "11942311"
REMOTE_NAME = "pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722_bxcpu_results"
NODE1_ROOT = pathlib.PurePosixPath(
    "/data1/qlyu/projects/"
    "pvrig_priority_top7500_dualreceptor_multiseed_docking_results_v1_20260722/"
    "top7500_25k"
)
LOCAL_ROOT = pathlib.Path(
    "/mnt/d/work/抗体/node1/"
    "pvrig_top7500_25k_bxcpu_incremental_spool_20260722/monitor"
)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run(command: list[str], *, timeout: int = 120) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}: {' '.join(command)}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def ssh(host: str, script: str) -> str:
    return run([SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, script])


def bxcpu_snapshot() -> dict[str, Any]:
    script = rf'''set -euo pipefail
R="$HOME/{REMOTE_NAME}"
python3 - "$R" <<'PY'
import collections, json, os, pathlib, sys
r=pathlib.Path(sys.argv[1]); counts=collections.Counter(); bad=0
def tree_bytes(root):
    total=0
    for directory, _, files in os.walk(str(root)):
        for name in files:
            try: total+=(pathlib.Path(directory)/name).stat().st_size
            except (FileNotFoundError, OSError): pass
    return total
for p in (r/"status/jobs").glob("*.json"):
    try: counts[json.load(open(p)).get("status", "UNKNOWN")]+=1
    except Exception: bad+=1
stderr_nonempty=[]; known_jobacct_timeout_lines=0; unexpected_stderr=[]
for p in sorted(r.glob("slurm-pvrig-top7500-25k-11942310_*.err")):
    try: lines=[line.strip() for line in p.read_text(errors="replace").splitlines() if line.strip()]
    except (FileNotFoundError, OSError): continue
    if not lines: continue
    stderr_nonempty.append({{"file":p.name, "bytes":p.stat().st_size, "lines":len(lines)}})
    for line in lines:
        if (
            "_handle_stat_jobacct" in line
            and "more than MessageTimeout" in line
            and "result won't be delivered" in line
        ):
            known_jobacct_timeout_lines+=1
        elif len(unexpected_stderr) < 20:
            unexpected_stderr.append({{"file":p.name, "line":line[:1000]}})
print(json.dumps({{
    "status_counts":dict(counts),
    "bad_status_json":bad,
    "archives_pending":len(list((r/"compressed_queue").glob("*.tar.gz"))),
    "root_bytes":tree_bytes(r),
    "stderr_summary":{{
        "nonempty_files":stderr_nonempty,
        "known_jobacct_timeout_lines":known_jobacct_timeout_lines,
        "unexpected_lines":unexpected_stderr,
    }},
}}))
PY
echo __QUEUE__
squeue -h -j {ARRAY_JOB},{AUDIT_JOB} -o "%i|%T|%M|%R"
'''
    output = ssh("bxcpu", script)
    payload_text, queue_text = output.split("__QUEUE__\n", 1)
    payload = json.loads(payload_text.strip().splitlines()[-1])
    queue = []
    for line in queue_text.splitlines():
        if not line.strip():
            continue
        job_id, state, elapsed, reason = line.split("|", 3)
        queue.append(
            {"job_id": job_id, "state": state, "elapsed": elapsed, "reason": reason}
        )
    payload["queue"] = queue
    payload["running_array_tasks"] = sum(
        row["state"] == "RUNNING" and row["job_id"].startswith(f"{ARRAY_JOB}_")
        for row in queue
    )
    return payload


def node1_snapshot() -> dict[str, Any]:
    script = rf'''set -euo pipefail
R={NODE1_ROOT}
python3 - "$R" <<'PY'
import collections, json, pathlib, sys
r=pathlib.Path(sys.argv[1]); counts=collections.Counter(); bad=0
for p in (r/"status/jobs").glob("*.json"):
    try: counts[json.load(open(p)).get("status", "UNKNOWN")]+=1
    except Exception: bad+=1
print(json.dumps({{
    "status_counts":dict(counts),
    "bad_status_json":bad,
    "job_results":len(list((r/"results").glob("*/job_result.json"))),
    "archives":len(list((r/"compressed_queue").glob("*.tar.gz"))),
    "failed_evidence":len(list((r/"failed_evidence").glob("*.tar.gz"))),
    "batch_receipts":len(list((r/"state/batches").glob("*"))),
}}))
PY
du -sb "$R" | awk '{{print $1}}'
df -B1 --output=avail /data1 | tail -1
'''
    lines = [line for line in ssh("node1", script).splitlines() if line.strip()]
    payload = json.loads(lines[-3])
    payload["result_root_bytes"] = int(lines[-2].strip())
    payload["free_bytes"] = int(lines[-1].strip())
    return payload


def relay_snapshot() -> dict[str, Any]:
    shards = []
    for index in range(4):
        session = f"pvrig-top7500-result-sync-{index:02d}"
        running = subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        path = LOCAL_ROOT.parent / f"shard{index:02d}/state/SYNC_STATUS.shard{index:02d}of04.json"
        payload: dict[str, Any] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text())
            except Exception as exc:
                payload = {"read_error": repr(exc)}
        shards.append(
            {
                "index": index,
                "session_running": running,
                "status_mtime_epoch": path.stat().st_mtime if path.exists() else None,
                "status": payload,
            }
        )
    return {"shards": shards, "all_sessions_running": all(x["session_running"] for x in shards)}


def previous_snapshot() -> dict[str, Any] | None:
    path = LOCAL_ROOT / "MONITOR_STATUS.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def main() -> int:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    checked = now()
    alerts: list[str] = []
    warnings: list[str] = []
    try:
        bx = bxcpu_snapshot()
    except Exception as exc:
        bx = {"error": repr(exc)}
        alerts.append("BXCPU_CHECK_FAILED")
    try:
        node1 = node1_snapshot()
    except Exception as exc:
        node1 = {"error": repr(exc)}
        alerts.append("NODE1_CHECK_FAILED")
    relay = relay_snapshot()
    if not relay["all_sessions_running"]:
        alerts.append("RELAY_SESSION_MISSING")

    counts = bx.get("status_counts", {})
    node1_current = "error" not in node1
    success = int(counts.get("SUCCESS", 0))
    failed = sum(int(value) for key, value in counts.items() if "FAIL" in key)
    node1_archives = int(node1.get("archives", 0))
    terminal = sum(int(value) for value in counts.values())
    if bx.get("bad_status_json"):
        alerts.append("BXCPU_BAD_STATUS_JSON")
    if node1_current and node1.get("bad_status_json"):
        alerts.append("NODE1_BAD_STATUS_JSON")
    failed_evidence = int(node1.get("failed_evidence", 0))
    local_failed_evidence_root = LOCAL_ROOT / "failed_evidence"
    local_failed_evidence = len(list(local_failed_evidence_root.glob("*.tar.gz")))
    pending_node1_delivery = len(
        list((local_failed_evidence_root / "pending_receipts").glob("*.json"))
    )
    if failed:
        warnings.append("TECHNICAL_FAILURES_PRESENT_AS_NA")
    if local_failed_evidence < failed:
        alerts.append("TECHNICAL_FAILURE_EVIDENCE_MISSING_LOCALLY")
    if node1_current and failed_evidence < failed:
        alerts.append("TECHNICAL_FAILURE_EVIDENCE_MISSING_ON_NODE1")
    if terminal < TARGET_JOBS and bx.get("running_array_tasks") != EXPECTED_ARRAY_TASKS:
        alerts.append("ARRAY_TASK_COUNT_NOT_8")
    if node1_current and success - node1_archives > MAX_RELAY_LAG:
        alerts.append("RELAY_LAG_OVER_1000")
    if int(bx.get("root_bytes", 0)) > MAX_BXCPU_BYTES:
        alerts.append("BXCPU_RESULT_ROOT_OVER_20GB")
    stderr_summary = bx.get("stderr_summary", {})
    if stderr_summary.get("known_jobacct_timeout_lines"):
        warnings.append("SLURM_JOBACCT_TIMEOUT_WARNINGS")
    if stderr_summary.get("unexpected_lines"):
        alerts.append("BXCPU_UNEXPECTED_SLURM_STDERR")
    if node1_current and int(node1.get("free_bytes", MIN_NODE1_FREE_BYTES)) < MIN_NODE1_FREE_BYTES:
        alerts.append("NODE1_FREE_SPACE_BELOW_50GB")

    previous = previous_snapshot()
    if previous and success <= int(previous["progress"]["last_success_count"]):
        last_progress = dt.datetime.fromisoformat(previous["progress"]["last_progress_utc"])
    else:
        last_progress = checked
    if terminal < TARGET_JOBS and (checked - last_progress).total_seconds() > STALL_SECONDS:
        alerts.append("NO_DOCKING_PROGRESS_FOR_20MIN")

    # Forecast this campaign's remaining storage from observed bytes per
    # verified archive.  The shared SSD can be consumed by unrelated users, so
    # the fixed 50-GiB emergency floor alone is not an adequate early warning.
    result_root_bytes = int(node1.get("result_root_bytes", 0))
    free_bytes = int(node1.get("free_bytes", 0))
    average_bytes_per_archive = (
        result_root_bytes / node1_archives if node1_archives else 0.0
    )
    remaining_jobs = max(0, TARGET_JOBS - terminal)
    projected_remaining_bytes = int(average_bytes_per_archive * remaining_jobs)
    projected_required_free_bytes = projected_remaining_bytes + NODE1_FINAL_RESERVE_BYTES
    if node1_current and result_root_bytes and free_bytes < projected_required_free_bytes:
        alerts.append("NODE1_FREE_SPACE_BELOW_PROJECTED_REQUIREMENT")

    free_space_drop_bytes_per_hour = 0.0
    hours_until_projected_floor = None
    if node1_current and previous and previous.get("node1", {}).get("free_bytes"):
        elapsed_hours = max(
            (checked - dt.datetime.fromisoformat(previous["checked_at_utc"])).total_seconds()
            / 3600,
            1 / 3600,
        )
        free_space_drop_bytes_per_hour = max(
            0.0,
            (int(previous["node1"]["free_bytes"]) - free_bytes) / elapsed_hours,
        )
        margin = free_bytes - projected_required_free_bytes
        if free_space_drop_bytes_per_hour > 0 and margin > 0:
            hours_until_projected_floor = margin / free_space_drop_bytes_per_hour
        if (
            free_space_drop_bytes_per_hour >= RAPID_FREE_SPACE_DROP_BYTES_PER_HOUR
            and hours_until_projected_floor is not None
            and hours_until_projected_floor <= RAPID_DROP_HORIZON_HOURS
        ):
            warnings.append("NODE1_FREE_SPACE_RAPID_DECLINE")

    complete = (
        terminal == TARGET_JOBS
        and node1_current
        and node1_archives == success
        and failed_evidence >= failed
        and not alerts
    )
    status = "COMPLETE" if complete else ("ALERT" if alerts else ("WARNING" if warnings else "HEALTHY"))
    payload = {
        "schema_version": "pvrig_top7500_live_health_v1",
        "checked_at_utc": checked.isoformat(),
        "status": status,
        "alerts": sorted(set(alerts)),
        "warnings": sorted(set(warnings)),
        "target_jobs": TARGET_JOBS,
        "bxcpu": bx,
        "node1": node1,
        "relay": relay,
        "storage_projection": {
            "node1_snapshot_current": node1_current,
            "average_bytes_per_archive": int(average_bytes_per_archive),
            "remaining_jobs_upper_bound": remaining_jobs,
            "projected_remaining_bytes": projected_remaining_bytes,
            "final_reserve_bytes": NODE1_FINAL_RESERVE_BYTES,
            "projected_required_free_bytes": projected_required_free_bytes,
            "free_space_drop_bytes_per_hour": int(free_space_drop_bytes_per_hour),
            "hours_until_projected_floor": hours_until_projected_floor,
        },
        "progress": {
            "success": success,
            "failed": failed,
            "failed_evidence": failed_evidence,
            "local_failed_evidence": local_failed_evidence,
            "pending_node1_delivery": pending_node1_delivery,
            "terminal": terminal,
            "node1_archives": node1_archives,
            "relay_lag": success - node1_archives,
            "last_success_count": success,
            "last_progress_utc": last_progress.isoformat(),
        },
    }
    target = LOCAL_ROOT / "MONITOR_STATUS.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temp, target)
    with (LOCAL_ROOT / "monitor_snapshots.jsonl").open("a") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if status in {"HEALTHY", "WARNING", "COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
