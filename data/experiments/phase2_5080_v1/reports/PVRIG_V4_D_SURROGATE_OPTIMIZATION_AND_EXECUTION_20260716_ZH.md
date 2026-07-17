# PVRIG V4-D Surrogate 优化与执行路线

**更新时间：** 2026-07-17 03:47 CST
**主目标：** 用便宜的 VHH 序列模型逼近独立 8X6B/9E6Y Docking 的连续阻断几何结果，用于大库前筛。  
**证据边界：** 模型输出只是 computational docking-geometry surrogate，不是 PVRIG 结合概率、Kd、PVRL2 competition 或实验阻断真值。

## 1. 当前结论

现在最大的瓶颈不是 GPU，也不是网络太小，而是：

1. 独立双受体 Docking teacher 尚未完成；
2. 当前训练集只有 226 条、20 个 parent clusters；
3. Support V3 的 deployment denominator 为 6,861，其中 1,733 条被标为
   `IN_DOMAIN`；coverage 和 nested-validation 总门禁仍为 FAIL，未发布 production
   support table；
4. 小数据下过早解冻 ESM2/VHHBERT 或上更大 cross-attention，更容易学到 parent、CDR3 长度或生成器风格。

因此当前正确的优化顺序是：

```text
完成 V4-D 真实 teacher
→ 低复杂度 baseline/contact/embedding/fusion 公平比较
→ 冻结模型和 V4-F 预测
→ V4-F 未见 parent 正式评估
→ 主动学习增加 parent 和支持域覆盖
→ 数据量达标后再尝试 tiny MLP / residue cross-attention
```

## 2. 实测运行状态

### 2.1 Node23 V4-D

2026-07-16 18:55 CST 快照：

```text
2022 total jobs
813 SUCCESS
12 RUNNING
1196 PENDING
1 FAILED_MAX_ATTEMPTS
```

分层情况：

```text
controls: 282/282 SUCCESS
OPEN_TRAIN: 495 SUCCESS + 12 RUNNING + 848 PENDING + 1 FAILED_MAX_ATTEMPTS
OPEN_DEVELOPMENT: 36 SUCCESS + 156 PENDING
PROSPECTIVE_COMPUTATIONAL_TEST: 0 touched
```

Controller PID 265751 存活，HADDOCK/CNS 正在运行。当前不修改 controller、scratch、并发数或 job order。
最近 60 分钟完成 106 个终态 job；按当前速率线性估计约 2026-07-17 06:20 CST 达到 Docking 终态。这只是运行 ETA，不包含 aggregate/evaluator/teacher 时间，也不代表 evaluator 一定 PASS。

唯一失败为：

```text
RFV1__PLDNANO_VHH_00322__A_CENTER__H3__B02__M00
8X6B seed 3253: FAILED_MAX_ATTEMPTS
```

该候选在 8X6B 上已有 seed 917/1931 成功，在 9E6Y 上三个 seed 均成功，因此仍满足每个 candidate-receptor 至少 2 个成功 seed 的预注册最低要求，不应单独阻断 teacher 发布。

由于远程 job priority 在后段会将 open 与 test32 交错，test32 保守降级为 computational challenge；真正未触达的正式 prospective holdout 是 V4-F 96。

### 2.2 Node1 Deep-QC 和 V4-F

```text
Top100 Deep-QC: 受控暂停并迁移到 Node1 本地 SSD
NFS source: /data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716
SSD target: /data1/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716
V4-F Full-QC watcher: WAITING_UPSTREAM
V4-F panel: 96 candidates / 4 completely unseen parent clusters
```

Node1 上的 `run_deepqc.sh`、8 个 `vhh_screen.py` 和 8 个 TNP 子进程当前均为 `T` 状态。这不是未知卡死，而是由受控 SSD 迁移流程主动暂停；证据在：

```text
/data1/qlyu/pvrig_migration_20260716/MIGRATION_CONTROL.json
status = PAUSED_AND_MIGRATING_TO_SSD
full_run_resume_allowed = false
valid_completed_tnp_json_on_target = 65
```

只能在 runtime closure 复制、路径重定位、source-target parity 和 SSD smoke 全部通过后，由受控恢复脚本继续。禁止手工对这些 PID 发送 `SIGCONT`，也不得在 NFS 原目录中启动第二份 Full-QC。

V4-F 将对全部 96 条运行 Full-QC；之后对所有 hard-pass 候选运行独立双受体 Docking，不按模型分数二次挑选，失败后不从 panel 外补位。

V4-F 第一轮 reviewer 发现的三个 High 和一个 Medium 已修复：production shell gate 现在锁定 canonical Python/freezer；verifier 在 PASS 前重验 receipt/prediction/audit 当前输出；freezer 和六个本地依赖从预捕获字节执行并将实际执行源码哈希纳入闭包；已存在的空/非普通/不可读 receipt 被正确标为 corrupt。修复后定向测试 `20/20 PASS`、联合回归 `61/61 PASS`，第二轮独立复审结论为 `PASS`。prediction-freeze watcher 已安全重启，当前为 `WAITING_V4_D_SURROGATES`，`v4_f_labels_read=false`，不会在上游三路正式 artifact 到位前发布预测或开启 Docking gate。

## 3. 已经完成的模型资产

### 3.1 基础 sequence surrogate

已实现：

- OPEN_TRAIN 226 拟合；
- OPEN_DEVELOPMENT 32 选型；
- parent-cluster 隔离；
- sequence/length/parent/metadata shortcut baselines；
- parent bootstrap ensemble 和 uncertainty；
- 原子发布、artifact replay 和 hash receipt；
- 没有 sealed test label 输入参数。

### 3.2 Frozen embedding surrogate

已实现：

```text
ESM2 mean-pooled ridge
VHHBERT mean-pooled ridge
ESM2 + VHHBERT joint ridge
CDR-length-only shortcut
```

Embedding bank 含 7,087 条 VHH 和 1 条 PVRIG target，共 7,088 条。当前训练代码已可用，但因 open258 teacher receipt 尚未出现，正式训练会 fail-closed，不会使用临时或不完整标签。

### 3.3 Residue/contact 特征 V3

2026-07-16 已用本地 RTX 5080 完成正式重算：

```text
rows: 7087
columns: 125
seeds: 43 / 53 / 67
receipt verification: PASS
CSV SHA256: f48de64d253a76bc9cff19ab1348c1655be7306828289b28f9a04e5b95471e7d
audit SHA256: eb63f16aacef2ed3d7ed0a755bfc3c49a590e09248b28643b94dc7e2c4e27e29
receipt SHA256: b12c0ff0ce6760db7169ec3616dddaf05786e5ca795354f639ef2bf87c370e2b
```

V3 已强制闭合 candidate/cache/mask/checkpoint/hotspot 身份，且已将两个严重编码 CDR 长度的 raw contact-mass 列标记为 diagnostic-only。旧 V1/V2 release 已移入 quarantine，未删除。

### 3.4 稳定 contact schema V2

已经在不读取 Docking label 的前提下，按三种 seed 的稳定性冻结 12 个特征：

```text
paratope_mean
paratope_cdr_mean
paratope_cdr3_mean
paratope_cdr3_max
paratope_cdr_mass_fraction
contact_global_mean
contact_hotspot_weighted_mean
contact_hotspot_fraction
contact_cdr_hotspot_weighted_mean
contact_cdr3_hotspot_weighted_mean
contact_noninterface_mean
contact_interface_specificity
```

冻结 schema：

```text
prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json
SHA256: 22d11cdccb0af6ecb26eb3bdcbae6c35dc5bc57543d662cf9da94155ee746cc0
```

### 3.5 Contact/fusion 与部署闭环验证

2026-07-16 17:05 CST 前的最新验证：

```text
contact/fusion trainer full tests: 9/9 PASS
deployment scorer tests: 10/10 PASS
deployment watcher tests: 3/3 PASS
deployment total: 13/13 PASS
```

生产 deployment scorer 已重新执行并通过 `--verify-only`，当前正确 fail-closed：

```text
status: WAITING_FROZEN_MODEL_ARTIFACTS
published score rows: 0
candidate7087_deployment_scores.tsv: absent
verify status: PASS_WAITING_RELEASE_HASH_CLOSURE
```

模型评分治理分组已冻结为：

```text
DEPLOYMENT_SCORING_ALLOWED: 6350
MODEL_DEVELOPMENT_OR_CHALLENGE_EXCLUDED_NO_SCORE: 290
PROSPECTIVE_V4_F_SEPARATE_FREEZER_NO_SCORE: 96
UNTOUCHED_RESERVE_NO_SCORE: 351
```

三类 no-score 行在进入 base/embedding/contact feature replay 前已被物理移除，不是仅在输出表中屏蔽分数。

## 4. 下一步的模型比较

在 open258 teacher 释放后，只运行一次冻结比较：

| 模型 | 作用 |
| --- | --- |
| sequence/CDR length only | 检查是否只学了长度 |
| parent only | 检查是否只记住 scaffold |
| design metadata only | 检查是否只识别 patch/method |
| sequence feature ridge | 低成本序列 baseline |
| ESM2 ridge | 通用蛋白 embedding baseline |
| VHHBERT ridge | VHH 专用 embedding baseline |
| joint embedding ridge | 两种 embedding 融合 |
| stable contact mean ridge | 只用 12 个稳定 contact mean |
| stable contact mean+std ridge | 加入 contact seed 不确定性 |
| embedding+contact fusion ridge | 当前主候选 |

当前不上大型 MLP，不解冻 PLM，不使用 G1-G5 硬分类作主标签。V4-D 的冻结主目标仍是 `R_dual_min`；多目标连续回归应当另起新版本，不在看到 V4-D dev/test 结果后回改当前协议。

## 5. 模型门禁

