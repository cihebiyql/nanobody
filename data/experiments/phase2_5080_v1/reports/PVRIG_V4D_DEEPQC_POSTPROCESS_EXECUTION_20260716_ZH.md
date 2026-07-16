# PVRIG V4-D、Top100 Deep-QC 与候选回填执行记录

**更新时间：** 2026-07-16 13:20 CST  
**范围：** V4-D FullQC290 双构象 Docking、Top100 TNP/IgFold、开放集连续几何、候选证据回填、Top50/Top20 计算复核包。  
**声明边界：** 本流程输出计算几何优先级、单体结构一致性和序列/QC 注释；不输出真实结合概率、Kd、竞争实验或功能阻断结论。

## 1. 当前执行状态

### 1.1 Node23：V4-D FullQC290

- 远端项目：`/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715`
- 固定规模：290 candidates + 47 controls，2 个 PVRIG 构象，3 个 seeds，共 2022 jobs。
- 并发合同：12 个 HADDOCK3 jobs，约占 48/64 logical CPUs；不需要 GPU。
- Decimal 阈值修正后的 runtime 测试为 `34/34 PASS`，4-job smoke 为 `4/4 PASS`。
- 2026-07-16 13:18 快照：`202 SUCCESS / 12 RUNNING / 1808 PENDING / 0 FAILED`；controller PID `265751`，load1 约 `41.42`。
- 全量 controller 与 orchestrator 均存活；full queue 终态后自动运行 fresh aggregate 和 evaluator，未到终态前不释放 open teacher。

### 1.2 Node1：Top100 Deep-QC

- 远端项目：`/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716`
- 输入：冻结的 100 条 pre-shortlist；其中 88 条属于开放集，12 条属于 prospective test。TNP/IgFold 是 label-free QC，不读取 V4-D Docking 标签，也不参与 open258 主排序。
- 单条 TNP smoke 和单条 IgFold smoke 均已通过。
- 当前阶段：`FULL_TNP`；8 个 TNP chunks 并行，每 chunk 4 CPU，runner PID `1299503`。
- 8 个 chunk 均已产生 numbering、VHH evaluation 和 layer1 FASTA 中间文件；TNP summary 尚未 terminal，因此 IgFold 全量 4-GPU 阶段尚未开始。
- `/data` 环境存在 NFS import 等待；当前按产物和进程状态继续观察，不把低 CPU 瞬时占用直接判为失败。

## 2. 已固定的后处理工具

### 2.1 V4-D open teacher

脚本：`src/prepare_phase2_v4_d_open_teacher.py`

关键合同：

- 固定绑定 2022-job manifest、V4-D protocol core/lock、Decimal stability spec 和 FullQC290 split 哈希；
- 只释放 `OPEN_TRAIN=226` 和 `OPEN_DEVELOPMENT=32`，总计 258 行；
- `PROSPECTIVE_COMPUTATIONAL_TEST=32` 的 raw `job_result.json` 打开数固定为 0；
- 全量 evaluator-bound `job_results.tsv` 和 `pose_scores.tsv` 会被流式扫描，但只保留预先选定的 open job IDs，用于证明 raw pose 与聚合表逐行闭合；test32 行不进入 teacher；
- 连续量包括 `R_8X6B`、`R_9E6Y`、`R_dual_mean`、`R_dual_min`、`R_dual_gap`、seed SD、native/cross agreement 和 model-pair consensus。

真实生产闭环 smoke 已重新运行：1 个实际 `OPEN_TRAIN` job、9 个模型、18 条 2x2 pose rows，raw 与生产 `aggregate_results.py` 生成的聚合行一致。收据：

- `audits/pvrig_v4_d_open_teacher_builder_smoke_v1/raw_aggregate_closure_smoke_receipt.json`
- 状态：`PASS_PRODUCTION_RAW_AGGREGATE_CLOSURE_SMOKE`

### 2.2 Candidate evidence master v2

脚本：`src/merge_pvrig_candidate_evidence_v2.py`

当前 pending 版位于 `prepared/pvrig_candidate_evidence_master_v2/`：

- 418 行；
- 418 个唯一 candidate IDs；
- 418 个唯一 sequence hashes；
- 32 条 prospective test 保持 sealed；
- open geometry 当前 0 行，等待 V4-D terminal；
- Deep-QC 当前 0 行，等待 Node1 terminal delivery。

正式合并时将回填 258 条 open teacher、100 条 TNP/IgFold 和 100 条 IgFold-vs-NBB2 结果；不会把这些字段解释为真实 binding/blocking evidence。

### 2.3 IgFold-vs-NBB2 交叉检查

脚本：`src/audit_pre_shortlist100_igfold_nbb2.py`

严格门禁：

- NBB2 文件 SHA256 必须与冻结 manifest 一致；
- candidate sequence SHA256 必须与 manifest 一致；
- 从 NBB2 PDB 重建的蛋白序列必须与候选序列完全一致；
- terminal 模式下缺任一 IgFold/NBB2 PDB、哈希或候选闭包即失败；
- 输出 framework CA RMSD、CDR3 anchor delta 和 coverage。

这只是单体结构一致性检查，不评价 PVRIG 复合物姿势。

### 2.4 Open258 geometry shortlist

脚本：`src/build_pvrig_geometry_shortlist.py`

排序边界：

- 只接受 258 条 open FullQC290；32 条 test 和 128 条 Dual128 全部排除；
- `R_dual_min` 权重 `0.70`，是主要计算几何证据；generic prior 权重 `0.02`，只是弱先验；
- 惩罚 `R_dual_gap`、seed uncertainty 和 geometry uncertainty；
- TNP/IgFold 只作 annotation，不进入主排序，避免 88/258 覆盖偏差；
- 相同 metric 使用 mid-rank percentile，不按 candidate ID 人为拆分并列值；
- Top50 强制 `parent <= 3`、`parent+patch+mode <= 2`、`CDR3 cluster <= 2`。

