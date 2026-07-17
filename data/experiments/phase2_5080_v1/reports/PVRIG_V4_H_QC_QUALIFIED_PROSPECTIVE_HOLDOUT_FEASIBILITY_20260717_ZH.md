# PVRIG V4-H QC-qualified prospective holdout 可行性审计

**审计日期：** 2026-07-17（Asia/Shanghai）  
**建议版本名：** `V4-H-QC96`，不建议命名为 `V4-F2`  
**当前结论：** `FAIL_NO_EXISTING_QC_QUALIFIED_96_PANEL / PASS_CONDITIONAL_LABEL_FREE_PREFLIGHT`  
**执行状态：** 本文只完成只读、label-free 可行性审计；未生成新候选、未启动 Fast-QC、Full-QC、结构预测或 Docking。

---

## 1. 结论先行

当前不能从已经冻结的 7,087 条候选库中再抽出一个满足要求的新 prospective holdout，原因不是候选条数不够，而是 **parent framework cluster 已被完全分配**：

| 已冻结用途 | parent cluster 数 | cluster |
|---|---:|---|
| V4-D open train/dev/test | 26 | `C0009,C0116,C0139,C0210,C0219,C0224,C0248,C0251,C0258,C0299,C0304,C0311,C0354,C0406,C0411,C0418,C0448,C0453,C0474,C0492,C0495,C0500,C0502,C0509,C0518,C0533` |
| 旧 V4-F96 | 4 | `C0198,C0379,C0401,C0515` |
| V4-G unseen96 | 8 | `C0051,C0154,C0324,C0372,C0375,C0404,C0504,C0514` |
| V4-G untouched reserve | 2 | `C0019,C0072` |
| **并集** | **40/40** | 互不重叠，覆盖原始 40 个 parent cluster |

因此：

1. 在原 7,087 库内，排除 V4-D、旧 V4-F、V4-G 后只剩两个 reserve cluster；
2. 若同时保持 reserve2 untouched，则剩余为零；
3. 即使动用 reserve2，也达不到 formal evaluator 要求的至少四个 parent cluster；
4. 不能通过放回 V4-D/V4-G parent、把同一 parent 的变体当独立 cluster、或修改旧 V4-F 来“补足”四个 cluster。

**可行的新路线是：** 从 Top-200 scaffold 中冻结一组从未进入 V4-D/V4-F/V4-G 的 parent queue，重新做 PVRIG 条件化 CDR 设计；先对全部新序列运行冻结的 Fast-QC 和 Full-QC，再按预先冻结的纯 QC 规则组成 `4 parent × 24 = 96` 条 `V4-H-QC96`。只有新 manifest、模型预测和配置全部冻结后，才可启动独立 8X6B/9E6Y Docking。

---

## 2. 证据边界

本次审计只使用：

- candidate ID、序列、SHA256；
- parent ID、`parent_framework_cluster`；
- target patch、design mode、CDR/长度等设计元数据；
- Node1 frozen large-scale-fast QC 的 hard-pass/hard-fail 与失败原因；
- label-free Full-QC 规划/状态；
- Top-200 scaffold 的 numbering、framework、developability、FR4、Cys、PTM 和 provenance 字段。

本次审计没有读取：

- `R_dual_min`、`R_8X6B`、`R_9E6Y`；
- G1–G5、hotspot/occlusion、HADDOCK score 或任何 Docking geometry；
- V4-D test32、V4-F Docking labels；
- 任一模型的 score、prediction、rank 或 uncertainty；
- 实验 binding、affinity、competition 或 blocking 标签。

本文中的 “pass” 仅指 sequence/developability QC；不代表结合、阻断或 Docking 成功。

---

## 3. 已有 Fast-QC 证据说明了什么

冻结的 7,087-candidate Node1 census 路径：

```text
reports/pvrig_candidate7087_node1_fastqc_census_v1_20260716/
  runtime_evidence/outputs/candidate7087_node1_fastqc_census_v1.tsv
  runtime_evidence/outputs/parent40_node1_fastqc_capacity_v1.tsv
  runtime_evidence/outputs/candidate7087_node1_fastqc_census_v1.audit.json
  runtime_evidence/outputs/candidate7087_node1_fastqc_census_v1.receipt.json
```

结果为：

