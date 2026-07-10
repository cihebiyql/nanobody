# Phase 2 模型架构 V1: VHH-Ag CrossContactNet

Updated: 2026-07-09

## 定位

Phase 1 是 NumPy 线性 baseline；Phase 2 升级为可在 RTX 5080 上训练的 PyTorch 多任务模型。

目标不是直接替代实验，而是比 Phase 1 更接近真实任务：

```text
sequence + CDR annotation + structure contact labels + PVRIG hotspot mask
        ↓
paratope / epitope / contact map / binding prior / blocker prior
```

## 输入

### VHH 输入

```text
vhh_seq
cdr1_span / cdr2_span / cdr3_span
optional: predicted VHH structure features
```

每个 residue 的特征：

```text
AA token embedding
position embedding
region embedding: FR/CDR1/CDR2/CDR3
CDR mask
composition summary
optional structure features: residue depth / secondary structure / confidence
```

### Antigen/PVRIG 输入

```text
antigen_seq
optional antigen chain structure features
PVRIG hotspot mask when target == PVRIG
```

每个 residue 的特征：

```text
AA token embedding
position embedding
surface/interface hint
PVRIG hotspot weight
optional structure features
```

## 架构

```text
VHH residue tokens                         Antigen residue tokens
        ↓                                           ↓
VHH encoder                              Antigen encoder
        ↓                                           ↓
        └──────── residue-pair cross features ──────┘
                            ↓
                    contact-map head
                            ↓
       hotspot-weighted pooling / CDR-weighted pooling
                            ↓
             binding-prior head + blocker-prior head
```

### Encoder

首版建议轻量化，适配 16GB 5080：

```yaml
d_model: 192 或 256
layers: 4
heads: 4 或 8
dropout: 0.1
max_vhh_len: 160
max_antigen_len: 512
mixed_precision: true
```

可选实现：

1. `BiLSTM + attention`：最快、显存低、适合先跑通；
2. `Transformer encoder`：更适合 residue-pair 建模；
3. `pretrained ESM/AbLang/AntiBERTy embedding`：第二阶段再接，避免初版被环境和显存拖住。

### Contact-map head

对每个 VHH residue i 和 antigen residue j：

```text
h_pair_ij = [h_vhh_i, h_ag_j, h_vhh_i * h_ag_j, |h_vhh_i - h_ag_j|]
contact_logit_ij = MLP(h_pair_ij)
```

输出：

```text
P(contact_ij)
```

### Site heads

```text
paratope_logit_i = MLP(h_vhh_i)
epitope_logit_j = MLP(h_ag_j)
```

输出 residue-level 概率。

### Pair binding head

从 contact map 和 token 表征池化：

```text
max/mean top-k contact probability
CDR3-contact weighted pooling
antigen hotspot weighted pooling
CLS-like pooled VHH/antigen embedding
```

输出：

```text
P(pair binds)
```

### PVRIG blocker-prior head

仅在 target 为 PVRIG 或 PVRIG inference 时启用：

```text
blocker_score = weighted_pool(contact_prob over PVRIG hotspot/interface residues)
              + CDR3-to-hotspot contact mass
              + predicted epitope overlap with PVRIG-PVRL2 mask
```

输出不是实验 IC50，而是进入 docking 的优先级。

## Loss

```text
L = w_para * BCE(paratope)
  + w_epi * BCE(epitope)
  + w_contact * BCE(contact_map)
  + w_pair * BCE(pair_binding)
  + w_rank * pairwise/ranking loss optional
```

初始权重：

```yaml
w_para: 1.0
w_epi: 1.0
w_contact: 2.0
w_pair: 1.0
w_rank: 0.0
```

原因：contact map 最接近结构机制，应比单纯 pair label 更重要。

## 输出解释

模型对每个候选输出：

```text
candidate_id
pair_binding_probability
blocker_prior_score
predicted_vhh_paratope_positions
predicted_pvrig_epitope_positions
pvrig_hotspot_contact_mass
cdr3_hotspot_contact_mass
leakage_label
recommended_next_step
```

## 与 MVP 的关系

Phase 2 不删除 Phase 1，而是生成新列：

```text
phase1_ai_prior_label
phase1_mvp_rank_score
phase2_pair_binding_probability
phase2_blocker_prior_score
phase2_contact_hotspot_mass
final_rank_for_docking
```

最终排序建议：

```text
final_rank = 0.35 * phase2_blocker_prior_score
           + 0.25 * phase2_pair_binding_probability
           + 0.20 * phase1_mvp_rank_score
           + 0.20 * developability / leakage-safe score
```

如果后续已有 docking，则 docking consensus 优先级高于 Phase 2 prior。
