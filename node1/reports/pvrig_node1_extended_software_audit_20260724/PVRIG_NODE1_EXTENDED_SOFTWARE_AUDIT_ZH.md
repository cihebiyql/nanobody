# PVRIG Node1 扩展结构、能量与动力学软件盘点

日期：2026-07-24  
范围：Node1 已安装软件、已有测试资产、PVRIG 实际结果及可接入当前筛选流程的路径。

## 1. 结论

Node1 不只有现有的 DeepNano、NanoBind、AbNatiV、Sapiens、TNP、NBB2、RF2 和 HADDOCK3。

本轮确认还可使用：

- FoldX 5.1；
- Rosetta 3.15；
- PRODIGY 2.4.0；
- GROMACS 2024.4 CUDA；
- OpenMM 8.4；
- gmx_MMPBSA 1.6.3；
- gmx_MMPBSA 环境内的 AmberTools 组件；
- IgFold；
- NanoNet；
- ColabFold 1.5.3；
- AlphaFold3 Python package 3.0.1；
- ESMFold/OpenFold 源码和环境痕迹。

精确名称为 `xfold` 的命令、环境或目录没有找到。用户所说的 `xfold`
更可能是 `FoldX`；Node1 上 FoldX 已确认可以运行。

安装状态不等于已有 PVRIG 生产结果。当前：

- FoldX、Rosetta、PRODIGY 在本轮以前没有找到 PVRIG/VHH 批量结果；
- GROMACS、gmx_MMPBSA 没有找到 PVRIG/VHH 轨迹或自由能结果；
- OpenMM 已在 NanoBodyBuilder2 的单体 refine smoke 中实际使用；
- IgFold、NanoNet 已有单体结构 smoke 和统一 `vhh-screen` 交叉结构测试；
- RF2 有 1,024 候选三 seed 结果和 78 条 validation；
- Chai-1/Boltz-2 有软件 smoke，已有 PVRIG 小规模 pose 但早期几何 QC 不足，不能当正式机制证据。

## 2. 软件能力矩阵

| 软件 | Node1 状态 | 已验证版本/入口 | 已有测试或结果 | 当前用途 |
|---|---|---|---|---|
| FoldX | 可运行 | `/data/qlyu/software/foldx/foldx`，FoldX 5.1 | 本轮 8X6B RepairPDB + AnalyseComplex PASS；此前无 PVRIG 批量结果 | pose 快速修复、界面 interaction energy、突变 ΔΔG |
| Rosetta | 可运行 | Rosetta 3.15 bundle；`score_jd2`、`relax`、`InterfaceAnalyzer`、`rosetta_scripts` 均为有效可执行文件 | 本轮 8X6B score_jd2 与 InterfaceAnalyzer PASS；此前无 PVRIG 批量结果 | FastRelax、界面 dG、dSASA、shape complementarity、unsatisfied H-bonds |
| PRODIGY | 可运行 | `/data/qlyu/software/bin/prodigy`，2.4.0 | 本轮 8X6B PASS；此前无 PVRIG 批量结果 | 快速结构界面 affinity/contact proxy |
| GROMACS | 可运行 | `/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx`，2024.4，CUDA | 版本和 CUDA 支持已确认；未发现 PVRIG/VHH `.xtc/.trr/.tpr/.edr` | 显式溶剂 MD、RMSD/RMSF、接触占有率 |
| OpenMM | 可运行 | Conda env `openmm`，8.4，CPU/CUDA/OpenCL | NBB2 smoke PDB 明确含 `STRUCTURE REFINED USING OPENMM 8.4`；未发现 PVRIG complex MD | 快速 minimization、短程 MD、批量 GPU simulation |
| gmx_MMPBSA | 可运行 | Conda env `gmx_mmpbsa`，1.6.3，AmberTools 20 | 版本和 CLI 已确认；未发现 PVRIG/VHH MMGBSA/PBSA 结果 | 对 MD snapshot 做 MM/GBSA 或 MM/PBSA 相对排序 |
| AmberTools | 可运行组件 | `tleap`、`sander`、`cpptraj`、`MMPBSA.py`、`ante-MMPBSA.py` | CLI 已确认；未发现 PVRIG 生产结果 | 建模、轨迹处理、自由能后处理 |
| IgFold | 可运行 | `/data/qlyu/software/vhh_eval_tools/bin/igfold-predict` | smoke PDB；统一 vhh-screen 单条交叉结构测试 | VHH 单体结构交叉验证 |
| NanoNet | 可运行 | `/data/qlyu/software/vhh_eval_tools/bin/nanonet-predict` | smoke backbone+CB PDB；统一 vhh-screen 单条测试 | 快速 VHH backbone 交叉验证 |
| NanoBodyBuilder2 | 生产可用 | `/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2` | 150k 和最新 100k 单体结构成功；OpenMM refine | 当前主单体结构来源 |
| RF2 | 生产/验证资产存在 | RFantibody `bin/rf2` | 1,024 候选 × 3 seed；另有 78 条 validation | 设计 pose recovery 和交互置信度 |
| Chai-1 | smoke 可用 | `/data/qlyu/software/envs/chai1/bin/chai-lab` | 软件 smoke；早期 PVRIG pose 需几何 QC | 小规模独立 co-fold pose |
| Boltz-2 | smoke 可用 | `/data/qlyu/anaconda3/envs/boltz/bin/boltz` | 软件 smoke；早期 PVRIG pose 需几何 QC | 小规模独立 complex pose |
| ColabFold | CLI 可用 | env `colabfold`，package 1.5.3；`colabfold_batch` | help PASS；未发现 PVRIG 正式结果 | 单体/Multimer 交叉结构预测 |
| AlphaFold3 | package/script 存在 | env `alphafold3`，package 3.0.1；`/data/qlyu/software/alphafold3/run_alphafold.py` | 未确认模型参数闭合和 PVRIG 结果 | 暂作为待验证 complex 路线 |
| ESMFold/OpenFold | 源码/环境存在 | env `esmfold_env`；`openfold-main/run_pretrained_openfold.py` | 未发现 PVRIG 结果；环境较旧 | 单体结构补充，不是当前主路线 |
| Desmond | 目录痕迹 | `/data/qlyu/software/Schrodinger/desmond-v7.7` | 未发现有效入口、license 验证或 PVRIG 结果 | 暂不纳入可复现流程 |
| NAMD/CHARMM | 未确认 | 未找到有效入口 | 无结果 | 当前不使用 |

