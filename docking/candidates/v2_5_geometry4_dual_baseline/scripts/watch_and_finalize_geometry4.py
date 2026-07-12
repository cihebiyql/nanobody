#!/usr/bin/env python3
"""Watch the guarded Node1 runs and finish the Geometry-4 cascade safely."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[2]
REPORTS_DIR = PACKAGE_ROOT / "reports"
POSE_ROOT = REPO_ROOT / "docking/candidates/v2_5_pose_batch/remote_sync/haddock3"
POSTPROCESS = PACKAGE_ROOT / "scripts/run_dual_baseline_postprocess.py"
POSTPROCESS_STATUS = REPORTS_DIR / "dual_baseline_postprocess_status.json"
AUDIT_CSV = REPORTS_DIR / "candidate_level_8x6b_9e6y_audit.csv"
FINALIZE_CSV = REPORTS_DIR / "cascade_finalize_docking_summary.csv"
LOCAL_CASCADE_ROOT = (
    REPO_ROOT
    / "data/experiments/phase2_5080_v1/assays/pvrig_v2_5_prospective_v1"
    / "computational_preqc/large_scale_cascade_20260711"
)
REMOTE_POSE_ROOT = "/data/qlyu/projects/pvrig_v2_5_pose_batch"
REMOTE_CASCADE_ROOT = "/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450"
REMOTE_TOOL_ROOT = "/data/qlyu/software/vhh_eval_tools"
REMOTE_FINALIZE_CSV = f"{REMOTE_CASCADE_ROOT}/docking_consensus_geometry4_20260711.csv"
WAITER_SOCKET = "pvrig_v25_geometry4"
WAITER_SESSION = "pvrig_v25_geometry4_waiter"
STATUS_JSON = REPORTS_DIR / "post_waiter_finalize_status.json"
EVENTS_TSV = REPORTS_DIR / "post_waiter_finalize_events.tsv"
LOCK_PATH = PACKAGE_ROOT / ".post_waiter_finalize.lock"

EXPECTED_CANDIDATES = {
    "PV25-EF3F71502C71": "zym_test_359954",
    "PV25-8E96BF37FD37": "zym_test_3633872",
    "PV25-0B63D218E0F3": "zym_test_8787",
    "PV25-25F7D6778F87": "zym_test_108006",
}
PENDING_SOURCE_IDS = ("zym_test_359954", "zym_test_3633872", "zym_test_8787")
ACTIVE_REMOTE_STATES = {"WAITING_FOR_LOAD", "GATE_ACCEPTED", "RUNNING"}
ERROR_REMOTE_STATES = {"TIMED_OUT", "FAILED", "INTERRUPTED"}
FINALIZE_METRICS = (
    "hotspot_overlap_count",
    "total_vhh_pvrl2_residue_pair_occlusion",
    "cdr3_pvrl2_residue_pair_occlusion",
    "cdr3_occlusion_fraction",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ALLOWED_FINAL_LABELS = {
    "FINAL_POSITIVE_HIGH",
    "FINAL_RECHECK_SINGLE_BASELINE",
    "FINAL_POSITIVE_PLAUSIBLE",
    "FINAL_BINDER_NOT_BLOCKER",
    "FINAL_INSUFFICIENT_GEOMETRY",
}
CANONICAL_FINAL_FILES = (
    "CASCADE_RUN_REPORT.md",
    "cascade_state.json",
    "final_blocker_screen.tsv",
    "final_positive_high.fasta",
)


class FinalizeError(RuntimeError):
    """Fail-closed operational error."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            raise FinalizeError(f"malformed status line: {line!r}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise FinalizeError(f"invalid status key: {key!r}")
        if key in values:
            raise FinalizeError(f"duplicate status key: {key}")
        values[key] = value
    return values


