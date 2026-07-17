# PVRIG V4-H QC96 与 V4-D-DEV1 sequence surrogate 预测契约兼容性审计

**日期：** 2026-07-17  
**审计性质：** repo-local，label-free，pre-Docking  
**结论状态：** `FAIL_FORMAL_COMPATIBILITY_BUT_DEV_ONLY_PREDICTION_FREEZE_IS_IMPLEMENTABLE`

## 1. 审计范围和证据边界

本审计只读取了：

- V4-H QC96 已冻结的 label-free manifest、provenance、audit 和 receipt；
- V4-D-DEV1 sequence surrogate trainer、base trainer 和它们的 preregistration；
- V4-H formal evaluator 的已冻结 label-free preregistration/protocol/template；
- V3 mean-pool generic prior 的已冻结 checkpoint、train summary、target 和打分代码。

本审计没有读取、接受或解析任何 H96 Docking label/path，也没有修改任何 existing preregistration、manifest 或科学门限。结论仅涉及：

> sequence-to-independent-dual-docking computational geometry surrogate；不是 PVRIG binding probability、Kd、competition、experimental blocking 或 Docking Gold。

## 2. 结论摘要

| 排名 | 结论 | 置信度 | 影响 |
|---:|---|---|---|
| 1 | 当前 DEV1 trainer 与已冻结 V4-H formal primary-model 契约不兼容 | 高 | 不能把 `frozen_feature_ridge` 改名为 `contact` 后冒充 formal primary |
| 2 | H96 已冻结 `model_split` 与 formal prereg 的 required value 不一致 | 高 | 不能静默 alias，也不能就地改已冻结 manifest |
| 3 | 纯字段层面的 sequence/CDR 映射可无损完成 | 高 | 可立即建立一个新版本 DEV-only prediction adapter |
| 4 | H96 generic prior 可使用同一组 V3 mean-pool 模型完全无标签重算 | 高 | 不能复用 legacy7087 的现成行，必须生成 H96 自己的 embedding/prior receipt |

## 3. 已冻结 H96 面板的实测闭合

内容寻址 delivery：

```text
experiments/phase2_5080_v1/prepared/
pvrig_v4_h_qc96_holdout_v1/delivery/current
```

`current` 指向 receipt SHA256：

```text
a28a4a419c91c4d4f73b5d9088d114b6fb427cede0d10eb0ba8856a488bb912d
```

关键文件：

| 文件 | SHA256 |
|---|---|
| `qc96_manifest_v1.tsv` | `f128f7b2389ea5e9887b931460332ce42898aece0314e7320975c204a692f723` |
| `qc96_selected_source_provenance_v1.tsv` | `e64317b9ff7b68b1dbaf8ece55fb8d051644c36b875e7f3bd28253d50fa65dc4` |
| `qc96_audit_v1.json` | `e9504217ee3a70f5bc0923588ab75de41719d0d3502efe2cad3259af535d97ea` |
| `qc96_receipt_v1.json` | `a28a4a419c91c4d4f73b5d9088d114b6fb427cede0d10eb0ba8856a488bb912d` |
| `recovery.complete.json` | `72cf1b0b1a262561f933960688bd3ad852c8763eaf4a02ba2e537a1b517b9da1` |
| `LOCAL_DELIVERY_RECEIPT.json` | `e630ca771f92dcd940e3abbe13a6965d1c64c3d65a549454f9c027143b53f55b` |

本次审计对 96 行执行了 label-free 内容闭合：

- 96/96 `sequence_sha256 == SHA256(sequence)`；
- 96/96 `cdr1_after` 非空且是 `sequence` 子串；
- 96/96 `cdr2_after` 非空且是 `sequence` 子串；
- 96/96 `cdr3_after` 非空且是 `sequence` 子串；
- 96/96 `len(cdr3_after) == cdr3_length`；
- candidate ID 和 sequence SHA256 均为 96 个唯一值；
- 4 个 parent cluster 各 24 条，24 个 parent-by-patch-by-mode stratum 各 4 条；
- `LOCAL_DELIVERY_RECEIPT.json` 明确记录 `docking_labels_accessed=false` 和 `model_prediction_accessed=false`（该文件第 1–37 行）。

## 4. DEV1 输入字段映射

DEV1 冻结的 required feature contract 要求：

```text
candidate_id
model_split
parent_framework_cluster
sequence_sha256
sequence
design_method
design_mode
target_patch_id
cdr1
cdr2
cdr3
generic_binding_prior
```

