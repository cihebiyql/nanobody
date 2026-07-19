# PVRIG VHH 结合先验与可开发性前筛部署状态

更新：2026-07-19  
节点：`node1`  
目标：在结构预测和 Docking 之前，用已验证的快速信号做排序和风险标注，但不把它们写成 Kd、IC50 或真实阻断。

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