def waiter_decision(status: dict[str, str]) -> str:
    state = status.get("state", "")
    session_running = status.get("session_running")
    if state == "COMPLETE":
        return "PROCEED"
    if state in ACTIVE_REMOTE_STATES:
        if session_running != "1":
            raise FinalizeError(f"remote waiter state {state} is stale because its tmux session is absent")
        return "WAIT"
    if state in ERROR_REMOTE_STATES:
        raise FinalizeError(f"remote waiter ended in {state}: {status.get('detail', '-')}")
    raise FinalizeError(f"unknown remote waiter state: {state or 'missing'}")


def run_complete(run_dir: Path) -> bool:
    consensus = run_dir / "traceback/consensus.tsv"
    top_dir = run_dir / "6_seletopclusts"
    return consensus.is_file() and consensus.stat().st_size > 0 and top_dir.is_dir() and any(
        path.is_file() and path.stat().st_size > 0
        for pattern in ("cluster_*_model_*.pdb", "cluster_*_model_*.pdb.gz")
        for path in top_dir.glob(pattern)
    )


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def validate_postprocess_outputs(
    status_json: Path = POSTPROCESS_STATUS,
    audit_csv: Path = AUDIT_CSV,
    finalize_csv: Path = FINALIZE_CSV,
) -> dict[str, object]:
    status = json.loads(status_json.read_text(encoding="utf-8"))
    if status.get("candidate_count") != 4 or status.get("importable_candidate_count") != 4:
        raise FinalizeError("postprocess did not produce four complete importable candidates")
    candidate_status = status.get("candidate_status")
    if not isinstance(candidate_status, list) or len(candidate_status) != 4:
        raise FinalizeError("postprocess candidate_status is incomplete")
    if any(str(row.get("status", "")).startswith("PENDING") for row in candidate_status):
        raise FinalizeError("postprocess still contains PENDING candidates")

    audit_rows = read_csv(audit_csv)
    if {row.get("candidate_id") for row in audit_rows} != set(EXPECTED_CANDIDATES):
        raise FinalizeError("audit candidate IDs do not match the frozen Geometry-4 set")
    classes: dict[str, str] = {}
    for row in audit_rows:
        candidate_id = row["candidate_id"]
        if row.get("source_candidate_id") != EXPECTED_CANDIDATES[candidate_id]:
            raise FinalizeError(f"source mapping mismatch for {candidate_id}")
        if row.get("run_status") != "RUN" or row.get("baseline_count") != "2":
            raise FinalizeError(f"incomplete dual-baseline run for {candidate_id}")
        if row.get("import_status") != "IMPORTED" or row.get("blocker_class") in {"", "INCOMPLETE", "NOT_RUN"}:
            raise FinalizeError(f"non-importable docking evidence for {candidate_id}")
        if any(not row.get(metric, "").strip() for metric in FINALIZE_METRICS):
            raise FinalizeError(f"missing conservative geometry metric for {candidate_id}")
        try:
            source_hashes = json.loads(row.get("source_hashes_json", ""))
        except json.JSONDecodeError as exc:
            raise FinalizeError(f"invalid source hash provenance for {candidate_id}") from exc
        if not isinstance(source_hashes, dict):
            raise FinalizeError(f"source hash provenance is not an object for {candidate_id}")
        input_sequence_sha = source_hashes.get("input_vhh_sequence_sha256")
        manifest_sequence_sha = source_hashes.get("manifest_vhh_seq_sha256")
        if (
            not isinstance(input_sequence_sha, str)
            or not SHA256_PATTERN.fullmatch(input_sequence_sha)
            or not isinstance(manifest_sequence_sha, str)
            or not SHA256_PATTERN.fullmatch(manifest_sequence_sha)
            or input_sequence_sha != manifest_sequence_sha
        ):
            raise FinalizeError(f"VHH sequence provenance mismatch for {candidate_id}")
        payload_json = row.get("payload_json", "")
        if hashlib.sha256(payload_json.encode()).hexdigest() != row.get("payload_sha256"):
            raise FinalizeError(f"candidate payload hash mismatch for {candidate_id}")
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise FinalizeError(f"invalid candidate payload for {candidate_id}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("source_hashes"), dict):
            raise FinalizeError(f"candidate payload provenance is not an object for {candidate_id}")
        payload_hashes = payload.get("source_hashes", {})
        if (
            payload.get("candidate_id") != candidate_id
            or payload.get("source_candidate_id") != EXPECTED_CANDIDATES[candidate_id]
            or payload.get("blocker_class") != row.get("blocker_class")
            or payload_hashes.get("input_vhh_sequence_sha256") != input_sequence_sha
            or payload_hashes.get("manifest_vhh_seq_sha256") != manifest_sequence_sha
        ):
            raise FinalizeError(f"candidate payload provenance mismatch for {candidate_id}")
        classes[candidate_id] = row["blocker_class"]

    finalize_rows = read_csv(finalize_csv)
    if {row.get("candidate_id") for row in finalize_rows} != set(EXPECTED_CANDIDATES):
        raise FinalizeError("finalize CSV does not contain exactly the four frozen candidates")
    if len(finalize_rows) != 4:
        raise FinalizeError("finalize CSV has duplicate or extra rows")
    audit_by_id = {row["candidate_id"]: row for row in audit_rows}
    for row in finalize_rows:
        candidate_id = row["candidate_id"]
        if row != audit_by_id[candidate_id]:
            raise FinalizeError(f"finalize CSV row differs from validated audit row for {candidate_id}")
    actual_sha = sha256_file(finalize_csv)
    if status.get("finalize_csv_sha256") != actual_sha:
        raise FinalizeError("postprocess status hash does not match the finalize CSV")
    return {"candidate_classes": classes, "finalize_csv_sha256": actual_sha}


def validate_cascade_outputs(cascade_dir: Path) -> dict[str, object]:
    state = json.loads((cascade_dir / "cascade_state.json").read_text(encoding="utf-8"))
    finalize_state = state.get("stages", {}).get("finalize", {})
    if finalize_state.get("status") != "complete":
        raise FinalizeError("cascade finalize state is not complete")
    if finalize_state.get("geometry_candidates") != 4 or finalize_state.get("docking_imported") != 4:
        raise FinalizeError("cascade did not import all four Geometry-4 rows")

    rows = read_csv(cascade_dir / "final_blocker_screen.tsv", delimiter="\t")
    if len(rows) != 4 or {row.get("candidate_id") for row in rows} != set(EXPECTED_CANDIDATES):
        raise FinalizeError("final blocker screen does not match the frozen Geometry-4 IDs")
    if any(row.get("docking_evidence_status") != "IMPORTED" for row in rows):
        raise FinalizeError("final blocker screen contains non-imported docking evidence")
    unexpected_labels = {row.get("final_blocker_label", "") for row in rows} - ALLOWED_FINAL_LABELS
    if unexpected_labels:
        raise FinalizeError(f"final blocker screen contains unsupported labels: {sorted(unexpected_labels)}")
    label_counts = dict(Counter(row["final_blocker_label"] for row in rows))
    if finalize_state.get("final_positive_high") != label_counts.get("FINAL_POSITIVE_HIGH", 0):
        raise FinalizeError("cascade state and final label counts disagree")
    return {"label_counts": label_counts, "rows": rows}


def atomic_json(path: Path, payload: dict[str, object]) -> None:
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


def write_status(state: str, detail: str, **extra: object) -> None:
    payload: dict[str, object] = {
        "schema_version": "pvrig_v2_5_geometry4_post_waiter_finalize_v1",
        "updated_at": now_iso(),
        "state": state,
        "detail": detail,
        "pid": os.getpid(),
        "claim_boundary": "computational_geometry_priority_not_experimental_binding_or_blocking_truth",
    }
    payload.update(extra)
    atomic_json(STATUS_JSON, payload)


def emit(event: str, candidate: str = "-", detail: str = "-") -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    clean_detail = detail.replace("\t", " ").replace("\n", " ")
    with EVENTS_TSV.open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()}\t{event}\t{candidate}\t{clean_detail}\n")


