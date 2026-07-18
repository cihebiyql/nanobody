# V2.4 supervised1507 数据契约

本目录以不可变的 `materialized_v1_1/v6_supervised1507.tsv` 为候选与结构特征基底，生成新的 V2.4 开发监督表：

- V4-D 226 条：保留原多 seed `R_8X6B`、`R_9E6Y`、`R_dual_min` 与不确定性，可靠性 tier=A。
- V4-H 1281 条：用 `final_adaptive_seed_ranking.tsv` 的最新 8X6B/9E6Y median 更新两个连续标签，并用十进制精确 `min` 重算 `R_dual_min`。
- V4-H 可靠性：`DUAL_3_SEED -> A`、`DUAL_2_SEED -> B`、`DUAL_1_SEED -> C`；39 条 `TECHNICAL_INCOMPLETE` 不进入监督表。
- 固定开发权重：A=1.0、B=0.8、C=0.65。该权重仅表达 Docking 技术重复可靠性，不是生物学置信度。
- 31 个 parent cluster 必须保持 outer-fold 隔离；seed 只能来自 917/1931/3253；失败 seed 禁止插补。

## 证据边界

输出仅是候选级独立双受体计算 Docking 几何监督，不代表结合、Kd、竞争实验、实验阻断、Docking Gold 或正式验证。

构建器只读取 DATA_CONTRACT 中列出的开放开发文件；不读取 V4-F/test32、sealed pose、sealed result 或 prediction metrics。

## 运行

见实际物化目录中的 receipt。所有输入先做 SHA256 闭合，输出同时生成 TSV、JSON receipt 与 `SHA256SUMS`。
