# residue_v1 V1.1 生产协议

V1.1 替代尚未用于远程生产的 V1。旧 `IMPLEMENTATION_FREEZE_V1.json` 保留原字节，
supersession 原因记录在 `IMPLEMENTATION_FREEZE_V1_SUPERSEDED_PREPRODUCTION.json`。

## 关键修正

- 复用上层冻结的 `PVRIG_V6_INNER` whole-parent **5-fold** hash。
- 对每个 observed inner fold 独立训练；epoch 按
  `Spearman → parent-centered Spearman → Top20 recall → -MAE` 字典序选择。
- 最终 epoch 数取各 inner fold 选择结果的 **rounded median**，再在全部 outer-train
  parent 上从头 refit。
- 训练行的 M2 base 全部来自 out-of-inner-fold 预测；outer test 的 M2 只在完整
  outer-train 上拟合。
- parent-aware batch、BF16 autocast、gradient accumulation；LoRA 使用独立 LR，
  可启用 gradient checkpointing。
- `last.pt` 只含 head/adapter、optimizer、scheduler、RNG 和 binding；不含基础 PLM。
- `metrics.jsonl` 会与 last checkpoint 对账并删除未提交的尾行。
- 低于 150 GiB 写 safe-stop；低于 180 GiB 禁止写 checkpoint。
- outer evaluation 有单向 seal；无 terminal 的已启动 outer pass 禁止自动重跑。
- 五个 outer run 完成后，由独立 collector 做 candidate/parent/fold/hash 闭包和
  parent bootstrap promotion。

## 冻结外部输入

| 输入 | SHA256 |
|---|---|
| supervised1507 TSV | `ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633` |
| dual contact target TSV.GZ | `bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f` |
| contact receipt | `de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027` |
| independent contact validation | `8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911` |
| ESM2-650M model.safetensors | `a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0` |

生产模式会直接核对这些冻结哈希，并额外核对 `IMPLEMENTATION_FREEZE_V1_1.json`。

## 单 outer fold 命令模板

```bash
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code/residue_v1

CUDA_VISIBLE_DEVICES=1 $PY "$ROOT/src/train_nested_residue_surrogate_v1_1.py" \
  --training-tsv /data1/qlyu/projects/.../v6_supervised1507.tsv \
  --contact-tsv-gz /data1/qlyu/projects/.../v6_dual_residue_contact_targets.tsv.gz \
  --contact-receipt /data1/qlyu/projects/.../RUN_RECEIPT.json \
  --contact-validation /data1/qlyu/projects/.../INDEPENDENT_VALIDATION.json \
  --implementation-freeze "$ROOT/IMPLEMENTATION_FREEZE_V1_1.json" \
  --output-dir /data1/qlyu/projects/.../outer_fold_0 \
  --outer-fold 0 \
  --backbone-kind hf --backbone-mode frozen \
  --model-path /data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c \
  --model-identity-file /data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c/model.safetensors \
  --expected-model-sha256 a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0 \
  --expected-training-sha256 ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633 \
  --expected-contact-sha256 bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f \
  --precision bf16 --gradient-accumulation 2 --resume
```

不同 outer fold 使用独立 GPU/输出目录。冻结 backbone lane 稳定后才运行 LoRA lane，
并增加 `--backbone-mode lora --gradient-checkpointing`。

## 独立 OOF collector

```bash
$PY "$ROOT/src/collect_residue_oof_v1_1.py" \
  --training-tsv /data1/qlyu/projects/.../v6_supervised1507.tsv \
  --implementation-freeze "$ROOT/IMPLEMENTATION_FREEZE_V1_1.json" \
  --outer-run-dir /data1/qlyu/projects/.../outer_fold_0 \
  --outer-run-dir /data1/qlyu/projects/.../outer_fold_1 \
  --outer-run-dir /data1/qlyu/projects/.../outer_fold_2 \
  --outer-run-dir /data1/qlyu/projects/.../outer_fold_3 \
  --outer-run-dir /data1/qlyu/projects/.../outer_fold_4 \
  --output-dir /data1/qlyu/projects/.../oof_collector_v1_1
```

只有 point estimates 和 parent-bootstrap 95% lower-bound gates 全部胜过 M2，collector
才输出 `PROMOTE_RESIDUE_V1_1_OVER_M2`。

