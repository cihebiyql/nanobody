# V2.6 正式训练作业图设计 V1

状态：`DESIGN_ONLY_NONLAUNCHING`

## 1. 目的

解决 V2.5 的协议错配：inner OOF neural 只有 seed 43，而 outer prediction 是 43/97/193 三 seed ensemble。V2.6 的 scalar calibration、contact calibration、meta-head 或 uncertainty 若在单 seed OOF 上拟合后应用到三 seed ensemble，会产生输入分布错配。

V2.6 冻结规则：

```text
进入 calibration/meta 的 neural/contact feature
必须在 inner OOF 和 outer test 使用同一 3-seed ensemble protocol。
```

单 seed inner 结果只允许用于超参数选择和描述性诊断，不直接拟合正式 calibration/meta。

## 2. 不采用 675-job 全网格的原因

直接对 3 lanes × 3 hparams × 5 outer × 5 inner × 3 seeds 做完整网格需要 675 个 inner GPU jobs。大部分计算只是在重复明显不晋级的 lane/hparam，不能提高正式证据质量。

采用两阶段 nested 设计：

1. seed 43 做 inner whole-parent 超参数选择；
2. 只对每个 outer fold 已选择的 H 重放 43/97/193 inner ensemble；
3. 正式 calibration/meta 只读取该 matched ensemble OOF。

超参数选择和 meta 训练仍只使用 outer-train parents，outer-test 不参与任何选择、缩放或拟合。

## 3. Lane 角色

### Primary

```text
F0_SHARED_GATED_NO_RANK
```

- 角色隔离 optimizer/RNG；
- direct R8/R9；
- exact-min inference；
- Huber + dual auxiliary；
- 无 ranking loss；
- 正式主 neural lane。

### Ranking challenger

```text
F1_SHARED_GATED_RELIABLE_RANK
```

- 继承 F0 的 selected H；
- `lambda_rank=0.10`；
- 仅使用预注册可靠 source/tier 的 same-parent pairs；
- 不因 inner pilot 漂亮而替换 F0；
- 只有完整 outer-parent gate 通过才可晋级。

### Dynamics controls

```text
B_SCALAR_ATTENTION_ONLY
E_STRICT_DETACHED_DYNAMICS_CONTROL
```

- B/E 使用 F0 每个 outer fold 的 selected H；
- 用于验证 contact 模块和训练动力学是否提供增量；
- 不参与 posthoc lane picking。

## 4. GPU 作业图

### Stage A：F0 单 seed inner H 选择

```text
3 H × 5 outer × 5 inner × seed43 = 75 GPU jobs
```

每个 outer fold只在其五个 inner validation partitions上选择 H。

### Stage B：F0 selected-H matched inner ensemble

```text
5 outer × 5 inner × seeds(43,97,193) = 75 logical jobs
```

其中 selected-H 的 seed43 checkpoint可从 Stage A内容寻址复用；新增计算最多50 jobs。复用前必须验证模型、split、optimizer、loss、seed和checkpoint hash完全一致。

### Stage C：F0 outer refit ensemble

```text
5 outer × 3 seeds = 15 GPU jobs
```

### Stage D：B/E dynamics controls

每个 control：

```text
5 outer × 5 inner × seed43 = 25 inner jobs
5 outer × 3 seeds = 15 outer jobs
合计40 GPU jobs
```

两个 control 合计80 jobs。它们不为正式meta生成三seed inner ensemble。

### Stage E：F1 reliable-rank challenger

使用F0 selected H：

```text
5 outer × 5 inner × 3 seeds = 75 inner jobs
5 outer × 3 seeds = 15 outer jobs
合计90 GPU jobs
```

### GPU总量

不计可复用seed43：

```text
75 + 50 + 15 + 80 + 90 = 310 unique GPU jobs
```

若F1在预注册前因真实数据pair closure不足而fail closed，则不构建F1作业，GPU总量降为220。

四块4090固定一张卡一个训练job；不得在同卡重叠两个训练进程。调度器只分配GPU 1/2/4/5，并记录每job显存、wall time、return code和输出hash。

## 5. CPU作业

每个outer fold：

1. F0 H selection；
2. F0 inner 3-seed ensemble；
3. R8/R9 positive affine calibration；
4. low-dimensional constrained meta fit；
5. F1/B/E outer ensemble；
6. exact-min validation；
7. parent-macro/source metrics；
8. paired-parent bootstrap。

所有 calibration/meta 参数必须在读取 outer truth 前形成 PRETRUTH receipt。

## 6. Seed/uncertainty规则

- inner和outer正式meta输入都使用43/97/193均值；
- seed std只有在inner/outer同协议且inner held-out parents上校准后才能作为challenger feature；
- 第一版primary不将seed std输入meta；
- B/E单seedinner结果不得用于拟合应用到三seedouter的calibrator；
- contact probability只有在held-out parent上改善candidate-balanced Brier/ECE后才允许称为probability，否则称contact score。

## 7. Ranking接受门

F1只可在以下条件全部满足时替换F0：

- eligible pair方向与exact-min定义一致；
- V4-D与V4-H source-specific Rdual Spearman均不退化；
- overall Rdual Spearman改善且paired-parent bootstrap 95% CI lower > 0；
- MAE/RMSE不超过冻结noninferiority界限；
- within-parent Spearman/NDCG改善；
- 至少4/5 outer folds方向一致；
- parent-macro指标不退化；
- 未读取V4-F/test32。

## 8. Softmin规则

- 对外推理和全部指标始终使用exact min；
- scalar dual auxiliary可保留smooth surrogate，但必须单独报告其与exact-min的误差；
- rank loss默认使用可微exact `torch.minimum`，避免normalized softmin改变pair方向；
- 若保留softmin rank challenger，eligible pair sign-flip必须 `<=1%`，否则fail closed。

## 9. 启动前硬门

- real1507 rows=1507，parents=31，outer folds=5；
- split/candidate/sequence/teacher hashes闭合；
- optimizer ownership无重叠；
- Node1 CUDA 20-step B/E trajectory max delta <=1e-7；
- gradient accumulation下每role的step/clip计数正确；
- F shared contact gradient cap每step<=0.25；
- exact-min violations=0，tol=1e-12；
- V4-F/test32 access=0；
- live V2.5 301-job graph未被修改；
- formal prereg、job graph和evaluator在首个outer结果前冻结。
