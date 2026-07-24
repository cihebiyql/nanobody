# PVRIG 数千条已 Docking VHH 的末端筛选规范 V1

版本：`pvrig.finalist_screening.v1.20260724`  
状态：规范冻结，现有 6,042 条 dry-run 通过  
目的：把已经完成结构与 docking 的数千条候选，稳定缩减为可审计的 200、80 和最终 50 条。

## 1. 核心原则

1. **先硬门控，后排名**：技术失败、提交不合规、阳性泄漏、结构证据不完整不能靠高分补偿。
2. **结合与阻断分开**：binder prior 与 blocker geometry 是两条证据线。
3. **不伪造实验指标**：计算分数不称 BLI response、表达量、纯度、Kd 或 IC50。
4. **不使用一个不透明总分**：保留“初筛生存”和“复筛竞争”两个排名。
5. **先通过阳性/控制校准，再启用新软件**：Rosetta、MD、MMGBSA 未通过校准前只能作审计字段。
6. **最终选择是投资组合，不是简单 Top50**：必须限制 parent、route 和 CDR3 近重复。

## 2. 当前真实起点

已经完成严格 docking 的两个互斥集合：

| 路线 | strict 候选 | 规则 |
|---|---:|---|
| 旧 Top7500 | 1,923 | 至少 2 个完整 seed，至少 2 个双构象严格通过 |
| C2 复核 | 4,119 | 4/4 seed 双构象严格通过 |
| 合计 | **6,042** | 两集合 candidate ID 无重叠 |

当前 V1 dry-run：

| 路线 | strict docking | 可开发性硬门控 | weak-binding top20% | surrogate 高支持 | 三者交集 |
|---|---:|---:|---:|---:|---:|
| 旧 Top7500 | 1,923 | 1,837 | 1,036 | 127 | 103 |
| C2 四 seed | 4,119 | 3,139 | 976 | 2,498 | 345 |
| 合计 | **6,042** | **4,976** | **2,012** | **2,625** | **448** |

448 条 `CORE_A` 的 parent 构成：

- HR-151：270；
- 151H7：146；
- PVRIG-38：32。

CDR3 dry-run 聚类（同长度、Hamming identity `>=0.80`）：

- 43 个 cluster；
- 最大 cluster 有 144 条；
- 12 个 cluster 含多条候选；
- 30 组 exact CDR3 重复，共涉及 88 条候选。

因此直接取 CORE_A 综合分前 50 会同时产生严重 parent 偏置和 CDR3 近重复偏置。

## 3. 硬门控

### G0 技术与哈希完整性

必须全部满足：

- candidate ID 唯一；
- 序列只含标准 20 AA；
- sequence SHA256 与实际序列一致；
- NBB2 成功；
- NBB2 PDB 与候选序列一致；
- 必填模型无 `TECHNICAL_NA`；
- docking、结构和源 manifest hash 能闭合。

任何必填证据缺失均记为 `BLOCKED_TECHNICAL`，不能当作生物学阴性。

### G1 官方提交合规

- 官方 `ab-data-validator`：PASS；
- ANARCI 按 IMGT 编号成功；
- FR1/2/3/4、CDR1/2/3 完整；
- 每个对应 CDR 对完整公开阳性库 identity `<0.80`；
- 内部安全边际：最大对应 CDR identity `<=0.75`；
- exact known-positive leakage：FAIL；
- near-positive：人工复核或排除；
- 优化改造候选必须保存起始分子与改造说明。

注意：当前 448 只是内部 identity 字段通过，仍必须再跑最终官方 validator 和完整阳性库。

### G2 可开发性

当前冻结门槛：

- TNP：`PASS/CLEAR`，red flag=0；
- AbNatiV VHH score `>=0.70`；
- Sapiens mean self probability `>=0.70`；
- expression/purity risk proxy `>=85`；
- Cys=2；
- N-glycosylation motif=0；
- 5 连续疏水=0；
- ANARCI QC=PASS。

pI、deamidation、isomerization、oxidation 等暂作 warning/rank，不能未经阳性校准任意 hard fail。

### G3 Docking

从当前 6,042 条开始时已满足：

- 双参考：8X6B、9E6Y；
- 双构象；
- native/cross 几何评分；
- 旧路线至少 2 个 seed 严格通过；
- C2 路线 4/4 seed 严格通过。

这些结果只代表 blocker-like geometry，不代表实验阻断。

## 4. 软证据与候选等级

### CORE_A

同时满足：

- G0–G3；
- weak-binding consensus 位于当前 top20%，阈值 `>=0.6783883333333334`；
- route-specific surrogate 高支持：
  - 旧路线：`A_HIGH_AGREEMENT`；
  - C2：`high_confidence_core_flag=true`。

当前 448 条。

### DIVERSITY_B

从 4,976 条 developability hard-pass 中选择：

- 仍满足 strict docking；
- parent、CDR3 或 route 能补足 CORE_A 的集中偏置；
- weak binding 或 surrogate 可以不是最高档，但不能存在硬门控失败。

### DISAGREEMENT_C

- strict docking 很稳；
- DeepNano/NanoBind、surrogate 或静态能量存在分歧；
- 用于发现共同模型盲区；
- 必须人工复核或进入静态能量/短 MD。

### RESERVE_D

