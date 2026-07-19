# V2.7：10 万条 VHH 多模型召回选择器（label-free）

## 1. 用途与边界

该工具把已完成快速 QC 和多模型推理的候选池，按固定配额收敛为后续结构预测或 Docking 池：

```text
100,000 条候选
→ 多模型 exploitation
→ 单模型 rescue
→ 模型分歧主动学习
→ parent/CDR3/patch/method 多样性
→ 分层随机 sentinel
→ 默认 20,000 条 Stage-1 池
```

工具只使用配置中显式声明的预测分数、不确定性、provenance、分组和 QC 字段。它**不读取** Docking truth、实验标签、sealed holdout 或 prospective test；输出也不能解释成结合、Kd、实验阻断或最终提交排名。

## 2. 文件

```text
src/select_100k_label_free_multimodel.py      选择器
configs/example_100k_selector_config.json    20K 示例冻结配置
tests/test_select_100k_label_free_multimodel.py
```

## 3. 输入约束

输入为一张 CSV/TSV。推荐至少提供：

```text
candidate_id
sequence / sequence_sha256
各模型 prediction / uncertainty
parent_framework_cluster
cdr3_cluster
target_patch_id
design_method
fast_qc_pass / hard_fail / developability_score
```

默认 `allow_extra_columns=false`，输入列必须全部在配置中声明。这样能防止把未声明的 Docking 派生量悄悄带入选择器。即使启用 extra columns，只要表头出现 `R_dual_min`、`docking_truth`、`experimental_blocking` 等 truth 字段也会 fail-closed。

输入/配置/输出路径若包含 `sealed`、`test32`、`v4_f`、`prospective_holdout`、`docking_truth` 或 `teacher_label` 也会在读取前拒绝。

## 4. 选择算法

### 4.1 统一尺度

每个模型在当前 QC 合格且去重后的 label-free 池内转换为 tie-aware average-rank percentile。模型 utility 为：

```text
score_rank_utility - uncertainty_penalty × uncertainty_rank
```

融合分数是按配置权重计算的 utility 均值；它不把不同模型的原始数值尺度直接相加。

### 4.2 固定通道

选择顺序和配额固定为：

1. `exploitation`：多模型 rank ensemble；
2. `single_model_rescue`：各单模型榜首轮转召回；
3. `disagreement`：模型 rank spread 大且至少一个模型较高；
4. `diversity`：按 parent/CDR3/patch/method 组合轮转；
5. `random_sentinel`：按 patch、method 和 ensemble score bin 分层，再用冻结 SHA256 seed 抽取。

同一候选命中多个通道时只保留一次，通道继续向后扫描回填。所有通道共享配置中的 per-group cap。排序并列固定用 `candidate_id` 升序打破；随机 sentinel 使用冻结 seed 的 SHA256，不依赖输入行顺序。

### 4.3 去重

`candidate_id` 必须唯一。可通过 `dedup_key_columns` 按 `sequence_sha256` 等键进行输入去重；同 key 使用字典序最小的 candidate ID 作为代表，并在 manifest 中记录被删除行数。

## 5. 运行

```bash
python3 src/select_100k_label_free_multimodel.py \
  --input /path/to/candidate100k_label_free_scores.tsv \
  --config configs/example_100k_selector_config.json \
  --output-dir /path/to/new_immutable_selection_dir
```

输出目录必须不存在。成功时原子发布：

```text
selection.tsv
selection_manifest.json
SHA256SUMS
```

`selection.tsv` 包含 `selection_channel`、`selection_reason`、融合/分歧/不确定性 utility、best model 和稳定 selection hash。manifest 记录输入与配置哈希、QC/去重计数、实际通道数量、cap 命中、回填计数、选择文件哈希以及零 truth/sealed access 声明。

## 6. 测试

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

测试覆盖固定配额、全局 cap、去重、QC、稳定 tie-break/输入行顺序不变性、truth 字段与 sealed 路径拒绝、未声明列拒绝、缺失单模型以及无法满足配额时的原子失败。

## 7. 生产冻结前必须做的事

1. 将 10 万候选的实际列名写入新的 versioned config，不直接覆盖示例；
2. 在任何候选分数曝光前冻结 config 与 SHA256；
3. 用 open whole-parent OOF 结果决定模型权重与配额，不使用 V4-F/test32；
4. 先运行 1,000 行 smoke，再运行完整 100K；
5. 校验 `SHA256SUMS`、配额、cap、去重计数和 `label_access`；
6. Docking 回流后以新增 teacher 训练下一版模型，但不得回写改变本次选择 manifest。
