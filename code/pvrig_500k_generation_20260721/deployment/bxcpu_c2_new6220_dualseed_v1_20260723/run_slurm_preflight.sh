#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_C2_NEW_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_c2_new6220_dualseed_v1_20260723}"
CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
BUNDLE_ARCHIVE="${PVRIG_C2_NEW_BUNDLE_ARCHIVE:-$HOME/pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz}"
PUBLISH_ROOT="${PVRIG_C2_NEW_PUBLISH_ROOT:-$HOME/pvrig_c2_new6220_dualreceptor_2seed_v1_20260723_bxcpu_results}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_C2_NEW_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_ROOT_RECEIPT_SHA256="${PVRIG_C2_NEW_ROOT_RECEIPT_SHA256:?root receipt SHA256 is required}"
EXPECTED_4220_MANIFEST_SHA256="${PVRIG_C2_NEW_4220_MANIFEST_SHA256:?4220 manifest SHA256 is required}"
EXPECTED_2000_MANIFEST_SHA256="${PVRIG_C2_NEW_2000_MANIFEST_SHA256:?2000 manifest SHA256 is required}"
EXPECTED_ANCHORS_SHA256="${PVRIG_C2_NEW_ANCHORS_SHA256:?frozen anchors SHA256 is required}"

PARENT_NAME=c2_new6220_split4220_2000_dualreceptor_2seed_handoffs_v2
PACKAGE_4220_NAME=c2_new4220_dualreceptor_2seed_handoff_v2
PACKAGE_2000_NAME=c2_new2000_dualreceptor_2seed_handoff_v2
WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/pvrig_c2_new6220_preflight/${SLURM_JOB_ID:-manual}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
LOCAL_PARENT="$WORK_BASE/$PARENT_NAME"
LOCAL_4220="$LOCAL_PARENT/$PACKAGE_4220_NAME"
LOCAL_2000="$LOCAL_PARENT/$PACKAGE_2000_NAME"

mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY" \
    "$LOCAL_SCRATCH" "$PUBLISH_ROOT/reports"