```text
7,087 candidates
4,578 Fast-QC hard pass
2,509 Fast-QC hard fail
40 parent clusters
29 capacity-ready parents
11 insufficient parents
```

### 3.1 旧 V4-F96 的状态必须保留

旧 V4-F 的 96 条全部可以在冻结 census 中闭合到 candidate ID，结果是：

```text
96/96 fast_hard_fail = True
```

本地 reason 汇总：

| reason_summary | 数量 |
|---|---:|
| `numbering_or_framework_failed;hydrophobic_run` | 52 |
| `numbering_or_framework_failed` | 32 |
| `numbering_or_framework_failed;odd_cysteine_count` | 12 |

四个 V4-F parent 的冻结 FR4 tail 分别是：

| cluster | parent | FR4 tail | Fast-QC pass/candidate |
|---|---|---|---:|
| C0198 | PLDNANO_VHH_00292 | `WGQGTQVTVSL` | 0/168 |
| C0379 | PLDNANO_VHH_00565 | `WGQGTQVTVSE` | 0/176 |
| C0401 | PLDNANO_VHH_00594 | `WGQGTQVTVS` | 0/180 |
| C0515 | PLDNANO_VHH_00892 | `WGQGTQVTVFS` | 0/169 |

这些结果与当前“FR4/framework hard fail”诊断一致。旧 V4-F formal evaluation 应继续保留为 `INSUFFICIENT`；不能删除旧 manifest、替换候选、修改 gate，或把新面板描述为旧 V4-F 的成功重跑。

### 3.2 其他已有库不能直接解决问题

- Support V4-A acquisition720 的 20 个 parent 全部来自 V4-D `OPEN_TRAIN`，可用于 teacher acquisition，但不能作为 unseen prospective holdout。
- 现有 RFantibody 1000 库只有一个 `h-NbBCII10` framework lineage，不能提供四个独立 parent cluster。
- reserve2 只有 `C0019`、`C0072` 两个 parent；且 `C0072` 的冻结 Fast-QC capacity 为 0/181。

所以当前没有一个已存在、已 Fast-QC 证明、同时满足四个新 parent cluster 的 96 条面板。

---

## 4. 新 parent queue 的选择规则（先冻结规则，再列 cluster）

以下规则用于 **preflight parent queue**，不是最终 V4-H manifest。正式执行前应把规则、输入哈希和代码写入独立 preregistration/implementation freeze。

### 4.1 输入

主输入：

```text
../scaffolds/top_200_vhh_scaffolds_for_design.csv
SHA256 16b478534ba350ef1b101099411f412d5b52bfb1482015ddd21d007c3b5e5861
```

排除输入：

```text
V4-D manifest    c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd
old V4-F manifest 3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334
V4-G manifest    e814103ee90831e33b3f04a7e8a477e68695d61401d96732b7e95829b1bd306f
reserve2         98c11e8f72d97d60c9e772fa2bb256622f1ed6e1e9fddd9e136a8cd42959bb75
calibration exact-sequence exclusions
                 cba42df8ad9fab0399eb8a7d8608397fdf85aeea6619e2993e46d12d31dbd7d4
```

### 4.2 parent 资格硬门

Top-200 中的 parent 必须同时满足：

1. cluster 不属于 V4-D、旧 V4-F、V4-G 或 reserve2 的 40-cluster 并集；
2. parent ID 和 exact sequence 未出现在上述冻结 manifest；
3. parent exact sequence SHA256 未命中 90 条 calibration exclusion；
4. `keep_or_drop=keep`；
5. `numbering_status=anarci_success`；
6. `is_vhh=yes`；
7. `framework_health_status=pass_framework_health`；
8. `developability_status=pass_developability`；
9. `target_related_similarity_status=pass_positive_leakage_gate`；
10. 仅含 20 种标准氨基酸，长度 110–135 aa；
11. terminal tail 必须精确为 `WGQGTQVTVSS`；
12. parent sequence 必须恰有 2 个 Cys；
13. `ptm_risk_flags` 为空，`free_cys_risk=low`。

上述强保守门在 Top-200 中留下 **67 个**可进入生成 preflight 的未用 parent cluster。这个数字只是 scaffold-level eligibility，不是 candidate-level Fast-QC pass 证明。

### 4.3 冻结排序

建议冻结：

