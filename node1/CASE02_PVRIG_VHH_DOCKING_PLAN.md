# Case 02 PVRIG VHH 结构与复合物 docking 计划

日期：2026-07-07
工作目录：`/mnt/d/work/抗体/node1`
目标文档：`/mnt/d/work/抗体/机制/case_studies/02_PVRIG_VHH_20_30_38_39_151_HR151_机制详解.md`
远端节点：`node1` / `qlyu`

## 目标

先获得可校对的结构链路：

```text
PVRIG/PVRL2 reference structures
  + HR-151 VHH sequence
  -> HR-151 VHH monomer model
  -> HR-151-PVRIG complex poses
  -> superpose PVRL2 back
  -> score interface proximity, hotspot contacts, PVRL2 occlusion, CDR-dominance
```

当前不把 docking pose 当作实验事实；所有 VHH-PVRIG 接触位点都标记为 docking inference。

## 已有输入

### PVRIG/PVRL2 参考结构

本地已有：

```text
/mnt/d/work/抗体/机制/data/structures/8X6B.pdb
/mnt/d/work/抗体/机制/data/structures/9E6Y.pdb
/mnt/d/work/抗体/机制/data/structures/PVRIG_hotspot_set_v1.csv
/mnt/d/work/抗体/机制/data/structures/PVRIG_consensus_interface_residues.csv
```

链映射来自机制文档：

```text
8X6B: PVRIG chain B, PVRL2 chain A
9E6Y: PVRIG chain A, PVRL2 chain D
```

### 当前可直接建模的 VHH

完整 VHH 序列目前确定的是 HR-151：

```text
HVQLVESGGGSVQAGGSLRLSCVASASGFTYRPYCMAWFRQAPGKEREAVAGIDIFGGTTYADSVKGRFTASRDNAGFSLFLQMNDLKPEDTAMYYCAAGDSPDGRCPPLGQGLNYWGQGTQVTVSS
```

本地来源：`/mnt/d/work/抗体/positives/known_positive_antibodies.fasta`

HR-151 IMGT CDR：

```text
CDR1 ASGFTYRPYC
CDR2 IDIFGGT
CDR3 AAGDSPDGRCGLPPQGLNY
```

PVRIG-20/30 目前只有较可靠的 Kabat CDR 片段；38/39/151 的完整专利表格仍需人工 OCR/PDF 补齐。因此第一轮先用 HR-151 跑通流程，20/30/38/39/151 后续作为批量扩展，不在缺完整序列时强行建完整结构。

## 使用已有 node1 工具

| 阶段 | 工具 | 用途 |
| --- | --- | --- |
| 单体 VHH 结构 | NanoBodyBuilder2 / ImmuneBuilder | 从 HR-151 VHH 序列生成 nanobody 单体 PDB |
| 复合物候选 1 | Chai-1 | HR-151 + PVRIG co-folding，产生初始复合物 pose |
| 复合物候选 2 | Boltz-2 | 另一套 VHH-PVRIG complex prediction，做交叉验证 |
| 约束 docking | HADDOCK3 | 用 PVRIG consensus interface/hotspot + VHH CDR 作为 ambiguous restraints 做 docking/refinement |
| 生成式设计 | RFantibody | 暂不作为 HR-151 docking 主工具；后续用于新 VHH backbone/sequence 设计与 RF2 过滤 |

DeepNano 只适合 sequence binding-like 预筛，不用于获取复合物结构。

## 执行路线

### Step 0：建立项目目录

本地结果目录：

```text
/mnt/d/work/抗体/docking/case02_hr151_pvrig/
```

node1 远端工作目录：

```text
/data/qlyu/projects/pvrig_case02_hr151_docking/
```

### Step 1：准备 receptor 与 reference ligand

从 `8X6B.pdb` 和 `9E6Y.pdb` 提取：

```text
8X6B_PVRIG_B.pdb
8X6B_PVRL2_A.pdb
9E6Y_PVRIG_A.pdb
9E6Y_PVRL2_D.pdb
```

第一轮 docking receptor 采用 `8X6B_PVRIG_B.pdb`，同时保留 `9E6Y` 做 robustness check。

### Step 2：用 NanoBodyBuilder2 预测 HR-151 VHH 单体结构

远端命令模板：

