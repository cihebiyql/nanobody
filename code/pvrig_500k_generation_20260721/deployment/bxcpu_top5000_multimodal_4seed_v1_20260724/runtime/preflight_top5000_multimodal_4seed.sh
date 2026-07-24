#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_TOP5000_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_top5000_multimodal_4seed_v1_20260724/runtime}"
# shellcheck source=bxcpu_runtime_common.sh
source "$DEPLOY_ROOT/bxcpu_runtime_common.sh"

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
PROJECT_NAME="${PVRIG_TOP5000_PROJECT_NAME:-pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724}"
PROJECT_DIR="${PVRIG_TOP5000_PROJECT_DIR:-$PROJECT_NAME}"
BUNDLE_ARCHIVE="${PVRIG_TOP5000_BUNDLE_ARCHIVE:-$HOME/${PROJECT_NAME}.tar.zst}"
EXTERNAL_MANIFEST="${PVRIG_TOP5000_MANIFEST_PATH:-$HOME/${PROJECT_NAME}.manifest.tsv}"
READY_PATH="${PVRIG_TOP5000_READY_PATH:-$HOME/${PROJECT_NAME}.READY.json}"
PUBLISH_ROOT="${PVRIG_TOP5000_PUBLISH_ROOT:-$HOME/${PROJECT_NAME}_bxcpu_results}"
MANIFEST_RELATIVE="${PVRIG_TOP5000_MANIFEST_RELATIVE:-manifests/docking_jobs.tsv}"
SHARD_DIR_RELATIVE="${PVRIG_TOP5000_SHARD_DIR_RELATIVE:-manifests/shards_exact_8}"
RECEIPT_RELATIVE="${PVRIG_TOP5000_RECEIPT_RELATIVE:-HANDOFF_RECEIPT.json}"
READY_RELATIVE="${PVRIG_TOP5000_READY_RELATIVE:-READY.json}"
READY_STATUS="${PVRIG_TOP5000_READY_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
RECEIPT_STATUS="${PVRIG_TOP5000_RECEIPT_STATUS:-READY_FOR_EXTERNAL_DOCKING_SUBMISSION}"
PREFLIGHT_RECEIPT="${PVRIG_TOP5000_PREFLIGHT_RECEIPT_PATH:-$PUBLISH_ROOT/reports/PREFLIGHT_RECEIPT.json}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_TOP5000_ARCHIVE_SHA256:?archive SHA256 is required}"
EXPECTED_MANIFEST_SHA256="${PVRIG_TOP5000_MANIFEST_SHA256:?manifest SHA256 is required}"
EXPECTED_READY_SHA256="${PVRIG_TOP5000_READY_SHA256:?READY SHA256 is required}"
EXPECTED_RECEIPT_SHA256="${PVRIG_TOP5000_RECEIPT_SHA256:?receipt SHA256 is required}"

for name in \
    EXPECTED_ARCHIVE_SHA256 \
    EXPECTED_MANIFEST_SHA256 \
    EXPECTED_READY_SHA256 \
    EXPECTED_RECEIPT_SHA256; do
    pvrig_require_sha256 "$name"
done
pvrig_check_sha256 "$BUNDLE_ARCHIVE" "$EXPECTED_ARCHIVE_SHA256" archive
pvrig_check_sha256 "$EXTERNAL_MANIFEST" "$EXPECTED_MANIFEST_SHA256" manifest
pvrig_check_sha256 "$READY_PATH" "$EXPECTED_READY_SHA256" READY
if [[ -n "${SLURM_JOB_ID:-}" ]]; then
    [[ "${SLURM_CPUS_PER_TASK:-0}" == 4 ]] ||
        pvrig_die "preflight smoke requires exactly four allocated CPUs"
fi

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${PROJECT_NAME}/preflight_${SLURM_JOB_ID:-manual}_$$"
LOCAL_PROJECT="$WORK_BASE/$PROJECT_DIR"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
mkdir -p "$WORK_BASE" "$LOCAL_SCRATCH" "$PUBLISH_ROOT/reports"
trap 'rm -rf "$WORK_BASE"' EXIT

pvrig_unpack_runtime "$CACHE_ROOT" "$WORK_BASE"
pvrig_validate_runtime
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" validate-inputs \
    --archive "$BUNDLE_ARCHIVE" \
    --archive-sha256 "$EXPECTED_ARCHIVE_SHA256" \
    --manifest "$EXTERNAL_MANIFEST" \
    --manifest-sha256 "$EXPECTED_MANIFEST_SHA256" \
    --ready "$READY_PATH" \
    --ready-sha256 "$EXPECTED_READY_SHA256" \
    --ready-status "$READY_STATUS" \
    --receipt-sha256 "$EXPECTED_RECEIPT_SHA256" >/dev/null

pvrig_extract_bundle "$BUNDLE_ARCHIVE" "$WORK_BASE"
[[ -d "$LOCAL_PROJECT" && ! -L "$LOCAL_PROJECT" ]] ||
    pvrig_die "bundle did not produce project directory: $PROJECT_DIR"