开放开发集上至少检查：

1. overall Spearman 是否超过最强 shortcut；
2. parent-macro Spearman 是否改善；
3. held-out parent clusters 中是否至少 2/3 不退化；
4. uncertainty 高的样本是否真的更容易出错；
5. contact/fusion 是否超过 length-only、parent-only 和 embedding-only；
6. artifact replay 与 prediction hash 是否完全一致。

如果 open gate 失败：

```text
冻结 FAIL
不改门槛
不挑最好的 seed
不解封或反复利用 test32
不广泛用于 7087 排名
直接转入主动学习增加 teacher
```

当前 support audit 的总门禁为 FAIL，因此即使 open model gate 通过，2,643 条 `IN_DOMAIN` 也不得立即进入 production exploitation，只能用于研究性排序和 acquisition。只有新预注册 support 版本通过 null/coverage 门禁后，才能在其通过的子集上做受限 exploitation；其余候选继续走 uncertainty/diversity/direct-docking 路线。

## 6. V4-F 正式评估

在 V4-F 任何 Docking label 被打开前，先冻结：

```text
model configuration
teacher/split/feature/embedding hashes
open-development summary
96-row predictions
prediction SHA256
```

然后一次性评估 4 个完全未见 parent clusters。报告必须同时给出：

- overall metrics；
- per-parent metrics；
- per-CDR3-length metrics；
- Full-QC attrition；
- in-domain/near-domain 分层；
- uncertainty selective-risk。

## 7. 主动学习扩充

建议下一批预注册约 296 条，它们是 acquisition set，不是评估集：

### 7.1 已见 parent：200 条

20 个 OPEN_TRAIN parent，每个 10 条：

```text
4  predicted top
3  high uncertainty / model disagreement
2  generic-prior vs geometry-surrogate conflict
1  middle/low-score QC-pass control
```

### 7.2 未见 parent：96 条

```text
8 unseen parent clusters
x 3 target patches
x 2 design modes
x 2 candidates
= 96
```

另外保留至少 2 个 parent clusters 不进入 acquisition，用作下一版 formal holdout。

排除：

- V4-D 290；
- V4-F 96；
- 所有已知阳性、patent anchors 和 calibration mutants；
- exact sequence/CDR 近重复；
- Full-QC hard fail。

如果 V4-D open gate 失败，上述 predicted-top 配额改为 feature-diverse 和 generic-prior high/mid/low 分层，不得假设失败模型仍有效。

## 8. 什么时候才值得上更复杂模型

至少同时满足：

```text
>= 500 independent candidate teachers
>= 30 parent clusters
untouched unseen-parent formal holdout
continuous dual-receptor targets complete
support/OOD audit has a new preregistered version
ridge/fusion baselines frozen
```

第一个复杂升级只建议两层 tiny ordinal/regression MLP，而不是全量解冻 ESM2/VHHBERT。只有它在 untouched parent 上显著超过 ridge，并通过 target-shuffle、parent-only、length-only 对照，才能继续引入 residue-level cross-attention。

## 9. 与抗体生成路线的衔接

生成路线与 surrogate 训练路线保持独立：

```text
RFantibody / fixed-pose ProteinMPNN / AntiFold
→ Fast QC / Full QC
→ support/OOD 判定
→ support 总门禁通过后的 in-domain: surrogate exploitation + uncertainty quota
→ near/OOD: diversity + direct Docking
→ 真实 Docking 结果追加为新 teacher
→ 重训下一版 surrogate
```

生成器输出不能自动成为正标签，模型高分也不能代替真实 Docking。这样才能形成可迭代但不自我循环污染的闭环。

## 10. 当前正在执行的工作

1. V4-D 2022 jobs 继续运行；18:51 快照为 805 SUCCESS / 12 RUNNING / 1204 PENDING / 1 FAILED_MAX_ATTEMPTS，不干扰远程 controller；
2. Node1 Deep-QC 已受控暂停并迁移到 `/data1` 本地 SSD，当前禁止手工 `SIGCONT`；V4-F watcher 继续等待上游；
3. residue/contact V3 已完成并验证；
4. contact schema V2 已冻结；
5. contact/fusion trainer 完整测试 9/9 PASS，deployment scorer + watcher 13/13 PASS；
6. open258 teacher-ready 训练 watcher 已完成并正在运行，当前为 `WAITING_OPEN_TEACHER`；teacher receipt 到达后将自动运行基础、embedding 和 contact/fusion 模型；
7. deployment scorer 当前为 `WAITING_FROZEN_MODEL_ARTIFACTS`，已确认不会提前发布任何 7087 分数；
8. V4-F 修复后定向测试 20/20、联合回归 61/61 和真实 96 条 label-free preflight 均 PASS，第二轮独立 reviewer 结论为 PASS；prediction-freeze watcher 已重启并处于 `WAITING_V4_D_SURROGATES`，仍未生成生产预测或触及标签。

## 11. 可立即推进的工作

### 11.1 收口 V4-D teacher 与三路 surrogate

1. 继续只读监控 Node23，不调整当前 12 x 4 cores 的控制器；
2. 终局后要求 evaluator 新鲜聚合且所有 stability gates 为 PASS；
3. 验证 open258 teacher、audit 和 release receipt 的行数、split 和 hash closure；
4. 让已运行 watcher 自动完成 base、embedding、contact/fusion 训练，随后逐个执行 artifact replay 和 receipt 验证。

### 11.2 完成 Node1 SSD 迁移和受控恢复

当前已有的受控迁移资产为：

```text
/data1/qlyu/pvrig_migration_20260716/MIGRATION_CONTROL.json
/data1/qlyu/pvrig_migration_20260716/migrate_to_ssd.sh
/data1/qlyu/pvrig_migration_20260716/migrate_runtime_closure.sh
/data1/qlyu/pvrig_migration_20260716/finalize_and_smoke_ssd.sh
```

remainder-only 恢复实现已经过两轮修复和独立复审，最终结论为 `PASS`；本地与 Node1 测试均为 `6/6 PASS`。但真实 preflight 仍为 WAITING，因此未启动新的 TNP/IgFold 任务：

```text
experiments/phase2_5080_v1/src/resume_node1_ssd_deepqc.py
experiments/phase2_5080_v1/src/launch_node1_ssd_deepqc.sh
/data1/qlyu/pvrig_migration_20260716/SSD_DEEPQC_RECOVERY_PROTOCOL_V1.json
/data1/qlyu/pvrig_migration_20260716/SSD_DEEPQC_RECOVERY_STATIC_VALIDATION.json
```

真实 SSD 快照中虽有 65 个 TNP JSON，但严格的 candidate ID + sequence + command log + exit-code + artifact 闭包只允许复用 64 条；另 36 条必须重跑。exact 64 reuse / 36 rerun manifest 及 SHA 现已冻结；IgFold 在启动前强制检查 4 x 25、100 unique 且 exact candidate set；旧 NFS 进程按 PID/PPID/starttime/cmdline/cwd/descendant closure 绑定；TNP final inventory 与 SSD delivery 均使用不可变、内容寻址、receipt-last 发布。由于旧暂停进程仍持有 NFS lock，新控制器明确禁止 NFS sync-back，最终 delivery 将发布到 `/data1/.../immutable_deliveries/`，然后停在“等待 downstream watcher 切换路径”状态。当前 preflight 因 `RUNTIME_CLOSURE_COMPLETE`、`SSD_SMOKE_PASS`、finalizer 五阶段和 source-target parity 尚未完成而正确返回 WAITING。收口必须同时满足：

1. 不对旧 NFS 进程树就地发送 `SIGCONT`；旧进程只作暂停现场和可追溯证据；
2. 只在所有 preflight 条件自然 PASS 后单次执行已冻结 launcher；不建立绕过 preflight 的 waiter，不修改旧 NFS 进程树；
3. 完整 IgFold 阶段在 SSD 运行并使用 4 张 GPU；单条 `--gpu 0` smoke 只是运行时验证，不代表完整结构预测已启动；
4. SSD immutable delivery 就绪后，独立修改并审计 downstream watcher 路径，直接读取 `/data1` delivery；不覆盖原 NFS 工程文件；
5. source-target parity、TNP smoke、IgFold smoke、100-row merge 和最终 delivery receipt 全部 PASS 后，才能将 Node1 Deep-QC 标记为完成。

### 11.3 修复 V4-F 安全门禁

1. 已完成 canonical execution lock、fresh output revalidation、executed-source closure 和 corrupt-receipt 分类修复；
2. 修复后定向测试 20/20、联合回归 61/61，第二轮独立 reviewer 为 PASS；
3. watcher 已重启为 `WAITING_V4_D_SURROGATES`，只等待 V4-D 三路正式 artifact，不读取 V4-F label；
4. 上游到位后仍要对真实生产 receipt 做一次端到端验证；只有该 receipt 通过，Docking gate 才可开启。

### 11.4 新建 support contract，不修改已失败的旧门槛

当前 support V2 只有 2643/6861 deployment candidates 为 `IN_DOMAIN`，且 CDR3 shuffle 与 unseen-parent chimera null gates 失败。可立即设计一个新的、独立预注册的 support 版本，但不能：

- 回改 V2 的 0.60 coverage 或 null 门槛；
- 把 `NEAR_DOMAIN` 临时改名为 exploitation-supported；
- 在看到 V4-D/V4-F label 后选择最好看的 support 参数。

新版本应优先评估 parent-conditioned 的 frozen embedding/contact 距离、nested unseen-parent 校准和更有区分度的 null controls，然后在不读取 Docking label 的前提下冻结。

### 11.5 准备后续扩充，但不污染保留集

