# V2.21 EF5-targeted plan 独立审查

## 审查结论

```text
CONDITIONALLY_APPROVE_DIRECTION
NOT_READY_FOR_PREREGISTRATION_FREEZE
NOT_READY_FOR_IMPLEMENTATION_FREEZE
NO_V2.21_EXECUTION_AUTHORIZED
NO_TRAINING_AUTHORIZED
```

V2.21 的主方向是合理的：把 contact 因果验证、多 seed、严格双层 compact stack、Top-K rank head 分开，并把 `R_dual_min` surrogate 与 binding/Kd/实验阻断严格区分。当前计划也正确禁止使用 global OOF 作为 meta-train、禁止读取 prospective labels，并要求 whole-parent outer/inner 隔离。

但当前 `PREREGISTRATION_DRAFT.json` 仍包含 `PENDING`、范围、模糊算法选择和未定义状态转移。它可以作为 master design，**还不能成为可执行 preregistration 或 implementation freeze**。

本审查只读取 train9849、既有 V2.13/V2.17 development OOF 指标、V2.20 preregistration 与 V1.3.3 技术冻结状态；未读取 open-development、sealed/frozen prospective 标签，也未启动训练。

---

## 一、从 EF5=3.08285 到 5.0 的真实难度

冻结集合为 9,849 条、985 个 global Top10% positives，Top5% 预算为 493 条。

| 项目 | hits/493 | precision | recall | EF5 |
|---|---:|---:|---:|---:|
| 当前 L1 | 152 | 0.3083 | 0.1543 | 3.08285 |
| 终极目标的最小整数解 | 247 | 0.5010 | 0.2508 | 5.00963 |
| 四模型 union oracle | 325 | 0.6592 | 0.3299 | 6.5916 |
| expanded union oracle | 346 | 0.7018 | 0.3513 | 7.0175 |

因此还差 **95 hits**。达到目标意味着：

- 从四模型 union 的 325 个可见阳性中正确保留至少 76%；或
- 从 expanded union 的 346 个阳性中正确保留至少 71.4%；
- 相对 L1，必须找回 union 新增阳性的约 49%–55%，同时不让原有阳性被等量挤出。

这不是小幅调参目标。既有严格模型未超过 152 hits；描述性、存在 meta leakage 风险的 fixed-HGB 也只有 163 hits。因此 **单靠再换一个分类头或 loss，直接从 152 到 247 的可信度很低**。更可行的路线是：

```text
高召回、严格 cross-fit 的候选 union
→ 证明新增 contact/uncertainty 信号真正正交
→ 只在 union/hard region 内做强正则二级排序
→ 若仍无 >=10 hits 稳定增量，立即增加独立 multi-seed Docking/contact teacher
```

---

## 二、当前 V2.20 C0/C1 状态：V2.21 尚未满足启动条件

当前存在：

- V1.3.3 technical freeze：`cafbe876e59df793711aeb578417778486223f81325d97ecf2062b5f0fc62519`；
- 独立 Stage-A-only approval：`9ffc4f48d880472eb6c1aef5af04cc668f656bd69b3108a7a1a9ac752cf7d499`。

当前仍缺少：

1. Node1 / Python 3.11.14 exact `102+44=146` tests；
2. 五折 shared-calibration materialize/load-only no-training receipt；
3. 单独的 Stage-B/finalizer/training approval；
4. fresh 5 folds × C0/C1 共 10 arms；
5. paired-fold validation；
6. 9,849-row OOF collection；
7. evaluator 与 frozen core gate；
8. hash-bound valid scientific terminal（PASS 或 FAIL）。

因此当前状态必须是：

```text
STOP_V221_UNSTARTED_WAITING_VALID_V220_SCIENTIFIC_TERMINAL
```

V1.3.3 不得改 V2.20 的 lambda grid 或科学门。其科学终止结果只能决定 V2.21 的预注册分支，不能被追溯解释为 PASS。

---

## 三、正式冻结前的阻断问题

### B1. 重复使用同一 outer OOF 做多阶段选择，存在适应性过拟合

计划依次查看 P1、P2、P3-linear、ElasticNet、HGB、P4-T1、P4-T2 的 outer OOF 结果，并选择是否继续。即使每个模型内部做 nested cross-fitting，反复使用同一 54-parent outer OOF 进行方法选择仍会产生 sequential selection bias。

必须在冻结前二选一：

