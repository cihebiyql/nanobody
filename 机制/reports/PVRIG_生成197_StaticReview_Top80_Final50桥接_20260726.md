# PVRIG 生成 Top3000 中 QC197 的 static-review → Top80 → Final50 桥接（V2）

**完成时间：**2026-07-26  
**最终状态：**`BRIDGE_AUDIT_COMPLETE`  
**最终输出：**只使用 V2；旧 Final50 未改写。  
**证据边界：**所有结论是计算优先级，不能表述为实验结合、Kd、IC50、CHO 表达量或纯度。

## 目标与输入

将生成 Top3000 中已通过整合 QC 的 **197** 条候选，以与旧池完全同类的桥接顺序接入：

```text
冻结 common4 docking pose
→ 每条提取 8X6B、9E6Y 各一个代表 pose
→ static review
→ 与旧 common4 Top200 合并（QC397）
→ Top80 多样性门控
→ Final50 / Top10 组合
```

输入由旧/新两部分组成：

|来源|候选数|原始 docking 覆盖|本轮 static-review|
|---|---:|---|---|
|旧池 common4 Top200|200|四随机种子 × 两构象的共同可比结果|既有 400 pose，已完成|
|生成 Top3000 整合 QC 合格池|197|每条 8/8 成功（4 seed × 2 构象）|本轮 394 pose，已完成|
|合计 QC397|397|共享 common4 几何序位|794 pose，恰好 2 pose/候选|

生成 197 的代表 pose 选择固定为：`STRICT_A` 优先 → strict-A fraction 降序 → HADDOCK score 升序 → seed → job ID；每个候选只保留每个构象一个已有 pose，**没有重新 docking**。

## 同协议性与排序规则

新增静态复核使用旧池 `run_top200_static.py` 的泛化副本。代码差异仅允许：从固定 `200/400` 改为任意偶数的 `N/2N` 计数、相应完整性检查及 schema/收据字段；静态几何、Rosetta、PRODIGY 计算逻辑未改变。逐行 diff：

```text
机制/data/audits/PVRIG_QC397_static_Top80_Final50_bridge_20260726_v2/runner_static_compatibility.diff
```

静态工具角色严格保持：

- Rosetta InterfaceAnalyzer：`DESCRIPTIVE_ONLY`
- PRODIGY：`WEAK_PRIOR_ONLY`
- FoldX：`NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED`
- static rank contribution：`0`

因此跨池排序没有混入不同来源的模型分数。唯一排序轴是已冻结的 QC397 shared-common4 几何序位，编码为：

```text
selection_score = 1,000,000 − unified_qc397_geometry_rank
```

Top80 与 Final50 仅将 static-review 作为“技术完整、两个构象均有诊断”的门槛/审计信息；Rosetta/PRODIGY 数值不改变候选相对名次。

## 完整性、硬门控与版本修正

- 新增 static panel：**394/394 成功、0 失败**；中位任务时间 6.438 秒。
- QC397：所有 397 条均为标准 20 AA、sequence SHA-256 一致、`official_validator_pass=PASS`、`pass_similarity_filter=PASS`，且无 `hard_fail=true`。
- 每条 QC397 都恰有 `8x6b` 与 `9e6y` 各一个静态指标记录。
- Top80：无重复 CDR3，最大同长度直接 CDR3 identity = **0.78947**，低于 0.80。
- Final50：无重复 sequence/CDR3，最大同长度直接 CDR3 identity = **0.78947**，低于 0.80。
- 旧冻结 Final50 内容未写入；其 SHA-256 复核仍为：
  `d1026f93b547013366ff803ee0fe7f1864df1cd02d758a24d72c988edcb37008`。

V1 桥接时发现生成 QC 表实际使用字段 `structure_selection_route`，而空字段 `source_route` 会把 RFantibody 候选错误折叠到 fixed-pose parent，影响 parent diversity cap。V1 保留为审计痕迹，**不作为结果使用**；V2 已按 `structure_selection_route` 重建，并在审计中强制验证：RFantibody 必须归入 `GENERATED_RFANTIBODY_<patch>`，fixed-pose MPNN 必须归入 `GENERATED_FIXED_POSE_MPNN`。

## V2 桥接结果

