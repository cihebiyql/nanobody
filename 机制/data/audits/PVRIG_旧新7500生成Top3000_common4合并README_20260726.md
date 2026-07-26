# PVRIG 旧/新两批7500 + 生成Top3000：common4 合并榜

- 冻结的旧 Final50 未被修改。
- `combined_common4_complete_3185_geometry_ranked.tsv`：200 条既有 common4 Top200 + 2,985 条生成候选完整 8/8 的合并几何榜。
- `combined_common4_qc397_geometry_ranked.tsv`：上述中已有 200 条完整QC + 生成候选中 197 条整合QC合格者的可进入后续静态复核池。
- 排序仅使用跨队列一致的 4 seed × 2 构象 docking 几何证据；不使用两路线各自训练/预筛模型分数进行跨队列比较。
- 该表不是新的比赛 Final50：新增候选尚未走与旧 Top200 相同的 static-review → Top80 → Final50 选择桥接。
