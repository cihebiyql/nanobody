#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
REMOTE_HOST=${REMOTE_HOST:-node1}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}
SSH_BIN=${SSH_BIN:-ssh.exe}

if [[ ! -s "$RUN_ROOT/PROTOCOL_LOCK.json" ]]; then
  echo "Refusing deployment: PROTOCOL_LOCK.json is missing. Run freeze_protocol.py final first." >&2
  exit 2
fi

python3 - "$RUN_ROOT/PROTOCOL_LOCK.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
if p.get("status") != "LOCKED":
    raise SystemExit("Refusing deployment: protocol status is not LOCKED")
PY

payload=(
  README.md
  RUN_STATUS.md
  PROTOCOL_CORE_LOCK.json
  PROTOCOL_LOCK.json
  config
  inputs
  manifests
  reports
  scripts
  tests
)

echo "Deploying frozen evaluator to $REMOTE_HOST:$REMOTE_ROOT"
tar -C "$RUN_ROOT" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='logs/*' \
  --exclude='status/*' \
  --exclude='data/*' \
  --exclude='reports/job_results.tsv' \
  --exclude='reports/pose_scores.tsv' \
  --exclude='reports/control_drift.tsv' \
  --exclude='reports/threshold_sensitivity.tsv' \
  --exclude='reports/EVALUATOR_STABLE.json' \
  --exclude='reports/P2_P3_P4_ENRICHMENT.json' \
  --exclude='reports/p2_p3_p4_enrichment.tsv' \
  -czf - "${payload[@]}" \
  | "$SSH_BIN" "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT' && tar -xzf - -C '$REMOTE_ROOT'"

local_lock=$(sha256sum "$RUN_ROOT/PROTOCOL_LOCK.json" | awk '{print $1}')
remote_lock=$(
  "$SSH_BIN" "$REMOTE_HOST" "sha256sum '$REMOTE_ROOT/PROTOCOL_LOCK.json' | awk '{print \$1}'"
)
if [[ "$local_lock" != "$remote_lock" ]]; then
  echo "Deployment verification failed: protocol lock hash mismatch" >&2
  exit 3
fi

"$SSH_BIN" "$REMOTE_HOST" "mkdir -p '$REMOTE_ROOT'/{data,logs,status,work,results,failed_attempts}"
echo "Deployment verified: protocol_lock_file_sha256=$local_lock"
