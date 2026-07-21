# bxcpu Docking 结果自动分批同步

## 数据路径

- bxcpu Stage2：`~/pvrig_v29_bxcpu_stage2_10500_v1_20260720_bxcpu_results`
- bxcpu Stage3：`~/pvrig_v29_bxcpu_stage3_node20_v1_20260720_bxcpu_results`
- 本地活动缓存（WSL ext4）：`/root/pvrig_bxcpu_incremental_spool_20260721`
- 持久脚本/文档：`/mnt/d/work/抗体/node1/bxcpu_external2000_v3_deployment_20260720`
- Node1 最终归档：`/data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720`

本地磁盘只保留当前小批次。每批文件在 Node1 通过 SHA256 后，本地的
`results/`、`runs/` 和对应 worker log 会自动删除；状态、报告、批次校验清单和
已交付 job ID 会保留。因此本地不需要容纳完整的数百 GB Docking 输出。

## 同步规则

1. 每轮先同步小体积的 `status/jobs`、`markers` 和 `reports`。
2. bxcpu 压缩器只处理已经稳定的 SUCCESS，并将完整 `runs/results/log/status`
   封装为逐 job `tar.gz`；原始成功状态和 `job_result.json` 始终保留作断点凭据。
3. 四个确定性分片同步器只选择状态稳定至少 180 秒的终态作业，每片每批 40 个。
4. bxcpu 将已压缩的逐 job `tar.gz` 用**无二次 gzip**的外层 tar 流下载到 WSL ext4 缓存，避免 9p/DrvFS 小文件 I/O。
5. 本地逐 job 检查 gzip/tar 完整性；损坏的历史包只延后该 job，不再中断整批。
6. 只将验证通过的 job 重组为无压缩外层 tar，断点传到 Node1；Node1 先验证整批 SHA256，再解外层 tar。
7. Node1 **不默认展开**每个 job 内部的数百个 HADDOCK 文件，而是保留 `compressed_queue/<job_id>.tar.gz`；需要查看时才按 job 解包。
8. Node1 验证成功后才登记 delivered，并删除 bxcpu 重型 payload；远端仅保留续跑 stub。
9. 校验失败或网络中断不会标记完成；下一轮自动续传。

技术失败仍作为终态同步，但不会被解释为生物学阴性。

## 操作命令

启动或确认守护进程：

```bash
PVRIG_BXCPU_SYNC_SHARDS=4 \
PVRIG_BXCPU_SYNC_BATCH_SIZE=40 \
PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=180 \
./start_bxcpu_results_sync_sharded.sh
```

查看状态：

```bash
./status_bxcpu_results_sync_sharded.sh
```

单轮测试：

```bash
python3 sync_bxcpu_results_incremental.py --once
```

环境变量：

- `PVRIG_BXCPU_SYNC_BATCH_SIZE`：每分片每批 job 数；守护启动器默认 40。
- `PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS`：终态稳定等待时间；守护启动器默认 180 秒。
- `PVRIG_BXCPU_SYNC_POLL_SECONDS`：轮询间隔；守护启动器默认 5 秒。
- `PVRIG_BXCPU_SYNC_MIN_LOCAL_FREE_GIB`：本地最低保留空间，默认 5 GiB。
- `PVRIG_BXCPU_SYNC_SHARD_COUNT/SHARD_INDEX`：确定性传输分片。

在 Node1 按需展开单个 job：

```bash
python3 /data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720/scripts/extract_node1_archived_job.py JOB_ID
```

## 完整性证据

- 本地分片状态：`.../shardNN/state/SYNC_STATUS.shardNNofMM.json`
- 本地分片事件日志：`.../shardNN/state/sync_events.jsonl`
- Node1 批次清单：`<campaign>/state/batches/*.sha256`
- Node1 已交付列表：`<campaign>/state/*.delivered_job_ids.txt`
- bxcpu 压缩队列：`<campaign>/compressed_queue/*.tar.gz`
- bxcpu 压缩事件：`<campaign>/compressed_queue/COMPACTION_EVENTS.jsonl`

2026-07-21 已用 4 分片真实批次验证：159 个 job 在约 173 秒内交付，
等效 55.1 job/分钟；随机抽取的单 job 包在 Node1 通过 `tar -tzf`，
并成功按需展开 417 个文件。
