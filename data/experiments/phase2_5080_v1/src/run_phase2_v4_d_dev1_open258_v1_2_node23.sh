#!/usr/bin/env bash
set -euo pipefail

ROOT=${PVRIG_V4D_DEV1_V12_ROOT:-/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717}
SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
PYTHON=${PVRIG_V4D_DEV1_V12_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
FREEZE=${PVRIG_V4D_DEV1_V12_LAUNCH_FREEZE:-$ROOT/governance/phase2_v4_d_dev1_open258_v1_2_launch_authorized_freeze.json}
PREREG=$ROOT/governance/phase2_v4_d_dev1_open258_v1_2_pose_validity_recovery_preregistration.json
DIAGNOSTIC=$ROOT/governance/phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2.json
DIAGNOSTIC_RECEIPT=$ROOT/governance/phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2_run_receipt.json
CLARIFICATION=$ROOT/governance/phase2_v4_d_dev1_open258_v1_2_invalid_pair_canonicalization_clarification.json
FALLBACK=$ROOT/governance/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json
V1_FAILURE=$ROOT/governance/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json
V11_FAILURE=$ROOT/governance/phase2_v4_d_dev1_open258_v1_1_remote_runtime_failure_receipt.json
BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258_v1_2.py
V1_BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258.py
V11_BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258_v1_1.py
V1_HELPER=$ROOT/scripts/prepare_phase2_v4_d_open_teacher.py
PRIOR=$ROOT/governance/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv
OUTPUT=$ROOT/release_v1_2
STATUS=$ROOT/status/dev1_v1_2_release_status.json
EXPECTED_ROOT=/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_2_20260717

[[ "$ROOT" == "$EXPECTED_ROOT" ]] || { echo "unexpected_root:$ROOT" >&2; exit 2; }
[[ -x "$PYTHON" ]] || { echo "python_not_executable:$PYTHON" >&2; exit 2; }
mkdir -p "$ROOT/status" "$ROOT/logs"
exec 9>"$ROOT/status/dev1_v1_2_build.lock"
flock -n 9 || exit 3
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || { echo "output_preexists:$OUTPUT" >&2; exit 4; }

"$PYTHON" - "$FREEZE" "$PREREG" "$DIAGNOSTIC" "$DIAGNOSTIC_RECEIPT" "$CLARIFICATION" \
  "$FALLBACK" "$V1_FAILURE" "$V11_FAILURE" "$BUILDER" "$V1_BUILDER" "$V11_BUILDER" "$V1_HELPER" "$PRIOR" <<'PY'
import hashlib, json, os, stat, sys
from pathlib import Path
paths = list(map(Path, sys.argv[1:]))
freeze, *inputs = paths

def snapshot(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise SystemExit(f"not_regular:{path}")
        chunks = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after) or len(raw) != before.st_size:
            raise SystemExit(f"changed_during_read:{path}")
        return raw
    finally:
        os.close(fd)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

raw_by_path = {path: snapshot(path) for path in paths}
f = json.loads(raw_by_path[freeze])
if f.get("status") != "FROZEN_FOR_DEV1_V1_2_REMOTE_EXECUTION":
    raise SystemExit("v1_2_launch_freeze_status_invalid")
if f.get("remote_execution_authorized") is not True:
    raise SystemExit("v1_2_launch_not_authorized")
if f.get("independent_implementation_review_status") != "PASS":
    raise SystemExit("v1_2_independent_review_not_pass")
if f.get("formal_v4_f_unlock_eligible") is not False:
    raise SystemExit("v1_2_formal_unlock_true")
if f.get("test32_raw_job_files_opened") != 0 or f.get("test32_metric_values_read") != 0 or f.get("test32_label_rows_emitted") != 0:
    raise SystemExit("v1_2_test32_boundary_invalid")
if f.get("source_evaluator_status") != "FAIL" or f.get("source_evaluator_unlockable") is not False:
    raise SystemExit("v1_2_source_evaluator_boundary_invalid")
expected = {
    paths[1]: "cbc70313d47ff5f0fc99476a5a0b108abc0e94e4ecaf05d53663e1b06adf62a1",
    paths[2]: "ef31a254de83dec7aa0f073154c8a7176eaa43c406df0aec8c9fd65df448aead",
    paths[3]: "1a99a0a498bb44c7d64b379a553a1d117b4ad9212e6d204fa73fb0f943c58f2f",
    paths[4]: "1fb8f1bdfdf8f8869cc1c80a477a1e1f4f74246c555925be4fa1c1ebc380b918",
    paths[5]: "36c7e11e3a727512d04a8797122efedc10b277bf58b5b997c09315209fdc6481",
    paths[6]: "247b6ec684a60ada85fa38834aa176e3f6a797a379938a5dabd5755bdd041720",
    paths[7]: "7dbf808d31985cd7555ebadec0c294583b95fc32cb76b26d63b6b06adc74bea7",
    paths[8]: "872bee4bf27b894244f14b31f43b03f877a1cff89a084f6272c0cbccd026ba9b",
    paths[9]: "04fd7addb8f1bc16f0cd3c0d113d9cbeb2cf23a25b5a39fe0113bfd2cf65d276",
    paths[10]: "cadc38165b272fde783f6afcf936f3c2c14cd3f57c43a6cb16148cc7413a9e82",
    paths[11]: "8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145",
    paths[12]: "21b4c6a38056d6777de5b5efbfcd5887b45098c637cab61489072d1e6e7783cd",
}
for path, expected_sha in expected.items():
    if digest(raw_by_path[path]) != expected_sha:
        raise SystemExit(f"hash_mismatch:{path.name}")
files = f.get("files") or {}
for key, path in {
    "preregistration": paths[1], "diagnostic": paths[2], "diagnostic_receipt": paths[3],
    "canonical_clarification": paths[4], "fallback_evidence": paths[5],
    "v1_failure_receipt": paths[6], "v1_1_failure_receipt": paths[7],
    "builder": paths[8], "v1_builder": paths[9], "v1_1_builder": paths[10],
    "v1_formula_helper": paths[11], "generic_prior": paths[12],
}.items():
    if (files.get(key) or {}).get("sha256") != digest(raw_by_path[path]):
        raise SystemExit(f"freeze_hash_mismatch:{key}")
PY

set +e
"$PYTHON" "$BUILDER" \
  --preregistration "$PREREG" --diagnostic "$DIAGNOSTIC" \
  --diagnostic-receipt "$DIAGNOSTIC_RECEIPT" --canonical-clarification "$CLARIFICATION" \
  --fallback-evidence "$FALLBACK" --v1-failure-receipt "$V1_FAILURE" \
  --v1-1-failure-receipt "$V11_FAILURE" --v1-builder "$V1_BUILDER" \
  --v1-1-builder "$V11_BUILDER" --v1-formula-helper "$V1_HELPER" \
  --split-manifest "$SOURCE/inputs/fullqc290_split_manifest.tsv" \
  --job-manifest "$SOURCE/manifests/docking_jobs.tsv" \
  --job-results "$SOURCE/reports/job_results.tsv" --pose-scores "$SOURCE/reports/pose_scores.tsv" \
  --protocol-core-lock "$SOURCE/PROTOCOL_CORE_LOCK.json" --protocol-lock "$SOURCE/PROTOCOL_LOCK.json" \
  --stability-spec "$SOURCE/config/evaluator_stability_gate.json" --results-root "$SOURCE/results" \
  --evaluator "$SOURCE/reports/EVALUATOR_STABLE.json" --generic-prior "$PRIOR" --output-dir "$OUTPUT" \
  >"$ROOT/logs/dev1_v1_2_builder.stdout.log" 2>"$ROOT/logs/dev1_v1_2_builder.stderr.log"
rc=$?
set -e
if (( rc != 0 )); then
  printf '{"status":"FAILED_DEV1_V1_2_BUILD","exit_code":%d,"formal_v4_f_unlock_eligible":false,"test32_raw_job_files_opened":0,"test32_metric_values_read":0}\n' "$rc" > "$STATUS"
  exit "$rc"
fi

test -s "$OUTPUT/v4d_dev1_open258_delivery_v1_2.tar.gz"
printf '{"status":"DEV1_V1_2_RELEASE_READY_TEST32_SEALED","formal_v4_f_unlock_eligible":false,"test32_raw_job_files_opened":0,"test32_metric_values_read":0}\n' > "$STATUS"