证据：

- `audits/phase2_v4_d_dev1_sequence_surrogate_v1_preregistration.json`；
- `src/train_phase2_v4_d_surrogate.py:75-104`；
- `src/train_phase2_v4_d_dev1_sequence_surrogate.py:284-336`。

对 H96 的最小无损映射是：

| DEV1 field | H96 source | 处理 |
|---|---|---|
| `candidate_id` | manifest `candidate_id` | 直接复制 |
| `parent_framework_cluster` | manifest 同名列 | 直接复制 |
| `sequence_sha256` | manifest 同名列 | 必须重算 SHA256 验证 |
| `sequence` | manifest 同名列 | 标准氨基酸检查 |
| `design_method` | 冻结 H0/H1 generator contract | 映射为训练库已有的唯一值 `RFantibody_RFdiffusion_ProteinMPNN` |
| `design_mode` | manifest 同名列 | `H3` / `H1H3` |
| `target_patch_id` | manifest 同名列 | `A_CENTER` / `B_LOWER` / `C_CROSS` |
| `cdr1` | manifest `cdr1_after` | 精确复制 |
| `cdr2` | manifest `cdr2_after` | 精确复制 |
| `cdr3` | manifest `cdr3_after` | 精确复制，并与 `cdr3_length` 闭合 |
| `generic_binding_prior` | H96 新的 label-free mean-pool 输出 | 禁止空值、常数或旧库行 imputation |

`design_method` 常量不是人工猜测：

- H0/H1 prereg 明确写为 `existing Node1 RFantibody RFdiffusion + ProteinMPNN only`（`audits/phase2_v4_h_qc96_h0_h3_v1_preregistration.json:57-64`）；
- 冻结 generation config SHA256 为 `4ae7e1a4536dd09e842dd0cc8a678b4f080d04b63b42151fbeb4c5e7feb971c6`；
- DEV1 290-row split 中 `design_method` 只有 `RFantibody_RFdiffusion_ProteinMPNN` 一种值。

## 5. Formal blocker 1：`model_split` 不一致

H96 recovery V1.2 生成代码冻结写入：

```text
V4_H_QC96_PROSPECTIVE_HOLDOUT
```

证据：`src/recover_phase2_v4_h_qc96_h2_h4_v1_2.py:248-258`；已发布 manifest 的 96/96 行也都是该值。

但 V4-H formal preregistration 冻结要求：

```text
PROSPECTIVE_V4_H_QC_QUALIFIED_NEW_PARENT_HOLDOUT
```

证据：`audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json:41-64`。

这不是字符串格式细节，而是 formal panel identity 的一部分。下列处理都不安全：

- 在 prediction adapter 中静默改名；
- 就地修改已冻结 H96 manifest；
- 让 formal evaluator 同时接受两个值而不做新的 prelabel 版本化说明。

因此，在创建 formal prediction receipt 前，必须由新的 prelabel governance 版本解决该不一致，或者另起 V4-H formal V2。

## 6. Formal blocker 2：DEV1 sequence model 不是 preregistered contact family

DEV1 trainer 的模型集是：

```text
constant
parent_only
metadata_shortcut
cdr3_only
handcrafted_full_sequence
generic_prior_only
frozen_feature_ridge
```

其中唯一 candidate model 是 `frozen_feature_ridge`。它是 sequence/CDR 位置、组成和 k-mer 的固定 signed-hash projection，不读取 residue-contact feature（`src/train_phase2_v4_d_surrogate.py:350-389,424-499`）。DEV1 artifact 将它写为 `selected_candidate_model`，并输出 `selected_prediction` / `selected_uncertainty`（`src/train_phase2_v4_d_dev1_sequence_surrogate.py:602-653`）。

但 V4-H formal preregistration 已冻结：

```text
primary_model_family      = contact
primary_prediction_column = contact_predicted_geometry_score
primary_uncertainty_column = contact_prediction_uncertainty
primary_model_selection   = contact-stage selected_candidate_model
```

证据：`audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json:66-100`。

所以：

- 把 `frozen_feature_ridge` 改名为 `contact_selected_model` 只是 schema 伪装，不是科学兼容；
- 当前 DEV1 trainer 可以生成有用的 development sequence surrogate，但不能直接作为已冻结 V4-H formal primary test；
- 已有 V4-F freezer 也不能直接复用，因为它硬绑 V4-F manifest/status/path/hash，并且实际重放 base + embedding + contact 三个 stage（`src/freeze_phase2_v4_f_surrogate_predictions.py:189-297,1110-1262`）。

