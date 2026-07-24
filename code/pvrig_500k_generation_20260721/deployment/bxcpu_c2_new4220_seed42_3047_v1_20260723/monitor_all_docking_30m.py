#!/usr/bin/env python3
"""Thirty-minute Node1/bxcpu Docking watchdog with resume-safe repair actions."""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "watchdog_runtime"
NODE1_SSH = Path("/mnt/c/WINDOWS/System32/OpenSSH/ssh.exe")
BXCPU_REPAIR = (
    "$HOME/.local/opt/haddock3-2025.11.0/bin/python "
    "$HOME/.local/share/pvrig_c2_new4220_seed42_3047_v1_20260723/"
    "repair_docking_campaigns_if_needed.py"
)
OLD_SYNC_START = (
    HERE.parent
    / "bxcpu_c2_new6220_dualseed_v1_20260723/start_results_sync_sharded.sh"
)
NEW_SYNC_START = HERE / "start_seed42_3047_results_sync_sharded.sh"
OLD_SYNC_BASE = Path(
    "/mnt/d/work/抗体/node1/"
    "pvrig_c2_new6220_dualseed_bxcpu_incremental_spool_20260723"
)
NEW_SYNC_BASE = Path(
    "/mnt/d/work/抗体/node1/"
    "pvrig_c2_new4220_seed42_3047_bxcpu_incremental_spool_20260723"
)
SYNC_GROUPS = {
    "current": {
        "prefix": "pvrig-c2-new6220-sync",
        "start": OLD_SYNC_START,
        "base": OLD_SYNC_BASE,
    },
    "extra_seed42_3047": {
        "prefix": "pvrig-c2-s42-3047-sync",
        "start": NEW_SYNC_START,
        "base": NEW_SYNC_BASE,
    },
}
NODE1_PAUSE_GIB = 25
NODE1_RESUME_GIB = 50
LOCAL_PAUSE_GIB = 20
STALE_SYNC_SECONDS = 3600
STALE_DOCKING_SECONDS = 5400


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(
    command: list[str],
    *,
    check: bool = True,
    timeout: int = 300,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        input=input_text,
    )


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def tmux_session_exists(name: str) -> bool:
    return run(["tmux", "has-session", "-t", name], check=False, timeout=10).returncode == 0


def stop_sync_sessions() -> list[str]:
    stopped: list[str] = []
    for config in SYNC_GROUPS.values():
        for index in range(4):
            name = f"{config['prefix']}-{index:02d}"
            if tmux_session_exists(name):
                run(["tmux", "kill-session", "-t", name], check=False, timeout=10)
                stopped.append(name)
    return stopped


def start_sync_group(key: str) -> str:
    start = Path(SYNC_GROUPS[key]["start"])
    result = run([str(start)], check=False, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"sync start failed for {key}: {result.stdout}")
    return result.stdout.strip()


def sync_log_path(key: str, index: int) -> Path:
    base = Path(SYNC_GROUPS[key]["base"])
    return base / f"shard{index:02d}/state/sync.nohup.log"


