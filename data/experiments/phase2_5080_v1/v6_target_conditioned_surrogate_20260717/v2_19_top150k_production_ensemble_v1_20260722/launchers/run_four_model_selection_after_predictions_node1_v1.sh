#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
SCRIPT="$ROOT/code/src/select_top150k_four_model_v1.py"
OUTPUT="$ROOT/four_model_preliminary_top7500_v1"
mkdir -p "$ROOT/status" "$ROOT/logs"
printf '{"status":"WAITING_FOR_S0_M2_L1_B","started_at":"%s"}\n' "$(date -u +%FT%TZ)" > "$ROOT/status/FOUR_MODEL_SELECTOR_WATCHER.json"
for _ in $(seq 1 25920); do
  [[ -f "$ROOT/status/M2_S0M2_TERMINAL.json" && -f "$ROOT/status/GRAPH_L1_B_TERMINAL.json" ]] && break
  sleep 10
done
[[ -f "$ROOT/status/M2_S0M2_TERMINAL.json" && -f "$ROOT/status/GRAPH_L1_B_TERMINAL.json" ]]
python3 "$SCRIPT" \
  --stage0 "$ROOT/stage0_label_free_priors_v1/STAGE0_LABEL_FREE_PRIORS.tsv" \
  --multimodal "$ROOT/s0_m2_predictions_full150k_v1/PRODUCTION_PREDICTIONS_RANK_READY.tsv" \
  --l1 "$ROOT/l1_5fold_predictions_full150k_v1/clean_attention_checkpoint_ensemble_predictions.tsv" \
  --b "$ROOT/b_4seed_predictions_full150k_v1/clean_attention_checkpoint_ensemble_predictions.tsv" \
  --expected-rows 150000 --stage1-rows 30000 --final-rows 7500 \
  --exploitation-rows 6750 --rescue-rows 500 --diversity-rows 250 \
  --output-dir "$OUTPUT" > "$ROOT/logs/four_model_selection_v1.log" 2>&1
cp "$OUTPUT/RUN_RECEIPT.json" "$ROOT/status/FOUR_MODEL_SELECTOR_TERMINAL.json"
