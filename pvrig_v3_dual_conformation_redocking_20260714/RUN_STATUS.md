# V3 运行状态

- 项目：`pvrig_v3_dual_conformation_redocking_20260714`
- 更新时间：`2026-07-14 14:47 Asia/Shanghai`
- 当前阶段：`DEPLOYED_SMOKE_WAITING_FOR_NODE1_LOAD_GATE`
- 本地协议验证：`PASS`
- node1 协议验证：`PASS`
- 评价器稳定性：`NOT_READY`
- 下一批 P2/P3/P4 生成：`LOCKED`
- 本地目录：`/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714`
- node1 目录：`/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714`

## 冻结标识

- `protocol_core_sha256`: `e027143c22712b43d973709b278519a0cf414a9de182e094ea0cd8470d8295b8`
- `protocol_lock_sha256`: `0f2d5eeafdc75949f4e422a091248ba33ff33c984f993dbba955827c71eb7daa`
- `PROTOCOL_LOCK.json` file SHA256: `a6740daabdc481a096cbc83ad17405f0a0b55bd8f7f412af63e23b9c5fe6a91e`
- `docking_jobs.tsv` SHA256: `e159027b23e76b041a02f3034a204379053f9d0780e2f8bdfc599d431c1a425e`
- `candidates_128.tsv` SHA256: `5e536f7178cb214102aef684c65fc97b4996d3b83de5b6f506ad2f9bf8e66c78`
- `candidate_monomers_manifest.tsv` SHA256: `db29dcb9047c7e0514a359077f380d53fedd0127c879a939ab8ebad812c5c0df`

## 已完成

- [x] 修复跨构象残基编号漂移：两个 PVRIG 均使用 UniProt Q6DKI7 编号和链 `T`；
- [x] 排除水、EDO、NAG 等 `HETATM`，scorer 只读取标准氨基酸重原子；
- [x] 将23个唯一界面位点固定拆为12个 AIR anchor和11个 scoring holdout；
- [x] 冻结128候选、47控制和全部175个单体 PDB；
- [x] 生成 `175 x 2 x 3 = 1050` 唯一独立对接任务；
- [x] 生成4任务 smoke 清单：HR-151与rank-1候选，各自8X6B/9E6Y、seed 917；
- [x] 24/24 本地回归测试通过；
- [x] 本地与 node1 `validate_protocol.py` 均为 `PASS`；
- [x] 部署文件与本地 `PROTOCOL_LOCK.json` 文件 hash 一致；
- [x] node1 后台 `smoke -> verify -> full` 编排器已启动。

## node1 当前现场

- 后台编排器 PID：`4062901`；smoke controller PID：`4062903`；
- 启动时 load1 约 `65.2`，协议规定 `load1 >= 62` 时并发为0；
- 因此当前4个 smoke 任务均为 `PENDING`，控制器正在等待，不会抢占节点现有高负载任务；
- load1 下降后，控制器会自动运行 smoke；只有4/4 均为 `SUCCESS`、selected model非空、job hash匹配且每个pose同时具有8X6B/9E6Y评分，才会写 `SMOKE_VALIDATION.json: PASS` 并自动进入全量1050任务。

## 尚未完成

- [ ] 4/4 node1 smoke任务通过；
- [ ] 自动进入1050任务全量队列；
- [ ] 每个实体、每个构象至少2/3 seeds成功；
- [ ] 47控制的漂移和阈值敏感性报告完成；
- [ ] `reports/EVALUATOR_STABLE.json` 变为 `status=PASS`。

在最后一项完成前，`scripts/guard_next_generation.py` 始终非零退出，不能根据 P2/P3/P4 富集结果生成下一批序列。