1. 冻结 alpha-spending / fixed-sequence multiple-testing 规则；或
2. 明确 train9849 所有阶段均为 development evidence，任何最终 EF5=5 声明只允许来自一个完全未触碰的新 prospective Docking cohort。

建议两者同时做。现有计划虽然提到 prospective 验证，但没有冻结 stage-wise alpha、终止后的 claim status 和同一 outer OOF 的重复使用边界。

### B2. `strongest causally valid stage reference` 不够精确

每一阶段必须在执行前写死 reference 身份与选择规则，不能看 outer-test 后选“最强”：

- P1 reference：exact V2.20 C0 或 exact B0，需明确；
- P2 reference：通过 P1 的 exact single-seed arm；
- P3 reference：L1，或 P2 通过时的固定 ensemble；
- P4 reference：只能由 inner evidence 选出的一个固定 P3 candidate。

outer-test 只能评价，不能决定 reference 或 blend。

### B3. P3/P4 的 union oracle gate 可能读取 outer-test truth

`P4_authorization_requires_union_oracle_ef5_gte=5.5` 必须只在每个 outer fold 的 outer-fit/inner evidence 上计算。不得用 outer-test truth 先看 oracle 再决定是否运行 P4，然后仍在同一 outer-test 上报告 P4。

需要冻结：union 的精确成员模型、每个模型的候选百分比、去重规则、pool size、tie-break、fit-only truth access 和无 outer-test label access 测试。

### B4. 多项关键参数仍是模糊词或选择范围

正式 preregistration 中不得保留：

- `bootstrap_seed=PENDING`；
- `LambdaLoss or ApproxNDCG@13`；
- `shallow HGB`；
- `low-weight PairLogit`；
- `few highest-score negative sentinels`；
- `compact_feature_dimension_range=24–40`；
- 未定义的 reliability/CDR3 strata；
- 未给精确值的 parent cap、epsilon、variance ddof、missing policy；
- 未给唯一选择规则的 ElasticNet/HGB 参数集合。

每一个 “or”、范围或 “small/few/low-weight” 都允许事后挑选，必须在 freeze 前变成单值或严格 inner-only selection grid。

### B5. F1–F5 root-cause classifier 仍不可执行

F1 较明确，但 F2–F5 缺精确指标、阈值、字段和 missing-evidence 规则。特别是：

- V2.20 core scientific FAIL 时，Phase1b heldout contact evaluator 可能尚未被授权/生成，F2/F3 证据可能不存在；
- F4 的 “pooled direction positive”“strata difference too large” 未量化；
- F5 的 scalar improvement 未规定最小 Spearman/MAE delta；
- 命中 V2.21-A/B/C/D 后，下一步回到哪一阶段、失败后是否允许进入下一 branch，未形成唯一状态机。

需要冻结纯函数式 dispatcher：输入 terminal schema，输出恰好一个状态；缺字段必须 fail closed，不能把 missing 当 false 后继续挑下一个有利分支。

### B6. P1 causal ablation 细节不足

需冻结：

- contact-label shuffle 是否保持 CDR/target residue marginals 与 contact density；建议 degree/marginal-preserving shuffle，而非全局随机打乱；
- position-only baseline 的容量、输入和训练预算必须与 contact head 匹配；
- target permutation 的 exact seed、置换范围、是否同时置换 graph features/edges/masks；
- conformer swap 的输入/label swap 定义；
- contact 主指标、parent 聚合和 bootstrap 实现；
- 当真实 contact EF5 gain `<=0` 时，`shuffle gain <= 50% of true gain` 的定义与失败行为。

否则 ablation 容易测到 OOD 破坏或 marginal density，而非 target/contact causality。

### B7. P2 的 `Top5 rank agreement` 不应成为 cohort-dependent inference shortcut

单条候选是否位于某个 seed 的 Top5% 依赖当前批次/库规模。100k/150k 生产库变化后，该特征会漂移。

若保留，只允许使用每个 seed 经 **fit-only reference CDF** 得到的 percentile dispersion/consensus；禁止直接使用 outer-test 或生产批次内 Top5 membership。

### B8. reliability 契约自相矛盾

Section 8 说 reliability 只能作为 loss weight；P4 又用 “same reliability stratum” 做 hard-negative sampling。采样也会改变学习分布。

必须明确选择：

- 只允许 weight，不允许 reliability-conditioned sampling；或
- 允许 sampling，但明确其为 train-only control、冻结 bins/fallback，并增加 ablation 和 provenance。

两种写法不能同时存在。

### B9. P4 slate 目标与 global Top5 不完全一致