|层级|总数|旧池|生成 Top3000|选择结构|
|---|---:|---:|---:|---|
|QC397 static complete|397|200|197|两个构象 static 诊断齐全|
|Top80|80|31|49|48 CORE、16 parent/CDR3 diversity、7 model-disagreement、8 reserve、1 quota-safe backfill|
|Final50|50|23|27|30 exploitation、10 parent/mechanism diversity、5 model-disagreement、5 structural reserve|
|Top10|10|3|7|前 7 为 high-confidence core，后 3 为独立 parent/mechanism 补充|

Top80 的 model-disagreement 来源只有 7 条，因此按旧选择器既有 fallback 规则产生 1 条 `QUOTA_SAFE_BACKFILL`；这是通道供给不足的透明记录，不是放松硬门控。

相对旧冻结 Final50，桥接 Final50 保留 21 个既有成员、纳入 27 个生成候选；这是新的**计算桥接组合**，不是对旧冻结 Final50 的覆盖或修改。

### V2 Top10（简写；完整序列和字段见 TSV）

|Top10|候选简写|来源|route|parent|QC397 几何序位|角色|
|---:|---|---|---|---|---:|---|
|1|P1MCPUFP__CPUFP500K_0288__00659|旧池|c2_four_seed|151H7|2|核心|
|2|NODE1GEN_112448|生成|rfantibody|RF P5|3|核心|
|3|NODE1GEN_229102|生成|fixed_pose_mpnn|fixed-pose MPNN|5|核心|
|4|P1MCPUFP__CPUFP500K_0188__00519|旧池|c2_four_seed|151H7|8|核心|
|5|P1MCPUFP__CPUFP500K_0100__00092|旧池|c2_four_seed|HR151|9|核心|
|6|NODE1GEN_181778|生成|fixed_pose_mpnn|fixed-pose MPNN|10|核心|
|7|NODE1GEN_154595|生成|fixed_pose_mpnn|fixed-pose MPNN|13|核心|
|8|NODE1GEN_127352|生成|rfantibody|RF P6|37|独立机制/亲本|
|9|NODE1GEN_002130|生成|rfantibody|RF P1|52|独立机制/亲本|
|10|NODE1GEN_128014|生成|rfantibody|RF P6|1|独立机制/亲本|

第 10 名的 shared-common4 序位虽为 1，但在 Top80/Final50 的多样性规则下作为独立 parent/mechanism 位点进入 Top10；因此 **Top10 不是纯全局分数前十**，而是“7 个核心 + 3 个独立补充”的旧组合规则。

## 输出位置与校验

### Node1 原始结果（V2，唯一应使用的桥接版本）

```text
/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/generated197_static_top80_final50_bridge_v2_20260726/
├── unified_qc397/
│   ├── unified_qc397_static_input.tsv                  # 397 条统一输入
│   ├── unified_qc397_static_metrics_794.tsv            # 794 pose 静态指标
│   ├── QC397_STATIC_COMPLETE.json
│   └── QC397_STATIC_BRIDGE_INPUT_RECEIPT.json
├── top80/
│   ├── top80_post_static.tsv
│   └── TOP80_COMPLETE.json
├── final50/
│   ├── final50_ranked.tsv
│   ├── top10_priority.tsv
│   └── FINAL50_PREAUDIT.json
└── BRIDGE_AUDIT.json
```

### 本地镜像

```text
机制/data/audits/PVRIG_QC397_static_Top80_Final50_bridge_20260726_v2/
```

关键文件 SHA-256：

```text
unified_qc397_static_input.tsv       f5c56c1030a1f9d2f85b309db85cab04ff2fa5ba1cde6fb275a2d20bd5063a80
unified_qc397_static_metrics_794.tsv d8d388400ff3c7c67b432951cff180e9b27466b50543493fbb086a87a6d67e92
Top80_post_static.tsv                496f83946e0249156d9773fc143a98354319eda0664852c484f0db25d80a24d7
Final50_ranked.tsv                   9ceb5734741a655e9c94c0b77aba293b054473718c9bd04787dfc6fa27590218
Top10_priority.tsv                   ab03cc5257964404fe14d9812a68071dfd7416174a41360813a1e4db7319fab5
```

`BRIDGE_AUDIT.json`、Top80/Final50 `SHA256SUMS` 均已通过校验。桥接 Final50 尚未运行 MD；MD 在本流程中仍是描述性证据，空 manifest 被明确记录为 `NOT_RUN_RESERVE`，未进入排序。
