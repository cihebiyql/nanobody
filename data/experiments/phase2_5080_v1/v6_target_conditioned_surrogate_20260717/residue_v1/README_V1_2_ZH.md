# residue_v1 V1.2 生产修订

V1.2 修复 verifier 在 V1.1 中发现的两个生产 P0。V1.1 所有代码和 freeze 字节保持
不变，supersession 见 `IMPLEMENTATION_FREEZE_V1_1_SUPERSEDED_PREPRODUCTION.json`。

## P0-1：完整 resume binding

V1.2 在任何模型构造或训练之前生成规范化 result-affecting binding。它覆盖：

- training、contact、receipt、独立验证、implementation freeze、split manifest 哈希；
- outer fold、observed inner folds、精确有序的 126 特征；
- ridge alpha；
- backbone kind/mode、模型路径与 identity、LoRA 全配置、gradient checkpointing；
- fusion、dropout、residual scale、contact pooling 模式；
- 全部 loss 参数；
- epoch、batch、parent chunk、gradient accumulation；
- head/LoRA LR、weight decay、warmup、gradient clip、precision、seed；
- device、150GB safe-stop、180GB checkpoint guard。

已有 preflight、stage checkpoint 或 terminal 的 `binding_hash` 与当前 binding 不一致时，
立即 fail closed；即使 terminal 已存在，也不会跳过校验直接返回。

## P0-2：严格使用冻结 promotion gate

独立 collector 现在精确实现
`PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json`：

```text
global Spearman: residue > M2
parent-centered Spearman: residue >= M2
Top20 recall: residue >= M2
parent bootstrap Spearman delta:
    positive_fraction >= 0.80
    median_delta_spearman > 0
```

同时报告 `median_delta_spearman`、`positive_fraction`、`ci95_lower`、`ci95_upper`。
CI 不参与 gate。MAE 只作为 diagnostic，不参与 promotion。

## 入口

训练：

```text
src/train_nested_residue_surrogate_v1_2.py
```

OOF collector：

```text
src/collect_residue_oof_v1_2.py
```

命令参数与 V1.1 相同，但必须把 implementation freeze 改为：

```text
IMPLEMENTATION_FREEZE_V1_2.json
```

当前状态仍为 `IMPLEMENTED_CPU_VALIDATED_NOT_REMOTE_TRAINED`。

