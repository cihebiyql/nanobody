# PVRIG RFantibody 1,000 条序列生成运行状态

更新时间：2026-07-12 16:16 CST

远端节点：`node1`

远端目录：`/data/qlyu/projects/pvrig_rfantibody_1000_20260712`

本地目录：`/mnt/d/work/抗体/node1/rfantibody_pvrig_1000`

## 当前状态

`COMPLETE`

RFdiffusion 和 ProteinMPNN 的四个分片均已正常完成，最终收集器于
2026-07-12 16:10:30 CST 生成 1,000 条精确去重的全长 VHH 序列。

| 指标 | 结果 |
|---|---:|
| RFdiffusion backbone | 200 |
| ProteinMPNN 原始 sequence-pose records | 1,600 |
| 原始有效 records | 1,600 |
| 原始 exact-unique 序列 | 1,494 |
| 原始重复 records | 106 |
| 最终序列 | 1,000 |
| 最终 exact-unique 序列 | 1,000 |
| 覆盖的独立 backbone | 171 |
| 单个 backbone 最多保留序列 | 6 |
| 32 条已知阳性/专利参考的 exact match | 0 |
| 全长序列长度 | 113-121 aa |
| CDR1 / CDR2 / CDR3 长度 | 7 / 6 / 5-13 aa |

## 生成设计

```text
4 个 PVRIG-PVRL2 界面 hotspot set
× 每组 50 个 RFdiffusion backbone
× 每个 backbone 8 条 ProteinMPNN 序列
= 1,600 条原始 sequence-pose records
→ 全局 exact dedup
→ 每组平衡选取 250 条
= 1,000 条最终序列
```

- RFantibody 代码 commit：`8fe311415754e0276d1a39c87c57e69c88927a2d`
- PVRIG 输入：8X6B chain B 的蛋白原子，chain ID 改为 `T`，共 103 个残基。
- VHH framework：RFantibody 官方人源化 `h-NbBCII10`。
- RFdiffusion：50 timesteps，`H1:7,H2:6,H3:5-13`，deterministic，不保存 trajectory。
- ProteinMPNN：设计 H1/H2/H3，temperature 0.2，omit `C/X`，deterministic。
- RF2：本轮按计划未运行。

## Hotspot 分组与几何质量

| 组 | GPU | PDB 位点 | UniProt 位点 | 最小距离中位数 | backbone `<=8 A` | 最终 `<=8 A` | 最终 `8-10 A` | 最终 `>10 A` |
|---|---:|---|---|---:|---:|---:|---:|---:|
| A | 1 | `T57,T101,T106` | `R95,F139,W144` | 4.87 A | 49/50 | 244 | 6 | 0 |
| B | 2 | `T62,T101,T106` | `W100,F139,W144` | 8.95 A | 20/50 | 96 | 125 | 29 |
| C | 3 | `T97,T101,T105,T106` | `K135,F139,S143,W144` | 4.32 A | 50/50 | 250 | 0 | 0 |
| D | 4 | `T33,T36,T105,T106` | `S71,T74,S143,W144` | 4.15 A | 49/50 | 247 | 0 | 3 |

**重要风险：** B 组的 hotspot 几何明显弱于 A/C/D；只有 20/50 个
backbone 的最小 hotspot 距离不超过 8 A，45/50 不超过 10 A。后续不应将
四组视为等价候选池。最终 B 组 250 条中只有 96 条属于 `<=8 A`，
另有 29 条属于 `>10 A`；B 组应先按 `rfd_mindist` 过滤，再进入
RF2/复合物建模。D 组也有 3 条 `>10 A` 记录，但整体风险远小于 B 组。

## 交付文件

远端原始交付目录：

```text
/data/qlyu/projects/pvrig_rfantibody_1000_20260712/final/
```

已同步到本地：

```text
/mnt/d/work/抗体/node1/rfantibody_pvrig_1000/results/
├── LOCAL_VERIFICATION.json
├── run_manifest.json
├── final/
│   ├── pvrig_rfantibody_1000.fasta
│   ├── pvrig_rfantibody_1000.tsv
│   ├── raw_candidates.tsv
│   ├── summary.json
│   └── sha256sums.txt
└── sets/set_{A-D}/complete.json
```

- `pvrig_rfantibody_1000.fasta`：下游筛选的 1,000 条全长 VHH 序列。
- `pvrig_rfantibody_1000.tsv`：最终候选的序列、CDR、backbone/MPNN provenance、hotspot 几何和状态。
- `raw_candidates.tsv`：1,600 条原始记录，可重做去重、配额或排序。
- `summary.json`：本批次统计和 hotspot 距离摘要。
- `run_manifest.json`：代码版本、输入、权重、参数和哈希。
- `LOCAL_VERIFICATION.json`：同步后在本地独立重做的一致性检查。

## 验证结果

本地独立验证全部通过：

- FASTA 有 1,000 个 header 和 1,000 条序列。
- FASTA 与最终 TSV 的 candidate ID 及序列一一一致。
- 1,000 个 candidate ID 和 1,000 条序列均精确唯一。
- A/B/C/D 均为 250 条。
- CDR1=7 aa，CDR2=6 aa，CDR3=5-13 aa，并与全长序列一致。
- 1,600 条原始记录中未发现 32 条已知阳性/专利参考的 exact match。
- A/B/C/D 的 `complete.json` 均为 return code 0，各有 50 个 backbone 和 400 个 sequence PDB。
- `sha256sum -c final/sha256sums.txt` 四项全部为 `OK`。

## 科学边界

这 1,000 条是 **hotspot-conditioned RFdiffusion + ProteinMPNN generated
candidates**，不是实验确认的 PVRIG binder，也不是已证明的 PVRIG-PVRL2
blocker。本批次不能直接推出：

- 真实结合概率或 Kd；
- 复合物 pose 是否可信；
- 是否占据并阻断 PVRIG-PVRL2 功能界面；
- 表达量、热稳定性、聚集、非特异性和成药性。

exact-match 泄漏检查只能排除与 32 条参考序列完全相同，不等于已排除
near-neighbour、同族序列或更广泛专利空间的重合。

## 建议的下一阶段

1. 先用现有 `vhh-large-scale-screen` 对 1,000 条做 VHH 格式、ANARCI、near-neighbour、novelty 和 developability 门控。
2. 优先从 A/C/D 各抽取 10-25 条运行 RF2/复合物预测；B 组先按 hotspot 距离过滤。
3. 对通过 pose 质量的候选单独计算 PVRIG-PVRL2 界面重叠、立体冲突和 hotspot 覆盖，不要用 binder score 代替 blocker score。
4. 只有经过序列门控、pose 门控和阻断几何门控后，才进入小批量合成和实验验证。