- V4-G unseen96 可作为 acquisition-only 面板继续准备 Full-QC；
- seen-parent 200 条必须按 V4-D open gate PASS/FAIL 分支使用预注册配额；
- `C0019` 和 `C0072` 两个 reserve parent 继续 no-score、no-Full-QC、no-Docking，直到新 prospective protocol 和 prediction receipt 冻结。

### 11.6 将旧 dual128 作为跨 campaign 辅助证据

已对以下历史双受体 Docking 运行做只读审计：

```text
/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714
```

该运行含 128 条候选、47 条 controls 和 1050 个独立 job，终局为 1049 SUCCESS / 1 FAILED_MAX_ATTEMPTS，evaluator PASS。它与 V4-D 290 在 candidate ID、完整序列、sequence SHA256、CDR1/2/3 和 parent/framework 上均为零交叉；Docking/scoring 的物理参数和 restraint 内容实质相同。

但旧 128 全部来自同一 h-NbBCII10 framework family 的三个变体，并且是根据旧 Docking/RF2/geometry bucket 事先挑出的强选择偏差面板。因此：

1. 不加入当前已冻结的 V4-D 主 teacher，不用于当前模型选择或 prospective 测试；
2. 可在新版 V4-D.1/V4-E 中作为 OOD、低权重辅助 teacher，但必须报告 `V4-D primary only` 与 `primary + legacy128` ablation；
3. 合并前先用两个 campaign 重复的 47 controls，按 `entity_id + receptor + seed` 生成 282-row 跨 campaign bridge，且必须在看 candidate 结果前冻结连续量 concordance 判据；
4. 使用与 V4-D 相同的 builder 从原始 pose 重算 `R_8X6B/R_9E6Y/R_dual_min`，不将旧 G1-G5、`robust_A` 或 P2/P3/P4 富集当作主标签；
5. 它只是 computational docking-geometry evidence，不是 PVRIG binding 或实验阻断真值。

### 11.7 已经冻结的两个不读标签 P0 合同

本轮已在读取成对 control 连续分数和运行 Support V3 之前，先冻结两个新版本合同：

```text
experiments/phase2_5080_v1/audits/phase2_v4_d_cross_campaign_control_bridge_preregistration.json
SHA256 0788d7d9fa98c1f39264cda9968aa49cf9515fb0f48ab57eaab7c2f840d7b163

experiments/phase2_5080_v1/audits/phase2_v4_d_sequence_support_v3_preregistration.json
SHA256 72dc6adc1e3404c65304d489b303f6d7ba6a08d3edd626518dbcfc74c34c186a
```

Control bridge 只允许先从两个 `docking_jobs.tsv` 筛出 282 条 control allowlist，再按 `entity_id + conformation + seed` 打开对应的 raw `job_result.json`；明确禁止读取 campaign-wide candidate aggregate。预注册了 Spearman、cluster-bootstrap CI、Lin CCC、绝对误差和 bias 硬门；任一失败都禁止将 legacy128 并入训练。该文件在成对 control 提取前做了一次仅修正先前 schema 抽样披露的 v2 correction；硬门、输入和决策规则未改。

Support V3 不回改 V2 失败门槛，固定使用 OPEN_TRAIN 226 条、parent-conditioned same-neighbor、CDR order-sensitive 表示、ESM2 residue embedding 和 12 个稳定 contact features，并预注册 composition shuffle、cross-parent CDR graft、channel splice 和 unseen-parent chimera 四类 null。它仍然是 label-free OOD 门，不会证明模型正确。

### 11.8 已完成的不干扰运行准备

Control bridge 已有 control-only builder 和 7 个合成测试，包含 production input hash、canonical protocol semantics、candidate-result 物理排除、10,000 次 entity-cluster bootstrap、硬门决策和 receipt replay。当前尚未执行真实成对 control 提取；需在独立 code review 通过后再冻结实现 hash 并运行。

Support V3 已完成 synthetic-validated skeleton 和 6 个测试，并对真实 label-free 输入完成闭包：

```text
experiments/phase2_5080_v1/audits/phase2_v4_d_sequence_support_v3_input_closure.json
SHA256 5e525fb6901c102f5c302b067918cd4ca3215a1718f173b574c5eb46ddf097af
status PASS_FROZEN_LABEL_FREE_INPUT_CLOSURE
candidate/contact/CDR-mask/ESM2 rows 7087/7087/7087/7087
Docking or experimental label paths opened 0
```

它明确拒绝发布 production support table，直到真实 ESM2/contact null materialization adapter 另行实现和审核。

V4-G unseen96 已生成可重放的 Full-QC 输入包，但没有复制到 Node1 或启动：

```text
experiments/phase2_5080_v1/prepared/pvrig_v4_g_unseen96_full_qc_v1/
PACKAGE_RECEIPT SHA256 07a2cda4d37288d0e06e2a21e6f74d960531106aafc68644e8fdb36dfaa70bdc
96 candidates / 8 unseen parents / reserve2 excluded / label files opened 0
```

生成器和 shell 运行时 smoke 为 7/7 PASS；waiter 只接受 `/data1` 不可变 Deep-QC delivery 与显式 path-switch receipt，不会因旧 NFS `COMPLETE` 状态误启动。

## 12. 停止条件

V4-D 当前版本在任一情况下应停止扩展：

- remote evaluator 不是 PASS；
- open258 teacher 行数、split 或 hash closure 不一致；
- 发现 test raw label 进入特征、调参或排名路径；
- 所有候选模型都不能超过最强 shortcut；
- uncertainty 不能识别高风险预测；
- V4-F 未见 parent 结果明显失效。

这些失败都应当触发“增加独立 teacher 和 parent 覆盖”，而不是临时改门槛或换更大网络。

## 13. 2026-07-16 23:55 CST 执行检查点

### 13.1 V4-D 主 Docking 链正常

Node23 实时只读快照：

```text
2022 total jobs
1343 SUCCESS
12 RUNNING
666 PENDING / not-yet-materialized
1 FAILED_MAX_ATTEMPTS
controller PID 265751
load1 约 42.9
最近 30/60/120 分钟吞吐约 114/111/105 jobs/hour
```

按当前速度预计还需约 6.0–6.5 小时。唯一失败 job 对应候选在同一 receptor
仍有另外两个成功 seed，因此当前不改 controller、并发、阈值或 job order。

下游仍严格等待：

```text
Node23 open-teacher watcher: WAITING_V4D
local surrogate watcher: WAITING_OPEN_TEACHER
local V4-F watcher: WAITING_V4_D_SURROGATES
V4-F label paths accepted: 0
```

### 13.2 Node1 Deep-QC 与结构交叉检查已闭合

Node1 SSD Deep-QC immutable delivery 已独立验证：

```text
100 candidates
85 VALID_TNP
7 TNP_NUMBERING_HARD_FAIL_NA
8 UPSTREAM_L2_HARD_FAIL_NA
100 IgFold PDB
431/431 immutable payload rows hash-closed
```

活跃 content id：

```text
83bf623afa8ed2364b6432ac5e99d00137d38e251a7393cd4ca1ac4cc04dd5a0
```

IgFold–NBB2 crosscheck 也已完成：

```text
100/100 PASS
0 failure
package SHA256 3947dcf8398d47ac9bc7f8f974d42c9eb7fd9cad1ab084595e3a2ebc000db859
```

本地 postprocess controller 已重新验证两份 delivery，并生成 418-row evidence
master；它当前只等待 V4-D open258 teacher，不读取 sealed test geometry。

### 13.3 Support V3 已真实运行并严格失败关闭

RTX 5080 生产 materialization 已完成，不是代码崩溃，而是预注册门禁未通过：

```text
status: FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY
nested validation overall: 0.5885 < 0.80
worst parent: 0.1538 < 0.60
deployment IN_DOMAIN: 1733/6861 = 25.26% < 60%
```

四类 null gate 全部通过；Docking/实验标签路径打开数和 V4-F 标签路径打开数均为 0。
因此当前 representation 的抗伪支持性较强，但 parent 覆盖过窄。正式 support table
没有发布，也不能把 `NEAR_DOMAIN` 改名或降低旧门槛。轻量终态证据保存在：

```text
reports/pvrig_v4_d_sequence_support_v3_deployment_v2/runtime_fail_closed_evidence/
```

### 13.4 V4-G 发现并隔离了一个假终态

Node1 重启前，V4-G wrapper 写出了旧版 `PASS` receipt；但 fresh audit 发现：

```text
cascade full = running
full merge = absent
2 个 full chunks 均无 complete.json
full_merged.tsv = absent
当前相关进程 = 0
```

所以该 receipt 已按证据视为无效，不能进入下游。新 completion contract 要求：

```text
rc == 0
+ full/merge_full state 均 complete
+ 2 个 chunk completion markers
+ full_chunk_status exact closure
+ 24 shortlist IDs 与 full_merged exact closure
+ full_qc_summary 和 hash replay
```

任一缺失均返回 rc 86 并写 `runner.failed.json`。恢复运行只重跑缺失的 24 条
Full-QC，使用 versioned SSD-native runtime closure，不覆盖旧证据、不改变 panel、
筛选规则或阈值。

恢复已在以下新目录终局通过：

```text
/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716
status: PASS_V4_G_UNSEEN96_FULL_QC_RECOVERY_VALIDATED
runtime closure: 86 files
runtime manifest SHA256:
603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d
full rows: 24
full hard-pass: 12
full hard-fail: 12
```

第一份 recovery v2 因 Python `__pycache__` 内含旧 NFS 编译路径而在启动任何 chunk
前 fail-close；v2.1 排除 `.pyc/__pycache__` 后确认 runtime manifest 无 `/data/qlyu`
路径命中。两条 12-sequence chunk 的完成标志、状态表、24-ID closure、merge 和
summary hash 均已 fresh 验证。

需要注意，V4-G 的 attrition 不是均匀的：

