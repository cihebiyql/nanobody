#!/usr/bin/env bash
set -euo pipefail

WORKTREE="/mnt/d/work/抗体/data"
BASE="$WORKTREE/experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717"
ROOT="$BASE/v2_20_v1_3_5_node1_stage_a_watcher_v2_20260723"
PACKAGE="$BASE/v2_20_contact_shared_top5_challenger_v1_3_5_technical_recovery_20260723"
APPROVAL="$WORKTREE/reports/pvrig_v220_v135_python311_bxcpu_tests_v1_20260723/INDEPENDENT_STAGE_A_APPROVAL_V1_3_5.json"
STATE_ROOT="$ROOT/runtime"

VERIFY="$ROOT/verify_frozen_package_v2.py"
PROBE="$ROOT/probe_node1_stage_a_state_v2.py"
CLASSIFY="$ROOT/classify_node1_stage_a_state_v2.py"
VALIDATE_SESSION="$ROOT/validate_node1_stage_a_session_v2.py"
PROVE="$ROOT/prove_remote_stage_a_artifacts_v2.py"
VALIDATE="$ROOT/validate_node1_stage_a_receipt_v2.py"
ENTRYPOINT="$ROOT/remote_stage_a_entrypoint_v2.sh"

EXPECTED_FREEZE_SHA="07c8463689d6baa0da1ebd0c1d4440fc0315c8e8edb4e1b72415434567dc0804"
EXPECTED_APPROVAL_SHA="91fc04f0cbe2441c76318eac20ba0f41b8525eca1a27bd24465a0963613c97c8"
EXPECTED_PREREG_SHA="574919e65f7079475c17294e297327ce311910ced12656e34640e1fa4a5b9562"
FREEZE_NAME="IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_5.json"

SSH="/mnt/c/Windows/System32/OpenSSH/ssh.exe"
SSH_CONFIG='C:\Users\ciheb\.ssh\config'
SSH_ARGS=(-F "$SSH_CONFIG" -o BatchMode=yes -o ConnectTimeout=10 node1)

REMOTE_PACKAGE="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_technical_recovery_watcher_v2_20260723"
REMOTE_RUNTIME="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_preflight_runtime_v2_20260723"
REMOTE_EVIDENCE="/data1/qlyu/projects/pvrig_v2_20_phase1_core_oof_v1_3_5_stage_a_evidence_v2_20260723"
REMOTE_SESSION="v220_v135_stagea_preflight_v2"
REMOTE_PARENT="$(dirname "$REMOTE_PACKAGE")"
REMOTE_STAGE="$REMOTE_PARENT/.pvrig_v220_v135_stagea_package.${EXPECTED_FREEZE_SHA:0:16}.stage"
REMOTE_READY_ARCHIVE="$REMOTE_PARENT/.pvrig_v220_v135_stagea_package.${EXPECTED_FREEZE_SHA:0:16}.tar.ready"
REMOTE_PARTIAL_ARCHIVE="$REMOTE_READY_ARCHIVE.partial"
REMOTE_ENTRYPOINT="$REMOTE_PARENT/.pvrig_v220_v135_stagea_entrypoint_v2.sh"

POLL_SECONDS="${POLL_SECONDS:-60}"
STATUS="$STATE_ROOT/WATCHER_STATUS.json"
LOG="$STATE_ROOT/WATCHER.log"
SNAPSHOT="$STATE_ROOT/REMOTE_SNAPSHOT.json"
ARCHIVE="$STATE_ROOT/FROZEN_PACKAGE.tar"

mkdir -p "$STATE_ROOT"
exec >>"$LOG" 2>&1

write_status() {
  local status="$1" detail="$2" temporary="$STATUS.tmp.$$"
  python3 - "$temporary" "$status" "$detail" <<'PY'
import datetime,json,sys
path,status,detail=sys.argv[1:]
payload={
  "schema_version":"pvrig.v220.v1_3_5.node1_stage_a_watcher.v2",
  "status":status,
  "detail":detail,
  "updated_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "training_authorized":False,
  "training_started":False,
  "claim_boundary":"Disconnect-resumable Stage-A package deployment and no-training preflight only.",
}
with open(path,"w",encoding="utf-8") as handle:
  json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n")
PY
  mv "$temporary" "$STATUS"
}

remote_available() {
  "$SSH" "${SSH_ARGS[@]}" true >/dev/null 2>&1
}

