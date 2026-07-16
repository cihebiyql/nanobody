#!/usr/bin/env bash
set -Eeuo pipefail

EXP_DIR=${PVRIG_EXP_DIR:-/mnt/d/work/抗体/data/experiments/phase2_5080_v1}
PYTHON=${PYTHON:-python3}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-864000}
BUILD_TIMEOUT_SECONDS=${BUILD_TIMEOUT_SECONDS:-7200}
REPLAY_TIMEOUT_SECONDS=${REPLAY_TIMEOUT_SECONDS:-7200}
ONCE=${ONCE:-0}

UPSTREAM_STATUS=$EXP_DIR/status/pvrig_v4d_deepqc_postprocess_v1
SHORTLIST_DIR=$EXP_DIR/prepared/pvrig_geometry_shortlist_v1
POSE_DIR=$EXP_DIR/prepared/pvrig_top20_pose_review_v1/remote_delivery_v1/current
ROOT=$EXP_DIR/prepared/pvrig_submission_release_v1
REVIEW=$ROOT/review_inputs
RELEASE=$ROOT/release
STATUS_DIR=$EXP_DIR/status/pvrig_submission_release_v1
BUILDER=${BUILDER:-$EXP_DIR/src/prepare_pvrig_submission_release.py}

mkdir -p "$ROOT" "$REVIEW" "$STATUS_DIR"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "submission release controller already running" >&2; exit 75; }
echo $$ >"$STATUS_DIR/controller.pid"
STARTED_AT=$(date +%s)

write_status() {
  local state=$1 reason=$2
  STATE_VALUE=$state REASON_VALUE=$reason "$PYTHON" - "$STATUS_DIR/status.json" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
  "status": os.environ["STATE_VALUE"],
  "reason": os.environ["REASON_VALUE"],
  "updated_at": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n")
PY
}

