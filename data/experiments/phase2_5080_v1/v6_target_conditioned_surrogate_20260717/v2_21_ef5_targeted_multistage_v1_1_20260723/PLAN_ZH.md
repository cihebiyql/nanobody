# V2.21 v1.1：以 EF5=5 为目标的严格多阶段方法

## 当前状态

```text
DRAFT_MASTER_METHOD
NO_TRAINING_AUTHORIZED
WAITING_VALID_V2.20_SCIENTIFIC_TERMINAL
```

目标是在固定 train9849 开发集上，用全局真实 `R_dual_min` Top10% 作为阳性，从预测 Top5% 的 493 条中找到至少 247 条阳性：

```text
EF5 >= 5.0
hits >= 247 / 493
precision >= 0.50
```

当前严格 L1 参考为 152 hits，`EF5=3.08285`，还差 95 hits。四模型 L1/B/M2/C2 Top5 union 包含 325 个真阳性，说明最大瓶颈是对 high-recall pool 的二次精排，而不是继续无限增加普通分类头。

## 不可越过的启动门

V2.21 只能在 V2.20 V1.3.3 完成以下证据后激活：

1. Node1 Python 3.11.14 下 exact `102+44=146` tests PASS；
2. 5-fold shared-calibration materialize/load-only PASS；
3. 独立 Stage-B 训练授权；
4. fresh 5 folds × C0/C1 共 10 arms 技术闭合；
5. 9,849-row OOF、evaluator、core gate 闭合；
6. 发布 hash-bound scientific terminal，状态只能是 PASS 或 FAIL。

当前 Node1 watcher 只有 Stage-A 权限，不得因为计算资源空闲而提前启动 V2.21。

## 固定评价契约

- 行数：9,849；阳性：985；预测预算：493。
- 主指标：`EF_true_top10_at_budget5`。
- 并列：分数降序，`sequence_sha256` 升序。
- split：whole-parent outer 5-fold；meta 训练必须在 outer-train 内再做 whole-parent inner cross-fitting。
- 严禁用 global OOF 直接训练并在同一批行评价 meta-head。
- 所有 CDF、threshold、union-oracle 只访问 fit-side labels；outer-test 只做一次评价。
- train9849 的所有顺序尝试只是 development evidence；EF5=5 的最终广泛声称需要新的 untouched prospective Docking cohort。

## 执行 DAG

```text
valid V2.20 terminal
  PASS -> P1 contact causal
       -> P2 multi-seed uncertainty（P1 fail 则跳过）
       -> P3 strict nested L1+B+M2+C2 compact stack
       -> P4 parent-balanced rank residual（仅 fit-only union oracle >=5.5）
       -> development terminal

  FAIL -> deterministic F1..F5 first-match dispatcher
       -> 只激活一个新版本分支，不追溯修改 V2.20
```

`src/protocol_v1_1.py` 已将以下契约写成纯函数并由 41 个 synthetic tests 锁定：

- exact EF5 与 SHA256 tie-break；
- fit-only CDF；
- exact L1/B/M2/C2 Top5 union；
- F1–F5 first-match/fail-closed dispatcher；
- 单一转移 DAG；
- parent-normalized reliability loss weight；
- compact feature 显式 allowlist 和 Docking-label 泄漏拒绝。
- outer/inner whole-parent 精确覆盖、不相交和每个 inner-validation 仅出现一次；
- fit-only Top10 threshold 与 union-oracle label-access firewall；
- equal parent cap 与 zero-positive parent 高分 negative sentinel fallback；
- 同时保持每个 VHH row marginal、每个 target column marginal 及总 density 的 contact shuffle；
- target-residue permutation 及 8X6B/9E6Y 整体 conformer swap 的闭合映射；
- prospective/sealed/open-development path 和特征的 access-before-read 拒绝。

## 主方法

### P1：联系与靶标因果性

必须同时证明：

- heldout-parent contact 超过 position-only baseline；
- target-residue permutation 使 contact 下降至少 10%；
- contact-label shuffle 不产生有利 EF5 假增益；
- conformer swap 使 receptor-specific MAE 恶化至少 2%。

P1 失败后不使用 contact addon，但仍可进入 P3 base-only。

### P2：多种子与不确定性

种子固定为 `43/917/1931`。只允许用 fit-reference CDF percentile dispersion，不允许将当前 cohort 的 Top5 membership 作为输入。相对固定 P1 single-seed reference 需：

```text
ΔEF5 >= 0.20
hits gain >= 10
paired whole-parent bootstrap 95% CI lower > 0
```

不通过则 P3 只使用 single-seed 证据。

### P3：high-recall union -> compact precision stack

基础模态固定：`L1/B/M2/C2`。每个模型只输入 R8、R9、exact min、receptor gap 和 fit-CDF percentile，再加少量 disagreement、通过 P2 的 uncertainty、通过 P1 的 predicted contact summaries。

顺序固定：

1. non-negative linear stack；
2. ElasticNet residual challenger；
3. depth-limited HGB residual challenger。

三者都必须用 inner-OOF meta features；最终分数保留 L1 percentile anchor，不允许二级模型自由推翻 L1。

### P4：Top-K rank residual

只在每个 outer fold 的 fit-side union oracle EF5 都至少 5.5 时启动。ranking head 只输出 residual/rank evidence，必须与 global calibrated scalar anchor 融合，以避免 parent-balanced local slate 破坏跨 parent 校准。

## 新 Docking teacher 回流

新数据不只选当前高分，而覆盖：

- L1/B/M2/C2 分歧大的候选；
- 预测排名 2%–20% 决策边界；
- 高/中/低分层的随机 multi-seed sentinels；
- contact-high/scalar-low 和 scalar-high/contact-low 冲突项；
- 弱 fold、稀有 parent、不同 CDR3 length/source/method。

最新 C2 Top7500 与正在运行的旧 priority/S0 Top7500 只交叉 1,280 条；必须完成另外 6,220 条的补跑才能对最新 Top7500 做整体 precision/enrichment 评估。

## 实际停止规则

- 同信息族最多 3 个 challenger；若都不能稳定增加至少 10 hits，停止枚举模型头，转向 hard-region 新 Docking teacher。
- 里程碑 M1/M2/M3/M4 仅用于资源决策：162/187/212/247 hits；不得降低最终 EF5=5 目标。
- 任何技术缺失、非有限值、split 交叉、特征越界或未冻结参数都 fail closed。
