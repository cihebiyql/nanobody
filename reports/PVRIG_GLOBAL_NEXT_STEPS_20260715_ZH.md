# PVRIG VHH 计算主线全局状态与下一步

**更新时间：** 2026-07-16 13:20 CST  
**第一轮截止：** 2026-07-26 18:00  
**本文范围：** 计算筛选、Docking、候选组合和提交释放；不把实验闭环作为当前关键路径。

## 1. 一句话决策

现在不缺序列，不缺工具，也不需要再生成一轮 8,000+ 基础库。当前应同时推进两条线：

1. **比赛主线：** 以 Teacher500 Full-QC 后的 290 条完整候选为主池，加上 Dual128 中已经真正双构象重对接的高证据候选，尽快形成 100-150 条 shortlist，再冻结 Top50 和多家族 Top10。
2. **研究旁线：** 按预注册协议完成 V4-D FullQC290 独立 8X6B/9E6Y 双构象 Docking 和连续几何教师，但不让 surrogate 训练和 sealed test 阻塞比赛交付。

P2/P3/P4 固定面板富集失败只意味着“不能根据 phase 标签生成下一批”，不禁止继续评价已经在结果解封前冻结的 290 条 Full-QC 候选。

## 2. 当前真实状态

### 2.1 设计库

    8,640 raw target-conditioned designs
    8,248 exact-unique designs
    7,087 fast-gate eligible designs
    40 parent framework clusters
    3 target patches: A_CENTER / B_LOWER / C_CROSS
    2 design modes: H3 / H1H3

设计数量和基础多样性已经足够。除非最终合规候选少于 50，否则不再重启大规模生成。

### 2.2 Teacher500 Full QC

已完成 Node23 主运行和 Node1 parity replicate：

    500 input
    327 fast hard-pass
    302 full-QC hard-pass
    25 full-QC hard-fail
    290 full-QC hard-pass + complete AbNatiV
    12 full-QC hard-pass but AbNatiV-unscorable review-only

Node23 与 Node1 在 327 条 full-QC 行上：

- candidate ID、行顺序和字段集合完全一致；
- hard-fail、official validator、recommendation、developability、expression/purity risk 和 final score 决策完全一致；
- 220 条 AbNatiV_VHH_score 存在浮点尾数差异，最大绝对差为 `1.583195473608967e-07`；chunk-local `rank` 和 `DEFERRED_*` cluster 标签因分块执行顺序不同，但 `cascade_full_rank` 和全部候选决策完全一致。

12 条 AbNatiV-unscorable 全部来自 parent PLDNANO_VHH_00220，原因是 ANARCI 对齐在 H85A 需要 75-residue insertion。它们保留为 review-only，不进入主要 exploitation 池。

### 2.3 Dual128 真正双构象重对接

    1050 jobs
    1049 SUCCESS / 1 FAILED_MAX_ATTEMPTS
    350/350 entity-conformations >= 2 successful seeds
    19,250 scored poses
    evaluator = PASS
    P2/P3/P4 enrichment = FAIL

候选级 robust_A 共 5 条：

| 候选 | Phase | 8X6B 支持 seeds | 9E6Y 支持 seeds | 当前 QC |
| --- | --- | ---: | ---: | --- |
| PVRIG_RFAb_v2_P2_qkg_L_bb007_mpn01 | P2 | 3 | 3 | REVIEW_DEVELOPABILITY |
| PVRIG_RFAb_v2_P4_ekg_L_bb007_mpn01 | P4 | 3 | 2 | REVIEW_DEVELOPABILITY |
| PVRIG_RFAb_v2_P6_ekg_L_bb005_mpn00 | P6 | 3 | 2 | REVIEW_DEVELOPABILITY |
| PVRIG_RFAb_v2_P4_ekg_L_bb005_mpn02 | P4 | 2 | 2 | REVIEW_DEVELOPABILITY |
| PVRIG_RFAb_v2_P4_qrg_L_bb003_mpn00 | P4 | 2 | 2 | REVIEW_DEVELOPABILITY |

