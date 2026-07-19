# V2.5 重复 seed Docking 噪声诊断计划

## 目标

只使用已经完成、可公开用于开发的 V4-D `OPEN_TRAIN` 与 V4-H research Docking 重复 seed，按候选为统计单位量化：

- `R_8X6B`、`R_9E6Y`、同 seed `R_dual_min=min(R8,R9)` 的 test-retest Spearman；
- ICC(1,1) 风格的单次测量可靠性；
- 候选内 seed 方差、分数区间相关方差、来源/重复层级差异；
- 单 seed 对另外两个 seed 均值的经验可预测上限，以及由 ICC 推导的均值标签上限。

## 证据边界

- 重复 seed 是同一候选的技术重复，不作为独立训练行。
- V4-D 只允许 `model_split=OPEN_TRAIN`；不读取 `OPEN_DEVELOPMENT` 或 `PROSPECTIVE_COMPUTATIONAL_TEST` 的 raw Docking result。
- V4-H 是自适应补 seed：2/3-seed 子集受首 seed 排名选择影响，不能当作全分数区间的无偏重复样本。
- 输出是计算 Docking 几何的测量噪声诊断，不是实验阻断、结合、Kd 或 Docking Gold。

## 实施顺序

1. 在 Node23 从 raw `job_result.json` 仅提取允许候选的 per-seed scalar，绑定 job/result SHA256。
2. 本地验证候选级中位数与既有 V4-D/V4-H terminal teacher 完全一致。
3. 生成候选级方差、seed-pair reliability、score-bin variance 与 empirical noise ceiling。
4. 运行合成单元测试、真实来源闭合检查与 SHA256 closure。

## Fail-closed 条件

- 出现 V4-D 非 `OPEN_TRAIN` candidate；
- per-seed `(candidate,receptor,seed)` 重复或缺少配对 receptor；
- 重算中位数与 terminal teacher 不一致；
- raw result identity/job hash/protocol hash 不闭合；
- 任何输出出现非有限数，或 `Rdual != min(R8,R9)`。