`slate_size=256, cutoff=13` 是局部约 5%，但最终目标是全体 9,849 条的 global Top5。parent-balanced slate 可能改善 parent 内排序，却破坏跨 parent score calibration。

需要：

- 同时保留 global calibrated scalar anchor；
- ranking head 只输出 residual/rank evidence；
- 固定最终 score 组合与跨 parent calibration；
- relevance threshold 在每个 fit 层级计算：inner-fit→inner-val、outer-fit→outer-test；不能用 inner-val/outer-test truth 定义 threshold；
- 精确处理 10/54 个没有 global Top10 positive 的 parent。

本地数据审计显示 parent size 从 6 到 519，且 10 个 parent 没有 global Top10 positive，因此 parent cap 和 zero-positive fallback 不是实现细节，而是会显著改变目标分布的科学选择。

### B10. P1 失败后的状态转移含糊

文档同时写 `STOP_NO_CONTACT_PROMOTION`、不启动 P2、且 contact 不进入 P3/P4，但没有明确 P3 是否仍可使用 L1+B+M2+C2 继续。

必须冻结唯一 DAG，例如：

```text
P1 FAIL → skip P2/contact addon → P3 base-only
```

或：

```text
P1 FAIL → terminal stop
```

不能执行后再决定。

---

## 四、建议的 EF5 推进架构

### 1. 先将问题正式拆成 high-recall pool 与 precision rerank

当前 union oracle 说明“召回存在、区分不足”。建议冻结两阶段目标：

```text
Stage R: L1+B+M2+C2(+causal contact) 生成高召回 pool
Stage P: 只在 pool 内用 compact OOF evidence 排 493 条
```

Stage R 必须先在 outer-fit/inner evidence 达到固定 oracle/recovery 门；Stage P 不得读取 outer-test truth 决定 pool 定义。

### 2. L1 作为强制 anchor，不让二级模型自由推翻

优先：

```text
non-negative rank stack
或
final_score = alpha * L1_percentile + (1-alpha) * challenger_percentile
```

alpha 只能从冻结小网格在 inner whole-parent CV 选择。HGB 若运行，也应输出 residual/challenger score 后与 L1 固定 blend，而不是直接替代 L1。

### 3. 不要把 HGB 运行绑定为“linear 先 PASS”

严格 nested shallow HGB 可能捕捉 disagreement/contact/uncertainty 的条件交互；linear 不通过不等价于 nonlinear 没信号。建议把 HGB 作为一个预注册 challenger，无论 linear 是否通过都按固定顺序运行一次，但计入同信息族最多三次的停止预算。它不能再用 global base OOF meta-train。

### 4. Contact 的第一目标是证明正交增量，而不是直接承诺 EF5=5

V2.20 frozen calibration 的 ratio 约 0.0005，表明现有 contact 辅助梯度几乎没有达到原 0.05–0.15 目标。若 valid V2.20 terminal 满足 F1，V2.21-A 的价值是恢复可测量 contact signal；之后仍必须通过：

```text
heldout-parent contact > position-only
AND target/contact perturbation causes degradation
AND scalar EF5 has stable incremental gain
```

只有三项都成立，contact summaries 才能进入 stack。

### 5. 设置现实的工程里程碑，但不修改终极门

终极门继续保持 EF5>=5 / hits>=247。建议增加非晋级、仅用于资源决策的里程碑：

- M1：>=162 hits（+10，达到统一增量门）；
- M2：>=187 hits（约 EF5 3.8）；
- M3：>=212 hits（约 EF5 4.3）；
- M4：>=247 hits（EF5 5）。

如果新正交信号只能从 152 提升到 162–170，不应继续在同一 9,849 上枚举更多头；应转向新的 multi-seed teacher。

### 6. 新 Docking 数据应针对 hard region，而非只增加随机样本

若三次同信息族 challenger 均失败，下一批 teacher 优先覆盖：

- L1/B/M2/C2 高分但互相冲突的候选；
- 当前预测 rank 2%–20% 的决策边界；
- 各分数段随机 multi-seed sentinels；
- 当前弱 fold/少数 parent/不同 CDR3 length；
- contact 高、scalar 低，以及 scalar 高、contact 低的冲突样本。

新 teacher 可以进入下一版本训练，但必须保留一个按 parent/source 冻结的 prospective holdout，不能把新增全部数据同时用于调参与评价。

---

## 五、现在即可在本地完成的 prereg/tests/freeze 工作

### A. Preregistration

