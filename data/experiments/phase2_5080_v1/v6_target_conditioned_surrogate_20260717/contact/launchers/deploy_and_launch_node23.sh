#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dry-run}"
case "$MODE" in
  dry-run|run|status) ;;
  *) printf 'usage: %s {dry-run|run|status}\n' "$0" >&2; exit 64 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTACT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$CONTACT_ROOT/../../../.." && pwd)"
LOCAL_PACKAGE="$REPO_ROOT/experiments/phase2_5080_v1/prepared/pvrig_v4_h_stage1_terminal_v1_20260717"
NODE23_HOST="${NODE23_HOST:-node23}"
SSH_BIN="${SSH_BIN:-ssh.exe}"
REMOTE_PROJECT="${REMOTE_PROJECT:-/data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718}"
REMOTE_DEPLOYMENT="$REMOTE_PROJECT/deployment"
REMOTE_RUNNER="$REMOTE_DEPLOYMENT/launchers/node23_readonly_runner.sh"

[[ -d "$LOCAL_PACKAGE" ]]
[[ -f "$CONTACT_ROOT/src/extract_v4h_stage1_contact_teacher.py" ]]
[[ -f "$CONTACT_ROOT/V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json" ]]

if [[ "$MODE" != "status" ]]; then
  "$SSH_BIN" "$NODE23_HOST" "mkdir -p '$REMOTE_DEPLOYMENT/terminal_package' '$REMOTE_PROJECT/logs'"
  tar -C "$CONTACT_ROOT" -cf - \
    src/extract_v4h_stage1_contact_teacher.py \
    V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json \
    README.md \
    launchers/node23_readonly_runner.sh \
    | "$SSH_BIN" "$NODE23_HOST" "tar -xf - -C '$REMOTE_DEPLOYMENT'"
  tar -C "$LOCAL_PACKAGE" -cf - \
    stage1_all_seed917.tsv \
    stage1_all_seed917.terminal.json \
    stage1_seed917_ranking.tsv \
    stage1_failures.tsv \
    stage1_local_package_receipt.json \
    SHA256SUMS \
    | "$SSH_BIN" "$NODE23_HOST" "tar -xf - -C '$REMOTE_DEPLOYMENT/terminal_package'"

  {
    (cd "$CONTACT_ROOT" && sha256sum \
      src/extract_v4h_stage1_contact_teacher.py \
      V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json \
      README.md \
      launchers/node23_readonly_runner.sh)
    (cd "$LOCAL_PACKAGE" && sha256sum \
      stage1_all_seed917.tsv \
      stage1_all_seed917.terminal.json \
      stage1_seed917_ranking.tsv \
      stage1_failures.tsv \
      stage1_local_package_receipt.json \
      SHA256SUMS) | sed 's#  #  terminal_package/#'
  } | "$SSH_BIN" "$NODE23_HOST" "cat > '$REMOTE_DEPLOYMENT/DEPLOYMENT_SHA256SUMS'"
fi

exec "$SSH_BIN" "$NODE23_HOST" \
  "PROJECT_ROOT='$REMOTE_PROJECT' bash '$REMOTE_RUNNER' '$MODE'"
