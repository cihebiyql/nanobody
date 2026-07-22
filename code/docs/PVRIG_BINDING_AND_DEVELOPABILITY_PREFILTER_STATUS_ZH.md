# PVRIG VHH 结合先验与可开发性前筛部署状态

更新：2026-07-21

节点：`bxcpu` 全量生产，`node1` 保留早期 smoke 与后续汇总
目标：在结构预测和 Docking 之前，用已验证的快速信号做排序和风险标注，但不把它们写成 Kd、IC50 或真实阻断。

## 0. 2026-07-21 bxcpu 全量生产结果

已在 bxcpu 部署 CPU 隔离环境，并对冻结的 `394,295` 条候选完成全量预测。

```text
运行根目录:
  $HOME/pvrig_bxcpu_model_runtime_v1_20260721
环境:
  $HOME/pvrig_bxcpu_model_runtime_v1_20260721/env
本地汇总:
  /mnt/d/work/抗体/code/pvrig_500k_generation_20260721/run/
    pvrig_bxcpu_model_predictions_v1_20260721
```

| 模块 | bxcpu 资源 | 全量用时 | 结果 |
| --- | --- | ---: | --- |
| DeepNano + NanoBind | 8 节点 / 512 CPU | 10m44s（初版） | 394,295/394,295 |
| DeepNano 精确长度分桶修正 | 8 节点 / 512 CPU | 5m03s | 394,295/394,295 |
| Sapiens | 8 节点 / 512 CPU | 1m31s | 394,295/394,295 |
| AbNatiV | 8 节点 / 512 CPU | 55s | PASS 381,030；NA 13,265 |

DeepNano 生产时发现上游代码在对 `last_hidden_state` 做 mean/max/min 池化时没有屏蔽 padding，因此同一条序列的分数会轻微受同 batch 其他序列长度影响。生产 V2 改为“相同 VHH 长度分桶后批处理”，对 256 条 smoke 比较 batch=32 和 batch=1：

```text
max_abs_diff = 7.75e-07
tolerance    = 1e-06
status       = PASS
```

当前权威 binding 文件是 V2：

```text
binding_priors_all_v2.tsv.gz
SHA256 3f0aa87ce8b89dfec9906995a8328ee014147c0422514756adbb94fb873755ce
```

修正后 DeepNano 分布：均值 `0.14429`，中位数 `0.13356`，范围 `0.00939–0.56701`。与初版 Pearson 相关为 `0.99691`，但初版已标记为 superseded。

AbNatiV 的 `13,265` 条 NA 均为上游 AHo 表示不支持插入位点，必须保留为技术/适用性 NA，不得改写成低可开发性或生物学阴性。

统一前筛表：

```text
pvrig_prefilter_all_v1.tsv.gz
records 394,295
SHA256 273e85d6a46d55964997418e48dd8063f74d1e6b6db3f2c98c83db3f4b61fcd5
```

该表按 `candidate_id` 一对一合并了候选序列与 provenance、序列风险、DeepNano/NanoBind、Sapiens 和 AbNatiV；五个输入的 ID 集合均严格一致。

## 1. 当前可用性矩阵

| 模型/工具 | 代码/权重 | Node1 环境 | PVRIG smoke | 实测速度 | 当前用法 |
| --- | --- | --- | --- | ---: | --- |
| DeepNano 8M model 1 | 完整 | `/data/qlyu/anaconda3/envs/deepnano` | HR-151 + 8X6B chain B 通过 | 10 条 `7.31-8.51 s` | 快速 weak binding prior |
| NanoBind-seq | 完整 | 复用 DeepNano 环境 | HR-151 + PVRIG 通过 | 10 条 `7.08-7.52 s` | 第二个 weak binding prior |
| NanoBind-affi | 完整 | 复用 DeepNano 环境 | HR-151 + PVRIG 通过 | 10 条 `18.73-19.89 s` | 通用 reference-anchored affinity range，默认后移 |
| NABP-BERT | 本地有代码和 TF checkpoint | **Node1 未部署** | 无 | 无 | 列保留为空，不伪造结果 |
| AbNatiV VHH | 完整 | SSD `vhh-eval` 环境 | HR-151 通过 | 1 条 `7.52 s` | VHH naturalness/developability |
| Sapiens | 完整 | SSD `vhh-eval` 环境 | HR-151 通过 | 1 条 `4.30 s` | human-likeness 独立列 |
| vhh-eval/ProtParam/liability | 完整 | SSD `vhh-eval` 环境 | HR-151 通过 | 1 条 `0.45 s` | 理化、PTM、聚集风险基础特征 |
| TNP | 完整 | SSD wrapper，部分模型资产仍在 `/data` | HR-151 通过 | 1 条 `21.07 s` | 只对后期 shortlist 补跑 |

