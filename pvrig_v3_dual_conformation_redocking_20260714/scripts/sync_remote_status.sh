#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
REMOTE_HOST=${REMOTE_HOST:-node1}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}
SSH_BIN=${SSH_BIN:-ssh.exe}

mkdir -p "$RUN_ROOT/status/remote" "$RUN_ROOT/reports/remote"

# Only pull lightweight state and summaries. Raw poses and HADDOCK workdirs remain on node1.
"$SSH_BIN" "$REMOTE_HOST" "cd '$REMOTE_ROOT' && find status reports -maxdepth 2 -type f \
  \( -name '*.json' -o -name '*.tsv' -o -name '*.md' -o -name '*.log.tail' \) -print0 2>/dev/null \
  | tar --null -T - -czf -" \
  | tar -xzf - -C "$RUN_ROOT/status/remote"

echo "Remote lightweight status synchronized to $RUN_ROOT/status/remote"

