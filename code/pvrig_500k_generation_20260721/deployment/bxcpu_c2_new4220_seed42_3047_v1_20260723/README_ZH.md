# C2 新增 4,220 条补充双种子 Docking

- 候选：4,220
- 受体：8X6B、9E6Y
- 新增独立种子：42、3047
- 作业：16,880
- 前置门禁：当前 4,220+2,000 批次的终态审计作业 `11943297` 必须成功
- 资源：bxcpu 8 个独占 64 核节点，每节点并发 16 个 4 核 Docking
- 技术失败语义：NA，不作为低分或负样本

调度链：

1. 当前 24,880 jobs 全部终态；
2. 当前终态审计通过；
3. 新包静态协议验证和单 job smoke；
4. 8 节点数组运行 seed 42/3047；
5. 独立终态技术审计；
6. 结果经 bounded spool 持续同步到 Node1。

该批结果仅提供计算 Docking 几何重复性证据，不代表结合、Kd、IC50、
表达、纯度或实验阻断。

## 30 分钟守护

守护会每 1,800 秒检查：

- 当前 4,220+2,000 批次以及 seed42/3047 补充批次的 Slurm 和结果闭合；
- Node1、本地 spool 与 bxcpu 文件系统剩余空间；
- 8 个分片同步进程及其心跳；
- 已结束但结果不完整的数组，并用相同冻结协议执行 resume-safe 补跑；
- 失败的补充批次 preflight，并自动重新提交；
- Node1 空间低于 25 GiB 时暂停同步、保留 bxcpu 权威副本，恢复到 50 GiB 后重启同步。

运行状态：

```text
watchdog_runtime/LATEST.json
watchdog_runtime/watchdog_history.jsonl
watchdog_runtime/watchdog.nohup.log
```

只有同时满足以下条件才会写出
`watchdog_runtime/ALL_DOCKING_COMPLETE.json`：

- 当前 24,880 jobs 全部终态且终态审计成功；
- seed42/3047 的 16,880 jobs 全部终态且终态审计成功；
- 两批所有 status 已同步到 Node1；
- Node1 成功结果数与 bxcpu 经审计的 SUCCESS 数完全一致；
- 没有巡检错误。

tmux 会话：

```text
pvrig-all-docking-watchdog-30m
```

系统 crontab 还会每 30 分钟执行一次
`start_all_docking_watchdog_30m.sh`。如果 tmux 守护意外退出，cron 会自动
恢复；如果仍在运行，则启动脚本幂等退出，不会产生第二个守护实例。
