# Top200 公共四 seed 补齐部署

- 候选：106
- 补跑：seed 42、3047
- 受体：8X6B、9E6Y
- 作业：424
- bxcpu：2 节点，每节点 16 个并行 HADDOCK 作业，每个作业 4 CPU
- 冻结协议核心：
  `8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3`

提交脚本必须先验证 `AGGREGATION_COMPLETE.json`，然后执行真实
HADDOCK smoke、2 节点 array 和终态审计。结果通过本地两路有界 spool
回传 Node1。

技术失败记为 NA，不得视为负样本。Docking 只表示计算几何代理。
