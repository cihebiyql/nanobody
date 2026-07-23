#!/usr/bin/env bash
set -euo pipefail
umask 027

DEPLOY_ROOT="${PVRIG_C2_NEW_DEPLOY_ROOT:-$HOME/.local/share/bxcpu_c2_new6220_dualseed_v1_20260723}"
PUBLISH_ROOT="${PVRIG_C2_NEW_PUBLISH_ROOT:-$HOME/pvrig_c2_new6220_dualreceptor_2seed_v1_20260723_bxcpu_results}"
ANCHORS="$DEPLOY_ROOT/FROZEN_INPUT_ANCHORS.json"
ARCHIVE="$HOME/pvrig_c2_new6220_dualreceptor_2seed_handoffs_v2_20260723.tar.gz"
WORKER="$DEPLOY_ROOT/bxcpu_c2_new6220_dualseed_eight_node_worker.sh"
PREFLIGHT="$DEPLOY_ROOT/run_slurm_preflight.sh"
AUDIT="$DEPLOY_ROOT/run_terminal_audit.sh"
RECEIPT="$PUBLISH_ROOT/markers/SUBMISSION_RECEIPT.retry1.txt"
PREFLIGHT_ID_FILE="$PUBLISH_ROOT/markers/PREFLIGHT_JOB_ID.retry1"
ARRAY_ID_FILE="$PUBLISH_ROOT/markers/ARRAY_JOB_ID.retry1"
AUDIT_ID_FILE="$PUBLISH_ROOT/markers/AUDIT_JOB_ID.retry1"

mkdir -p "$PUBLISH_ROOT/markers" "$PUBLISH_ROOT/reports" \
    "$PUBLISH_ROOT/batch_4220/status/jobs" "$PUBLISH_ROOT/batch_4220/results" \
    "$PUBLISH_ROOT/batch_4220/worker_logs" "$PUBLISH_ROOT/batch_4220/compressed_queue" \
    "$PUBLISH_ROOT/batch_2000/status/jobs" "$PUBLISH_ROOT/batch_2000/results" \
    "$PUBLISH_ROOT/batch_2000/worker_logs" "$PUBLISH_ROOT/batch_2000/compressed_queue"

mapfile -t FROZEN < <(python3 - "$ANCHORS" "$ARCHIVE" "$DEPLOY_ROOT" <<'PY'
import hashlib,json,pathlib,sys
anchors=json.load(open(sys.argv[1]))
archive=pathlib.Path(sys.argv[2]); deploy=pathlib.Path(sys.argv[3])
def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
assert anchors["status"]=="FROZEN_READY_FOR_DEPENDENT_SUBMISSION"
assert anchors["expected_jobs"]==24880
assert anchors["shards"]==8 and anchors["jobs_per_shard"]==3110
assert sha(archive)==anchors["archive_sha256"]
for relative, expected in anchors["deployment_file_sha256"].items():
    assert sha(deploy/relative)==expected, relative
for key in (
    "archive_sha256","root_receipt_sha256",
    "manifest_4220_sha256","manifest_2000_sha256",
):
    print(anchors[key])
print(sha(sys.argv[1]))
PY
)
ARCHIVE_SHA=${FROZEN[0]}
ROOT_RECEIPT_SHA=${FROZEN[1]}
MANIFEST_4220_SHA=${FROZEN[2]}
MANIFEST_2000_SHA=${FROZEN[3]}
ANCHORS_SHA=${FROZEN[4]}

if [[ -s "$RECEIPT" ]]; then
    grep -Fx "archive_sha256=$ARCHIVE_SHA" "$RECEIPT" >/dev/null
    grep -Fx "anchors_sha256=$ANCHORS_SHA" "$RECEIPT" >/dev/null
    previous_array=$(awk -F= '$1=="array_job_id"{print $2}' "$RECEIPT")
    [[ -n "$previous_array" ]]
    sacct -n -X -j "$previous_array" --format=JobID,JobName,State -P | \
        grep -q 'pvrig-c2new-r1-24880'
    cat "$RECEIPT"
    exit 0
fi

sacct -n -X -j 11942310 --format=JobID,JobName,User,Partition -P | \
    python3 -c '
import sys
rows=[line.strip().split("|") for line in sys.stdin if line.strip()]
ids={row[0] for row in rows if row[1]=="pvrig-top7500-25k"}
assert ids=={f"11942310_{i}" for i in range(1,9)}, ids
assert all(row[2]=="als001821" and row[3]=="amd_256q" for row in rows if row[1]=="pvrig-top7500-25k")
'

