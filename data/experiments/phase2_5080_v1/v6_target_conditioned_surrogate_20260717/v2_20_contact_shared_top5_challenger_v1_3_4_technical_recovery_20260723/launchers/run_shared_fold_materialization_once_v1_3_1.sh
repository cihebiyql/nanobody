#!/usr/bin/env bash
set -euo pipefail

SHARED_DIR="${1:?usage: $0 SHARED_DIR -- command [args...]}"
shift
[[ "${1:-}" == "--" ]] || { echo "missing_command_separator" >&2; exit 2; }
shift
(( $# > 0 )) || { echo "missing_materializer_command" >&2; exit 2; }

PARENT="$(dirname "$SHARED_DIR")"
mkdir -p "$PARENT"

# The directory is the same-fold exact-once lock.  Never replace this with
# mkdir -p and never remove it after a failed command.
if ! mkdir "$SHARED_DIR"; then
  echo "shared_fold_lock_exists:$SHARED_DIR" >&2
  exit 73
fi

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HELPER_SHA256="$(sha256sum "$SELF" | awk '{print $1}')"
LOCK_TOKEN="$(printf '%s\0%s\0%s\0%s' "$$" "$SHARED_DIR" "$(date +%s%N)" "$RANDOM" | sha256sum | awk '{print $1}')"
LOCK_RECEIPT="$SHARED_DIR/EXACT_ONCE_LOCK.json"
printf '{"helper_sha256":"%s","schema_version":"pvrig.v220.v1_3_1.exact_once_lock.v1","token":"%s"}\n' \
  "$HELPER_SHA256" "$LOCK_TOKEN" > "$LOCK_RECEIPT"
export V220_V131_EXACT_ONCE_LOCK_DIR="$(readlink -f "$SHARED_DIR")"
export V220_V131_EXACT_ONCE_LOCK_TOKEN="$LOCK_TOKEN"
export V220_V131_EXACT_ONCE_HELPER_SHA256="$HELPER_SHA256"

TERMINAL="$SHARED_DIR/MATERIALIZATION_TERMINAL.json"
STDERR_LOG="$SHARED_DIR/MATERIALIZATION_STDERR.log"
[[ ! -e "$TERMINAL" && ! -e "$STDERR_LOG" ]] || {
  echo "unexpected_file_after_atomic_lock:$SHARED_DIR" >&2
  exit 74
}

set +e
"$@" > "$TERMINAL" 2> "$STDERR_LOG"
rc=$?
set -e
printf '%s\n' "$rc" > "$SHARED_DIR/MATERIALIZATION_COMMAND.rc"
exit "$rc"
