# 在 bxcpu 上运行 PVRIG V3 docking

本教程对应当前已部署的 `pvrig_v29_external2000_sequences_v3_20260720`。
它只运行可立即执行的 3,814 个 safe jobs；node21 尚未移交的 186 个 jobs
始终不调度。

## 1. 登录与资源边界

Windows PowerShell、Windows Terminal 或 WSL 均可使用：

```bash
ssh bxcpu
```

本账户所在分区是 `amd_256q`。每节点为 64 CPU 核、约 256 GiB 内存，但
Slurm 使用 `select/linear`：即使只请求 4 核，一个 job 也会占用完整节点。
当前部署固定为两个独占节点、每节点 64 核。

不要在登录节点直接运行 HADDOCK，也不要用 V2 包开始新计算。

### 8 节点预检与实际调度限制（2026-07-20 实测更正）

2026-07-20 `sbatch --test-only` 曾接受单个 `--nodes=8` 请求，并返回
512 CPU 和 8 个具体节点的计划。但这只证明资源形状和分区可解析，
不证明正式作业能突破账户关联限额。

正式提交 8 任务 array `11936121` 后，实际只有任务 1、2 运行，
任务 3–8 均显示 `AssocGrpNodeLimit`。`sacctmgr` 的实时关联为：

```text
user=als001821 account=bscc-al qos=normal GrpTRES=node=2
```

因此当前正式作业的实际并发上限是 **2 节点 × 64 核 = 128 CPU 核**。
除非集群管理员将 `bscc-al` 的关联节点上限从 2 提高到 8，
否则不能通过改 array 形状、重复提交或切换分片绕过该限制。
`MaxSubmitJobs=10` 仍是独立的作业数量限制。

## 2. 关键路径

登录后设置：

```bash
DEPLOY="$HOME/.local/share/bxcpu_external2000_v3_deployment_20260720"
RESULT_ROOT="$HOME/pvrig_v29_external2000_sequences_v3_20260720_bxcpu_results"
cd "$DEPLOY"
```

| 位置 | 用途 |
| --- | --- |
| `~/pvrig_v29_external2000_sequences_v3_20260720.tar.zst` | V3 不可变输入包 |
| `~/.local/opt/` | HADDOCK 2025.11.0 运行时、源码和 NumPy 2.0.1 EL7 覆盖层 |
| `$DEPLOY` | 预检、两节点 worker 与汇总脚本 |
| `$RESULT_ROOT` | 实时状态、结果、pose、日志和汇总报告 |

V3 包 SHA256 必须为：

```text
62f3c702f582c1d488263170b3a8835746fe7fb533fa49b01786392978483e94
```

## 3. 为什么必须使用 V3

V2 的 `score_pose.py` 固定读取：

```text
reports/reference_normalization_summary.json
```

V2 包中缺少该文件，因而可能在 HADDOCK 已完成后于评分阶段失败。V3 已加入
该文件、`validate_protocol.py`、外部分片专用汇总器和完整包校验。

不要对 external2000 直接运行主项目的 `aggregate_results.py`。它依赖 47 个
控制和多 seed 门禁，适用于完整主项目，不适用于本分片。V3 必须使用：

```bash
python scripts/aggregate_external2000_results.py --root "$PWD"
```

它会输出 `NOT_READY`，直到 node21 的 186 个 jobs 移交；这不是 FAIL，且
`unlockable=false` 是预期的科学边界。

## 4. 启动前预检

每次提交前运行：

```bash
cd "$DEPLOY"
./preflight_v3_bxcpu.sh
```

预检必须显示 `v3_portable_cache=PASS`。它检查 V3 包、HADDOCK 源码、三个
运行时分片以及 EL7 兼容的 NumPy 2.0.1 覆盖层。

不要手工激活别的 Conda 环境，也不要覆盖 worker 的 `PYTHONPATH`。原始
NumPy 2.4.0 需要 glibc 2.27，而 bxcpu 是 EL7/glibc 2.17；worker 会在本地
scratch 中优先加载已验证的 NumPy 2.0.1。

## 5. 启动两节点、满 64 核 docking

先确认没有同名活跃 campaign，避免向同一结果目录重复写入：

```bash
squeue -u "$USER" -n pvrig-v3-ext2000
```

无活跃 job 时，提交：

```bash
cd "$DEPLOY"
./submit_v3_two_nodes.sh
```

该脚本提交一个两任务 array。每个 array task：

- 申请 1 个独占节点、64 CPU、230 GiB；
- 读取 `external_ready_now_jobs.tsv`；
- 得到 1,907 个不重叠 job；
- 每批并发 16 个冻结的 4 核 HADDOCK 运行，正好使用该节点的 64 核；
- 每个 job 在节点本地 scratch 运行，再将 `status/jobs/`、`results/`、`runs/`
  同步回 `$RESULT_ROOT`。

### 扩展到 8 个节点前必须重分片

当前 `submit_v3_two_nodes.sh` 和 `bxcpu_v3_two_node_worker.sh` **只支持两个
shard**。不能把它的 array 改成 `1-8%8`：worker 会拒绝第 3–8 项，而且即使
强行绕过也会有重复或遗漏 job 的风险。

正确的 8 节点方案必须先把 3,814 个 safe jobs 分成 8 个无重叠 shard（每个
476 或 477 jobs），再让每节点继续采用 16 路 4 核并发。建议在当前两节点
campaign 结束、或另建完全独立的结果目录后实施。若没有其他活跃 job，8 个
docking task 加 1 个后置汇总 task 共 9 个，仍低于 `MaxSubmitJobs=10`。

