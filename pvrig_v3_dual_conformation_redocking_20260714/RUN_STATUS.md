# V3 运行状态

- 项目：`pvrig_v3_dual_conformation_redocking_20260714`
- 更新时间：`2026-07-14 19:59 Asia/Shanghai`
- 当前阶段：`SMOKE_PASS_FULL_QUEUE_RUNNING_LOAD_AWARE`
- 本地协议验证：`PASS`
- node1 协议验证：`PASS`
- 评价器稳定性：`NOT_READY`
- P2/P3/P4 固定面板富集：`NOT_READY`
- 下一批 P2/P3/P4 生成：`LOCKED`
- 本地目录：`/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714`
- node1 目录：`/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714`

## 冻结标识

- `protocol_core_sha256`: `e027143c22712b43d973709b278519a0cf414a9de182e094ea0cd8470d8295b8`
- `protocol_lock_sha256`: `a187a9addc60d66fd3ffba5221d1121b81029824ffaf0cd7f35a9278f017b4a1`
- `PROTOCOL_LOCK.json` file SHA256: `4d017059a5043140341298e5deb93dd4e7adac90cedbba074c329a74c7b2693c`
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
- [x] 37/37 本地回归测试通过；
- [x] 本地与 node1 `validate_protocol.py` 均为 `PASS`；
- [x] 部署文件与本地 `PROTOCOL_LOCK.json` 文件 hash 一致；
- [x] node1 后台 `smoke -> verify -> full` 编排器已启动。
- [x] 4/4 node1 smoke任务通过，`reports/SMOKE_VALIDATION.json` 为 `PASS`；
- [x] 1050任务全量控制器已自动启动。
- [x] 保持 Docking 核心 hash 和1050任务不变，将最终后处理锁升级为23文件；
- [x] 评价器稳定门禁已加入模型、seed、native/cross、阳性、破坏性控制和阈值敏感性判据；
- [x] 新增 P2/P3/P4 相对 P1/P5/P6 的 Fisher/Holm 固定面板富集门禁；
- [x] `guard_next_generation.py` 现在要求两个生产报告同时 `PASS` 才能解锁。

## node1 当前现场

- 后台编排器 PID：`4072777`；全量 controller PID：`4074688`；
- smoke 结果：`4 SUCCESS / 0 FAIL`，selected models 数分别为 `10 / 10 / 10 / 9`；
- smoke 已同时验证 HR-151 和 rank-1 候选的 8X6B、9E6Y 独立 HADDOCK run，以及每个 pose 的 native/cross 双参考评分；
- 全量当前状态：`29 SUCCESS / 1021 PENDING`；已有 `8/350` 个实体-构象达到至少2个成功 seed；
- 记录时 load1 约 `68.9`，故控制器暂不启动新任务；节点降载后自动恢复1/2/4并发；
- 当前29个成功任务中控制任务27个、候选任务2个；远端部分汇总已有29个 pose-backed jobs，但所有终局门禁保持 `NOT_READY`；
- node1 已验证最终锁文件 SHA256 为 `4d017059...b2693c`，远端 `PROTOCOL_VALIDATION.json` 为 `PASS`。

## 尚未完成

- [x] 4/4 node1 smoke任务通过；
- [x] 自动进入1050任务全量队列；
- [ ] 每个实体、每个构象至少2/3 seeds成功；
- [ ] 47控制的漂移和阈值敏感性报告完成；
- [ ] `reports/EVALUATOR_STABLE.json` 变为 `status=PASS`。
- [ ] `reports/P2_P3_P4_ENRICHMENT.json` 至少支持一个可靠 phase 并变为 `status=PASS`。

在最后两项同时完成前，`scripts/guard_next_generation.py` 始终非零退出，不能根据 P2/P3/P4 富集结果生成下一批序列。当前实测阻断原因是 `evaluator_status_not_pass:NOT_READY`。
