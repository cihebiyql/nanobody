# PVRIG 两版 Top7500 到最终 50 条执行计划

筛选指标、分层门控、证据优先级和最终组合规则的完整说明见：

- [`TOP7500_TO_FINAL50_SCREENING_METHOD_ZH.md`](TOP7500_TO_FINAL50_SCREENING_METHOD_ZH.md)

更新时间：2026-07-24  
运行根目录：`/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724`

## 1. 目标与固定范围

- 旧版 Top7500：7,500 条；
- C2-refined Top7500：7,500 条；
- 重叠：1,280 条；
- 严格并集：13,720 条；
- 不纳入先前误提的 Top5000；
- 不重复全量 docking，优先复用已经完成的 66,760 个 docking jobs；
- 最终依次冻结：Top200 静态复核池、Top80 精细池、最终50、Top10 优先级。

所有计算结论保持证据边界：binding prior、docking geometry、静态能量和
MD 均不是实验 BLI、Kd、IC50、表达量或纯度。

## 2. 资源上限

Node1 当前 64 CPU、8 GPU。经用户授权，本流程最多使用：

- CPU：32 logical CPUs；
- GPU：4 张；
- 当前 docking 证据后处理约使用 20 个 CPU worker/thread，不占 GPU；
- 后续完整 QC 默认 16–24 CPU；
- Rosetta/PRODIGY/FoldX 以 CPU 为主；
- MD 最多并行 4 GPU，每个任务固定 GPU、独立目录和随机种子。

禁止为了追求吞吐覆盖现有结果、重复启动同一批任务或超过上述资源上限。

## 3. 每 30 分钟监控合同

实时状态：`STATUS.json`。  
30 分钟快照：`monitor_30min/history/STATUS_*.json`。  
历史表：`monitor_30min/MONITOR_HISTORY.tsv`。

每次监控必须记录：

- PID/tmux 存活；
- 近似 manifest 进度；
- 结果 TSV、receipt 和 SHA256；
- stderr 大小；
- CPU/GPU 使用量；
- `/data`、`/data1` 剩余空间；
- Top200、Top80、最终50产物状态。

技术失败一律记为 `TECHNICAL_NA`，不能当作不结合或不阻断。

## 4. 执行阶段

### S0：输入和 lineage 冻结（已完成）

- 冻结 13,720 条候选、序列 SHA256、面板归属、parent 和来源；
- 校验 old/C2 各 7,500、重叠 1,280、并集 13,720；
- 权威输入：`inputs/TOP7500_UNION_13720_MEMBERSHIP.tsv`。

### S1：全量快速序列门控（已完成）

- 标准氨基酸、ANARCI/IMGT、CDR 完整性；
- 对阳性库 CDR identity；
- 基础 VHH/可开发性风险；
- 当前 13,720 条中 13,719 条 fast hard-pass，1 条 hard fail；
- 官方 validator 和完整 AbNatiV/Sapiens/TNP 留给完整 QC。

### S2：既有 docking 证据统一（运行中）

- C2：直接读取压缩包内完整 `pose_scores`；
- 旧版：读取冻结 selected models 补算几何字段，不重新 docking；
- 输出统一 job-level schema：seed、构象、native/cross、热点、PVRL2/CDR3
  遮挡、clash、overlay RMSD、HADDOCK/AIR、模型一致性。
- strict job 的冻结定义是“该 job 的 selected-model panel 中至少一个 pose
  对两套 reference-overlay 均为 A”，不是“最低 HADDOCK score 的单个
  representative pose 必须为 A”。后者会把 6,042 条错误缩成 963 条；
  代表 pose 仍保留用于静态复核，但不能替代 any-pose mechanism gate。

完成判据：

- C2：41,760 行；预期 41,735 success、25 technical NA；
- 旧版：25,000 行；预期 24,985 success、15 technical NA；
- receipt、行数、job hash 和协议 hash 全部闭合。

### S3：候选级证据表和完整 QC

将 66,760 job 聚合到 13,720 条候选，生成：

- `candidate_evidence_table.tsv`；
- `funnel_counts.tsv`；
- `hard_gate_failures.tsv`；
- `core_and_rescue_pool.tsv`；
- `pairwise_diversity_clusters.tsv`。

硬门控：

1. ID、序列和 hash 完整；
2. official `ab-data-validator` PASS；
3. ANARCI/IMGT、FR/CDR 完整；
4. 对任一阳性对应 CDR identity `<0.80`，内部优先 `<=0.75`；
5. 可开发性按阳性校准分层处理：未解释奇数 Cys、多项正交严重风险、
   序列/结构不一致为 hard/manual-review；TNP 单项 red、AbNatiV/Sapiens
   中等、单个 hydrophobic 5-mer、pI/PTM proxy 为 warn/rank，不能单项
   宣判不是 blocker；