verify_local_inputs() {
  python3 "$VERIFY" \
    --package-root "$PACKAGE" \
    --expected-freeze-sha256 "$EXPECTED_FREEZE_SHA" \
    --approval "$APPROVAL" \
    --expected-approval-sha256 "$EXPECTED_APPROVAL_SHA" \
    --expected-preregistration-sha256 "$EXPECTED_PREREG_SHA"
}

build_deterministic_archive() {
  local temporary="$ARCHIVE.tmp.$$" parent base
  parent="$(dirname "$PACKAGE")"; base="$(basename "$PACKAGE")"
  tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
      --format=gnu -C "$parent" -cf "$temporary" "$base"
  if [[ -e "$ARCHIVE" ]]; then
    cmp -s "$temporary" "$ARCHIVE" || {
      rm -f "$temporary"
      echo "nondeterministic_or_changed_local_archive" >&2
      return 65
    }
    rm -f "$temporary"
  else
    mv "$temporary" "$ARCHIVE"
  fi
  [[ -f "$ARCHIVE" && ! -L "$ARCHIVE" ]]
}

probe_remote() {
  local temporary="$SNAPSHOT.tmp.$$"
  if ! "$SSH" "${SSH_ARGS[@]}" \
      "python3 - --package '$REMOTE_PACKAGE' --stage '$REMOTE_STAGE' --ready-archive '$REMOTE_READY_ARCHIVE' --partial-archive '$REMOTE_PARTIAL_ARCHIVE' --runtime '$REMOTE_RUNTIME' --evidence '$REMOTE_EVIDENCE' --session '$REMOTE_SESSION'" \
      < "$PROBE" > "$temporary"; then
    rm -f "$temporary"
    return 1
  fi
  python3 -m json.tool "$temporary" >/dev/null
  mv "$temporary" "$SNAPSHOT"
}

classify_snapshot() {
  python3 "$CLASSIFY" --snapshot "$SNAPSHOT"
}

verify_remote_package_path() {
  local path="$1"
  "$SSH" "${SSH_ARGS[@]}" \
    "python3 - --package-root '$path' --expected-freeze-sha256 '$EXPECTED_FREEZE_SHA'" \
    < "$VERIFY"
}

verify_remote_ready_archive() {
  local archive_sha
  archive_sha="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; test -f '$REMOTE_READY_ARCHIVE' && test ! -L '$REMOTE_READY_ARCHIVE'; printf '%s  %s\n' '$archive_sha' '$REMOTE_READY_ARCHIVE' | sha256sum -c -"
}

upload_archive_atomically() {
  local archive_sha
  archive_sha="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; umask 077; mkdir -p '$REMOTE_PARENT'; cat > '$REMOTE_PARTIAL_ARCHIVE'; printf '%s  %s\n' '$archive_sha' '$REMOTE_PARTIAL_ARCHIVE' | sha256sum -c -; if test -e '$REMOTE_READY_ARCHIVE'; then test -f '$REMOTE_READY_ARCHIVE' && test ! -L '$REMOTE_READY_ARCHIVE'; printf '%s  %s\n' '$archive_sha' '$REMOTE_READY_ARCHIVE' | sha256sum -c -; rm -f '$REMOTE_PARTIAL_ARCHIVE'; else mv '$REMOTE_PARTIAL_ARCHIVE' '$REMOTE_READY_ARCHIVE'; fi" \
    < "$ARCHIVE"
}

extract_ready_archive_atomically() {
  verify_remote_ready_archive
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; test ! -e '$REMOTE_PACKAGE'; test ! -e '$REMOTE_STAGE'; test ! -e '$REMOTE_PARTIAL_ARCHIVE' || { test -f '$REMOTE_PARTIAL_ARCHIVE' && test ! -L '$REMOTE_PARTIAL_ARCHIVE' && rm -f '$REMOTE_PARTIAL_ARCHIVE'; }; work='$REMOTE_STAGE.work.\$\$'; test ! -e \"\$work\"; mkdir -m 700 \"\$work\"; trap 'rm -rf \"\$work\"' EXIT; tar -xf '$REMOTE_READY_ARCHIVE' --strip-components=1 -C \"\$work\"; mv \"\$work\" '$REMOTE_STAGE'; trap - EXIT"
  verify_remote_package_path "$REMOTE_STAGE"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; test ! -e '$REMOTE_PACKAGE'; test -d '$REMOTE_STAGE' && test ! -L '$REMOTE_STAGE'; mv '$REMOTE_STAGE' '$REMOTE_PACKAGE'"
}

