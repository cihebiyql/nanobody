# PVRIG V4-H 研究池与自适应双构象 Docking 状态

更新时间：2026-07-17 08:42（Asia/Shanghai）

状态：`MONOMER_RUNNING_AND_DOCKING_AUTOLAUNCH_ARMED`

## 1. 当前执行目标

本轮不再以 P2/P3/P4 富集是否显著作为停止条件。实际目标是：

> 对现有新生成 VHH 尽可能扩大单体结构和 8X6B/9E6Y 双构象 Docking 覆盖，再依据跨构象较弱侧评分、seed 稳定性和多样性形成可追溯的候选排序库。

Docking 输出仅代表计算上的 blocker-like geometry，不代表真实结合、Kd、竞争或实验阻断。

## 2. 已冻结研究池

V4-H 已完成 1,440 条 exact-unique 序列生成：

| 研究状态 | 数量 | 处理 |
|---|---:|---|
| `RESEARCH_READY` | 1,320 | 全量进入 NBB2 单体建模 |
| `QUARANTINE_REPAIRABLE_PARENT_N_TERMINUS` | 120 | 全部来自 C0371，暂不进入本轮结构/Docking |

1,320 条研究候选的平衡性：

- 11 个 parent framework cluster，各 120 条；
- A_CENTER、B_LOWER、C_CROSS 各 440 条；
- H3、H1H3 各 660 条。

关键产物：

- `prepared/pvrig_v4_h_research_pool_v1/outputs/research_pool1440_manifest.tsv`
- `prepared/pvrig_v4_h_research_pool_v1/outputs/research_ready1320.tsv`
- `prepared/pvrig_v4_h_research_pool_v1/outputs/research_ready1320.fasta`
- `prepared/pvrig_v4_h_research_pool_v1/outputs/quarantine_c0371_120.tsv`
- `prepared/pvrig_v4_h_research_pool_v1/research_pool_audit_v1.json`
- `prepared/pvrig_v4_h_research_pool_v1/research_pool_receipt_v1.json`

## 3. C0371 为什么不自动补 N 端

C0371 对应 `PLDNANO_VHH_00553 / QYQ19596.1`。本地冻结序列和 NCBI 原始记录均为 121 aa，均从 `SGGGLVQAG...` 开始；NCBI 将其记录为专利 US 11001625 的 sequence 157。现有仓库没有可审计的 N 端 donor、补全规则或既往修复记录。

因此：

- 不把猜测的 `QVQLQE...` 直接拼到原序列；
- 不覆盖原 candidate_id 或 sequence SHA256；
- 120 条先隔离；以后若修复，必须产生新 ID、新序列哈希和明确 donor/rule provenance。

原始记录：<https://www.ncbi.nlm.nih.gov/protein/QYQ19596.1>

## 4. Node1 单体结构建模

远端根目录：

```text
/data1/qlyu/projects/pvrig_v4_h_research_pool_v1_20260717
```

运行方式：

- Node1 本地 SSD `/data1`；
- 8 个 GPU lane；
- 每 lane 4 CPU threads，总目标 32 CPU threads；
- 每条先 refined NBB2，再 unrefined fallback；
- 每条独立 JSON 状态，可断点续跑；
- 已成功且 PDB/序列/哈希闭合的候选在 resume 时自动跳过。

08:42 快照：

```text
917 SUCCESS
2 TECHNICAL_FAILURE
401 PENDING
919/1320 terminal
```

已确认的技术失败之一不是序列无法编号，而是 ImmuneBuilder 1.2.0 在 strained-sidechain 分支把 OpenMM `Threads` 参数作为 set 而不是 mapping 传入。已提供不修改安装环境的内存兼容 wrapper，并实测将该结构从 CA 最大断点 5.210 Å 恢复到 3.908 Å；初轮完成后只重跑 technical failures。

动态进度：

```text
/data1/qlyu/projects/pvrig_v4_h_research_pool_v1_20260717/monomer_full/status/PROGRESS.json
```

## 5. Node23 双构象 Docking 验证

已完成两层 smoke：

1. 静态 staging smoke：1 条候选成功生成 288-job 协议面板，协议锁、job manifest、相关单测和 final validation 通过；
2. 真实 HADDOCK smoke：1 条候选 + 1 条阳性 control，在 8X6B/9E6Y、seed 917 上共 4/4 jobs 成功。

真实 smoke 根目录：

```text
/data/qlyu/projects/pvrig_v4_h_research_docking_stage_smoke1h_20260717
```

同时修复了旧辅助聚合器的矛盾：HADDOCK 实际返回 10 个 selected models，旧函数声称使用 fixed top8 却在 `>8` 时直接报错。研究聚合器现在明确按 HADDOCK score 排序并截取 top8，保留固定评价逻辑而不重跑 Docking。

## 6. 正式计算漏斗

| 阶段 | 候选 | 每候选新增 jobs | 预计 candidate jobs | 目的 |
|---|---:|---:|---:|---|
| Stage 1 | 所有 monomer-success | 2 | 约 2,640 | seed 917，8X6B/9E6Y 全量覆盖 |
| Stage 2 | diversity-aware top 384 | 2 | 768 | 补 seed 1931 |
| Stage 3 | diversity-aware top 128 | 2 | 256 | 补 seed 3253 |

Node23 使用最多 12 个并行 HADDOCK jobs；每 job 配置 4 cores，目标负载约 48 logical CPU threads，不使用 GPU。

按既有 V4-D 实测：2,021 个结果的生成跨度约 18.9 小时。因此本轮从正式 Stage 1 启动到最终 adaptive ranking，粗略预计约 34–40 小时；实际时间取决于 monomer-success 数、重试和 NFS 发布速度。

## 7. 自动交接链

tmux session：

```text
pvrig-v4h-autolaunch
```

监控脚本：

```text
prepared/pvrig_v4_h_research_pool_v1/scripts/monitor_monomers_and_launch_adaptive_docking.sh
```

自动执行顺序：

1. 等待 Node1 初轮 1,320 条单体任务终态；
2. 用 OpenMM compatibility wrapper 只重跑 technical failures；
3. 发布 portable、hash-closed docking input；
4. 从 Node1 SSD 传输到 Node23；
5. 构建正式自适应双构象 Docking runtime；
6. 在 Node23 后台启动 Stage 1 → Stage 2 → Stage 3；
7. 发布候选级 adaptive seed 排名和技术失败状态。

本地动态状态：

```text
prepared/pvrig_v4_h_research_pool_v1/status/AUTOLAUNCH_STATUS.json
prepared/pvrig_v4_h_research_pool_v1/logs/monitor_and_launch.log
```

## 8. 最终将交付什么

最终排序文件会至少包含：

- candidate_id、sequence SHA256、parent、patch、design mode；
- 8X6B/9E6Y 各自成功 seed 数；
- 两构象各自 median geometry score；
- `R_dual_min`；
- seed dispersion；
- evidence tier（1/2/3 seed）；
- technical failure 原因；
- diversity-aware selection provenance。

这套结果用于计算优先级排序，不应写成已验证 binder 或已验证 blocker。