```text
Fast-QC hard-pass 24 条只来自 C0154 和 C0372
C0154: Full-QC 12/12 pass
C0372: Full-QC 0/12 pass，均有 missing_n_terminal
其余 6 个 V4-G parent: Fast-QC 0/12 pass
```

因此 V4-G 当前只增加 1 个可用 parent cluster，而不是理想的 8 个；它解决了一小部分
teacher 数据量，但没有解决 Support V3 的 parent breadth 问题。下一步必须先对 7,087
条候选做一次独立、版本化、纯序列/QC 的 Node1 Fast-QC census，冻结真实可部署分母和
parent 可用性，再设计 Support V4-A acquisition。不能把失败 parent 从旧结果里静默删除。

### 13.5 算力调度决定

- Node23 当前 12 个 HADDOCK jobs 持续占用约 48/64 CPU，保持不动。
- Node1 重启后负载很低，优先用于 V4-G 24 条 SSD-native Full-QC 恢复。
- Node25 可访问且具备 HADDOCK/CNS，但当前 load1 约 39，其他用户正在占用大量 CPU；
  当前不抢占，也不把冻结中的 V4-D 跨节点迁移。后续新批次只有在做过跨节点
  control concordance 后才考虑分流。

### 13.6 下一执行顺序

```text
V4-G 24 条 Full-QC fresh recovery receipt（已完成）
→ 7,087 条 Node1 Fast-QC census / parent 可用性冻结
→ V4-D 远程终局/evaluator
→ open258 teacher hash closure
→ base/embedding/contact-fusion 一次性冻结比较
→ V4-F 96-row predictions 先冻结、后独立 Docking
→ V4-G 仅 12 条 C0154 hard-pass 作为 acquisition-only direct Docking 输入
→ 按 Fast-QC census 扩展合格 parent clusters 与 teacher 数量后另起 Support V4
```

Support V4 的主要修复方向是增加独立 parent-cluster teacher 覆盖，而不是对 V3
门槛做事后放宽。复杂神经网络仍排在数据扩充和 ridge/fusion baseline 之后。

## 14. 2026-07-17 00:33 CST 执行检查点

### 14.1 7,087 条 large-scale-fast census 已完成并独立复跑验证

Node1 使用 16 个并发 chunk、每 chunk 2 workers，对冻结的 7,087 条候选执行了
`blocker_calibrated --large-scale-fast`。这是真实 fresh 运行，不是重放已有 candidate
结果：16 个 chunk 的墙钟分别为 34.408–41.983 秒；独立 verifier 将完整
`chunk_000001` 重新执行一次，用时 41.049 秒，原始与复跑的
`portfolio_ranked.tsv` SHA256 完全相同：

```text
69cfbfc9079216b3d89a5429a224d53f851a407ed122cc41d2e62b962762b82c
```

另外 8 条隔离单候选复跑的 `hard_fail + reason_summary` 为 8/8 精确一致。冻结结果为：

```text
7,087 unique candidates
40 parent clusters
4,578 large-scale-fast hard-pass
2,509 large-scale-fast hard-fail
29 parents >= 36 fast-pass planning capacity
11 parents < 36 fast-pass planning capacity
```

所有 20 个 `OPEN_TRAIN` parent 均达到 36 条容量线；其中最低的是 C0139，仍有
76 条 fast-pass。这为后续按 parent 分层的 acquisition/readiness 方案提供了足够的
纯序列候选容量，但不能直接证明 Full-QC 或 Docking 可用性。

这里必须保持严格语义边界：本轮运行包含 vhh-eval 的 Python `abnumber.Chain`
IMGT/Kabat 编号、FR/CDR/保守位点、cheap liability/ProtParam 和官方+本地阳性 CDR
novelty；official `ab-data-validator` 对全部 7,087 条均为
`DEFERRED_TO_FULL_SHORTLIST`，显式 ANARCI binary 未直接执行，AbNatiV、Sapiens、
TNP、team diversity 和结构预测均未运行。因此 4,578 只能称为
`large-scale-fast sequence/developability planning capacity`，29 个 parent 只能称为
Fast-QC 容量充足，不能称为 Full-QC parent。

本地可复现证据：

```text
reports/pvrig_candidate7087_node1_fastqc_census_v1_20260716/
```

其中包含 134 项 SHA256 闭包、16 组 command/marker/timing/log、candidate/parent
结果、receipt 和独立验证记录。

事后闭包审阅还确认了两个不推翻 census 数学结果、但不应隐藏的实现限制：
runner 只检查 `INPUT_AUDIT.json` 中的 7,087/40 计数，没有将该 audit 的哈希与
freeze 再比对；receipt 是最后一个科学输出，但之后仍写了 terminal status marker，
因此原文中 `LAST_AFTER_ALL_CLOSURE_GATES` 的字面表述过强。这些限制将在下一版
census closure 修复；当前 4,578/2,509 计数、16 个 chunk 重放和 134/134 哈希验证
仍保持有效。Git allowlist 也已从无界 `chunk_*` 收紧为冻结的
`chunk_000001`--`chunk_000016` 范围。

### 14.2 seen200 V1 已 fail-closed，V2 已冻结但尚未读取模型结果

已在 surrogate 结果出现前冻结 future seen200 selector：20 个 `OPEN_TRAIN` parent
各取 10 条。若 open-development gate PASS，每个 parent 使用
`4 top + 3 uncertainty + 2 disagreement + 1 hash-control`；若 FAIL，则以 4 条
label-free CDR diversity 替换 top 配额，其余 3/2/1 不变。

选择器严格排除 V4-D290、V4-F96、reserve2、90 条 identity-only calibration
sequence 和 exact duplicate；production seen200 manifest 尚未生成，V4-D prospective
 test、V4-F 和未来 Docking label 均未打开。专用 10 项测试及与 V4-G 联合的 18 项
回归均通过。

**后续独立审阅发现 V1 不可运行 production selection**：它绑定的是旧
`fast_gate_formal_eligible_v1.csv`，没有消费新完成的 7,087 条 Node1 census，因而可能选入
已知 `fast_hard_fail=true` 的序列。另外 V1 的 hash-control 在模型排序桶之后才选取，
其成员可随模型分数改变，与“无模型 control”的声明不符。因此 V1 保留原字节
作 preproduction failure evidence，不会生成 seen200；正在另起 V2，强制绑定
census TSV/receipt/audit 哈希、先硬拒 Fast-QC failure，并在任何 model-ranked
bucket 之前预留 score-invariant hash control。

V2 现已冻结完成：它同时绑定 census TSV、receipt、audit 和 independent
verification，并要求 deployment summary/receipt 中三类 `*_labels_read` 字段必须
显式为 `false`，三类 `*_label_paths_accepted` 必须显式为整数 `0`。V1+V2
共 26 项回归通过，且 V1 selector/tests/freeze/receipt 字节均未改变。关键哈希：

```text
V2 selector: 3ceae574e077d5044dfcd3be14b87b95daea968f8c623de7054a6adecea1a399
V2 tests:    4b4798df80b6d63e3ded7d45346a40a925288e579a1311dc62b3f5c8b925d26c
V2 freeze:   4122651e4b1742e097b5a5b7cc68611f3470ccaa22b4507dbaacef9d3e70ced7
V2 receipt:  95fcdf2a7623190cf891b49d357e8db29d6fd06d9a075ebf087041c6caacf3a7
```

当前旧 deployment-scoring V1 缺少新增的显式 accepted-path 字段，所以 V2 按设计
fail-closed；尚未生成 `seen200_acquisition_v2`。必须等新的 scoring release 按新契约
出具零标签路径 receipt 后才能执行选择。

### 14.3 Support V4-A acquisition/readiness 合同已冻结

在不读取任何模型或 Docking 标签的前提下，已基于 census 冻结新的 V4-A 容量与
未来采集规则；Support V3 仍保持
`FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY`，其旧门槛没有修改。

角色和 exact-identity 排除后，20 个 `OPEN_TRAIN` parent 仍有 2,962 条 eligible
候选；单 parent 最低 69 条、单 patch 最低 17 条。未来池冻结为：

```text
20 parents × 36 = 720 rows
per parent: 24 acquisition + 12 audit
per patch:  8 acquisition + 4 audit
per parent: 36 exact-unique CDR3
selection: deterministic max-min edit diversity + SHA256 tie-break
```

16 个 parent 可以在每个 patch 内平衡 H3/H1H3；C0139、C0500、C0509、C0533
的 Fast-QC H3 survivor 为 0，因此显式使用同 parent、同 patch 的 H1H3-only
fallback，不借用 open-development、prospective test、V4-F、V4-G 或 reserve2。
全局 unique-CDR3 quota feasibility 已通过。

在 prereg、capacity audit、builder、10 项测试和 V2 implementation receipt 均闭包后，
2026-07-17 01:10 CST 已显式执行无标签 production materialization，生成：

```text
720 rows = 20 parents x 36
480 FUTURE_NODE1_TEACHER_ACQUISITION
240 LABEL_FREE_AUDIT
3 patches x 240
720 parent-local exact-unique CDR3
manifest SHA256: 73454cbf8194d3faa5cad354a5b2f31f433e317d5222a6cd59906775fb56bfca
```

输出在
`prepared/pvrig_support_v4_a_acquisition720_v1/`，四个非 receipt 文件的哈希均与
receipt 精确一致。这仍然只是未来 teacher acquisition 清单，不能解决跨 parent
support coverage，也不能发布 Support-domain PASS。

Node1 随后已对全部 720 条运行无替换 Full-QC，使用 16 fast/full chunks x 2
workers，上限 32/64 CPU，不使用 GPU，TNP 保持延后。冻结的 7,087 census 中已是
Fast-QC pass 的这 720 条在 fresh 重跑中仍为 720/720 fast hard-pass；Full 阶段亦输出
720/720 `hard_fail=False`、720/720 official-validator PASS 和非空 AbNatiV 分数。但这不等于
全部可直接提交：