pending master 上会按预期 fail-closed：open eligible rows 为 0 时拒绝生成伪 shortlist。

### 2.5 Top20 pose review bundle

脚本：`src/package_pvrig_top20_pose_review.py`

固定合同：

- 只接受 Top20 open candidates；任何 test32 ID 在打开 raw result 前立即失败；
- 每候选必须有 `2 conformations x 3 seeds = 6` 个成功 jobs；
- 每 job 至少 4 个完整 2x2 models；
- 按 native HADDOCK score 复制每 job Top3 原生 `.pdb.gz`；
- 最终目标严格为 `20 x 6 x 3 = 360` 个 poses；
- PVRIG/PVRL2 clash 必须来自明确的 pair-specific 字段，禁止用通用 clash 计数冒充 PVRL2 特异指标；
- geometry summary 只保留紧凑标量，不复制巨大 atom-pair 列表。

真实 schema 验证：

- Node23 原始 `job_result.json` 脱敏 fixture：`src/test_fixtures/pvrig_v4d_real_job_schema_v1.json`
- fixture SHA256：`8bf2a5e195a13e6e3877f3e13bdf60360d091f675c229ea69834bc87bfed6888`
- source raw SHA256：`07d028f5a55855164319d0910ecc23823a81adca1f8ac3b789b52958f159eed5`
- 当前 packager SHA256：`30825b03ea70cdb902cb9741f82249dbfd28cbc885a25d15ec5a750927ccf294`
- 实际单 job parser 收据：`audits/pvrig_top20_pose_packager_smoke_v1/smoke_receipt.json`
- 状态：`PASS_REAL_V4D_JOB_TOP3_COMPACT_POSE_PARSE`

## 3. 已部署的自动续跑

### 3.1 Node23 open-teacher watcher

- 目录：`/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716`
- watcher PID：`444259`
- 当前状态：`WAITING_V4D`
- 带 `flock`、幂等 receipt 检查、`ERR -> FAILED`、48 小时 timeout 和哈希闭包。

### 3.2 Node1 Deep-QC delivery watcher

- 目录：`/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716`
- 当前状态：`WAITING_DEEPQC`
- terminal 后核验 `100 TNP rows + 100 IgFold rows + 100 IgFold PDBs + ID parity`，再生成 manifest/receipt/hash-bound tar。

### 3.3 Node1 structure crosscheck watcher

- 目录：`/data/qlyu/projects/pvrig_pre_shortlist100_structure_crosscheck_v1_20260716`
- 当前状态：`WAITING_DEEPQC`
- Deep-QC terminal 后执行 100 条 hash-frozen NBB2/IgFold 检查并生成独立交付包。

### 3.4 本地总控 watcher

- 脚本：`src/monitor_pvrig_v4d_deepqc_postprocess.sh`
- tmux session：`pvrig-v4d-deepqc-postprocess`
- 2026-07-16 13:20 controller PID：`1649127`
- 当前状态：`RUNNING`
- 当前原因：`waiting for remote DeepQC/crosscheck and V4-D open teacher deliveries`

总控行为：

1. 每次下载先进入新的 `.staging.*`；
2. 核验外部 archive hash、内部 receipt/manifest/SHA256SUMS 和本地 pinned inputs/scripts；
3. 通过后原子提升到 `current/`；
4. Deep-QC 先完成时先做 partial v2 merge；
5. V4-D 完成后做 final v2 merge、open258 ranking 和 Top50；
6. 在 Node23 生成并同步真实 Top20 360-pose bundle；
7. 写最终 receipt；任一 gate 失败时保持 fail-closed。

远端 watcher 的本地规范归档：`audits/pvrig_remote_postprocess_watchers_v1_20260716/`。

## 4. 测试与验证

第二轮 code review 的两项 MEDIUM 已关闭，复核结果为 `NO_HIGH_OR_MEDIUM`：

1. 删除通用 clash -> PVRL2 特异 clash 的错误回退；
2. 加入默认执行的、哈希固定的真实 V4-D schema fixture 测试。

最终组合测试：

- parity audit：3；
- evidence master v1：2；
- pre-shortlist100：1；
- V4-D split/freeze：5；
- V4-D open teacher：7；
- evidence master v2：4；
- geometry shortlist：7；
- IgFold/NBB2：5；
- production-schema postprocess integration：1；
- Top20 pose packager：7 PASS + 1 optional remote test skipped。

合计：`43 tests = 42 PASS + 1 optional remote skipped`。此外：

- Python `py_compile`：PASS；
- local watcher `bash -n`：PASS；
- 真实 raw/production-aggregate closure smoke：PASS；
- 当前 packager 对真实 Node23 raw job 和原生 PDB.gz 的单 job smoke：PASS。

## 5. 后续自动执行顺序与完成门禁

接下来无需人工逐项触发，watcher 将按以下顺序继续：

1. Node1 完成 8 个 TNP chunks；
2. Node1 运行 4 个 IgFold GPU chunks；
3. Node1 生成 Deep-QC delivery 和 IgFold-vs-NBB2 delivery；
4. Node23 完成 2022 个 V4-D jobs；
5. Node23 fresh evaluator 必须 `PASS` 且 `unlockable=true`；
6. 只释放 open258 连续几何，test32 保持 sealed；
7. 合并 418-row evidence master v2；
8. 生成 ranked open258、Top50；
9. 生成真实 Top20 360-pose review bundle；
10. 核验全部 receipt/SHA256 并写总控终态。

终态产物支持的是“可追溯的计算优先级候选集”，不是实验结合、Kd 或功能阻断证明。
