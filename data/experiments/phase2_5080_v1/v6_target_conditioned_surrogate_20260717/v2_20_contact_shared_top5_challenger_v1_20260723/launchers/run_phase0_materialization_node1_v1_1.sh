#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v2_20_phase0_train_contact_teacher_v1_20260723
PYTHON=/data/qlyu/anaconda3/bin/python
FREEZE=$ROOT/IMPLEMENTATION_FREEZE_PHASE0_V1_1.json
EXPECTED_FREEZE_SHA=0ec60d77a0afb4e8f31e0ca1991e8d16a5082127fc8aa4d713e84996e9fb78b5
OUTPUT=$ROOT/release/train_contact_teacher_v1_1
LOG=$ROOT/PHASE0_MATERIALIZATION_V1_1.log
STATUS=$ROOT/PHASE0_MATERIALIZATION_TERMINAL_V1_1.json
test "$(sha256sum "$FREEZE" | awk '{print $1}')" = "$EXPECTED_FREEZE_SHA"
test ! -e "$OUTPUT"
test ! -e "$STATUS"
mkdir -p "$ROOT/release"
ARGS=(
  --scalar-teacher "$ROOT/inputs/scalar/primary_D1_canonical10644_teacher.tsv"
  --split-manifest "$ROOT/inputs/scalar/primary_D1_canonical10644_split_manifest.json"
  --phase0-contract "$ROOT/PHASE0_TEACHER_MATERIALIZATION_CONTRACT_V1_1.json"
  --implementation-freeze "$FREEZE"
  --v4d-pair "$ROOT/inputs/v4d/v4d_open226_multi_seed_pair_contact_teacher_v2.tsv.gz"
  --v4d-marginal "$ROOT/inputs/v4d/v4d_open226_multi_seed_residue_marginal_teacher_v2.tsv.gz"
  --v4d-receipt "$ROOT/inputs/v4d/RUN_RECEIPT.json"
  --v4h-pair "$ROOT/inputs/v4h/v4h_adaptive_residue_pair_contact_teacher.tsv.gz"
  --v4h-marginal "$ROOT/inputs/v4h/v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz"
  --v4h-state "$ROOT/inputs/v4h/v4h_adaptive_candidate_state.tsv.gz"
  --v4h-receipt "$ROOT/inputs/v4h/RUN_RECEIPT.json"
  --v29-release /data1/qlyu/projects/pvrig_v29_canonical_training_release_v1_20260721
  --v29-pose-root /data/qlyu/projects/pvrig_v29_docking25k_v1_20260720/runs
  --target-cache "$ROOT/inputs/target/target_graph_cache_v2.npz"
  --target-manifest "$ROOT/inputs/target/target_graph_manifest_v2.tsv"
  --target-receipt "$ROOT/inputs/target/target_graph_receipt_v2.json"
  --output-dir "$OUTPUT"
  --workers 12
)
set +e
"$PYTHON" "$ROOT/src/materialize_v220_train_contact_teacher_v1_1.py" "${ARGS[@]}" > "$LOG" 2>&1
RC=$?
set -e
if [ "$RC" -eq 0 ]; then
  VERIFY=$("$PYTHON" "$ROOT/src/materialize_v220_train_contact_teacher_v1_1.py" "${ARGS[@]}" --verify-only)
  STATUS_VALUE=PASS_PHASE0_TRAIN_ONLY_TEACHER
else
  VERIFY='{}'
  STATUS_VALUE=FAILED_PHASE0_TRAIN_ONLY_TEACHER
fi
"$PYTHON" - "$STATUS" "$STATUS_VALUE" "$RC" "$LOG" "$OUTPUT" "$VERIFY" <<'PY'
import hashlib,json,sys
from pathlib import Path
out,status,rc,log,release,verify=sys.argv[1:]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else ''
payload={'schema_version':'pvrig_v2_20_phase0_materialization_terminal_v1_1','status':status,'return_code':int(rc),'oof_training_authorized':False,'log_path':log,'log_sha256':sha(log),'release_path':release,'release_receipt_sha256':sha(Path(release)/'MATERIALIZATION_RECEIPT.json'),'sha256sums_sha256':sha(Path(release)/'SHA256SUMS'),'verification':json.loads(verify)}
Path(out).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
chmod 0444 "$LOG" "$STATUS"
cat "$STATUS"
exit "$RC"
