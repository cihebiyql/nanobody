# Softmin / exact-min 数学诊断 V1

本诊断只读取开放的 1,507 条 teacher scalar，未读取任何 outer model metric 或 V4-F/test32。

结论：`tau=.02` 的 normalized softmin 相对 exact-min 有约 0.00886 的平均上偏和 0.01386 的最大上偏。全体同-parent pair 中可出现方向翻转；在真实 teacher 上使用冻结 `delta_noise=.019614956149` 过滤后未观察到翻转，但预测值的 receptor gap 会变化，因此 V2.6 rank loss 仍应直接使用可微的 `torch.minimum`。Normalized softmin只保留为 scalar dual auxiliary及诊断，不参与正式 pair 方向定义。