## 7. H96 generic prior：可以同模型无标签重算，但不能复用旧行

实测 H96 与 legacy7087 generic-prior source：

```text
candidate_id overlap     = 0
sequence_sha256 overlap  = 0
```

因此，`scored_candidates_v1.csv` 中没有可直接 join 的 H96 行。

但同一无标签 V3 mean-pool 模型可以对 H96 重算：

| 冻结项 | SHA256 |
|---|---|
| seed 43 checkpoint | `0b2ce4b453f682e6f95ceafe0b008fb872ff76f865ec0133abb2f9807fe99ea0` |
| seed 53 checkpoint | `d9652d70fc0b4e53e4ceb7468d3b7a137064cc6191569f5375fd28db801f85b3` |
| seed 67 checkpoint | `d402cc202752f48f3b8027251308f6a29f34ddc0eb46c258fdc6491aae7d0089` |
| train summary | `3f07f62de4a4b1c73dad0f2e80296401a8d5955386031c35826f0ae129607371` |
| PVRIG target sequence | `b3d2735abe671004474d0196f9d010bbdf22ea2cec9ccb6d71b28f9bdb328075` |
| original embedding config | `e525cb725bc5b9ea93c2f91ba84209cc3992d1e65e0e0d78f79b7c219ba33636` |

三个 checkpoint 和 train summary 在本次审计中重新计算 SHA256，均与已发布 audit 一致。证据：

- `prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_audit_v1.json:1-31`；
- `src/score_pvrig_formal_candidates_meanpool.py:78-166`；
- `src/prepare_phase2_v3_embeddings.py`。

新 H96 prior 必须使用：

1. H96 自己的 exact sequence manifest，再加同一 PVRIG target；
2. 与 checkpoint 相同的 ESM2/VHHBERT/pooling config；
3. 新的 embedding manifest、summary 和所有 shard hashes；
4. 同一 3-seed checkpoints 生成 mean、std 和 disagreement；
5. H96-specific prior TSV/audit/receipt，并记录 H96/V4-D test32/V4-F label path counters 全为 0。

禁止：用常数填补、用 parent 均值填补、或将 legacy7087 中的相近序列 prior 移植给 H96。

## 8. 可安全立即实施的 DEV-only prediction freeze

建议新起一个不冒充 formal 的版本，例如：

```text
V4-H-DEV1-PRED1
```

它的主要状态必须包含 `DEV_ONLY`，不得使用 `FORMAL` / `UNLOCK` / `COMPLETION` / `DOCKING_MAY_START` 等权威语义。

### 8.1 新版本最小输入

- H96 manifest/audit/receipt/provenance/recovery/local-delivery 的上述 6 个精确 hash；
- H0/H1 generator prereg 和 generation config hash，用于绑定 `design_method`；
- DEV1 preregistration（SHA256 `10395d03f0f8d9eae7db2fa94fc3b4cccc1570369ee8b09a6650bff062f35113`）；
- DEV1 teacher TSV/audit/split manifest 的最终通过审查 hash；
- DEV1 model config/artifact/summary/receipt 的最终 hash；
- trainer SHA256 `e412bee668f52cbf15c49c9d0c542263202ae9a9fd2e7a332be8a5ac7438b414`；
- reused base module SHA256 `bbdf2d1d22ef1e375b65d1d680c25fffe6a4d09d170184528dc2c3f0292fa95e`；
- H96-specific generic-prior sequence/embedding/shards/output/audit/receipt 的完整 input closure；
- prediction adapter 源码、tests、test log 和 implementation freeze hashes。

### 8.2 最小输出 schema

为避免冒充 formal contact family，建议明确使用：

```text
candidate_id
sequence_sha256
model_split
parent_id
parent_framework_cluster
design_method
design_mode
target_patch_id
cdr3_length
dev1_selected_model
dev1_sequence_predicted_geometry_score
dev1_sequence_prediction_uncertainty
dev1_strongest_shortcut_model
dev1_strongest_shortcut_prediction
dev1_strongest_shortcut_uncertainty
```

不应使用 `contact_predicted_geometry_score` 列名，除非实际训练和重放了 preregistered contact-stage feature/model。

### 8.3 必须 fail-closed 的 gates

