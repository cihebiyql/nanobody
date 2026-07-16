#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
ROOT=/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716
PYTHON=/data/qlyu/anaconda3/envs/haddock3/bin/python
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-172800}
EXPECTED_BUILDER_SHA=8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145
cd "$ROOT"

mkdir -p status outputs logs
exec 9>status/postprocess_watcher.lock
flock -n 9 || exit 75

write_status() {
  local state=$1 reason=$2
  STATE_VALUE=$state REASON_VALUE=$reason $PYTHON - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
Path("status/postprocess_status.json").write_text(json.dumps({
    "status": os.environ["STATE_VALUE"], "reason": os.environ["REASON_VALUE"],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n")
PY
}

fail() {
  local rc=$? line=$1
  write_status FAILED "open_teacher_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

actual=$(sha256sum prepare_phase2_v4_d_open_teacher.py | awk '{print $1}')
[[ "$actual" == "$EXPECTED_BUILDER_SHA" ]]

if [[ -s outputs/open_teacher_postprocess_receipt.json &&
      -s outputs/v4d_open_teacher_delivery_v1.tar.gz &&
      -s outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256 ]] &&
   sha256sum -c outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256 >/dev/null 2>&1 &&
   $PYTHON - <<'PY'
import json
from pathlib import Path
p=Path("outputs/open_teacher_postprocess_receipt.json")
raise SystemExit(0 if json.loads(p.read_text()).get("status")=="PASS_OPEN258_TEACHER_READY_TEST32_SEALED" else 1)
PY
then
  write_status COMPLETE "existing hash-bound open258 teacher delivery verified"
  exit 0
fi

started=$(date +%s)
write_status WAITING_V4D "waiting for terminal V4-D evaluator"
while true; do
  orchestrator=$($PYTHON - "$SOURCE/status/orchestrator.json" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); print(json.loads(p.read_text()).get("status","MISSING") if p.is_file() else "MISSING")
PY
)
  case "$orchestrator" in
    COMPLETE_EVALUATOR_PASS) break ;;
    COMPLETE_EVALUATOR_NOT_RELEASED|COMPLETE_REVIEW_REQUIRED)
      write_status BLOCKED "v4d_orchestrator_terminal_without_evaluator_release:$orchestrator"
      exit 3
      ;;
  esac
  if (( $(date +%s) - started > MAX_WAIT_SECONDS )); then
    write_status BLOCKED "v4d_wait_timeout_seconds=$MAX_WAIT_SECONDS"
    exit 4
  fi
  sleep 300
done

write_status BUILDING_OPEN_TEACHER "V4-D evaluator passed; releasing only 258 open candidate rows"
$PYTHON prepare_phase2_v4_d_open_teacher.py \
  --split-manifest "$SOURCE/inputs/fullqc290_split_manifest.tsv" \
  --job-manifest "$SOURCE/manifests/docking_jobs.tsv" \
  --job-results "$SOURCE/reports/job_results.tsv" \
  --pose-scores "$SOURCE/reports/pose_scores.tsv" \
  --results-root "$SOURCE/results" \
  --evaluator "$SOURCE/reports/EVALUATOR_STABLE.json" \
  --out outputs/v4d_open_teacher.tsv \
  >logs/teacher_builder.stdout.log 2>logs/teacher_builder.stderr.log
cp "$SOURCE/reports/EVALUATOR_STABLE.json" outputs/EVALUATOR_STABLE.json

$PYTHON - "$SOURCE" "$ROOT" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path
source, root = map(Path, sys.argv[1:3])
teacher=root/"outputs/v4d_open_teacher.tsv"
audit_path=root/"outputs/v4d_open_teacher.tsv.audit.json"
evaluator_path=root/"outputs/EVALUATOR_STABLE.json"
with teacher.open(newline="", encoding="utf-8-sig") as handle:
    rows=list(csv.DictReader(handle, delimiter="\t"))
counts={}
for row in rows: counts[row["model_split"]]=counts.get(row["model_split"],0)+1
if len(rows)!=258 or counts!={"OPEN_TRAIN":226,"OPEN_DEVELOPMENT":32}:
    raise SystemExit(f"open teacher closure failed rows={len(rows)} counts={counts}")
if any(row["model_split"]=="PROSPECTIVE_COMPUTATIONAL_TEST" for row in rows):
    raise SystemExit("sealed test leaked into open teacher")
audit=json.loads(audit_path.read_text())
boundary=audit.get("sealed_data_boundary", {})
closure=audit.get("inputs", {}).get("raw_aggregate_closure", {})
if boundary.get("raw_job_results_opened")!=0 or boundary.get("sealed_metrics_used_for_teacher_or_ranking") is not False:
    raise SystemExit("sealed boundary receipt invalid")
if closure.get("status")!="PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES" or closure.get("job_count")!=1548:
    raise SystemExit(f"raw/aggregate closure invalid: {closure}")
evaluator=json.loads(evaluator_path.read_text())
if evaluator.get("status")!="PASS" or evaluator.get("unlockable") is not True:
    raise SystemExit("copied evaluator is not releasable")
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
receipt={
    "schema_version":"pvrig_v4_d_open_teacher_postprocess_receipt_v2",
    "status":"PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
    "row_count":len(rows), "split_counts":counts,
    "sealed_test_raw_job_results_opened":0,
    "sealed_metrics_used_for_teacher_or_ranking":False,
    "full_aggregate_streamed_only_for_open_row_closure":True,
    "raw_aggregate_closure_sha256":closure["closure_sha256"],
    "teacher_sha256":digest(teacher),
    "teacher_audit_sha256":digest(audit_path),
    "evaluator_sha256":digest(evaluator_path),
    "builder_sha256":digest(root/"prepare_phase2_v4_d_open_teacher.py"),
    "job_manifest_sha256":evaluator["job_manifest_sha256"],
    "job_results_sha256":evaluator["job_results_sha256"],
    "pose_scores_sha256":evaluator["pose_scores_sha256"],
    "claim_boundary":"Computational dual-conformation geometry teacher only; not binding, affinity, competition, or experimental blocking.",
}
(root/"outputs/open_teacher_postprocess_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
PY

sha256sum outputs/v4d_open_teacher.tsv outputs/v4d_open_teacher.tsv.audit.json \
  outputs/EVALUATOR_STABLE.json outputs/open_teacher_postprocess_receipt.json \
  >outputs/SHA256SUMS
tar -czf outputs/v4d_open_teacher_delivery_v1.tar.gz \
  outputs/v4d_open_teacher.tsv outputs/v4d_open_teacher.tsv.audit.json \
  outputs/EVALUATOR_STABLE.json outputs/open_teacher_postprocess_receipt.json \
  outputs/SHA256SUMS
sha256sum outputs/v4d_open_teacher_delivery_v1.tar.gz \
  >outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256
write_status COMPLETE "open258 teacher delivery ready; test32 raw results remain unopened"
