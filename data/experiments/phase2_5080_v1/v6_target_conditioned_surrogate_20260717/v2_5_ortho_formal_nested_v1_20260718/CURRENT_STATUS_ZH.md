# V2.5 ORTHO 正式 nested 训练当前状态

- V1.2 runtime 因部署命令缺少 `node1_bundle` 路径前缀而 fail-closed；完成 job 数为 0，原 runtime/log/terminal 已原样保留。
- V1.3 仅修复该路径前缀，未改变 lane、数据、split、超参数、seed、损失、GPU 配额或指标协议。
- V1.3 不可启动包独立审计通过：301 jobs，270 GPU jobs，31 CPU jobs。
- job graph SHA256：`ea1c4c1eedf189d9542e3e73b0c0368777b4073468fd4e39535b28fd7fa24185`。
- strict V1.2.1 与 V2.5 meta evaluator 均已 PASS；watcher 已完成哈希验证并启动 scheduler。
- Node1 scheduler PID：`999220`。
- 首批 5 个 `B_CLEAN/H0` inner jobs 已全部 PASS；已验证 8 epochs、seed 43、exact-min、metrics access=0、V4-F=0、forbidden neural inputs=0。当前继续运行 `B_CLEAN/H1`；5 completed / 4 running / 292 pending（验证快照）。
- `V4-F/test32` 访问计数仍为 0。