```text
seed = phase2_v4_h_qc_qualified_prospective_holdout_20260717
selection_hash = SHA256(seed + "|" + cluster_id)
排序 = score_v1_1 降序，然后 selection_hash 升序，然后 cluster_id 升序
```

任何 parent 是否最终进入 V4-H，只能由下面第 6 节预注册的 label-free QC capacity gate 决定；不得使用模型分数或 Docking 结果改变顺序。

---

## 5. 按上述规则得到的冻结候选队列

### 5.1 前四个 primary parent（尚未 QC-qualified）

| queue rank | cluster | parent_id | accession | parent sequence SHA256 | length | source CDR3 len | HR151/Tab5 max CDR identity | selection hash |
|---:|---|---|---|---|---:|---:|---:|---|
| 1 | **C0162** | PLDNANO_VHH_00231 | AOI36585 | `420bbd19b0370b554cc9aa0e16862cd0ee7ce9f8196917d360d8314a91eb4ed8` | 121 | 14 | 50.0% | `00b1611963b67189bee8676cfd0a4edbe8d1c8b0c000b96193bc6b7deb8e5c6e` |
| 2 | **C0371** | PLDNANO_VHH_00553 | QYQ19596 | `9456c8ce783b422a6da055edde6b08c0e2e7940fb63ac884224e3eedca49c656` | 121 | 20 | 44.4% | `05fd500ceb512991f36a5cf60003841b66ab8b14aac93affa5dca694bad1f351` |
| 3 | **C0283** | PLDNANO_VHH_00423 | AKE13335 | `a5ffdb0bab1981efc64b49aa955b16cd7fb8cd3878635fe9141637fb7b80f91c` | 130 | 19 | 30.0% | `0785530cf89cece967f8e3b81cac0914746ca1726ffc22cde0aadf41eac05a66` |
| 4 | **C0148** | PLDNANO_VHH_00211 | APO05852 | `3cb053b8587a7e9d883cd0a7d85b24929c580ac0a326146ae39a57e94992fd7c` | 124 | 17 | 37.5% | `08e17de78d1127c464594183cbc16bf976a7b1c2ddf8b2f5413a84b517ea7076` |

这四个 cluster 均：

- 不在 V4-D、旧 V4-F、V4-G、reserve2；
- parent exact sequence 不在 calibration exact-exclusion 表；
- 使用完整 `WGQGTQVTVSS` FR4；
- parent 只有两个 Cys；
- Top-200 framework/developability/numbering/leakage gate 通过。

但必须明确：**当前没有这些新 parent 的 PVRIG 条件化候选，也没有 candidate-level Fast-QC/Full-QC 结果，所以现在不能声称每 cluster 已有 16–24 条 pass。**

### 5.2 预先排序的 reserve parent

为避免看到 QC 结果后临时挑 parent，建议同时冻结至少 12 个 parent 的完整 queue：

| rank | cluster | parent_id | accession | CDR3 len | selection hash prefix |
|---:|---|---|---|---:|---|
| 5 | C0078 | PLDNANO_VHH_00118 | AVY47144 | 17 | `0ebcc3b7ba52` |
| 6 | C0145 | PLDNANO_VHH_00207 | APO05859 | 15 | `0f16adb6a372` |
| 7 | C0086 | PLDNANO_VHH_00136 | AVC21983_H | 20 | `118e314d71f5` |
| 8 | C0417 | PLDNANO_VHH_00622 | QRL94740 | 12 | `12a2e851c356` |
| 9 | C0176 | PLDNANO_VHH_00257 | AOI36546 | 21 | `1469a2086d24` |
| 10 | C0348 | PLDNANO_VHH_00508 | AGV76525 | 18 | `14b1f7665dd1` |
| 11 | C0409 | PLDNANO_VHH_00614 | QRL94750 | 14 | `1848172b575a` |
| 12 | C0360 | PLDNANO_VHH_00531 | AGF21639 | 18 | `19c7b2b4ffa4` |

reserve 不是 Docking 后 replacement。它们只允许在 **最终 holdout 尚未冻结、且只看 label-free QC capacity** 时，按预先冻结顺序补足四个合格 parent。

---

## 6. 可执行的 label-free preflight

### Stage H0：先冻结协议和 parent queue

新建独立版本，不修改任何 V4-D/V4-F 文件：