1. 将 master draft 冻结成 **no-execution protocol freeze**，在 V2.20 terminal 前冻结所有 branch 定义和 dispatcher；
2. 填入 bootstrap seed、tie-break、rounding：Top10 固定 985、Top5 固定 493，按 score 降序、`sequence_sha256` 升序打破并列；
3. 把 P1–P4、F1–F5 写成机器可读状态转移表；
4. 给 F2–F5 填精确阈值、字段和 missing-evidence fail-closed 规则；
5. 固定每阶段 reference identity；
6. 固定 union 模型、pool 百分比、去重、pool oracle 的 fit-only 作用域；
7. 固定所有算法/参数，不允许 “or”、范围和模糊形容词；
8. 绑定 L1 terminal 与 V2.17 union metrics 的 path/hash，而不只抄数值；
9. 绑定 contact teacher、target graphs、M2/C2 artifacts、base runner hashes；
10. terminal 到来后只允许生成一个 **terminal-bound activation receipt**，填写 path/hash/status 和 deterministic branch；不得改方法正文。

### B. Tests

最少应先写并通过：

1. `test_metric_exact_985_493_ties_and_ef.py`；
2. `test_parent_outer_inner_disjoint.py`；
3. `test_split_before_label_access.py`；
4. `test_inner_base_retraining_no_global_oof_meta.py`；
5. `test_fit_only_cdf_and_threshold.py`；
6. `test_union_oracle_never_reads_outer_test_truth.py`；
7. `test_root_cause_first_match_and_missing_fail_closed.py`；
8. `test_stage_dag_single_transition.py`；
9. `test_reliability_fit_only_no_inference_feature.py`；
10. `test_parent_cap_and_zero_positive_parent_policy.py`；
11. `test_contact_shuffle_preserves_frozen_marginals.py`；
12. `test_target_permutation_and_conformer_swap_contract.py`；
13. `test_no_open_sealed_frozen_prospective_access.py`；
14. `test_post_freeze_exact_test_launcher.py`。

所有测试先用 synthetic fixtures；不得为测试读取 prospective labels。

### C. Freeze 分层

建议分三层：

```text
MASTER_METHOD_FREEZE
- 全部 branch、阈值、算法、split/metric code
- no execution authorization

TERMINAL_ACTIVATION_RECEIPT
- 只绑定 valid V2.20 terminal hash
- deterministic 选择 PASS path 或一个 F branch
- 不允许改 method bytes

BRANCH_IMPLEMENTATION_FREEZE
- 绑定唯一执行分支的代码、测试、数据、模型和资源
- 独立 critic approval 后才可训练
```

这比“看完 V2.20 terminal 后再完成 V2.21 细节”更能避免事后选择。

---

## 六、V2.21 的准确启动依赖

按顺序必须全部满足：

1. V1.3.3 Stage-A 在 Node1 exact Python3.11.14 下通过 102+44；
2. 五折 exactly-once materialize/load-only receipt 通过且零训练；
3. 单独 Stage-B approval 和 finalized training launcher；
4. fresh C0/C1 十臂全部完成；
5. paired-fold hash/initial-state/batch/optimizer/calibration closure 通过；
6. 9,849 OOF 行完整、54 parent、5 folds、无重复/缺行；
7. evaluator 与 frozen core gate 技术完成；
8. valid scientific terminal path/schema/hash/status 固定；
9. frozen dispatcher 恰好选择一个 V2.21 path；
10. 对应 branch implementation tests 与 freeze 通过；
11. package 外独立 approval；
12. 才能启动该 branch 的训练。

当前只完成了 V1.3.3 本地 freeze 与 Stage-A-only approval，因此 V2.21 不能启动。

---

## 最终判断

V2.21 应继续，但成功关键不是增加更多 head，而是：

1. 先让 V2.20/V1.3.3 形成有效 scientific terminal；
2. 在结果前冻结 V2.21 dispatcher 与所有模糊参数；
3. 用 fit-only high-recall union + strict nested compact reranker；
4. contact 必须先证明 target-aware causal signal；
5. 同一信息族若只能带来少量 hits，立即投入新 multi-seed Docking/contact teacher。

在现有 9,849 条上，EF5=5 的信号上限存在，但从 152 提高到 247 要求二级模型找回约一半的 union 新增阳性。现有证据不支持靠单纯调 loss/优化器达到这一幅度；**正交 contact/uncertainty 信息和针对 hard region 的新 Docking teacher 才是最有可能的增量来源。**