6. docking 必须具备规定的双构象、多 seed、双参考证据；
7. 缺失 binding evidence 不填中性分，保持 `NEEDS_BINDING_EVIDENCE`。

为提高末端筛选精度，本轮 Top200 主池从冻结的 6,042 条 strict-A 多 seed
候选中产生；这是一项保守的生产优先级策略，不表示其余 A/B 支持候选是
生物学阴性。阳性校准显示 strict-A 召回不足，因此在后续模型迭代中保留
A/B rescue 通道，不能把 strict-A 写成通用 blocker 真值。

独立 evidence lanes：

- binding：`binding_consensus_weak_prior`、DeepNano/NanoBind；
- blocking：strict-A/support-AB、双构象、seed 一致性、热点和遮挡；
- developability/expression/purity：仅作计算 proxy；
- structure/static/MD：只作复核，不替代 binding/blocking。

批处理实现约束：

- 官方 validator 使用 24 个候选级 worker；MUSCLE 固定为单线程，避免
  `worker × 机器核数` 的线程过度订阅；
- 完整 QC 中的 TNP/NanoBodyBuilder2 使用项目内隔离的可恢复调度器：
  最多 24 条候选并发、每条 `--ncores 1`，有效 JSON 结果写入独立
  `tnp_cache` 并按候选复用；GPU 固定在授权的 `0,1,2,4` 上轮转，
  避免所有 NanoBodyBuilder2 进程挤占 GPU0；
- Top200 控制器将自身及全部子进程固定到 CPU `0-31`，因此无论底层
  PyTorch/BLAS 创建多少线程，实际计算都不会超过半台 Node1；
- 2,000 条完整 QC 只计算对阳性参照的 CDR 新颖性；约 200 万候选对的
  全量团队内 MUSCLE 比较在此阶段显式 defer，避免约 600 万次子进程
  对齐。候选间多样性由 Top200/Top80/Final50 的 CDR3 聚类、parent、
  route 和 exact-duplicate 配额门控；最终50再执行完整两两复核；
- 任何优化前的未完成目录先移入 `run/archive/`，正式结果只在完整
  receipt 产生后提交，不用半成品覆盖正式输出。

### S4：Top200 静态复核池

组合预算：

- CORE_A exploitation：120；
- parent/CDR3/route diversity：40；
- model-disagreement rescue：20；
- structural reserve：20。

必须满足 hard gates，并执行 parent、route、exact sequence 和 CDR3 近重复约束。
CDR3 多样性门控使用候选间**直接两两 identity**：同长度 CDR3
`identity >= 0.80` 不得同时进入 Top200，精确 CDR3 重复为0。单链连接
分量仅用于报告，不再设置小簇配额；否则通过相似性链条会把彼此并不近似
的序列传递合并成巨型簇并造成错误淘汰。
静态字段至少包括：

- buried SASA、接触密度；
- 氢键、盐桥；
- clash atom/residue penalty；
- shape complementarity；
- buried unsatisfied polar；
- surface hydrophobic patch/SAP；
- PTM 位点结构暴露；
- CDR/framework 接触贡献；
- PRODIGY、FoldX、Rosetta 状态和校准标签。

实际执行固定为每条候选抽取一个 8X6B pose 和一个 9E6Y pose，共 400 个
静态作业。当前阳性/扰动控制校准结论：

- Rosetta InterfaceAnalyzer：`DESCRIPTIVE_ONLY`；
- PRODIGY：`WEAK_PRIOR_ONLY`；
- FoldX 跨候选绝对排序：校准拒绝，本轮标为
  `NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED`；
- 自有原子级界面审计：接触密度、2 Å 物理 clash proxy、氢键/盐桥距离
  proxy、CDR/framework 接触贡献、疏水和 PTM 暴露 proxy。

未通过阳性/控制校准的软件只输出诊断字段，`static_rank_contribution=0`，
不作为 hard cutoff，也不覆盖 binding/blocking 两条主证据。

### S5：Top80 精细池

- 对 Top200 完成 pose 审计、静态能量和证据完整性检查；
- 优先淘汰高 clash、低接触密度、框架异常主导、跨 seed/构象不稳定项；
- 保留 CORE、diversity、disagreement 和 reserve 通道；
- 继续执行直接两两 CDR3 identity `<0.80` 和零精确 CDR3 重复；单链簇
  仅报告，不作为小配额硬门控；
- 输出 `top80_post_static.tsv` 与逐条选择/排除原因。

### S6：MD 与最终50

- 本轮固定对 Top80 中 20 条运行 matched-pose 短 MD；
- 每条使用同一个冻结 8X6B 起始 pose、3 个速度 seed，共 60 条 2 ns 轨迹；
- 固定使用物理 GPU `0,1,2,4`，每卡 4 个独立 trajectory slot、每条
  `2 OMP threads`，合计最多 16 条轨迹和 32 CPU threads 并发；每条轨迹
  独立目录、随机 seed 和 checkpoint，控制器重启必须用 `prod.cpt -append`
  续跑，不能覆盖已有结果；
