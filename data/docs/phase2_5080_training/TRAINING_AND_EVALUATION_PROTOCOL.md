# Phase 2 训练与评估协议

Updated: 2026-07-09

## 训练环境

当前 base Python 环境没有 PyTorch，所以 Phase 2 建议单独环境：

```bash
cd /mnt/d/work/抗体/data
python3 -m venv .venv-phase2-5080
source .venv-phase2-5080/bin/activate
python -m pip install --upgrade pip
# 根据 PyTorch 官网当前 CUDA/RTX 50 支持选择 torch wheel；安装后必须验证 torch.cuda.is_available()
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO_CUDA')
PY
```

注意：本机 `nvidia-smi` 已看到 RTX 5080，但 PyTorch wheel 版本必须和 CUDA/驱动兼容。训练前必须写入环境审计：

```text
experiments/phase2_5080_v1/audits/environment_audit.md
```

## 训练阶段

### Phase 2A: site-only warmup

数据：`ZYMScott_Paratope`。

任务：

```text
paratope residue BCE
epitope residue BCE
```

目的：验证 PyTorch pipeline 和 Phase 1 baseline 是否可超越。

### Phase 2B: structure contact-map training

数据：SAbDab2 single-domain structures 全量 contact extraction。

任务：

```text
contact-map BCE
paratope/epitope weak labels from contact projection
```

目的：让模型学 residue-pair 接触，而不是只学单链 residue probability。

### Phase 2C: pair binding classifier

数据：positive cognate pairs + N1/N2/N3 负样本。

任务：

```text
pair-level binding BCE
hard-negative robustness
```

目的：对 VHH-antigen pair 给出 binding-prior。

### Phase 2D: PVRIG calibration / inference

数据：

```text
PVRIG known positives
PVRIG mutant controls
MVP Top candidates
PVRIG hotspot mask
```

用途：只做 calibration / evaluation / ranking，不做普通 supervised training。

## 推荐超参

```yaml
seed: 7
precision: amp_bfloat16_or_float16
batch_size_pair: 8-32
batch_size_site: 16-64
gradient_accumulation: 1-4
optimizer: AdamW
lr: 2.0e-4
weight_decay: 1.0e-2
epochs_site_warmup: 10
epochs_contact_pair: 30
early_stopping_metric: val_contact_auprc 或 val_hard_negative_auprc
patience: 5
```

RTX 5080 16GB 首轮建议小模型：

```yaml
d_model: 192
layers: 4
heads: 4
max_antigen_len: 512
max_vhh_len: 160
```

## 指标

### residue-level site metrics

| 指标 | 说明 |
| --- | --- |
| AUROC | residue 二分类总体区分度 |
| AUPRC | 正样本稀疏时更重要 |
| F1@threshold | 固定阈值表现 |
| Precision@K | Top K residue 是否为真实 paratope/epitope |
| Recall@K | 是否覆盖真实接触区域 |

### contact-map metrics

| 指标 | 说明 |
| --- | --- |
| contact AUROC | residue pair 二分类 |
| contact AUPRC | 主指标，正负极不平衡 |
| Precision@L/5, L/10 | 结构预测常用 top contact 指标 |
| CDR3-contact recall | 是否抓住 CDR3 接触 |

### pair-level metrics

| 指标 | 说明 |
| --- | --- |
| AUROC | pair binder/non-binder 区分 |
| AUPRC | 主指标之一 |
| MCC | 阈值下分类鲁棒性 |
| Brier score / ECE | 概率校准 |
| hard-negative AUROC/AUPRC | 重点看是否抗 easy-negative 虚高 |

### PVRIG external metrics

| 指标 | 说明 |
| --- | --- |
| known-positive sensitivity | 11 个 PVRIG positive/control 排名是否靠前 |
| mutant/control separation | mutant/near leakage 是否被挂起或降权 |
| hotspot recall | PVRIG hotspot top-K 覆盖 |
| CDR3-hotspot contact mass | 是否主要由 CDR3 打到 interface |
| Top candidate leakage-free rate | Top 输出是否排除 exact/near positives |

## 报告格式

训练后必须生成：

```text
experiments/phase2_5080_v1/reports/phase2_v1_eval.md
```

至少包含：

```text
1. 环境和 GPU 信息
2. 数据集行数和 split 数量
3. 正负样本比例
4. negative type 分布
5. train/val/test 指标表
6. easy-negative vs hard-negative 指标拆分
7. PVRIG external calibration 表
8. 与 Phase 1 baseline 对比
9. 失败案例和下一步
```

## 最低性能验收建议

因为这是小数据定向模型，不能只追求总 AUROC。建议第一版验收：

| 项目 | 最低要求 |
| --- | --- |
| site paratope AUPRC | 高于 Phase 1 paratope test AUPRC 0.4174 或解释原因 |
| site epitope AUPRC | 高于 Phase 1 epitope test AUPRC 0.1325 或解释原因 |
| contact AUPRC | 明显高于 random positive rate |
| hard-negative pair AUPRC | 单独报告，不能只报 easy-negative |
| PVRIG Top output | exact/near known-positive 不进入新候选排名 |
| reproducibility | 同 seed 可复跑，同 run_id 产物齐全 |

## 不能声称的内容

除非有实验数据，否则不能声称：

```text
新候选已经真实结合 PVRIG
新候选已经阻断 PVRIG-PVRL2
预测 score 等于 Kd/IC50
模型已经完成药物开发级验证
```

可以声称：

```text
模型给出了结构+序列先验排序
模型预测了候选 CDR/paratope 和 PVRIG epitope/hotspot 覆盖
候选通过了计算泄漏排除和下一轮 docking 优先级筛选
```
