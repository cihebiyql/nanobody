# PVRIG VHH 生产筛选指标实施规范

更新时间：2026-07-24

当前实施状态：

- P0 代码已部署到 Node1；
- 本地和 Node1 `/data/qlyu/software/envs/vhh-eval` 均通过 18 项回归；
- Node1 真实 3 条历史 smoke 输入通过，结果保持 2 条 hard fail；
- 部署收据：
  `competition_qc/node1_p0_metrics_deployment_receipt_20260724.json`；
- Node1 证据目录：
  `/data/qlyu/software/vhh_eval_tools/tests/p0_metrics_20260724_212333`。

## 1. 目标和边界

目标是在不重复全量 Docking 的前提下，将现有两批约 7,500 条及后续
多 seed、双受体构象结果统一接入比赛筛选流程：

```text
全量序列
→ 合规、编号、新颖性和可开发性
→ 导入现有 Docking
→ 候选级多 pose / 多 seed / 8X6B+9E6Y 共识
→ Top 100–300 复核 Docking
→ Top 10–30 Rosetta / MD 诊断
→ Top 50 多样性组合
```

证据边界：

- sequence-only 分数只能用于前筛，不能声明 PVRIG binder 或 blocker；
- Docking 几何只能作为 blocker-like 计算证据；
- Rosetta、FoldX、PRODIGY、MD 当前只作复核或诊断；
- Kd、IC50、表达量和纯度最终以湿实验为准。

## 2. 不再全量重跑 Docking

现有 Docking 结果优先复用。仅在以下情况重跑：

1. 候选进入 Top 100–300；
2. 只有单 seed 或单 PVRIG 构象；
3. 8X6B 与 9E6Y 判断矛盾；
4. blocker class 很高但 pose 一致性低；
5. 技术失败、结果缺失或 lineage/hash 不完整。

技术失败必须标为 `TECHNICAL_NA`，不能当作不结合或不阻断。

## 3. 分层 Gate 和排名

### Gate 0–3：全量序列硬门控

- 标准 20 AA、长度；
- 官方 validator；
- ANARCI/IMGT 编号与 CDR 完整性；
- 任一 CDR 对公开/官方阳性 identity `<0.80`；
- 奇数 Cys、明显折叠失败等硬风险；
- 队内近重复和 cluster 限额。

### Gate 4：表达、纯度和可开发性

三个分数分开保留：

- `expression_score`：框架天然性、pI、净电荷、instability、Cys、
  AbNatiV、Sapiens；
- `purity_aggregation_score`：GRAVY、连续疏水、polyreactivity、
  暴露/异常 Cys、TNP 聚集相关 flags；
- `developability_score`：PTM、TNP、糖基化、脱酰胺、异构化和剪切风险。

三者均为 proxy，不等于实际表达量或纯度。

### Gate 5：Binding entry

`binding_entry_score` 必须来自独立 binding evidence，例如：

- DeepNano 或其他 target-conditioned binding prior；
- 明确导入的 `binding_score`；
- 后续 BLI/Kd 数据。

禁止根据 blocker class 反推 binding score，避免同一 Docking 证据重复计权。

默认状态：

| 条件 | 状态 |
|---|---|
| 没有 binding evidence | `NEEDS_BINDING_EVIDENCE` |
| binding score `<60/100` | `BINDING_GATE_FAILED` |
| binding score `>=60/100` | 允许进入 blocker 排名 |

阈值 60 是当前工程门槛，后续必须用比赛 BLI 反馈重新校准。

### Gate 6：Blocking geometry consensus

阳性校准的 A 级几何锚点：

- hotspot overlap `>=14`；
- total PVRL2 occlusion `>=500`；
- CDR3 occlusion `>=100`；
- CDR3 occlusion fraction `>=0.15`。

候选连续阻断分由几何和重复性共同构成：

```text
blocking_consensus_score
= 70% geometry threshold-normalized score
+ 30% pose robustness score
```

`pose_robustness_score` 当前包含：

- valid docking job fraction；
- 8X6B/9E6Y 构象覆盖；
- seed class consistency；
- pose pair consensus；
- native/cross reference agreement。

没有重复性字段时不补中性分；几何分按 70% 折扣，状态为
`NEEDS_REPEAT_DOCKING`。

### Gate 7：生产排名