1. 96-row exact order 与 H96 manifest 完全一致；
2. 9 个 identity field 及 sequence/CDR 映射逐行闭合；
3. 预测值有限，uncertainty 有限且 `>=0`；
4. 所有行的 selected-model identity 一致；
5. selected model 来自 DEV1 OPEN_DEVELOPMENT 冻结选择，不根据 H96 改模型或权重；
6. `R_dual_min`、tier、Docking label 和 experimental field 不得出现在输入/输出 header；
7. V4-D test32、V4-F 和 V4-H label path accepted/opened/read 全为 0/false；
8. 完整 `input_hashes` + `input_closure_sha256`；
9. 完整 `execution_source_hashes` + `execution_source_closure_sha256`；
10. 独立 replay 生成的预测字节/值与发布 TSV 一致；
11. staging 写入，audit 和 receipt 闭合，receipt 最后原子发布；
12. 独立 verifier 通过后只能产生 `DEV_ONLY_PREDICTIONS_FROZEN` receipt，不能解锁 formal V4-H Docking/evaluator。

## 9. 恢复已有 V4-H formal one-shot 路径的最小方案

如果目标是继续使用现有 V4-H formal V1 preregistration，则不能仅有上述 DEV-only sequence model。最小路径是：

1. **prelabel governance 解决 `model_split` 冲突**  
   新建版本化说明或 formal V2；禁止改 V1 原文和已冻结 H96 文件。

2. **训练真实 contact-stage DEV1 surrogate**  
   用同一 OPEN_TRAIN226 / OPEN_DEVELOPMENT32 teacher，加入已冻结的 label-free residue-contact feature 和 embedding，训练 contact/fusion model；模型选择只能看 OPEN_DEVELOPMENT。

3. **对 H96 无标签生成同版本 contact features/embeddings**  
   必须使用同一 extractor/checkpoint/schema/allowlist，并闭合 candidate ID + sequence SHA256。

4. **新建 V4-H formal prediction freezer**  
   不能直接改 V4-F freezer；可复用其 replay、hash closure、exact schema 和 atomic publication 模式，但必须有新的 H-specific prereg/test/freeze/trust anchor。

5. **只有完整预测冻结 gate 通过后才能接受 H96 Docking-label path**  
   V4-H preregistration 明确规定 manifest、model/config、96-row predictions、audit 和 receipt 全部 hash-close 在先（`audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json:66-100`）。

如果不计划训练真实 contact-stage model，则应另起一个 sequence-primary 的 V4-H-DEV 或 formal V2 preregistration，并在任何 H96 Docking label 读取前冻结。这条路不得宣称是现有 V4-H formal V1 的 PASS/FAIL。

## 10. 建议 handoff

### Handoff A：executor

实现新的 `V4-H-DEV1-PRED1` label-free adapter/freezer：

- exact field mapping；
- H96-specific mean-pool prior materialization；
- DEV1 serialized artifact replay；
- staged atomic publication；
- DEV-only audit/receipt；
- 不触发 Docking 和 formal evaluator。

### Handoff B：test-engineer / verifier

用 adversarial tests 验证：

- `model_split` 静默 alias 被拒绝；
- `frozen_feature_ridge` 冒充 contact 被拒绝；
- CDR 映射/序列 hash/prior hash 篡改被拒绝；
- 任何 H96/V4-D test32/V4-F label path 传入被拒绝；
- receipt 提前发布、symlink、非常规文件、不完整 input closure 被拒绝；
- normal 和 `PYTHONOPTIMIZE=1` 均通过。

### Handoff C：architect / critic

在不看 H96 Docking label 的前提下，冻结一个治理决策：

```text
保留 formal V1 contact-family primary，并训练真实 contact-stage DEV1
    或
另起 sequence-primary V4-H formal V2/DEV 版本
```

无论哪条路，都不应修改现有 V1 的阈值、指标、endpoint 或 evidence boundary。

## 11. 最终判定

```text
H96 label-free panel                 READY
CDR/sequence adapter mapping         READY
H96 same-model generic prior         IMPLEMENTABLE, MUST RECOMPUTE
DEV1 sequence prediction freeze      IMPLEMENTABLE AS NEW DEV-ONLY VERSION
existing V4-H formal V1 compatibility BLOCKED
```

两个 formal blocker 是合同性问题，不是数值训练问题：

1. `model_split` identity 不一致；
2. sequence-only `frozen_feature_ridge` 不是 preregistered contact-stage primary family。

在这两点被新版本 prelabel 解决前，可以安全推进 DEV-only H96 prediction freeze，但不能用它解锁现有 V4-H formal Docking/evaluator。
