# V2.9 扩展 teacher 的 sequence Stage0

## 目的

在不改变 V2.7 已验证序列基线含义的前提下，支持 D0（3388）和 D1（V29 open 扩展）任意行数的 teacher，并以 whole-parent 隔离、三个训练种子比较数据扩展对早期富集的影响。

本目录只表示：

```text
VHH sequence -> independent dual-receptor computational Docking geometry surrogate
```

不表示结合概率、Kd、实验阻断概率、Docking Gold 或 frozen-test 证据。

## 相对 V2.7 的修改

- 删除 `1507 / 1085 / 184` 固定行数；
- embedding receipt 行数由 receipt 与实际 shard 内容闭合，允许缓存包含额外的 label-free 序列；
- split manifest 显式绑定 `D0` 或 `D1`，train/score 必须按完整 parent 分离；
- teacher TSV 本身只能含 open train + open development，禁止先读取 frozen truth 再过滤；
- 默认运行 `43,97,193` 三个 seed；
- 仅保留 Ridge 650M、Ridge 3B、Ridge 650M+3B、ElasticNet 650M PCA；
- 暂停已失败的 MLP 和被其污染的 naive mean5；
- 只直接预测 `R_8X6B / R_9E6Y`，`Rdual` 始终为推理时精确 `min`；
- 新增非破坏性 `--dry-run` 和可持久化 preflight receipt。

## split manifest 契约

```json
{
  "schema_version": "pvrig_v2_9_whole_parent_split_v1",
  "data_version": "D1",
  "split_id": "v29_open_snapshot_...",
  "open_only": true,
  "frozen_test_access_count": 0,
  "sealed_truth_access_count": 0,
  "training_tsv_sha256": "<64 hex>",
  "train_parents": ["..."],
  "score_parents": ["..."],
  "frozen_test_parents": ["..."],
  "train_parent_set_sha256": "<canonical parent hash>",
  "score_parent_set_sha256": "<canonical parent hash>",
  "frozen_test_parent_set_sha256": "<canonical parent hash>",
  "expected_total_rows": 3531,
  "expected_train_rows": 3372,
  "expected_score_rows": 159
}
```

三个 expected count 字段可省略；存在时会 fail-closed 校验，但不再由代码硬编码。

这里的 `3531 / 3372 / 159` 只是 2026-07-20 当前 D1 open snapshot 的估计示例，正式值必须来自冻结 manifest。当前 primary 数据边界为：

```text
D0: 3054 = 2977 train + 77 development
D1 current: about 3531 = 3372 train + 159 development
```

旧 3388 中属于 V29 frozen-test parents 的 334 行必须在生成 teacher TSV 时完全移除，不能挪到 score 集。程序要求 manifest 提供 frozen-test parent 元数据及其哈希，并证明 train、score、teacher observed parents 与其完全不相交；程序不读取这些 parents 的标签。

## Dry-run / preflight

```bash
python src/run_sequence_stage0_expanded_v2_9.py \
  --training-tsv /path/to/open_teacher.tsv \
  --expected-training-tsv-sha256 "$(sha256sum /path/to/open_teacher.tsv | cut -d' ' -f1)" \
  --split-manifest /path/to/whole_parent_split.json \
  --expected-data-version D1 \
  --esm2-650m-cache /path/to/esm2_650m_cache \
  --esm2-3b-cache /path/to/esm2_3b_cache \
  --output-dir /path/to/nonexistent/output \
  --seeds 43,97,193 \
  --dry-run \
  --preflight-json /path/to/preflight.json
```

`--dry-run` 不创建 output directory。只有 teacher/hash、parent closure、exact-min、embedding/hash/sequence closure 全部通过后才返回 `PASS_PREFLIGHT`。

## 正式训练

去掉 `--dry-run` 和 `--preflight-json` 即可。输出包含：

```text
PREFLIGHT.json
seed_43/{RESULT.json,OPEN_SCORE_PREDICTIONS.tsv,SEQUENCE_STAGE0_MODELS.joblib,SHA256SUMS}
seed_97/...
seed_193/...
MULTISEED_SUMMARY.json
SHA256SUMS
```

建议 D0、D1 分别使用不同且不可覆盖的 output directory，避免同一版本混写。

## 测试

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

测试覆盖可变行数、额外 embedding cache 行、D0/D1 绑定、whole-parent closure、dry-run 非破坏性、三个 seed、四模型及 exact-min 输出契约。
