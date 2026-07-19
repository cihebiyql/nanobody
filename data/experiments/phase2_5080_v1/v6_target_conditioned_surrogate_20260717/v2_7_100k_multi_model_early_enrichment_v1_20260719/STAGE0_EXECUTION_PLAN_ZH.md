# Stage 0 执行计划（冻结前开发版）

## 输入

- teacher：V2.6 已冻结的 `outer_0_inner_0.tsv`，SHA256 必须同时匹配 V2.6
  `SHA256SUMS`/job graph 已登记的 partition hash；split manifest 中的
  `training_tsv_sha256` 是完整 1,507-row teacher hash，不能误当 partition hash；
- split：`outer_0_inner_0.json`，必须 `open_only=true` 且 `v4_f_test32_access_count=0`；
- embedding：已完成的 full1507 ESM2-650M 与 ESM2-3B pooled cache；
- 只读取 allowlist 列：candidate/sequence/parent/CDR、sample weight、R8/R9/Rdual。

## 防泄漏

1. 路径出现 `v4_f`、`test32`、`outer_test`、`sealed` 时 fail closed；
2. train/score parent 必须完全不相交；
3. embedding candidate 与 sequence SHA256 必须逐条闭合；
4. 所有 scaler/PCA/模型只拟合 train；
5. score truth 只在全部预测写出后用于一次性 open-inner evaluation；
6. 报告中的访问计数固定记录为：V4-F/test32=0、outer-test truth=0、outer-test metrics=0。

## 停止条件

代码、测试、输入哈希、预测、指标和中文报告全部生成；若模型不能优于随机富集，
仍保留结果并停止，不事后改 score split 或标签定义。
