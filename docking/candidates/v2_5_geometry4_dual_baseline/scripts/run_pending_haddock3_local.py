#!/usr/bin/env python3
"""Claim Geometry-4 ownership from Node1 and run pending HADDOCK3 jobs locally."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_POSE_ROOT = REPO_ROOT / "docking/candidates/v2_5_pose_batch/remote_sync/haddock3"
DEFAULT_HADDOCK_BIN = Path("/root/.local/share/pvrig-v25/haddock3-2025.11.0/bin/haddock3")
DEFAULT_HANDOFF = PACKAGE_ROOT / "reports/local_execution_handoff.json"
DEFAULT_STATUS = PACKAGE_ROOT / "reports/local_execution_status.json"
EVENTS_TSV = PACKAGE_ROOT / "reports/local_execution_events.tsv"
LOCK_PATH = PACKAGE_ROOT / ".local_geometry4_haddock.lock"

EXPECTED_VERSION = "2025.11.0"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_v2_5_pose_batch"
WAITER_SOCKET = "pvrig_v25_geometry4"
WAITER_SESSION = "pvrig_v25_geometry4_waiter"
CANDIDATES = ("zym_test_359954", "zym_test_3633872", "zym_test_8787")
HANDOFF_SCHEMA = "pvrig_v2_5_geometry4_local_handoff_v1"
STATUS_SCHEMA = "pvrig_v2_5_geometry4_local_execution_v1"
CLAIM_BOUNDARY = "computational_geometry_priority_not_experimental_binding_or_blocking_truth"


class LocalExecutionError(RuntimeError):
    """Fail-closed operational error."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_event(event: str, candidate: str = "-", detail: str = "-") -> None:
    EVENTS_TSV.parent.mkdir(parents=True, exist_ok=True)
    fields = (now_iso(), event, candidate, detail)
    safe_fields = [str(value).encode("ascii", "backslashreplace").decode("ascii") for value in fields]
    with EVENTS_TSV.open("a", encoding="ascii") as handle:
        handle.write("\t".join(safe_fields) + "\n")


def write_status(path: Path, state: str, detail: str, **extra: Any) -> None:
    payload: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA,
        "claim_boundary": CLAIM_BOUNDARY,
        "updated_at": now_iso(),
        "state": state,
        "detail": detail,
    }
    payload.update(extra)
    atomic_json(path, payload)


def run_complete(run_dir: Path) -> bool:
    consensus = run_dir / "traceback/consensus.tsv"
    top_dir = run_dir / "6_seletopclusts"
    return consensus.is_file() and consensus.stat().st_size > 0 and top_dir.is_dir() and any(
        path.is_file() and path.stat().st_size > 0
        for pattern in ("cluster_*_model_*.pdb", "cluster_*_model_*.pdb.gz")
        for path in top_dir.glob(pattern)
    )


def candidate_paths(pose_root: Path, candidate: str) -> dict[str, Path]:
    workdir = pose_root / candidate
    return {
        "workdir": workdir,
        "config": workdir / f"{candidate}_pvrig_hotspot.cfg",
        "vhh": workdir / "data" / f"{candidate}_vhh_chainA.pdb",
        "receptor": workdir / "data/pvrig_8x6b_chainB.pdb",
        "restraints": workdir / "data" / f"{candidate}_cdr_to_pvrig_hotspot_ambig.tbl",
        "run_dir": workdir / f"run_{candidate}_pvrig_hotspot",
    }