## 3. 已有结构交叉验证结果

统一 `vhh-screen` smoke：

`/data/qlyu/software/vhh_eval_tools/tests/vhh_screen_smoke_20260707_180843`

单条 VHH 的结果：

- IgFold coverage = 1.0；
- NanoNet coverage = 1.0；
- NanoBodyBuilder2 coverage = 1.0；
- IgFold vs NanoBodyBuilder2 FR RMSD = 0.645 Å；
- L4 structure stability = PASS；
- TNP 六项均 green；
- 最终仍为 REVIEW，原因是 N-glyc/deamidation/isomerization 序列风险。

独立 smoke PDB：

- `/data/qlyu/software/vhh_eval_tools/tests/final_igfold/vhh_smoke_igfold.pdb`
- `/data/qlyu/software/vhh_eval_tools/tests/final_nanonet/vhh_smoke_nanonet_backbone_cb.pdb`
- `/data/qlyu/software/tests/immunebuilder/nanobodybuilder2_smoke.pdb`

这些证明三套单体结构工具可以组成 cross-tool FR/CDR 几何检查，但尚未覆盖当前 448 或 1,473 候选。

## 4. 本轮新增 8X6B 能量工具 smoke

为区分“文件存在”与“真实可运行”，本轮使用官方 PVRIG-PVRL2
复合物 8X6B 做了独立 smoke。

远端根目录：

`/data/qlyu/projects/pvrig_tool_capability_smoke_20260724`

输入 SHA256：

`b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868`

### PRODIGY 2.4.0

结果：

- return code = 0；
- elapsed = 17 s；
- intermolecular contacts = 84；
- predicted binding affinity = -9.8 kcal/mol；
- predicted Kd at 25 °C = 7.0e-08 M。

证据：

- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/prodigy/RECEIPT.json`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/prodigy/prodigy_8X6B.stdout`

### FoldX 5.1

结果：

- RepairPDB return code = 0，约 120 s；
- AnalyseComplex return code = 0，约 2 s；
- B/A interface interaction energy = -20.5719；
- interface residues = 46；
- interface clashing residues = 0。

