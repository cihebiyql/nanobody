#!/usr/bin/env bash
set -Eeuo pipefail

EXP_DIR=${PVRIG_EXP_DIR:-/mnt/d/work/抗体/data/experiments/phase2_5080_v1}
PYTHON=${PYTHON:-$EXP_DIR/.venv-phase2-5080/bin/python}
SSH=${SSH:-ssh.exe}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-172800}

V4D_REMOTE=/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716
DEEPQC_REMOTE=/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716
CROSSCHECK_REMOTE=/data/qlyu/projects/pvrig_pre_shortlist100_structure_crosscheck_v1_20260716
POSE_REMOTE=/data/qlyu/projects/pvrig_top20_pose_review_postprocess_v1_20260716

V4D_LOCAL=$EXP_DIR/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1
DEEPQC_LOCAL=$EXP_DIR/prepared/pvrig_pre_shortlist100_deepqc_v1/remote_delivery_v1
CROSSCHECK_LOCAL=$EXP_DIR/prepared/pvrig_pre_shortlist100_structure_crosscheck_v1/remote_delivery_v1
POSE_LOCAL=$EXP_DIR/prepared/pvrig_top20_pose_review_v1/remote_delivery_v1
V4D_DELIVERY=$V4D_LOCAL/current
DEEPQC_DELIVERY=$DEEPQC_LOCAL/current
CROSSCHECK_DELIVERY=$CROSSCHECK_LOCAL/current
POSE_DELIVERY=$POSE_LOCAL/current
MASTER_V2=$EXP_DIR/prepared/pvrig_candidate_evidence_master_v2
SHORTLIST=$EXP_DIR/prepared/pvrig_geometry_shortlist_v1
STATUS_DIR=$EXP_DIR/status/pvrig_v4d_deepqc_postprocess_v1
LOG_DIR=$EXP_DIR/logs

[[ -x "$PYTHON" ]] || PYTHON=python3
command -v "$SSH" >/dev/null
mkdir -p "$V4D_LOCAL" "$DEEPQC_LOCAL" "$CROSSCHECK_LOCAL" "$POSE_LOCAL" "$STATUS_DIR" "$LOG_DIR"
exec 9>"$STATUS_DIR/controller.lock"
flock -n 9 || { echo "postprocess controller already running" >&2; exit 75; }
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
  write_status FAILED "local_postprocess_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

remote_status() {
  local node=$1 path=$2
  local payload
  if ! payload=$("$SSH" "$node" "if [ -s '$path' ]; then cat '$path'; else printf '{\"status\":\"MISSING\"}\\n'; fi" 2>/dev/null); then
    echo UNREACHABLE
    return 0
  fi
  printf '%s' "$payload" |
    "$PYTHON" -c 'import json,sys
try: print(json.load(sys.stdin).get("status","MISSING"))
except Exception: print("MALFORMED")'
}

verify_delivery() {
  local kind=$1 directory=$2
  "$PYTHON" - "$kind" "$directory" "$EXP_DIR" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path

kind, root, exp = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path): return json.loads(path.read_text())
def require(condition, message):
    if not condition: raise SystemExit(message)
def safe_path(text):
    path=(root/text).resolve()
    require(path == root or root in path.parents, f"unsafe delivery path: {text}")
    return path
def verify_sums(path):
    for line in path.read_text().splitlines():
        if not line.strip(): continue
        digest, rel = line.split(None, 1)
        target=safe_path(rel.strip().lstrip("*"))
        require(target.is_file() and sha(target)==digest, f"internal checksum mismatch: {rel}")

