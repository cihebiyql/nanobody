# V2.11 full10644 纯 B_CLEAN_TARGET_ATTENTION challenger

## 状态

`IMPLEMENTED_NOT_LAUNCHED_GRAPH_MATERIALIZATION_IN_PROGRESS`

该 runner 复用冻结 V2.5 正交模型的 **B clean-attention** 路径：

```text
sequence tokens
  + label-free VHH monomer residue graph
  + fixed public 8X6B / 9E6Y target graphs
  -> direct R8 / R9
  -> inference exact min(R8, R9)
```

## 数据与输入防火墙

- D1 whole-parent：train 9,849 / development 795；54 train parents / 10 development parents；交集 0。
- 模型 forward 只允许 9 项冻结 allowlist。
- `candidate_id`、parent 只用于 split/audit/prediction row，不进入 batch forward。
- M2、126D、C2、coarse pose、contact marginal/pair、teacher_source、Docking pose/result 均无 CLI 输入路径，也不进入模型。
- B lane 不实例化 contact module；optimizer 中 contact parameter 数必须为 0。
- 训练固定 8 epochs，无 early stopping、无 development 选择；development 仅 final evaluation。
- 主输出为 R8/R9，Rdual 始终用预测 R8/R9 的逐行 exact min。

## 4×4090 并行策略

D1 只有一个合法 whole-parent split，不能凭空构造四个 folds。因此四张 4090 分别运行固定 seed：

```text
GPU0 seed43
GPU1 seed917
GPU2 seed1931
GPU3 seed3253
```

每个任务独立输出；四个任务全部 PASS 后，launcher 调用独立 evaluator 汇总。不会按 development 指标选择 seed，而是同时报告四个 seed，并对 R8/R9 求 seed mean 后再取 exact min。

## 启动（当前未执行）

等待 full10644 graph materialization receipt 到位后：

```bash
export GRAPH_CACHE_DIR=/path/to/full10644/graph_cache
export MODEL_PATH=/path/to/frozen/esm2_t33_650M
export MODEL_IDENTITY_FILE=/path/to/model_identity.json
export EXPECTED_MODEL_SHA256=<sha256_from_frozen_model_receipt>
export OUTPUT_ROOT=/path/to/v211_clean_attention_4seed

./launch_4gpu_clean_attention_seeds_v1.sh
```

默认每卡 batch 8、gradient accumulation 4、bf16、8 epochs。launcher 只有在完整 graph materialization receipt 存在时才启动。

## 输出

每个 seed 目录：

- `development_predictions.tsv`
- `clean_attention_head_final.pt`（仅 head，不复制 650M backbone）
- `epoch_history.json`
- `RESULT.json`

其中 `RESULT.json` 已包含单 seed 的 early-enrichment 表、top20 recall、top10 EF、binary NDCG 和 within-parent top20 recall。

四 seed 全部完成后额外生成 `EARLY_ENRICHMENT/`：

- `EARLY_ENRICHMENT.json`：四 seed 独立指标、R8/R9 均值 ensemble 指标、seed 稳定性；不做 seed 选择。
- `ensemble_development_predictions.tsv`：先均值 R8/R9，再逐行 exact min。
- `SHA256SUMS`

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
