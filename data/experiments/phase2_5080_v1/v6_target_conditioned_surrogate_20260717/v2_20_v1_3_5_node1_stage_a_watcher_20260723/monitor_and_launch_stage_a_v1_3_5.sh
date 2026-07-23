#!/usr/bin/env bash
set -euo pipefail

WORKTREE="/mnt/d/work/抗体/data"
BASE="$WORKTREE/experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717"
PACKAGE="$BASE/v2_20_contact_shared_top5_challenger_v1_3_5_technical_recovery_20260723"
APPROVAL="$WORKTREE/reports/pvrig_v220_v135_python311_bxcpu_tests_v1_20260723/INDEPENDENT_STAGE_A_APPROVAL_V1_3_5.json"
STATE_ROOT="$BASE/v2_20_v1_3_5_node1_stage_a_watcher_20260723/runtime"

EXPECTED_FREEZE_SHA="07c8463689d6baa0da1ebd0c1d4440fc0315c8e8edb4e1b72415434567dc0804"
EXPECTED_APPROVAL_SHA="91fc04f0cbe2441c76318eac20ba0f41b8525eca1a27bd24465a0963613c97c8"
FREEZE_NAME="IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_5.json"

SSH="/mnt/c/Windows/System32/OpenSSH/ssh.exe"
SSH_CONFIG='C:\Users\ciheb\.ssh\config'
SSH_ARGS=(-F "$SSH_CONFIG" -o BatchMode=yes -o ConnectTimeout=10 node1)

REMOTE_PACKAGE="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_technical_recovery_20260723"
REMOTE_RUNTIME="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_preflight_runtime_20260723"
REMOTE_EVIDENCE="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_stage_a_evidence_20260723"
REMOTE_SESSION="v220_v135_stagea_preflight"
POLL_SECONDS="${POLL_SECONDS:-60}"

mkdir -p "$STATE_ROOT"
STATUS="$STATE_ROOT/WATCHER_STATUS.json"
LOG="$STATE_ROOT/WATCHER.log"

write_status() {
  local status="$1"
  local detail="$2"
  local temporary="$STATUS.tmp.$$"
  python3 - "$temporary" "$status" "$detail" <<'PY'
import datetime
import json
import sys

path, status, detail = sys.argv[1:]
payload = {
    "schema_version": "pvrig.v220.v1_3_5.node1_stage_a_watcher.v1",
    "status": status,
    "detail": detail,
    "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "training_authorized": False,
    "training_started": False,
    "claim_boundary": "Stage-A technical no-training deployment/preflight monitor only.",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
  mv "$temporary" "$STATUS"
}

verify_local_package() {
  printf '%s  %s\n' "$EXPECTED_FREEZE_SHA" "$PACKAGE/$FREEZE_NAME" | sha256sum -c -
  printf '%s  %s\n' "$EXPECTED_APPROVAL_SHA" "$APPROVAL" | sha256sum -c -
  python3 - "$PACKAGE" "$FREEZE_NAME" "$APPROVAL" "$EXPECTED_APPROVAL_SHA" "$EXPECTED_FREEZE_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
freeze_name = sys.argv[2]
approval_path = Path(sys.argv[3]).resolve(strict=True)
expected_approval_sha = sys.argv[4]
expected_freeze_sha = sys.argv[5]
freeze = json.loads((root / freeze_name).read_text())
assert freeze["training_authorized"] is False
assert freeze["training_started"] is False
expected = set(freeze["package_file_allowlist"])
observed = set()
for path in root.rglob("*"):
    relative = str(path.relative_to(root))
    assert not path.is_symlink(), f"symlink:{relative}"
    assert path.name != "__pycache__" and path.suffix != ".pyc", f"cache:{relative}"
    if path.is_file():
        observed.add(relative)
assert observed == expected, (sorted(observed - expected), sorted(expected - observed))
assert set(freeze["implementation_hashes"]) == expected - {
    freeze_name,
    freeze_name + ".sha256",
}
for relative, expected_sha in freeze["implementation_hashes"].items():
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    assert actual == expected_sha, relative
approval_raw = approval_path.read_bytes()
assert hashlib.sha256(approval_raw).hexdigest() == expected_approval_sha
approval = json.loads(approval_raw)
assert approval["status"] == "PASS_V1_3_5_INDEPENDENT_REVIEW_STAGE_A_PREFLIGHT_ONLY_AUTHORIZED"
auth = approval["authorization"]
assert auth["independent_review_passed"] is True
assert auth["node1_stage_a_preflight_execution_authorized"] is True
assert auth["stage_a_only_package_deployment_authorized"] is True
assert auth["training_authorized"] is False
assert auth["training_started"] is False
assert approval["implementation_freeze_sha256"] == expected_freeze_sha
PY
}

remote_available() {
  "$SSH" "${SSH_ARGS[@]}" true >/dev/null 2>&1
}

choose_gpu() {
  "$SSH" "${SSH_ARGS[@]}" \
    "nvidia-smi --query-gpu=index,memory.free,utilization.gpu --format=csv,noheader,nounits" \
    | awk -F',' '
        {
          gsub(/ /, "", $1); gsub(/ /, "", $2); gsub(/ /, "", $3)
          if ($1 >= 1 && $1 <= 7 && $2 >= 12000) print $1, $2, $3
        }
      ' \
    | sort -k2,2nr -k3,3n \
    | awk 'NR == 1 {print $1}'
}

deploy_exact_package() {
  local parent base
  parent="$(dirname "$PACKAGE")"
  base="$(basename "$PACKAGE")"
  "$SSH" "${SSH_ARGS[@]}" \
    "test ! -e '$REMOTE_PACKAGE' && test ! -e '$REMOTE_RUNTIME' && test ! -e '$REMOTE_EVIDENCE'"
  tar -C "$parent" --exclude='__pycache__' --exclude='*.pyc' -cf - "$base" \
    | "$SSH" "${SSH_ARGS[@]}" \
      "set -e; mkdir -m 700 '$REMOTE_PACKAGE'; tar -xf - --strip-components=1 -C '$REMOTE_PACKAGE'"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -e; cd '$REMOTE_PACKAGE'; printf '%s  %s\n' '$EXPECTED_FREEZE_SHA' '$FREEZE_NAME' | sha256sum -c -; python3 - '$REMOTE_PACKAGE' '$FREEZE_NAME' <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True); freeze_name=sys.argv[2]
freeze=json.loads((root/freeze_name).read_text())
expected=set(freeze['package_file_allowlist']); observed=set()
for path in root.rglob('*'):
    relative=str(path.relative_to(root))
    assert not path.is_symlink(), relative
    assert path.name != '__pycache__' and path.suffix != '.pyc', relative
    if path.is_file(): observed.add(relative)
assert observed==expected,(sorted(observed-expected),sorted(expected-observed))
assert set(freeze['implementation_hashes'])==expected-{freeze_name,freeze_name+'.sha256'}
for relative,digest in freeze['implementation_hashes'].items():
    assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest,relative
print('PASS_REMOTE_EXACT_V1_3_5_PACKAGE')
PY"
}

