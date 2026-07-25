# Top1 候选 P1MCPUFP__CPUFP500K_0107__00292：机制与多 seed 复核

## 结论

- **界面机制层面：通过。** 在代表 pose 中，候选 VHH 接触了天然 PVRL2–PVRIG 界面的绝大部分蛋白残基，并且由 CDR 主导；这与“占据 PVRL2 功能界面实现空间阻断”的阳性机制规则一致。
- **四 seed 稳定性层面：存在重要不确定性。** 初始 Final50/Top10 表仅保留旧路线 2 个 seed（917、1931）的结果。后续补齐为 4 seed × 2 构象后，8/8 job 虽全部成功、4/4 seed 均有双构象 blocker-like 支持，但只有 2 个 seed 为 `STRICT_A`，另 2 个为 `SUPPORTED_AB`。全 common4 诊断 rank 为 **188/200**，而不是初始 Top200 rank=1。
- 因此，该候选可保留为“**界面机制合理、但多 seed pose 稳定性较高不确定性**”的候选；不得再描述为“4/4 strict-A 稳定 Top1”或已验证实验阻断。

## 残基接触复核（重原子 4.5 Å；先按PVRIG序列对齐，避免不同构建残基编号偏移）

|参考构象|候选接触的天然PVRL2界面残基覆盖|结论|
|---|---:|---|
|8X6B|18/22 个天然PVRL2界面蛋白残基|覆盖主界面：S33、L34、T36、N43、G44、V52、H54、R57、G58、R60、K97、A99、S100、F101、P102、E103、G104、S105|
|9E6Y|19/22 个天然PVRL2界面蛋白残基|覆盖主界面：S31、L32、T34、N41、G42、A43、T47、V50、H52、R55、G56、R58、K95、A97、S98、F99、P100、G102、S103|

代表 pose 的接口质量：

|构象|PVRIG–VHH 接触原子对|CDR3 接触残基数|CDR 总接触比例|PVRIG–VHH <2 Å物理 clash|
|---|---:|---:|---:|---:|
|8X6B / seed917|244|9|0.905|0|
|9E6Y / seed1931|324|9|0.826|0|

这支持“CDR 主导、覆盖天然配体界面、无 PVRIG–VHH 硬穿插”的结构机制判断。

## 原始 2 seed 与补齐后 common4 的区别

|指标|初始 Final50/Top10 主表|Top200 seed completion 复核表|
|---|---:|---:|
|seed|917、1931|42、917、1931、3047|
|构象×seed job|4|8/8 SUCCESS|
|strict-A representative jobs|4/4（仅旧的两 seed）|4/8|
|supported-AB representative jobs|4/4|8/8|
|seed consistency|1.000（2 seed 子集）|0.500（完整4 seed）|
|blocking consensus|98.80|94.39|
|pose robustness|96.00|83.64|
|诊断排名|初始 Top200 rank 1|common4 diagnostic rank **188/200**|

`STABLE_STRICT_4_OF_4` 是补 seed 聚合器的类别标签；其“strict”包含 `STRICT_A` 与 `SUPPORTED_AB` 的双构象支持，不应误读为 4 个 seed 都是 `STRICT_A`。

## 与阳性机制规则的关系

候选 parent pose source 是 `case02_pos_01_PVRIG-151_HR151`，但本候选的最近阳性 CDR identity 最大为 0.571（CDR1=0.30、CDR2=0.571、CDR3=0.421），满足比赛 <0.80 的新颖性要求。因此它不是 HR151 序列复制。

现有证据验证的是：候选符合从阳性阻断 VHH 提炼出的 **功能界面占据 / CDR 主导 / 双构象遮挡** 规则；它不等于已由 BLI、Kd、竞争ELISA或表达/纯度实验证实。

## 证据文件

- 初始 Final50：`../../final50/final50_ranked.tsv`
- 初始 Top10：`../../final50/top10_priority.tsv`
- Top200 common4 候选级复核：`TOP200_COMMON4_CANDIDATE_EVIDENCE_200.tsv`
- 8个 job 原始结果：`TOP200_COMMON4_JOB_RESULTS_1600.tsv`
- 代表 pose 静态复核：`../../static_review/STATIC_POSE_METRICS.tsv`