其余支持分布：

    14 NEAR_DUAL_SUPPORT
    9 SINGLE_CONFORMATION_2PLUS
    17 SPARSE_SUPPORT
    83 NO_STRICT_A_SEED_SUPPORT

五条 robust-A 都应进入高证据复核池，但它们都有 developability 复核提示，不应因几何强就自动成为 Top5。

### 2.4 P2/P3/P4 富集的正确解释

| Phase | robust A | rate | RR vs P1/P5/P6 | Holm p | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| P2 | 1/21 | 0.0476 | 2.857 | 0.907 | 不可靠 |
| P3 | 0/24 | 0 | 0 | 1.000 | 不可靠 |
| P4 | 3/23 | 0.1304 | 7.826 | 0.188 | 有趋势，未过门禁 |
| P1/P5/P6 | 1/60 | 0.0167 | - | - | comparator |

不能用“P4 已富集”作为下一批生成策略。可以使用 3 条 P4 robust-A 的个体证据，但不能将其上升为 phase 级规律。

### 2.5 V4-D FullQC290 状态

V4-D 已在任何新双构象标签出现前冻结：

    290 candidates
    226 OPEN_TRAIN
    32 OPEN_DEVELOPMENT
    32 PROSPECTIVE_COMPUTATIONAL_TEST
    47 protocol-regression controls
    2022 total jobs = 337 entities x 2 receptors x 3 seeds

V4-D 已在零结果状态下完成 Decimal 修订和重冻结：core/candidate/split/monomer/job manifest 哈希均未改变，runtime `34/34` 测试通过，4-job smoke `4/4 PASS`。2026-07-16 11:26 全量控制器在 node23 启动；13:18 的实测快照为 `202 SUCCESS / 12 RUNNING / 1808 PENDING / 0 FAILED`。Node23 open-teacher watcher 为 `WAITING_V4D`，只有 fresh evaluator PASS 后才释放 open258；test32 保持 sealed。

新 evaluator gate 为 `pvrig_v4_d_evaluator_stability_v3_decimal_thresholds`。修订、前后归档和哈希证据见 `data/experiments/phase2_5080_v1/reports/PVRIG_V4_D_DECIMAL_PROTOCOL_CORRECTION_20260716_ZH.md`。

### 2.6 候选交付状态

当前仍然没有：

- 冻结的 submission_top50.fasta；
- 冻结的 submission_top50_ranked.csv；
- Top10 多家族组合；
- Top10 人工 pose verdict；
- 官方模板和一页方案；
- clean replay 与 SHA256 收据。

项目状态应表述为：

    PIPELINE_READY
    DESIGN_POOL_READY
    FULL_QC_PRIMARY_POOL_READY
    DUAL_DOCKING_EVALUATOR_READY
    FINAL_SUBMISSION_PORTFOLIO_NOT_FROZEN

### 2.7 自动后处理与验证状态

本地和远端续跑已固定，不再依赖手工逐步触发：

- Node23 open-teacher watcher：`WAITING_V4D`；
- Node1 Deep-QC delivery watcher：`WAITING_DEEPQC`；
- Node1 IgFold-vs-NBB2 watcher：`WAITING_DEEPQC`；
- 本地 tmux 总控：`pvrig-v4d-deepqc-postprocess`，状态 `RUNNING`。

总控将先验证 archive/receipt/manifest/SHA256，再执行 partial Deep-QC merge、final open258 geometry merge、Top50 排名和真实 Top20 `20 x 6 x 3 = 360` pose bundle。第二轮代码审查已关闭全部 HIGH/MEDIUM；组合验证为 `42 PASS + 1 optional remote skipped`，真实 raw/aggregate closure smoke 与真实 Node23 pose parser smoke 均通过。

## 3. 全局执行顺序

## P0 - 立即修复治理和启动边界

### P0.1 为 V4-D 做标签前 Decimal 修正

