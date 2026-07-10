# Phase 2 文件夹契约

Updated: 2026-07-09

## 原则

1. MVP 产物不覆盖；Phase 2 产物进入 `experiments/phase2_5080_v1/`。
2. 原始下载数据不移动；只在 `prepared/` 写训练格式缓存。
3. 数据划分、负样本、训练配置、模型权重、评估报告分开存放。
4. 每个可复跑步骤必须有 manifest 或 audit 文件。

## 目录职责

| 目录 | 职责 | 是否可删除重建 |
| --- | --- | --- |
| `configs/` | 训练超参、数据路径、loss 权重 | 可手工编辑，不自动覆盖 |
| `data_splits/` | 样本 split、cluster split、holdout 标记 | 可重建，但必须保留 seed 和规则 |
| `prepared/` | tensor/npz/jsonl/parquet 缓存 | 可删除重建 |
| `negative_sets/` | easy/hard/decoy/PVRIG 负样本池 | 可重建，但必须可审计 |
| `checkpoints/` | `.pt` / `.safetensors` 权重 | 不自动删除 |
| `runs/` | 单次训练运行目录 | 不自动覆盖，按 run_id 新建 |
| `reports/` | 评估和中文报告 | 不自动覆盖，版本化命名 |
| `logs/` | 训练日志 | 可追加 |
| `predictions/` | 验证/测试/PVRIG 候选预测 | 可重建 |
| `audits/` | 完成审计、数据泄漏审计 | 不自动删除 |
| `src/` | Phase 2 专用代码 | 人工维护 |

## 推荐 run_id

```text
phase2_v1_YYYYMMDD_HHMMSS_seed{seed}
```

例如：

```text
experiments/phase2_5080_v1/runs/phase2_v1_20260709_150000_seed7/
```

每个 run 目录至少包含：

```text
config_resolved.yaml
train.log
metrics_train.csv
metrics_val.csv
best_checkpoint.pt
best_val_metrics.json
```
