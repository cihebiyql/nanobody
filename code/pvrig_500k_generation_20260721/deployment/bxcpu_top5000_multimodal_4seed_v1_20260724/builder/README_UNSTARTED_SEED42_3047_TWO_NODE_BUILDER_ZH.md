# Top5000 完全未启动候选两节点 handoff builder

## 用途与边界

`build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py` 从一个本地、
hash-closed 的 Top5000 双受体四 seed 源包构建独立 portable handoff。它只读
本地输入，不访问 Node1/bxcpu、不提交任务，也不修改源包。

输出目录必须尚不存在，且不能位于源包目录内部。构建过程先写同级 staging
目录，全部校验通过后才原子发布。

## 冻结输入

- `--source-package-root`：5000 candidates、40000 jobs、8 个原始 shard 的
  源 handoff 包。
- `--unstarted-candidates`：冻结的 `UNSTARTED_CANDIDATES`。
- `--started-job-ids`：冻结的 `STARTED_JOB_IDS`。
- `--output-root`：待创建的本地输出目录。
- `--created-at`：带时区的 ISO-8601 固定时间戳；它是可复现包内容的一部分。

两个 ID 输入支持 JSON 数组/带命名数组的 JSON、TSV/CSV 单列或逐行文本。
原始字节会复制到 `selection/frozen_inputs/`，同时写出排序后的 normalized
清单。生产使用时建议同时传入三个 `--expected-*-sha256` 参数锁定输入：

```bash
python3 build_top5000_unstarted_seed42_3047_two_node_handoff_v1.py \
  --source-package-root /local/path/top5000_source_handoff \
  --unstarted-candidates /local/path/UNSTARTED_CANDIDATES.tsv \
  --started-job-ids /local/path/STARTED_JOB_IDS.json \
  --output-root /local/path/top5000_seed42_3047_two_node_handoff \
  --created-at 2026-07-24T12:00:00+08:00 \
  --expected-source-ready-sha256 <64-hex> \
  --expected-unstarted-sha256 <64-hex> \
  --expected-started-sha256 <64-hex>
```

## 选择与调度不变量

1. 验证源包恰好为 5000 candidates、40000 jobs、8 shards；每个原始 shard
   恰好 625 candidates/5000 jobs，每个 candidate 恰好有四 seed × 双受体
   的 8 个源 job。
2. candidate 必须同时满足：
   - 位于冻结的 `UNSTARTED_CANDIDATES`；
   - 它的全部 8 个源 job 均不位于冻结的 `STARTED_JOB_IDS`。
3. 在每个原始 shard 内按 `(release_rank, candidate_id)` 升序选择前 250 个，
   共 2000 candidates。
4. 仅保留 seed 42/3047 与受体 8x6b/9e6y 的源 job，共 8000 jobs；源 job
   行逐字段复制，因此 `job_id`、`job_hash` 不重算。
5. node 0 接收原始 shards 0–3，node 1 接收原始 shards 4–7；每节点恰好
   1000 candidates/4000 jobs，candidate 单元不跨节点。
6. 最终 selected job 与 `STARTED_JOB_IDS` 的交集必须为零，否则不发布。

## 输出

- `selection/SELECTED_CANDIDATES.tsv`：确定性选择清单与行级绑定 hash。
- `selection/EXCLUDED_CANDIDATES.tsv`：其余 3000 candidates 及排除原因。
- `selection/SOURCE_SHARD_SELECTION_SUMMARY.tsv`：8 个原始 shard 的选择摘要。
- `selection/STARTED_JOB_OVERLAP.tsv`：通过时仅有表头。
- `inputs/selected_candidates.tsv` 与对应的 2000 个 monomer。
- `manifests/docking_jobs.tsv`：8000 个原始 job 行。
- `manifests/nodes_exact_2/node_00.tsv`、`node_01.tsv` 与 `NODE_RECEIPT.json`。
- 源 `config/`、`scripts/`、`inputs/normalized/`、可选 `inputs/source/`；
  另生成只含 seed 42/3047 的 `config/TWO_SEED_CFG_LOCK.json`。
- `READY.json`、`HANDOFF_RECEIPT.json`、`DOCKING_PLAN.json`、`README.md`、
  精确文件闭包 `SHA256SUMS`。

## 测试

测试在临时目录构造 exact-scale 5000/40000/8-shard synthetic 源包，不读取或
修改远端：

```bash
bash run_unstarted_seed42_3047_builder_tests.sh
```

测试覆盖两次构建字节级复现、最低 release rank 选择、8×250 闭包、双节点
精确计数、源 job 行/monomer hash 保留、零 started overlap、源包只读、
SHA256SUMS 精确闭包，以及某 shard 不足 250 个完全未启动候选时 fail-closed。