```bash
ssh.exe node1 'mkdir -p /data/qlyu/projects/pvrig_case02_hr151_docking/01_vhh_monomer && \
BIN=/data/qlyu/anaconda3/envs/boltz/bin && \
SEQ="HVQLVESGGGSVQAGGSLRLSCVASASGFTYRPYCMAWFRQAPGKEREAVAGIDIFGGTTYADSVKGRFTASRDNAGFSLFLQMNDLKPEDTAMYYCAAGDSPDGRCPPLGQGLNYWGQGTQVTVSS" && \
CUDA_VISIBLE_DEVICES=0 PATH="$BIN:$PATH" NanoBodyBuilder2 \
  -H "$SEQ" \
  -o /data/qlyu/projects/pvrig_case02_hr151_docking/01_vhh_monomer/hr151_nanobodybuilder2.pdb \
  --n_threads 4 -v'
```

单体 QC：

```text
1. CDR3 是否伸出而非塌陷；
2. CDR3 Cys 是否形成异常二硫键或暴露游离 Cys；
3. framework 是否有明显断链/异常几何。
```

### Step 3：Chai-1 / Boltz-2 生成无约束复合物候选

目的不是最终判定，而是快速得到多个可比较 pose。

Chai-1：输入 FASTA 包含 HR-151 VHH 和 PVRIG ECD 序列；输出 CIF/score。

Boltz-2：输入 YAML 包含 HR-151 VHH 和 PVRIG ECD；输出 PDB/confidence。

保留每个工具的 top poses，然后统一转换到 PDB，进入同一评分脚本。

### Step 4：HADDOCK3 做机制约束 docking

HADDOCK restraints：

```text
PVRIG active/passive side:
- core hotspots: Q6DKI7 71,72,74,81,82,83,90,92,95,96,98,100,135,137,138,139,140,141,142,143,144
- secondary: 87,97
- soft hints: R95 high, I97 low, S67 excluded/not driver

VHH side:
- active/passive: HR-151 CDR1/CDR2/CDR3, especially CDR3
- framework contacts downgraded
```

HADDOCK3 的优势是可以直接编码“靠近 PVRIG-PVRL2 interface + CDR 主导”的约束，弥补 Chai/Boltz 可能跑到远端表面的风险。

### Step 5：把 PVRL2 叠回去做 blocking 校对

每个 VHH-PVRIG pose 都叠到 8X6B/9E6Y 的 PVRIG 上，再把 PVRL2 放回参考位置，计算：

```text
1. VHH-PVRL2 heavy-atom clash count / min distance；
2. VHH 是否占据 PVRL2 原结合表面；
3. VHH 接触的 PVRIG residues 与 hotspot overlap；
4. VHH 接触是否由 CDR/CDR3 主导；
5. 是否接触或靠近 H92/R95/R98/W100 与 K135/F139/S143/W144 区域。
```

### Step 6：解释分级

沿用目标文档 16.4：

```text
A: CDR3/CDR 主导 + 靠近 consensus interface + 明显遮挡 PVRL2
B: 靠近 interface，但遮挡不足
C: 远离 PVRL2 interface，可能只是 binder
D: framework 非特异或结构不合理
X: 与 HR-151/公开阳性太相似的新设计，作为 leakage risk 排除
```

第一轮 HR-151 本身是 positive control，不做设计候选，只用于校准 docking 流程。

## 第一轮交付物

```text
/mnt/d/work/抗体/docking/case02_hr151_pvrig/inputs/
/mnt/d/work/抗体/docking/case02_hr151_pvrig/monomer/hr151_nanobodybuilder2.pdb
/mnt/d/work/抗体/docking/case02_hr151_pvrig/complex/chai1_poses/
/mnt/d/work/抗体/docking/case02_hr151_pvrig/complex/boltz_poses/
/mnt/d/work/抗体/docking/case02_hr151_pvrig/complex/haddock3_poses/
/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/pose_scoring_table.csv
/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/top_pose_mechanism_notes.md
```

## 决策点

如果 HR-151 positive control 的 top pose 不能靠近 PVRIG-PVRL2 consensus interface，或者不能遮挡 PVRL2，则不进入批量候选设计；先调整：

```text
1. receptor 选 8X6B 还是 9E6Y；
2. CDR/hotspot restraints；
3. Chai/Boltz sampling 数量；
4. HADDOCK active/passive residue 定义；
5. 是否需要更多 VHH family 完整序列作为校准集。
```