- 指标：interface RMSD、CDR3 RMSF、热点接触占有率、PVRL2 遮挡保持率、
  氢键/盐桥保持率；MM/GBSA 仅在环境和阳性校准通过后使用；
- 未运行 MD 的 reserve 保持 `NOT_RUN`，不能填 0。

阳性/破坏性控制的四家族校准结论为 `MD_DESCRIPTIVE_ONLY`，所以本轮 MD
只检查 pose persistence。二元 PVRIG–VHH MD 不能直接观察 PVRL2，
`pvrl2_occlusion_retention_status` 必须明确记录为
`NOT_DIRECTLY_OBSERVABLE_IN_BINARY_MD`，不得伪造成遮挡保持率。

最终50约束：

- exact sequence duplicate = 0；
- exact CDR3 每条最多1；
- 任意两条同长度 CDR3 直接 identity `<0.80`；单链连接分量仅报告；
- 单一 parent 最多15；
- 单一路线最多35；
- 条件允许时至少4个 parent clusters；
- Top10：7条最高置信 + 3条独立 parent/机制；单一 parent 最多4，单一路线最多7。

最终50的完整QC复用同一持久 TNP cache，MUSCLE固定单线程，并继续把控制器
和全部子进程限制在CPU `0-31`；最终50规模允许执行完整团队内两两复核，
不再使用2,000池的defer策略。

## 5. 完成判据

只有以下产物全部存在、行数和 hash 验证通过，目标才完成：

- `top200_pre_static.tsv`：200条；
- `top80_post_static.tsv`：80条；
- `md_manifest.tsv`；
- `final50_ranked.tsv`：50条；
- `top10_priority.tsv`：10条；
- `FINAL50_COMPLETE.json`；
- `SHA256SUMS`；
- 每条候选完整 provenance、hard-gate、evidence status、selection channel。

可选静态软件或 MD 不可用时，不伪造结果；以 `NOT_RUN/TECHNICAL_NA` 保留，
但 official validator、序列/hash、必需 docking 证据缺失时不得冻结最终50。

## 6. 已部署自动执行器

- `continue_to_top200.py`：等待 66,760 job 收据闭合，生成候选证据、完整
  QC 2,000 和 Top200；
- `continue_top200_to_top80.py`：冻结 400 个既有 pose，运行静态复核并
  生成 Top80；
- `continue_top80_to_final50.py`：运行 MD20、生成最终50/Top10、重新执行
  official validator 并写入最终审计收据；
- `monitor_top7500_screen.py`：每分钟更新 live status，每 30 分钟写入不可
  覆盖历史快照。

三个控制器均使用文件锁、完成收据和输入 hash，已有 COMPLETE 不覆盖，
任何计数/hash/协议回归直接停止后续阶段。

## 7. 生产执行结果（2026-07-25）

本轮计划已完整执行并通过独立完成审计：

- Full QC：2,000/2,000；
- Top200：200条，静态复核400/400 jobs；
- Top80：80条；
- MD：20条候选、3 seeds、60/60条2 ns轨迹，失败0；
- MD分析：60条 trajectory metrics、20条 candidate summaries；
- Final50：50条，官方 validator 50/50通过，similarity filter 50/50通过，
  hard fail 0；
- Top10：10条，其中7条 `HIGHEST_CONFIDENCE_CORE`、3条
  `INDEPENDENT_PARENT_OR_MECHANISM`；
- Final50 exact sequence duplicate 0、exact CDR3 duplicate 0、同长度CDR3
  最大直接 identity `0.7894736842`、5个 parent clusters、单一parent最大15、
  单一路线最大28；
- 新鲜单元测试：15/15通过；
- 完成审计：29/29 checks通过、失败0。

关键产物：

- `run/final50/final50_ranked.tsv`
  SHA256 `dca87287e4cc7d4a777122182fb435399427ffa34b2f34cf1243d190525df2e6`
- `run/final50/top10_priority.tsv`
  SHA256 `40d58611ff82f396e10643e7e4d590193648d6712bef183be5fb57e1aca60ea6`
- `run/final50/FINAL50_COMPLETE.json`
  SHA256 `fb6c667c387081c497e1192528e5c5230eace8dab6aab4ad1350f47a24b5f52d`
- `run/final50/GOAL_COMPLETION_AUDIT.json`
  SHA256 `6f72b08248299922328c0d6469147a364f7df7870e88effe4bd5ddc981d70dcc`

这些结果是经过审计的**计算筛选优先级组合**，不是实验 BLI、Kd、IC50、
表达量、纯度或阻断活性的替代结论。