- G0–G3 通过；
- 具有不同 CDR3 长度、parent、序列簇或设计路线；
- 证据较弱，必须明确标成 reserve。

## 5. 两个排名

### 初筛生存代理

```text
initial_survival_proxy =
    0.70 × binding-prior percentile
  + 0.20 × expression-proxy percentile
  + 0.10 × developability/purity-proxy percentile
```

只用于模拟官网 BLI 单浓度、表达量和纯度的权重关系，不等于对应实验指标。

### 复筛竞争代理

```text
rescreen_competition_proxy =
    0.50 × affinity-prior percentile
  + 0.50 × blocker-mechanism percentile
```

只用于模拟 Kd/IC50 各 50% 的目标，不称预测 Kd 或 IC50。

最终排序：

```text
硬门控状态
→ 初筛生存风险
→ 复筛竞争排名
→ parent/CDR3/route 约束
→ 人工机制复核
```

禁止把两个排名再次压成一个无法解释的总分。

## 6. 分层缩减

### P0：6,042 → 合规集合

- 跑官方 validator；
- 完整阳性库 CDR similarity；
- sequence/hash/provenance closure；
- 输出所有 hard-fail 和 technical-blocked 行。

### P1：合规集合 → 4,976 左右

- 执行 G2 可开发性门控；
- 这里只是当前 dry-run 预期，正式计数以 P0 后结果为准。

### P2：建立 200 条静态复核组合

推荐通道：

| 通道 | 数量 |
|---|---:|
| CORE_A exploitation | 120 |
| parent/CDR3 diversity | 40 |
| model disagreement rescue | 20 |
| structural reserve | 20 |

不能直接把 448 的前 200 当作结果。

### P3：200 → 80

执行：

- pose 人工/规则审计；
- PRODIGY、FoldX、Rosetta；
- 近重复聚类；
- 证据完整性检查。

只有通过阳性/控制校准的软件才允许参与排名。当前：

- PRODIGY：弱先验；
- FoldX 跨候选绝对亲和力：拒绝；
- FoldX 同 parent ΔΔG：诊断；
- Rosetta：等待同面板校准。

### P4：80 → 50

- 选择 20–50 条跑短 MD；
- 若计算资源有限，优先覆盖 Top10、模型分歧和 parent diversity；
- 未跑 MD 的 reserve 保留 `NOT_RUN`，不能填 0。

### P5：最终冻结

- 50 条最终排序；
- Top10 单独标记；
- 全部输入、输出和脚本 SHA256；
- 保存设计来源、parent、序列、CDR、模型版本、结构与 docking 协议。

## 7. 最终 50 组合约束

建议构成：

- 30 条 exploitation；
- 10 条 parent/mechanism diversity；
- 5 条 disagreement rescue；
- 5 条 structural reserve。

约束：

- exact sequence duplicate：0；
- exact CDR3：最多 1 条；
- 同长度 CDR3 identity `>=0.80` 的近族群：最多 2 条；
- 单一 parent：最多 15 条；
- 单一路线：最多 35 条；
- 如果合格候选允许，至少 4 个 parent cluster；
- Top10：7 条最高置信核心 + 3 条独立 parent/机制；
- Top10 单一 parent 最多 4，单一路线最多 7。

若约束无法满足，只能写入机器可读 exception，不能静默放宽。

## 8. MD 的位置

MD 不是数千条筛选工具，而是 20–50 条末端假阳性复核工具。

优先判断：

- CDR3 和界面 RMSD/RMSF；
- PVRIG hotspot contact occupancy；
- PVRL2 遮挡保持率；
- 界面氢键和盐桥占有率；
- MMGBSA median/IQR。

动力学判别方法必须先通过：

- 阳性召回率 `>=0.80`；
- 控制假阳性率 `<=0.30`；
- AUROC `>=0.70`；
- seed 一致性至少 2/3；
- 四组 parent 配对至少 3/4 方向正确。

否则 MD 结果只用于人工复核。

## 9. 必须输出的审计文件

- `candidate_evidence_table.tsv`
- `funnel_counts.tsv`
- `hard_gate_failures.tsv`
- `core_and_rescue_pool.tsv`
- `pairwise_diversity_clusters.tsv`
- `top200_pre_static.tsv`
- `top80_post_static.tsv`
- `md_manifest.tsv`
- `final50_ranked.tsv`
- `top10_priority.tsv`
- `STATUS.json`
- `SHA256SUMS`

## 10. 当前规范资产

- `SCREENING_CONTRACT_V1.json`：规则合同；
- `SCREENING_OUTPUT_SCHEMA_V1.json`：输出字段和 null policy；
- `surrogate_high_support_snapshot.tsv`：冻结的 surrogate 高支持成员；
- `dry_run_existing_6042.py`：当前 6,042 条回归测试；
- `dry_run/strict6042_standard_dry_run.tsv`：6,042 条逐条门控结果；
- `dry_run/core448_candidates.tsv`：448 条 CORE_A；
- `dry_run/core448_cdr3_clusters.tsv`：448 条的 CDR3 80% 聚类；
- `dry_run/funnel_counts.tsv`：漏斗计数；
- `dry_run/DRY_RUN_RECEIPT.json`：输入/输出 hash 收据。

复现：

```bash
python reports/pvrig_finalist_screening_standard_v1_20260724/dry_run_existing_6042.py
```