提交前可做无副作用的资源验证：

```bash
sbatch --test-only \
  --partition=amd_256q --nodes=8 --ntasks=8 --cpus-per-task=64 \
  --mem=230G --exclusive --time=24:00:00 \
  "$DEPLOY/bxcpu_v3_two_node_worker.sh"
```

这条命令只验证 Slurm 资源，不会执行 worker；它不是 8-shard 的正式启动命令。

新建独立 campaign 时，务必先换结果目录：

```bash
export PVRIG_V3_PUBLISH_ROOT="$HOME/pvrig_v29_external2000_v3_rerun_$(date +%Y%m%d_%H%M%S)"
./submit_v3_two_nodes.sh
```

## 6. 监控进度

将 `<ARRAY_JOB_ID>` 换成提交命令返回的 array job ID：

```bash
squeue -j <ARRAY_JOB_ID> -o "%.18i %.9P %.8T %.4C %.10M %.9l %.28R"
sacct -j <ARRAY_JOB_ID> --format=JobID,State,ExitCode,Elapsed,AllocCPUS,NodeList%20
```

确认两个任务都是 `RUNNING`，且分别有 `CPUS=64`、不同的节点名。查看已发布
的技术状态：

```bash
python3 - "$RESULT_ROOT/status/jobs" <<'PY'
from collections import Counter
import json, pathlib, sys

counts = Counter()
for path in pathlib.Path(sys.argv[1]).glob("*.json"):
    counts[json.load(open(path)).get("status", "MISSING")] += 1
print(", ".join("{}={}".format(k, v) for k, v in sorted(counts.items())))
PY
```

实时日志位于：

```bash
tail -f "$RESULT_ROOT/slurm-pvrig-v3-ext2000-<ARRAY_JOB_ID>_1.out"
tail -f "$RESULT_ROOT/slurm-pvrig-v3-ext2000-<ARRAY_JOB_ID>_2.out"
```

单个 docking 的详细日志位于：

```bash
ls "$RESULT_ROOT/worker_logs/"
```

### 当前实测速率与 ETA 计算

2026-07-20 的两节点 V3 run 在完成 192 个 safe jobs、且没有技术失败时，按首
批完成后连续 5 个完整 32-job 批次的时间间隔测得：

```text
总吞吐：约 7.24 jobs/分钟 = 434.6 jobs/小时
单节点：约 3.62 jobs/分钟 = 217.3 jobs/小时
```

这个数值对应两个 64 核节点、每节点 16 个 4 核 HADDOCK job 并发的当前配置。
它是运行时观测值，不是固定性能保证；不同 VHH、聚类、磁盘 I/O、共享文件系统
抖动和技术重试都会改变批次时长。

估算剩余时间时，使用已完成 job 数 `DONE`：

```text
剩余小时 ≈ (3814 - DONE) / 434.6
```

例如 `DONE=192` 时，剩余计算时间约为 8.3 小时；后置专用汇总还会额外需要几
分钟。应以最新 `SUCCESS` 计数重新计算，而不要用提交时的静态 ETA。

## 7. 专用汇总与结果解释

对新的部署，array 的第 1 个 shard 在第 2 个 shard 完成后会运行专用汇总。
汇总报告在：

```bash
ls -lh "$RESULT_ROOT/reports/"
python3 -m json.tool "$RESULT_ROOT/reports/EXTERNAL2000_AGGREGATION.json" | head -n 80
```

应存在：

```text
external_job_results.tsv
external_pose_scores.tsv
external_candidate_dual.tsv
EXTERNAL2000_AGGREGATION.json
```

如果需要为旧版已启动的 array 增加可靠的后置汇总，可使用：

```bash
cd "$DEPLOY"
./submit_v3_aggregation_after_shards.sh <ARRAY_JOB_ID>
```

该汇总 job 会等待两个 shard 结束，接受 V3 预期的 `NOT_READY` 退出语义，并
发布报告。它不会套用 47-control 或 multi-seed 主项目门禁。

`SUCCESS` 只表示计算与评分流程完成。外部分片的结果是双受体、单 seed 的
计算 geometry evidence，不代表亲和力、Kd、IC50、表达、纯度或实验阻断。

## 8. 回迁到完整主项目

外部节点完成后，回传以下目录：

```text
status/jobs/
results/
runs/
```

合并时必须使用以下三元身份键核对：

```text
job_id + job_hash + protocol_core_sha256
```

完成回迁后，才在完整 V29 主项目中运行正式的全量汇总。技术失败必须保留为
`NA`，不能改写为生物学阴性。

## 9. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `GLIBC_2.27 not found` | 使用了未覆盖的 NumPy 2.4.0；重新运行预检并使用本部署 worker。 |
| HADDOCK 完成、评分失败 | 常见于 V2 缺少参考摘要；停止 V2 新任务，改用 V3。 |
| `NOT_READY` | node21 的 186 jobs 尚未移交，是预期状态而不是 FAIL。 |
| 申请 4 核却占满节点 | bxcpu 的 `select/linear` 行为；使用本教程的 16 路节点内并发。 |
| 作业等待 `Dependency` | 后置汇总正在等待两个 docking shard 结束。 |

如需停止当前 array，请先确认 job ID，再执行：

```bash
scancel <ARRAY_JOB_ID>
```

停止会中断尚未完成的 safe jobs；已发布的 `status/jobs/`、`results/` 和
`runs/` 可用于后续审计或按身份键恢复。
