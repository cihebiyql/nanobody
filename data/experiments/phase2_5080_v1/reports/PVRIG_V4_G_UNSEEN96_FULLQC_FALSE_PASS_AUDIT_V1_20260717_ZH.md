# PVRIG V4-G unseen96 Full-QC 假 PASS 独立审计（V1）

## 结论

当前 V4-G **不能视为 Full-QC 完成**。

冻结终态为：

```text
FAIL_V4_G_FULL_QC_NOT_COMPLETE_FALSE_PASS_RECEIPT
```

`status/runner.complete.json` 虽声称 `returncode=0` 和
`PASS_V4_G_UNSEEN96_FULL_QC_COMPLETE`，但它与 cascade 状态、chunk
闭合产物、日志终点及当前进程状态不一致。可信解释是：两个 Full-QC
chunk 均在 Sapiens 子流程中被异常终止，而 runner 的 EXIT-only trap
没有先验证产物闭合，将异步终止误记成了 PASS。

> 证据边界：这里只审计 VHH 序列与可开发性 QC。没有 docking、结合、
> affinity、competition、PVRIG-PVRL2 阻断或实验 blocker 标签含义。

机器可读审计：

```text
experiments/phase2_5080_v1/audits/phase2_v4_g_unseen96_fullqc_false_pass_audit_v1_20260717.json
SHA256 42fa50ed6c796ec311f128650c886d7e8f839a18dbadff76d2721c6bb792157c
```

## 一、相互矛盾的终态

| 证据 | 实际状态 |
|---|---|
| `status/runner.complete.json` | 声称 PASS、returncode 0；SHA `3c4200f2...`；23:07:06 写入 |
| `cascade/cascade_state.json` | `full.status=running`、2 chunks；没有 `merge_full`；SHA `a38af895...` |
| `status/watcher_status.json` | 仍是 `RUNNING_FULL_QC`，没有到达 waiter 的 COMPLETE 更新 |
| `logs/full_qc_runner.log` | 最后只记录 22:08:31 进入 `stage=full` |
| 当前进程 | 2026-07-17 10:22:24 CST，相关匹配进程为 0；两个记录 PID 均死亡 |

因此 `runner.complete.json` 不是可消费的 Full-QC 完成证据。

## 二、实际完成到哪里

已可靠完成：

- unseen96 输入 96 条；
- fast merged 96 行；
- fast hard-pass / Full-QC shortlist 24 条；
- 两个 Full-QC chunk，各 12 条；
- 两个 chunk 的官方 validator、VHH numbering 和 AbNatiV 已产生部分结果。

未完成：

- 两个 chunk 均无 `complete.json`；
- 两个 chunk 均无 `runner.stdout.log`、`runner.stderr.log`；
- 均无 `portfolio_ranked.tsv`、`competition_qc_details.json`、
  `stage_timings.tsv`、`screen_summary.tsv`、`screen_details.json`；
- 两个 Sapiens 日志只记录启动命令，没有 `[exit_code]`；
- 两个 Sapiens CSV 均不存在；
- 顶层无 `full_chunk_status.tsv`、`full_merged.tsv`、
  `geometry_shortlist.*`、`full_qc_summary.json`；
- 两份 Full-QC lineage 输出均不存在。

Sapiens 日志最后更新时间为 22:55:18–22:55:19，假 PASS receipt 在
23:07:06 才出现。这表明工作在 Sapiens 运行期间被截断，而不是完成后仅忘记更新状态。

## 三、为什么正常 rc=0 可以排除

canonical cascade 源码：

```text
/data1/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py
SHA256 051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a
```

正常控制流要求：

1. chunk 子命令返回 0；
2. `portfolio_ranked.tsv` 行数等于 chunk 输入数；
3. 写入 chunk `complete.json`；
4. 所有 futures 结束后把 full stage 写为 complete 或 failed；
5. 运行 `merge_full` 并生成顶层输出。

这些条件均未满足，所以 Python cascade 不可能通过正常路径返回成功。

## 四、假 PASS 机制

runner：

```text
/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_v1_20260716/run_full_qc_node1.sh
SHA256 e5d8630f7b95a022a8bf675e98222479125a0a98088792ffb0c6b2b355df94dd
```

它只注册了：

```bash
trap 'rc=$?; terminal_status "$rc"; exit "$rc"' EXIT
```

但没有单独处理 `HUP`、`INT`、`TERM`，也没有在 `rc=0` 时验证 cascade
闭合。Shell 在等待子进程时被异步终止，EXIT trap 可能读到前一条成功命令的
状态 0，于是无条件写出 PASS。

该机制能够解释现存证据；但 **现有日志不能证明确切信号或来源**。不得将其
归因于特定用户、agent、cgroup、调度器、OOM 或系统服务。审计窗口内也没有发现
可归因的 kernel/OOM 日志。

## 五、最小安全恢复建议

本审计没有启动恢复。后续应：

1. 保留现有 V1 root、partial outputs、假 PASS receipt 和 cascade state 作为失败证据；
2. 使用新 versioned recovery root，绑定同一 96 条输入和同一 24 条 shortlist；
3. 不替换候选、不加入标签、不改变 sequence/developability QC 语义；
4. 为 runner 增加 HUP/INT/TERM 非零终态处理及幂等 terminal writer；
5. PASS 前强制验证：
   - `full=complete` 和 `merge_full=complete`；
   - 2/2 chunk complete marker；
   - 每 chunk 12 行 portfolio；
   - `full_chunk_status.tsv` 两行 complete；
   - `full_merged.tsv` 恰好 24 个唯一 ID，等于 fast hard-pass 集合；
   - summary 和两份 lineage 输出存在且哈希闭合；
6. 使用不会随临时 agent 进程组消失的持久执行面，并在发布前独立验证闭合。

## 六、本次非操作声明

```text
Node1 远端文件修改：0
Node1 新启动进程：0
Node1 信号操作：0
修复任务启动：否
```
