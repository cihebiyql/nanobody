# PVRIG 赛题官网对齐的下一轮筛选方案

日期：2026-07-24  
范围：Node1/BXCPU 当前已落盘的 PVRIG VHH 生成、多模型、结构与 docking 资产  
结论状态：可立即从已完成 docking 的集合收敛首轮 50 条；新 100k 结构集合尚缺 docking 闭环，只作为并行扩展路线。

## 1. 官网正式要求

官方页面：

- https://www.bioshanghaiweek.com/2026/SICBC?lan=cn&section=5
- 附件 7（实验测试流程与评分规则）：
  https://imgcdn.yicai.com/ibiws/files/2026/06/639179778135220000.pdf
- 附件 8（实验筛选流程图）：
  https://imgcdn.yicai.com/ibiws/files/2026/06/639179778298340000.pdf

本次下载校验：

- 附件 7 SHA256：
  `0729e221d4a89f5ff54e3581430dc046c46d773b18f5dc1b54b10a39ec7d0ddc`
- 附件 8 SHA256：
  `f65cb9208ddf73696bed0dc57e8950031aa6cea8e20f47103225fedcdef53781`

必须按以下语义理解官网指标：

1. 初筛：
   - BLI 单浓度结合得分权重 70%；
   - 表达量权重 20%；
   - 纯度权重 10%。
2. BLI 单浓度在不高于 500 nM 抗原浓度下：
   - response shift >= 0.1 nm：结合；
   - 0 <= response shift < 0.1 nm：弱结合；
   - response shift < 0 nm：不结合。
3. 表达量：
   - >100 mg/L：100 分；
   - 25–100 mg/L：60 分；
   - <25 mg/L：0 分。
4. 纯度：
   - >=90%：100 分；
   - 80–90%：80 分；
   - <80%：60 分。
5. 复筛：
   - 五浓度 BLI 拟合 Kd；
   - 竞争 ELISA 测 IC50；
   - Kd 排名得分与 IC50 排名得分各占 50%。
6. 每队提交 50 条并按预测顺序排序，原则上不超过 10 条进入实验。
7. 使用 ANARCI/IMGT 与 MUSCLE/Hamming identity 做 CDR 相似性审查；每个对应 CDR 对已知阳性参照原则上应低于 80%。
8. 优化改造候选需要提交起始分子信息。
9. 当前首轮截止时间为 2026-07-26 18:00。

### 重要语义边界

- 本地 `expression_purity_risk_score`、TNP、AbNatiV、Sapiens 只是表达、聚集、天然性、人源性和结构可开发性代理，不是官网的 SDS-PAGE/HPLC 实测纯度，也不能证明纯度 >=90%。
- DeepNano、NanoBind 和 generic binding prior 是弱结合先验，不是 BLI response、Kd 或 IC50。
- docking 与 blocker geometry 是阻断机制的计算支持，不是竞争 ELISA 实测阻断。

## 2. 当前两条可用路线

### 路线 A：已完成 docking 的 fixed-pose Top7500 路线

这是首轮提交最可靠的直接来源，因为它已经拥有：

- 150,000 条 fixed-pose 候选的序列多指标；
- NBB2 150,000/150,000；
- TNP 150,000/150,000；
- DeepNano + NanoBind；
- Sapiens + AbNatiV；
- 四/六模型 docking-geometry surrogate；
- 两批 Top7500 的双参考、双构象、多 seed docking。

关键入口：

- 多指标：
  `/mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/pvrig_1m_fixed_pose_top150k_multimetric_v2_20260722/fixed_pose_top150k_multimetric.tsv.gz`
- C2 Top7500：
  `/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722/c2_refined_top7500_docking_handoff_v1/TOP7500_C2_REFINED.tsv`
- docking 机制汇总：
  `/mnt/d/work/抗体/node1/reports/pvrig_top7500_mechanism_count_20260724/final_mechanism_count_receipt.json`

严格 docking 集合：

- 旧 Top7500：双 seed、双构象、双参考 strict A，1,923 条；
- C2 4,220 四 seed 复核集：四个 seed 全部 strict A，4,119 条。

为了得到一个可用于最终人工/官方校验的核心池，本报告采用以下保守计算条件：

