# Docking compute expansion v1

- `admin` 未使用；`node20` 因高负载未使用。
- node17、node18、node19 各冻结 2,000 个 Docking job，启动并行度 P4。
- node21 冻结 2,000 个 Docking job，启动并行度 P3。
- `external_server2000_jobs.tsv` 另行冻结 2,000 个 job（1,000 个完整双受体 entity-seed 对），尚未启动，也尚未制作便携运行包。
- 所有分片均来自冻结的 `docking_jobs.tsv`，与 node25 分片互斥；冻结时无已有状态文件。
- 这些只是计算调度分片，不改变协议、job hash、评分标签或技术失败为 NA 的语义。

远端权威根目录：

`/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720`