证据：

- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/foldx/RECEIPT.json`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/foldx/Interaction_8X6B_Repair_AC.fxout`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/foldx/Summary_8X6B_Repair_AC.fxout`

### Rosetta 3.15

`score_jd2`：

- return code = 0；
- elapsed = 28 s；
- ref2015 total score = 379.929。

`InterfaceAnalyzer`：

- return code = 0；
- elapsed = 17 s；
- dG_cross = -39.822；
- dSASA_int = 1841.015 Å²；
- shape complementarity = 0.747；
- interface residues = 81；
- interface H-bonds = 3；
- delta unsatisfied H-bonds = 16。

证据：

- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/rosetta/RECEIPT.json`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/rosetta/INTERFACE_RECEIPT.json`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/rosetta/score.sc`
- `/data/qlyu/projects/pvrig_tool_capability_smoke_20260724/rosetta/interface.sc`

这些数字只证明软件执行和字段产出。8X6B 是 PVRIG-PVRL2 天然配体复合物，
不是 VHH-PVRIG；不能把这些数直接作为 VHH 阳性阈值。

## 5. 当前没有的结果

在 `/data/qlyu/projects` 和 `/data1/qlyu/projects` 中未找到：

- PVRIG/VHH FoldX 批量 `.fxout`；
- PVRIG/VHH Rosetta score/relax/interface 批次；
- PVRIG/VHH PRODIGY 批次；
- GROMACS `.xtc/.trr/.tpr/.edr`；
- Amber `.mdout/.rst`；
- `.dcd` trajectory；
- gmx_MMPBSA/MMGBSA/PBSA 输出；
- NAMD/CHARMM/Desmond PVRIG 生产结果。

因此当前筛选不能声称已经有动力学或自由能验证。

## 6. 如何接入当前 448/1,473 候选

### 第一层：448 条快速结构能量复核

对已经通过多 seed blocker geometry 的 448 条：

1. 每条保留代表性的 8X6B 和 9E6Y pose；
2. 统一去水、补原子、链命名和 protonation；
3. PRODIGY 快速计算 contacts、affinity proxy；
4. FoldX RepairPDB + AnalyseComplex；
5. Rosetta InterfaceAnalyzer；
6. 使用 within-tool percentile/rank，不直接混加不同软件的原始能量。

必须同时加入：

- HR-151、PVRIG-20/38/39 等阳性控制；
- PVRIG-PVRL2 8X6B/9E6Y 天然配体控制；
- 非阻断或几何阴性 decoy；
- 同一候选的多 seed/多构象 pose。

没有这些控制，Rosetta/FoldX/PRODIGY 的绝对值不能形成可靠阈值。

### 第二层：Top100 Rosetta/FoldX 稳健性

对快速重打分后的 Top100：

- Rosetta FastRelax 生成多个 decoy；
- 每个 decoy 运行 InterfaceAnalyzer；
- 观察 dG、dSASA、shape complementarity、unsatisfied H-bonds 的中位数和最差分位；
- FoldX 对统一 repaired pose 做 AnalyseComplex；
- 对潜在设计位点使用 FoldX BuildModel 或 Rosetta mutation scan。

### 第三层：Top10–20 动力学

不建议对 448 或 1,473 全量做 MD。

对 Top10–20：

- GROMACS 或 OpenMM 显式溶剂；
- 至少 3 个独立 seed；
- 初步可采用 10–20 ns/replicate；
- 分析 complex RMSD、VHH/PVRIG interface RMSF、关键接触占有率、CDR3 接触、
  hotspot 保持率和 PVRL2 界面遮挡保持率；
- 对平衡后的 snapshot 用 gmx_MMPBSA 做相对排序。

MMGBSA 只作为相对稳定性和能量排序，不能称为实验 Kd。

## 7. 当前推荐顺序

鉴于首轮提交截止时间临近：

1. 不等待全量 MD；
2. 先对现有 448 核心池做 PRODIGY/FoldX/Rosetta 快速重打分；
3. 用阳性/阴性控制校准后收敛到 100；
4. 从 100 中形成最终 50；
5. 对 Top10–20 并行动力学，用于后续复核和第二轮迭代。

新 1,473 路线应先完成正式 docking，再进入同样的能量重打分和 MD 漏斗。