- docking 满足上述 strict 条件；
- TNP `CLEAR`；
- AbNatiV 成功且 VHH score >=0.70；
- Sapiens mean self probability >=0.70；
- expression/purity risk proxy >=85；
- Cys 数为 2；
- 无 N-glycosylation motif；
- 无 5 连续疏水残基；
- 对当前阳性库任一对应 CDR identity <=0.75，给官网 0.80 门槛留安全边际；
- DeepNano/NanoBind weak-binding consensus 位于 fixed-pose 150k 的前 20%，阈值
  `binding_consensus_weak_prior >= 0.6783883333333334`；
- surrogate 高支持：
  - 旧 Top7500 为 `A_HIGH_AGREEMENT`；
  - C2 为 `high_confidence_core_flag=true`。

得到：

| 集合 | strict docking | 严格可开发性代理 | weak-affinity top20% | surrogate 高支持 | 三者交集 |
|---|---:|---:|---:|---:|---:|
| 旧 Top7500 | 1,923 | 1,837 | 1,036 | 127 | 103 |
| C2 四 seed 全通过 | 4,119 | 3,139 | 976 | 2,498 | 345 |
| 合计 | 6,042 | 4,976 | 2,012 | 2,625 | **448** |

这 448 条是当前最适合立刻进入“官方 validator + 团队内去近重复 + 最终 50 排序”的集合。

但 448 条存在明显 parent 偏置：

- 旧版 103 条：HR-151 parent 62，PVRIG-38 parent 32，151H7 parent 9；
- C2 345 条：HR-151 parent 208，151H7 parent 137。

因此不能直接取综合分前 50，否则会形成高度相关的单一机制/parent 投资组合。

### 路线 B：最新 Node1 generated300k -> structure100k 路线

当前状态：

- 300,000 条 sequence multimetric 完成；
- sequence hard-pass 299,870；
- 100,000 条 primary + 20,000 条 reserve 已冻结；
- NBB2 primary 100,000/100,000 成功；
- TNP 初次运行因 CDR 字段 alias 兼容问题产生 100,000 TECHNICAL_NA；
- 修复任务 `11945644` 与聚合任务 `11945645` 已于 2026-07-24 14:16 完成；
- 修复后 TNP 100,000/100,000 `PASS`，SHA256：
  `98819acdd9ce81077a4d00d37a5c7a98eedc70551fe9fb18c7d2769260902266`。

修复后的 TNP 主结果：

`/publicfs04/fs04-al/home/als001821/pvrig_bxcpu_model_runtime_v1_20260721/node1_generated300k_structure100k_v1/tnp_aggregated_11945644/tnp_all.tsv.gz`

注意：截至 2026-07-24 14:22，Node1 目录中的
`metadata/tnp_aggregated_11945599/READY.json`
仍是旧的全量 TECHNICAL_NA 收据；下一步必须同步新结果并进行 ID/hash 闭合，不能读取旧收据做排序。

100k 当前计算漏斗：

| 条件 | 候选数 |
|---|---:|
| primary 结构集 | 100,000 |
| TNP 无 red flag | 91,727 |
| sequence developability tier=STANDARD | 95,045 |
| TNP 无 red + STANDARD | 86,998 |
| DeepNano/NanoBind 双模型 high weak-prior | 2,390 |
| 上项 + TNP 无 red + STANDARD | 2,011 |
| 上项 + expression/purity proxy >=80 | 1,889 |
| 上项 + AbNatiV>=0.70 + Sapiens>=0.70 | 1,808 |
| 上项 + 无 N-glyc + instability<=40 | **1,473** |

这 1,473 条适合成为新路线的下一批精细 docking 输入，但目前不能进入最终 50，因为尚无新的双参考、双构象、多 seed docking 完成证据。

## 3. 立即执行的筛选顺序

### 第一优先级：冻结首轮可提交主池

从路线 A 的 448 条开始：

1. 运行官方 `ab-data-validator`，不是只读取当前内部 `max_positive_cdr_identity`。
2. 使用完整公开阳性库重新跑 ANARCI/IMGT + MUSCLE/Hamming identity。
3. 要求每个 CDR identity <0.80；内部推荐继续使用 <=0.75 安全边际。
4. 对同队 448 条做团队内 CDR1/CDR2/CDR3 近重复审查。
5. 排除 incomplete seed、technical NA、hash 未闭合和 overlap reuse 尚未闭合的记录。
6. 为每条保留：
   - 起始 parent；
   - 设计方法；
   - 序列、CDR、hash；
   - 多模型原始分；
   - docking 双参考/双构象/seed 证据；
   - 科学边界说明。