```text
REVIEW_DEVELOPABILITY: 675
REVIEW_NOVELTY_MARGIN:   37
REVIEW_RISK:              8
single-domain suitability: 389 good / 223 borderline / 108 poor
AbNatiV VHH score range: 0.4665--0.8355
```

因此正确解读是“720 条都未触发冻结硬拒门，可进入后续层内排序”，而不是
“720 条都有高开发性”。本地证据包为
`reports/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717/`，15 个轻量 member
哈希全部通过，`SHA256SUMS` 哈希为
`e7c8897c604a9225ad5e23b6b0c4f9b84b86be717960841740aa6bc35e9b1b82`。
一次人工 post-run `--preflight` 曾覆盖 canonical `zero_work_preflight.json`；该文件已显式
重分类为 post-run runtime reverification。真正 prelaunch 证据由冻结 launcher 在 runner 启动前
写入的 raw log（mtime 17:24:10 UTC）重建并绑定；独立 correction receipt 记录了这一
管理更正，科学输出和阈值未改动。
冻结的当前输入中没有 NaN/Inf；但 builder 尚未对 positive-identity 数值显式做
`isfinite` 拒绝。因为输入哈希已绑定，这不影响本次 readiness 结论；在真正运行
720-row production 前应另起新版加入 fail-closed 测试。

### 14.4 V4-G C0154 的 12 条 Full-QC hard-pass 已完成双工具单体结构

Node1 在 versioned `/data1` SSD 路径对不替换的 12 条 C0154 hard-pass 运行了：

```text
NanoBodyBuilder2 primary: 12/12
IgFold crosscheck:        12/12
basic backbone sanity:    12/12
```

其中 11 条 NBB2 为 refined，1 条为 `unrefined_fallback`；该条保留显式标记，不做
replacement。NBB2–IgFold 的描述性 crosscheck 显示 framework Kabsch RMSD 中位数
0.703 Å（范围 0.675–0.979 Å），CDR3 RMSD 中位数 3.402 Å（范围
2.689–6.096 Å）；这些指标只记录结构不确定性，不用于筛选或替换。

72 个 acquisition Docking job（12 candidates × 2 receptors × 3 seeds）已经完成 exact
matrix、物理参数和 no-label preflight，但仍为 0 runs / 0 results。原 V2 waiter 包含
V4-D 2022-job 终局、open258 teacher complete、TEST32 sealed 和 load1 <= 16 等表层门；
但独立审阅发现它没有遍历验证 `ACQUISITION_PROTOCOL_LOCK.json.files[]`，也没有将
trust-anchor 本身、implementation freeze 以及 runtime source/open-teacher/Python/load 覆盖
硬绑到不可变哈希。因此 V2 不足以安全启动 acquisition。

V2 waiter PID 1841547 已在确认 0 controller / 0 runs / 0 results 后以
`SIGSTOP -> verify-zero-work -> SIGKILL` 安全终止，并保留远程停止 receipt；当前正在另起
V3 waiter，逐项验证 lock-relative regular files/no-symlink/no-traversal/size/SHA256，并硬绑
anchor/freeze 与所有 runtime overrides。V3 完成前 acquisition 保持 0-job。

V3 现已冻结并部署：非循环 launcher/waiter 链硬绑 V2+V3 anchor/freeze 哈希，
完整验证 protocol lock 中 47 个文件（2,589,493 bytes），包括 controller、run_job、
72-row manifest 和 12 个 PDB。九项 tamper/env/path/symlink 安全测试全部通过。
V3 waiter PID 1898924（nice 15）当前只是安全等待，acquisition 仍为
0 controller / 0 runs / 0 results / 0 job-status。本地轻量证据新闭包：

```text
reports/pvrig_v4_g_c0154_hardpass12_acquisition_v1/SHA256SUMS
97ff27e0b24fc488ed5f2607fb919c694c7111f04ede0bd081fefc3df7dfa9ef
```

该包当前共有 66 个 SHA-bound 轻量 member，全部按精确 Git allowlist 收口；
本地不包含 PDB、模型、Docking runtime output 或 `__pycache__`。升级前 V2 证据的
`SHA256SUMS` 哈希 `9ca4adf1...b1be8e9` 仅作历史检查点；当前权威闭包是上述
V3 `97ff27e0...dfa9ef`。

### 14.5 V4-D 主链继续产生 fresh 结果

`status/summary.json` 自 21:08 后未继续刷新，因此实时监控改为只读统计
`results/*/job_result.json` 与 active `run_job.py`，不修改冻结 controller。00:33 CST
的 fresh 文件系统证据为：

```text
1,422 completed job_result.json
11 active run_job.py
1 failed-attempt entity
2022 frozen total jobs
```

结果目录在 00:32 仍持续写入新的 pose score 和 `job_result.json`，Node23 load1 约
37.9，说明主链没有停滞。按最近约 110–115 jobs/hour 的吞吐，剩余约 5–6 小时。
下游仍为：

```text
open-teacher watcher: WAITING_V4D
surrogate watcher:    WAITING_OPEN_TEACHER
V4-F watcher:         WAITING_V4_D_SURROGATES
V4-F labels read:     false
```

2026-07-17 00:52 CST 的后续只读检查为：

```text
1,454 completed job_result.json
12 active run_job.py
555 pending
1 failed-attempt entity
Node23 load1: 39.93
open-teacher: WAITING_V4D
V4-G12 acquisition: 0 runs / 0 results / 0 status jobs
```

冻结 controller PID 265751 仍存活。上述 V2 acquisition waiter 在 00:52 时仍存活且
没有提前启动 controller，随后因独立审阅发现的信任闭包缺口而被安全终止。

同一次 pre-label 预检还发现 surrogate watcher helper 中 `shard_00001.pt` 的
expected SHA 少了一个字符（63 位），而真实 shard 及 embedding trainer 中的冻结值为
64 位。该错误在 teacher 缺失时被 WAITING 分支遮蔽，open258 一到就会造成确定性
`FAILED_INPUT_VALIDATION`。旧 surrogate watcher PID 2045857 和 V4-F watcher PID 2437379
均已在 waiting/zero-label-path/zero-training 状态下安全停止。下一版将修正该 typo，
并在 teacher 到达前对 base/embedding/contact trainer、helper 和 launcher 加入预冻结
implementation hash 锁，然后重启两条 watcher。

该修复已于 01:40 CST 以 V2 完成，而不是修改旧 watcher：86 项联合回归在 RTX 5080
环境下全部通过，7 个 embedding shard 的真实 SHA256 全部纳入 immutable trust anchor，
其中 `shard_00001.pt` 的冻结值为正确的
`3b08d1b685904bfad4855b377541b3c9477a3082e7b017a53b7b5ca2396732f1`。
两个 tmux 长驻控制器现为：

```text
surrogate V2 PID 3743587: WAITING_OPEN_TEACHER
V4-F V2 PID 3743592:     WAITING_V4_D_SURROGATES
prospective/V4-F labels_read: false
accepted label paths:          0
```

V2 surrogate/V4-F trust-anchor SHA256 分别为
`9d5aff568b9473a56c6111fae6221266eabe09f92be7752c76bbc596ef2d74cf` 和
`3d6be9ddb2d0dcb8703779053aa30fcbac5a9b12191095ec0fafe1e00c527e84`；
旧 V1 状态只保留为被安全替代的历史证据。

### 14.6 当前下一步

```text
已完成：V4-G12 NBB2/IgFold terminal closure
已完成：72-job dual-receptor acquisition package；V2 waiter 审阅后停止
已完成：Support V4-A label-free acquisition/readiness contract（不修补 V3）
已完成：seen200 V2 和 V4-G12 waiter V3 的信任闭包
已完成：surrogate/V4-F watcher V2 修复、86 项回归与长驻启动
当前：Support V4-A720 全集 NBB2 + IgFold 结构预计算
当前：等待 V4-D evaluator 与 open258 teacher hash closure
→ 本机依次训练 base / frozen-embedding / contact-fusion surrogate
→ 先冻结 V4-F 96 条预测，再允许其独立 Docking
→ 仅用经验证的 seen200 V2 selector 做下一轮主动学习扩充
```

主目标仍是从序列近似 `R_dual_min` 等独立双受体 Docking 连续几何；以上 Fast-QC、
structure support 和 acquisition 工作只是在扩充可用输入与 teacher 覆盖，不能替代
surrogate 的 prospective 验证。

### 14.7 联合回归与哈希闭包

在不读取真实 V4-F/test32 标签、不触发 production selection、训练或
Docking 的条件下，已完成一次联合验证：

```text
7087 census                                    3/3 PASS
V4-G Full-QC package/recovery runner           8/8 PASS
seen200 selector                              10/10 PASS
Support V4-A readiness                        10/10 PASS
DeepQC V3.2 reconciliation                    10/10 PASS
three-state delivery validator                 3/3 PASS
candidate evidence merge                       4/4 PASS
V4-G12 open-teacher/waiter                     4/4 PASS
Node23 72-job protocol                         3/3 PASS
```

去除本地/远程重复 waiter 测试后共 55 个不同测试全部通过，实际执行
59 次全部通过。八个证据包共 219 条 `SHA256SUMS` 记录全部验证通过。
Git 可见的未跟踪证据总量约 2.5 MiB，未放行 PDB/CIF/checkpoint/cache/archive
等大文件。

### 14.8 01:40 CST 后的最新执行与独立复验

Node23 V4-D 的 fresh 文件系统计数已推进到：

```text
1,539 SUCCESS
12 RUNNING
470 PENDING
1 FAILED_MAX_ATTEMPTS
2,022 frozen total
controller PID 265751, load1 about 40
```

