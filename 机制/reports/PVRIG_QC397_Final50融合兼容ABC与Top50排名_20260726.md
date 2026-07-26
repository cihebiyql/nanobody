# PVRIG QC397：Final50 融合兼容性、A/B/C 风险与 Top50 排名

日期：2026-07-26  
上游：QC397 V2 static-review → Top80 → Final50  
Node1 原始目录：

```text
/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/qc397_final50_fusion_developability_v1_20260726/
```

本地机器可读镜像：

```text
机制/data/audits/PVRIG_QC397_Final50_融合兼容ABC与竞赛排名_v1_20260726/
```

## 1. 扩大范围后的结论

上一轮只覆盖 `Final-rank Top20 ∪ 当前 Top10` 共 22 条。本轮扩大到完整 Final50：

```text
50 条候选
× 4 seeds（42、917、1931、3047）
× 2 个 PVRIG 构象（8X6B、9E6Y）
= 400 个冻结 pose
```

结果：

| 项目 | 结果 |
|---|---:|
| Final50 候选 | 50/50 |
| 冻结 pose | 400/400 |
| 结构 PTM 暴露记录 | 5,912 |
| 融合窄预检 F1 | 50/50 |
| 融合 hard fail | 0/50 |
| A 级 | 18 |
| B 级 | 26 |
| C 级 | 6 |
| Top10 组合 | 8A + 2B |
| 精确不同序列 | 50/50 |

全部 50 条的裸 VHH C 端在当前 400 个 pose 中均未显示明显融合障碍：

```text
C端-PVRIG 最小距离范围：25.63–36.25 Å
C端末残基中位 SASA 范围：118.52–138.02 Å²
C端直接接触 PVRIG：0/400
低 C端 SASA pose：0/400
严重直线退出穿越：0/400
暴露未配对 Cys：0/50
```

完整 Fc-PVRIG 碰撞、另一 VHH 臂、二价几何和 hinge/Fc Cys 仍等待赛事方精确构建，不能解释成已经通过。

## 2. 排名规则

原 `mechanism_rank` 保持不可变。新增独立：

```text
competition_rank_1_50
```

规则：

1. 前 10 名使用已经固定的赛事组合：8 条 A + 最多 2 条高机制 B；
2. 第 11–44 名为未入 Top10 的非 C 候选，并保持原机制相对顺序；
3. 6 条 C 级 hard-risk 候选移到第 45–50 名；
4. C 级候选不删除，仍保留原机制排名和全部证据；
5. 不重新计算 docking，不修改 Final50 原文件。

因此该榜是：

```text
赛事表达/实验投放顺序
```

不是新的 docking 排名。

## 3. Competition Top50