if kind == "deepqc":
    receipt=load(root/"reports/deepqc_delivery_receipt_v1.json")
    require(receipt.get("status")=="PASS_DEEPQC100_DELIVERY_READY", "bad DeepQC receipt status")
    require(receipt.get("candidate_count")==100 and receipt.get("tnp_row_count")==100 and receipt.get("igfold_row_count")==100 and receipt.get("igfold_pdb_count")==100, "bad DeepQC receipt counts")
    manifest=root/"reports/delivery_file_manifest.tsv"
    require(sha(manifest)==receipt.get("delivery_manifest_sha256"), "DeepQC manifest hash mismatch")
    with manifest.open(newline="", encoding="utf-8-sig") as handle:
        rows=list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows)==111, f"unexpected DeepQC delivery manifest rows: {len(rows)}")
    for row in rows:
        target=safe_path(row["path"])
        require(target.is_file(), f"DeepQC file missing: {row['path']}")
        require(target.stat().st_size==int(row["bytes"]) and sha(target)==row["sha256"], f"DeepQC file mismatch: {row['path']}")
    expected={
        "run_deepqc_sha256": exp/"prepared/pvrig_pre_shortlist100_deepqc_v1/run_deepqc.sh",
        "deepqc_config_sha256": exp/"prepared/pvrig_pre_shortlist100_deepqc_v1/deepqc_config.json",
        "input_audit_sha256": exp/"prepared/pvrig_pre_shortlist100_deepqc_v1/input_audit.json",
        "input_fasta_sha256": exp/"prepared/pvrig_pre_shortlist100_deepqc_v1/inputs/pre_shortlist100.fasta",
    }
    for field, path in expected.items(): require(sha(path)==receipt.get(field), f"DeepQC pinned source mismatch: {field}")
elif kind == "crosscheck":
    verify_sums(root/"outputs/SHA256SUMS")
    receipt=load(root/"outputs/structure_crosscheck_receipt.json")
    require(receipt.get("status")=="PASS_100_OF_100_STRUCTURE_CROSSCHECK_COMPUTED", "bad crosscheck receipt status")
    require(receipt.get("script_sha256")==sha(exp/"src/audit_pre_shortlist100_igfold_nbb2.py"), "crosscheck script mismatch")
    require(receipt.get("shortlist_sha256")==sha(exp/"prepared/pvrig_portfolio_pre_shortlist100_v1/pre_shortlist100.tsv"), "crosscheck shortlist mismatch")
    require(receipt.get("monomer_manifest_sha256")==sha(exp/"prepared/pvrig_candidate_evidence_master_v1/sources/v4d_candidate_monomers_manifest.tsv"), "crosscheck monomer manifest mismatch")
elif kind == "v4d":
    verify_sums(root/"outputs/SHA256SUMS")
    receipt=load(root/"outputs/open_teacher_postprocess_receipt.json")
    evaluator=load(root/"outputs/EVALUATOR_STABLE.json")
    audit=load(root/"outputs/v4d_open_teacher.tsv.audit.json")
    require(receipt.get("status")=="PASS_OPEN258_TEACHER_READY_TEST32_SEALED" and receipt.get("row_count")==258, "bad V4-D teacher receipt")
    require(receipt.get("sealed_test_raw_job_results_opened")==0 and receipt.get("sealed_metrics_used_for_teacher_or_ranking") is False, "V4-D sealed boundary mismatch")
    require(evaluator.get("status")=="PASS" and evaluator.get("unlockable") is True, "V4-D evaluator not releasable")
    require(receipt.get("evaluator_sha256")==sha(root/"outputs/EVALUATOR_STABLE.json"), "V4-D evaluator hash mismatch")
    require(receipt.get("teacher_sha256")==sha(root/"outputs/v4d_open_teacher.tsv"), "V4-D teacher hash mismatch")
    require(receipt.get("teacher_audit_sha256")==sha(root/"outputs/v4d_open_teacher.tsv.audit.json"), "V4-D teacher audit hash mismatch")
    require(receipt.get("builder_sha256")==sha(exp/"src/prepare_phase2_v4_d_open_teacher.py"), "V4-D builder mismatch")
    closure=audit.get("inputs",{}).get("raw_aggregate_closure",{})
    require(closure.get("status")=="PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES" and closure.get("job_count")==1548, "V4-D raw aggregate closure missing")
    require(receipt.get("raw_aggregate_closure_sha256")==closure.get("closure_sha256"), "V4-D closure hash mismatch")