```text
experiments/phase2_5080_v1/data_splits/pvrig_v4_h/
experiments/phase2_5080_v1/audits/phase2_v4_h_qc96_preregistration.json
```

preregistration 至少冻结：

- Top-200、D/F/G/reserve/calibration 输入哈希；
- 上述 parent eligibility 和完整 12-parent queue；
- generator 版本、target structure、hotspot、seed、CDR loop 和 ProteinMPNN 配置；
- Fast-QC 和 Full-QC 工具/配置/positive cache 哈希；
- capacity gate、candidate hash selection 和 fail-closed 条件；
- label-path access 必须全部为 0。

### Stage H1：生成 label-free 候选

建议保持与原 formal design library 一致的六个 strata：

```text
3 patches: A_CENTER / B_LOWER / C_CROSS
2 modes:   H3 / H1H3
```

为每个冻结 parent、每个 stratum 预先生成 20 条 exact-unique candidate：

```text
12 parents × 6 strata × 20 = 1,440 raw preflight candidates
```

生成过程必须保护：

- framework 与 FR4 不被改写；
- CDR2 在 H3/H1H3 模式下保持冻结；
- candidate ID、parent、seed、backbone、MPNN index 和序列哈希闭合；
- 与已知阳性/calibration exact sequence 和 CDR identity gate 分离处理；
- 不运行、不读取模型分数。

### Stage H2：对全部 1,440 运行冻结 Fast-QC

使用与 7,087 census 相同的：

```text
vhh-competition-qc
--gate-policy blocker_calibrated
--large-scale-fast
```

必须保留 candidate-level：

```text
fast_hard_fail
reason_summary
official_validator_failed_reason
numbering/framework/FR4 state
sequence_sha256
```

不得因为某个 parent 结果差而改 FR4 规则、阈值或生成序列。

### Stage H3：对全部 Fast-QC hard-pass 运行冻结 Full-QC

新 holdout 应当是 **QC-qualified prospective holdout**，因此最终冻结前还应运行 label-free Full-QC：

```text
official validator
ANARCI/IMGT
AbNatiV
Sapiens/human-likeness
ProtParam/liability
positive CDR novelty
```

TNP 是否运行应在 preregistration 中一次性冻结；不能在看到结果后改变。无论是否运行，Full-QC hard-pass 定义必须在 H0 固定。

### Stage H4：纯 QC capacity gate 后冻结 96 条

一个 parent 只有同时满足以下条件才是 `QC_CAPACITY_READY`：

```text
Full-QC hard-pass >=24
且六个 patch×mode strata 每个 >=4 条 Full-QC hard-pass
```

然后：

1. 按 H0 冻结的 parent queue 顺序取前四个 `QC_CAPACITY_READY` parent；
2. 每 parent × patch × mode 内，用预先冻结的 candidate hash 排序；
3. 每 stratum 取前 4 条；
4. 得到 `4 parents × 6 strata × 4 = 96`；
5. 输出 immutable manifest、audit、receipt、SHA256SUMS；
6. 冻结后不得因结构或 Docking 失败 replacement。

若 12-parent queue 中少于四个 parent 通过上述 gate：

```text
FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY
```

此时不得降到三个 parent、不得临时增补未登记 parent、不得启动 Docking；应另起新的生成/preflight 版本。

### Stage H5：预测冻结后才允许 Docking

顺序必须是：

```text
V4-H manifest/receipt frozen
→ surrogate model/config frozen
→ 96 条预测和 rank frozen
→ verify zero label access
→ independent 8X6B/9E6Y Docking
→ one-shot formal evaluation
```

Docking 后不允许 replacement。若 Docking/technical success 低于 formal evaluator 的最小分析数，则结果仍应是 `INSUFFICIENT`，不能继续改面板。

---

## 7. Formal evaluator 的处理

不应把旧 V4-F evaluator 的输入哈希直接改成新面板。应另建：

```text
phase2_v4_h_qc96_formal_evaluator_v1
```

原则：