def ssh_command(ssh_bin: str, host: str, *remote_args: str) -> list[str]:
    return [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
        host,
        *remote_args,
    ]


def run_ssh_script(ssh_bin: str, host: str, script: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ssh_command(ssh_bin, host, "bash", "-s", "--", *args),
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def read_remote_waiter(ssh_bin: str, host: str) -> dict[str, str]:
    script = r"""
set -euo pipefail
root=$1
socket=$2
session=$3
if tmux -L "$socket" has-session -t "$session" 2>/dev/null; then
  echo session_running=1
else
  echo session_running=0
fi
test -s "$root/geometry4_waiter/status.env"
cat "$root/geometry4_waiter/status.env"
"""
    result = run_ssh_script(
        ssh_bin,
        host,
        script,
        [REMOTE_POSE_ROOT, WAITER_SOCKET, WAITER_SESSION],
        timeout=45,
    )
    if result.returncode != 0:
        raise FinalizeError(f"remote waiter query failed ({result.returncode}): {result.stderr.strip()}")
    return parse_env_text(result.stdout)


def rsync_transport(ssh_bin: str) -> str:
    return " ".join(
        shlex.quote(part)
        for part in (
            ssh_bin,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=4",
        )
    )


def rsync_remote_tree(
    rsync_bin: str,
    ssh_bin: str,
    host: str,
    remote_dir: str,
    local_dir: Path,
    timeout: int = 3600,
) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            rsync_bin,
            "-a",
            "--partial",
            "-e",
            rsync_transport(ssh_bin),
            f"{host}:{remote_dir.rstrip('/')}/",
            f"{local_dir}/",
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise FinalizeError(f"rsync failed for {remote_dir}: {result.stderr.strip()}")


def rsync_remote_file(
    rsync_bin: str,
    ssh_bin: str,
    host: str,
    remote_file: str,
    local_file: Path,
    timeout: int = 300,
) -> None:
    local_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            rsync_bin,
            "-a",
            "--partial",
            "-e",
            rsync_transport(ssh_bin),
            f"{host}:{remote_file}",
            str(local_file),
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise FinalizeError(f"rsync failed for {remote_file}: {result.stderr.strip()}")


def sync_candidate_run(rsync_bin: str, ssh_bin: str, host: str, source_id: str) -> str:
    local_candidate = POSE_ROOT / source_id
    run_name = f"run_{source_id}_pvrig_hotspot"
    final_run = local_candidate / run_name
    if final_run.exists():
        if not run_complete(final_run):
            raise FinalizeError(f"refusing incomplete existing local run: {final_run}")
        emit("LOCAL_RUN_REUSED", source_id, str(final_run))
        return "REUSED_COMPLETE"

    local_candidate.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{run_name}.sync.", dir=local_candidate))
    try:
        remote_run = f"{REMOTE_POSE_ROOT}/haddock3/{source_id}/{run_name}"
        rsync_remote_tree(rsync_bin, ssh_bin, host, remote_run, stage)
        if not run_complete(stage):
            raise FinalizeError(f"synced run is incomplete: {remote_run}")
        if final_run.exists():
            raise FinalizeError(f"local run appeared during sync: {final_run}")
        os.replace(stage, final_run)
        emit("LOCAL_RUN_SYNCED", source_id, str(final_run))
        return "SYNCED_COMPLETE"
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def run_postprocess() -> dict[str, object]:
    log_path = REPORTS_DIR / "post_waiter_dual_baseline_postprocess.log"
    started = now_iso()
    result = subprocess.run(
        [sys.executable, str(POSTPROCESS)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=7200,
        check=False,
    )
    log_path.write_text(
        f"started={started}\nfinished={now_iso()}\nexit_code={result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise FinalizeError(f"dual-baseline postprocess failed; see {log_path}")
    validated = validate_postprocess_outputs()
    emit("POSTPROCESS_COMPLETE", "-", str(validated["finalize_csv_sha256"]))
    return validated


def upload_finalize_csv(ssh_bin: str, host: str, remote_temp: str) -> None:
    remote_command = f"umask 077; cat > {shlex.quote(remote_temp)}"
    with FINALIZE_CSV.open("rb") as handle:
        result = subprocess.run(
            ssh_command(ssh_bin, host, remote_command),
            stdin=handle,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise FinalizeError(f"finalize CSV upload failed ({result.returncode}): {stderr}")


REMOTE_FINALIZE_SCRIPT = r"""
set -euo pipefail
run_root=$1
tool_root=$2
incoming=$3
target=$4
expected_sha=$5
stamp=$6
expected_ids=$7

exec 9>"$run_root/.geometry4_complete_finalize.lock"
if ! flock -n 9; then
  echo "remote finalize lock is busy" >&2
  exit 42
fi

test -s "$incoming"
actual_sha=$(sha256sum "$incoming" | cut -d ' ' -f1)
if [[ "$actual_sha" != "$expected_sha" ]]; then
  echo "uploaded finalize hash mismatch" >&2
  exit 43
fi

validate_cascade() {
  python3 - "$1" "$expected_ids" <<'PY'
import csv
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
expected = set(sys.argv[2].split(','))
allowed = {
    'FINAL_POSITIVE_HIGH',
    'FINAL_RECHECK_SINGLE_BASELINE',
    'FINAL_POSITIVE_PLAUSIBLE',
    'FINAL_BINDER_NOT_BLOCKER',
    'FINAL_INSUFFICIENT_GEOMETRY',
}
state = json.loads((root / 'cascade_state.json').read_text())['stages']['finalize']
with (root / 'final_blocker_screen.tsv').open(newline='', encoding='utf-8-sig') as handle:
    rows = list(csv.DictReader(handle, delimiter='\t'))
if state.get('status') != 'complete' or state.get('geometry_candidates') != 4 or state.get('docking_imported') != 4:
    raise SystemExit('invalid finalized cascade state')
if len(rows) != 4 or {row.get('candidate_id') for row in rows} != expected:
    raise SystemExit('final blocker screen candidate mismatch')
if any(row.get('docking_evidence_status') != 'IMPORTED' for row in rows):
    raise SystemExit('non-imported docking evidence remains')
labels = {row.get('final_blocker_label', '') for row in rows}
if not labels <= allowed:
    raise SystemExit(f'unsupported final labels: {sorted(labels - allowed)}')
counts = Counter(row['final_blocker_label'] for row in rows)
if state.get('final_positive_high') != counts.get('FINAL_POSITIVE_HIGH', 0):
    raise SystemExit('final label count mismatch')
print(json.dumps({'label_counts': dict(counts)}, sort_keys=True))
PY
}

already_complete=0
if [[ -s "$target" ]] && [[ "$(sha256sum "$target" | cut -d ' ' -f1)" == "$expected_sha" ]]; then
  if validate_cascade "$run_root/cascade" >/dev/null 2>&1; then
    already_complete=1
  fi
fi

mode=REUSED
snapshot=-
stage_archive=-
log=-
if [[ $already_complete -eq 1 ]]; then
  rm -f "$incoming"
else
  live="$run_root/cascade"
  stage="$run_root/.cascade_geometry4_stage_$stamp"
  stage_archive="$run_root/geometry4_complete_finalize_stage_$stamp"
  snapshot="$run_root/pre_geometry4_complete_finalize_$stamp"
  if [[ -e "$stage" || -e "$stage_archive" || -e "$snapshot" ]]; then
    echo "refusing existing remote stage or snapshot for stamp $stamp" >&2
    exit 44
  fi
  cp -a "$live" "$stage"

  log="$run_root/finalize_geometry4_complete_$stamp.log"
  status_file="$run_root/finalize_geometry4_complete_${stamp}_status.txt"
  started=$(date -Is)
  set +e
  "$tool_root/bin/vhh-large-scale-screen" \
    "$run_root/panel_blinded.fasta" \
    -o "$stage" \
    --stage finalize \
    --docking-summary "$incoming" >"$log" 2>&1
  code=$?
  set -e
  printf 'started=%s\nfinished=%s\nexit_code=%s\n' "$started" "$(date -Is)" "$code" > "$status_file"
  if [[ $code -ne 0 ]]; then
    echo "remote cascade finalize failed; see $log" >&2
    exit "$code"
  fi

  sed -i "s|$stage|$live|g" "$stage/CASCADE_RUN_REPORT.md"
  validate_cascade "$stage"

  mkdir -p "$snapshot"
  for name in CASCADE_RUN_REPORT.md cascade_state.json final_blocker_screen.tsv final_positive_high.fasta; do
    if [[ -e "$live/$name" ]]; then
      cp -a "$live/$name" "$snapshot/$name"
    fi
    cp -a "$stage/$name" "$live/.geometry4_publish_${stamp}_$name"
  done
  if [[ -e "$target" ]]; then
    cp -a "$target" "$snapshot/$(basename "$target")"
  fi
  mv "$stage" "$stage_archive"

  rollback_publish() {
    rc=$?
    trap - ERR
    set +e
    for name in CASCADE_RUN_REPORT.md final_blocker_screen.tsv final_positive_high.fasta cascade_state.json; do
      if [[ -e "$snapshot/$name" ]]; then
        cp -a "$snapshot/$name" "$live/.geometry4_rollback_${stamp}_$name"
        mv "$live/.geometry4_rollback_${stamp}_$name" "$live/$name"
      else
        rm -f "$live/$name"
      fi
    done
    if [[ -e "$snapshot/$(basename "$target")" ]]; then
      cp -a "$snapshot/$(basename "$target")" "$target.rollback.$stamp"
      mv "$target.rollback.$stamp" "$target"
    else
      rm -f "$target"
    fi
    exit "$rc"
  }
  trap rollback_publish ERR

  mv "$live/.geometry4_publish_${stamp}_final_blocker_screen.tsv" "$live/final_blocker_screen.tsv"
  mv "$live/.geometry4_publish_${stamp}_final_positive_high.fasta" "$live/final_positive_high.fasta"
  mv "$live/.geometry4_publish_${stamp}_CASCADE_RUN_REPORT.md" "$live/CASCADE_RUN_REPORT.md"
  mv "$incoming" "$target"
  mv "$live/.geometry4_publish_${stamp}_cascade_state.json" "$live/cascade_state.json"
  validate_cascade "$live"
  trap - ERR
  mode=FINALIZED
fi

validate_cascade "$run_root/cascade"

echo "remote_finalize_mode=$mode"
echo "remote_snapshot=$snapshot"
echo "remote_stage_archive=$stage_archive"
echo "remote_finalize_log=$log"
echo "remote_finalize_sha256=$expected_sha"
"""


def remote_finalize(ssh_bin: str, host: str, stamp: str, expected_sha: str) -> str:
    remote_temp = f"{REMOTE_FINALIZE_CSV}.tmp.{os.getpid()}.{stamp}"
    upload_finalize_csv(ssh_bin, host, remote_temp)
    result = run_ssh_script(
        ssh_bin,
        host,
        REMOTE_FINALIZE_SCRIPT,
        [
            REMOTE_CASCADE_ROOT,
            REMOTE_TOOL_ROOT,
            remote_temp,
            REMOTE_FINALIZE_CSV,
            expected_sha,
            stamp,
            ",".join(sorted(EXPECTED_CANDIDATES)),
        ],
        timeout=1800,
    )
    log_path = REPORTS_DIR / f"post_waiter_remote_finalize_{stamp}.log"
    log_path.write_text(
        f"exit_code={result.returncode}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise FinalizeError(f"remote cascade finalize failed; see {log_path}")
    emit("REMOTE_FINALIZE_COMPLETE", "-", expected_sha)
    return result.stdout


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(fd)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sync_final_cascade(
    rsync_bin: str,
    ssh_bin: str,
    host: str,
    stamp: str,
    expected_sha: str,
    remote_finalize_output: str,
) -> tuple[Path, dict[str, object]]:
    LOCAL_CASCADE_ROOT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".geometry4_complete_finalize.", dir=LOCAL_CASCADE_ROOT))
    destination = LOCAL_CASCADE_ROOT / f"geometry4_complete_finalize_{stamp}"
    try:
        cascade_stage = stage / "cascade"
        rsync_remote_tree(
            rsync_bin,
            ssh_bin,
            host,
            f"{REMOTE_CASCADE_ROOT}/cascade",
            cascade_stage,
            timeout=600,
        )
        synced_finalize = stage / "docking_consensus_geometry4_20260711.csv"
        rsync_remote_file(rsync_bin, ssh_bin, host, REMOTE_FINALIZE_CSV, synced_finalize)
        if sha256_file(synced_finalize) != expected_sha:
            raise FinalizeError("synced remote finalize CSV hash mismatch")
        validated = validate_cascade_outputs(cascade_stage)
        (stage / "remote_finalize.log").write_text(remote_finalize_output, encoding="utf-8")
        atomic_json(
            stage / "snapshot_metadata.json",
            {
                "schema_version": "pvrig_v2_5_geometry4_complete_finalize_snapshot_v1",
                "created_at": now_iso(),
                "immutable": True,
                "finalize_csv_sha256": expected_sha,
                "label_counts": validated["label_counts"],
                "artifact_sha256": {
                    "cascade_state.json": sha256_file(cascade_stage / "cascade_state.json"),
                    "final_blocker_screen.tsv": sha256_file(cascade_stage / "final_blocker_screen.tsv"),
                    "final_positive_high.fasta": sha256_file(cascade_stage / "final_positive_high.fasta"),
                    "docking_consensus_geometry4_20260711.csv": sha256_file(synced_finalize),
                },
                "claim_boundary": "computational_geometry_priority_not_experimental_binding_or_blocking_truth",
            },
        )
        if destination.exists():
            raise FinalizeError(f"refusing existing local snapshot: {destination}")
        os.replace(stage, destination)

        canonical = LOCAL_CASCADE_ROOT / "cascade"
        for name in CANONICAL_FINAL_FILES:
            atomic_copy(destination / "cascade" / name, canonical / name)
        validate_cascade_outputs(canonical)
        emit("LOCAL_CASCADE_SYNCED", "-", str(destination))
        return destination, validated
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def default_ssh_bin() -> str:
    override = os.environ.get("GEOMETRY4_SSH_BIN")
    if override:
        return override
    return shutil.which("ssh.exe") or shutil.which("ssh") or "ssh"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--watch", action="store_true", help="wait for COMPLETE, then sync and finalize")
    mode.add_argument("--once", action="store_true", help="query once; proceed only if already COMPLETE")
    mode.add_argument("--status", action="store_true", help="print local and remote status without changing outputs")
    parser.add_argument("--host", default=os.environ.get("GEOMETRY4_SSH_HOST", "node1"))
    parser.add_argument("--ssh-bin", default=default_ssh_bin())
    parser.add_argument("--rsync-bin", default=shutil.which("rsync") or "rsync")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-wait-seconds", type=int, default=90000)
    parser.add_argument("--max-ssh-errors", type=int, default=10)
    args = parser.parse_args(argv)
    if args.poll_seconds < 10:
        parser.error("--poll-seconds must be >= 10")
    if args.max_wait_seconds < args.poll_seconds:
        parser.error("--max-wait-seconds must be >= --poll-seconds")
    if args.max_ssh_errors < 1:
        parser.error("--max-ssh-errors must be >= 1")
    return args


def print_status(args: argparse.Namespace) -> int:
    remote = read_remote_waiter(args.ssh_bin, args.host)
    local: object = None
    if STATUS_JSON.is_file():
        local = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    print(json.dumps({"remote_waiter": remote, "local_finalizer": local}, indent=2, sort_keys=True))
    return 0


def wait_until_complete(args: argparse.Namespace) -> dict[str, str] | None:
    deadline = time.monotonic() + args.max_wait_seconds
    consecutive_errors = 0
    while True:
        if time.monotonic() >= deadline:
            raise FinalizeError("local post-waiter watcher exceeded its bounded wait")
        try:
            remote = read_remote_waiter(args.ssh_bin, args.host)
            consecutive_errors = 0
        except (FinalizeError, subprocess.TimeoutExpired) as exc:
            consecutive_errors += 1
            emit("REMOTE_STATUS_ERROR", "-", f"attempt={consecutive_errors} {exc}")
            write_status("REMOTE_STATUS_RETRY", str(exc), consecutive_errors=consecutive_errors)
            if consecutive_errors >= args.max_ssh_errors:
                raise FinalizeError(f"remote status failed {consecutive_errors} consecutive times") from exc
            if args.once:
                return None
            time.sleep(args.poll_seconds)
            continue

        decision = waiter_decision(remote)
        if decision == "PROCEED":
            write_status("REMOTE_COMPLETE", "starting guarded local sync", remote_waiter=remote)
            emit("REMOTE_WAITER_COMPLETE", "-", remote.get("updated_at", "-"))
            return remote
        write_status("WAITING_FOR_REMOTE", "Node1 load gate or docking is still active", remote_waiter=remote)
        emit("REMOTE_WAITER_WAIT", remote.get("candidate", "-"), f"state={remote.get('state')} load1={remote.get('load1')}")
        if args.once:
            return None
        time.sleep(args.poll_seconds)


def execute(args: argparse.Namespace) -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="ascii") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FinalizeError("another post-waiter finalizer already holds the local lock")

        write_status("STARTING", "querying guarded Node1 waiter")
        emit("FINALIZER_START", "-", f"mode={'once' if args.once else 'watch'}")
        remote = wait_until_complete(args)
        if remote is None:
            return 10

        sync_status = {
            source_id: sync_candidate_run(args.rsync_bin, args.ssh_bin, args.host, source_id)
            for source_id in PENDING_SOURCE_IDS
        }
        write_status("RUNS_SYNCED", "all pending HADDOCK3 runs are complete locally", sync_status=sync_status)
        postprocess = run_postprocess()
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        expected_sha = str(postprocess["finalize_csv_sha256"])
        write_status("FINALIZING_REMOTE", "uploading four-candidate docking summary", finalize_csv_sha256=expected_sha)
        remote_output = remote_finalize(args.ssh_bin, args.host, stamp, expected_sha)
        snapshot, cascade = sync_final_cascade(
            args.rsync_bin,
            args.ssh_bin,
            args.host,
            stamp,
            expected_sha,
            remote_output,
        )
        write_status(
            "COMPLETE",
            "four-candidate dual-baseline docking and cascade finalize are verified",
            remote_waiter=remote,
            sync_status=sync_status,
            candidate_classes=postprocess["candidate_classes"],
            finalize_csv_sha256=expected_sha,
            local_cascade_snapshot=str(snapshot),
            final_label_counts=cascade["label_counts"],
        )
        emit("FINALIZER_COMPLETE", "-", str(snapshot))
        return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.status:
        return print_status(args)

    interrupted: dict[str, str] = {}

    def handle_signal(signum: int, _frame: object) -> None:
        interrupted["signal"] = signal.Signals(signum).name
        raise KeyboardInterrupt

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)

    try:
        return execute(args)
    except KeyboardInterrupt:
        signal_name = interrupted.get("signal", "INTERRUPT")
        write_status("INTERRUPTED", f"received {signal_name}")
        emit("FINALIZER_INTERRUPTED", "-", signal_name)
        return 130
    except (FinalizeError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        write_status("FAILED", str(exc))
        emit("FINALIZER_FAILED", "-", str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
