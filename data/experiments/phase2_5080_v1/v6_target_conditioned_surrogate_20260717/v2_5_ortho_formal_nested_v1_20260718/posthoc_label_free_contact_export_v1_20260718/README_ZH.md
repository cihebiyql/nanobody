# V2.5 outer-refit label-free contact 重放与导出 V1

## 目的

在 V2.5 formal nested 训练完成后，仅使用：

- 冻结的 VHH sequence panel；
- label-free VHH 单体图缓存；
- 固定 8X6B/9E6Y PVRIG 图；
- 冻结 ESM2 backbone；
- `E_DECOUPLED_CONTACT_SHARED` 三个 outer-refit head checkpoint；

重放每个 outer-test 候选的预测，并导出：

- `R8/R9/Rdual`；
- 2D `contact_composite`；
- 完整 14D `pair_summary`；
- 三 seed 的均值和总体标准差（`ddof=0`）。

## 证据边界

本工具不读取 Docking teacher scalar、contact teacher、pair-contact teacher、V4-F/test32 或任何实验标签。输入 sequence panel 必须严格只有：

```text
candidate_id
sequence
sequence_sha256
parent_framework_cluster
outer_fold
```

出现额外列即 fail-closed。所有输入和 checkpoint 均由 contract 中的 SHA256 约束。

完整 14D 仅是 **future-version diagnostic feature**。它不能进入当前 V2.5 primary performance selection，也不能用于事后选择 B/E-detached/E-shared lane。当前 V2.5 若需要 contact meta 输入，只能使用训练时已经持久化的 `contact_score_R8/R9`，并从三份 immutable per-seed raw prediction TSV 重建均值。

## 输出

```text
OUTER_TEST_SEED_FEATURES.tsv
OUTER_TEST_ENSEMBLE_FEATURES.tsv
EXPORT_RECEIPT.json
SHA256SUMS
```

`OUTER_TEST_SEED_FEATURES.tsv` 保存每个 seed 的完整重放结果；`OUTER_TEST_ENSEMBLE_FEATURES.tsv` 保存逐候选 mean/std。

## 使用流程

1. 从三份 terminal outer-refit job directory 构建 contract：

```bash
python src/build_export_contract_v1.py \
  --outer-fold 0 \
  --label-free-panel /path/open1507.label_free.tsv \
  --graph-cache-dir /path/graph_cache \
  --target-graph-pt /path/fixed_target_graphs.pt \
  --model-source /path/residue_model_v2_5_ortho.py \
  --model-path /path/esm2_650m \
  --model-identity-file /path/model_identity.json \
  --expected-model-identity-sha256 <sha256> \
  --split-manifest /path/outer_0.json \
  --outer-refit 43:/path/o0.E_DECOUPLED_CONTACT_SHARED.s43.outer_refit \
  --outer-refit 97:/path/o0.E_DECOUPLED_CONTACT_SHARED.s97.outer_refit \
  --outer-refit 193:/path/o0.E_DECOUPLED_CONTACT_SHARED.s193.outer_refit \
  --output-json /path/export_contract.json
```

2. 执行导出：

```bash
python src/export_outer_label_free_features_v1.py \
  --contract-json /path/export_contract.json \
  --output-dir /path/new_output_dir \
  --device cuda
```

输出目录必须不存在；任何 hash、lane、seed、split、candidate closure 或重放差异都会阻止发布。

