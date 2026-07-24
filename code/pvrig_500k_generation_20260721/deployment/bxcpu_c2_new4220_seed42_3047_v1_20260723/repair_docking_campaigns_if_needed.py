#!/usr/bin/env python3
"""Inspect both bxcpu campaigns and submit only resume-safe repair work."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any


HOME = Path.home()
CURRENT_DEPLOY = HOME / ".local/share/bxcpu_c2_new6220_dualseed_v1_20260723"
CURRENT_ROOT = HOME / "pvrig_c2_new6220_dualreceptor_2seed_v1_20260723_bxcpu_results"
CURRENT_ARCHIVE = HOME / "pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz"
CURRENT_ARRAY = "11943288"
CURRENT_AUDIT = "11943297"

EXTRA_DEPLOY = HOME / ".local/share/pvrig_c2_new4220_seed42_3047_v1_20260723"
EXTRA_ROOT = HOME / "pvrig_c2_new4220_seed42_3047_v1_20260723_bxcpu_results"
EXTRA_ARCHIVE = HOME / "c2_new4220_dualreceptor_seed42_3047_handoff_v1_20260723.tar.gz"
EXTRA_ARCHIVE_SHA = "b5afb17360a03c539e02dae064e87f8b70de597179823a891f1f8a0a79ac4061"
EXTRA_MANIFEST_SHA = "60290622ab842f7c888912c828a2a48068a208ba370b666a32b121a8c7266aa5"
TERMINAL_STATES = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "BOOT_FAIL",
}
ACTIVE_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def state(job_id: str | None) -> str:
    if not job_id:
        return "MISSING"
    result = run(
        ["sacct", "-n", "-X", "-j", job_id, "--format=JobIDRaw,State", "-P"],
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 2 and parts[0] == job_id:
            return parts[1].split("+", 1)[0]
    return "UNKNOWN"


def active_for(job_id: str | None) -> bool:
    if not job_id:
        return False
    result = run(["squeue", "-h", "-j", job_id, "-o", "%i|%T"], check=False)
    return result.returncode == 0 and any(
        line.strip() for line in result.stdout.splitlines()
    )


def active_named(fragment: str) -> bool:
    result = run(["squeue", "-h", "-u", os.environ["USER"], "-o", "%j|%T"], check=False)
    return any(fragment in line and line.rsplit("|", 1)[-1] in ACTIVE_STATES for line in result.stdout.splitlines())


def status_count(directory: Path) -> tuple[int, int, int]:
    success = failed = invalid = 0
    if not directory.is_dir():
        return 0, 0, 0
    for path in directory.glob("*.json"):
        try:
            value = str(json.loads(path.read_text()).get("status", "UNKNOWN")).upper()
        except Exception:
            invalid += 1
            continue
        if value == "SUCCESS":
            success += 1
        elif value in {"FAILED", "FAILED_MAX_ATTEMPTS"}:
            failed += 1
        else:
            invalid += 1
    return success, failed, invalid


def latest_status_age_seconds(directory: Path) -> float | None:
    mtimes = [path.stat().st_mtime for path in directory.glob("*.json")] if directory.is_dir() else []
    if not mtimes:
        return None
    return max(0.0, dt.datetime.now().timestamp() - max(mtimes))


def latest_status_age_across(*directories: Path) -> float | None:
    values = [latest_status_age_seconds(directory) for directory in directories]
    present = [value for value in values if value is not None]
    return min(present) if present else None


def read_id(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text().strip()
    return value or None


def next_round(root: Path, key: str) -> int:
    directory = root / "markers/watchdog_repairs"
    directory.mkdir(parents=True, exist_ok=True)
    rounds = []
    for path in directory.glob(f"{key}_round_*.json"):
        try:
            rounds.append(int(path.stem.rsplit("_", 1)[-1]))
        except ValueError:
            pass
    return max(rounds, default=0) + 1


def latest_repair(root: Path, key: str) -> dict[str, Any] | None:
    directory = root / "markers/watchdog_repairs"
    candidates: list[tuple[int, Path]] = []
    for path in directory.glob(f"{key}_round_*.json") if directory.is_dir() else []:
        try:
            candidates.append((int(path.stem.rsplit("_", 1)[-1]), path))
        except ValueError:
            pass
    if not candidates:
        return None
    return json.loads(max(candidates)[1].read_text())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def submit(command: list[str], dry_run: bool) -> str:
    if dry_run:
        return "DRY_RUN"
    output = run(command).stdout.strip()
    return output.split(";", 1)[0]


def current_exports() -> str:
    anchors = json.loads((CURRENT_DEPLOY / "FROZEN_INPUT_ANCHORS.json").read_text())
    return ",".join(
        [
            "ALL",
            f"PVRIG_C2_NEW_DEPLOY_ROOT={CURRENT_DEPLOY}",
            f"PVRIG_C2_NEW_PUBLISH_ROOT={CURRENT_ROOT}",
            f"PVRIG_C2_NEW_BUNDLE_ARCHIVE={CURRENT_ARCHIVE}",
            f"PVRIG_C2_NEW_ARCHIVE_SHA256={anchors['archive_sha256']}",
            f"PVRIG_C2_NEW_ROOT_RECEIPT_SHA256={anchors['root_receipt_sha256']}",
            f"PVRIG_C2_NEW_4220_MANIFEST_SHA256={anchors['manifest_4220_sha256']}",
            f"PVRIG_C2_NEW_2000_MANIFEST_SHA256={anchors['manifest_2000_sha256']}",
            f"PVRIG_C2_NEW_ANCHORS_SHA256={__import__('hashlib').sha256((CURRENT_DEPLOY / 'FROZEN_INPUT_ANCHORS.json').read_bytes()).hexdigest()}",
            "PVRIG_C2_NEW_NODE_CONCURRENCY=16",
        ]
    )


def extra_exports() -> str:
    return ",".join(
        [
            "ALL",
            f"PVRIG_C2_EXTRA_DEPLOY_ROOT={EXTRA_DEPLOY}",
            f"PVRIG_C2_EXTRA_ARCHIVE={EXTRA_ARCHIVE}",
            f"PVRIG_C2_EXTRA_PUBLISH_ROOT={EXTRA_ROOT}",
            f"PVRIG_C2_EXTRA_ARCHIVE_SHA256={EXTRA_ARCHIVE_SHA}",
            f"PVRIG_C2_EXTRA_MANIFEST_SHA256={EXTRA_MANIFEST_SHA}",
            "PVRIG_C2_EXTRA_NODE_CONCURRENCY=16",
        ]
    )


def submit_resume_array(
    *,
    campaign: str,
    deploy: Path,
    publish: Path,
    worker: Path,
    audit_script: Path,
    export: str,
    dry_run: bool,
) -> dict[str, Any]:
    round_no = next_round(publish, campaign)
    tag = f"{campaign}-repair{round_no}"
    array = submit(
        [
            "sbatch",
            "--parsable",
            "--partition=amd_256q",
            f"--job-name={tag}",
            "--nodes=1",
            "--ntasks=1",
            "--cpus-per-task=64",
            "--mem=230G",
            "--exclusive",
            "--time=24:00:00",
            "--array=1-8%8",
            f"--output={publish}/slurm-%x-%A_%a.out",
            f"--error={publish}/slurm-%x-%A_%a.err",
            f"--export={export}",
            str(worker),
        ],
        dry_run,
    )
    audit_dependency = "afterany" + "".join(f":{array}_{index}" for index in range(1, 9))
    audit = submit(
        [
            "sbatch",
            "--parsable",
            f"--dependency={audit_dependency}",
            "--partition=amd_256q",
            f"--job-name={tag}-audit",
            "--nodes=1",
            "--ntasks=1",
            "--cpus-per-task=1",
            "--mem=4G",
            "--time=01:00:00",
            f"--output={publish}/slurm-%x-%j.out",
            f"--error={publish}/slurm-%x-%j.err",
            f"--export={export}",
            str(audit_script),
        ],
        dry_run,
    )
    payload = {
        "status": "DRY_RUN_REPAIR" if dry_run else "REPAIR_SUBMITTED",
        "campaign": campaign,
        "round": round_no,
        "array_job_id": array,
        "audit_job_id": audit,
        "created_at_utc": now(),
    }
    if not dry_run:
        atomic_json(
            publish / f"markers/watchdog_repairs/{campaign}_round_{round_no:02d}.json",
            payload,
        )
    return payload


def submit_audit_only(
    *,
    campaign: str,
    publish: Path,
    audit_script: Path,
    export: str,
    dry_run: bool,
) -> dict[str, Any]:
    round_no = next_round(publish, campaign)
    tag = f"{campaign}-repair{round_no}"
    audit = submit(
        [
            "sbatch",
            "--parsable",
            "--partition=amd_256q",
            f"--job-name={tag}",
            "--nodes=1",
            "--ntasks=1",
            "--cpus-per-task=1",
            "--mem=4G",
            "--time=01:00:00",
            f"--output={publish}/slurm-%x-%j.out",
            f"--error={publish}/slurm-%x-%j.err",
            f"--export={export}",
            str(audit_script),
        ],
        dry_run,
    )
    payload = {
        "status": "DRY_RUN_AUDIT_REPAIR" if dry_run else "AUDIT_REPAIR_SUBMITTED",
        "campaign": campaign,
        "round": round_no,
        "audit_job_id": audit,
        "created_at_utc": now(),
    }
    if not dry_run:
        atomic_json(
            publish / f"markers/watchdog_repairs/{campaign}_round_{round_no:02d}.json",
            payload,
        )
    return payload


def maybe_repair_current(dry_run: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    a = status_count(CURRENT_ROOT / "batch_4220/status/jobs")
    b = status_count(CURRENT_ROOT / "batch_2000/status/jobs")
    terminal = sum(a[:2]) + sum(b[:2])
    repair = latest_repair(CURRENT_ROOT, "pvrig-c2new-r1")
    audit_repair = latest_repair(CURRENT_ROOT, "pvrig-c2new-r1-audit-only")
    effective_array = str(repair["array_job_id"]) if repair else CURRENT_ARRAY
    effective_audit = (
        str(audit_repair["audit_job_id"])
        if audit_repair
        else str(repair["audit_job_id"])
        if repair
        else CURRENT_AUDIT
    )
    audit_state = state(effective_audit)
    snapshot = {
        "terminal": terminal,
        "expected": 24880,
        "batch_4220": {"success": a[0], "technical_na": a[1], "invalid": a[2]},
        "batch_2000": {"success": b[0], "technical_na": b[1], "invalid": b[2]},
        "array_job_id": effective_array,
        "array_active": active_for(effective_array),
        "audit_job_id": effective_audit,
        "audit_state": audit_state,
        "latest_status_age_seconds": latest_status_age_across(
            CURRENT_ROOT / "batch_4220/status/jobs",
            CURRENT_ROOT / "batch_2000/status/jobs",
        ),
    }
    actions: list[dict[str, Any]] = []
    if (
        terminal < 24880
        and not snapshot["array_active"]
        and audit_state in TERMINAL_STATES
        and not active_named("pvrig-c2new-r1-repair")
    ):
        action = submit_resume_array(
            campaign="pvrig-c2new-r1",
            deploy=CURRENT_DEPLOY,
            publish=CURRENT_ROOT,
            worker=CURRENT_DEPLOY / "bxcpu_c2_new6220_dualseed_eight_node_worker.sh",
            audit_script=CURRENT_DEPLOY / "run_terminal_audit.sh",
            export=current_exports(),
            dry_run=dry_run,
        )
        actions.append(action)
        if not dry_run:
            preflight = read_id(EXTRA_ROOT / "markers/PREFLIGHT_JOB_ID")
            if preflight and state(preflight) == "PENDING":
                run(["scontrol", "update", f"JobId={preflight}", f"Dependency=afterok:{action['audit_job_id']}"])
                actions.append(
                    {
                        "status": "EXTRA_PREFLIGHT_REDEPENDENCED_ON_REPAIR_AUDIT",
                        "preflight_job_id": preflight,
                        "repair_audit_job_id": action["audit_job_id"],
                    }
                )
    elif (
        terminal == 24880
        and audit_state in TERMINAL_STATES - {"COMPLETED"}
        and not active_named("pvrig-c2new-r1-audit-only-repair")
    ):
        action = submit_audit_only(
            campaign="pvrig-c2new-r1-audit-only",
            publish=CURRENT_ROOT,
            audit_script=CURRENT_DEPLOY / "run_terminal_audit.sh",
            export=current_exports(),
            dry_run=dry_run,
        )
        actions.append(action)
        if not dry_run:
            preflight = read_id(EXTRA_ROOT / "markers/PREFLIGHT_JOB_ID")
            override = EXTRA_ROOT / "markers/CURRENT_AUDIT_OVERRIDE_ID"
            override.parent.mkdir(parents=True, exist_ok=True)
            override.write_text(str(action["audit_job_id"]) + "\n")
            if preflight and state(preflight) == "PENDING":
                run(
                    [
                        "scontrol",
                        "update",
                        f"JobId={preflight}",
                        f"Dependency=afterok:{action['audit_job_id']}",
                    ]
                )
                actions.append(
                    {
                        "status": "EXTRA_PREFLIGHT_REDEPENDENCED_ON_AUDIT_ONLY_REPAIR",
                        "preflight_job_id": preflight,
                        "repair_audit_job_id": action["audit_job_id"],
                    }
                )
    return snapshot, actions


def maybe_repair_extra(dry_run: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    counts = status_count(EXTRA_ROOT / "status/jobs")
    terminal = counts[0] + counts[1]
    preflight_id = read_id(EXTRA_ROOT / "markers/PREFLIGHT_JOB_ID")
    array_id = read_id(EXTRA_ROOT / "markers/ARRAY_JOB_ID")
    audit_id = read_id(EXTRA_ROOT / "markers/AUDIT_JOB_ID")
    preflight_state = state(preflight_id)
    array_state = state(array_id)
    audit_state = state(audit_id)
    snapshot = {
        "terminal": terminal,
        "expected": 16880,
        "success": counts[0],
        "technical_na": counts[1],
        "invalid": counts[2],
        "preflight_job_id": preflight_id,
        "preflight_state": preflight_state,
        "array_job_id": array_id,
        "array_state": array_state,
        "audit_job_id": audit_id,
        "audit_state": audit_state,
        "latest_status_age_seconds": latest_status_age_seconds(EXTRA_ROOT / "status/jobs"),
    }
    actions: list[dict[str, Any]] = []
    if (
        not array_id
        and preflight_id
        and preflight_state in TERMINAL_STATES - {"COMPLETED"}
        and not active_named("pvrig-c2-s42-3047-preflight")
    ):
        replacement = submit(
            [
                "sbatch",
                "--parsable",
                "--partition=amd_256q",
                "--job-name=pvrig-c2-s42-3047-preflight-repair",
                "--nodes=1",
                "--ntasks=1",
                "--cpus-per-task=4",
                "--mem=16G",
                "--time=00:30:00",
                f"--output={EXTRA_ROOT}/slurm-%x-%j.out",
                f"--error={EXTRA_ROOT}/slurm-%x-%j.err",
                f"--export={extra_exports()}",
                str(EXTRA_DEPLOY / "preflight_seed42_3047.sh"),
            ],
            dry_run,
        )
        actions.append(
            {
                "status": "DRY_RUN_PREFLIGHT_REPAIR" if dry_run else "PREFLIGHT_REPAIR_SUBMITTED",
                "old_preflight_job_id": preflight_id,
                "new_preflight_job_id": replacement,
            }
        )
        if not dry_run:
            (EXTRA_ROOT / "markers/PREFLIGHT_JOB_ID").write_text(replacement + "\n")
    if (
        array_id
        and terminal < 16880
        and not active_for(array_id)
        and audit_state in TERMINAL_STATES
        and not active_named("pvrig-c2-s42-3047-repair")
    ):
        action = submit_resume_array(
                campaign="pvrig-c2-s42-3047",
                deploy=EXTRA_DEPLOY,
                publish=EXTRA_ROOT,
                worker=EXTRA_DEPLOY / "bxcpu_c2_new4220_seed42_3047_worker.sh",
                audit_script=EXTRA_DEPLOY / "run_terminal_audit_seed42_3047.sh",
                export=extra_exports(),
                dry_run=dry_run,
            )
        actions.append(action)
        if not dry_run:
            (EXTRA_ROOT / "markers/ARRAY_JOB_ID").write_text(
                str(action["array_job_id"]) + "\n"
            )
            (EXTRA_ROOT / "markers/AUDIT_JOB_ID").write_text(
                str(action["audit_job_id"]) + "\n"
            )
    return snapshot, actions


def tree_bytes(root: Path) -> int:
    result = run(["du", "-sb", str(root)], check=False)
    try:
        return int(result.stdout.split()[0])
    except Exception:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    current, current_actions = maybe_repair_current(args.dry_run)
    extra, extra_actions = maybe_repair_extra(args.dry_run)
    stat = os.statvfs(HOME)
    current_result_bytes = tree_bytes(CURRENT_ROOT)
    extra_result_bytes = tree_bytes(EXTRA_ROOT)
    current_archive_bytes = CURRENT_ARCHIVE.stat().st_size if CURRENT_ARCHIVE.exists() else -1
    extra_archive_bytes = EXTRA_ARCHIVE.stat().st_size if EXTRA_ARCHIVE.exists() else -1
    known_campaign_bytes = sum(
        max(0, value)
        for value in (
            current_result_bytes,
            extra_result_bytes,
            current_archive_bytes,
            extra_archive_bytes,
        )
    )
    quota_probe = run(["quota", "-s"], check=False).stdout.strip()
    report = {
        "schema_version": "pvrig.bxcpu.docking_watchdog.v1",
        "generated_at_utc": now(),
        "dry_run": args.dry_run,
        "current": current,
        "extra_seed42_3047": extra,
        "actions": current_actions + extra_actions,
        "storage": {
            "filesystem_free_bytes": stat.f_bavail * stat.f_frsize,
            "filesystem_type": "gpfs",
            "current_result_bytes": current_result_bytes,
            "extra_result_bytes": extra_result_bytes,
            "current_archive_bytes": current_archive_bytes,
            "extra_archive_bytes": extra_archive_bytes,
            "known_campaign_bytes": known_campaign_bytes,
            "known_campaign_soft_limit_bytes": 64 * 1024**3,
            "quota_probe_available": bool(quota_probe),
            "quota_probe_text": quota_probe[-2000:],
        },
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
