# bxcpu top5000 multimodal 4-seed runtime

这是一个独立、fail-closed 的运行切片，只依赖同目录脚本和已安装的 bxcpu
HADDOCK runtime cache。固定执行规模：

- 5,000 candidates；
- 40,000 exact jobs；
- 8 个计算 shard，每 shard 5,000 jobs；
- 8 个节点，每节点 64 CPU；
- 每节点 16 个并发 job，每 job 4 CPU；
- 每 job 使用 `SLURM_TMPDIR` 下的独立 scratch；
- SUCCESS status 最后发布；此前必须已有 `job_result.json` resume stub 和
  `compressed_queue/<job_id>.tar.gz` 完整证据。

## 必需锚点

提交前必须设置四个 SHA256：

```bash
export PVRIG_TOP5000_ARCHIVE_SHA256=...
export PVRIG_TOP5000_MANIFEST_SHA256=...
export PVRIG_TOP5000_READY_SHA256=...
export PVRIG_TOP5000_RECEIPT_SHA256=...
```

所有路径均可参数化：

```bash
export PVRIG_TOP5000_BUNDLE_ARCHIVE="$HOME/<bundle>.tar.zst"
export PVRIG_TOP5000_MANIFEST_PATH="$HOME/<bundle>.manifest.tsv"
export PVRIG_TOP5000_READY_PATH="$HOME/<bundle>.READY.json"
export PVRIG_TOP5000_PUBLISH_ROOT="$HOME/<campaign>_bxcpu_results"
export PVRIG_TOP5000_PREFLIGHT_RECEIPT_PATH="$PVRIG_TOP5000_PUBLISH_ROOT/reports/PREFLIGHT_RECEIPT.json"
export PVRIG_TOP5000_SUBMISSION_RECEIPT_PATH="$PVRIG_TOP5000_PUBLISH_ROOT/markers/SUBMISSION_RECEIPT.txt"
export PVRIG_TOP5000_AUDIT_OUTPUT="$PVRIG_TOP5000_PUBLISH_ROOT/reports/TECHNICAL_COMPLETION.json"
```

默认项目目录与 builder 一致：
`pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724`，默认 shard 目录是
`manifests/shards_exact_8`。

`READY.json` 必须把 manifest、内部 receipt SHA 绑定到同一个 campaign，并声明
`5000/40000/8` 计数；若 READY 还包含 archive SHA 或 jobs-per-shard，runtime
会继续校验。archive 在 builder READY 之后封装，因此 archive SHA 作为独立必需
锚点校验。默认 READY status 为
`READY_FOR_EXTERNAL_DOCKING_SUBMISSION`。内部 receipt 默认
`HANDOFF_RECEIPT.json`，status 默认为
`READY_FOR_EXTERNAL_DOCKING_SUBMISSION`，且必须声明
`docking_started=false`。这些 status 和内部相对路径也可通过环境变量覆盖。

## 提交链

在 bxcpu 上运行：

```bash
bash submit_top5000_multimodal_4seed_eight_nodes.sh
```

脚本一次性提交：

1. 4-CPU preflight：校验 archive/manifest/READY/receipt、HADDOCK 2025.11.0、
   NumPy 2.0.1、40k exact manifest、8×5000 shard，并运行一个真实 job smoke；
2. `afterok:preflight` 的 `1-8%8` array；
3. 对 8 个 array task 的 `afterany` technical audit。

## 增量回传与容量边界

在本地 D 盘控制机启动：

```bash
bash start_top5000_results_sync_sharded.sh
```

实测单 job compressed evidence 约 0.87 MB，40k 约 35 GB。默认同步参数：

- 固定 4 个并行 sync shard；
- batch 60（启动器只接受 40..80）；
- stable age 90 秒（启动器只接受 60..120）；
- 每个 shard spool 上限 4 GiB，总显式上限约 16 GiB；
- D 盘最少保留 10 GiB；
- Node1 默认目标是
  `/data/qlyu/projects/pvrig_node1_generated100k_multimodal_top5000_4seed_docking_results_v1_20260724`；
- 不使用 `/data1`。

每批流程是：

1. 从 bxcpu 拉到有界本地 spool；
2. 校验本地 payload 与 bxcpu inventory；
3. 生成逐文件 SHA manifest 和 transport archive SHA；
4. Node1 先校验 archive SHA，再解包并执行逐文件 `sha256sum -c`；
5. Node1 写入 `VERIFIED_ON_NODE1_BEFORE_BXCPU_PRUNE` receipt；
6. 仅此后调用 bxcpu prune helper，删除 `runs/`、worker log、
   `compressed_queue` 和 result 重载荷；
7. bxcpu 永久保留 SUCCESS `status/jobs/<id>.json` 和最小
   `results/<id>/job_result.json`（`offloaded_to_node1=true`）；
8. 本地 batch payload 立即删除，失败 prune 进入可恢复 backlog。

查看四路进度：

```bash
bash status_top5000_results_sync_sharded.sh
```

## 本地验证

```bash
bash run_static_tests.sh
```

该命令执行全部 Python `py_compile`、全部 shell `bash -n`，以及 exact-40k
manifest/8-shard、compact evidence、resume stub prune 和同步静态顺序的 synthetic
tests。
