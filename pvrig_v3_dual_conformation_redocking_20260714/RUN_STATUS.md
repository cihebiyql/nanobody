# V3 运行状态

- 项目：`pvrig_v3_dual_conformation_redocking_20260714`
- 当前阶段：`IMPLEMENTING_AND_FREEZING_PROTOCOL`
- 评价器：`NOT_READY`
- 下一批 P2/P3/P4 生成：`LOCKED`
- 本地目录：`/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714`
- node1 目录：`/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714`

## 已确认

- 旧 9E6Y 跨参考评分存在残基编号映射风险；V3 统一使用 UniProt Q6DKI7 编号。
- 旧 scorer 读取 `HETATM`；V3 只读取20种标准氨基酸 `ATOM`。
- 固定矩阵为128候选 + 47协议回归控制，2构象，3显式 seeds，共1050任务。
- HADDOCK3 node1 版本为 `2025.11.0`，支持四个模块的显式 `iniseed`。
- node1 HADDOCK是CPU任务，控制器必须按load降载和低优先级运行。

## 尚未完成

- [ ] 标准化并冻结 8X6B/9E6Y 参考结构；
- [ ] 生成并冻结128候选和47控制；
- [ ] 生成1050唯一任务及最终协议锁；
- [ ] 本地全部回归测试和协议验证通过；
- [ ] node1 双构象 smoke test 通过；
- [ ] node1 全量后台任务启动；
- [ ] 47控制稳定性门禁完成；
- [ ] 写出 `EVALUATOR_STABLE.json: status=PASS`。

在最后一项完成前，不允许根据 P2/P3/P4 富集结果生成下一批序列。
