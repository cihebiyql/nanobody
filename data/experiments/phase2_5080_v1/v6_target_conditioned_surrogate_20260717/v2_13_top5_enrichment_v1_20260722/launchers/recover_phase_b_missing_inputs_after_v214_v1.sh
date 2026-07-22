#!/usr/bin/env bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722
STATUS=$ROOT/status
INPUTS=$ROOT/inputs
RECOVERY=$ROOT/recovery/phase_b_missing_inputs_v1
FAILED_OUT=$ROOT/training/phase_b_multiseed
ARCHIVED_OUT=$ROOT/training/phase_b_multiseed_failed_missing_inputs_v1
BASELINE_SRC=/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/training/oof_seed43_v1/OOF_AGGREGATE/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv
LEGACY_SRC=/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/TRAIN_INNER_OOF_PREDICTIONS.tsv
BASELINE_SHA=2e0096a04cbedf724553e1ed11f82f768a2db0687e55b4feb0d50f58658da3da
LEGACY_SHA=e1a5553e67b0f2d60a4c690756f4f2cbe81de53a669dc41cf6fee883f4d8847b

mkdir -p "$STATUS" "$INPUTS" "$RECOVERY"
(cd "$ROOT" && sha256sum -c SHA256SUMS_PHASE_B_INPUT_RECOVERY_V1)

python3 - "$ROOT/PHASE_B_INPUT_RECOVERY_PREREGISTRATION_V1.json" "$STATUS/TERMINAL.json" <<'PY'
import json,pathlib,sys
pre=json.loads(pathlib.Path(sys.argv[1]).read_text())
terminal=json.loads(pathlib.Path(sys.argv[2]).read_text())
assert pre['status']=='FROZEN_OPERATIONAL_RECOVERY_AFTER_PHASE_A_UNSEAL_BEFORE_RECOVERY_EXECUTION'
assert pre['scientific_contract_changes'] is False
assert pre['input_access']=={'open_development_rows':0,'frozen_test_rows':0}
assert terminal['status']=='PASS_V2_13_TOP5_PHASE_A_COMPLETE'
assert terminal['open_development_access_count']==0 and terminal['frozen_test_access_count']==0
PY

test -f "$FAILED_OUT/logs/phase_a_selection.log"
grep -Fq 'regular_file_required:/data1/qlyu/projects/pvrig_v2_13_top5_ensemble_v1_20260722/inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv' "$FAILED_OUT/logs/phase_a_selection.log"
test "$(find "$FAILED_OUT" -type f | wc -l)" -eq 1
test ! -e "$ARCHIVED_OUT"
test ! -e "$FAILED_OUT/PHASE_A_SELECTION.json"

printf '%s  %s\n' "$BASELINE_SHA" "$BASELINE_SRC" | sha256sum -c -
printf '%s  %s\n' "$LEGACY_SHA" "$LEGACY_SRC" | sha256sum -c -
install -m 0444 "$BASELINE_SRC" "$INPUTS/.CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv.tmp"
install -m 0444 "$LEGACY_SRC" "$INPUTS/.TRAIN_INNER_OOF_PREDICTIONS.tsv.tmp"
mv "$INPUTS/.CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv.tmp" "$INPUTS/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv"
mv "$INPUTS/.TRAIN_INNER_OOF_PREDICTIONS.tsv.tmp" "$INPUTS/TRAIN_INNER_OOF_PREDICTIONS.tsv"
test -f "$INPUTS/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv" && test ! -L "$INPUTS/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv"
test -f "$INPUTS/TRAIN_INNER_OOF_PREDICTIONS.tsv" && test ! -L "$INPUTS/TRAIN_INNER_OOF_PREDICTIONS.tsv"
printf '%s  %s\n' "$BASELINE_SHA" "$INPUTS/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv" | sha256sum -c -
printf '%s  %s\n' "$LEGACY_SHA" "$INPUTS/TRAIN_INNER_OOF_PREDICTIONS.tsv" | sha256sum -c -

mv "$FAILED_OUT" "$ARCHIVED_OUT"
for name in PHASE_C1_TERMINAL.json HARD_NEGATIVE_C1_TERMINAL.json; do
  if [[ -f "$STATUS/$name" ]]; then mv "$STATUS/$name" "$RECOVERY/${name%.json}_STALE_PRE_RECOVERY.json"; fi
done

python3 - "$RECOVERY/INPUT_RECOVERY_RECEIPT.json" "$BASELINE_SRC" "$LEGACY_SRC" <<'PY'
import hashlib,json,pathlib,sys,datetime
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
out=pathlib.Path(sys.argv[1])
x={
 'schema_version':'pvrig_v2_13_phase_b_input_recovery_receipt_v1',
 'status':'PASS_INPUTS_RECOVERED_WAITING_V2_14_TERMINAL',
 'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'phase_b_training_started':False,
 'inputs':{
  'CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv':sha(sys.argv[2]),
  'TRAIN_INNER_OOF_PREDICTIONS.tsv':sha(sys.argv[3])},
 'input_access':{'open_development_rows':0,'frozen_test_rows':0}}
out.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
PY

printf '{"status":"WAITING_V2_14_TERMINAL_BEFORE_PHASE_B_RECOVERY","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_RECOVERY_LIVE_STATUS.json"
while [[ ! -f "$STATUS/V2_14_TERMINAL.json" ]]; do
  if [[ -f "$STATUS/V2_14_SUPERVISOR.pid" ]]; then
    pid=$(cat "$STATUS/V2_14_SUPERVISOR.pid")
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '{"status":"FAIL_V2_14_DIED_WITHOUT_TERMINAL"}\n' > "$STATUS/PHASE_B_RECOVERY_TERMINAL.json"
      exit 5
    fi
  fi
  sleep 60
done

printf '%s\n' "$$" > "$STATUS/PHASE_B_SUPERVISOR.pid"
printf '{"status":"RUNNING_RECOVERED_PHASE_B","timestamp":"%s"}\n' "$(date --iso-8601=seconds)" > "$STATUS/PHASE_B_RECOVERY_LIVE_STATUS.json"
bash "$ROOT/launchers/run_phase_b_node1_v1.sh"
test -f "$STATUS/PHASE_B_TERMINAL.json"

printf '%s\n' "$$" > "$STATUS/PHASE_C1_SUPERVISOR.pid"
bash "$ROOT/launchers/run_phase_c1_after_phase_b_node1_v1.sh"
test -f "$STATUS/PHASE_C1_TERMINAL.json"

printf '%s\n' "$$" > "$STATUS/HARD_NEGATIVE_C1_SUPERVISOR.pid"
bash "$ROOT/launchers/run_hard_negative_c1_after_phase_c1_node1_v1.sh"
test -f "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json"

python3 - "$STATUS/PHASE_B_TERMINAL.json" "$STATUS/PHASE_C1_TERMINAL.json" "$STATUS/HARD_NEGATIVE_C1_TERMINAL.json" > "$STATUS/PHASE_B_RECOVERY_TERMINAL.json" <<'PY'
import json,pathlib,sys
read=lambda p:json.loads(pathlib.Path(p).read_text())
print(json.dumps({
 'schema_version':'pvrig_v2_13_phase_b_recovery_terminal_v1',
 'status':'PASS_PHASE_B_RECOVERY_CHAIN_TERMINAL',
 'phase_b_status':read(sys.argv[1]).get('status'),
 'phase_c1_status':read(sys.argv[2]).get('status'),
 'hard_negative_c1_status':read(sys.argv[3]).get('status'),
 'input_access':{'open_development_rows':0,'frozen_test_rows':0}},indent=2,sort_keys=True))
PY
