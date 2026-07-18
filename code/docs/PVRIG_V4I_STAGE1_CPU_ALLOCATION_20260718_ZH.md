# PVRIG V4-I Stage 1 CPU 分片运行记录（2026-07-18）

## 当前分配

| 计算端 | 候选数 | Docking 作业数 | 并发作业 | 每作业 CPU | 约占用 CPU |
|---|---:|---:|---:|---:|---:|
| Node23 | 1446 | 2892 | 24 | 4 | 动态上限 96 线程 |
| Node1 | 300 | 600 | 5 | 4 | 约 20 核 |
| 本机 WSL | 100 | 200 | 2 | 4 | 约 8 核 |

本机保持 2 个 Docking 作业并发，是为了遵守先前的温度/负载限制，不用满 WSL 可见的 16 个 CPU。

## 分片安全性

- Node1 manifest: `stage1_node1_cpu20_v1.tsv`，600 jobs，SHA256 `1c72beb6120914b804e8dfb06958b7dcdda5f769bad0030d70903d3e60069722`
- 本机 manifest: `stage1_local_cpu8_v1.tsv`，200 jobs，SHA256 `7ca3797355bb0d30c8395a1e56c6132e7615c08e2b1fcaa86314cb44ea23fa15`
- Node23 manifest: `stage1_node23_main_v1.tsv`，2892 jobs，SHA256 `8d9047eaacda827a2dec220469b065330c784a5d24b0c5c4c00cfed79d59601a`
- 三个 job-ID 集合两两交集均为 0，共覆盖 3692 个当时可分配的 pending jobs。
- 每个候选的 `8X6B`/`9E6Y` 两个构象保持在同一分片中。
- 原 Stage 1 控制器 PID `1383397` 以 `SIGSTOP` 保留；不再派发新作业，避免与分片重复。
- 守护程序只在三个分片的 canonical 状态全部终止后恢复原控制器，由它收尾未分片的少量作业并继续 adaptive workflow。

## 运行路径

- Canonical root: `/data/qlyu/projects/pvrig_v4_i_round2_dual_docking_v1_1_20260718`
- Node1 SSD runtime: `/data1/qlyu/pvrig_node1_cpu_offload_v4i_20260718`
- 本机 runtime: `/root/pvrig_local_offload_v4i_20260718`
- Node23 shard controller: `scripts/run_controller_node23_shard_v1.py`
- 自动恢复守护状态: `status/stage1_distributed_resume_guard_v1.json`

## 首批验证

- Node1 首批 5 jobs 已成功完成并通过 hash-bound importer 写回 canonical root。
- 本机 2 jobs 已进入正常 HADDOCK 运行状态。
- Node23 shard controller 已保持 24 jobs 并发。
- 初次 SSD 镜像缺少 `reports/reference_normalization_summary.json`，已补齐且三端 SHA256 一致；Node1 重试后首批成功。

## 科学边界

本记录只证明计算 Docking 任务的分配、执行和结果导入；不代表真实结合、亲和力/Kd 或实验阻断效果。