NABP-BERT 未跑通的具体原因是上游代码依赖 Python 3.7/TensorFlow 1.x 和 `tf.contrib`，Node1 当前没有可用环境，也没有定制 FASTA 推理 wrapper。

## 2. 实际运行位置

```text
DeepNano root:
  /data/qlyu/software/DeepNano
DeepNano wrapper:
  /data/qlyu/software/DeepNano/run_deepnano_predict.sh

NanoBind root (Node1 本地 SSD):
  /data1/qlyu/software/NanoBind
NanoBind wrapper:
  /data1/qlyu/software/NanoBind/run_nanobind_predict.sh

Developability/QC root (Node1 本地 SSD):
  /data1/qlyu/software/vhh_eval_tools
Binding prior 统一入口:
  /data1/qlyu/software/vhh_eval_tools/bin/vhh-binding-prior
Large-scale cascade:
  /data1/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen
```

2026-07-19 E2E smoke 证据：

```text
/data1/qlyu/model_smoke/binding_prior_e2e10_20260719/
/data1/qlyu/model_smoke/cascade_binding_prior_e2e_20260719/
/data1/qlyu/model_smoke/developability_hr151_20260719/
/data1/qlyu/model_smoke/tnp_hr151_20260719/
/data1/qlyu/model_smoke/competition_qc_hr151_20260719/
```

## 3. 新的 binding prior 输出合同

```text
candidate_id
deepnano_binding_prior
nabp_binding_prior
nanobind_binding_prior
nanobind_affinity_range
binding_model_count
binding_prior_consensus
binding_model_disagreement
binding_prior_status
binding_prior_source
```

语义：

- 缺失模型留空，不能当作 0。
- `binding_prior_consensus` 是当前可用概率列的简单均值，只用于排序。
- `binding_model_disagreement=max-min`；只有一个模型时留空。
- `nanobind_affinity_range` 不参与概率均值，不改名为预测 Kd。
- 任一 binding model 不能改写 sequence/QC hard gate，也不能产生 blocker 阳性。

HR-151/PVRIG smoke 中：

```text
deepnano_binding_prior = 0.10236786
nanobind_binding_prior = 0.54870957
binding_prior_consensus = 0.32553871
binding_model_disagreement = 0.44634172
binding_prior_status = MULTI_MODEL_DISAGREEMENT
nanobind_affinity_range = [9e-09,1e-08] M
```

这个结果的意义是“模型分歧，适合作 acquisition/review 样本”，不是 HR-151 不结合，也不是它的实验 Kd。

## 4. 推荐生产顺序

```text
FASTA 去重 + 长度/字符 hard gate
  -> DeepNano 8M + NanoBind-seq（GPU 并行）
  -> binding consensus + disagreement 排序
  -> full QC: official validator + AbNatiV + Sapiens
  -> geometry shortlist: 补 TNP，可选补 NanoBind-affi
  -> VHH 结构 + 双受体 Docking
  -> 多目标组合
```

对 50 万条库，先运行 cascade `prepare` 得到 `unique_candidates.fasta`，再分 chunk 运行 binding prior。NanoBind-affi 和 TNP 不应默认全量运行。

## 5. 可开发性/纯度输出

`portfolio_ranked.tsv` 现在独立保留：

```text
AbNatiV_VHH_score
AbNatiV_FR_VHH_score
Sapiens_mean_self_probability
Sapiens_num_suggested_mutations
TNP_flags
developability_score
expression_purity_risk_score
```

`expression_purity_risk_score` 是基于 pI、电荷、GRAVY、instability、疏水串、Cys、polyreactivity 和 TNP 的计算代理分，不是实测纯度或表达量。

## 6. 验证结果

本地与 Node1 目标测试：

```text
12 tests PASS
```

Node1 完整 E2E：

- 10/10 DeepNano 输出完整。
- 10/10 NanoBind-seq 输出完整。
- 10/10 NanoBind-affi 输出完整。
- prior table 10/10 对齐并写入 receipt。
- `vhh-large-scale-screen --binder-summary` 成功透传全部 prior 列，binding prior 未绕过 `hard_fail`。
