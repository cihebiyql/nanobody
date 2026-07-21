# bxcpu Docking 结果自动分批同步

## 数据路径

- bxcpu Stage2：`~/pvrig_v29_bxcpu_stage2_10500_v1_20260720_bxcpu_results`
- bxcpu Stage3：`~/pvrig_v29_bxcpu_stage3_node20_v1_20260720_bxcpu_results`
- 本地临时缓存：`/mnt/d/work/抗体/node1/bxcpu_incremental_spool_20260720`
- Node1 最终归档：`/data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720`

本地磁盘只保留当前小批次。每批文件在 Node1 通过 SHA256 后，本地的
`results/`、`runs/` 和对应 worker log 会自动删除；状态、报告、批次校验清单和
已交付 job ID 会保留。因此本地不需要容纳完整的数百 GB Docking 输出。

## 同步规则

1. 每轮先同步小体积的 `status/jobs`、`markers` 和 `reports`。
2. bxcpu 压缩器只处理已经稳定的 SUCCESS，并将完整 `runs/results/log/status`
   封装为逐 job `tar.gz`；原始成功状态和 `job_result.json` 始终保留作断点凭据。
3. 两个确定性分片同步器只选择状态稳定至少 600 秒的终态作业，每片每批 40 个。
4. bxcpu 将批次作为 tar.gz 流下载到本地临时缓存，避免数十万小文件逐个 SSH。
5. 本地检查外层及逐 job gzip/tar 完整性，并计算整批 SHA256。
6. 同一个压缩包再断点传到 Node1；Node1 先验证整批 SHA256，再完整解包。
7. Node1 验证成功后才登记 delivered，并删除 bxcpu 重型 payload；远端仅保留续跑 stub。
8. 校验失败或网络中断不会标记完成；下一轮自动续传。

技术失败仍作为终态同步，但不会被解释为生物学阴性。

## 操作命令

启动或确认守护进程：

```bash
PVRIG_BXCPU_SYNC_SHARDS=2 \
PVRIG_BXCPU_SYNC_BATCH_SIZE=40 \
PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS=600 \
./start_bxcpu_results_sync_sharded.sh
```

查看状态：

```bash
PVRIG_BXCPU_SYNC_SHARDS=2 ./status_bxcpu_results_sync_sharded.sh
```

单轮测试：

```bash
python3 sync_bxcpu_results_incremental.py --once
```

环境变量：

- `PVRIG_BXCPU_SYNC_BATCH_SIZE`：每批 job 数，默认 5。
- `PVRIG_BXCPU_SYNC_STABLE_AGE_SECONDS`：终态稳定等待时间，默认 600 秒。
- `PVRIG_BXCPU_SYNC_POLL_SECONDS`：轮询间隔，默认 60 秒。
- `PVRIG_BXCPU_SYNC_MIN_LOCAL_FREE_GIB`：本地最低保留空间，默认 5 GiB。
- `PVRIG_BXCPU_SYNC_SHARD_COUNT/SHARD_INDEX`：确定性传输分片。

## 完整性证据

- 本地分片状态：`.../shardNN/state/SYNC_STATUS.shardNNofMM.json`
- 本地分片事件日志：`.../shardNN/state/sync_events.jsonl`
- Node1 批次清单：`<campaign>/state/batches/*.sha256`
- Node1 已交付列表：`<campaign>/state/*.delivered_job_ids.txt`
- bxcpu 压缩队列：`<campaign>/compressed_queue/*.tar.gz`
- bxcpu 压缩事件：`<campaign>/compressed_queue/COMPACTION_EVENTS.jsonl`

2026-07-20 已用一个真实 Stage2 作业完成端到端验证：31 个 result 文件和
384 个 run 文件均传至 Node1，并通过批次 SHA256 校验。