controller 仍按冻结的 `max_parallel=12` 补满队列，结果目录持续写入；唯一失败 job
没有被事后改成成功，也没有改变 frozen protocol。open-teacher watcher PID 1746400
仍为 `WAITING_V4D`，会在 terminal evaluator 的所有 gate 通过后才发布 open258。

Support V4-A720 的 label-free 单体结构全集也已在 Node1 SSD 启动：

```text
remote root: /data1/qlyu/projects/pvrig_support_v4_a_acquisition720_monomer_structures_v1_20260717
wrapper / runner PID: 396235 / 396238
resources: GPU 0--3, 4 workers x 8 threads = at most 32/64 CPU
policy: all 720 NBB2 primary + all 720 IgFold crosscheck
latest verified snapshot: 40/720 dual-method success, 0 failure
```

该任务不按结构结果替换候选，不读取模型、Docking、geometry 或实验标签；启动前
zero-work preflight 为 0 PDB/0 candidate records，启动后 live-FD audit 对 forbidden
路径命中为 0。Startup receipt SHA256 为
`fb43e1c4981121b16d49474c1918c720df6a0447f9f30701f4dbd8c7d9e505a0`。
独立 Git scope 审阅发现本地结构 manifest 虽不是 FASTA，却仍包含 720 条完整 VHH
序列；它已从 Git allowlist 移除而保留在本地，原 prereg/startup receipt 中的 manifest
SHA 仍提供闭包。该发布范围更正不删除本地输入，也不改变结构运行。

对 720-row Full-QC 的独立复验为
`PASS_WITH_MEDIUM_METADATA_AND_SEMANTIC_CAVEATS`，无 HIGH 问题，但补充了三个必须
长期保留的语义限制：

1. prereg 内嵌 `frozen_at_utc=17:30Z` 是错误元数据；真正的预执行证据是
   17:23:38 implementation freeze 和 17:23:39 package receipt 对同一 prereg SHA
   的闭合，均早于 17:24:11 runner start；原 prereg 字节没有修改。
2. `full_merged.tsv` 将未运行通道写成非空默认常量，如 `TNP_flags=/////`、
   `binding_score=50`、`PVRL2_competition_score=50`、`structure_score=60` 和
   `blocker_class=NOT_RUN`。这些必须按 NOT_MEASURED 屏蔽，禁止作为 Docking surrogate、
   阻断标签或绝对 `final_score` 证据。
3. Sapiens 原始 chunk 输出覆盖 720/720，但没有进入 merged hard gate；若后续使用，
   必须按 candidate ID 从原始 Sapiens CSV 显式汇总。

不修改原结果的 correction/semantics receipt 已写入：

```text
reports/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717/
  INDEPENDENT_REVIEW_ADDENDUM_V1.md
  node1_evidence/status/PREREGISTRATION_TIMESTAMP_CORRECTION_V1.json
  node1_evidence/status/FULL_QC_UNRUN_CHANNEL_SEMANTICS_V1.json
  node1_evidence/outputs/INDEPENDENT_FIELD_SEMANTICS_REPLAY_V1.json
```

以上所有新工作继续服务于同一目标：训练一个 sequence surrogate 去逼近独立双受体
Docking 的连续几何，尤其是 `R_dual_min`；它们不把结构 QC、默认分数或 Docking
几何偷换成实验阻断真值。

### 14.9 02:10 CST：Watcher V2 安全退役，V3 已冻结并恢复自动链

对 V2 长驻 watcher 的独立审查发现三个不会立即污染结果、但不能留在
production 的信任缺口：

1. surrogate V2 只固定了 delivery root，没有单独固定 teacher、audit 和 release receipt；
2. V4-F V2 的 test-only 开关可在 canonical root 绕过路径检查；
3. V4-F trust 和 surrogate-completion verifier 使用 Python `assert`，在
   `PYTHONOPTIMIZE=1` 下可被禁用。

V2 两个进程已在 teacher 不存在、训练输出为零、V4-F 预测输出为零时先
`SIGSTOP`、再终止；保留
`phase2_v4_d_v4_f_watcher_v2_stopped_for_v3_trust_fix.json` 作为零污染退役证据。

新的 V3 不修改 V4-D split、`R_dual_min`、trainer、contact schema、模型输出目录
或 V4-F 96-row manifest；只修复执行信任边界：

- canonical gate 现在单独固定 teacher/audit/release/evaluator、embedding 三个
  manifest 和 shard directory；
- production root 上禁止所有 test-only/unfrozen 模式；
- production 信任验证不再使用 `assert`，并对 `PYTHONOPTIMIZE`、`BASH_ENV`、
  `PYTHONPATH` fail-closed；
- launcher 使用 clean environment，不继承 test/path override；
- open teacher 除内部三件套互相匹配外，还必须闭合固定 builder、job manifest、
  evaluator、job-results 和 pose-scores 哈希。

新增的 adversarial 与功能测试共 `18/18 PASS`，包括真实的
`PYTHONOPTIMIZE=1 + bogus hash`、canonical test-only、伪 completion receipt、全部
base/embedding/contact 链、recovery 和 idempotence。冻结哈希为：

```text
surrogate V3 trust anchor: bddee8dc7a303b7239641bf0e74317ee2af8a7509506564714227b5118a6ef11
V4-F V3 trust anchor:      31f7f2cc66fcee3dcf665b76fd2a4985be3ce9d64460dd74956d776e4ee9197e
joint freeze receipt:      fe91ecf994c18c5dbf593860569e9028dc0223cf2be86d3e4b4cda9d1ec14ecc
```

V3 已通过 tmux 长驻恢复：

```text
PID 3864520  WAITING_OPEN_TEACHER
PID 3864523  WAITING_V4_D_SURROGATES
prospective/V4-F labels_read=false
label_paths_accepted=0
production model/prediction output paths created=0
```

同时，V4-F96 的新 SSD Full-QC recovery 已部署到
`/data1/qlyu/projects/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717`，waiter PID
`523095` 只在 Support V4-A720 结构任务完整终止、load 回落后才会启动；当前
`cascade=0`、`outputs=0`。它冻结处理全部 96 条，不用模型重选、不替换失败项、
不读取 V4-F Docking label。此外，V4-F 正式一次性 evaluator 已在任何 label
解封前另起 clean-room 冻结和对抗测试，保持“先预注册、后解封”。

### 14.10 02:23 CST：open258 安全交付和 V4-F one-shot evaluator 已冻结

Node23 的 V4-D 主链继续按原冻结 controller 运行，最新控制器快照为：

```text
1,611 SUCCESS
12 RUNNING
398 PENDING
1 FAILED_MAX_ATTEMPTS
2,022 frozen total
controller PID 265751, load1 about 44.8
```

没有修改并发、seed、受体、Top-8 或失败处理策略。唯一失败记录仍按原状态保留，
不会因下游需要而事后重标。open-teacher postprocessor 仍为 `WAITING_V4D`。

为避免 Node23 完成后再临时手工复制，已预先部署内容寻址的只读交付 watcher：

```text
tmux: pvrig_v4d_open_teacher_delivery_v1
PID: 3899959
state: WAITING_REMOTE
remote state: WAITING_V4D
```

它只有在远端 `COMPLETE`、archive SHA、精确 tar member、258-row teacher
（226 train + 32 dev）、TEST32 sealed、evaluator、builder 和原始聚合闭包全部通过后，
才会原子发布 `by_sha256/<archive_sha>/` 并建立 canonical `current`。14 项对抗测试和
`PYTHONOPTIMIZE=1` fail-closed smoke 均通过；当前 archive 与 `current` 均不存在，
没有读取 test32 或 V4-F 标签。该发布完成后，现有 surrogate V3 会自动继续，无需
人工改路径。

V4-F96 的正式 one-shot evaluator V2 也已在 label 不存在时完成预注册与冻结：

```text
V2 prereg:          05d5727c7568ac9563c75d7ec7b916f172eefd915a728b829d29c25a12079fc3
evaluator:          e5594681e122e38834441f6e6aa53602a673a62615abc55a0cec20bb3650ef17
implementation:     2f43e8cea0bfbafb7a122a2d78c5850cb4f602598405d783b0432e8d3bbb6cf5
runtime anchor:     86066e7508c701d03f3c32e17df38be398455e92643c88f761ca96c109041651
canonical launcher: a3bbe27e59b19c0e38995fd31e2e33b741aafe8aec36a50ad38313fef90440e8
```

正式主指标是 contact-family 对 `R_dual_min` 的 overall Spearman；同时冻结
parent-macro、NDCG、Recall@20%、MAE、uncertainty selective-risk，以及
EF@Top10% point estimate >=3 且 parent-bootstrap 95% CI lower >1。29 项 evaluator
测试和独立 reviewer 均通过（HIGH=0、MEDIUM=0）；本地再联合 open-teacher delivery
重放共 43/43 PASS，优化模式下 evaluator 29/29 PASS。正式 label root、prediction
receipt、one-shot lock 和 evaluator output 仍全部不存在，因此没有发生提前解封。

Node1 的 Support V4-A720 结构全集在同一时间推进到 `610/720` terminal records，
runner 与资源 monitor 正常，V4-F96 Full-QC waiter 仍正确等待，没有手工绕过。Full-QC
只会产出 sequence/developability eligibility，不会产出 Docking label。随后将对全部
Full-QC hard-pass（不替换）运行独立 8X6B/9E6Y Docking，再执行唯一一次正式评估。

Support V3 的既有结论继续保持
`FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY`：它的 deployment coverage
与 nested-validation gate 未通过，所以没有发布 production support table。这个失败
不被修门槛，也不阻塞当前 surrogate 训练，因为 V3 watcher 所需的 frozen contact
features、schema、ESM2 embedding manifest/summary/shards 已经独立存在并通过当前
preflight；Support V3 只保留为 OOD/直接 Docking routing 证据。

