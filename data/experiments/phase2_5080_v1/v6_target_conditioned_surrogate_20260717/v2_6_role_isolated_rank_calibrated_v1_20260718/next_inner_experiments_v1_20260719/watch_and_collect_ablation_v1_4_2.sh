#!/usr/bin/env bash
set -euo pipefail
runtime=/data1/qlyu/projects/pvrig_v2_6_contact_ablation_8epoch_runtime_v1_4_2_20260719
package=/data1/qlyu/projects/pvrig_v2_6_next_inner_experiments_v1_20260719
output=/data1/qlyu/projects/pvrig_v2_6_open_inner_early_enrichment_ablation_v1_4_2_20260719
while [[ ! -f "${runtime}/TERMINAL.json" ]]; do sleep 30; done
/data1/qlyu/software/envs/pvrig-v6-tc/bin/python - "${runtime}/TERMINAL.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
assert x['status']=='PASS_ALL_SIX_CONTACT_ABLATION_JOBS', x
assert x['outer_test_truth_access_count']==x['outer_metrics_access_count']==x['v4_f_test32_access_count']==0
PY
exec /data1/qlyu/software/envs/pvrig-v6-tc/bin/python "${package}/collect_early_enrichment_v1.py"  --experiment-manifest "${package}/EXPERIMENT_MANIFEST_ABLATION_V1_4_2.json"  --expected-experiment-manifest-sha256 "db7a4c5361656d62637fa4172b4c2d66970d8f68a7938abc67737d0d161c0a6a"  --training-tsv /data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718/inputs/split_training/outer_0_inner_0.tsv  --expected-training-tsv-sha256 5abacbe69e85a5f6e3a13d6af23ae7e2b2903d59554dbce46e14ea165acc4d21  --split-manifest /data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718/plan/trainer_splits/outer_0_inner_0.json  --expected-split-manifest-sha256 11b3f0f394fa3057b3e3f7fec4d91ecf677f2a3546fab223d727bf9f707d219d  --output-dir "${output}"
