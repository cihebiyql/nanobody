#!/usr/bin/env bash
set -Eeuo pipefail

MODE=${1:-full}
REMOTE_HOST=${REMOTE_HOST:-node1}
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}
SSH_BIN=${SSH_BIN:-ssh.exe}
PYTHON=${REMOTE_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
HADDOCK3=${REMOTE_HADDOCK3:-/data/qlyu/anaconda3/envs/haddock3/bin/haddock3}
LOCAL_SCRATCH_ROOT=${REMOTE_LOCAL_SCRATCH_ROOT:-}

case "$MODE" in
  validate)
    "$SSH_BIN" "$REMOTE_HOST" "cd '$REMOTE_ROOT' && PVRIG_PROJECT_ROOT='$REMOTE_ROOT' '$PYTHON' scripts/validate_protocol.py"
    ;;
  pipeline|smoke|full)
    if [[ "$MODE" == pipeline ]]; then
      extra=""
      name=smoke_then_full
      entry=scripts/orchestrate_smoke_then_full.py
    elif [[ "$MODE" == smoke ]]; then
      extra="--job-list manifests/smoke_jobs.tsv --poll-seconds 15"
      name=smoke_controller
      entry=scripts/run_controller.py
    else
      extra="--poll-seconds 60"
      name=full_controller
      entry=scripts/run_controller.py
    fi
    "$SSH_BIN" "$REMOTE_HOST" "set -e; cd '$REMOTE_ROOT'; mkdir -p logs status; \
      if test -s status/${name}.pid && kill -0 \$(cat status/${name}.pid) 2>/dev/null; then \
        echo '${name} already running pid='\$(cat status/${name}.pid); exit 0; \
      fi; \
      nohup env PVRIG_PROJECT_ROOT='$REMOTE_ROOT' HADDOCK3='$HADDOCK3' PATH='/data/qlyu/anaconda3/envs/haddock3/bin':\"\$PATH\" \
        PVRIG_LOCAL_SCRATCH_ROOT='$LOCAL_SCRATCH_ROOT' \
        '$PYTHON' '$entry' $extra > logs/${name}.log 2>&1 < /dev/null & \
      pid=\$!; echo \$pid > status/${name}.pid; echo '${name} started pid='\$pid"
    ;;
  status)
    "$SSH_BIN" "$REMOTE_HOST" "cd '$REMOTE_ROOT' && PVRIG_PROJECT_ROOT='$REMOTE_ROOT' '$PYTHON' scripts/status.py --json; \
      for f in status/*.pid; do test -e \"\$f\" || continue; p=\$(cat \"\$f\"); \
      if kill -0 \"\$p\" 2>/dev/null; then echo \"\$f RUNNING pid=\$p\"; else echo \"\$f STOPPED pid=\$p\"; fi; done"
    ;;
  *)
    echo "Usage: $0 {validate|pipeline|smoke|full|status}" >&2
    exit 2
    ;;
esac