执行状态：`COMPLETE`。

必须在 status/jobs 和 results 仍为空时完成：

1. 归档 V4-D 当前 PROTOCOL_LOCK、aggregate_results、门禁配置和 preregistration；
2. 移植已验证的 Decimal(str(value)) × Decimal(str(scale)) 阈值缩放；
3. 加入 CDR3 occlusion=110 通过且 109.999999999 不通过的回归测试；
4. 升级 V4-D evaluator gate ID 和 preregistration correction record；
5. 保持 V4-D core candidate/split/monomer/job manifest 不变，仅重冻结 final/postprocessing lock；
6. 更新 watcher 中的 preregistration 和 final-lock 哈希。

退出条件：

    core hash unchanged
    candidate/split/monomer/job hashes unchanged
    new final lock PASS
    all tests PASS
    status/jobs empty
    results empty

### P0.2 固化 Teacher500 Full-QC parity 审计

执行状态：`COMPLETE`。规范化 receipt 为 `PASS_NORMALIZED_DECISION_PARITY`。

写入独立审计 JSON/Markdown，明确：

- Node1/Node23 327 条决策完全一致；
- 220 条 AbNatiV 差异在 `1e-6` 冻结容差内，最大绝对差为 `1.583195473608967e-07`；
- V4-D 继续使用已在结果前冻结的 Node23 complete290 哈希，不根据后续 Docking 更换候选。

### P0.3 记录 V4-C 远程失败，不让它阻塞比赛

执行状态：`COMPLETE`。初始 config-hash mismatch 已 fail-closed 并经 target embedding `max/mean delta = 0` 恢复；V4-C 的 broad-use/enrichment 失败边界保持不变。

Node1 pvrig_v4c_generic_prior_20260715 因 embedding config 与 frozen checkpoint 不同而退出。但本地已有哈希绑定的 dual128_generic_prior.csv，Teacher500 manifest 也已含三个 seed 的 generic prior。

因此：

- 将远程失败写入审计；
- 不为比赛重跑它；
- generic prior 只作弱先验/tie-breaker，不作主硬门。

## P1 - 启动 V4-D FullQC290 双构象 Docking

执行状态：`RUNNING`。4-job smoke 已通过，全量 2022-job 控制器已启动；13:18 快照为 `202 SUCCESS / 12 RUNNING / 1808 PENDING / 0 FAILED`。

P0 通过后，在 node23 使用本地 scratch 执行：

    2022 jobs
    12 concurrent jobs
    4 logical CPUs/job
    48/64 logical CPUs target
    about 10-12 GiB active RAM
    about 45-50 GiB final storage budget
    about 15-18 hours expected wall time
    GPU not required for HADDOCK3

执行顺序：

    protocol validation
    -> fixed smoke
    -> smoke evidence validation
    -> full 2022-job queue
    -> fresh aggregation
    -> evaluator stability
    -> continuous geometry teacher build

主要输出是连续值，而不是单一 A/B/C/E 类别：

- R_8X6B；
- R_9E6Y；
- R_dual_mean；
- R_dual_min；
- R_dual_gap；
- receptor/seed 标准差；
- native/cross agreement；
- model-pair consensus；
- hotspot、holdout、occlusion、CDR3 contribution、clash 和 pose-support 摘要。

暂停或回退条件：

- smoke 失败：不进入 full queue；
- 协议/hash 漂移：停止并重做预检；
- node23 负载升高：并发自适应降到 8/6/4，不在 NFS 上直接运行 CNS；
- 7/18 仍未完成：比赛主线不等待 surrogate 训练，使用 Full-QC + Teacher 旧 pose + Dual128 高证据候选先行冻结 portfolio。

## P2 - 建立统一候选证据表

执行状态：`PENDING_MASTER_V2_SCHEMA_COMPLETE`。当前 v2 master 含 418 条唯一候选、418 个唯一序列哈希：290 条 FullQC 主池和 128 条 Dual128 辅助池；32 条 prospective test 已显式 sealed。V4-D open258 连续几何与 Top100 Deep-QC 字段分别等待各自 terminal delivery 后回填。

