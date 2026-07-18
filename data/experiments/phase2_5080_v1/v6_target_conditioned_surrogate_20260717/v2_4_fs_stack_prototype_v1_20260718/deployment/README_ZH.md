# Residue V2.4 Node1 部署包

该目录实现严格的四门执行合同：

```text
open-only、optimizer-step 前 gradient calibration receipt 冻结
        ↓ 独立门
implementation freeze 绑定 manifest/runner/trainer/校准权重
        ↓ 独立门
四 lane Node1 tiny smoke 全部通过并停止
        ↓ 独立门
GPU 1/2/4/5 四 lane 并行，每条 lane 内 outer fold 0..4 顺序执行
```

每个进程最多 8 个 CPU threads。部署只使用开放 V4-D/V4-H 计算 Docking 监督、label-free VHH/target 图、冻结 ESM2 和开放 contact teacher；禁止访问 V4-F/test32。

`--dry-run` 不创建 runtime。`--execute-smoke` 只跑 tiny smoke 并写入 `SMOKE_RECEIPT.json`，绝不自动进入 outer。`--execute-outer` 必须独立重新调用，并同时验证 implementation freeze、smoke receipt 以及哈希冻结的 `CALIBRATION_RECEIPT.json`。

当前交付仍是 **prefreeze**：`run_open_only_prestep_calibration_v1.py` 会真实启动 C/D 两个 contact lane，在构造 optimizer 之前扫描冻结 grid，且自动生成 `CALIBRATION_RECEIPT.json`；不允许人工填写权重。`V2_4_NODE1_PREFREEZE_MANIFEST_V1.json` 将校准状态固定为 pending，`DRY_RUN_CALIBRATION_PENDING_V1.json` 闭合两个真实校准命令。`DRY_RUN_PREFREEZE_PENDING_CALIBRATION_V1.json` 则证明 4 个 smoke 命令可在后续冻结后执行，但 20 个 outer job 只有规划、可执行命令数为 0。校准完成后仍必须先生成独立 `IMPLEMENTATION_FREEZE_V2_4.json`，才能创建 production runtime 和运行 Node1 smoke。

证据边界：模型预测是独立 8X6B/9E6Y computational Docking geometry surrogate，不是结合概率、Kd、实验阻断概率或 Docking Gold。
