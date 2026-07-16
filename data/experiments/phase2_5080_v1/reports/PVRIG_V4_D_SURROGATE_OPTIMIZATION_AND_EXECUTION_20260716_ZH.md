# PVRIG V4-D Surrogate 优化与执行路线

**更新时间：** 2026-07-16 17:05 CST
**主目标：** 用便宜的 VHH 序列模型逼近独立 8X6B/9E6Y Docking 的连续阻断几何结果，用于大库前筛。  
**证据边界：** 模型输出只是 computational docking-geometry surrogate，不是 PVRIG 结合概率、Kd、PVRL2 competition 或实验阻断真值。

## 1. 当前结论

现在最大的瓶颈不是 GPU，也不是网络太小，而是：

1. 独立双受体 Docking teacher 尚未完成；
2. 当前训练集只有 226 条、20 个 parent clusters；
3. 7,087 条候选中，2,643 条被局部标记为 `IN_DOMAIN`，但当前 support 总门禁仍为 FAIL；
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

2026-07-16 17:05 CST 快照：

```text
2022 total jobs
616 SUCCESS
12 RUNNING
1393 PENDING
1 FAILED_MAX_ATTEMPTS
```

分层情况：

```text
controls: 282/282 SUCCESS
OPEN_TRAIN: 298 SUCCESS + 12 RUNNING + 1045 PENDING + 1 FAILED_MAX_ATTEMPTS
OPEN_DEVELOPMENT: 36 SUCCESS + 156 PENDING
PROSPECTIVE_COMPUTATIONAL_TEST: 0 touched
```

Controller PID 265751 存活，HADDOCK/CNS 正在运行。当前不修改 controller、scratch、并发数或 job order。
最近 60 分钟完成 106 个 SUCCESS job；按当前速率粗略估计剩余时间约 13–14 小时。这只是运行时间估计，不是完成承诺。

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

当前 V4-F 独立安全复审结论为 `BLOCK`，不得开启正式预测冻结或 Docking gate。第一轮四个已知 High 的修复和定向测试已完成，但 reviewer 又发现三个 High：production shell gate 可用任意 `PYTHON`/freezer override 绕过 verifier；verifier 在 PASS 前未重验 receipt/prediction/audit 当前输出；receipt 可绑定到“磁盘上已替换的新源码”而非实际运行的已加载代码。另有一个 Medium：watcher 将已存在的零字节/不可读 receipt 错分为 missing。当前修复任务已启动；watcher 继续停止，不发布生产预测，不读取 V4-F Docking label。

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

1. V4-D 2022 jobs 继续运行；17:05 快照为 616 SUCCESS / 12 RUNNING / 1393 PENDING / 1 FAILED_MAX_ATTEMPTS，不干扰远程 controller；
2. Node1 Deep-QC 已受控暂停并迁移到 `/data1` 本地 SSD，当前禁止手工 `SIGCONT`；V4-F watcher 继续等待上游；
3. residue/contact V3 已完成并验证；
4. contact schema V2 已冻结；
5. contact/fusion trainer 完整测试 9/9 PASS，deployment scorer + watcher 13/13 PASS；
6. open258 teacher-ready 训练 watcher 已完成并正在运行，当前为 `WAITING_OPEN_TEACHER`；teacher receipt 到达后将自动运行基础、embedding 和 contact/fusion 模型；
7. deployment scorer 当前为 `WAITING_FROZEN_MODEL_ARTIFACTS`，已确认不会提前发布任何 7087 分数；
8. V4-F 第一轮对抗测试 16/16、联合回归测试 83/83 和真实 96 条 label-free preflight 均 PASS，但独立 reviewer 结论仍为 BLOCK；新发现的 3 High + 1 Medium 正在修复，期间不开启正式预测冻结或标签 unseal。

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

17:05 快照中，还没有发现已发布的 remainder-only resume 脚本、最终 delivery 回同步脚本或 100-row merge receipt，因此迁移仍不能标记完成。收口必须同时满足：

1. 不对旧 NFS 进程树就地发送 `SIGCONT`；旧进程只作暂停现场和可追溯证据；
2. 新建并审计 remainder-only 续跑脚本：仅复用已通过 JSON 解析、candidate identity 和 SHA256 验证的 TNP 结果，只对缺失/无效条目重跑，并输出 reused/rerun 清单与 receipt；
3. 完整 IgFold 阶段在 SSD 运行并使用 4 张 GPU；单条 `--gpu 0` smoke 只是运行时验证，不代表完整结构预测已启动；
4. 最终 delivery 要么通过原子回同步发布到现有 watcher 路径 `/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716`，要么在恢复前显式更新并哈希绑定所有轮询路径；
5. source-target parity、TNP smoke、IgFold smoke、100-row merge 和最终 delivery receipt 全部 PASS 后，才能将 Node1 Deep-QC 标记为完成。

### 11.3 修复 V4-F 安全门禁

1. 锁定 production shell gate 的 canonical Python 和 freezer verifier，明确禁止任意环境变量替换信任根；
2. verifier 在返回 PASS 前重新校验 receipt、prediction 和 audit 的当前哈希，并增加最后一次检查时篡改输出的对抗测试；
3. 将 freezer 自身和直接依赖的实际执行代码绑定到不可变/内容寻址快照，阻断 import 后原子替换源码的 provenance 冒充；
4. watcher 只将不存在的 receipt 视为 WAITING；已存在但为零字节、非普通文件或不可读的 receipt 必须进入 `BLOCKED_INVALID_PREDICTION_RECEIPT`；
5. 修复后重跑对抗测试和联合回归，再交给新 reviewer；只有 reviewer `PASS` 且 V4-D 三路正式 artifact 到位后，才能重启 watcher。

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

## 12. 停止条件

V4-D 当前版本在任一情况下应停止扩展：

- remote evaluator 不是 PASS；
- open258 teacher 行数、split 或 hash closure 不一致；
- 发现 test raw label 进入特征、调参或排名路径；
- 所有候选模型都不能超过最强 shortcut；
- uncertainty 不能识别高风险预测；
- V4-F 未见 parent 结果明显失效。

这些失败都应当触发“增加独立 teacher 和 parent 覆盖”，而不是临时改门槛或换更大网络。
