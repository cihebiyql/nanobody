#!/usr/bin/env bash
set -Eeuo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$here/runtime"

nohup setsid python3 -u "$here/monitor_node1_bxcpu_30m.py" --interval 1800 \
  >>"$here/runtime/monitor.nohup.log" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$here/runtime/monitor.pid"
echo "started pid=$pid"
