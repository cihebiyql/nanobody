#!/usr/bin/env bash
set -euo pipefail

REMOTE_ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
CODE_ROOT=$REMOTE_ROOT/code_v1_5
RESIDUE_ROOT=$CODE_ROOT/residue_v1
DEPLOY_ROOT=$REMOTE_ROOT/deployment_v1_5
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
TRAINER=$RESIDUE_ROOT/src/train_nested_residue_surrogate_v1_5.py
COLLECTOR=$RESIDUE_ROOT/src/collect_residue_oof_v1_5.py
FREEZE=$RESIDUE_ROOT/IMPLEMENTATION_FREEZE_V1_5.json
MATRIX=$DEPLOY_ROOT/RESIDUE_PRODUCTION_MATRIX_V1_2.json
GOVERNANCE=$CODE_ROOT/PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json
TRAIN=$REMOTE_ROOT/inputs_v1_2/full1507/v6_supervised1507.tsv
TRAIN_RECEIPT=$REMOTE_ROOT/inputs_v1_2/full1507/v6_training_table_receipt.json
CONTACT_DIR=$REMOTE_ROOT/inputs_v1_2/residue_contact_targets_v1
CONTACT=$REMOTE_ROOT/inputs_v1_2/residue_contact_targets_v1/v6_dual_residue_contact_targets.tsv.gz
CONTACT_RECEIPT=$REMOTE_ROOT/inputs_v1_2/residue_contact_targets_v1/RUN_RECEIPT.json
CONTACT_VALIDATION=$REMOTE_ROOT/inputs_v1_2/residue_contact_targets_v1/INDEPENDENT_VALIDATION.json
SMOKE_DIR=$REMOTE_ROOT/inputs_v1_2/smoke93
SMOKE_TRAIN=$SMOKE_DIR/v6_smoke93.tsv
SMOKE_CONTACT=$SMOKE_DIR/v6_smoke93_dual_residue_contact_targets.tsv.gz
SMOKE_CONTACT_RECEIPT=$SMOKE_DIR/v6_smoke93_dual_residue_contact_targets_receipt_v1_1.json
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
MODEL_IDENTITY=$MODEL/model.safetensors

FREEZE_SHA=3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e
TRAINER_SHA=6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af
COLLECTOR_SHA=a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0
MATRIX_SHA=48fadb1b104d7528a574972e5d391f88b1a21df375e281e119025e5ed170683d
GOVERNANCE_SHA=dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226
TRAIN_SHA=ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633
TRAIN_RECEIPT_SHA=46fae18a63e10920c05ccf1dc873de2b588ec436a0320d909405164f9d14c529
CONTACT_SHA=bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f
CONTACT_RECEIPT_SHA=de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027
CONTACT_VALIDATION_SHA=8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911
MODEL_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
SMOKE_TRAIN_SHA=5db7659250b6d9da3ad203f0361a128469b026ccf24f101e25ec1236f4e3aff5
SMOKE_CONTACT_SHA=acfdef0bd8bc548032394140cd4c318a3fb166c0c1fb05e73d1f763f388863d8
SMOKE_CONTACT_RECEIPT_SHA=f0a25c9f6b847a2f282999c9b6cf8dd09a870cfa28d0a0cbea63f90d3657a413

LANES=(F1_contact_low_frozen F4_contact_high_frozen F3_contact_low_rank_frozen L1_contact_low_lora)

sha256_file() { sha256sum "$1" | awk '{print $1}'; }

require_regular() {
  local path=$1 label=$2
  [[ -f "$path" && ! -L "$path" ]] || { echo "missing_or_symlink_${label}:$path" >&2; return 70; }
}

verify_hash() {
  local path=$1 expected=$2 label=$3 actual
  require_regular "$path" "$label"
  actual=$(sha256_file "$path")
  [[ "$actual" == "$expected" ]] || { echo "sha256_mismatch_${label}:$actual:$expected:$path" >&2; return 71; }
}

assert_physical_gpu() {
  local gpu=${1:-}
  [[ "$gpu" =~ ^[1-4]$ ]] || { echo "physical_gpu_forbidden_or_invalid:${gpu:-missing}" >&2; return 64; }
}

