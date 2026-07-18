#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dry-run}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
RAW_ROOT="${RAW_ROOT:-/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717}"
DEPLOYMENT_ROOT="$PROJECT_ROOT/deployment"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WORKERS="${WORKERS:-24}"
SESSION_NAME="${SESSION_NAME:-pvrig-v6-stage1-contact-v1}"
OUTPUT_DIR="$PROJECT_ROOT/output"
LOG_DIR="$PROJECT_ROOT/logs"
RUN_LOG="$LOG_DIR/contact_extraction.log"
RUN_RC="$LOG_DIR/contact_extraction.returncode"

EXTRACTOR="$DEPLOYMENT_ROOT/src/extract_v4h_stage1_contact_teacher.py"
CONTRACT="$DEPLOYMENT_ROOT/V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json"
TERMINAL_PACKAGE="$DEPLOYMENT_ROOT/terminal_package"
DEPLOYMENT_SUMS="$DEPLOYMENT_ROOT/DEPLOYMENT_SHA256SUMS"

case "$MODE" in
  dry-run|foreground|run|status) ;;
  *) printf 'usage: %s {dry-run|foreground|run|status}\n' "$0" >&2; exit 64 ;;
esac

[[ "$PROJECT_ROOT" != "$RAW_ROOT" ]]
[[ "$OUTPUT_DIR" != "$RAW_ROOT"/* ]]
[[ -d "$RAW_ROOT" ]]
[[ -f "$EXTRACTOR" ]]
[[ -f "$CONTRACT" ]]
[[ -d "$TERMINAL_PACKAGE" ]]
[[ -f "$DEPLOYMENT_SUMS" ]]

(cd "$DEPLOYMENT_ROOT" && sha256sum --check --strict DEPLOYMENT_SHA256SUMS)

if [[ "$MODE" == "status" ]]; then
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    printf 'RUNNING session=%s output=%s log=%s\n' "$SESSION_NAME" "$OUTPUT_DIR" "$RUN_LOG"
  elif [[ -f "$RUN_RC" ]]; then
    printf 'TERMINAL returncode=%s output=%s log=%s\n' "$(cat "$RUN_RC")" "$OUTPUT_DIR" "$RUN_LOG"
  else
    printf 'NOT_STARTED session=%s output=%s\n' "$SESSION_NAME" "$OUTPUT_DIR"
  fi
  exit 0
fi

COMMON_ARGS=(
  --campaign-root "$RAW_ROOT"
  --terminal-package "$TERMINAL_PACKAGE"
  --contract "$CONTRACT"
  --output-dir "$OUTPUT_DIR"
  --workers "$WORKERS"
)

if [[ "$MODE" == "dry-run" ]]; then
  [[ ! -e "$OUTPUT_DIR" ]]
  exec "$PYTHON_BIN" "$EXTRACTOR" "${COMMON_ARGS[@]}" --dry-run
fi

if [[ "$MODE" == "foreground" ]]; then
  [[ ! -e "$OUTPUT_DIR" ]]
  exec env PYTHONUNBUFFERED=1 "$PYTHON_BIN" "$EXTRACTOR" "${COMMON_ARGS[@]}"
fi

command -v tmux >/dev/null
[[ ! -e "$OUTPUT_DIR" ]]
mkdir -p "$LOG_DIR"
[[ ! -e "$RUN_RC" ]]
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  printf 'session already exists: %s\n' "$SESSION_NAME" >&2
  exit 73
fi

tmux new-session -d -s "$SESSION_NAME" \
  "bash '$SCRIPT_DIR/node23_readonly_runner.sh' foreground > '$RUN_LOG' 2>&1; rc=\$?; printf '%s\n' \"\$rc\" > '$RUN_RC'"
printf 'STARTED session=%s output=%s log=%s\n' "$SESSION_NAME" "$OUTPUT_DIR" "$RUN_LOG"
