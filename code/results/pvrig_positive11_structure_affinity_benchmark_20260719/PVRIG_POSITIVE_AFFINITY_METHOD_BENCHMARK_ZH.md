# PVRIG 已有阳性 VHH 计算亲和力方法实测

## 1. 结论先行

本次用 **11 条已有 PVRIG 阳性 VHH** 做了真实结构重打分，其中 10 条有已知 Kd，共使用 99 个已有 HADDOCK pose（每条 9 个）。

结果不支持把任何一个方法当成“可靠的 Kd 预测器”：

1. **PRODIGY** 有弱的跨候选方向信号（Spearman=0.310），但绝对 Kd 中位误差为 2.63 个 log10 单位，约差 427 倍。只能作 weak prior，不能写成预测 Kd。
2. **FoldX 独立 docking pose 的 AnalyseComplex** 跨候选排序更弱（Spearman=0.236），不建议用于不同 VHH 的绝对亲和力比较。
3. **FoldX 固定 parent pose 的多突变绑定 ΔΔG** 在 20->20H5 和 30->30H2 上方向正确，但总体只有 2/5 方向正确，对 39 家族失败，对 151H7 基本返回 0。
4. **Graphinity** 的官方单点推理已成功部署，但它只能处理单个界面突变。当前 79 个 parent->child 替换中只有 9 个在固定 pose 的 4 A 界面内（11.4%）。将这些单点分数加和后，4 个有 Kd 的可评估 pair 只有 1/4 方向正确，Spearman=-0.949。**当前不能用于候选排名。**

因此，当前亲和力路线的合理位置是：**PRODIGY 作弱先验，FoldX 固定 pose ΔΔG 作同 parent 诊断，不设亲和力 hard gate。**

## 2. 数据和评估口径

- 阳性面板：11 条；10 条有 Kd，5 条有 IC50。
- 结构输入：每个候选固定取 9 个已有 HADDOCK pose，共 99 个；本次没有重新 docking。
- 绝对排序：将 PRODIGY 中位 pKd、FoldX 中位 interaction energy 与实验 pKd 比较。
- 相对排序：同 parent 的 humanized child 在 parent 固定 pose 上建模，实验值按 `RT ln(Kd_child/Kd_parent)` 计算。
- 方向判定：ΔΔG < -0.1 kcal/mol 为变强，> +0.1 为变弱，其余为中性。
- 技术边界：这些是 pose-dependent 计算分数，不是实验 Kd，也不等于阻断效果。

## 3. PRODIGY 绝对 Kd 结果

| 阳性 | 实验 Kd (nM) | PRODIGY 中位 Kd (nM) | |pKd 误差| | FoldX interaction 中位 |
|---|---|---|---|---|
| 20H5 | 0.0698 | 20.0 | 2.46 | -8.87 |
| PVRIG-151_HR151 | 0.2000 | 98.0 | 2.69 | -7.85 |
| PVRIG-20 | 0.2360 | 110.0 | 2.67 | -10.94 |
| 39H4 | 0.4820 | 460.0 | 2.98 | -5.45 |
| 39H2 | 0.6920 | 540.0 | 2.89 | -6.22 |
| PVRIG-39 | 0.6960 | 150.0 | 2.33 | -5.96 |
| PVRIG-30 | 0.7230 | 540.0 | 2.87 | -5.86 |
| 151H7 | 1.2000 | 270.0 | 2.35 | -6.78 |
| 30H2 | 1.9200 | 750.0 | 2.59 | -7.51 |
| PVRIG-38 | 2.1700 | 19.0 | 0.94 | -8.57 |

统计：

- PRODIGY：Pearson=0.389，Spearman=0.310，pKd MAE=2.478；同家族两两方向 4/6。
- FoldX absolute interaction：Pearson=0.366，Spearman=0.236；同家族方向 2/6。
- PRODIGY 预测的 Kd 全部比实验值弱，不能直接填入“预测 Kd”字段。

## 4. FoldX 固定 pose 多突变绑定 ΔΔG