free_data1_gb() {
  df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}'
}

verify_exact_code() {
  [[ -x "$PY" ]] || { echo "missing_python:$PY" >&2; return 72; }
  verify_hash "$TRAINER" "$TRAINER_SHA" trainer_v1_5
  verify_hash "$COLLECTOR" "$COLLECTOR_SHA" collector_v1_5
  verify_hash "$FREEZE" "$FREEZE_SHA" implementation_freeze_v1_5
  verify_hash "$MATRIX" "$MATRIX_SHA" production_matrix_v1_2
  verify_hash "$GOVERNANCE" "$GOVERNANCE_SHA" governance_amendment
  verify_hash "$MODEL_IDENTITY" "$MODEL_SHA" esm2_650m_model_identity
}

verify_production_inputs() {
  verify_hash "$TRAIN" "$TRAIN_SHA" training_tsv
  verify_hash "$TRAIN_RECEIPT" "$TRAIN_RECEIPT_SHA" training_receipt
  verify_hash "$CONTACT" "$CONTACT_SHA" contact_targets
  verify_hash "$CONTACT_RECEIPT" "$CONTACT_RECEIPT_SHA" contact_RUN_RECEIPT
  verify_hash "$CONTACT_VALIDATION" "$CONTACT_VALIDATION_SHA" contact_independent_validation
}

verify_smoke_inputs() {
  verify_hash "$SMOKE_TRAIN" "$SMOKE_TRAIN_SHA" smoke_training_tsv
  verify_hash "$SMOKE_CONTACT" "$SMOKE_CONTACT_SHA" smoke_contact_targets
  verify_hash "$SMOKE_CONTACT_RECEIPT" "$SMOKE_CONTACT_RECEIPT_SHA" smoke_contact_receipt
}

configure_lane() {
  local lane=$1
  LANE_ARGS=()
  case "$lane" in
    F1_contact_low_frozen)
      LANE_ARGS=(--backbone-mode frozen --contact-weight 0.0001 --ranking-weight 0.0 --ranking-minimum-delta 0.005 --ranking-temperature 0.02)
      ;;
    F4_contact_high_frozen)
      LANE_ARGS=(--backbone-mode frozen --contact-weight 0.0003 --ranking-weight 0.0 --ranking-minimum-delta 0.005 --ranking-temperature 0.02)
      ;;
    F3_contact_low_rank_frozen)
      LANE_ARGS=(--backbone-mode frozen --contact-weight 0.0001 --ranking-weight 0.0001 --ranking-minimum-delta 0.02 --ranking-temperature 0.03)
      ;;
    L1_contact_low_lora)
      LANE_ARGS=(--backbone-mode lora --contact-weight 0.0001 --ranking-weight 0.0 --ranking-minimum-delta 0.005 --ranking-temperature 0.02 --gradient-checkpointing --lora-r 4 --lora-alpha 8 --lora-dropout 0.10 --lora-target-modules query,value --lora-learning-rate 0.000005)
      ;;
    *) echo "unknown_lane:$lane" >&2; return 65 ;;
  esac
}

write_terminal() {
  local path=$1 status=$2 detail=${3:-}
  mkdir -p "$(dirname "$path")"
  python3 - "$path" "$status" "$detail" <<'PY'
import datetime,json,pathlib,sys
path=pathlib.Path(sys.argv[1]); payload={"status":sys.argv[2],"detail":sys.argv[3],"timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); tmp.replace(path)
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-}" in
    --assert-gpu) assert_physical_gpu "${2:-}" ;;
    --print-lane)
      configure_lane "${2:-}"
      python3 - "${2:-}" "${LANE_ARGS[@]}" <<'PY'
import json,sys
print(json.dumps({"lane":sys.argv[1],"argv":sys.argv[2:]},sort_keys=True))
PY
      ;;
    *) echo 'usage: residue_v1_5_common.sh --assert-gpu 1|2|3|4 | --print-lane LANE' >&2; exit 64 ;;
  esac
fi