pvrig_check_sha256 \
    "$LOCAL_PROJECT/$READY_RELATIVE" "$EXPECTED_READY_SHA256" "internal READY"
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" validate-project \
    --project-root "$LOCAL_PROJECT" \
    --manifest-relative "$MANIFEST_RELATIVE" \
    --manifest-sha256 "$EXPECTED_MANIFEST_SHA256" \
    --receipt-relative "$RECEIPT_RELATIVE" \
    --receipt-sha256 "$EXPECTED_RECEIPT_SHA256" \
    --receipt-status "$RECEIPT_STATUS" \
    --shard-dir-relative "$SHARD_DIR_RELATIVE" >"$WORK_BASE/package_validation.json"

SMOKE_JOB="${PVRIG_TOP5000_SMOKE_JOB_ID:-}"
if [[ -z "$SMOKE_JOB" ]]; then
    SMOKE_JOB=$(
        awk -F $'\t' 'NR==2{gsub(/\r$/, "", $1); print $1}' \
            "$LOCAL_PROJECT/$SHARD_DIR_RELATIVE/shard_00.tsv"
    )
fi
[[ "$SMOKE_JOB" =~ ^[A-Za-z0-9_.-]+$ ]] || pvrig_die "unsafe smoke job ID"
mkdir -p "$LOCAL_SCRATCH/$SMOKE_JOB"
PVRIG_PROJECT_ROOT="$LOCAL_PROJECT" \
    PVRIG_LOCAL_SCRATCH_ROOT="$LOCAL_SCRATCH/$SMOKE_JOB" \
    PVRIG_JOB_CPUS=4 \
    "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" \
    "$SMOKE_JOB" --max-attempts 1

SMOKE_COMPACT="$WORK_BASE/smoke_publish/compressed_queue/$SMOKE_JOB.tar.gz"
mkdir -p "$(dirname "$SMOKE_COMPACT")"
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/compact_run_evidence.py" \
    --project-root "$LOCAL_PROJECT" \
    --job-id "$SMOKE_JOB" \
    --output "$SMOKE_COMPACT" >/dev/null
"$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/runtime_contract.py" check-smoke \
    --status "$LOCAL_PROJECT/status/jobs/$SMOKE_JOB.json" \
    --result "$LOCAL_PROJECT/results/$SMOKE_JOB/job_result.json" \
    --compact "$SMOKE_COMPACT" \
    --job-id "$SMOKE_JOB" >"$WORK_BASE/smoke_validation.json"

# The actual 8-task array has already been accepted by Slurm before this
# dependency-gated preflight runs.  A second `sbatch --test-only` here consumes
# the account's submit-job allowance and can fail with AssocMaxSubmitJobLimit
# even though the accepted array is valid.  Package, runtime, exact shard
# closure, CPU layout, and one real HADDOCK job are validated above.

"$LOCAL_ENV/bin/python" - \
    "$PREFLIGHT_RECEIPT" \
    "$EXPECTED_ARCHIVE_SHA256" \
    "$EXPECTED_MANIFEST_SHA256" \
    "$EXPECTED_READY_SHA256" \
    "$EXPECTED_RECEIPT_SHA256" \
    "$SMOKE_JOB" \
    "$WORK_BASE/package_validation.json" \
    "$WORK_BASE/smoke_validation.json" <<'PY'
import datetime, json, os, pathlib, sys
output=pathlib.Path(sys.argv[1])
package=json.load(open(sys.argv[7]))
smoke=json.load(open(sys.argv[8]))
payload={
    "schema_version":"pvrig.top5000_multimodal_4seed.bxcpu_preflight.v1",
    "status":"PASS_RUNTIME_PACKAGE_8_SHARDS_AND_ONE_JOB_SMOKE",
    "runtime":{"haddock":"2025.11.0","numpy":"2.0.1"},
    "expected_candidates":5000,
    "expected_jobs":40000,
    "expected_shards":8,
    "expected_jobs_per_shard":5000,
    "node_layout":{"nodes":8,"cpus_per_node":64,"concurrent_jobs_per_node":16,"cpus_per_job":4},
    "slurm_array_validation":"accepted_dependency_gated_array_plus_static_8x64_layout; no duplicate sbatch --test-only",
    "archive_sha256":sys.argv[2],
    "manifest_sha256":sys.argv[3],
    "ready_sha256":sys.argv[4],
    "receipt_sha256":sys.argv[5],
    "smoke_job_id":sys.argv[6],
    "package_validation":package,
    "smoke_validation":smoke,
    "generated_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
output.parent.mkdir(parents=True,exist_ok=True)
temporary=output.with_name(f".{output.name}.partial.{os.getpid()}")
temporary.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
os.replace(temporary,output)
print(json.dumps(payload,sort_keys=True))
PY
