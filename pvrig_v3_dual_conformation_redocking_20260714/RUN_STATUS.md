# V3 运行状态

- 项目：`pvrig_v3_dual_conformation_redocking_20260714`
- 更新时间：`2026-07-15 06:50 Asia/Shanghai`
- 当前阶段：`FULL_QUEUE_NODE23_LOCAL_SCRATCH_VERIFIED_RUNNING_4_WAY`
- 本地协议验证：`PASS`
- node1 协议验证：`PASS`
- node23 协议验证：`PASS`
- 评价器稳定性：`NOT_READY`
- P2/P3/P4 固定面板富集：`NOT_READY`
- 下一批 P2/P3/P4 生成：`LOCKED`
- 本地目录：`/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714`
- node1/node23 共享目录：`/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714`

## 冻结标识

- `protocol_core_sha256`: `e027143c22712b43d973709b278519a0cf414a9de182e094ea0cd8470d8295b8`
- `protocol_lock_sha256`: `74b4cd7c7567f3ee68b7123a69fab021641cbdb8d96d12401375285cf91755f3`
- `PROTOCOL_LOCK.json` file SHA256: `ef803b1b242cbb55e2f787ed06c62939ef7fba1a8e734661bd950f2ec065e45f`
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
- [x] 42/42 本地回归测试通过；
- [x] 本地与 node1 `validate_protocol.py` 均为 `PASS`；
- [x] 部署文件与本地 `PROTOCOL_LOCK.json` 文件 hash 一致；
- [x] node1 后台 `smoke -> verify -> full` 编排器已启动。
- [x] 4/4 node1 smoke任务通过，`reports/SMOKE_VALIDATION.json` 为 `PASS`；
- [x] 1050任务全量控制器已自动启动。
- [x] 保持 Docking 核心 hash 和1050任务不变，将最终后处理锁升级为23文件；
- [x] 评价器稳定门禁已加入模型、seed、native/cross、阳性、破坏性控制和阈值敏感性判据；
- [x] 新增 P2/P3/P4 相对 P1/P5/P6 的 Fisher/Holm 固定面板富集门禁；
- [x] `guard_next_generation.py` 现在要求两个生产报告同时 `PASS` 才能解锁。
- [x] node1 长时间高负载后，在无活跃 job 的窗口将唯一控制器无损迁移到 node23；
- [x] 迁移保留38个成功任务，node1旧PID已归档，共享控制锁已由node23接管。
- [x] 识别出 node23 直接在共享 NFS 上运行 CNS 的目录操作瓶颈，并改为本地 scratch 计算后原子回写；
- [x] 同任务本地 scratch 对照在4分47秒完成，首个正式4任务 scratch 批次4/4成功并自动补位。

## 当前执行现场

- 当前控制器主机：`node23`；全量 controller PID：`3340245`；
- node1 编排器 PID `4072777` 和 controller PID `4074688` 已停止，不存在双控制器；
- smoke 结果：`4 SUCCESS / 0 FAIL`，selected models 数分别为 `10 / 10 / 10 / 9`；
- smoke 已同时验证 HR-151 和 rank-1 候选的 8X6B、9E6Y 独立 HADDOCK run，以及每个 pose 的 native/cross 双参考评分；
- `06:50` 全量快照：`54 SUCCESS / 4 RUNNING / 992 PENDING`；已有 `17/350` 个实体-构象达到至少2个成功 seed；
- node23 迁移前 load1 约 `4.2`；本地 scratch 模式当前并发上限为4，运行根目录为 `/tmp/pvrig_v3_haddock`；
- 当前38个成功任务中控制任务36个、候选任务2个；所有终局门禁仍保持 `NOT_READY`；
- 迁移证据：`status/controller_migration_node1_to_node23.json`；旧PID归档在 `status/migration_archive/`；
- node23 已验证协议 `PASS`。迁移后的首批4个 NFS 任务虽然约26分钟才完成，但最终全部成功；随后已有12个 scratch 正式任务完成，现有54个结果均保留。

## node23 本地 scratch 修复

首批4个 node23 生产任务直接在共享 `/data` NFS 中运行，全部在 `flexref` 阶段长期等待 NFS 目录操作；它们最终在约26分钟后完成，不是结果损坏或永久死锁。相同 job 仅把 `haddock3.cfg` 和 `data/` 复制到 node23 本地 ext4 `/tmp` 后，4分47秒完成完整 HADDOCK3 流程，说明瓶颈位于 NFS 上的 CNS 高频临时文件操作，而不是 node23 CPU 或 HADDOCK3 安装。

当前 `scripts/run_job.py` 在设置 `PVRIG_LOCAL_SCRATCH_ROOT` 时执行以下闭环：

1. 状态、锁、manifest 和最终结果仍以共享项目目录为权威源；
2. 每个 job 在 `/tmp/pvrig_v3_haddock/<job_id>/` 独立执行 HADDOCK3；
3. HADDOCK 完成后先把完整 run 复制到共享目录的隐藏临时路径，再用同目录原子 rename 发布；
4. 后处理只对已发布的共享 selected models 评分，结果路径继续保持 `runs/<job_id>/...`；
5. job 成功后清理本地 scratch；失败任务在重试前先原子归档到共享 `failed_attempts/`，不会静默删除失败日志；
6. 共享 `status/controller.lock` 继续保证 node1/node23 只有一个 controller。

启动器默认使用 `/tmp/pvrig_v3_haddock`，启动前检查目录可写并拒绝 NFS 文件系统；非法或带路径分隔符的 job ID 会在任何锁、归档或删除操作前被拒绝。scratch 清理失败只记录警告，不会把已经完整发布的 `SUCCESS` 回滚为 `FAILED`。

当前生产启动命令为：

```bash
REMOTE_HOST=node23 \
REMOTE_LOCAL_SCRATCH_ROOT=/tmp/pvrig_v3_haddock \
scripts/launch_node1.sh full
```

实时状态命令：

```bash
REMOTE_HOST=node23 scripts/launch_node1.sh status
```

## 尚未完成

- [x] 4/4 node1 smoke任务通过；
- [x] 自动进入1050任务全量队列；
- [ ] 每个实体、每个构象至少2/3 seeds成功；
- [ ] 47控制的漂移和阈值敏感性报告完成；
- [ ] `reports/EVALUATOR_STABLE.json` 变为 `status=PASS`。
- [ ] `reports/P2_P3_P4_ENRICHMENT.json` 至少支持一个可靠 phase 并变为 `status=PASS`。

在最后两项同时完成前，`scripts/guard_next_generation.py` 始终非零退出，不能根据 P2/P3/P4 富集结果生成下一批序列。当前实测阻断原因是 `evaluator_status_not_pass:NOT_READY`。
