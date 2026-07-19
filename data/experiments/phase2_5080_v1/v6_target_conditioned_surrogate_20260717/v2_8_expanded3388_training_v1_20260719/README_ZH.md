# V2.8：扩展到 3,388 条独立 VHH 的标量 Docking 教师集

## 权威结论

用户记忆中的“约 4,000 条 Docking 数据”对应的是 V4-I Stage 1 的技术任务口径：

```text
1,962 条 VHH × 2 个受体 = 3,924 个 Docking jobs
```

它不是 3,924 条独立序列。严格排除 81 条双受体标签不完整候选后，V4-I 新增：

```text
1,881 条独立、无重复、具有 R8/R9/Rdual 的 VHH
```

与既有 teacher 合并后：

| 来源 | 独立序列 | 标签策略 |
|---|---:|---|
| V4-D OPEN_TRAIN | 226 | 多 seed 候选级聚合 |
| V4-H analyzable | 1,281 | 1/2/3 seed 候选级聚合 |
| V4-I Stage 1 + Stage 2 overlay | 1,881 | 500 条用 Stage 2 聚合覆盖，其余用 Stage 1 |
| **合计** | **3,388** | **6,776 个受体特异标量目标** |

三批序列 SHA256 交集为 0。

V4-H/V4-I 协议语义兼容审计也已通过：受体/参考结构、hotspot、blocker rules、Docking 和评分脚本逐字节相同；协议差异仅为候选规模、任务数和 smoke candidate。不同的 protocol-core hash 仍保留在审计中，不能抹去。

## 为什么不是 3,888 或 4,888 条

V4-I Stage 2 的 500 条是 Stage 1 候选的第二个 seed 技术重复，不是新序列。它们用于：

- 计算候选级中位数；
- 估计 seed dispersion；
- 提高 476 条候选的教师可靠性；

不能作为 500 条额外独立样本重复加入训练。

## 当前可立即使用的监督

`prepared/v6_scalar_teacher3388_v2_8.tsv` 可立即用于 sequence-only 标量模型：

```text
直接预测 R_8X6B、R_9E6Y
推理时 R_dual_min = min(R_8X6B, R_9E6Y)
```

同时物化了 `prepared/v6_scalar_teacher2007_stage2_ablation_v2_8.tsv`。该表只加入 V4-I Stage 2 的 500 条候选，对应 2,007 条独立序列和 4,014 个受体特异标量目标，用来检验其余 1,381 条低可靠单-seed数据是否真的提供增益。

证据分层：

| 监督层 | 数量 | 基础权重 |
|---|---:|---:|
| 多 seed（V4-D、2/3 seed） | 1,066 | 0.8–1.0 |
| 单 seed | 2,322 | 0.65 |

## 当前不能直接声称扩展的部分

V4-I 尚未物化本地 126-D 单体结构特征，也尚未从原始 Top-8 poses 提取 residue/contact teacher。因此：

- sequence scalar lane：现在即可从 1,507 扩到 3,388；
- M2/structure lane：需先在 Node23 对 V4-I 单体 PDB 物化同版本特征；
- contact/F0 lane：需先执行冻结的 V4-I pose-contact extractor；
- pair-only lane：继续暂停，除非新的 contact 监督证明有增益。

## 关键风险

V4-I 的 11 个 parent clusters 全部已在 V4-H 中出现。新增数据扩大了同 parent 的序列/生成方法覆盖，但没有增加 unseen-parent 生物学多样性。因此验证必须绑定 whole-parent split，并额外报告 generator/source-lane challenge；不能随机拆分序列行。

## 复现

```bash
python3 src/build_expanded_scalar_teacher_v2_8.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
cd prepared && sha256sum -c SHA256SUMS
```

证据边界：所有标签均为独立双受体 computational docking geometry evidence，不是结合、Kd、竞争实验、真实阻断概率或 Docking Gold。