adopt_staged_package() {
  verify_remote_package_path "$REMOTE_STAGE"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; test ! -e '$REMOTE_PACKAGE'; test -d '$REMOTE_STAGE' && test ! -L '$REMOTE_STAGE'; mv '$REMOTE_STAGE' '$REMOTE_PACKAGE'"
}

ensure_remote_entrypoint() {
  local digest partial
  digest="$(sha256sum "$ENTRYPOINT" | awk '{print $1}')"
  partial="$REMOTE_ENTRYPOINT.partial"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; umask 077; if test -e '$REMOTE_ENTRYPOINT'; then test -f '$REMOTE_ENTRYPOINT' && test ! -L '$REMOTE_ENTRYPOINT'; printf '%s  %s\n' '$digest' '$REMOTE_ENTRYPOINT' | sha256sum -c -; cat >/dev/null; else test ! -e '$partial' || { test -f '$partial' && test ! -L '$partial'; }; cat > '$partial'; printf '%s  %s\n' '$digest' '$partial' | sha256sum -c -; chmod 700 '$partial'; mv '$partial' '$REMOTE_ENTRYPOINT'; fi" \
    < "$ENTRYPOINT"
}

choose_gpu() {
  "$SSH" "${SSH_ARGS[@]}" \
    "nvidia-smi --query-gpu=index,memory.free,utilization.gpu --format=csv,noheader,nounits" \
    | awk -F',' '{gsub(/ /,"",$1);gsub(/ /,"",$2);gsub(/ /,"",$3);if($1>=1&&$1<=7&&$2>=12000)print $1,$2,$3}' \
    | sort -k2,2nr -k3,3n | awk 'NR==1{print $1}'
}

launch_stage_a_once() {
  local gpu="$1" digest
  digest="$(sha256sum "$ENTRYPOINT" | awk '{print $1}')"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; test -d '$REMOTE_PACKAGE' && test ! -L '$REMOTE_PACKAGE'; test ! -e '$REMOTE_RUNTIME'; test ! -e '$REMOTE_EVIDENCE'; ! tmux has-session -t '$REMOTE_SESSION' 2>/dev/null; test -f '$REMOTE_ENTRYPOINT' && test ! -L '$REMOTE_ENTRYPOINT'; printf '%s  %s\n' '$digest' '$REMOTE_ENTRYPOINT' | sha256sum -c -; tmux new-session -d -s '$REMOTE_SESSION' \"/bin/bash '$REMOTE_ENTRYPOINT' '$REMOTE_RUNTIME' '$REMOTE_PACKAGE' '$REMOTE_EVIDENCE' '$FREEZE_NAME' '$EXPECTED_FREEZE_SHA' '$gpu'\""
}

remote_rc_value() {
  python3 - "$SNAPSHOT" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["rc_value"])
PY
}

download_success_bundle_atomically() {
  local proof_tmp="$STATE_ROOT/REMOTE_ARTIFACT_PROOF.json.tmp.$$"
  local tar_tmp="$STATE_ROOT/RETURNED_STAGE_A_V2.tar.tmp.$$"
  local stage_tmp="$STATE_ROOT/.RETURNED_STAGE_A_V2.tmp.$$"
  local final="$STATE_ROOT/RETURNED_STAGE_A_V2"
  local receipt="NODE1_V1_3_5_PREFLIGHT_RECEIPT.json"
  local content

  if [[ -e "$final" ]]; then
    content="$(python3 - "$final/REMOTE_ARTIFACT_PROOF.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["content_name"])
PY
)"
    local adoption_validation="$STATE_ROOT/.adoption_validation.$$"
    python3 "$VALIDATE" --receipt "$final/$receipt" --sidecar "$final/$receipt.sha256" \
      --content-copy "$final/$content" --expected-freeze-sha256 "$EXPECTED_FREEZE_SHA" \
      --expected-preregistration-sha256 "$EXPECTED_PREREG_SHA" \
      --output "$adoption_validation"
    rm -f "$adoption_validation"
    return 0
  fi

  "$SSH" "${SSH_ARGS[@]}" \
    "python3 - --runtime '$REMOTE_RUNTIME' --evidence '$REMOTE_EVIDENCE'" \
    < "$PROVE" > "$proof_tmp"
  python3 -m json.tool "$proof_tmp" >/dev/null
  content="$(python3 - "$proof_tmp" <<'PY'