- 保持 V4-F V2 已冻结的科学指标和阈值，不因旧 F 的 QC 失败而调低；
- 主目标仍为 `R_dual_min`；
- 仍报告 overall/parent-macro Spearman、Recall@20%、EF@10%、parent bootstrap CI 和 uncertainty selective risk；
- minimum analyzable count 仍至少 64，至少 4 parent clusters；
- 新 evaluator 绑定新的 manifest、prediction receipt、Docking label receipt 和 one-shot runtime trust；
- V4-H 只代表 QC-qualified、new-parent、PVRIG-conditioned design universe，不能外推到未经 QC 的全部设计库。

---

## 8. Post-selection 风险与控制

### 风险 1：看到旧 V4-F 失败后选择 canonical FR4

这是明确的 QC-domain 修正，因此新面板不能声称是旧 V4-F 的续跑或替换。控制方式是另起 `V4-H`，并把旧 F 的 96/96 attrition 与 `INSUFFICIENT` 永久保留。

### 风险 2：按 Fast/Full-QC 选择会改变目标分布

这是有意的：V4-H 的 estimand 是“实际可进入结构/Docking 的 QC-qualified candidate universe”，不是原始未筛选 universe。报告必须明确这个条件化边界。

### 风险 3：QC 后从 reserve parent 补位可能形成事后挑选

只有在 H0 冻结完整 parent queue、capacity gate 和 hash selection 后，按纯 QC 结果顺序取前四个，才可接受。任何人工看序列、模型分数或 Docking 结果后的挑选都禁止。

### 风险 4：新 generator 造成 distribution shift

应尽量复用原 PVRIG formal library 的 patches、H3/H1H3 设计模式、framework protection 和 ProteinMPNN/collector contract；所有差异必须写入 generation manifest，并在最终报告中单独解释。

### 风险 5：新面板被用于反复调模型

V4-H 应 one-shot。预测一旦冻结，不能看 Docking 结果后继续调相同版本并重复声称 formal。若失败，后续模型必须另起版本，并将 V4-H 视为已见 development evidence。

---

## 9. 旧 V4-F 失败证据如何保留

以下文件继续 immutable，不覆盖、不删除：

```text
experiments/phase2_5080_v1/data_splits/pvrig_v4_f/
  prospective_holdout96_manifest.tsv
  prospective_holdout96_audit.json
  prospective_holdout96_receipt.json

experiments/phase2_5080_v1/audits/
  phase2_v4_f96_formal_evaluator_v2_preregistration.json

reports/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717/
```

建议新增一个只追加的 supersession/lineage 说明：

```text
V4-F = frozen prospective panel; terminal evaluation state INSUFFICIENT due to QC attrition
V4-H = new QC-qualified prospective protocol; does not revise or replace V4-F evidence
```

---

## 10. 下一步执行顺序

```text
1. 冻结 V4-H H0 preregistration、12-parent queue、生成与 QC 配置
2. 为 12 parents 生成 1,440 条 PVRIG-conditioned candidates
3. 对 1,440 条运行 frozen Fast-QC
4. 对 Fast-QC pass 运行 frozen Full-QC
5. 按预注册 capacity/hash 规则冻结 4×24=96
6. 输出 V4-H manifest/audit/receipt，验证与 D/F/G/calibration 零重叠
7. 冻结 surrogate model/config 和 96 条 predictions
8. 再启动 independent 8X6B/9E6Y Docking
9. 使用独立 V4-H evaluator 一次性评估
```

当前的停止点是第 1 步之前：**已有数据足以证明新方案在 scaffold 供给上可行，但不足以声称已有 96 条 QC-qualified candidate。**

---

## 11. 最终判断

```text
现有 7,087 frozen design universe：不可行
  原因：40/40 parent clusters 已被 D/F/G/reserve 分配；旧 F 96/96 Fast-QC hard fail

Top-200 新 parent 供给：可行
  67 个 parent 通过保守 scaffold eligibility
  首选队列：C0162, C0371, C0283, C0148
  reserve：C0078, C0145, C0086, C0417, C0176, C0348, C0409, C0360

当前是否已有 96 条 QC-qualified holdout：否
  必须先执行新生成 + frozen Fast-QC + frozen Full-QC

建议版本：V4-H-QC96
  不修改 V4-F；不将新面板称为 V4-F PASS；不在 Docking 后 replacement
```

`V4-H-QC96` 的价值不是把旧 V4-F “修成通过”，而是建立一个定义更合理、技术上可分析、且仍对 Docking labels 完全 prospective 的新 parent-cluster holdout。
