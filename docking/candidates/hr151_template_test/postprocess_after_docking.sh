#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/d/work/抗体
WD=docking/candidates/hr151_template_test

# Expected after docking:
#   $WD/haddock3/top_models_aligned_to_8x6b/{model}_aligned_to_8x6b.pdb
#   $WD/reports/haddock3_top_model_mechanism_scores.csv
#   $WD/reports/cdr_region_occlusion/cdr3_occlusion_summary.csv

python "$ROOT/docking/success_case_validation/apply_blocker_judgment.py" \
  --occlusion-csv "$WD/reports/cdr_region_occlusion/cdr3_occlusion_summary.csv" \
  --mechanism-csv "$WD/reports/haddock3_top_model_mechanism_scores.csv" \
  --candidate-name hr151_template_test_8x6b \
  --format-context naked_vhh \
  --out-csv "$WD/reports/hr151_template_test_8x6b_blocker_classification.csv" \
  --out-md "$WD/reports/hr151_template_test_8x6b_blocker_classification.md"

# Optional but recommended: once top model names are known, run 9E6Y baseline and combine:
# python "$ROOT/docking/success_case_validation/score_reference_baseline.py" \
#   --models cluster_1_model_1,cluster_2_model_1 \
#   --pose-dir "$WD/haddock3/top_models_aligned_to_8x6b" \
#   --pose-pattern '{model}_aligned_to_8x6b.pdb' \
#   --output-pose-dir "$WD/haddock3/top_models_aligned_to_9e6y" \
#   --out-dir "$WD/reports/9e6y_baseline" \
#   --reference-pdb "$ROOT/data/structures/9E6Y.pdb" \
#   --baseline-label 9e6y \
#   --mobile-pvrig-chain B \
#   --reference-pvrig-chain A \
#   --vhh-chain A \
#   --reference-pvrl2-chain D \
#   --pair-map-csv "$ROOT/data/structures/PVRIG_hotspot_set_v1.csv" \
#   --mobile-ref-column pdb_8x6b_ref \
#   --reference-ref-column pdb_9e6y_ref \
#   --hotspots-csv "$ROOT/data/structures/PVRIG_hotspot_set_v1.csv" \
#   --hotspot-ref-column pdb_9e6y_ref \
#   --cdr1 26-35 --cdr2 53-59 --cdr3 98-116 \
#   --rank-score-csv "$WD/reports/haddock3_top_model_mechanism_scores.csv"