import json,sys
value=json.load(open(sys.argv[1])); assert value["status"]=="PASS_REMOTE_REGULAR_NONSYMLINK_STAGE_A_ARTIFACTS"
print(value["content_name"])
PY
)"
  "$SSH" "${SSH_ARGS[@]}" \
    "set -euo pipefail; tar -cf - -C '$REMOTE_RUNTIME' '$receipt' '$receipt.sha256' '$content' -C '$REMOTE_EVIDENCE' 'PREFLIGHT_LAUNCHER.log' 'PREFLIGHT_LAUNCHER.rc'" \
    > "$tar_tmp"
  rm -rf "$stage_tmp"
  mkdir -m 700 "$stage_tmp"
  python3 - "$tar_tmp" "$stage_tmp" "$receipt" "$content" <<'PY'
import sys,tarfile
from pathlib import Path
archive=Path(sys.argv[1]); target=Path(sys.argv[2]); receipt=sys.argv[3]; content=sys.argv[4]
expected={receipt,receipt+".sha256",content,"PREFLIGHT_LAUNCHER.log","PREFLIGHT_LAUNCHER.rc"}
with tarfile.open(archive,"r:") as handle:
    members=handle.getmembers()
    assert {m.name for m in members}==expected
    assert all(m.isfile() and not m.issym() and not m.islnk() for m in members)
    handle.extractall(target)
PY
  mv "$proof_tmp" "$stage_tmp/REMOTE_ARTIFACT_PROOF.json"
  python3 "$VALIDATE" --receipt "$stage_tmp/$receipt" --sidecar "$stage_tmp/$receipt.sha256" \
    --content-copy "$stage_tmp/$content" --expected-freeze-sha256 "$EXPECTED_FREEZE_SHA" \
    --expected-preregistration-sha256 "$EXPECTED_PREREG_SHA" \
    --output "$stage_tmp/LOCAL_RETURN_VALIDATION.json"
  [[ ! -e "$final" ]] || return 65
  mv "$stage_tmp" "$final"
  rm -f "$tar_tmp"
}

printf 'watcher_v2_started_utc=%s\n' "$(date -u +%FT%TZ)"
verify_local_inputs
build_deterministic_archive
write_status "PASS_LOCAL_IDENTITY_WAITING_NODE1" "exact frozen package and independent Stage-A-only approval verified"

if [[ "${WATCHER_LOCAL_PREFLIGHT_ONLY:-0}" == "1" ]]; then
  write_status "PASS_LOCAL_PREFLIGHT_ONLY" "local identities and deterministic archive verified; no SSH or remote action"
  exit 0
fi

