#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE=${SOURCE:-/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715}
METHOD=${METHOD:-/data/qlyu/projects/pvrig_v4_e_endpoint_aligned_evaluator_v1_20260717}
ROOT=${ROOT:-/data/qlyu/projects/pvrig_v4_e_open258_research_teacher_v1_20260717}
PYTHON=${PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
EXPECTED_BASE_BUILDER_SHA=8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145
EXPECTED_V4E_BUILDER_SHA=32a9504aa886f69a9fad7d1e54d06527ca179af3dda5e5abd1aaa67b1845ef19

cd "$ROOT"
mkdir -p outputs logs status
exec 9>status/runner.lock
flock -n 9 || exit 75

write_status() {
  local state=$1 reason=$2
  STATE="$state" REASON="$reason" "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
Path("status/status.json").write_text(json.dumps({
    "status": os.environ["STATE"],
    "reason": os.environ["REASON"],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n")
PY
}

fail() {
  local rc=$? line=$1
  write_status FAILED "v4e_open_teacher_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

[[ $(sha256sum prepare_phase2_v4_d_open_teacher.py | awk '{print $1}') == "$EXPECTED_BASE_BUILDER_SHA" ]]
[[ $(sha256sum prepare_pvrig_v4e_open_research_teacher.py | awk '{print $1}') == "$EXPECTED_V4E_BUILDER_SHA" ]]

write_status BUILDING "building open258 retrospective research teacher; test32 remains physically sealed"
"$PYTHON" prepare_pvrig_v4e_open_research_teacher.py \
  --split-manifest "$SOURCE/inputs/fullqc290_split_manifest.tsv" \
  --job-manifest "$SOURCE/manifests/docking_jobs.tsv" \
  --job-results "$SOURCE/reports/job_results.tsv" \
  --pose-scores "$SOURCE/reports/pose_scores.tsv" \
  --results-root "$SOURCE/results" \
  --status-root "$SOURCE/status/jobs" \
  --v4d-evaluator "$SOURCE/reports/EVALUATOR_STABLE.json" \
  --method-audit "$METHOD/outputs/METHOD_AUDIT.json" \
  --method-declaration "$METHOD/governance/V4E_METHOD_AUDIT_DECLARATION.json" \
  --method-receipt "$METHOD/outputs/METHOD_AUDIT_RECEIPT.json" \
  --out outputs/v4e_open258_research_teacher.tsv \
  >logs/builder.stdout.log 2>logs/builder.stderr.log

"$PYTHON" - "$SOURCE" "$METHOD" "$ROOT" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path
source, method, root = map(Path, sys.argv[1:])
teacher = root / "outputs/v4e_open258_research_teacher.tsv"
audit_path = teacher.with_suffix(teacher.suffix + ".audit.json")
with teacher.open(newline="", encoding="utf-8-sig") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
counts = {}
for row in rows:
    counts[row["model_split"]] = counts.get(row["model_split"], 0) + 1
if len(rows) != 258 or counts != {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}:
    raise SystemExit(f"open258 closure failed rows={len(rows)} counts={counts}")
audit = json.loads(audit_path.read_text())
boundary = audit["sealed_test_boundary"]
closure = audit["inputs"]["raw_aggregate_closure"]
if audit["status"] != "PASS_V4E_OPEN258_RETROSPECTIVE_RESEARCH_TEACHER":
    raise SystemExit("bad V4-E audit status")
if boundary["raw_job_results_opened"] != 0 or boundary["candidate_level_rows_released"] != 0:
    raise SystemExit("test32 boundary violated")
if boundary["valid_for_formal_prospective_claim"] is not False:
    raise SystemExit("invalid prospective claim")
if closure["job_count"] != 1548 or closure["successful_job_count"] != 1547 or closure["failed_max_attempts_count"] != 1:
    raise SystemExit(f"unexpected open-job closure: {closure}")
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
receipt = {
    "schema_version": "pvrig_v4e_open258_research_teacher_receipt_v1",
    "status": "PASS_V4E_OPEN258_RESEARCH_TEACHER_TEST32_SEALED",
    "row_count": len(rows),
    "split_counts": counts,
    "teacher_sha256": sha(teacher),
    "teacher_audit_sha256": sha(audit_path),
    "builder_sha256": sha(root / "prepare_pvrig_v4e_open_research_teacher.py"),
    "method_audit_sha256": sha(method / "outputs/METHOD_AUDIT.json"),
    "original_v4d_evaluator_sha256": sha(source / "reports/EVALUATOR_STABLE.json"),
    "original_v4d_evaluator_status": "FAIL",
    "prospective_claim": False,
    "test32_raw_job_results_opened": 0,
    "claim_boundary": "Retrospective open-only computational geometry research teacher; not original V4-D release, prospective validation, binding, affinity, competition, or experimental blocking.",
}
(root / "outputs/V4E_OPEN258_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
PY

sha256sum \
  outputs/v4e_open258_research_teacher.tsv \
  outputs/v4e_open258_research_teacher.tsv.audit.json \
  outputs/V4E_OPEN258_RECEIPT.json \
  >outputs/SHA256SUMS
tar -czf outputs/v4e_open258_research_teacher_delivery_v1.tar.gz \
  outputs/v4e_open258_research_teacher.tsv \
  outputs/v4e_open258_research_teacher.tsv.audit.json \
  outputs/V4E_OPEN258_RECEIPT.json outputs/SHA256SUMS
sha256sum outputs/v4e_open258_research_teacher_delivery_v1.tar.gz \
  >outputs/v4e_open258_research_teacher_delivery_v1.tar.gz.sha256
write_status COMPLETE "open258 retrospective research teacher ready; test32 remains sealed and invalid for formal prospective claim"
