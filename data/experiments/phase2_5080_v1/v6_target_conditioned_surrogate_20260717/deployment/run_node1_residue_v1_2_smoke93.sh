#!/usr/bin/env bash
set -euo pipefail
if (( $# != 3 )); then echo 'usage: lane frozen|lora physical_gpu' >&2; exit 64; fi
lane=$1; mode=$2; gpu=$3
[[ "$mode" == frozen || "$mode" == lora ]] || exit 64
[[ "$gpu" =~ ^[1-4]$ ]] || { echo 'GPU must be physical 1-4' >&2; exit 64; }
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE_ROOT=$ROOT/code_v1_3/residue_v1
TRAIN=$ROOT/inputs_v1_2/smoke93/v6_smoke93.tsv
CONTACT=$ROOT/inputs_v1_2/smoke93/v6_smoke93_dual_residue_contact_targets.tsv.gz
CONTACT_RECEIPT=$ROOT/inputs_v1_2/smoke93/v6_smoke93_dual_residue_contact_targets_receipt_v1_1.json
MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
OUT=$ROOT/runtime/residue_v1_2_smoke93_${lane}_20260718
STATUS=$ROOT/status/residue_v1_2_smoke93_${lane}_20260718
mkdir -p "$STATUS"
sha256sum -c <<'HASHES'
782e5255e06eaffc72c4546c4a87838521c7593974877b29a79f7ccac3f149d2  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_3/residue_v1/src/train_nested_residue_surrogate_v1_2.py
c6745faf5d9c4afb101015f751b89e2aefb82aa4ccfbf3259c2d2c9cba4b05bb  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_3/residue_v1/src/residue_model.py
1bd76aa3128f7cbd54c94004760547102c402dc5127a896669e0e072ca7ed5d8  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_3/residue_v1/src/train_nested_residue_surrogate.py
b9baa1bbecba316d34e9c47baea832f382b20958d724911dba4005bdde8421e2  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_3/residue_v1/IMPLEMENTATION_FREEZE_V1_2.json
5db7659250b6d9da3ad203f0361a128469b026ccf24f101e25ec1236f4e3aff5  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_2/smoke93/v6_smoke93.tsv
acfdef0bd8bc548032394140cd4c318a3fb166c0c1fb05e73d1f763f388863d8  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_2/smoke93/v6_smoke93_dual_residue_contact_targets.tsv.gz
f0a25c9f6b847a2f282999c9b6cf8dd09a870cfa28d0a0cbea63f90d3657a413  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/inputs_v1_2/smoke93/v6_smoke93_dual_residue_contact_targets_receipt_v1_1.json
a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0  /data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c/model.safetensors
HASHES
free_gb=$(df -Pk /data1 | awk 'NR==2 {printf "%.0f", $4/1024/1024}')
if (( free_gb < 180 )); then printf '{"status":"FAIL_DISK_PREFLIGHT","free_gb":%s}\n' "$free_gb" > "$STATUS/terminal.json"; exit 72; fi
printf '{"status":"RUNNING","pid":%s,"gpu_physical":%s,"mode":"%s","started_at":"%s","claim_boundary":"mechanical smoke only"}\n' "$$" "$gpu" "$mode" "$(date -Is)" > "$STATUS/status.json"
export CUDA_VISIBLE_DEVICES="$gpu"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
monitor="$STATUS/gpu_memory_mib.csv"; printf 'timestamp,memory_used_mib,utilization_gpu\n' > "$monitor"
( while [[ ! -f "$STATUS/monitor.stop" ]]; do nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader,nounits -i "$gpu" >> "$monitor" || true; sleep 2; done ) & monitor_pid=$!
start=$(date +%s)
cmd=("$PY" "$CODE_ROOT/src/train_nested_residue_surrogate_v1_2.py"
 --training-tsv "$TRAIN" --contact-tsv-gz "$CONTACT" --contact-receipt "$CONTACT_RECEIPT"
 --output-dir "$OUT" --outer-fold 0 --smoke-mode --resume
 --backbone-kind hf --backbone-mode "$mode" --model-path "$MODEL" --model-identity-file "$MODEL/model.safetensors"
 --expected-model-sha256 a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0
 --precision bf16 --gradient-accumulation 2 --fusion-dim 64 --dropout 0.25 --residual-scale 0.02
 --dual-weight 1.0 --receptor-weight 0.35 --contact-weight 0.0001 --ranking-weight 0.0 --residual-weight 0.05
 --huber-delta 0.02 --max-epochs 1 --batch-size 8 --per-parent-batch 2
 --head-learning-rate 0.0001 --weight-decay 0.02 --warmup-steps 0
 --safe-stop-free-gb 150 --checkpoint-min-free-gb 180 --seed 43 --device cuda:0)
if [[ "$mode" == lora ]]; then cmd+=(--gradient-checkpointing --lora-r 4 --lora-alpha 8 --lora-dropout 0.10 --lora-target-modules query,value --lora-learning-rate 0.000005); fi
set +e
"${cmd[@]}" > "$STATUS/stdout.first.json.tmp" 2> "$STATUS/stderr.first.log"; rc=$?
set -e
touch "$STATUS/monitor.stop"; wait "$monitor_pid" || true
if (( rc != 0 )); then printf '{"status":"FAIL_RESIDUE_V1_2_SMOKE","lane":"%s","mode":"%s","return_code":%s,"finished_at":"%s"}\n' "$lane" "$mode" "$rc" "$(date -Is)" > "$STATUS/terminal.json"; exit "$rc"; fi
mv "$STATUS/stdout.first.json.tmp" "$STATUS/stdout.first.json"
before=$(sha256sum "$OUT/RESULT.json" | awk '{print $1}')
"${cmd[@]}" > "$STATUS/stdout.resume.json.tmp" 2> "$STATUS/stderr.resume.log"; mv "$STATUS/stdout.resume.json.tmp" "$STATUS/stdout.resume.json"
after=$(sha256sum "$OUT/RESULT.json" | awk '{print $1}'); [[ "$before" == "$after" ]]
end=$(date +%s)
"$PY" - "$OUT" "$STATUS" "$((end-start))" "$after" "$lane" "$mode" <<'PY'
import csv,json,hashlib,pathlib,sys
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);seconds=int(sys.argv[3]);expected=sys.argv[4];lane=sys.argv[5];mode=sys.argv[6]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(); r=json.loads((out/'RESULT.json').read_text()); seal=json.loads((out/'OUTER_EVALUATION_SEAL.json').read_text())
assert r['status']=='PASS_OUTER_FOLD_COMPLETE' and r['outer_evaluation_count']==1 and seal['status']=='SEALED_COMPLETE_ONE_EVALUATION' and sha(out/'RESULT.json')==expected
mem=[]
with (status/'gpu_memory_mib.csv').open() as h:
 for row in csv.DictReader(h):
  try:mem.append(int(row['memory_used_mib']))
  except:pass
ck=list(out.rglob('last.pt')); payload={'status':'PASS_RESIDUE_V1_2_SMOKE93_TERMINAL','lane':lane,'mode':mode,'elapsed_seconds':seconds,'peak_gpu_memory_mib':max(mem) if mem else None,'outer_evaluation_count':1,'result_sha256':expected,'resume_result_sha256_unchanged':True,'last_checkpoint_count':len(ck),'last_checkpoint_total_bytes':sum(p.stat().st_size for p in ck),'finished_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'claim_boundary':'mechanical smoke only; not model selection or biological evidence'}
(status/'terminal.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');print(json.dumps(payload,sort_keys=True))
PY
