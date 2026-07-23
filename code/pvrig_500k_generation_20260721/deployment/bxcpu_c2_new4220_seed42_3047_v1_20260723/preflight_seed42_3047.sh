#!/usr/bin/env bash
set -euo pipefail
umask 027

CAMPAIGN=pvrig_c2_new4220_seed42_3047_v1_20260723
PACKAGE_NAME=c2_new4220_dualreceptor_seed42_3047_handoff_v1
CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
BUNDLE_ARCHIVE="${PVRIG_C2_EXTRA_ARCHIVE:-$HOME/${PACKAGE_NAME}_20260723.tar.gz}"
PUBLISH_ROOT="${PVRIG_C2_EXTRA_PUBLISH_ROOT:-$HOME/${CAMPAIGN}_bxcpu_results}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_C2_EXTRA_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_MANIFEST_SHA256="${PVRIG_C2_EXTRA_MANIFEST_SHA256:?manifest SHA256 is required}"
WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${CAMPAIGN}_preflight/${SLURM_JOB_ID:-manual}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
LOCAL_PROJECT="$WORK_BASE/$PACKAGE_NAME"

mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY" \
    "$LOCAL_SCRATCH" "$PUBLISH_ROOT/reports"
[[ $(sha256sum "$BUNDLE_ARCHIVE" | awk '{print $1}') == "$EXPECTED_ARCHIVE_SHA256" ]]
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
MANIFEST="$LOCAL_PROJECT/manifests/docking_jobs.tsv"
[[ $(sha256sum "$MANIFEST" | awk '{print $1}') == "$EXPECTED_MANIFEST_SHA256" ]]
"$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/validate_protocol.py" \
    --protocol "$LOCAL_PROJECT/config/protocol_spec.json" \
    --jobs "$MANIFEST" --out "$WORK_BASE/validation.json" \
    --expected-total-jobs 16880 >/dev/null

SMOKE_JOB=$(awk -F'\t' 'NR==2{gsub(/\r$/, "", $1);print $1}' "$LOCAL_PROJECT/manifests/smoke_jobs.tsv")
PVRIG_PROJECT_ROOT="$LOCAL_PROJECT" PVRIG_LOCAL_SCRATCH_ROOT="$LOCAL_SCRATCH/$SMOKE_JOB" \
    "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" "$SMOKE_JOB" --max-attempts 1
"$LOCAL_ENV/bin/python" - "$LOCAL_PROJECT/HANDOFF_RECEIPT.json" \
    "$LOCAL_PROJECT/status/jobs/$SMOKE_JOB.json" "$WORK_BASE/validation.json" \
    "$PUBLISH_ROOT/reports/PREFLIGHT_RECEIPT.json" <<'PY'
import datetime,json,pathlib,sys
r=json.load(open(sys.argv[1]));s=json.load(open(sys.argv[2]));v=json.load(open(sys.argv[3]))
assert r["protocol"]["seeds"]==[42,3047] and r["counts"]["jobs"]==16880
assert s["status"]=="SUCCESS"
assert v["status"]=="PASS" and v["job_count"]==16880
out=pathlib.Path(sys.argv[4])
p={"status":"PASS_ARCHIVE_PROTOCOL_RUNTIME_AND_ONE_JOB_SMOKE","seeds":[42,3047],
   "validated_jobs":16880,"smoke_job_id":s["job_id"],
   "generated_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
tmp=out.with_suffix(".partial");tmp.write_text(json.dumps(p,indent=2,sort_keys=True)+"\n");tmp.replace(out)
print(json.dumps(p,sort_keys=True))
PY

# The account submit-job limit prevents reserving the full follow-on chain while
# the predecessor array is still active.  This preflight is already dependency-
# gated by the predecessor terminal audit, so it stages the 8-node array and its
# audit only after the smoke and protocol checks above have passed.
PVRIG_SUBMIT_FROM_PREFLIGHT=1 "$HOME/.local/share/$CAMPAIGN/submit_after_current_audit.sh"
PVRIG_SUBMIT_FROM_PREFLIGHT=1 "$HOME/.local/share/$CAMPAIGN/submit_after_current_audit.sh"
