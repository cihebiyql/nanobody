# V2.20 V1.3.5 Node1 Stage-A-only watcher

本 watcher 只执行已经独立批准的技术 Stage-A：

```text
等待 Node1 连通和单张空闲 GPU
→ 校验 V1.3.5 freeze 与 independent approval 哈希
→ 上传 exact 20-file frozen package 到全新远端路径
→ 运行 Python3.11 exact 102+46 tests
→ 五折 shared-calibration 一次物料化、C0/C1 load-only 验证
→ 回传 Node1 Stage-A receipt
```

边界：

- 不启动任何 fold training arm；
- 不调用 optimizer、训练模板或 `sbatch`；
- Stage-A PASS 后仍然只进入独立 Stage-B 训练审批；
- Node1 不可达、GPU 不足、远端路径已存在、哈希漂移或任一测试失败时均 fail closed；
- V1.3.4 已被独立审查拒绝，绝不部署。

冻结锚点：

```text
V1.3.5 implementation freeze:
07c8463689d6baa0da1ebd0c1d4440fc0315c8e8edb4e1b72415434567dc0804

Independent Stage-A-only approval:
91fc04f0cbe2441c76318eac20ba0f41b8525eca1a27bd24465a0963613c97c8
```

本地 watcher 使用独立 tmux：

```text
pvrig-v220-v135-node1-stagea
```

运行状态保存在 `runtime/WATCHER_STATUS.json`；runtime 不纳入 Git，也不作为训练证据。