在 V4-D 运行的同时建表，不等 Docking 结束后才开始。

建议产物：

    candidate_evidence_master.tsv
    candidate_evidence_schema.json
    candidate_evidence_lineage_audit.json

每条候选必须分轴保存：

1. identity/lineage：candidate ID、sequence SHA256、parent/scaffold、patch、mode、backbone、MPNN index、CDR before/after；
2. hard QC：official validator、ANARCI/IMGT、known-positive CDR identity、liability、AbNatiV completeness；
3. developability：AbNatiV、Sapiens、GRAVY、pI、instability、hydrophobic run、expression/purity risk；
4. binding/contact weak prior：generic prior、contact/paratope/epitope 特征，明确标记为弱先验；
5. structure：NBB2 序列一致性、主链 QC、CDR3 构象交叉检查；
6. geometry：两个 receptor、3 seeds、top-k 连续量、一致性和不确定性；
7. diversity：full-sequence cluster、CDR3 cluster、parent cluster、patch、angle family；
8. claim boundary：不输出 binder probability、Kd 或 experimental blocker 标签。

Dual128 与 FullQC290 序列交集为 0，可作为两条独立候选来源。但 Dual128 要进入最终提交池，必须先补齐与 Teacher290 同一 schema 的 full-QC 和完整设计 lineage，不能只凭对接标签合并。

## P3 - 形成 100-150 条 portfolio shortlist

执行状态：`PRE_SHORTLIST100_COMPLETE_GEOMETRY_PENDING`。已冻结 82 exploitation + 18 exploration 的 100 条预 shortlist；Dual128 因尚缺同等 Full-QC/lineage 未直接并入。

建议两层入池：

### P3.1 Exploitation 80%-85%

- Full-QC hard-pass；
- AbNatiV 完整；
- developability 和 expression/purity risk 不处于明显尾部；
- generic binding/contact 弱先验不相互矛盾；
- 双 receptor 连续几何、seed 稳定性和 top-k 支持较好。

### P3.2 Exploration 15%-20%

- Full-QC 仍然良好；
- 但模型低分、几何不确定或与主趋势不同；
- parent、patch、mode、CDR3 或 angle family 可以补齐组合多样性。

硬性组合上限：

- 每个 parent 最多 3-4 条；
- 每个 parent + patch + mode 最多 1-2 条；
- 三个 patch 各保留约 25%-40%；
- H3 和 H1H3 都必须保留；
- 近 CDR3 家族不允许通过评分累积占据 shortlist；
- 已知阳性、专利序列和 calibration mutants 完全排除。

候选筛选不应被 V4-D surrogate 研究阻塞。可以先用真实 Docking 连续量筛 shortlist，再用 surrogate 作旁路验证。

## P4 - Top100 补充检查和 Top20 深度复核

执行状态：`TOP100_DEEP_QC_FULL_TNP_RUNNING_ON_NODE1`。单条 TNP 与 IgFold smoke 均已通过；当前 8 个 TNP chunks x 4 CPU 正在运行，随后才启动 4 个 IgFold GPU chunks，不与 Node23 HADDOCK 竞争资源。Deep-QC delivery watcher 和 IgFold-vs-NBB2 structure watcher 均为 `WAITING_DEEPQC`。

### Top100

- 运行 TNP 作可开发性注释，不作阻断硬门；
- 对 NBB2 单体做 CDR3/overall fold 交叉检查；
- 检查氧化、脱酰胺、异构化、糖基化、多 Cys、连续疏水和极端电荷；
- 计算 parent/CDR3/full-sequence 三层 diversity。

### Top20

人工逐条检查：

