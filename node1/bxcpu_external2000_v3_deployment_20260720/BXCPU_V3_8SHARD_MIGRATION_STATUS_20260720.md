# BXCPU PVRIG V3 8 分片迁移状态

## 结论

- V3 输入包、HADDOCK 2025.11.0 运行时、协议核心哈希和评分参照均已核对。
- 已将 3,814 个 safe jobs 固定拆分为 8 个互斥分片：前 6 片各 477 个，后 2 片各 476 个。
- 旧两节点作业在 288 个 SUCCESS 时安全停止；结果保留，新 worker 会按状态和结果双文件跳过已完成 job。
- 新 array 为 `11936121`，后置专用汇总为 `11936122`。
- 初次正式调度时只有分片 1、2 运行；管理员放开限额后，分片 1–8 已全部运行。
- 主 V29 队列已重分配：Node1 排除 2,596 个 bxcpu jobs，Node23 排除 1,218 个，两端新队列与 bxcpu 重叠均为 0。

## 实际资源限制

```text
user=als001821
account=bscc-al
qos=normal
partition=amd_256q
GrpTRES=node=8
MaxSubmitJobs=10
```

`sbatch --test-only` 曾规划出 8 个节点，但初次正式 array 仍受 `node=2` 关联限额约束。
管理员将关联上限改为 `node=8` 后，原已提交的 pending 分片由 Slurm 自动启动，
没有重新提交或重复构建输入。

## 运行证据

2026-07-20 20:01 CST：

```text
SUCCESS=836
FAILED=0
11936121_[1-8] RUNNING, 8 x 64 CPU
11936122 PENDING Dependency
```

SUCCESS 已从迁移时的 288 增加到 836，说明 resume 和发布链正常。

## 一致性检查

迁移前对 256 个 SUCCESS 结果进行了独立核对：

- job ID 全部存在于冻结 manifest；
- job hash、seed、受体构象全部一致；
- `protocol_core_sha256` 全部为
  `49fffc2c7087b1ff3a8e42463319168fad409687f502b619f3661c978fc6d666`；
- 每个 pose 都具有 `8x6b` 和 `9e6y` 参照评分；
- 一致性错误为 0。

selected models 中 249 个 job 为 10 个、7 个 job 为 9 个，属于聚类后的合法数量差异，
不是协议分叉。

## Node1/Node23 主队列重分配

已在主项目生成：

```text
manifests/node1_jobs_excluding_bxcpu_v3.tsv   9,817 jobs
manifests/node23_jobs_excluding_bxcpu_v3.tsv 11,195 jobs
```

原有 feeder 先用 `SIGSTOP` 停止继续取任务，已在运行的 Docking 自然完成后才替换 feeder。
新 Node1 feeder 保持 5 路并发，新 Node23 feeder 使用 16 路并发。
