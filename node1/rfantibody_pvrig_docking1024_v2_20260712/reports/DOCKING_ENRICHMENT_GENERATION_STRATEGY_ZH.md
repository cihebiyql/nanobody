# 如何增加尽可能多的 docking 更好序列

> 生成时间：`2026-07-14T00:38:52.540281+00:00`

本报告只讨论计算生成与 docking 富集，不讨论实验验证。

## 1. 直接结论

不要再按 36 个 arm 平均分配。下一轮应把主体预算集中到：

```text
P2_bridge_N_C / P3_charge_aromatic / P4_cterm_robust
+ long H3
+ fixed CDR3 length 13
+ ekg/qrg 为主，qkg 保留稳定命中支线
```

全量 1,024 条中，至少一个双参考 A 的比例为 `4.6%`，同时满足 A 且 best HADDOCK≤-80 的严格比例为 `3.1%`。
在 `P2/P3/P4 + long H3 + CDR3=13` 的 100 条回看子集中，这两个比例分别达到 `20.0%` 和 `17.0%`，约为全量的 `4.4x` 和 `5.4x`。
这是当前最明确的计算扩增方向，但它是 retrospective enrichment，不是未来批次的保证。

## 2. 先定义什么叫 docking 更好

建议不要只按 HADDOCK score，而采用四级计算目标：

1. 主目标：`A_count >= 1`，至少一个 top4 pose 为双参考 `CONSENSUS_BLOCKER_LIKE_A`。
2. 稳定目标：`A_count >= 2`，避免单 pose 偶然命中。
3. 严格目标：`A_count >= 1 && best_HADDOCK <= -80`。
4. 强严格目标：`A_count >= 2 && best_HADDOCK <= -80`。

HADDOCK 分数只在同一几何等级内排序；不能让低分但 9E6Y 热点不通过的序列排到双参考 A 前面。

## 3. 现有数据中的富集规律

### H3 长度

| 区域 | n | 任一双参考 A | 稳定 A>=2 | 严格 good |
|---|---:|---:|---:|---:|
| `all_1024` | 1024 | 47 (4.6%) | 12 (1.2%) | 32 (3.1%) |
| `long_h3` | 522 | 44 (8.4%) | 11 (2.1%) | 32 (6.1%) |
| `p2_p3_p4_long_h3` | 261 | 34 (13.0%) | 9 (3.4%) | 28 (10.7%) |
| `p2_p3_p4_long_h3_cdr3_13` | 100 | 20 (20.0%) | 8 (8.0%) | 17 (17.0%) |

长 H3 的任一 A 命中率为 8.4%，短 H3 只有 0.6%。CDR3 长度 5、7、8 在本批合计没有产生任何双参考 A；CDR3=13 最强。

### patch

| patch | n | 任一 A | 稳定 A | 严格 good | HADDOCK≤-90 |
|---|---:|---:|---:|---:|---:|
| `P3_charge_aromatic` | 171 | 13 (7.6%) | 4 (2.3%) | 11 (6.4%) | 36 (21.1%) |
| `P2_bridge_N_C` | 169 | 12 (7.1%) | 3 (1.8%) | 10 (5.9%) | 21 (12.4%) |
| `P4_cterm_robust` | 174 | 11 (6.3%) | 3 (1.7%) | 7 (4.0%) | 30 (17.2%) |
| `P5_upper_interface` | 174 | 6 (3.4%) | 1 (0.6%) | 1 (0.6%) | 22 (12.6%) |
| `P1_core_blocker` | 168 | 4 (2.4%) | 1 (0.6%) | 2 (1.2%) | 18 (10.7%) |
| `P6_holdout_ablation` | 168 | 1 (0.6%) | 0 (0.0%) | 1 (0.6%) | 32 (19.0%) |

P6 虽然有不少很负的 HADDOCK 分数，但几乎不产生双参考 A，说明继续优化单一分数会浪费算力。

### 最优 arm 和 backbone seed

任一 A 命中率最高的主 arm 是 `P2_qrg_L` (6/29)、`P4_ekg_L` (5/29)、`P3_ekg_L`、`P3_qkg_L`、`P3_qrg_L` (各 4/29)。
局部扩增优先使用 `P3_ekg_L_bb003`、`P2_qrg_L_bb003/bb004`、`P4_qkg_L_bb003`、`P2_qkg_L_bb006` 和 `P5_qrg_L_bb004`。

## 4. 真正的瓶颈是 9E6Y 热点覆盖

共有 `1219` 个 pose 在 8X6B 为 A、但在 9E6Y 不是 A。
其中 `1216` 个未通过 9E6Y hotspot gate；`1099` 个只差 hotspot，其他三个阈值均已通过。
因此下一轮不应主要继续增加总遮挡或把 HADDOCK 再压低，而应增加同一 pose 在 9E6Y 构象下覆盖的 PVRIG 共识热点数量。

具体做法：

- 保留 8X6B-guided 主标签，增加 9E6Y PVRIG conformer 的 RFdiffusion 生成支线。
- 用 P2/P3/P4 的跨 N/C 端热点组合，而不是只压一个局部 patch。
- acquisition score 中直接使用 `min(hotspot_8X6B, hotspot_9E6Y)` 和 9E6Y hotspot margin。
- 对进入 HADDOCK 的候选要求 cheap generated-pose proxy 在 9E6Y 上至少接近阈值，再保留一部分 uncertainty 候选防止误杀。

