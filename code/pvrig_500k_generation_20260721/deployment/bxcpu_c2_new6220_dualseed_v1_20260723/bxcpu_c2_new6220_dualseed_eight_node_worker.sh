#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_C2_NEW_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_c2_new6220_dualseed_v1_20260723}"
CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
CAMPAIGN=pvrig_c2_new6220_dualreceptor_2seed_v1_20260723
BUNDLE_ARCHIVE="${PVRIG_C2_NEW_BUNDLE_ARCHIVE:-$HOME/pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz}"
EXPECTED_ARCHIVE_SHA256="${PVRIG_C2_NEW_ARCHIVE_SHA256:?archive SHA256 is required}"
PUBLISH_ROOT="${PVRIG_C2_NEW_PUBLISH_ROOT:-$HOME/${CAMPAIGN}_bxcpu_results}"
SHARD_INDEX="${SLURM_ARRAY_TASK_ID:-1}"
NODE_CONCURRENCY="${PVRIG_C2_NEW_NODE_CONCURRENCY:-16}"

PARENT_NAME=c2_new6220_split4220_2000_dualreceptor_2seed_handoffs_v2
PACKAGE_4220_NAME=c2_new4220_dualreceptor_2seed_handoff_v2
PACKAGE_2000_NAME=c2_new2000_dualreceptor_2seed_handoff_v2
EXPECTED_ROOT_RECEIPT_SHA256="${PVRIG_C2_NEW_ROOT_RECEIPT_SHA256:?root receipt SHA256 is required}"
EXPECTED_4220_MANIFEST_SHA256="${PVRIG_C2_NEW_4220_MANIFEST_SHA256:?4220 manifest SHA256 is required}"
EXPECTED_2000_MANIFEST_SHA256="${PVRIG_C2_NEW_2000_MANIFEST_SHA256:?2000 manifest SHA256 is required}"
EXPECTED_ANCHORS_SHA256="${PVRIG_C2_NEW_ANCHORS_SHA256:?frozen anchors SHA256 is required}"

[[ "$SHARD_INDEX" =~ ^[1-8]$ ]] || { echo "shard index must be 1..8" >&2; exit 64; }
[[ "$NODE_CONCURRENCY" == 16 ]] || { echo "worker requires 16 concurrent 4-core jobs" >&2; exit 64; }
[[ "${SLURM_CPUS_ON_NODE:-64}" == 64 ]] || { echo "expected 64 allocated CPUs" >&2; exit 65; }
[[ $(sha256sum "$BUNDLE_ARCHIVE" | awk '{print $1}') == "$EXPECTED_ARCHIVE_SHA256" ]] || {
    echo "bundle SHA256 mismatch" >&2
    exit 65
}

WORK_BASE="${SLURM_TMPDIR:-/tmp}/${USER}/${CAMPAIGN}/${SLURM_ARRAY_JOB_ID:-manual}_${SHARD_INDEX}"
LOCAL_ENV="$WORK_BASE/haddock3-env"
LOCAL_SOURCE="$WORK_BASE/haddock3-source"
NUMPY_OVERLAY="$WORK_BASE/numpy-el7-overlay"
LOCAL_SCRATCH="$WORK_BASE/job-scratch"
LOCAL_PARENT="$WORK_BASE/$PARENT_NAME"
LOCAL_4220="$LOCAL_PARENT/$PACKAGE_4220_NAME"
LOCAL_2000="$LOCAL_PARENT/$PACKAGE_2000_NAME"

mkdir -p "$WORK_BASE" "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY" "$LOCAL_SCRATCH" \
    "$PUBLISH_ROOT/batch_4220/status/jobs" "$PUBLISH_ROOT/batch_4220/results" \
    "$PUBLISH_ROOT/batch_4220/worker_logs" "$PUBLISH_ROOT/batch_4220/compressed_queue" \
    "$PUBLISH_ROOT/batch_2000/status/jobs" "$PUBLISH_ROOT/batch_2000/results" \
    "$PUBLISH_ROOT/batch_2000/worker_logs" "$PUBLISH_ROOT/batch_2000/compressed_queue" \
    "$PUBLISH_ROOT/markers" "$PUBLISH_ROOT/reports"

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

[[ $(sha256sum "$LOCAL_PARENT/ROOT_RECEIPT.json" | awk '{print $1}') == "$EXPECTED_ROOT_RECEIPT_SHA256" ]] || {
    echo "root receipt SHA256 mismatch" >&2
    exit 65
}
[[ $(sha256sum "$LOCAL_4220/manifests/docking_jobs.tsv" | awk '{print $1}') == "$EXPECTED_4220_MANIFEST_SHA256" ]] || {
    echo "4220 manifest SHA256 mismatch" >&2
    exit 65
}
[[ $(sha256sum "$LOCAL_2000/manifests/docking_jobs.tsv" | awk '{print $1}') == "$EXPECTED_2000_MANIFEST_SHA256" ]] || {
    echo "2000 manifest SHA256 mismatch" >&2
    exit 65
}