def validate_local_inputs(pose_root: Path) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for candidate in CANDIDATES:
        paths = candidate_paths(pose_root, candidate)
        for key in ("config", "vhh", "receptor", "restraints"):
            path = paths[key]
            if not path.is_file() or path.stat().st_size == 0:
                raise LocalExecutionError(f"missing or empty {key} for {candidate}: {path}")

        run_dir = paths["run_dir"]
        if run_complete(run_dir):
            run_state = "COMPLETE"
        elif run_dir.exists():
            raise LocalExecutionError(f"refuse incomplete existing local run: {run_dir}")
        else:
            run_state = "ABSENT"

        config_text = paths["config"].read_text(encoding="utf-8")
        expected_run = f"run_{candidate}_pvrig_hotspot"
        expected_molecules = [
            f"data/{candidate}_vhh_chainA.pdb",
            "data/pvrig_8x6b_chainB.pdb",
        ]
        run_match = re.search(r'(?m)^run_dir\s*=\s*"([^"]+)"\s*$', config_text)
        mode_match = re.search(r'(?m)^mode\s*=\s*"([^"]+)"\s*$', config_text)
        ncores_match = re.search(r"(?m)^ncores\s*=\s*([0-9]+)\s*$", config_text)
        molecules_match = re.search(r"(?ms)^molecules\s*=\s*\[(.*?)\]\s*$", config_text)
        rigidbody_match = re.search(r"(?ms)^\[rigidbody\]\s*(.*?)(?=^\[|\Z)", config_text)
        sampling_match = (
            re.search(r"(?m)^sampling\s*=\s*([0-9]+)\s*$", rigidbody_match.group(1))
            if rigidbody_match
            else None
        )
        molecules = re.findall(r'"([^"]+)"', molecules_match.group(1)) if molecules_match else []
        if not run_match or run_match.group(1) != expected_run:
            raise LocalExecutionError(f"unexpected run_dir in {paths['config']}")
        if not mode_match or mode_match.group(1) != "local" or not ncores_match or int(ncores_match.group(1)) != 8:
            raise LocalExecutionError(f"production config must use mode=local and ncores=8: {paths['config']}")
        if molecules != expected_molecules:
            raise LocalExecutionError(f"unexpected molecule paths in {paths['config']}")
        if not sampling_match or int(sampling_match.group(1)) != 40:
            raise LocalExecutionError(f"production rigidbody sampling must remain 40: {paths['config']}")

        evidence[candidate] = {
            "run_state": run_state,
            "config_sha256": sha256_file(paths["config"]),
            "vhh_sha256": sha256_file(paths["vhh"]),
            "receptor_sha256": sha256_file(paths["receptor"]),
            "restraints_sha256": sha256_file(paths["restraints"]),
        }
    return evidence