### 14.11 02:41 CST：V4-F96 为零 eligible，不能事后修成 formal PASS

Support V4-A720 结构全集已经完整收口，而不是停在进度计数：

```text
NanoBodyBuilder2: 720/720
IgFold:           720/720
both methods:     720/720
unrefined fallback explicitly retained: 23
PDB hash closure: 1,440/1,440
replacement:      0
runner/wrapper/resource-monitor: all terminal, rc=0
```

随后冻结的 V4-F96 Fast-QC 确实处理了全部 96 条，但结果不是“Full-QC 尚未跑”，而是：

```text
Fast-QC hard-pass: 0
Fast-QC hard-fail: 96
Full-QC eligible:  0
Full-QC chunks:    0
downstream Docking eligible: 0
```

四个 frozen parent cluster 各 24 条，全部在同一个 framework 门上失败。ANARCI 的
IMGT/Kabat 编号本身为 96/96 成功，但 `L1_numbering_integrity` 因 parent FR4 末端
分别为 `WGQGTQVTVSL`、`WGQGTQVTVSE`、`WGQGTQVTVS`、`WGQGTQVTVFS`
而全部触发 `fr4_motif_not_typical`。另有 hydrophobic/odd-Cys 风险只影响部分序列，
不是 96/96 的共同原因。

原 V2 runner 在 zero-survivor 情况下仍强制要求 `merge_full`，因此先以
`cascade_stage_not_complete:merge_full` fail-closed；这只是 terminalization bug，不能
被用来绕过真实的 0-hard-pass。新的 V2.1 只修复终态表达，不改变候选、序列、QC 门或
结果：它验证全部 96 条 fast 结果、空 shortlist、无 Full-QC chunk、无 replacement 和
零 label access 后，发布：

```text
schema: phase2_v4_f_holdout96_canonical_eligibility_receipt_v2_1
status: PASS_CANONICAL_ELIGIBILITY_ZERO_HARDPASS
terminal_state: COMPLETE_WITH_ZERO_ELIGIBLE
receipt SHA256: c0ee3aae278836b91f77a3e33aa78823dd0dc6551b5f93e5458763f38c191aa7
```

8 项 zero-eligible 对抗/回归测试全部通过。TNP 对 96 条均明确记录为
`UPSTREAM_FAST_HARD_FAIL_NA`，所有 numeric/flag 字段为空，不做 imputation。

因此当前 V4-F96 的诚实结论是：**formal technical coverage 不足**。不能 trim FR4、
放宽门槛、替换候选或直接 Dock 全 96 来把它修成 PASS；Node23 应保持 0 V4-F jobs，
formal evaluator 也不应消耗 one-shot lock 去计算一个已知不可达的结果。V4-F96 保留为
prospective panel 构建失败/label-free attrition 证据。

下一版正式验证集必须另起版本并在任何 Docking label、模型 prediction 或 model score
介入前，先用冻结 Fast-QC 证明 parent-level eligibility。优先方向是从新的、未进入
V4-D/V4-G/V4-F 的高质量 framework 生成 4 个以上 parent clusters；每 cluster 预留
至少 16--24 条 hard-pass，然后才冻结序列、预测和独立双受体 Docking。旧 V4-F 的
0/96 结果不会被覆盖或删除。

### 14.12 新正式验证集采用 `V4-H-QC96`，已开始 H0/H1

只读、无标签的可行性审计进一步确认，现有 7,087 条候选覆盖的 40 个 parent cluster
已经全部分配：

```text
V4-D train/dev/test: 26 clusters
old V4-F:             4 clusters
V4-G acquisition:     8 clusters
untouched reserve2:   2 clusters
union:               40/40 clusters
```

reserve2 也不能直接解决：`C0019` 有足够 Fast-QC capacity，但 `C0072` 为 0/181，
且两个 parent 本身也达不到正式 evaluator 的至少四个 parent 要求。因此不能从旧库
重新抽 96 条冒充新的 untouched test。

对 Top-200 scaffold 使用严格的 label-free parent gate（未进入 D/F/G/reserve、
ANARCI/VHH/framework/developability/leakage 通过、长度 110--135、FR4 精确
`WGQGTQVTVSS`、2 Cys、无 PTM/free-Cys 风险）后，仍有 67 个新 parent cluster。
已经先冻结完整 12-parent queue，前四个为：

```text
C0162 / PLDNANO_VHH_00231
C0371 / PLDNANO_VHH_00553
C0283 / PLDNANO_VHH_00423
C0148 / PLDNANO_VHH_00211
```

新的版本名固定为 `V4-H-QC96`，不是对 V4-F 的覆盖重跑。执行合同为：

```text
12 parents × 3 patches × 2 modes × 20 = 1,440 label-free designs
→ 全量 frozen Fast-QC
→ 全体 Fast-pass frozen Full-QC
→ parent capacity: Full-QC pass >=24 且每个 patch×mode stratum >=4
→ 按预冻结 queue 取前4个合格 parent
→ 每 parent×stratum 按预冻结 hash 取4条
→ 4 parents × 6 strata × 4 = 96
→ 冻结模型预测后才允许双受体 Docking
```

若 12-parent queue 中少于四个满足 capacity gate，则新版本直接
`FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY`，不减少 parent 数、不临时补位、
不启动 Docking。H0/H1 的实现、测试、工具/输入/config/seed 哈希冻结和 Node1 生成包
现已开始；该分支不占用 Node23，也不读取模型 score、V4-D/test32/V4-F label 或实验
标签。

完整审计写入：

```text
experiments/phase2_5080_v1/reports/
PVRIG_V4_H_QC_QUALIFIED_PROSPECTIVE_HOLDOUT_FEASIBILITY_20260717_ZH.md
SHA256 fe6c351a52360bde3079baac52a3e6beb106bef40118fd36621ebe7261872b0d
```

### 14.13 02:55 CST：V4-F96 已在 Node23 以零作业终态闭合

V4-F96 的 canonical eligibility receipt 已证明 96 条全部 Fast-QC hard fail、
Full-QC hard-pass 为 0。独立版本化的 Node23 V1.1 waiter 随后验证了该 exact receipt，
并走冻结的 zero-eligible 分支结束；没有把“无候选”误写成待运行：

```text
terminal status:                 NO_ELIGIBLE_DOCKING
expected / started Docking jobs: 0 / 0
node23_scientific_work_started:  false
Docking label receipt produced:  false
formal evaluator run:            false
forbidden results/runs/release:  0
bootstrap PID 2069185:           terminal/dead
```

V1 的第一次部署因 shell 只读环境变量冲突在任何科学计算前退出，已原样保留失败证据；
V1.1 通过独立路径和 clean environment 修复部署层错误，没有改变候选、QC 门、受体、
seed、Top-8 或科学策略。V1.1 的 13 项测试、远端 package hash、zero-job receipt、
process closure 和本地 `SHA256SUMS` 均通过。

持久证据位于：

```text
reports/pvrig_v4_f96_dual_docking_v1_1_zero_eligible_20260717/
```

其中 deployment record 状态为
`PASS_REMOTE_TERMINAL_NO_ELIGIBLE_DOCKING`，canonical Node1 receipt SHA256 为
`c0ee3aae278836b91f77a3e33aa78823dd0dc6551b5f93e5458763f38c191aa7`。
正式 evaluator 不会运行，也不会消耗 one-shot lock，因为不存在可评估的 Docking label。

Git 发布范围同时进一步收紧：V1/V1.1 的代码、prereg、freeze、package receipt 和轻量
终态证据保持可见，但含 96 条完整 VHH 序列的两个 prospective manifest 已恢复为
default-deny；本地/远端文件和冻结哈希未删除或改变。

同一时间，V4-D 冻结主链的只读实测快照为：

```text
1,671 SUCCESS
12 RUNNING
338 PENDING
1 FAILED_MAX_ATTEMPTS
2,022 total; controller PID 265751 alive
```

最近吞吐约 96--108 jobs/hour，按当前瞬时速率估计还需约 3.2--3.7 小时。该时间只是
运行估算，不影响冻结协议。open-teacher 仍为 `WAITING_V4D`，没有提前生成 evaluator
receipt、teacher 或读取 test32。

V4-H H0/H1 的执行前预检也完成了一个关键步骤：12/12 新 parent 均用冻结 ANARCI
runtime 编号成功，并据此得到真实 H1/H2/H3 spans；RFantibody、ProteinMPNN 入口和权重
哈希已采集。此时仍为候选 0、GPU 作业 0，必须等 package tests 和 implementation
freeze 完成后才启动真实生成。

### 14.14 03:07 CST：V4-H one-shot 指标在 label-free 阶段提前预注册

为了避免等 V4-H 96 条生成、QC、预测和 Docking 完成后再挑评价指标，已经先建立只含
科学合同、不绑定任何未来结果文件的 V4-H formal preregistration。estimand 明确为：

```text
V4_H_QC_QUALIFIED_NEW_PARENT_DESIGN_UNIVERSE
```

它只评价新 parent、PVRIG 条件化生成且通过冻结 Full-QC 的候选空间；不外推到原始
1,440 条 pre-QC 库、天然 VHH 大库、实验结合或真实阻断。

该 prereg 逐字段复用了 V4-F V2 的既有科学门槛，没有因为 V4-F 的 QC attrition 调低：