### 第二优先级：建立两个不同的排名，而不是一个混合总分

#### 初筛生存排名

模拟官网初筛，但明确是代理：

```text
initial_survival_proxy =
  0.70 * binding-consensus rank
  + 0.20 * expression-risk rank
  + 0.10 * purity/developability rank
```

它只用于估计能否通过 BLI 单浓度、表达量和纯度初筛。

#### 复筛竞争排名

```text
rescreen_competition_proxy =
  0.50 * affinity-consensus rank
  + 0.50 * blocker-mechanism rank
```

其中：

- affinity-consensus：DeepNano、NanoBind、docking energy/contact 等独立信息的稳健 rank aggregation；
- blocker-mechanism：双参考、双构象、多 seed 的 strict 通过数及连续 occlusion 指标；
- 不把两者称为 Kd 或 IC50。

最终排序先要求初筛生存风险可接受，再按复筛竞争排名排序；不要继续沿用当前 100k 结构资源分配分数作为最终竞赛分数。

当前 100k 结构选择分数约 75% 来自 developability/Sapiens/AbNatiV、15% 来自 weak binding prior、10% 来自 novelty。它适合分配结构计算资源，但与官网 BLI 70% 和复筛 Kd/IC50 各 50% 的目标不一致。

### 第三优先级：50 条投资组合

推荐：

- 30 条 exploitation：
  从 448 核心池中按初筛生存门槛 + 复筛竞争排名选择；
- 10 条 parent/mechanism diversity：
  强制覆盖 PVRIG-38、PVRIG-20、PVRIG-39、39H2、20H5、151H8 等可用 parent，前提是仍满足 strict docking 和基本可开发性；
- 5 条 model-disagreement rescue：
  docking 极稳、但 DeepNano/NanoBind 分歧较大的候选；
- 5 条 structural/diversity reserve：
  不同 CDR3 长度、不同近族群、不同 parent/设计路线。

建议组合约束：

- final 50 exact CDR3 最多 1 条；
- >=80% identity 的同长度 CDR3 近族群最多 2 条；
- 单一 parent 最多 15 条；
- Top10 中单一 parent 最多 4 条；
- Top10 建议 7 条最高置信核心 + 3 条独立 parent/机制候选；
- 最终 50 必须按预测优先级排序，不按 parent 分组排列。

### 第四优先级：新 100k 路线并行扩展

1. 先同步并锁定修复后的 TNP 100k PASS 结果。
2. 将 1,473 条严格预筛候选作为主 docking 批次。
3. 另保留约 300 条 disagreement/diversity 候选，避免两个 binding prior 的共同盲区。
4. 使用与已完成 Top7500 相同的双参考、双构象、多 seed 合同。
5. 只有在 docking、hash、technical-NA 审计完成后，才允许替换首轮 50 中的候选。
6. 鉴于 2026-07-26 18:00 截止，不应等待该路线完成才开始冻结已有 448 核心池的最终 50。

## 4. 当前必须补齐的缺口

1. 448 条尚未跑最终版官方 validator。
2. 当前团队内 identity 字段不是最终官方口径。
3. 新 100k 的修复 TNP 结果尚未同步到 Node1 主状态入口。
4. 新 100k 尚无完整 docking。
5. C2 overlap 1,280 的 old/new monomer 与 job hash closure 仍未闭合；首轮选择应优先使用 exact-new 记录。
6. 目前无实验表达量、SDS/HPLC 纯度、BLI response、Kd 或 IC50；所有计算结果必须保持 proxy/geometry 表述。

## 5. 决策

首轮最稳妥方案不是继续从 100k 直接按“纯度/亲和力软件总分”取 50，而是：

```text
已完成 docking 的 6,042 strict 候选
-> 多软件可开发性 + weak-affinity + surrogate 高支持交集 448
-> 官方 validator + 完整阳性库相似性 + 团队内去近重复
-> 双排名（初筛生存、复筛竞争）
-> parent/CDR3/机制约束的 50 条组合
-> 优先级最高的 Top10
```

新 100k 路线应并行推进 1,473 + diversity rescue 的 docking，但不能替代当前已经闭环的首轮主路线。
