# V3 运行状态

- 项目：`pvrig_v3_dual_conformation_redocking_20260714`
- 更新时间：`2026-07-15 21:29 Asia/Shanghai`
- 当前阶段：`FULL_QUEUE_COMPLETE_EVALUATOR_PASS_ENRICHMENT_FAIL`
- 本地协议验证：`PASS`
- node1 协议验证：`PASS`
- node23 协议验证：`PASS`
- 评价器稳定性：`PASS`
- P2/P3/P4 固定面板富集：`FAIL_NO_RELIABLE_PHASE`
- 下一批 P2/P3/P4 生成：`LOCKED`
- 本地目录：`/mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714`
- node1/node23 共享目录：`/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714`

## 冻结标识

- `protocol_core_sha256`: `e027143c22712b43d973709b278519a0cf414a9de182e094ea0cd8470d8295b8`
- `protocol_lock_sha256`: `4a6abac9612f69e3fd2f6df58ac192b6b8b852209c1afaf9e9f5dec33efb414e`
- `PROTOCOL_LOCK.json` file SHA256: `6c3598eefd109481a236fd38859d0aa4f47a6b5ba2df1db21fab54c8187530d1`
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
- [x] 44/44 本地回归测试通过；
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
- [x] node23 并发从4路提升到8路，8个任务各使用4核，目标占用32/64逻辑CPU；
- [x] 1,050 个任务终局为 `1049 SUCCESS / 1 FAILED_MAX_ATTEMPTS`，350/350 个实体-构象均达到至少2个成功 seed；
- [x] 归档旧浮点后处锁和 FAIL 报告，使用十进制阈值缩放修正 `100 x 1.1` 边界错判；
- [x] 评价器 `pvrig_v3_evaluator_stability_v3_decimal_thresholds` 所有门禁通过；
- [x] 完成 P2/P3/P4 固定面板富集分析，无 phase 达到预先锁定的可靠富集标准；

## 当前执行现场

- 当前控制器主机：`node23`；全量 controller PID：`3410701`；
- node1 编排器 PID `4072777` 和 controller PID `4074688` 已停止，不存在双控制器；
- smoke 结果：`4 SUCCESS / 0 FAIL`，selected models 数分别为 `10 / 10 / 10 / 9`；
- smoke 已同时验证 HR-151 和 rank-1 候选的 8X6B、9E6Y 独立 HADDOCK run，以及每个 pose 的 native/cross 双参考评分；
- 全量终局：`1049 SUCCESS / 1 FAILED_MAX_ATTEMPTS`；`350/350` 个实体-构象达到至少2个成功 seed；
- node23 本地 scratch 模式当前并发上限为8，运行根目录为 `/tmp/pvrig_v3_haddock`；
- 控制任务 `282/282` 成功，候选任务 `767/768` 成功；评价器 `PASS`，富集门禁 `FAIL`；
- 迁移证据：`status/controller_migration_node1_to_node23.json`；旧PID归档在 `status/migration_archive/`；
- node23 已验证协议 `PASS`。迁移后的首批4个 NFS 任务虽然约26分钟才完成，但最终全部成功；后续本地 scratch 生产任务已全部终止并保留结果。

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

8路模式下每个 HADDOCK job 固定4核，合计目标为32/64逻辑CPU。控制器继续按1-minute load自适应：`<48: 8路`、`48-56: 6路`、`56-62: 4路`、`>=62: 暂停补位`。`08:07` 实测维持8路时 load1约41.7；由于同机其他用户也在运行高CPU任务，整机CPU忙约75.6%、idle约24.4%，其中 PVRIG 的 nice CPU约37.2%，I/O wait为0。随后在 load1 `46.56` 时仍保持8路，并在一批任务完成后的60秒轮询中自动补回8路。

当前生产启动命令为：

```bash
REMOTE_HOST=node23 \
REMOTE_LOCAL_SCRATCH_ROOT=/tmp/pvrig_v3_haddock \
REMOTE_MAX_PARALLEL=8 \
scripts/launch_node1.sh full
```

实时状态命令：

```bash
REMOTE_HOST=node23 scripts/launch_node1.sh status
```

## 尚未完成

- [x] 4/4 node1 smoke任务通过；
- [x] 自动进入1050任务全量队列；
- [x] 每个实体、每个构象至少2/3 seeds成功；
- [x] 47控制的漂移和阈值敏感性报告完成；
- [x] `reports/EVALUATOR_STABLE.json` 变为 `status=PASS`。
- [ ] `reports/P2_P3_P4_ENRICHMENT.json` 至少支持一个可靠 phase 并变为 `status=PASS`。

当前 `scripts/guard_next_generation.py` 仍非零退出，不能根据 P2/P3/P4 富集结果生成下一批序列。当前实测阻断原因是 `enrichment_status_not_pass:FAIL`。