```text
primary endpoint:                       R_dual_min
overall contact Spearman:               >= 0.30
parent-macro Spearman:                  >= 0.20
parent bootstrap 95% CI lower:          > 0
nonnegative parent Spearman count:      >= 3
top-quartile Recall at 20% budget:      >= 0.50
EF at Top10%:                           >= 3.0 and bootstrap CI lower > 1
selective-risk MAE reduction:           >= 0.10
high/low uncertainty MAE ratio:         >= 1.25
minimum analyzable / Full-QC hard-pass: >= 64
minimum parent coverage:                4 parents, >= 8 analyzable per parent
```

NDCG 和 MAE 继续是报告指标，不被事后升级为 standalone pass gate。独立测试直接读取并
比较 hash-frozen V4-F V2 prereg，常规和 `PYTHONOPTIMIZE=1` 下均为 11/11 PASS。

当前只新增：

```text
audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json
audits/phase2_v4_h_qc96_formal_evaluator_v1_protocol.md
src/templates/pvrig_v4_h_qc96_formal_evaluator_inputs_v1.json.in
src/test_phase2_v4_h_qc96_formal_evaluator_preregistration_v1.py
```

prereg SHA256 为
`0f0f5b546f71400b50d19e0f3f43cdb7b040c0c2765eef025ae43846df47d8d5`。
未来 H4 manifest、prediction、eligibility、Docking labels 和 evaluator implementation
hash 均保持 `UNBOUND`；V4-D test32、V4-F 和 V4-H label path accepted 都为 0，没有
创建 one-shot lock、formal evaluator 或 formal output。

随后用不修改 V1 字节的 V1.1 prelabel clarification 消除了数量措辞歧义：

```text
2,592 = 12 parents × 6 strata × 12 backbones × 3 MPNN
        raw generator records，可含 exact-sequence duplicates
1,440 = 12 parents × 6 strata × 20
        经 SHA256 exact dedup、冻结 cross-stratum priority 和 H1 hash 选择后的
        exact-unique pre-QC candidates
```

两者都不是 formal estimand。V1.1 clarification SHA256 为
`8746c8739f2ca405c345eb0b22b558f9528a11e12bcf7a8ab23c87ceae915704`；
V1 原 prereg SHA 保持不变，旧新测试合计 17/17 PASS，优化模式 6/6 PASS。

### 14.15 03:30 CST：V4-H H0–H4 冻结自动链已在 Node1 启动

V4-H 的 label-free H0/H1 包已在首次真实生成前冻结。本地和部署包的 20 项对抗测试
均 PASS；冻结记录 SHA256 为：

```text
dab2f0dedc845fe3e415bf77bc7ca3281ed14bcaee1caf0bcacd60ca5fcd9209
```

历史 zero-work preflight 在 tmux 启动前完成，当时检查到的科学产物为 0，12 个 parent、
72 个 generation task、2,592 个 raw generator records 和 1,440 个 H1 exact-unique
目标全部与 prereg 闭合；V4-D test32、V4-F label、Docking、模型预测和实验标签访问计数
均为 0。冻结后远程 17 个包文件逐一 hash replay 通过，未修改冻结字节。

当前真实运行状态为：

```text
Node1 root:       /data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717
tmux:             pvrig-v4h-qc96-v1
pipeline PID:     726070
monitor PID:      726073
generation PID:   726091
parent structures: 12/12 PASS
generation tasks:  0/72 complete（启动后第一批 4 个 RFdiffusion task 运行中）
GPU:               0–3，各约 76–77% utilization
CPU affinity:      0-7 / 8-15 / 16-23 / 24-31，共 32 核
```

这符合用户授权的 Node1 最多一半 GPU 和一半 CPU。冻结 supervisor 会依次执行：

```text
H1: 72 tasks 的 RFdiffusion + ProteinMPNN，2,592 raw → 1,440 exact-unique
H2: 全 1,440 Fast-QC
H3: 全部 Fast-pass Full-QC，不设人工 cap
H4: 按预冻结 4 parents × 6 strata × 4 纯 QC 选出 96
```

由于旧 V4-G 曾在 `Linger=no` 的 Node1 user session 结束时被 SIGTERM，本地另启动了
`pvrig-v4h-node1-keepalive-v1` tmux，仅维持一条带 ServerAlive 的 SSH 登录会话，直到远程
pipeline PID 726070 结束。该 keepalive 不改远程代码、任务、门槛或资源分配，只用于降低
systemd session cleanup 中断长任务的运维风险。机器记录为
`audits/phase2_v4_h_qc96_node1_keepalive_v1.json`，SHA256 为
`b2e2ed5fd5f1137cbac772517682e2b0e163c0f3e117b0346fc6de9203ab9b92`。

任一 stratum 不足 20 个可用 exact-unique 序列，或 Full-QC 后少于 4 个合格
parent，都会 fail-closed，不改阈值、不增补 backbone、不替换候选。部署 receipt
SHA256 为
`250a5cf8975d047c437c448642a32749c34ef4b510495d6e888a423de7f60a94`。

同时，Node23 的 V4-D 冻结 teacher 链继续原样运行：

```text
1,731 SUCCESS
12 RUNNING
278 PENDING
1 FAILED_MAX_ATTEMPTS
2,022 total; controller PID 265751 alive
```

V4-H 当前仍只是新 parent 、PVRIG-hotspot-conditioned 生成与序列/可开发性筛选证据；
它还没有 Docking geometry label，也不是结合、亲和力、竞争或实验阻断证据。

独立对抗审计的最终轮比 tmux 启动晚，因此不能声称“独立最终审计完成后才
启动”。正确的证据表述是：

```text
PASS_HISTORICAL_FROZEN_ZERO_WORK_AND_RUNTIME_INTEGRITY
```

即已保存的两次启动前 zero-work preflight、冻结包/远程 17 文件字节闭合、运行时
禁止路径和资源绑定均通过；审计本身是启动后确认，不倒签 prelaunch 时序。

该审计还发现，冻结后重跑旧测试会调用 builder，并仅因新时间戳将本地 canonical
prereg 镜像从 `fc7aa149...` 改写为 `fdf9da80...`。Node1 和 prepared 冻结包从未漂移；
本地镜像已从 prepared 包按字节恢复为冻结 SHA256：

```text
fc7aa149eedcf11a23484b152dc6431672cdf8a0787396958004c2ffa88a612d
```

单独纠正记录为
`audits/phase2_v4_h_qc96_h0_h3_v1_local_prereg_mirror_reconciliation_20260717.json`，
SHA256 为 `7b66bf45350674251e10ca712192a1429fb8fcb95bb8cd5e0ed49b3aa0bde4d2`。
这是本地证据镜像纠正，没有修改 Node1 冻结包、候选、阈值或运行任务。本版冻结测试不应
再对 canonical path 重跑；后续新版必须先将 builder 输出隔离到临时目录。

### 14.16 03:42 CST：Deep-QC、V4-G 与 Support V3 证据链重新对账

Node1 Deep-QC V3.2 已完成并切换到 content-addressed SSD delivery：

```text
/data1/qlyu/pvrig_migration_20260716/immutable_deliveries/
deepqc100_83bf623afa8ed2364b6432ac5e99d00137d38e251a7393cd4ca1ac4cc04dd5a0
```

100 条的三态 TNP 闭合为 `85 VALID_TNP / 7 TNP_NUMBERING_HARD_FAIL_NA /
8 UPSTREAM_L2_HARD_FAIL_NA`；15 条 NA 的 TNP numeric/flag 字段全部为空，没有插补。
IgFold 为 100/100 `VALID_MONOMER_PREDICTION`，并有 100 个 PDB。recovery receipt 和 path-switch
SHA256 分别为：

```text
54dd54e48468e0884e4d3b0541d7ebda35dd6a5df158986e1d3cae37f6316c49
0dd3f4055d58db69dd428571b54cca55a6d5b1de0afbbe0a2aa1fddab11e5b03
```

V4-G 的旧 V1 目录确实有 false terminal：systemd user session 关闭时，两个 Full-QC
chunk 均中止在 Sapiens；旧 EXIT-only trap 未捕获 TERM/HUP/INT，误将继承状态 0 写成
PASS。该旧 receipt 原样保留，但 execution-completion claim 无效。

有效终态已由既有的独立 V2.1 recovery 提供，不需要再启动一次 Full-QC：

```text
root: /data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716
shortlist:          exact frozen 24; no replacement/reselection
full rows:          24
full hard-pass:     12
full hard-fail:     12
complete chunks:    2/2
recovery receipt:   7b2786274045a45d7b487fa7b9cc4e14d7a2e6215e2cb6286d950e2b9632f356
full_merged.tsv:    f6b0ca1d3de522f6cc3269d498bcd89cd40e73576b81d16291bd81f49b7d6962
full_qc_summary:    255dee0b1bd8800cda1f82fd11f556a3c97aade65f8db0fa88280012c5597942
runtime manifest:   603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d
```

本地 `reports/pvrig_v4_g_node1_full_qc_recovery_v2_1_20260716/SHA256SUMS` 全部通过；
12 条 hard-pass 也与下游 C0154 panel 的 ID/序列精确一致。运行后目录新增了 14 个
`__pycache__/*.pyc`；它们不在冻结 86-file manifest 内，不影响已绑定文件的结果，但因此
不应把运行后的整个 runtime directory 称为完全不可变文件集。

本机 RTX 5080 的 Support V3 V2 也已终态对账：3,000 条 null ESM2、3-seed contact
和四类 null gate 均完成，但 nested validation 和 deployment coverage 未达预注册门槛：

```text
nested overall: 0.5885 < 0.8
nested min-parent: 0.1538 < 0.6
IN_DOMAIN: 1,733 / 6,861 = 0.2526 < 0.6
```

因此它正确地 fail-closed，没有发布 production support table，也不应放宽 gate 或把
`NEAR_DOMAIN` 重标为 `IN_DOMAIN`。它仍可用于 research ranking 和 direct-Docking routing，不是
Docking geometry、结合或阻断标签。
