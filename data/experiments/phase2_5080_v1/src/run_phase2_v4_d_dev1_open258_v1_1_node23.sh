#!/usr/bin/env bash
set -euo pipefail

ROOT=${PVRIG_V4D_DEV1_V11_ROOT:-/data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_1_20260717}
SOURCE=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
PYTHON=${PVRIG_V4D_DEV1_V11_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}
FREEZE=${PVRIG_V4D_DEV1_V11_LAUNCH_FREEZE:-$ROOT/governance/phase2_v4_d_dev1_open258_v1_1_launch_authorized_freeze.json}
PREREG=$ROOT/governance/phase2_v4_d_dev1_open258_v1_1_recovery_preregistration.json
EVIDENCE=$ROOT/governance/phase2_v4_d_dev1_open258_v1_1_terminal_fallback_projection_evidence.json
V1_FAILURE=$ROOT/governance/phase2_v4_d_dev1_open258_v1_remote_runtime_failure_receipt.json
BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258_v1_1.py
V1_BUILDER=$ROOT/scripts/prepare_phase2_v4_d_dev1_open258.py
V1_HELPER=$ROOT/scripts/prepare_phase2_v4_d_open_teacher.py
PRIOR=$ROOT/governance/v4d_dev1_fullqc290_label_free_generic_prior_v1.csv
OUTPUT=$ROOT/release_v1_1
STATUS=$ROOT/status/dev1_v1_1_release_status.json
[[ "$ROOT" == /data/qlyu/projects/pvrig_v4_d_dev1_open258_v1_1_20260717 ]] || exit 2
mkdir -p "$ROOT/status" "$ROOT/logs"
exec 9>"$ROOT/status/dev1_v1_1_build.lock"; flock -n 9 || exit 3
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || exit 4
"$PYTHON" - "$FREEZE" "$PREREG" "$EVIDENCE" "$V1_FAILURE" "$BUILDER" "$V1_BUILDER" "$V1_HELPER" <<'PY'
import hashlib,json,stat,sys
from pathlib import Path
paths=list(map(Path,sys.argv[1:])); freeze,*inputs=paths
def d(p): return hashlib.sha256(p.read_bytes()).hexdigest()
for p in paths:
 if not stat.S_ISREG(p.lstat().st_mode): raise SystemExit(f"not_regular:{p}")
f=json.loads(freeze.read_text())
if f.get("status")!="FROZEN_FOR_DEV1_V1_1_REMOTE_EXECUTION" or f.get("remote_execution_authorized") is not True: raise SystemExit("v1_1_launch_authorization_missing")
if f.get("test32_raw_job_files_opened")!=0 or f.get("test32_metric_values_read")!=0 or f.get("formal_v4_f_unlock_eligible") is not False: raise SystemExit("v1_1_boundary_invalid")
expected={
 paths[1]:"e57f08f266f53cc966d7dca34366310742ca4889a3c5173972105bb30734879d",
 paths[2]:"36c7e11e3a727512d04a8797122efedc10b277bf58b5b997c09315209fdc6481",
 paths[3]:"247b6ec684a60ada85fa38834aa176e3f6a797a379938a5dabd5755bdd041720",
 paths[4]:"cadc38165b272fde783f6afcf936f3c2c14cd3f57c43a6cb16148cc7413a9e82",
 paths[5]:"04fd7addb8f1bc16f0cd3c0d113d9cbeb2cf23a25b5a39fe0113bfd2cf65d276",
 paths[6]:"8adb3c4e1de37bbaaf469dfb967176d2c49d40f353e21a3f028baa20ea8e4145"}
for p,h in expected.items():
 if d(p)!=h: raise SystemExit(f"hash_mismatch:{p.name}")
files=f.get("files") or {}
for key,p in (("preregistration",paths[1]),("fallback_evidence",paths[2]),("v1_failure_receipt",paths[3]),("builder",paths[4]),("v1_builder",paths[5]),("v1_formula_helper",paths[6])):
 if (files.get(key) or {}).get("sha256")!=d(p): raise SystemExit(f"freeze_hash_mismatch:{key}")
PY
"$PYTHON" "$BUILDER" --preregistration "$PREREG" --fallback-evidence "$EVIDENCE" \
 --v1-failure-receipt "$V1_FAILURE" --v1-builder "$V1_BUILDER" --v1-formula-helper "$V1_HELPER" \
 --split-manifest "$SOURCE/inputs/fullqc290_split_manifest.tsv" --job-manifest "$SOURCE/manifests/docking_jobs.tsv" \
 --job-results "$SOURCE/reports/job_results.tsv" --pose-scores "$SOURCE/reports/pose_scores.tsv" \
 --protocol-core-lock "$SOURCE/PROTOCOL_CORE_LOCK.json" --protocol-lock "$SOURCE/PROTOCOL_LOCK.json" \
 --stability-spec "$SOURCE/config/evaluator_stability_gate.json" --results-root "$SOURCE/results" \
 --evaluator "$SOURCE/reports/EVALUATOR_STABLE.json" --generic-prior "$PRIOR" --output-dir "$OUTPUT" \
 >"$ROOT/logs/dev1_v1_1_builder.stdout.log" 2>"$ROOT/logs/dev1_v1_1_builder.stderr.log"
test -s "$OUTPUT/v4d_dev1_open258_delivery_v1_1.tar.gz"
printf '{"status":"DEV1_V1_1_RELEASE_READY_TEST32_SEALED","formal_v4_f_unlock_eligible":false,"test32_raw_job_files_opened":0,"test32_metric_values_read":0}\n' > "$STATUS"
