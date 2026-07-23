#!/usr/bin/env bash
set -euo pipefail

DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_c2_only_missing6220_seed917_dual_handoff_v1_20260723
ROOT="${PVRIG_C2_PUBLISH_ROOT:-$HOME/${PROJECT}_bxcpu_results}"
ANCHORS="$DEPLOY/FROZEN_INPUT_ANCHORS.json"
APPROVAL="$DEPLOY/INDEPENDENT_LAUNCH_APPROVAL.json"

"$DEPLOY/preflight_c2_missing6220_12440.sh"
[[ -f "$APPROVAL" && ! -L "$APPROVAL" ]] || { echo independent_launch_approval_missing >&2; exit 67; }
python3 - "$APPROVAL" "$ANCHORS" "$0" "$DEPLOY/bxcpu_c2_missing6220_eight_node_worker.sh" <<'PY'
import hashlib,json,pathlib,sys
approval=json.load(open(sys.argv[1]))
def h(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
assert approval["schema_version"]=="pvrig.c2_missing6220.bxcpu_launch_approval.v1"
assert approval["status"]=="APPROVED_TO_SUBMIT_EXACT_12440_JOBS"
assert approval["required_candidates"]==6220 and approval["required_jobs"]==12440
assert approval["frozen_input_anchors_sha256"]==h(sys.argv[2])
assert approval["submit_script_sha256"]==h(sys.argv[3])
assert approval["worker_script_sha256"]==h(sys.argv[4])
assert approval["overlap1280_reuse_authorized"] is False
PY
mapfile -t FROZEN < <(python3 - "$ANCHORS" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
for key in ("archive_sha256","job_manifest_sha256","deployment_bundle_receipt_sha256"):
 print(d[key])
PY
)
ARCHIVE_SHA=${FROZEN[0]}
MANIFEST_SHA=${FROZEN[1]}
BUNDLE_RECEIPT_SHA=${FROZEN[2]}

mkdir -p "$ROOT" "$ROOT/markers" "$ROOT/status/jobs" "$ROOT/results" \
  "$ROOT/compressed_queue" "$ROOT/reports_v2"
[[ $(squeue -h -u "$USER" -n pvrig-c2-gap-12440 | wc -l) -eq 0 ]] || { echo active_campaign_exists >&2; exit 66; }
array=$(sbatch --parsable --partition=amd_256q --job-name=pvrig-c2-gap-12440 \
  --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G --exclusive --time=24:00:00 \
  --array=1-8%8 --output="$ROOT/slurm-%x-%A_%a.out" --error="$ROOT/slurm-%x-%A_%a.err" \
  --export=ALL,PVRIG_C2_NODE_CONCURRENCY=16,PVRIG_C2_PUBLISH_ROOT="$ROOT",PVRIG_C2_ARCHIVE_SHA256="$ARCHIVE_SHA",PVRIG_C2_MANIFEST_SHA256="$MANIFEST_SHA",PVRIG_C2_BUNDLE_RECEIPT_SHA256="$BUNDLE_RECEIPT_SHA" \
  "$DEPLOY/bxcpu_c2_missing6220_eight_node_worker.sh")
array=${array%%;*}
dep=afterany
for shard in {1..8}; do dep+=:${array}_${shard}; done
audit=$(sbatch --parsable --dependency="$dep" --partition=amd_256q --job-name=pvrig-c2-gap-audit-v2 \
  --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=4G --exclusive --time=01:00:00 \
  --output="$ROOT/slurm-%x-%j.out" --error="$ROOT/slurm-%x-%j.err" \
  --export=ALL,PVRIG_C2_PUBLISH_ROOT="$ROOT" "$DEPLOY/run_terminal_audit_v2.sh")
audit=${audit%%;*}
printf 'array_job_id=%s\naudit_v2_job_id=%s\narchive_sha256=%s\nmanifest_sha256=%s\nresult_root=%s\nsubmitted_at=%s\noverlap1280_reuse_authorized=false\n' \
  "$array" "$audit" "$ARCHIVE_SHA" "$MANIFEST_SHA" "$ROOT" "$(date -u +%FT%TZ)" \
  | tee "$ROOT/markers/SUBMISSION_RECEIPT.txt"