"$LOCAL_ENV/bin/python" - "$LOCAL_PARENT/ROOT_RECEIPT.json" \
    "$LOCAL_4220/HANDOFF_RECEIPT.json" "$LOCAL_2000/HANDOFF_RECEIPT.json" <<'PY_GATE'
import json, sys
root, a, b = (json.load(open(path)) for path in sys.argv[1:])
assert root["status"] == "READY_TWO_INDEPENDENT_HANDOFFS"
assert root["counts"]["total_candidates"] == 6220
assert root["counts"]["total_jobs"] == 24880
assert set(root["conformations"]) == {"8x6b", "9e6y"}
assert set(root["seeds"]) == {917, 1931}
assert a["status"] == b["status"] == "READY_FOR_EXTERNAL_DOCKING_SUBMISSION"
assert a["counts"]["candidates"] == 4220 and a["counts"]["jobs"] == 16880
assert b["counts"]["candidates"] == 2000 and b["counts"]["jobs"] == 8000
assert a["docking_started"] is False and b["docking_started"] is False
PY_GATE

SHARD_ZERO=$((SHARD_INDEX - 1))
SAFE_MANIFEST=$(printf '%s/dispatch_shards/shard_%02d.tsv' "$DEPLOY_ROOT" "$SHARD_ZERO")
[[ -f "$SAFE_MANIFEST" ]] || { echo "missing dispatch shard: $SAFE_MANIFEST" >&2; exit 65; }
[[ $(sha256sum "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" | awk '{print $1}') == "$EXPECTED_ANCHORS_SHA256" ]] || {
    echo "frozen anchors SHA256 mismatch" >&2
    exit 65
}
"$LOCAL_ENV/bin/python" - "$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json" \
    "$DEPLOY_ROOT" "$SAFE_MANIFEST" <<'PY_DISPATCH_GATE'
import csv, hashlib, json, pathlib, sys
anchors=json.load(open(sys.argv[1]))
deploy=pathlib.Path(sys.argv[2])
shard=pathlib.Path(sys.argv[3])
def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
assert anchors["status"]=="FROZEN_READY_FOR_DEPENDENT_SUBMISSION"
assert anchors["expected_jobs"]==24880
for relative, expected in anchors["deployment_file_sha256"].items():
    assert sha(deploy/relative)==expected, relative
receipt=json.load(open(deploy/"dispatch_shards/DISPATCH_RECEIPT.json"))
assert receipt["status"]=="READY_8_BALANCED_SHARDS"
assert receipt["total_jobs"]==24880 and receipt["shard_count"]==8
assert receipt["input_manifest_sha256"]["c2_new4220"]==anchors["manifest_4220_sha256"]
assert receipt["input_manifest_sha256"]["c2_new2000"]==anchors["manifest_2000_sha256"]
assert receipt["shard_sha256"][shard.name]==sha(shard)
assert b"\r" not in shard.read_bytes()
rows=list(csv.DictReader(shard.open(),delimiter="\t"))
assert len(rows)==3110
assert sum(r["package_key"]=="c2_new4220" for r in rows)==2110
assert sum(r["package_key"]=="c2_new2000" for r in rows)==1000
assert len({r["job_id"] for r in rows})==3110
PY_DISPATCH_GATE
mapfile -t DISPATCH < <(awk -F'\t' 'NR>1{gsub(/\r$/, "", $2); print $1 "\t" $2}' "$SAFE_MANIFEST")
[[ ${#DISPATCH[@]} -eq 3110 ]] || {
    echo "unexpected shard size ${#DISPATCH[@]} expected 3110" >&2
    exit 65
}

package_paths() {
    case "$1" in
        c2_new4220)
            LOCAL_PROJECT="$LOCAL_4220"
            PACKAGE_PUBLISH="$PUBLISH_ROOT/batch_4220"
            ;;
        c2_new2000)
            LOCAL_PROJECT="$LOCAL_2000"
            PACKAGE_PUBLISH="$PUBLISH_ROOT/batch_2000"
            ;;
        *)
            echo "unknown package key: $1" >&2
            return 64
            ;;
    esac
}