launch_preflight() {
  local gpu="$1"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -e; ! tmux has-session -t '$REMOTE_SESSION' 2>/dev/null; mkdir -m 700 '$REMOTE_EVIDENCE'; tmux new-session -d -s '$REMOTE_SESSION' \"cd '$REMOTE_PACKAGE' && CUDA_VISIBLE_DEVICES='$gpu' OMP_NUM_THREADS=4 ./launchers/run_phase1_preflight_node1_v1_3_5.sh '$REMOTE_RUNTIME' '$REMOTE_PACKAGE/$FREEZE_NAME' '$EXPECTED_FREEZE_SHA' > '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.log' 2>&1; rc=\\\$?; printf '%s\\n' \\\$rc > '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.rc'; exit \\\$rc\"; tmux has-session -t '$REMOTE_SESSION' 2>/dev/null || test -f '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.rc'"
}

monitor_terminal() {
  while true; do
    if ! remote_available; then
      write_status "WAITING_NODE1_AFTER_LAUNCH" "preflight launched; SSH temporarily unavailable"
      sleep "$POLL_SECONDS"
      continue
    fi
    if "$SSH" "${SSH_ARGS[@]}" "tmux has-session -t '$REMOTE_SESSION' 2>/dev/null"; then
      write_status "RUNNING_NODE1_STAGE_A_PREFLIGHT" "exact V1.3.5 Stage-A preflight is running; no training authorized"
      sleep "$POLL_SECONDS"
      continue
    fi
    local rc
    rc="$($SSH "${SSH_ARGS[@]}" "cat '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.rc' 2>/dev/null || printf missing")"
    if [[ "$rc" == "0" ]]; then
      "$SSH" "${SSH_ARGS[@]}" "cat '$REMOTE_RUNTIME/NODE1_V1_3_5_PREFLIGHT_RECEIPT.json'" \
        > "$STATE_ROOT/NODE1_V1_3_5_PREFLIGHT_RECEIPT.json"
      "$SSH" "${SSH_ARGS[@]}" "cat '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.log'" \
        > "$STATE_ROOT/PREFLIGHT_LAUNCHER.log"
      write_status "PASS_NODE1_STAGE_A_PREFLIGHT_WAITING_INDEPENDENT_STAGE_B_REVIEW" \
        "Node1 exact tests and five-fold no-training preflight completed; training remains unauthorized"
      return 0
    fi
    "$SSH" "${SSH_ARGS[@]}" "cat '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.log' 2>/dev/null || true" \
      > "$STATE_ROOT/PREFLIGHT_LAUNCHER.log"
    write_status "FAIL_NODE1_STAGE_A_PREFLIGHT_NO_RETRY" "terminal rc=$rc; no training was authorized"
    return 1
  done
}

exec >>"$LOG" 2>&1
printf 'watcher_started_utc=%s\n' "$(date -u +%FT%TZ)"
verify_local_package

while ! remote_available; do
  write_status "WAITING_NODE1_CONNECTIVITY" "campus-WLAN SSH proxy unavailable; exact package remains local and immutable"
  sleep "$POLL_SECONDS"
done

write_status "NODE1_CONNECTED_PREDEPLOY" "validating fresh remote paths and GPU capacity"
gpu=""
while [[ -z "$gpu" ]]; do
  if ! gpu="$(choose_gpu 2>/dev/null)"; then
    gpu=""
    write_status "WAITING_NODE1_CONNECTIVITY" "SSH dropped while selecting a Stage-A GPU; no deployment attempted"
    sleep "$POLL_SECONDS"
    continue
  fi
  if [[ -z "$gpu" ]]; then
    write_status "WAITING_NODE1_GPU_CAPACITY" "requires one qlyu GPU index 1-7 with at least 12000 MiB free"
    sleep "$POLL_SECONDS"
  fi
done

deploy_exact_package
write_status "PASS_REMOTE_PACKAGE_DEPLOYED" "exact frozen package deployed; launching no-training Stage-A on physical GPU $gpu"
launch_preflight "$gpu"
write_status "RUNNING_NODE1_STAGE_A_PREFLIGHT" "physical GPU $gpu; training remains unauthorized"
monitor_terminal