while true; do
  if ! remote_available || ! probe_remote; then
    write_status "WAITING_NODE1_CONNECTIVITY" "SSH unavailable; watcher will resume and adopt exact remote package/session state"
    sleep "$POLL_SECONDS"
    continue
  fi

  set +e
  state="$(classify_snapshot 2>&1)"; classify_rc=$?
  set -e
  if [[ "$classify_rc" -ne 0 ]]; then
    write_status "FAIL_CLOSED_AMBIGUOUS_REMOTE_STATE" "$state"
    exit 65
  fi

  case "$state" in
    CLEAN)
      write_status "DEPLOYING_ATOMIC_ARCHIVE" "uploading immutable package archive; no execution"
      if ! upload_archive_atomically; then
        write_status "WAITING_NODE1_CONNECTIVITY" "archive upload interrupted; safe partial upload will be overwritten on retry"
        sleep "$POLL_SECONDS"
      fi
      ;;
    ARCHIVE_READY)
      write_status "ADOPTING_READY_ARCHIVE" "exact ready archive found after prior connection boundary"
      if ! extract_ready_archive_atomically; then
        write_status "FAIL_CLOSED_ARCHIVE_EXTRACTION_OR_IDENTITY" "ready archive/stage failed exact frozen-package verification"
        exit 65
      fi
      ;;
    STAGED_PACKAGE)
      write_status "ADOPTING_ATOMIC_STAGE" "exact staged directory found after prior connection boundary"
      if ! adopt_staged_package; then
        write_status "FAIL_CLOSED_STAGED_PACKAGE_IDENTITY" "staged directory is not the exact frozen package"
        exit 65
      fi
      ;;
    READY)
      if ! verify_remote_package_path "$REMOTE_PACKAGE"; then
        write_status "FAIL_CLOSED_FINAL_PACKAGE_IDENTITY" "remote final package differs from frozen allowlist/hashes"
        exit 65
      fi
      if [[ "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["ready_archive"])' "$SNAPSHOT")" == "file" ]]; then
        verify_remote_ready_archive || { write_status "FAIL_CLOSED_READY_ARCHIVE_IDENTITY" "retained archive differs"; exit 65; }
      fi
      ensure_remote_entrypoint || { write_status "FAIL_CLOSED_REMOTE_ENTRYPOINT_IDENTITY" "controller bytes differ"; exit 65; }
      set +e
      gpu="$(choose_gpu 2>/dev/null)"; gpu_rc=$?
      set -e
      if [[ "$gpu_rc" -ne 0 ]]; then
        write_status "WAITING_NODE1_CONNECTIVITY" "SSH dropped while selecting GPU; no launch attempted"
        sleep "$POLL_SECONDS"
      elif [[ -z "$gpu" ]]; then
        write_status "WAITING_NODE1_GPU_CAPACITY" "requires one physical GPU 1-7 with >=12000 MiB free"
        sleep "$POLL_SECONDS"
      else
        write_status "LAUNCHING_NODE1_STAGE_A" "launching exact no-training Stage-A on physical GPU $gpu"
        if ! launch_stage_a_once "$gpu"; then
          write_status "RECONCILING_AFTER_LAUNCH_CONNECTION_BOUNDARY" "launch acknowledgement missing; adopting remote tmux/terminal state before any retry"
          sleep "$POLL_SECONDS"
        fi
      fi
      ;;
    RUNNING)
      verify_remote_package_path "$REMOTE_PACKAGE" >/dev/null || {
        write_status "FAIL_CLOSED_RUNNING_PACKAGE_IDENTITY" "running session package bytes changed"; exit 65;
      }
      python3 "$VALIDATE_SESSION" --snapshot "$SNAPSHOT" --entrypoint "$REMOTE_ENTRYPOINT" \
        --runtime "$REMOTE_RUNTIME" --package "$REMOTE_PACKAGE" --evidence "$REMOTE_EVIDENCE" \
        --freeze-name "$FREEZE_NAME" --freeze-sha256 "$EXPECTED_FREEZE_SHA" >/dev/null || {
          write_status "FAIL_CLOSED_RUNNING_SESSION_IDENTITY" "tmux pane command is not the exact V2 Stage-A entrypoint"; exit 65;
        }
      write_status "RUNNING_NODE1_STAGE_A_PREFLIGHT" "adopted exact tmux session; tests and five-fold load-only preflight running; no training"
      sleep "$POLL_SECONDS"
      ;;
    TERMINAL)
      verify_remote_package_path "$REMOTE_PACKAGE" >/dev/null || {
        write_status "FAIL_CLOSED_TERMINAL_PACKAGE_IDENTITY" "terminal session package bytes changed"; exit 65;
      }
      rc="$(remote_rc_value)"
      if [[ "$rc" != "0" ]]; then
        "$SSH" "${SSH_ARGS[@]}" "cat '$REMOTE_EVIDENCE/PREFLIGHT_LAUNCHER.log'" > "$STATE_ROOT/PREFLIGHT_LAUNCHER_FAILURE.log.tmp" || true
        [[ ! -e "$STATE_ROOT/PREFLIGHT_LAUNCHER_FAILURE.log" ]] && mv "$STATE_ROOT/PREFLIGHT_LAUNCHER_FAILURE.log.tmp" "$STATE_ROOT/PREFLIGHT_LAUNCHER_FAILURE.log" || rm -f "$STATE_ROOT/PREFLIGHT_LAUNCHER_FAILURE.log.tmp"
        write_status "FAIL_NODE1_STAGE_A_PREFLIGHT_NO_RETRY" "terminal rc=$rc; training remains forbidden"
        exit 1
      fi
      if ! download_success_bundle_atomically; then
        write_status "WAITING_NODE1_SUCCESS_ARTIFACT_DOWNLOAD" "terminal rc=0 but remote proof/download was interrupted; retrying without relaunch"
        sleep "$POLL_SECONDS"
        continue
      fi
      write_status "PASS_VALIDATED_NODE1_STAGE_A_WAITING_INDEPENDENT_TRAINING_REVIEW" "receipt, sidecar and content copy passed remote and local validation; training remains unauthorized"
      exit 0
      ;;
    *)
      write_status "FAIL_CLOSED_UNKNOWN_STATE" "$state"
      exit 65
      ;;
  esac
done