[[ $(sha256sum "$BUNDLE_ARCHIVE" | awk '{print $1}') == "$EXPECTED_ARCHIVE_SHA256" ]]
[[ $(sha256sum "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" | awk '{print $1}') == "$EXPECTED_ANCHORS_SHA256" ]]
python3 - "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" "$DEPLOY_ROOT" <<'PY_DEPLOY_GATE'
import hashlib,json,pathlib,sys
anchors=json.load(open(sys.argv[1])); deploy=pathlib.Path(sys.argv[2])
def sha(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
assert anchors["status"]=="FROZEN_READY_FOR_DEPENDENT_SUBMISSION"
for relative, expected in anchors["deployment_file_sha256"].items():
    assert sha(deploy/relative)==expected, relative
PY_DEPLOY_GATE

for archive in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz; do
    tar -xzf "$CACHE_ROOT/$archive" -C "$LOCAL_ENV"
done
tar -xzf "$CACHE_ROOT/haddock3_source_2025.11.0.tar.gz" -C "$LOCAL_SOURCE"
tar -xzf "$CACHE_ROOT/numpy_el7_overlay_2.0.1.tar.gz" -C "$NUMPY_OVERLAY"
tar -xzf "$BUNDLE_ARCHIVE" -C "$WORK_BASE"

export PATH="$LOCAL_ENV/bin:$PATH"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$NUMPY_OVERLAY/lib/python3.11/site-packages:$LOCAL_SOURCE/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
"$LOCAL_ENV/bin/python" -m haddock.clis.cli --version | head -n 1 | grep -Fx 'cli.py - 2025.11.0'
"$LOCAL_ENV/bin/python" -c 'import numpy; assert numpy.__version__ == "2.0.1"'

[[ $(sha256sum "$LOCAL_PARENT/ROOT_RECEIPT.json" | awk '{print $1}') == "$EXPECTED_ROOT_RECEIPT_SHA256" ]]
[[ $(sha256sum "$LOCAL_4220/manifests/docking_jobs.tsv" | awk '{print $1}') == "$EXPECTED_4220_MANIFEST_SHA256" ]]
[[ $(sha256sum "$LOCAL_2000/manifests/docking_jobs.tsv" | awk '{print $1}') == "$EXPECTED_2000_MANIFEST_SHA256" ]]

"$LOCAL_ENV/bin/python" "$LOCAL_4220/scripts/validate_protocol.py" \
    --protocol "$LOCAL_4220/config/protocol_spec.json" \
    --jobs "$LOCAL_4220/manifests/docking_jobs.tsv" \
    --out "$WORK_BASE/validation_4220.json" \
    --expected-total-jobs 16880 >/dev/null
"$LOCAL_ENV/bin/python" "$LOCAL_2000/scripts/validate_protocol.py" \
    --protocol "$LOCAL_2000/config/protocol_spec.json" \
    --jobs "$LOCAL_2000/manifests/docking_jobs.tsv" \
    --out "$WORK_BASE/validation_2000.json" \
    --expected-total-jobs 8000 >/dev/null

DISPATCH_SMOKE="$DEPLOY_ROOT/dispatch_shards/shard_00.tsv"
! grep -q $'\r' "$DISPATCH_SMOKE"
IFS=$'\t' read -r SMOKE_PACKAGE SMOKE_JOB < <(
    awk -F'\t' 'NR==2{gsub(/\r$/, "", $2); print $1 "\t" $2}' "$DISPATCH_SMOKE"
)
case "$SMOKE_PACKAGE" in
    c2_new4220) SMOKE_PROJECT="$LOCAL_4220" ;;
    c2_new2000) SMOKE_PROJECT="$LOCAL_2000" ;;
    *) echo "unknown smoke package: $SMOKE_PACKAGE" >&2; exit 65 ;;
esac
PVRIG_PROJECT_ROOT="$SMOKE_PROJECT" PVRIG_LOCAL_SCRATCH_ROOT="$LOCAL_SCRATCH/$SMOKE_JOB" \
    "$LOCAL_ENV/bin/python" "$SMOKE_PROJECT/scripts/run_job.py" \
    "$SMOKE_JOB" --max-attempts 1

"$LOCAL_ENV/bin/python" - "$SMOKE_PROJECT/status/jobs/$SMOKE_JOB.json" \
    "$SMOKE_PROJECT/results/$SMOKE_JOB/job_result.json" \
    "$WORK_BASE/validation_4220.json" "$WORK_BASE/validation_2000.json" \
    "$SMOKE_PACKAGE" "$PUBLISH_ROOT/reports/PREFLIGHT_RECEIPT.retry1.json" <<'PY'
import datetime, json, pathlib, sys
status=json.load(open(sys.argv[1]))
result=json.load(open(sys.argv[2]))
v4220=json.load(open(sys.argv[3]))
v2000=json.load(open(sys.argv[4]))
assert status["status"]=="SUCCESS"
assert result["state"]=="SUCCESS"
for validation, jobs in ((v4220,16880),(v2000,8000)):
    assert validation["status"]=="PASS"
    assert validation["expected_total_jobs"]==jobs
    assert validation["job_count"]==jobs
out=pathlib.Path(sys.argv[6])
payload={
 "schema_version":"pvrig.c2_new6220.bxcpu_preflight.v1",
 "status":"PASS_ARCHIVE_PROTOCOL_RUNTIME_AND_ONE_JOB_SMOKE",
 "smoke_job_id":pathlib.Path(sys.argv[1]).stem,
 "smoke_package":sys.argv[5],
 "validated_jobs":24880,
 "docking_campaign_started":False,
 "generated_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
tmp=out.with_suffix(".partial")
tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
tmp.replace(out)
print(json.dumps(payload,sort_keys=True))
PY