## 5. 最快增加数量的方法：先扩成功 backbone 的序列邻域

当前每个 RFdiffusion backbone 只生成 4 条 ProteinMPNN 序列。要快速增加数量，最便宜的做法不是全部重新跑 RFdiffusion，而是：

1. 选 12-20 个成功 backbone；
2. 每个 backbone 生成 16-32 条序列；
3. 使用 temperature 0.1/0.2/0.3 三档；
4. 保留 exact-unique，并限制单个 near-CDR3 family 的进入 docking 数；
5. 然后再补充新 RFdiffusion backbone，避免全部候选成为同一姿势的近重复。

`H1:7,H2:6,H3:13` 是 RFantibody 支持的固定长度语法，可以直接用于下一轮 arm。

## 6. 推荐的 8,192 条 raw pool 预算

| lane | 比例 | raw 数 | patch | scaffold | loop | 目的 |
|---|---:|---:|---|---|---|---|
| `EXPLOIT_P3_STABLE` | 25.0% | 2048 | P3_charge_aromatic | ekg;qkg;qrg | `H1:7,H2:6,H3:13` | maximize stable A_count and favorable HADDOCK score |
| `EXPLOIT_P2_YIELD` | 25.0% | 2048 | P2_bridge_N_C | qrg;ekg;qkg | `H1:7,H2:6,H3:13` | maximize number of candidates with at least one dual-reference A pose |
| `EXPLOIT_P4_ROBUST` | 20.0% | 1638 | P4_cterm_robust | ekg;qkg;qrg | `H1:7,H2:6,H3:13` | retain a second robust high-yield patch family |
| `NEIGHBOR_LENGTHS` | 10.0% | 819 | P2_bridge_N_C;P3_charge_aromatic;P4_cterm_robust | ekg;qrg;qkg | `H1:7,H2:6,H3:11|14|15` | avoid overfitting all capacity to length 13 |
| `9E6Y_CONFORMER_SEARCH` | 10.0% | 819 | P2/P3/P4 mapped consensus hotspots | ekg;qrg;qkg | `H1:7,H2:6,H3:13` | directly attack the 9E6Y hotspot-overlap bottleneck |
| `NOVELTY_AND_BIAS_AUDIT` | 10.0% | 820 | P1;P5;P6;new cross-lobe hotspot combinations | balanced | `H1:7,H2:6,H3:11-15` | maintain exploration and detect surrogate or restraint shortcuts |

推荐漏斗：

```text
8,192 raw RFantibody/ProteinMPNN sequences
  -> exact unique + sequence QC
  -> generated-pose 双参考快速几何 + surrogate 预筛
  -> 1,536 NanoBodyBuilder2
  -> 1,024 HADDOCK3
  -> top4 pose 的 8X6B/9E6Y 全量后处理
```

如果 100 条富集子集的历史比例完全复现，1,024 条 docking 可得到约 `205` 条任一 A、`174` 条严格 good。这个数字只能作为容量规划上限，实际 prospective yield 应按回归到均值后的 100-170 条严格 good 规划。

## 7. 主动学习循环

每完成一批 512-1,024 条 docking，就用新标签重训四个独立头：

- `P(A_count>=1)`；
- `E[A_count]`；
- `9E6Y hotspot margin`；
- `best HADDOCK score`。

进入下一批的比例建议为 70% exploitation、20% uncertainty、10% novelty。不要把四个头压成一个未经验证的总分；先过双参考几何硬门，再用 HADDOCK 排序。

计算停止条件可以设为：连续两批严格 good 命中率低于 5%，或每新增一条严格 good 需要超过 30 条完整 docking。

## 8. 优化前必须修正的评分问题

当前两个 occlusion scorer 都读取 `HETATM`。9E6Y 的 PVRL2 chain 中存在 HOH/EDO，因此总遮挡、clash 和 CDR3 fraction 可能包含结晶水或添加剂。下一轮训练 surrogate 或优化 geometry margin 前必须：

- PVRIG/PVRL2 蛋白接触只保留标准氨基酸 `ATOM`；
- HOH、EDO 和其他 ligand 单独记录，不进入 protein occlusion；
- 重新计算旧 1,024 条的 clean geometry label，再开始 active learning。

否则大量生成会逐渐学会利用评分器漏洞，而不是产生真正更好的蛋白 docking 几何。

## 9. 不应继续做的事情

- 不再平均扩全部 36 个 arm。
- 不把 CDR3 长度 5/7/8 作为主线。
- 不因 P6 的 HADDOCK 很负就增加 P6 预算。
- 不全量跑三 seed RF2；它与当前 Tier 1 没有交集，可把 GPU 预算转给更多生成和 NBB2。
- 不允许一个 near-CDR3 family 吃掉全部 docking 名额。
- 不在修复 HETATM 计分前训练最终 surrogate。

## 10. 输出

- `reports/docking_generation_enrichment_summary.json`：机器可读摘要。
- `reports/docking_generation_group_enrichment.tsv`：全部 group 富集统计。
- `reports/proposed_generation_budget_v3.tsv`：下一轮预算表。
- `scripts/analyze_generation_enrichment.py`：可复现分析脚本。