| 新排名 | 原机制排名 | 候选简称 | 风险级别 | 角色 |
|---:|---:|---|:---:|---|
| 1 | 2 | `NODE1GEN_112448` | A | Top10 A |
| 2 | 3 | `NODE1GEN_229102` | A | Top10 A |
| 3 | 4 | `P1MCPUFP__CPUFP500K_0188__00519` | A | Top10 A |
| 4 | 6 | `NODE1GEN_181778` | A | Top10 A |
| 5 | 8 | `NODE1GEN_256613` | A | Top10 A |
| 6 | 9 | `NODE1GEN_183154` | A | Top10 A |
| 7 | 14 | `P1MCPUFP__CPUFP500K_0100__00188` | A | Top10 A |
| 8 | 16 | `P1MCPUFP__CPUFP500K_0002__00919` | A | Top10 A |
| 9 | 1 | `P1MCPUFP__CPUFP500K_0288__00659` | B | Top10 B |
| 10 | 5 | `P1MCPUFP__CPUFP500K_0100__00092` | B | Top10 B |
| 11 | 7 | `NODE1GEN_154595` | B | reserve |
| 12 | 10 | `P1MCPUFP__CPUFP500K_0188__00282` | B | reserve |
| 13 | 11 | `NODE1GEN_191476` | A | reserve |
| 14 | 12 | `P1MCPUFP__CPUFP500K_0090__00532` | B | reserve |
| 15 | 13 | `NODE1GEN_177961` | B | reserve |
| 16 | 15 | `NODE1GEN_206644` | A | reserve |
| 17 | 17 | `P1MCPUFP__CPUFP500K_0287__00804` | B | reserve |
| 18 | 18 | `NODE1GEN_127352` | A | reserve |
| 19 | 19 | `P1MCPUFP__CPUFP500K_0089__00735` | B | reserve |
| 20 | 20 | `NODE1GEN_258472` | B | reserve |
| 21 | 21 | `P1MCPUFP__CPUFP500K_0299__00780` | A | reserve |
| 22 | 22 | `P1MCPUFP__CPUFP500K_0189__00858` | A | reserve |
| 23 | 23 | `NODE1GEN_174576` | B | reserve |
| 24 | 24 | `NODE1GEN_002130` | B | reserve |
| 25 | 25 | `P1MCPUFP__CPUFP500K_0380__00771` | B | reserve |
| 26 | 26 | `NODE1GEN_217675` | B | reserve |
| 27 | 27 | `P1MCPUFP__CPUFP500K_0404__00029` | B | reserve |
| 28 | 28 | `P1MCPUFP__CPUFP500K_0188__00549` | A | reserve |
| 29 | 29 | `P1MCPUFP__CPUFP500K_0188__00481` | B | reserve |
| 30 | 30 | `NODE1GEN_182669` | A | reserve |
| 31 | 31 | `NODE1GEN_128014` | A | reserve |
| 32 | 32 | `NODE1GEN_218195` | B | reserve |
| 33 | 33 | `NODE1GEN_195165` | B | reserve |
| 34 | 34 | `NODE1GEN_235318` | B | reserve |
| 35 | 37 | `NODE1GEN_076816` | B | reserve |
| 36 | 40 | `NODE1GEN_136300` | B | reserve |
| 37 | 41 | `NODE1GEN_095824` | B | reserve |
| 38 | 42 | `NODE1GEN_017313` | B | reserve |
| 39 | 43 | `NODE1GEN_109783` | B | reserve |
| 40 | 44 | `NODE1GEN_100102` | B | reserve |
| 41 | 45 | `NODE1GEN_109883` | A | reserve |
| 42 | 47 | `P1MCPUFP__CPUFP500K_0030__00860` | A | reserve |
| 43 | 48 | `P1MCPUFP__CPUFP500K_0029__00647` | B | reserve |
| 44 | 49 | `P1MCPUFP__CPUFP500K_0090__00860` | B | reserve |
| 45 | 35 | `P1MCPUFP__CPUFP500K_0289__00496` | C | C tail |
| 46 | 36 | `P1MCPUFP__CPUFP500K_0091__00849` | C | C tail |
| 47 | 38 | `P1MCPUFP__CPUFP500K_0388__00174` | C | C tail |
| 48 | 39 | `P1MCPUFP__CPUFP500K_0487__00827` | C | C tail |
| 49 | 46 | `P1MCPUFP__CPUFP500K_0188__00645` | C | C tail |
| 50 | 50 | `NODE1GEN_128929` | C | C tail |

## 4. 六条 C 级的原因

| 新排名 | 原机制排名 | 候选 | hard-risk 原因 |
|---:|---:|---|---|
| 45 | 35 | `CPUFP500K_0289__00496` | poor/not-VHH-like；极端表面疏水 patch |
| 46 | 36 | `CPUFP500K_0091__00849` | poor/not-VHH-like |
| 47 | 38 | `CPUFP500K_0388__00174` | poor/not-VHH-like |
| 48 | 39 | `CPUFP500K_0487__00827` | poor/not-VHH-like |
| 49 | 46 | `CPUFP500K_0188__00645` | 极端表面疏水 patch |
| 50 | 50 | `NODE1GEN_128929` | CDR N-糖基化 motif |

这些是计算 hard-risk，不是已经实验确认的表达失败。

## 5. 序列文件

完整的 50 条序列及逐条指标：

```text
机制/data/audits/PVRIG_QC397_Final50_融合兼容ABC与竞赛排名_v1_20260726/
  final50_competition_ranking/Final50_competition_ranked.tsv
  final50_competition_ranking/Final50_competition_ranked.fasta
```

TSV 包含：

- `competition_rank_1_50`
- 原 `mechanism_rank_immutable`
- 完整 VHH 序列
- CDR1/2/3
- parent、route、source cohort
- A/B/C 级别和原因
- 融合预检结果
- blocker class 和多 seed 几何指标

FASTA 按新的 1–50 顺序排列，共 50 条精确不同序列。

## 6. 审计和边界

最终收据：

```text
FINAL50_FUSION_RANKING_AUDIT.json
state = AUDIT_COMPLETE
```

已验证：

- Final50 50 条集合未改变；
- 400 个 PDB 均存在且哈希匹配；
- 每条严格为 4 seeds × 2 构象；
- TSV 和 FASTA 均为 50 条、无重复序列；
- Top10 为 8A+2B，无 C；
- C 级构成连续的排名末尾；
- QC397 V2 Final50 SHA-256 仍为  
  `9ceb5734741a655e9c94c0b77aba293b054473718c9bd04787dfc6fa27590218`；
- 旧冻结 Final50 SHA-256 仍为  
  `d1026f93b547013366ff803ee0fe7f1864df1cd02d758a24d72c988edcb37008`。

本榜仍不是实际：

```text
CHO Yield
纯度/SEC
Tm/Tagg
BLI/Kd
IC50/blocking
完整 VHH-hFc 二价结构
```

获得赛事方精确构建或湿实验结果后，应作为新证据侧车更新，不应覆盖当前机制榜。
