# V6 residue_v1：双受体残基级 Docking surrogate

## 证据边界

本目录只训练并评估：

```text
VHH sequence + monomer structure features
→ 近似独立 8X6B/9E6Y Docking 的连续几何
```

主目标仍为 `R_dual_min`。输出不是结合概率、Kd、实验竞争/阻断证据、
Docking Gold 或最终提交判定。

## 为什么另起版本

实现完全位于 `residue_v1/`，不修改已有 M3 文件。相较于候选级 pooled embedding，
该 lane 明确保留残基维度，并用两个 receptor-specific contact channel 驱动加权池化。

核心约束：

1. **显式 M2 base**：模型接收已经 cross-fit 的 M2 预测；内部没有可偷看训练标签的
   M2 head。
2. **双通道 contact head**：分别预测 8X6B 和 9E6Y 的 VHH residue contact。
3. **contact-weighted pooling**：全局池化之外，分别生成两个受体的残基加权池化向量。
4. **受限 residual**：最终预测为 `M2 + residual_scale * tanh(raw_residual)`。
5. **嵌套 whole-parent 评估**：inner fold 只用于 epoch 选择；最终在全部 outer-train
   parent 上从头 refit，再一次性评估 outer test。
6. **小 checkpoint**：只保存 head 和可选 LoRA/adapter；禁止复制基础 PLM 权重。

## 1. 构建双受体 contact targets

输入为冻结 contact teacher 的 residue-pair TSV.GZ 和 V6 supervised TSV。聚合规则固定为：

```text
candidate × receptor × VHH residue
→ max(contact_frequency_pose_weighted over PVRIG residues)
```

采用 `max` 而不是求和，是为了避免把同一 pose 中高度相关的多个 PVRIG residue pair
错误当成独立概率。对已经拥有双受体 contact teacher 的候选，未出现在 pair 表中的
VHH residue 记为 0；技术不完整候选根本不进入 target 表，不能被写成 0。

```bash
PY=experiments/phase2_5080_v1/.venv-phase2-5080/bin/python
ROOT=experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/residue_v1

$PY "$ROOT/src/build_dual_contact_targets.py" \
  --training-tsv /path/to/v6_supervised1507.tsv \
  --pair-tsv-gz /path/to/v4h_stage1_residue_pair_contact_teacher.tsv.gz \
  --output-dir /data1/qlyu/projects/.../residue_contact_targets_v1 \
  --expected-candidates 1281 \
  --expected-training-sha256 <sha256> \
  --expected-pair-sha256 <sha256>
```

输出 gzip 固定 `mtime=0`，并写入带输入/输出哈希和计数的 `RUN_RECEIPT.json`。

## 2. 冻结 PLM 的第一条生产 lane

非 smoke 模式必须提供训练表、contact target 和本地模型 identity file 的 SHA256。
运行目录必须位于 `/data1/qlyu`，且默认要求至少剩余 180 GiB。

```bash
$PY "$ROOT/src/train_nested_residue_surrogate.py" \
  --training-tsv /data1/qlyu/projects/.../v6_supervised1507.tsv \
  --contact-tsv-gz /data1/qlyu/projects/.../v6_dual_residue_contact_targets.tsv.gz \
  --output-dir /data1/qlyu/projects/.../residue_v1_frozen_seed43 \
  --expected-training-sha256 <sha256> \
  --expected-contact-sha256 <sha256> \
  --backbone-kind hf \
  --backbone-mode frozen \
  --model-path /data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c \
  --model-identity-file /path/to/model.safetensors \
  --expected-model-sha256 <sha256> \
  --outer-fold all \
  --inner-folds 3 \
  --inner-validation-fold 0 \
  --device cuda \
  --minimum-free-gb 180
```

建议生产时让 5 个 outer fold 分开启动，以便独立失败和重试；每个进程使用
`--outer-fold 0` 到 `4` 和独立 output directory。

## 3. LoRA lane

冻结 backbone lane 稳定后，使用同一数据、split 和评估合同，仅增加：

```bash
--backbone-mode lora \
--lora-r 8 \
--lora-alpha 16 \
--lora-target-modules query,key,value
```

启动前必须针对实际 PLM 打印并核对 module 名；若 PEFT 暴露了任何非 LoRA/adapter
backbone parameter，模型初始化会 fail closed。

## 输出

每个 outer fold 只写小型可审计产物：

- `contract.json`
- `m2_outer_train_fit.npz`
- `adapter_head.pt`
- `outer_test_predictions.tsv`
- `RESULT.json`

根目录写 `RUN_SUMMARY.json`。`adapter_head.pt` 不包含基础 PLM 权重。

## 本地验证

```bash
$PY -m py_compile "$ROOT"/src/*.py "$ROOT"/tests/*.py
$PY -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v
```

当前只完成 synthetic CPU 验证，尚未启动 Node1 重训练；真实运行仍依赖 contact teacher
pair TSV.GZ 的正式产出或同步。