- 双 receptor pose 是否真正覆盖 PVRIG-PVRL2 界面；
- 遮挡是否主要由 CDR 而非 framework 假接触造成；
- PVRIG-VHH 实体 clash 和错误接触角；
- best pose 是否与 top-k median 差距过大；
- 8X6B/9E6Y 是否只有单受体支持；
- 三个 seed 是否聚集到相似 angle/epitope；
- 可开发性风险是否与几何收益相称。

人工 verdict 固定为：

    ACCEPT_COMPUTATIONAL_PRIORITY
    ACCEPT_DIVERSITY_HEDGE
    REVIEW_SINGLE_RECEPTOR
    REVIEW_DEVELOPABILITY
    REJECT_IMPLAUSIBLE_POSE

## P5 - Pareto 组合与 Top50/Top10 冻结

先做 hard gate，再做 Pareto front，最后才在层内给 operational score。

| 证据轴 | 建议权重 | 边界 |
| --- | ---: | --- |
| binding/contact weak evidence | 40% | 相对先验，不是结合概率 |
| expression/purity/developability | 25% | 序列/QC 代理指标 |
| independent dual-receptor geometry | 20% | 优先连续量和稳定性 |
| monomer structure confidence | 10% | 检查 CDR3 和整体折叠 |
| novelty | 5% | 已知阳性泄漏为硬排除 |

这是 operational score，不是概率。多样性是硬约束，不放进 5% 加分项。

Top10 最低组合条件：

- 至少 5 个 CDR3/full-sequence clusters；
- 至少 4 个 parent/scaffold/angle families；
- 同一近邻家族最多 2 条；
- A_CENTER、B_LOWER、C_CROSS 都有代表；
- 至少 2 条强 expression/purity/developability 对冲候选；
- 至少 2 条 alternative-angle 候选；
- 最多 1 条 high-risk/high-reward exploration；
- Dual128 robust-A 只有补齐同等 full-QC/lineage 后才可进入 Top10。

## P6 - 提交包和独立重放

必须生成：

    submission_top50.fasta
    submission_top50_ranked.csv
    submission_top50_lineage.csv
    submission_top50_evidence.tsv
    submission_top10_dossier/
    submission_method_one_page.pdf
    SOURCE_AND_MODEL_PROVENANCE.md
    SHA256SUMS
    clean_replay.sh
    clean_replay_receipt.json

冻结门禁：

1. 正好 50 条，ID、序列、顺序和 SHA256 唯一；
2. 50/50 official validator、ANARCI/IMGT、known-positive CDR novelty 和 full hard gate 通过；
3. 50/50 有完整 design lineage；
4. 阳性、专利序列和 calibration mutants 与提交集完全隔离；
5. 50/50 有 developability/expression/purity 风险摘要；
6. Top10 有单体、candidate-specific 双 receptor pose、连续几何和人工 verdict；
7. Top10 满足多家族约束；
8. 排序表分开 binding、geometry、structure、developability、expression/purity 和 diversity；
9. 官方模板和一页方案完成；
10. 干净目录重放后数量、顺序和 SHA256 完全一致。

## 4. V4-D surrogate 研究旁线

这条线不是比赛 Top50 的前置条件。

### Open development

- OPEN_TRAIN 226 条拟合；
- OPEN_DEVELOPMENT 32 条做所有模型/特征/超参选择；
- 强制比较 constant、parent-only、design-metadata、CDR3-only、handcrafted sequence 和 generic-prior baselines；
- 主指标是 R_dual_min Spearman；
- 对最强 shortcut 的 open-development delta 至少 0.10；
- 筛除最高不确定性 25% 后 MAE 至少下降 10%。

### Prospective computational test

32 条 test 在以下文件冻结前保持 sealed：

- preregistration hash；
- split/teacher/feature hashes；
- 模型配置和 checkpoint hashes；
- open-development summary；
- 冻结 32 行 prediction hash；
- one-shot evaluator hash。

主 test 门禁：

- overall Spearman delta over strongest shortcut >= 0.05；
- 3 个 held-out parent clusters 中至少 2 个 delta 非负。