| pair | 突变数 | 实验 ΔΔG | FoldX 中位 ΔΔG | 实验/预测方向 |
|---|---|---|---|---|
| PVRIG-20 -> 20H5 | 12 | -0.722 | -0.743 | stronger/stronger |
| PVRIG-30 -> 30H2 | 20 | 0.579 | 1.331 | weaker/weaker |
| PVRIG-39 -> 39H2 | 15 | -0.003 | 1.938 | neutral/weaker |
| PVRIG-39 -> 39H4 | 12 | -0.218 | 1.521 | stronger/weaker |
| PVRIG-151_HR151 -> 151H7 | 8 | 1.062 | 0.000 | weaker/neutral |
| PVRIG-151_HR151 -> 151H8 | 12 | NA | 0.228 | unknown/weaker |

总体：Pearson=0.129，Spearman=0.100，MAE=1.103 kcal/mol，方向 2/5。样本数只有 5，只能看成定性诊断。

## 5. Graphinity 单界面突变实测

Graphinity 官方 example smoke 已成功；本次又对 9 个 pair-specific 界面突变、3 个 FoldX 构象重复，共 27 个 WT/mutant 对成功推理。

| pair | 界面突变数 | 突变 | 实验 pair ΔΔG | Graphinity 加和 | 实验/预测方向 |
|---|---|---|---|---|---|
| 20_to_20H5 | 3 | DA1E,RA26G,DA103E | -0.722 | 0.969 | stronger/weaker |
| 30_to_30H2 | 3 | HA1E,SA28T,YA29F | 0.579 | -0.595 | weaker/stronger |
| 39_to_39H2 | 1 | RA26G | -0.003 | 0.068 | neutral/neutral |
| 39_to_39H4 | 1 | RA26G | -0.218 | 0.068 | stronger/neutral |
| 151_to_151H8 | 1 | HA1E | NA | -0.500 | unknown/stronger |

不接受 Graphinity 结果作当前排名依据，原因是：

1. 模型实际口径是单界面突变，而当前 child 有 8--20 个突变；简单相加忽略 epistasis。
2. 只覆盖 9/79 个替换，大多数突变不在当前 pose 的 4 A 界面内。
3. 20H5 和 30H2 的实验方向都被预测反了；39H2/39H4 因 parent pose 和 RA26G 完全相同而得到相同分数，无法解释其它差异。
4. 多个“界面突变”出现在 VHH 第 1 位残基，这提示当前 docking pose 可能含有不理想的 N 端接触。

## 6. 对筛选流程的决策

### 现在可以保留

- `prodigy_binding_prior`：保留为连续弱先验，不 hard fail，不称 Kd。
- `foldx_fixed_pose_ddg`：只在同 parent、同 pose、界面经人工/规则质控时使用，并保留 5 个 repeat 的方差。
- 两者都与 blocker geometry、developability、expression/purity 分开存储。

### 现在不能使用

- PRODIGY 绝对 Kd；
- 独立 docking pose 的 FoldX 跨候选排名；
- Graphinity 对当前多突变 VHH 的直接排名或 hard gate；
- 任何将计算亲和力分数等同于阻断效果的表述。

## 7. 下一个最有价值的计算实验

不是再堆更多通用 sequence-only binding classifier，而是为 5--10 个已知阳性家族建立**经校准的同 parent 复合物姿势**，做小规模 pose ensemble + FoldX/Flex-ddG 或短 MD 后 MM/GBSA，先看能否稳定复现 20/30/39/151 家族的已知相对方向。只有这个校准关通过，才值得把结构亲和力项加入 50 万条前筛。

## 8. 可复现文件

- `pose_manifest.tsv`：99 个冻结 pose。
- `pose_level_affinity_scores.tsv`：PRODIGY/FoldX pose-level 结果。
- `candidate_level_affinity_summary.tsv`：候选汇总。
- `fixed_pose_foldx_binding_ddg.tsv`：30 个 FoldX 重复。
- `fixed_pose_foldx_pair_summary.tsv`：同 parent pair 汇总。
- `graphinity_single_mutation_input.csv`：27 个 Graphinity 合法单点输入。
- `graphinity_single_mutation_scores.tsv`：Graphinity 单突变汇总。
- `graphinity_pair_additive_summary.tsv`：仅供评估的加和近似。
- `final_method_comparison.tsv` 与 `final_evaluation_metrics.json`：最终机器可读结论。