fail() {
  local rc=$? line=$1
  write_status FAILED "submission_release_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

upstream_ready() {
  "$PYTHON" - \
    "$UPSTREAM_STATUS/final_receipt.json" \
    "$SHORTLIST_DIR/shortlist50.tsv" \
    "$SHORTLIST_DIR/geometry_shortlist_audit.json" \
    "$POSE_DIR/pose_review_manifest.tsv" \
    "$POSE_DIR/pose_review_audit.json" \
    "$POSE_DIR/pose_review_bundle.tar.gz" <<'PY'
import hashlib, json, sys
from pathlib import Path
receipt_path=Path(sys.argv[1])
paths={
 "shortlist50":Path(sys.argv[2]),
 "geometry_shortlist_audit":Path(sys.argv[3]),
 "top20_pose_bundle_manifest":Path(sys.argv[4]),
 "top20_pose_bundle_audit":Path(sys.argv[5]),
 "top20_pose_bundle_archive":Path(sys.argv[6]),
}
try: receipt=json.loads(receipt_path.read_text())
except Exception: raise SystemExit(2)
if receipt.get("schema_version")!="pvrig_v4d_deepqc_postprocess_receipt_v1": raise SystemExit(2)
if receipt.get("status")!="PASS_OPEN258_RANKED_TOP50_TOP20_POSE_BUNDLE_READY": raise SystemExit(2)
if receipt.get("sealed_test_geometry_rows_released")!=0: raise SystemExit(2)
outputs=receipt.get("outputs",{})
for name,path in paths.items():
    record=outputs.get(name,{})
    if not path.is_file() or not record: raise SystemExit(2)
    try:
        if Path(record.get("path","")).resolve()!=path.resolve(): raise SystemExit(2)
    except Exception: raise SystemExit(2)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=record.get("sha256"): raise SystemExit(2)
PY
}

generate_templates() {
  "$PYTHON" - \
    "$SHORTLIST_DIR/shortlist50.tsv" \
    "$SHORTLIST_DIR/geometry_shortlist_audit.json" \
    "$POSE_DIR/pose_review_manifest.tsv" \
    "$POSE_DIR/pose_review_audit.json" \
    "$REVIEW" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path
shortlist, shortlist_audit, manifest, pose_audit, outdir = map(Path, sys.argv[1:])
def read(path):
    with path.open(newline="",encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle,delimiter="\t"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
rows=read(shortlist); poses=read(manifest); top20=rows[:20]
ids=[row["candidate_id"] for row in top20]
if len(rows)!=50 or len(ids)!=20 or len(set(ids))!=20: raise SystemExit("shortlist closure failed")
if {row["candidate_id"] for row in poses}!=set(ids) or len(poses)!=360: raise SystemExit("pose closure failed")
core={
 "shortlist_sha256":sha(shortlist),
 "shortlist_audit_sha256":sha(shortlist_audit),
 "pose_manifest_sha256":sha(manifest),
 "pose_audit_sha256":sha(pose_audit),
 "top20":[{"candidate_id":row["candidate_id"],"rank":row["rank"]} for row in top20],
}
context_id=hashlib.sha256(json.dumps(core,separators=(",",":"),sort_keys=True).encode()).hexdigest()
context={"schema_version":"pvrig_submission_review_context_v1","review_context_id":context_id,**core}
outdir.mkdir(parents=True,exist_ok=True)
(outdir/"review_context.json").write_text(json.dumps(context,indent=2,sort_keys=True)+"\n")
with (outdir/"pose_review_verdicts.template.tsv").open("w",newline="",encoding="utf-8") as handle:
    fields=["candidate_id","top50_rank","review_context_id","verdict","reviewer","review_notes"]
    writer=csv.DictWriter(handle,fieldnames=fields,delimiter="\t",lineterminator="\n"); writer.writeheader()
    for row in top20: writer.writerow({"candidate_id":row["candidate_id"],"top50_rank":row["rank"],"review_context_id":context_id})
with (outdir/"top10_selection.template.tsv").open("w",newline="",encoding="utf-8") as handle:
    fields=["candidate_id","top50_rank","review_context_id","portfolio_rank","selection_reason"]
    writer=csv.DictWriter(handle,fieldnames=fields,delimiter="\t",lineterminator="\n"); writer.writeheader()
    for row in top20: writer.writerow({"candidate_id":row["candidate_id"],"top50_rank":row["rank"],"review_context_id":context_id})
(outdir/"README_ZH.md").write_text(
 "# Top20 计算姿势复核输入\n\n"
 "模板已绑定 `review_context.json`；不得复用其他 shortlist/pose 版本的 verdict。\n\n"
 "1. 复制 `pose_review_verdicts.template.tsv` 为 `pose_review_verdicts.tsv`，填满 20 行。\n"
 "2. 从 Top20 选择正好 10 条写入 `top10_selection.tsv`，保留相同 review_context_id。\n"
 "3. Top10 只接受 ACCEPT_COMPUTATIONAL_PRIORITY 或 ACCEPT_DIVERSITY_HEDGE。\n\n"
 "这是计算姿势优先级复核，不是结合、Kd 或实验阻断证据。\n",encoding="utf-8")
print(json.dumps({"status":"PASS_REVIEW_TEMPLATES_READY","review_context_id":context_id,"top20_count":20,"pose_count":360}))
PY
}

review_inputs_ready() {
  "$PYTHON" - \
    "$REVIEW/review_context.json" \
    "$REVIEW/pose_review_verdicts.tsv" \
    "$REVIEW/top10_selection.tsv" <<'PY'
import csv, json, sys
from pathlib import Path
context_path, verdicts, selection = map(Path, sys.argv[1:])
if not all(path.is_file() for path in (context_path,verdicts,selection)): raise SystemExit(1)
try: context=json.loads(context_path.read_text())
except Exception: raise SystemExit(1)
context_id=context.get("review_context_id","")
top20=context.get("top20",[]); expected={row["candidate_id"] for row in top20}
def read(path):
    with path.open(newline="",encoding="utf-8-sig") as handle: return list(csv.DictReader(handle,delimiter="\t"))
v=read(verdicts); s=read(selection)
if len(v)!=20 or len(s)!=10 or {row.get("candidate_id") for row in v}!=expected: raise SystemExit(1)
if not {row.get("candidate_id") for row in s}.issubset(expected): raise SystemExit(1)
if any(row.get("review_context_id")!=context_id for row in v+s): raise SystemExit(1)
if any(not all(row.get(field,"").strip() for field in ("candidate_id","verdict","reviewer","review_notes")) for row in v): raise SystemExit(1)
if any(not all(row.get(field,"").strip() for field in ("candidate_id","portfolio_rank","selection_reason")) for row in s): raise SystemExit(1)
if [row["portfolio_rank"] for row in s] != [str(i) for i in range(1,11)]: raise SystemExit(1)
PY
}

run_stage() {
  local stage=$1 budget=$2
  shift 2
  local rc
  if timeout --preserve-status "$budget" "$@"; then return 0; else rc=$?; fi
  if [[ $rc -eq 124 || $rc -eq 137 || $rc -eq 143 ]]; then
    write_status BLOCKED "stage=$stage timeout_seconds=$budget rc=$rc"
  else
    write_status FAILED "stage=$stage rc=$rc"
  fi
  exit "$rc"
}

validate_release_build() {
  "$PYTHON" - "$RELEASE" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
required=["release_audit.json","release_recipe.json","SHA256SUMS","clean_replay.sh","pvrig_submission_release_v1.tar.gz","submission_top50.fasta","submission_top10.fasta"]
if any(not (root/name).is_file() or (root/name).stat().st_size==0 for name in required): raise SystemExit(2)
try: audit=json.loads((root/"release_audit.json").read_text())
except Exception: raise SystemExit(2)
if audit.get("status")!="PASS_COMPUTATIONAL_SUBMISSION_PACKAGE_READY": raise SystemExit(2)
if audit.get("top50_count")!=50 or audit.get("top10_count")!=10 or audit.get("frozen_top20_pose_count")!=360: raise SystemExit(2)
PY
}

write_final_receipt() {
  "$PYTHON" - "$RELEASE" "$STATUS_DIR" "$REVIEW/review_context.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
release,status,context_path=map(Path,sys.argv[1:])
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
try:
    audit=json.loads((release/"release_audit.json").read_text())
    replay=json.loads((release/"clean_replay_receipt.json").read_text())
    context=json.loads(context_path.read_text())
except Exception: raise SystemExit(2)
archive=release/"pvrig_submission_release_v1.tar.gz"
if audit.get("status")!="PASS_COMPUTATIONAL_SUBMISSION_PACKAGE_READY": raise SystemExit(2)
if replay.get("status")!="PASS_CLEAN_REPLAY_BYTE_IDENTICAL": raise SystemExit(2)
if replay.get("release_archive_sha256")!=sha(archive) or replay.get("replay_archive_sha256")!=sha(archive): raise SystemExit(2)
payload={
 "schema_version":"pvrig_submission_release_controller_receipt_v1",
 "status":"PASS_COMPUTATIONAL_TOP50_TOP10_RELEASE_REPLAYED",
 "claim_boundary":"Computational priority release only; not binding, affinity/Kd, competition, or experimental blocking.",
 "review_context_id":context["review_context_id"],
 "review_context_sha256":sha(context_path),
 "release_audit_sha256":sha(release/"release_audit.json"),
 "clean_replay_receipt_sha256":sha(release/"clean_replay_receipt.json"),
 "archive_sha256":sha(archive),
}
(status/"final_receipt.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
}

build_release() {
  if [[ -e "$RELEASE" ]]; then
    if ! validate_release_build; then
      write_status FAILED "existing release failed strict validation"
      exit 2
    fi
  else
    run_stage builder "$BUILD_TIMEOUT_SECONDS" "$PYTHON" "$BUILDER" \
      --shortlist "$SHORTLIST_DIR/shortlist50.tsv" \
      --shortlist-audit "$SHORTLIST_DIR/geometry_shortlist_audit.json" \
      --top10-selection "$REVIEW/top10_selection.tsv" \
      --pose-manifest "$POSE_DIR/pose_review_manifest.tsv" \
      --pose-audit "$POSE_DIR/pose_review_audit.json" \
      --pose-verdicts "$REVIEW/pose_review_verdicts.tsv" \
      --outdir "$RELEASE"
    validate_release_build
  fi
  run_stage clean_replay "$REPLAY_TIMEOUT_SECONDS" "$RELEASE/clean_replay.sh"
  write_final_receipt
}

write_status WAITING_UPSTREAM "waiting for validated open258 Top50 and hash-bound Top20 pose bundle"
while true; do
  if [[ -s "$UPSTREAM_STATUS/final_receipt.json" ]]; then
    if upstream_ready; then
      generate_templates >"$STATUS_DIR/template_generation.json"
      if review_inputs_ready; then
        write_status BUILDING_RELEASE "current-context review inputs complete; building deterministic release"
        build_release
        write_status COMPLETE "computational Top50/Top10 release and clean replay complete"
        exit 0
      fi
      write_status WAITING_COMPUTATIONAL_POSE_REVIEW \
        "Top20 bundle ready; complete current-context pose verdicts and Top10 selection"
    else
      write_status BLOCKED_UPSTREAM_INVALID_RECEIPT \
        "upstream final receipt or bound artifacts failed validation"
    fi
  else
    write_status WAITING_UPSTREAM "waiting for validated open258 Top50 and hash-bound Top20 pose bundle"
  fi
  if [[ "$ONCE" == 1 ]]; then exit 4; fi
  if (( $(date +%s) - STARTED_AT > MAX_WAIT_SECONDS )); then
    write_status BLOCKED "submission release wait timeout seconds=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep "$POLL_SECONDS"
done