失败就关闭 V4-D 当前版本，不用 test 结果回改阈值、特征、split 或架构。

## 5. 时间表

| 时间 | 主任务 | 退出条件 |
| --- | --- | --- |
| 7/15 晚-7/16 | V4-D Decimal 修正、Full-QC parity 审计、重锁并启动 | smoke PASS，full queue 开始 |
| 7/16-7/17 | V4-D 2022 jobs；并行建 evidence master | Docking terminal，连续 teacher 完成 |
| 7/17-7/18 | 100-150 shortlist；Top100 TNP/单体交叉检查 | 配额、exploration 和 lineage 闭包 |
| 7/18-7/20 | Top20 人工 pose 复核；Pareto 排序 | Top50/Top10 草案 |
| 7/20-7/22 | 冻结 Top50/Top10；编写提交材料 | SUBMISSION_CANDIDATE_RELEASE |
| 7/22-7/24 | clean replay、格式、数量、顺序和 SHA 审计 | 重放收据 PASS |
| 7/25 | 缓冲日，只修复发布/格式问题 | 不改候选科学规则 |
| 7/26 | 上传、平台校验和回执 | 18:00 前完成，内部目标 16:00 |

## 6. 当前明确不做

1. 不因 P4 有趋势就宣称 P4 已富集；
2. 不绕过 P2_P3_P4_ENRICHMENT=FAIL 生成下一批 phase-conditioned 序列；
3. 不将 V3-P1 部署为主排序模型；
4. 不将 V1.3 或 V4-D 连续几何称为 Docking Gold 或 biological label；
5. 不在已解封数据上放宽门禁、挑阈值或反复调参；
6. 不让 V4-D surrogate 训练、test unseal 或大模型迭代阻塞 Top50/Top10；
7. 不重新生成 8,000+ 基础库，除非最终合规集少于 50；
8. 不用单一 HADDOCK 分数、单一 rank-1 pose 或单受体 A 类决定最终排名。

## 7. 结束标准

当前计算主线只在以下状态下结束：

    COMPUTATIONAL_EVALUATOR_STABLE
    FULL_QC_PRIMARY_POOL_FROZEN
    PORTFOLIO_TOP50_FROZEN
    TOP10_DIVERSE_EVIDENCE_COMPLETE
    SUBMISSION_PACKAGE_REPLAY_PASS

这些状态支持的是“可追溯计算优先级提交集”，不是实验结合、Kd 或功能阻断证明。

## 8. 权威证据路径

- 全局进度：PROJECT_PROGRESS.md
- 当前 V4-D/Deep-QC 后处理执行记录：data/experiments/phase2_5080_v1/reports/PVRIG_V4D_DEEPQC_POSTPROCESS_EXECUTION_20260716_ZH.md
- 比赛回顾：data/experiments/phase2_5080_v1/reports/PVRIG_COMPETITION_TRAINING_TEST_RETROSPECTIVE_AND_NEXT_STEPS_ZH.md
- Teacher500 lineage：data/experiments/phase2_5080_v1/data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv
- Full-QC290：data/experiments/phase2_5080_v1/runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/teacher500_full_qc_complete290_lineage.csv
- Full-QC 完整性审计：data/experiments/phase2_5080_v1/runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/teacher500_full_qc_node23_integrity_audit.json
- V4-D 预注册：/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715/governance/phase2_v4_d_preregistration.json
- Dual128 终态：pvrig_v3_dual_conformation_redocking_20260714/RUN_STATUS.md
- Dual128 robust/near 表：pvrig_v3_dual_conformation_redocking_20260714/reports/dual128_candidate_support_summary.tsv
- 数值修正审计：pvrig_v3_dual_conformation_redocking_20260714/reports/EVALUATOR_NUMERIC_CORRECTION_20260715_ZH.md
- Docking 资源实测：pvrig_v3_dual_conformation_redocking_20260714/reports/DOCKING_RESOURCE_TIME_BENCHMARK_ZH.md
