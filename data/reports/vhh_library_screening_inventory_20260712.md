# VHH 库清点与 PVRIG 筛选对象决策（2026-07-12）

## 直接结论

本轮不应把 INDI2、VHHCorpus-2M、OAS 或 PLAbDab-nano 原始天然库直接当作 PVRIG 参赛候选库。

真正要送入 Node1 `vhh-large-scale-screen` 的库应该是：

```text
PVRIG target-conditioned VHH design library
= 从 Top 200 中选择 30-50 个 parent scaffold
+ 针对 PVRIG-PVRL2 界面的 CDR/RFantibody/ProteinMPNN/fixed-pose redesign
```

- 当前这个正式生产设计库的已落盘规模：**0 条**。
- 截止日期安全的首批生产规模：**1,000-5,000 条**。
- 按完整设计矩阵展开后的目标筛选规模：**8,000-15,000 条原始设计**。
- 现有 `Top 200` 是父骨架种子，不是 200 条 PVRIG binder，也不是最终待筛库。

## 当前相关数据资产

| 资产 | 当前实物规模 | 用途 | 是否直接作为 PVRIG 候选库 |
| --- | ---: | --- | --- |
| PLAbDab-nano `vhh_sequences.csv.gz` | 4,457 数据行 | 受控 scaffold 导入源、文献/专利查重 | 否 |
| `raw_vhh_scaffold_pool.fasta` | 1,965 条唯一序列 | 受控导入的原始 scaffold 池 | 否 |
| `clean_vhh_scaffold_library.fasta` | 1,591 条唯一序列 | 通过基础门控的 parent starting material | 否 |
| `vhh_scaffold_cluster_table.csv` | 1,268 个 90% identity cluster | 父骨架多样性管理 | 否 |
| `top_200_vhh_scaffolds_for_design.fasta` | 200 条唯一序列 | 本轮首选 parent scaffold seed | 否，需先定向设计 |
| VHHCorpus-2M full CSV | 2,054,320 数据行 | VHH 天然性、分布和预训练背景 | 否 |
| INDI2 `sequences_index` | 11,900,529 索引行 | 大规模天然/专利/结构背景和 scaffold 扩展 | 否 |
| INDI2 AbNGS annotated reads | 29,224,937 行 | repertoire/naturalness 背景；存在来源内和跨来源冗余 | 否 |
| OAS 本地下载子集 | 30 个 `.gz`，约 778 MB | 原始天然性背景，尚未固化为 VHH-only 唯一序列库 | 否 |
| ZYM public candidate subset | 500 条 | 模型/流程审计和可能的优化起点 | 否，抗原上下文缺失 |
| V2.4 model Top50 | 50 条 | Node1 cascade 审计 | 否，50/50 均是未改造公开序列 |
| 正式 PVRIG 条件化设计批次 | 0 条 | 本轮真正要建立和筛选的候选库 | **是** |

VHHCorpus-2M 在 `datasets/24_hf_nanobody/` 和 `datasets/49_hf_broad_antibody/` 中各有一份镜像；主 CSV、train 和 valid 文件的 SHA256 分别完全相同，因此逻辑上只能计一个 2.054M 数据集，不能累加成 4.1M。

## 为什么选 Top 200 作为生成起点

Top 200 已经完成了：

- ANARCI/IMGT 编号与 FR/CDR 完整性检查；
- framework health 和基础 developability 门控；
- 已知 PVRIG 阳性 CDR 泄漏排除；
- 90% identity 聚类与家族多样性筛选；
- parent accession、source release 和使用条款字段保留。

因此当前不应先花时间从 INDI2 的 11.9M 索引或 VHHCorpus-2M 的 2.054M 序列从头清洗。它们应该用于：

1. 天然性/表达 prior；
2. 序列分布偏离检查；
3. 专利和近邻查重；
4. Top 200 覆盖不足时的 scaffold 补充。

## 建议的生产规模

完整设计矩阵可按下列方式形成：

```text
40 parent scaffolds
x 3 PVRIG target patches
x 2 main design modes
x 30-50 sequences per cell
= 7,200-12,000 designs

+ fixed-pose/local redesign
= 8,000-15,000 total raw designs
```

实际执行建议分两段：

1. 先生成 1,000-5,000 条带完整 lineage 的首批，验证 RFantibody 生产配置和 Node1 漏斗。
2. 通过基础 FASTA/编号检查后立即扩展到 8,000-15,000 条，再做 fast gate -> 模型前筛 -> full QC -> 结构/docking。

## 当前不能混淆的三个数字

```text
200          = 已就绪的优选 parent scaffold 数
8,000-15,000 = 需要生成并送入筛选的 PVRIG 条件化设计数
50           = 最终提交 portfolio 数
```

INDI2 的 11.9M 和 VHHCorpus-2M 的 2.054M 是背景/源数据规模，不是本轮要对 PVRIG 直接做结构和 docking 的候选数。

## 核验证据

- 当前 `datasets/` 共 27,951 个文件，276,217,240,969 bytes（约 257.2 GiB）。
- PLAbDab-nano scaffold FASTA 重新计数结果：1,965 / 1,591 / 200，且三个文件内均无完全重复序列。
- VHHCorpus-2M full CSV 实际为 2,054,320 条数据行；两份本地镜像 SHA256 相同。
- INDI2 Delta log 记录 `sequences_index` 为 11,900,529 行，AbNGS annotated reads 为 29,224,937 行。
- 全项目未发现 PVRIG 正式生产 design batch FASTA；只有 `top_200_vhh_scaffolds_for_design.fasta` 和审计/校准候选文件。