elif kind == "pose":
    verify_sums(root/"SHA256SUMS")
    audit=load(root/"pose_review_audit.json")
    require(audit.get("status")=="PASS_OPEN_ONLY_V4D_POSE_REVIEW", "bad pose bundle audit")
    require(audit.get("candidate_count")==20 and audit.get("successful_job_count")==120 and audit.get("manifest_pose_count")==360, "bad pose bundle counts")
    require(audit.get("input_sha256",{}).get("packager")==sha(exp/"src/package_pvrig_top20_pose_review.py"), "pose packager mismatch")
    require(audit.get("input_sha256",{}).get("shortlist")==sha(exp/"prepared/pvrig_geometry_shortlist_v1/shortlist50.tsv"), "pose shortlist mismatch")
    require(audit.get("input_sha256",{}).get("split_manifest")==sha(exp/"data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"), "pose split mismatch")
    require(audit.get("input_sha256",{}).get("job_manifest")=="96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737", "pose job manifest mismatch")
else:
    raise SystemExit(f"unknown delivery kind: {kind}")
print(f"PASS_{kind.upper()}_DELIVERY_VERIFIED")
PY
}

fetch_archive() {
  local kind=$1 node=$2 remote_archive=$3 remote_sha=$4 local_root=$5
  if [[ -d "$local_root/current" ]]; then
    verify_delivery "$kind" "$local_root/current"
    return 0
  fi
  local staging archive expected actual
  staging=$(mktemp -d "$local_root/.staging.XXXXXX")
  archive=$staging/$(basename "$remote_archive")
  expected=$("$SSH" "$node" "awk '{print \$1}' '$remote_sha'")
  "$SSH" "$node" "cat '$remote_archive'" >"$archive.download"
  actual=$(sha256sum "$archive.download" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || {
    echo "archive hash mismatch: $remote_archive expected=$expected actual=$actual" >&2
    return 2
  }
  mv "$archive.download" "$archive"
  tar -xzf "$archive" -C "$staging"
  verify_delivery "$kind" "$staging"
  printf '%s  %s\n' "$actual" "$(basename "$archive")" >"$staging/ARCHIVE_SHA256"
  mv "$staging" "$local_root/current"
}

merge_deepqc_only() {
  "$PYTHON" "$EXP_DIR/src/merge_pvrig_candidate_evidence_v2.py" \
    --tnp-summary "$DEEPQC_DELIVERY/reports/tnp_summary.tsv" \
    --igfold-summary "$DEEPQC_DELIVERY/reports/igfold_summary.tsv" \
    --igfold-nbb2-audit "$CROSSCHECK_DELIVERY/outputs/igfold_nbb2_crosscheck.tsv" \
    --outdir "$MASTER_V2"
  printf '{"status":"PASS_DEEPQC100_MERGED_V4D_PENDING"}\n' >"$STATUS_DIR/deepqc_merged.json"
}

merge_all_and_rank() {
  "$PYTHON" "$EXP_DIR/src/merge_pvrig_candidate_evidence_v2.py" \
    --v4d-open-teacher "$V4D_DELIVERY/outputs/v4d_open_teacher.tsv" \
    --tnp-summary "$DEEPQC_DELIVERY/reports/tnp_summary.tsv" \
    --igfold-summary "$DEEPQC_DELIVERY/reports/igfold_summary.tsv" \
    --igfold-nbb2-audit "$CROSSCHECK_DELIVERY/outputs/igfold_nbb2_crosscheck.tsv" \
    --outdir "$MASTER_V2"
  "$PYTHON" "$EXP_DIR/src/build_pvrig_geometry_shortlist.py" \
    --master "$MASTER_V2/candidate_evidence_master.tsv" \
    --outdir "$SHORTLIST"
}

build_and_fetch_top20_pose_bundle() {
  local packager=$EXP_DIR/src/package_pvrig_top20_pose_review.py
  local shortlist=$SHORTLIST/shortlist50.tsv
  local packager_sha shortlist_sha remote_packager_sha remote_shortlist_sha
  packager_sha=$(sha256sum "$packager" | awk '{print $1}')
  shortlist_sha=$(sha256sum "$shortlist" | awk '{print $1}')
  "$SSH" node23 "mkdir -p '$POSE_REMOTE/inputs' '$POSE_REMOTE/logs'"
  "$SSH" node23 "cat > '$POSE_REMOTE/package_pvrig_top20_pose_review.py'" <"$packager"
  "$SSH" node23 "cat > '$POSE_REMOTE/inputs/shortlist50.tsv'" <"$shortlist"
  remote_packager_sha=$("$SSH" node23 "sha256sum '$POSE_REMOTE/package_pvrig_top20_pose_review.py' | awk '{print \$1}'")
  remote_shortlist_sha=$("$SSH" node23 "sha256sum '$POSE_REMOTE/inputs/shortlist50.tsv' | awk '{print \$1}'")
  [[ "$remote_packager_sha" == "$packager_sha" ]]
  [[ "$remote_shortlist_sha" == "$shortlist_sha" ]]

  "$SSH" node23 "set -e; \
    SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715; \
    ROOT='$POSE_REMOTE'; \
    PY=/data/qlyu/anaconda3/envs/haddock3/bin/python; \
    cd \"\$ROOT\"; \
    if [ ! -s delivery/pose_review_audit.json ]; then \
      \"\$PY\" package_pvrig_top20_pose_review.py \
        --shortlist inputs/shortlist50.tsv \
        --split-manifest \"\$SOURCE/inputs/fullqc290_split_manifest.tsv\" \
        --job-manifest \"\$SOURCE/manifests/docking_jobs.tsv\" \
        --results-root \"\$SOURCE/results\" \
        --project-root \"\$SOURCE\" \
        --outdir delivery \
        >logs/packager.stdout.log 2>logs/packager.stderr.log; \
    fi; \
    \"\$PY\" - <<'PY'
import json
from pathlib import Path
p=Path('delivery/pose_review_audit.json')
x=json.loads(p.read_text())
assert x['status']=='PASS_OPEN_ONLY_V4D_POSE_REVIEW'
assert x['candidate_count']==20 and x['successful_job_count']==120
assert x['manifest_pose_count']==360
PY
    sha256sum delivery/pose_review_bundle.tar.gz >delivery/pose_review_bundle.tar.gz.sha256"

  fetch_archive pose node23 \
    "$POSE_REMOTE/delivery/pose_review_bundle.tar.gz" \
    "$POSE_REMOTE/delivery/pose_review_bundle.tar.gz.sha256" \
    "$POSE_LOCAL"
  printf '{"status":"PASS_TOP20_OPEN_POSE_BUNDLE_SYNCED"}\n' \
    >"$STATUS_DIR/top20_pose_bundle_synced.json"
}

write_final_receipt() {
  "$PYTHON" - "$EXP_DIR" "$STATUS_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
exp, status = map(Path, sys.argv[1:3])
paths = {
    "candidate_evidence_master_v2": exp / "prepared/pvrig_candidate_evidence_master_v2/candidate_evidence_master.tsv",
    "candidate_evidence_audit_v2": exp / "prepared/pvrig_candidate_evidence_master_v2/candidate_evidence_lineage_audit.json",
    "ranked_open258": exp / "prepared/pvrig_geometry_shortlist_v1/ranked_open258.tsv",
    "shortlist50": exp / "prepared/pvrig_geometry_shortlist_v1/shortlist50.tsv",
    "top20_pose_review_manifest": exp / "prepared/pvrig_geometry_shortlist_v1/top20_pose_review_manifest.tsv",
    "geometry_shortlist_audit": exp / "prepared/pvrig_geometry_shortlist_v1/geometry_shortlist_audit.json",
    "top20_pose_bundle_manifest": exp / "prepared/pvrig_top20_pose_review_v1/remote_delivery_v1/current/pose_review_manifest.tsv",
    "top20_pose_bundle_audit": exp / "prepared/pvrig_top20_pose_review_v1/remote_delivery_v1/current/pose_review_audit.json",
    "top20_pose_bundle_archive": exp / "prepared/pvrig_top20_pose_review_v1/remote_delivery_v1/current/pose_review_bundle.tar.gz",
}
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
missing = [name for name, path in paths.items() if not path.is_file()]
if missing:
    raise SystemExit(f"final receipt inputs missing: {missing}")
payload = {
    "schema_version": "pvrig_v4d_deepqc_postprocess_receipt_v1",
    "status": "PASS_OPEN258_RANKED_TOP50_TOP20_POSE_BUNDLE_READY",
    "outputs": {name: {"path": str(path), "sha256": digest(path)} for name, path in paths.items()},
    "sealed_test_geometry_rows_released": 0,
    "claim_boundary": "Computational priority only; not binding, affinity, competition, or experimental blocking.",
}
(status / "final_receipt.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

write_status RUNNING "waiting for remote DeepQC/crosscheck and V4-D open teacher deliveries"
while true; do
  deepqc_state=$(remote_status node1 "$DEEPQC_REMOTE/status/package_watcher_status.json")
  crosscheck_state=$(remote_status node1 "$CROSSCHECK_REMOTE/status/crosscheck_status.json")
  v4d_state=$(remote_status node23 "$V4D_REMOTE/status/postprocess_status.json")

  if [[ "$deepqc_state" == BLOCKED* || "$deepqc_state" == FAILED* ||
        "$crosscheck_state" == BLOCKED* || "$crosscheck_state" == FAILED* ||
        "$v4d_state" == BLOCKED* || "$v4d_state" == FAILED* ]]; then
    write_status BLOCKED "remote terminal failure: deepqc=$deepqc_state crosscheck=$crosscheck_state v4d=$v4d_state"
    exit 2
  fi
  if (( $(date +%s) - STARTED_AT > MAX_WAIT_SECONDS )); then
    write_status BLOCKED "local_wait_timeout_seconds=$MAX_WAIT_SECONDS states: deepqc=$deepqc_state crosscheck=$crosscheck_state v4d=$v4d_state"
    exit 3
  fi

  if [[ "$deepqc_state" == COMPLETE && "$crosscheck_state" == COMPLETE &&
        ! -s "$STATUS_DIR/deepqc_merged.json" ]]; then
    write_status SYNCING_DEEPQC "fetching hash-bound Node1 DeepQC and structure crosscheck deliveries"
    fetch_archive deepqc node1 \
      "$DEEPQC_REMOTE/reports/deepqc_delivery_v1.tar.gz" \
      "$DEEPQC_REMOTE/reports/deepqc_delivery_v1.tar.gz.sha256" \
      "$DEEPQC_LOCAL"
    fetch_archive crosscheck node1 \
      "$CROSSCHECK_REMOTE/outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz" \
      "$CROSSCHECK_REMOTE/outputs/igfold_nbb2_crosscheck_delivery_v1.tar.gz.sha256" \
      "$CROSSCHECK_LOCAL"
    merge_deepqc_only
  fi

  if [[ "$v4d_state" == COMPLETE && ! -s "$STATUS_DIR/v4d_open_teacher_synced.json" ]]; then
    write_status SYNCING_V4D "fetching open258 teacher delivery; test32 remains remote and sealed"
    fetch_archive v4d node23 \
      "$V4D_REMOTE/outputs/v4d_open_teacher_delivery_v1.tar.gz" \
      "$V4D_REMOTE/outputs/v4d_open_teacher_delivery_v1.tar.gz.sha256" \
      "$V4D_LOCAL"
    printf '{"status":"PASS_OPEN258_TEACHER_SYNCED_TEST32_SEALED"}\n' \
      >"$STATUS_DIR/v4d_open_teacher_synced.json"
  fi

  if [[ -s "$STATUS_DIR/deepqc_merged.json" && -s "$STATUS_DIR/v4d_open_teacher_synced.json" ]]; then
    write_status MERGING_AND_RANKING "building final v2 evidence master and open258 geometry shortlist"
    merge_all_and_rank
    write_status PACKAGING_TOP20_POSES "copying only Top20 open-candidate V4-D poses for manual review"
    build_and_fetch_top20_pose_bundle
    write_final_receipt
    write_status COMPLETE "open258 ranked; Top50 and hash-bound Top20 pose bundle ready"
    exit 0
  fi

  write_status RUNNING "remote states: deepqc=$deepqc_state crosscheck=$crosscheck_state v4d=$v4d_state"
  sleep "$POLL_SECONDS"
done