COMMON_EXPORT="ALL,PVRIG_C2_NEW_DEPLOY_ROOT=$DEPLOY_ROOT,PVRIG_C2_NEW_PUBLISH_ROOT=$PUBLISH_ROOT,PVRIG_C2_NEW_BUNDLE_ARCHIVE=$ARCHIVE,PVRIG_C2_NEW_ARCHIVE_SHA256=$ARCHIVE_SHA,PVRIG_C2_NEW_ROOT_RECEIPT_SHA256=$ROOT_RECEIPT_SHA,PVRIG_C2_NEW_4220_MANIFEST_SHA256=$MANIFEST_4220_SHA,PVRIG_C2_NEW_2000_MANIFEST_SHA256=$MANIFEST_2000_SHA,PVRIG_C2_NEW_ANCHORS_SHA256=$ANCHORS_SHA"

if [[ ! -s "$PREFLIGHT_ID_FILE" ]]; then
    preflight=$(sbatch --parsable --partition=amd_256q --job-name=pvrig-c2new-r1-preflight \
        --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=16G --time=00:30:00 \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" "$PREFLIGHT")
    preflight=${preflight%%;*}
    printf '%s\n' "$preflight" > "$PREFLIGHT_ID_FILE.tmp"
    mv "$PREFLIGHT_ID_FILE.tmp" "$PREFLIGHT_ID_FILE"
    echo "PREFLIGHT_SUBMITTED job_id=$preflight"
    exit 0
fi
preflight=$(cat "$PREFLIGHT_ID_FILE")
preflight_state=$(sacct -n -X -j "$preflight" --format=State | awk 'NF{print $1; exit}' | cut -d+ -f1)
case "$preflight_state" in
    COMPLETED) ;;
    PENDING|RUNNING|CONFIGURING|COMPLETING|"")
        echo "WAITING_PREFLIGHT job_id=$preflight state=${preflight_state:-UNKNOWN}"
        exit 0
        ;;
    *)
        echo "PREFLIGHT_FAILED job_id=$preflight state=$preflight_state" >&2
        exit 67
        ;;
esac

old_dep=afterany
for shard in {1..8}; do
    old_dep+=:11942310_${shard}
done
dependency="afterok:${preflight},${old_dep}"

if [[ ! -s "$ARRAY_ID_FILE" ]]; then
    [[ $(squeue -h -u "$USER" -n pvrig-c2new-r1-24880 | wc -l) -eq 0 ]] || {
        echo "active campaign exists without frozen array ID" >&2
        exit 66
    }
    array=$(sbatch --parsable --dependency="$dependency" --partition=amd_256q \
        --job-name=pvrig-c2new-r1-24880 --nodes=1 --ntasks=1 --cpus-per-task=64 \
        --mem=230G --exclusive --time=24:00:00 --array=1-8%8 \
        --output="$PUBLISH_ROOT/slurm-%x-%A_%a.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%A_%a.err" \
        --export="$COMMON_EXPORT,PVRIG_C2_NEW_NODE_CONCURRENCY=16" "$WORKER")
    array=${array%%;*}
    printf '%s\n' "$array" > "$ARRAY_ID_FILE.tmp"
    mv "$ARRAY_ID_FILE.tmp" "$ARRAY_ID_FILE"
    echo "ARRAY_SUBMITTED job_id=$array"
    exit 0
fi
array=$(cat "$ARRAY_ID_FILE")

audit_dep=afterany
for shard in {1..8}; do
    audit_dep+=:${array}_${shard}
done
if [[ ! -s "$AUDIT_ID_FILE" ]]; then
    audit=$(sbatch --parsable --dependency="$audit_dep" --partition=amd_256q \
        --job-name=pvrig-c2new-r1-audit --nodes=1 --ntasks=1 --cpus-per-task=1 \
        --mem=4G --time=01:00:00 \
        --output="$PUBLISH_ROOT/slurm-%x-%j.out" \
        --error="$PUBLISH_ROOT/slurm-%x-%j.err" \
        --export="$COMMON_EXPORT" "$AUDIT")
    audit=${audit%%;*}
    printf '%s\n' "$audit" > "$AUDIT_ID_FILE.tmp"
    mv "$AUDIT_ID_FILE.tmp" "$AUDIT_ID_FILE"
else
    audit=$(cat "$AUDIT_ID_FILE")
fi

printf 'status=SUBMITTED_RETRY1_AFTER_CRLF_FIX\npreflight_job_id=%s\narray_job_id=%s\naudit_job_id=%s\npredecessor_array_job_id=11942310\nfailed_attempt_array_job_id=11943265\nexpected_jobs=24880\nexpected_candidates=6220\narchive_sha256=%s\nanchors_sha256=%s\nresult_root=%s\nsubmitted_at=%s\n' \
    "$preflight" "$array" "$audit" "$ARCHIVE_SHA" "$ANCHORS_SHA" "$PUBLISH_ROOT" \
    "$(date -u +%FT%TZ)" | tee "$RECEIPT"
