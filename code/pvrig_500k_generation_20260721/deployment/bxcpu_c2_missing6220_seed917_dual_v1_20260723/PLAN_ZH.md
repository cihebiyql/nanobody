# 最新 C2 缺口 6,220 条 seed917 双受体 bxcpu 部署计划 V1

## 目标与边界

本包只为 Node1 结构门和 handoff builder 均通过后的最新 C2-only 缺口准备：

```text
6,220 candidates × seed917 × (8X6B, 9E6Y) = 12,440 jobs
```

它复用旧 priority 25k 已冻结的 HADDOCK protocol、`run_job.py`、8 节点
array controller、每节点 64 CPU / 16 个四核子任务、compact evidence 和结果回流语义。
当前版本只准备和验证部署材料，**不得提交 Slurm**。

计算结果只表示独立双受体 Docking geometry。`FAILED` 和
`FAILED_MAX_ATTEMPTS` 均为 technical NA，绝不解释为生物学阴性。

## 必须先满足的输入门

1. Node1 handoff receipt 状态为 `READY_FOR_EXTERNAL_DOCKING_SUBMISSION`；
2. receipt 的 package version 必须为
   `pvrig_c2_missing6220_seed917_dual_handoff_v1`；
3. receipt 明确：6,220 candidates、12,440 jobs、`docking_started=false`、
   `overlap1280_reuse_authorized=false`；
4. handoff `SHA256SUMS` 全量通过，receipt、job manifest 和所有 monomer
   必须是 regular non-symlink 文件；
5. job manifest 必须恰好包含每个候选的 seed917 8X6B/9E6Y 各一条；
6. protocol core、cfg、sequence、monomer 和 job hashes 必须闭合；
7. Node1 生成的新 bundle archive、manifest 和 receipt 的哈希写入一次性
   `FROZEN_INPUT_ANCHORS.json` 后，bxcpu preflight 才能 PASS。

当前 Node1 PASS receipt 尚未出现，因此仓库只保存
`PENDING_INPUT_ANCHORS.json`。缺少正式冻结 anchor 时，preflight 必须失败；
不能用旧 25k archive、旧 25k manifest 或 overlap1280 的旧结果替代。

## 分阶段实施

### A. Node1 物料化和 archive sealing（不运行 Docking）

`prepare_node1_bundle_v1.py`：

- 校验 exact PASS handoff receipt 和完整 `SHA256SUMS`；
- 验证 6,220/12,440、seed917、双受体和 candidate pair closure；
- 复制为新的 deployment root；
- 生成 8 个固定 shard，每个 1,555 jobs；
- 生成 `DEPLOYMENT_BUNDLE_RECEIPT.json` 和 `DEPLOYMENT_SHA256SUMS`。

`stage_and_upload_no_submit_v1.sh`：

- 在 Node1 运行上述 sealer；
- 生成 `.tar.zst`；
- 拉到本地 staging，再上传 bxcpu；
- 上传单独的 authoritative manifest 和部署代码；
- 生成并上传 `FROZEN_INPUT_ANCHORS.json`；
- 远端复核 archive/manifest/receipt/hash；
- 明确禁止调用 `sbatch`。

### B. bxcpu preflight 和后续人工分离提交

`preflight_c2_missing6220_12440.sh` 只有在 frozen anchors、archive、manifest、
runtime 和内部 receipt 全部闭合时才 PASS，并用 `sbatch --test-only` 验证：

```text
partition=amd_256q
nodes=1
cpus-per-task=64
mem=230G
exclusive
time=24:00:00
array=1-8%8
node_concurrency=16
```

正式提交脚本与 staging 脚本分离。只有后续独立复核后才允许人工运行
`submit_c2_missing6220_12440_eight_nodes.sh`；该脚本还要求一个绑定 frozen
anchors、submit script 和 worker script 精确 SHA256 的
`INDEPENDENT_LAUNCH_APPROVAL.json`。本包不生成该批准文件，本任务不运行提交。

### C. 执行、压缩、回流和终态审计

- worker 逐 job 最多两次 attempt；
- SUCCESS 结果使用旧 25k 的 `compact_run_evidence.py` **精确字节复用**；
- terminal 结果经本地 bounded spool 传到 Node1 并校验后，才清理 bxcpu 重 payload；
- terminal audit V2 逐 manifest job 统计：
  - `SUCCESS`：terminal success；
  - `FAILED`/`FAILED_MAX_ATTEMPTS`：terminal technical NA；
  - missing/running/bad JSON：非终态，fail closed。

## 停止线

本包完成的判据只是：代码、计划、合成测试、shell syntax 和静态协议检查
全部通过，并保持 `docking_started=false`。真正运行仍缺：

- Node1 exact PASS handoff receipt SHA256；
- 12,440-row manifest SHA256；
- sealed archive SHA256/bytes；
- deployment bundle receipt SHA256；
- 由这些字段生成的 `FROZEN_INPUT_ANCHORS.json`。
