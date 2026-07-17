#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_monomer_structures_v1_20260717
PYTHON=/usr/bin/python3
RUNNER="$ROOT/scripts/prepare_and_run_support_v4a720_structures.py"

test -f "$ROOT/status/zero_work_preflight.json"
test ! -e "$ROOT/status/structures.complete.json"
test ! -e "$ROOT/status/runner.pid"

setsid bash -c '
  set -uo pipefail
  root="$1"; python="$2"; runner="$3"
  "$python" "$runner" run --output-root "$root" --max-parallel 4 --threads 8 --gpu-ids 0,1,2,3 \
    >"$root/logs/structures.run.log" 2>&1
  rc=$?
  printf "%s\n" "$rc" >"$root/status/runner.rc"
  exit "$rc"
' _ "$ROOT" "$PYTHON" "$RUNNER" </dev/null >/dev/null 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$ROOT/status/runner.pid"

setsid bash -c '
  root="$1"; runner_pid="$2"
  out="$root/audit/resource_monitor.tsv"
  printf "observed_at_utc\tload1\trunner_pid_alive\tterminal_records\tgpu_csv\n" >"$out"
  while kill -0 "$runner_pid" 2>/dev/null; do
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    load=$(cut -d" " -f1 /proc/loadavg)
    n=$(find "$root/status/candidates" -maxdepth 1 -name "*.terminal.json" -type f | wc -l)
    gpu=$(nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader,nounits | head -n 4 | tr "\n" ";")
    printf "%s\t%s\t1\t%s\t%s\n" "$ts" "$load" "$n" "$gpu" >>"$out"
    sleep 60
  done
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  load=$(cut -d" " -f1 /proc/loadavg)
  n=$(find "$root/status/candidates" -maxdepth 1 -name "*.terminal.json" -type f | wc -l)
  printf "%s\t%s\t0\t%s\t\n" "$ts" "$load" "$n" >>"$out"
' _ "$ROOT" "$pid" </dev/null >/dev/null 2>&1 &
monitor_pid=$!
printf '%s\n' "$monitor_pid" >"$ROOT/status/resource_monitor.pid"

python3 - "$ROOT" "$pid" "$monitor_pid" <<'PY'
import hashlib, json, pathlib, sys
root=pathlib.Path(sys.argv[1])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
payload={
  "schema_version":"pvrig_support_v4a720_monomer_launch_receipt_v1",
  "status":"STARTED",
  "runner_pid":int(sys.argv[2]),
  "resource_monitor_pid":int(sys.argv[3]),
  "runner_sha256":sha(root/"scripts/prepare_and_run_support_v4a720_structures.py"),
  "preregistration_sha256":sha(root/"PREREGISTRATION.json"),
  "zero_work_preflight_sha256":sha(root/"status/zero_work_preflight.json"),
  "resource_policy":{"gpu_ids":[0,1,2,3],"gpu_workers":4,"threads_per_worker":8,"max_cpu_threads":32},
  "claim_boundary":"label_free_computational_monomer_structure_and_cross_method_uncertainty_only;not_docking_geometry_binding_affinity_competition_experimental_blocking_blocker_probability_or_docking_gold"
}
(root/"status/launch_receipt.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
print(json.dumps(payload,indent=2,sort_keys=True))
PY
