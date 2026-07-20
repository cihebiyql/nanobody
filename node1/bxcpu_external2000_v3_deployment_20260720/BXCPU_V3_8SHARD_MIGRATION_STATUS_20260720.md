# BXCPU PVRIG V3 8 分片迁移状态

## 结论

- V3 输入包、HADDOCK 2025.11.0 运行时、协议核心哈希和评分参照均已核对。
- 已将 3,814 个 safe jobs 固定拆分为 8 个互斥分片：前 6 片各 477 个，后 2 片各 476 个。
- 旧两节点作业在 288 个 SUCCESS 时安全停止；结果保留，新 worker 会按状态和结果双文件跳过已完成 job。
- 新 array 为 `11936121`，后置专用汇总为 `11936122`。
- 正式调度时只有分片 1、2 运行；分片 3–8 因 `AssocGrpNodeLimit` 等待。

## 实际资源限制

```text
user=als001821
account=bscc-al
qos=normal
partition=amd_256q
GrpTRES=node=2
MaxSubmitJobs=10
```

`sbatch --test-only` 曾规划出 8 个节点，但正式 array 的 pending reason 证明
账户关联上限会在真实调度时生效。当前用户没有第二个已授权 account/QOS，
所以不能在不更改集群授权的前提下同时使用 8 个节点。

## 运行证据

2026-07-20 19:25 CST：

```text
SUCCESS=312
RUNNING(status)=3
FAILED=0
11936121_1 RUNNING p2314, 64 CPU
11936121_2 RUNNING k1314, 64 CPU
11936121_[3-8] PENDING AssocGrpNodeLimit
11936122 PENDING Dependency
```

SUCCESS 已从迁移时的 288 增加到 312，说明 resume 和发布链正常。

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

## 需要的外部授权变更

若要立即将 6 个 pending 分片同时拉起，集群管理员需将
`als001821 / bscc-al` 的 association `GrpTRES` 节点上限从 2 提高到至少 8。
限额放开后，已提交的分片 3–8 可由 Slurm 自动调度，无需重新生成或重复 Docking。