published_success() {
    local package_key=$1 job_id=$2
    package_paths "$package_key"
    local status="$PACKAGE_PUBLISH/status/jobs/$job_id.json"
    local result="$PACKAGE_PUBLISH/results/$job_id/job_result.json"
    local compact="$PACKAGE_PUBLISH/compressed_queue/$job_id.tar.gz"
    [[ -f "$status" && -f "$result" ]] || return 1
    "$LOCAL_ENV/bin/python" - "$status" "$result" "$compact" <<'PY' >/dev/null 2>&1
import json, pathlib, sys
s=json.load(open(sys.argv[1])); r=json.load(open(sys.argv[2]))
compact=pathlib.Path(sys.argv[3])
ok=s.get("status")=="SUCCESS" and r.get("state")=="SUCCESS"
ok=ok and (compact.is_file() or r.get("offloaded_to_node1") is True)
raise SystemExit(0 if ok else 1)
PY
}

publish_status_last() {
    local package_key=$1 job_id=$2
    package_paths "$package_key"
    local src="$LOCAL_PROJECT/status/jobs/$job_id.json"
    [[ -f "$src" ]] || return 0
    local tmp="$PACKAGE_PUBLISH/status/jobs/.$job_id.json.partial.$$"
    cp -f "$src" "$tmp"
    mv -f "$tmp" "$PACKAGE_PUBLISH/status/jobs/$job_id.json"
}

run_one() {
    local package_key=$1 job_id=$2
    package_paths "$package_key"
    local log="$PACKAGE_PUBLISH/worker_logs/${job_id}.log"
    local scratch="$LOCAL_SCRATCH/$package_key/$job_id"
    local rc=1 call attempts tmp_result tmp_compact
    mkdir -p "$scratch"
    if published_success "$package_key" "$job_id"; then
        return 100
    fi
    [[ -f "$PACKAGE_PUBLISH/status/jobs/$job_id.json" ]] &&
        cp -f "$PACKAGE_PUBLISH/status/jobs/$job_id.json" "$LOCAL_PROJECT/status/jobs/$job_id.json"
    for call in 1 2; do
        if PVRIG_PROJECT_ROOT="$LOCAL_PROJECT" PVRIG_LOCAL_SCRATCH_ROOT="$scratch" \
            "$LOCAL_ENV/bin/python" "$LOCAL_PROJECT/scripts/run_job.py" \
            "$job_id" --max-attempts 2 >>"$log" 2>&1; then
            rc=0
            break
        else
            rc=$?
        fi
        attempts=$("$LOCAL_ENV/bin/python" - "$LOCAL_PROJECT/status/jobs/$job_id.json" <<'PY'
import json, sys
try: print(int(json.load(open(sys.argv[1])).get("attempts", 0)))
except Exception: print(0)
PY
)
        (( attempts < 2 )) || break
    done

    if [[ "$rc" == 0 ]]; then
        tmp_result="$PACKAGE_PUBLISH/results/.$job_id.partial.$$"
        rm -rf "$tmp_result"
        cp -a "$LOCAL_PROJECT/results/$job_id" "$tmp_result"
        rm -rf "$PACKAGE_PUBLISH/results/$job_id"
        mv "$tmp_result" "$PACKAGE_PUBLISH/results/$job_id"

        tmp_compact="$PACKAGE_PUBLISH/compressed_queue/.$job_id.tar.gz.partial.$$"
        rm -f "$tmp_compact"
        "$LOCAL_ENV/bin/python" "$DEPLOY_ROOT/compact_run_evidence.py" \
            --project-root "$LOCAL_PROJECT" --job-id "$job_id" \
            --output "$tmp_compact" >>"$log" 2>&1
        mv -f "$tmp_compact" "$PACKAGE_PUBLISH/compressed_queue/$job_id.tar.gz"
        rm -rf "$LOCAL_PROJECT/runs/$job_id"
    fi
    publish_status_last "$package_key" "$job_id"
    return "$rc"
}

failures=0
skipped=0
pids=()
drain_batch() {
    local pid rc
    for pid in "${pids[@]}"; do
        if wait "$pid"; then rc=0; else rc=$?; fi
        if [[ "$rc" == 100 ]]; then
            skipped=$((skipped + 1))
        elif [[ "$rc" != 0 ]]; then
            failures=$((failures + 1))
        fi
    done
    pids=()
}

for row in "${DISPATCH[@]}"; do
    package_key=${row%%$'\t'*}
    job_id=${row#*$'\t'}
    run_one "$package_key" "$job_id" &
    pids+=("$!")
    [[ ${#pids[@]} -lt "$NODE_CONCURRENCY" ]] || drain_batch
done
[[ ${#pids[@]} -eq 0 ]] || drain_batch

marker="$PUBLISH_ROOT/markers/c2_new6220_dualseed_shard_${SHARD_INDEX}.done"
printf 'array_job=%s shard=%s assigned=%s skipped=%s failures=%s completed_at=%s\n' \
    "${SLURM_ARRAY_JOB_ID:-manual}" "$SHARD_INDEX" "${#DISPATCH[@]}" \
    "$skipped" "$failures" "$(date -u +%FT%TZ)" > "$marker"
exit "$failures"