仅 `PRODUCTION_RANK_READY` 候选获得生产最终分：

```text
40% blocking consensus
20% pose robustness
10% independent binding
10% developability
7.5% expression
7.5% purity/aggregation
5% monomer structure quality
```

新颖性主要作为硬门控，多样性主要作为最终 portfolio 约束，不再通过
额外连续权重稀释 blocker 证据。

## 4. 当前已实施字段

`portfolio_ranked.tsv` 新增或明确：

- `binding_evidence_status`
- `blocking_evidence_status`
- `expression_score`
- `purity_aggregation_score`
- `sequence_priority_score`
- `pose_robustness_score`
- `strict_a_job_fraction`
- `supported_ab_job_fraction`
- `valid_docking_job_fraction`
- `dual_conformation_coverage`
- `seed_consistency_fraction`
- `pose_pair_consensus_fraction`
- `dual_reference_agreement_fraction`
- `ranking_status`
- `production_final_score`

`final_blocker_screen.tsv` 进一步保留：

- Docking job/success 数量；
- 构象和 seed 数量；
- 每个构象最少成功 seed；
- 几何连续分；
- binding entry 状态；
- production rank 状态。

支持直接导入新版 V3 `reports/job_results.tsv`，按 `entity_id` 聚合多 seed、
双构象数据；同时保持旧版一行一个候选 summary 的兼容。

## 5. 缺失值规范

| 情况 | 输出 |
|---|---|
| 未运行 | 空数值 + `NOT_RUN` |
| 技术失败 | 空数值 + `TECHNICAL_NA` |
| 只有单 seed/单构象 | `PARTIAL_DOCKING_EVIDENCE` |
| 双构象且每构象至少 2 seed | `MULTISEED_DUAL_REFERENCE` |
| 没有独立 binding | 不计算生产最终分 |
| 没有 pose robustness | 不计算生产最终分 |

严禁将缺失的 binding/blocking 自动填成 50。

## 6. 后续指标实施顺序

### P0：已完成首版

- [x] 缺失 binding/blocking 改为 NA；
- [x] binding 与 blocker class 解耦；
- [x] expression 和 purity 拆分；
- [x] 双构象、多 seed job results 聚合；
- [x] 连续 blocking consensus；
- [x] production rank readiness 状态；
- [x] 旧 candidate summary 兼容。

### P1：下一批

- [ ] buried SASA；
- [ ] 接触密度；
- [ ] 界面氢键和盐桥；
- [ ] clash residue/atom pair penalty；
- [ ] shape complementarity；
- [ ] buried unsatisfied polar atoms；
- [ ] 表面疏水 patch/SAP；
- [ ] PTM 位点结构暴露；
- [ ] CDR 与 framework 的界面贡献比例；
- [ ] N 端/非预期 framework 接触惩罚。

优先复用新版 `pose_scores.tsv` 已有的 `clash_atom_pairs`、
`clash_residue_pairs`、`haddock_score`、`air_energy` 和
`overlay_rmsd_a`；不先重复运行 Docking。

### P2：校准后加入

- [ ] PVRIG 同家族或结构相似蛋白 decoy docking；
- [ ] electrostatic/polyreactivity specificity penalty；
- [ ] 湿实验表达、纯度、BLI、Kd、IC50 回填；
- [ ] 分数等距/保序校准；
- [ ] Top-k enrichment 和阳性回收率评估。

### P3：仅 Top 候选

- [ ] Top 100–300 复核 Docking；
- [ ] Top 10–30 Rosetta InterfaceAnalyzer；
- [ ] matched-pose 10 ns 级 MD；
- [ ] Gmx_MMPBSA 环境修复后再评估是否保留。

## 7. 回归与部署要求

每次变更至少执行：

```bash
PYTHONPATH=competition_qc python3 -m unittest \
  competition_qc/test_vhh_competition_qc.py \
  competition_qc/test_vhh_large_scale_screen.py -v

python3 -m py_compile \
  competition_qc/vhh_competition_qc.py \
  competition_qc/vhh_large_scale_screen.py
```

部署 Node1 前必须：

1. 备份远端现行脚本；
2. 记录部署前后 SHA256；
3. 运行 CLI help；
4. 运行旧 smoke 样例；
5. 用合成双构象、多 seed `job_results.tsv` 验证新字段；
6. 不覆盖历史结果目录。