def ensure_sync_sessions(paused: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    if paused:
        snapshot["paused"] = True
        return snapshot, actions
    current_time = time.time()
    for key, config in SYNC_GROUPS.items():
        missing: list[str] = []
        stale: list[str] = []
        for index in range(4):
            name = f"{config['prefix']}-{index:02d}"
            exists = tmux_session_exists(name)
            log = sync_log_path(key, index)
            age = current_time - log.stat().st_mtime if log.exists() else None
            if not exists:
                missing.append(name)
            elif age is not None and age > STALE_SYNC_SECONDS:
                stale.append(name)
        if stale:
            for name in stale:
                run(["tmux", "kill-session", "-t", name], check=False, timeout=10)
            missing.extend(stale)
            actions.append({"action": "RESTART_STALE_SYNC_SESSIONS", "group": key, "sessions": stale})
        if missing:
            output = start_sync_group(key)
            actions.append(
                {
                    "action": "START_MISSING_SYNC_SESSIONS",
                    "group": key,
                    "sessions": sorted(set(missing)),
                    "output": output,
                }
            )
        snapshot[key] = {
            "missing_before_repair": sorted(set(missing)),
            "stale_before_repair": stale,
            "active_after_repair": [
                f"{config['prefix']}-{index:02d}"
                for index in range(4)
                if tmux_session_exists(f"{config['prefix']}-{index:02d}")
            ],
            "latest_log_age_seconds": min(
                [
                    current_time - sync_log_path(key, index).stat().st_mtime
                    for index in range(4)
                    if sync_log_path(key, index).exists()
                ],
                default=None,
            ),
        }
    return snapshot, actions


def node1_snapshot() -> dict[str, Any]:
    script = r"""
import json,os,subprocess
from pathlib import Path
roots={
 "current_results":Path("/data1/qlyu/projects/pvrig_c2_new6220_dualreceptor_2seed_docking_results_v1_20260723"),
 "extra_results":Path("/data1/qlyu/projects/pvrig_c2_new4220_seed42_3047_docking_results_v1_20260723"),
 "rfantibody":Path("/data1/qlyu/projects/pvrig_1m_rfantibody150k_v1_20260722"),
}
sync_roots={
 "current_4220":roots["current_results"]/ "c2_new4220",
 "current_2000":roots["current_results"]/ "c2_new2000",
 "extra_seed42_3047":roots["extra_results"]/ "c2_new4220_seed42_3047",
}
v=os.statvfs("/data1")
sizes={}
for key,path in roots.items():
 result=subprocess.run(["du","-sb",str(path)],text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 try:sizes[key]=int(result.stdout.split()[0])
 except:sizes[key]=-1
sync_counts={}
for key,path in sync_roots.items():
 sync_counts[key]={
  "status_files":len(list((path/"status/jobs").glob("*.json"))) if (path/"status/jobs").is_dir() else 0,
  "result_files":len(list((path/"results").glob("*/job_result.json"))) if (path/"results").is_dir() else 0,
 }
print(json.dumps({
 "filesystem_free_bytes":v.f_bavail*v.f_frsize,
 "filesystem_total_bytes":v.f_blocks*v.f_frsize,
 "project_bytes":sizes,
 "sync_counts":sync_counts,
}))
"""
    result = run(
        [str(NODE1_SSH), "-o", "BatchMode=yes", "node1", "python3", "-"],
        timeout=180,
        input_text=script,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def bxcpu_snapshot_and_repair() -> dict[str, Any]:
    result = run(["ssh", "bxcpu", BXCPU_REPAIR], timeout=300)
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock_handle = (RUNTIME / "watchdog.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0

    generated = now()
    actions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        node1 = node1_snapshot()
    except Exception as exc:
        node1 = {"error": repr(exc)}
        errors.append({"component": "node1", "error": repr(exc)})
    local_disk = shutil.disk_usage(RUNTIME)
    pause_marker = RUNTIME / "SYNC_PAUSED_LOW_DISK.json"
    node1_free = int(node1.get("filesystem_free_bytes", -1))
    low_node1 = 0 <= node1_free < NODE1_PAUSE_GIB * 1024**3
    low_local = local_disk.free < LOCAL_PAUSE_GIB * 1024**3
    if (low_node1 or low_local) and not pause_marker.exists():
        stopped = stop_sync_sessions()
        payload = {
            "status": "SYNC_PAUSED_TO_PROTECT_AUTHORITATIVE_STORAGE",
            "created_at_utc": generated,
            "node1_free_bytes": node1_free,
            "local_free_bytes": local_disk.free,
            "stopped_sessions": stopped,
        }
        atomic_json(pause_marker, payload)
        actions.append({"action": "PAUSE_SYNC_LOW_DISK", **payload})
    elif pause_marker.exists() and (
        node1_free >= NODE1_RESUME_GIB * 1024**3
        and local_disk.free >= LOCAL_PAUSE_GIB * 1024**3
    ):
        pause_marker.unlink()
        actions.append({"action": "RESUME_SYNC_DISK_RECOVERED"})
    paused = pause_marker.exists()

    try:
        sync, sync_actions = ensure_sync_sessions(paused)
        actions.extend(sync_actions)
    except Exception as exc:
        sync = {"error": repr(exc)}
        errors.append({"component": "sync", "error": repr(exc)})
    try:
        bxcpu = bxcpu_snapshot_and_repair()
        actions.extend(bxcpu.get("actions", []))
    except Exception as exc:
        bxcpu = {"error": repr(exc)}
        errors.append({"component": "bxcpu", "error": repr(exc)})

    alerts: list[dict[str, Any]] = []
    if 0 <= node1_free < 60 * 1024**3:
        alerts.append({"severity": "critical" if low_node1 else "warning", "issue": "NODE1_LOW_DISK", "free_bytes": node1_free})
    if local_disk.free < 30 * 1024**3:
        alerts.append({"severity": "critical" if low_local else "warning", "issue": "LOCAL_SPOOL_LOW_DISK", "free_bytes": local_disk.free})
    for key in ("current", "extra_seed42_3047"):
        campaign = bxcpu.get(key, {}) if isinstance(bxcpu, dict) else {}
        age = campaign.get("latest_status_age_seconds")
        expected = int(campaign.get("expected", -1))
        terminal = int(campaign.get("terminal", -2))
        if (
            expected >= 0
            and terminal == expected
            and campaign.get("audit_state") == "COMPLETED"
        ):
            continue
        active = campaign.get("array_active") or campaign.get("array_state") in {
            "RUNNING",
            "PENDING",
            "CONFIGURING",
            "COMPLETING",
        }
        if active and age is not None and age > STALE_DOCKING_SECONDS:
            alerts.append({"severity": "warning", "issue": "DOCKING_PROGRESS_STALE", "campaign": key, "age_seconds": age})
    storage = bxcpu.get("storage", {}) if isinstance(bxcpu, dict) else {}
    known_bxcpu = int(storage.get("known_campaign_bytes", -1))
    soft_limit = int(storage.get("known_campaign_soft_limit_bytes", 64 * 1024**3))
    if known_bxcpu >= 0.75 * soft_limit:
        alerts.append(
            {
                "severity": "critical" if known_bxcpu >= soft_limit else "warning",
                "issue": "BXCPU_KNOWN_CAMPAIGN_SOFT_QUOTA",
                "known_campaign_bytes": known_bxcpu,
                "soft_limit_bytes": soft_limit,
                "quota_probe_available": storage.get("quota_probe_available", False),
            }
        )

    status = "PASS"
    if errors or any(alert["severity"] == "critical" for alert in alerts):
        status = "ATTENTION_REQUIRED"
    elif alerts or actions:
        status = "PASS_WITH_ACTIONS_OR_WARNINGS"
    report = {
        "schema_version": "pvrig.all_docking.watchdog_30m.v1",
        "status": status,
        "generated_at_utc": generated,
        "interval_seconds": 1800,
        "node1": node1,
        "bxcpu": bxcpu,
        "local": {
            "filesystem_total_bytes": local_disk.total,
            "filesystem_free_bytes": local_disk.free,
            "sync_paused_low_disk": paused,
        },
        "sync": sync,
        "actions": actions,
        "alerts": alerts,
        "errors": errors,
    }
    node1_counts = node1.get("sync_counts", {}) if isinstance(node1, dict) else {}
    current = bxcpu.get("current", {}) if isinstance(bxcpu, dict) else {}
    extra = bxcpu.get("extra_seed42_3047", {}) if isinstance(bxcpu, dict) else {}
    current_sync_status = (
        int(node1_counts.get("current_4220", {}).get("status_files", -1)) == 16880
        and int(node1_counts.get("current_2000", {}).get("status_files", -1)) == 8000
    )
    current_sync_results = (
        int(node1_counts.get("current_4220", {}).get("result_files", -1))
        == int(current.get("batch_4220", {}).get("success", -2))
        and int(node1_counts.get("current_2000", {}).get("result_files", -1))
        == int(current.get("batch_2000", {}).get("success", -2))
    )
    extra_sync_status = (
        int(node1_counts.get("extra_seed42_3047", {}).get("status_files", -1)) == 16880
    )
    extra_sync_results = (
        int(node1_counts.get("extra_seed42_3047", {}).get("result_files", -1))
        == int(extra.get("success", -2))
    )
    completion = {
        "current_bxcpu_terminal": (
            int(current.get("terminal", -1)) == 24880
            and current.get("audit_state") == "COMPLETED"
        ),
        "current_node1_sync_status_closed": current_sync_status,
        "current_node1_success_results_closed": current_sync_results,
        "extra_bxcpu_terminal": (
            int(extra.get("terminal", -1)) == 16880
            and extra.get("audit_state") == "COMPLETED"
        ),
        "extra_node1_sync_status_closed": extra_sync_status,
        "extra_node1_success_results_closed": extra_sync_results,
    }
    completion["all_complete"] = all(completion.values()) and not errors
    report["completion"] = completion
    if completion["all_complete"]:
        atomic_json(RUNTIME / "ALL_DOCKING_COMPLETE.json", report)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    atomic_json(RUNTIME / f"checks/watchdog_{stamp}.json", report)
    atomic_json(RUNTIME / "LATEST.json", report)
    with (RUNTIME / "watchdog_history.jsonl").open("a") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