def runtime_preflight(haddock_bin: Path) -> dict[str, str]:
    if not haddock_bin.is_file() or not os.access(haddock_bin, os.X_OK):
        raise LocalExecutionError(f"HADDOCK3 executable is unavailable: {haddock_bin}")
    version_result = subprocess.run(
        [str(haddock_bin), "--version"], text=True, capture_output=True, timeout=30, check=False
    )
    version_text = (version_result.stdout + version_result.stderr).strip()
    if version_result.returncode != 0 or version_text != f"haddock3 - {EXPECTED_VERSION}":
        raise LocalExecutionError(f"unexpected HADDOCK3 version: {version_text!r}")

    runtime_python = haddock_bin.parent / "python"
    cfg_bin = haddock_bin.parent / "haddock3-cfg"
    if not runtime_python.is_file() or not cfg_bin.is_file():
        raise LocalExecutionError("HADDOCK3 runtime is missing python or haddock3-cfg")
    cfg_result = subprocess.run(
        [str(cfg_bin), "-m", "rigidbody"], text=True, capture_output=True, timeout=30, check=False
    )
    if cfg_result.returncode != 0 or "[rigidbody]" not in cfg_result.stdout:
        raise LocalExecutionError("haddock3-cfg rigidbody preflight failed")

    smoke_code = r'''
import json
import subprocess
from importlib.metadata import version
from haddock.libs.libutil import get_cns_executable

cns = get_cns_executable()[0]
result = subprocess.run([str(cns)], input="stop\n", text=True, capture_output=True, timeout=15)
print(json.dumps({
    "version": version("haddock3"),
    "cns": str(cns),
    "cns_returncode": result.returncode,
    "cns_stopped": "Program stopped at:" in result.stdout,
}, sort_keys=True))
'''
    smoke_result = subprocess.run(
        [str(runtime_python), "-c", smoke_code], text=True, capture_output=True, timeout=30, check=False
    )
    if smoke_result.returncode != 0:
        raise LocalExecutionError(f"CNS preflight command failed: {smoke_result.stderr.strip()}")
    try:
        smoke = json.loads(smoke_result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LocalExecutionError("CNS preflight did not return valid JSON") from exc
    if (
        smoke.get("version") != EXPECTED_VERSION
        or smoke.get("cns_returncode") != 0
        or smoke.get("cns_stopped") is not True
    ):
        raise LocalExecutionError(f"CNS preflight failed: {smoke}")
    return {
        "haddock_bin": str(haddock_bin),
        "haddock_version": EXPECTED_VERSION,
        "cns_bin": str(smoke["cns"]),
        "cns_smoke": "PASS_STOP",
        "rigidbody_cfg": "PASS",
    }


def find_local_conflicts() -> list[str]:
    conflicts: list[str] = []
    own_pid = os.getpid()
    patterns = ("watch_and_finalize_geometry4.py",) + tuple(
        f"{candidate}_pvrig_hotspot.cfg" for candidate in CANDIDATES
    )
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == own_pid:
            continue
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(pattern in command for pattern in patterns):
            conflicts.append(f"pid={proc.name} command={command.strip()}")
    return conflicts


REMOTE_CLAIM_SCRIPT = r'''set -euo pipefail
socket=$1
session=$2
root=$3
nonce=$4
state_file="$root/geometry4_waiter/status.env"
owner_file="$root/geometry4_waiter/execution_owner.env"
ownership_lock="$root/geometry4_waiter/ownership.lock"
runner_lock="$root/geometry4_waiter/runner.lock"
candidates=(zym_test_359954 zym_test_3633872 zym_test_8787)

mkdir -p "$root/geometry4_waiter"
exec 8>"$ownership_lock"
flock -w 10 8 || { echo REFUSE_OWNERSHIP_LOCK_TIMEOUT >&2; exit 58; }

read_state() {
  if [[ -s "$state_file" ]]; then
    awk -F= '$1 == "state" {print $2; exit}' "$state_file"
  fi
}
run_state() {
  local cid=$1 run="$root/haddock3/$cid/run_${cid}_pvrig_hotspot"
  if [[ -s "$run/traceback/consensus.tsv" ]] &&
     find "$run/6_seletopclusts" -maxdepth 1 \
       \( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \) \
       -type f -size +0c -print -quit 2>/dev/null | grep -q .; then
    printf COMPLETE
  elif [[ -e "$run" ]]; then
    printf INCOMPLETE
  else
    printf ABSENT
  fi
}

before_state=$(read_state)
for cid in "${candidates[@]}"; do
  state=$(run_state "$cid")
  [[ "$state" == ABSENT ]] || {
    echo "REFUSE_REMOTE_RUN_$state candidate=$cid" >&2
    exit 41
  }
done
if [[ "$before_state" == RUNNING || "$before_state" == GATE_ACCEPTED ]]; then
  echo "REFUSE_REMOTE_WAITER_ACTIVE state=$before_state" >&2
  exit 42
fi

was_running=0
stopped_pid=
resume_waiter() {
  if [[ -n "$stopped_pid" ]]; then
    kill -CONT "$stopped_pid" 2>/dev/null || true
    stopped_pid=
  fi
}
trap resume_waiter EXIT
if tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
  was_running=1
  [[ "$before_state" == WAITING_FOR_LOAD ]] || {
    echo "REFUSE_UNEXPECTED_WAITER_STATE state=${before_state:-missing}" >&2
    exit 43
  }
  waiter_pid=$(awk -F= '$1 == "pid" {print $2; exit}' "$state_file")
  pane_pid=$(tmux -L "$socket" display-message -p -t "$session" '#{pane_pid}')
  waiter_ppid=$(ps -o ppid= -p "$waiter_pid" 2>/dev/null | tr -d '[:space:]')
  [[ "$waiter_pid" =~ ^[1-9][0-9]*$ && "$pane_pid" =~ ^[1-9][0-9]*$ && "$waiter_ppid" == "$pane_pid" ]] || {
    echo "REFUSE_WAITER_PID_MISMATCH status_pid=${waiter_pid:-missing} parent_pid=${waiter_ppid:-missing} pane_pid=${pane_pid:-missing}" >&2
    exit 48
  }
  kill -STOP "$waiter_pid"
  stopped_pid=$waiter_pid
  for _ in $(seq 1 20); do
    proc_state=$(awk '{print $3}' "/proc/$waiter_pid/stat" 2>/dev/null || true)
    [[ "$proc_state" == T || "$proc_state" == t ]] && break
    sleep 0.05
  done
  [[ "$proc_state" == T || "$proc_state" == t ]] || {
    echo "REFUSE_WAITER_NOT_FROZEN pid=$waiter_pid state=${proc_state:-missing}" >&2
    exit 49
  }
  frozen_state=$(read_state)
  [[ "$frozen_state" == WAITING_FOR_LOAD ]] || {
    echo "REFUSE_WAITER_RACED_AFTER_FREEZE state=${frozen_state:-missing}" >&2
    exit 50
  }
  for cid in "${candidates[@]}"; do
    state=$(run_state "$cid")
    [[ "$state" == ABSENT ]] || {
      echo "REFUSE_REMOTE_RUN_AFTER_FREEZE state=$state candidate=$cid" >&2
      exit 56
    }
  done
  if pgrep -af 'zym_test_(359954|3633872|8787)_pvrig_hotspot.cfg' >/dev/null; then
    echo REFUSE_REMOTE_HADDOCK_PROCESS_AFTER_FREEZE >&2
    exit 57
  fi
  tmux -L "$socket" kill-session -t "$session"
  resume_waiter
fi

exec 9>"$runner_lock"
flock -w 10 9 || { echo REFUSE_RUNNER_LOCK_TIMEOUT >&2; exit 59; }

for _ in $(seq 1 50); do
  if ! tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
    after_state=$(read_state)
    if [[ $was_running -eq 0 || "$after_state" == INTERRUPTED ]]; then
      break
    fi
  fi
  sleep 0.2
done
if tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
  echo REFUSE_WAITER_SESSION_STILL_RUNNING >&2
  exit 44
fi
after_state=$(read_state)
if [[ $was_running -eq 1 && "$after_state" != INTERRUPTED ]]; then
  echo "REFUSE_WAITER_NOT_INTERRUPTED state=${after_state:-missing}" >&2
  exit 45
fi
for cid in "${candidates[@]}"; do
  state=$(run_state "$cid")
  [[ "$state" == ABSENT ]] || {
    echo "REFUSE_REMOTE_RUN_APPEARED state=$state candidate=$cid" >&2
    exit 46
  }
done
if pgrep -af 'zym_test_(359954|3633872|8787)_pvrig_hotspot.cfg' >/dev/null; then
  echo REFUSE_REMOTE_HADDOCK_PROCESS_PRESENT >&2
  exit 47
fi

mkdir -p "$(dirname "$owner_file")"
tmp="$owner_file.tmp.$$"
{
  printf 'owner=local\n'
  printf 'nonce=%s\n' "$nonce"
  printf 'claimed_at=%s\n' "$(date -Is)"
} > "$tmp"
mv "$tmp" "$owner_file"

printf 'CLAIM_REMOTE_STATE=%s\n' "${after_state:-NOT_RUNNING_NO_STATUS}"
printf 'CLAIM_SESSION_RUNNING=0\n'
printf 'CLAIM_WAS_RUNNING=%s\n' "$was_running"
printf 'CLAIM_NONCE=%s\n' "$nonce"
printf 'CLAIM_OWNER_FILE=%s\n' "$owner_file"
for cid in "${candidates[@]}"; do
  printf 'CLAIM_RUN_%s=ABSENT\n' "$cid"
done
'''


REMOTE_VERIFY_SCRIPT = r'''set -euo pipefail
socket=$1
session=$2
root=$3
nonce=$4
owner_file="$root/geometry4_waiter/execution_owner.env"
ownership_lock="$root/geometry4_waiter/ownership.lock"
runner_lock="$root/geometry4_waiter/runner.lock"
candidates=(zym_test_359954 zym_test_3633872 zym_test_8787)

exec 8>"$ownership_lock"
flock -w 10 8 || { echo REFUSE_OWNERSHIP_LOCK_TIMEOUT >&2; exit 56; }
exec 9>"$runner_lock"
flock -w 10 9 || { echo REFUSE_RUNNER_LOCK_TIMEOUT >&2; exit 57; }
tmux -L "$socket" has-session -t "$session" 2>/dev/null && {
  echo REFUSE_WAITER_SESSION_RUNNING >&2
  exit 51
}
[[ -s "$owner_file" ]] || { echo REFUSE_MISSING_OWNER_FILE >&2; exit 52; }
owner=$(awk -F= '$1 == "owner" {print $2; exit}' "$owner_file")
remote_nonce=$(awk -F= '$1 == "nonce" {print $2; exit}' "$owner_file")
[[ "$owner" == local && "$remote_nonce" == "$nonce" ]] || {
  echo REFUSE_OWNER_MISMATCH >&2
  exit 53
}
for cid in "${candidates[@]}"; do
  run="$root/haddock3/$cid/run_${cid}_pvrig_hotspot"
  [[ ! -e "$run" ]] || { echo "REFUSE_REMOTE_RUN_PRESENT candidate=$cid" >&2; exit 54; }
done
if pgrep -af 'zym_test_(359954|3633872|8787)_pvrig_hotspot.cfg' >/dev/null; then
  echo REFUSE_REMOTE_HADDOCK_PROCESS_PRESENT >&2
  exit 55
fi
echo CLAIM_VERIFIED
'''


def parse_claim_output(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("CLAIM_") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise LocalExecutionError(f"duplicate remote claim field: {key}")
        values[key] = value
    required = {
        "CLAIM_REMOTE_STATE",
        "CLAIM_SESSION_RUNNING",
        "CLAIM_WAS_RUNNING",
        "CLAIM_NONCE",
        "CLAIM_OWNER_FILE",
        *(f"CLAIM_RUN_{candidate}" for candidate in CANDIDATES),
    }
    missing = required - set(values)
    if missing:
        raise LocalExecutionError(f"remote claim output is missing fields: {sorted(missing)}")
    return values


def ssh_command(ssh_bin: str, host: str, script: str, nonce: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ssh_bin, host, "bash", "-s", "--", WAITER_SOCKET, WAITER_SESSION, REMOTE_ROOT, nonce],
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def claim_remote_ownership(ssh_bin: str, host: str, nonce: str) -> dict[str, str]:
    result = ssh_command(ssh_bin, host, REMOTE_CLAIM_SCRIPT, nonce, timeout=90)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise LocalExecutionError(f"remote ownership claim failed ({result.returncode}): {detail}")
    claim = parse_claim_output(result.stdout)
    if claim["CLAIM_NONCE"] != nonce or claim["CLAIM_SESSION_RUNNING"] != "0":
        raise LocalExecutionError("remote ownership claim returned inconsistent ownership")
    if any(claim[f"CLAIM_RUN_{candidate}"] != "ABSENT" for candidate in CANDIDATES):
        raise LocalExecutionError("remote ownership claim did not prove all runs absent")
    return claim


def verify_remote_ownership(ssh_bin: str, host: str, nonce: str) -> None:
    result = ssh_command(ssh_bin, host, REMOTE_VERIFY_SCRIPT, nonce, timeout=60)
    if result.returncode != 0 or "CLAIM_VERIFIED" not in result.stdout.splitlines():
        detail = (result.stderr or result.stdout).strip()
        raise LocalExecutionError(f"remote ownership verification failed ({result.returncode}): {detail}")


def create_handoff(
    path: Path,
    host: str,
    nonce: str,
    claim: dict[str, str],
    runtime: dict[str, str],
    inputs: dict[str, dict[str, str]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA,
        "claim_boundary": CLAIM_BOUNDARY,
        "created_at": now_iso(),
        "execution_owner": "local",
        "host": host,
        "nonce": nonce,
        "remote_waiter": {
            "socket": WAITER_SOCKET,
            "session": WAITER_SESSION,
            "state": claim["CLAIM_REMOTE_STATE"],
            "session_running": False,
            "was_running": claim["CLAIM_WAS_RUNNING"] == "1",
            "owner_file": claim["CLAIM_OWNER_FILE"],
        },
        "remote_runs": {candidate: "ABSENT" for candidate in CANDIDATES},
        "local_inputs": inputs,
        "runtime": runtime,
    }
    atomic_json(path, payload)
    return payload


def validate_handoff(
    payload: dict[str, Any],
    host: str,
    inputs: dict[str, dict[str, str]],
    max_age_seconds: int,
) -> str:
    if payload.get("schema_version") != HANDOFF_SCHEMA or payload.get("execution_owner") != "local":
        raise LocalExecutionError("invalid local execution handoff schema or owner")
    if payload.get("claim_boundary") != CLAIM_BOUNDARY or payload.get("host") != host:
        raise LocalExecutionError("handoff claim boundary or host mismatch")
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
        raise LocalExecutionError("handoff nonce is invalid")
    try:
        created = datetime.fromisoformat(str(payload["created_at"]))
    except (KeyError, ValueError) as exc:
        raise LocalExecutionError("handoff creation time is invalid") from exc
    if created.tzinfo is None:
        raise LocalExecutionError("handoff creation time must be timezone-aware")
    age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    if age < -30 or age > max_age_seconds:
        raise LocalExecutionError(f"handoff is stale or future-dated: age_seconds={age:.1f}")
    waiter = payload.get("remote_waiter")
    if not isinstance(waiter, dict) or waiter.get("session_running") is not False:
        raise LocalExecutionError("handoff does not prove the remote waiter stopped")
    remote_runs = payload.get("remote_runs")
    if remote_runs != {candidate: "ABSENT" for candidate in CANDIDATES}:
        raise LocalExecutionError("handoff does not prove all remote run directories absent")
    if payload.get("local_inputs") != inputs:
        raise LocalExecutionError("local inputs changed after ownership handoff")
    return nonce


def execute_local_runs(
    pose_root: Path,
    haddock_bin: Path,
    status_path: Path,
    handoff_path: Path,
) -> None:
    completed: list[str] = []
    write_status(status_path, "RUNNING", "local sequential HADDOCK3 execution started", completed=completed)
    append_event("LOCAL_RUNNER_START", detail=f"handoff={handoff_path}")
    for candidate in CANDIDATES:
        paths = candidate_paths(pose_root, candidate)
        run_dir = paths["run_dir"]
        if run_complete(run_dir):
            completed.append(candidate)
            append_event("HADDOCK_ALREADY_COMPLETE", candidate, str(run_dir))
            continue
        if run_dir.exists():
            raise LocalExecutionError(f"refuse incomplete run before launch: {run_dir}")
        conflicts = find_local_conflicts()
        if conflicts:
            raise LocalExecutionError(f"local execution conflict before {candidate}: {conflicts}")

        log_dir = paths["workdir"] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{candidate}_haddock3_geometry4_local_{datetime.now():%Y%m%d_%H%M%S}.log"
        append_event("HADDOCK_START", candidate, str(log_path))
        write_status(
            status_path,
            "RUNNING",
            f"running {candidate}",
            current_candidate=candidate,
            completed=completed,
            log=str(log_path),
        )
        with log_path.open("w", encoding="utf-8") as log_handle:
            result = subprocess.run(
                [str(haddock_bin), paths["config"].name],
                cwd=paths["workdir"],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode != 0:
            raise LocalExecutionError(f"HADDOCK3 failed for {candidate} with exit {result.returncode}: {log_path}")
        if not run_complete(run_dir):
            raise LocalExecutionError(f"HADDOCK3 output is incomplete for {candidate}: {run_dir}")
        completed.append(candidate)
        append_event("HADDOCK_COMPLETE", candidate, str(run_dir))

    write_status(
        status_path,
        "COMPLETE",
        "all three local Geometry-4 HADDOCK3 runs are complete",
        completed=completed,
        handoff=str(handoff_path),
    )
    append_event("LOCAL_RUNNER_COMPLETE", detail="all_candidates_complete")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="validate local runtime and inputs only (default)")
    mode.add_argument("--claim-and-execute", action="store_true", help="stop/verify Node1 waiter, then run locally")
    mode.add_argument("--execute", action="store_true", help="use a recent handoff and reverify Node1 before running")
    parser.add_argument("--pose-root", type=Path, default=DEFAULT_POSE_ROOT)
    parser.add_argument("--haddock-bin", type=Path, default=DEFAULT_HADDOCK_BIN)
    parser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--host", default="node1")
    parser.add_argument("--ssh-bin", default=None)
    parser.add_argument("--max-handoff-age-seconds", type=int, default=900)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_handoff_age_seconds < 60 or args.max_handoff_age_seconds > 3600:
        raise SystemExit("--max-handoff-age-seconds must be in [60, 3600]")
    args.haddock_bin = args.haddock_bin.resolve()
    args.pose_root = args.pose_root.resolve()
    ssh_bin = args.ssh_bin or shutil.which("ssh.exe") or shutil.which("ssh")

    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("w", encoding="ascii") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LocalExecutionError("another local Geometry-4 launcher owns the execution lock") from exc

        try:
            conflicts = find_local_conflicts()
            if conflicts:
                raise LocalExecutionError(f"local watcher or candidate HADDOCK3 process is active: {conflicts}")
            inputs = validate_local_inputs(args.pose_root)
            runtime = runtime_preflight(args.haddock_bin)

            if not args.claim_and_execute and not args.execute:
                write_status(
                    args.status,
                    "READY_FOR_REMOTE_HANDOFF",
                    "local runtime and all production inputs passed; no execution started",
                    runtime=runtime,
                    local_inputs=inputs,
                )
                print(json.dumps({"state": "READY_FOR_REMOTE_HANDOFF", "runtime": runtime}, sort_keys=True))
                return 0

            if not ssh_bin:
                raise LocalExecutionError("ssh executable is unavailable; remote ownership cannot be proven")
            if args.claim_and_execute:
                nonce = secrets.token_hex(32)
                claim = claim_remote_ownership(ssh_bin, args.host, nonce)
                payload = create_handoff(args.handoff, args.host, nonce, claim, runtime, inputs)
                append_event("REMOTE_OWNERSHIP_CLAIMED", detail=f"host={args.host} nonce={nonce}")
            else:
                if not args.handoff.is_file():
                    raise LocalExecutionError(f"handoff file is missing: {args.handoff}")
                payload = json.loads(args.handoff.read_text(encoding="utf-8"))

            nonce = validate_handoff(payload, args.host, inputs, args.max_handoff_age_seconds)
            verify_remote_ownership(ssh_bin, args.host, nonce)
            append_event("REMOTE_OWNERSHIP_VERIFIED", detail=f"host={args.host} nonce={nonce}")
            execute_local_runs(args.pose_root, args.haddock_bin, args.status, args.handoff)
            print(json.dumps({"state": "COMPLETE", "completed": list(CANDIDATES)}, sort_keys=True))
            return 0
        except (LocalExecutionError, json.JSONDecodeError, subprocess.TimeoutExpired, UnicodeError) as exc:
            write_status(args.status, "FAILED", str(exc))
            append_event("LOCAL_RUNNER_FAILED", detail=str(exc).replace("\t", " ").replace("\n", " "))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            write_status(args.status, "INTERRUPTED", "local launcher interrupted by operator")
            append_event("LOCAL_RUNNER_INTERRUPTED", detail="signal=SIGINT")
            return 130


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
