# node1 Paragraph / TNP / ProtParam 部署与调用记录

更新时间：2026-07-07 22:40 +08:00  
本地目录：`/mnt/d/work/抗体/node1`  
远端：`node1`，用户：`qlyu`  
统一工具目录：`/data/qlyu/software/vhh_eval_tools`

## 当前流程记录

当前 VHH 筛选主流程已经固化为：

```bash
/data/qlyu/software/vhh_eval_tools/bin/vhh-screen
```

主流程文档：

```bash
VHH_SCREENING_SYSTEM_NODE1.md
```

流程分层：

1. **编号和结构完整性**：`vhh-eval` 调用 AbNumber/ANARCI，检查 IMGT/Kabat 编号、FR/CDR、保守 Cys、FR4 motif、CDR 长度。失败即停止。
2. **VHH 特征**：FR2 hallmark、H44/H45 hydrophilic substitutions、VH-VL 接触面疏水性、AbNatiV VHH score。
3. **可开发性**：TNP、ProtParam/BioPython、liability motifs、N-glyc motif、多反应性 proxy。
4. **结构稳定性**：可选 IgFold/NanoNet/NanoBodyBuilder2 建模，检查模型覆盖率和跨工具 FR RMSD；后续复合物姿势再接 Chai-1/Boltz-2/HADDOCK3/Paragraph。

大规模初筛建议先只跑 1-3 层：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-screen candidates.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/my_batch_screen \
  --prefix my_batch \
  --tnp-ncores 4
'
```

少量 top hits 再跑结构层：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-screen candidates.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/my_batch_screen_struct \
  --prefix my_batch \
  --structure-tools igfold,nanonet,nanobodybuilder2 \
  --max-structures 20 \
  --gpu 0
'
```

## 本轮部署/复核结论

| 软件 | 状态 | 入口 | 说明 |
| --- | --- | --- | --- |
| Paragraph | 已部署并复核；本轮新增 VHH 便捷 wrapper | `/data/qlyu/software/vhh_eval_tools/bin/Paragraph`，`/data/qlyu/software/vhh_eval_tools/bin/paragraph-vhh` | 用于结构模型 residue-level paratope probability；可接 NanoBodyBuilder2/IgFold PDB |
| TNP | 已部署并复核 | `/data/qlyu/software/vhh_eval_tools/bin/TNP` | VHH developability 主评分；输出 CDR length/compactness、PSH/PPC/PNC 和 flags |
| ProtParam / Compute pI-Mw | 本轮新增独立批量 CLI | `/data/qlyu/software/vhh_eval_tools/bin/protparam-vhh` | 基于 BioPython 复现 pI/Mw/GRAVY/instability/aliphatic index/extinction 等基础字段 |

已验证输出目录：

```bash
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222
```

## 2.18 Paragraph

### 定位

Paragraph 是抗体 paratope 预测工具，输入抗体/VHH 结构，输出每个残基的 paratope probability。对当前 VHH 项目，它适合放在 docking 前，用于：

- 从 NanoBodyBuilder2 / IgFold 结构中找可能参与结合的 CDR/FR 残基。
- 生成 HADDOCK3 active/passive residue 约束假设。
- 辅助突变扫描、竞争实验、HDX/表位实验设计。

### 已部署入口

原始 CLI：

```bash
/data/qlyu/software/vhh_eval_tools/bin/Paragraph
```

本轮新增 VHH/heavy-chain 便捷 wrapper：

```bash
/data/qlyu/software/vhh_eval_tools/bin/paragraph-vhh
```

源码位置：

```bash
/data/qlyu/software/Paragraph
```

### 标准 Paragraph 调用

Paragraph 原始输入需要一个无表头三列 key CSV：`pdb_code,H_chain,L_chain`，以及 PDB 文件夹。

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/Paragraph \
  --pdb_H_L_csv /abs/path/pdb_H_L_key.csv \
  --pdb_folder_path /abs/path/pdbs \
  --out_path /abs/path/paragraph_predictions.csv \
  --heavy
'
```

### VHH 便捷调用

`paragraph-vhh` 会自动创建 key CSV 和工作目录，适合单链 VHH PDB：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/paragraph-vhh /path/to/vhh_model.pdb \
  -o /path/to/paragraph_vhh_predictions.csv \
  --chain H
'
```

多个 PDB：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/paragraph-vhh model1.pdb model2.pdb model3.pdb \
  -o paragraph_batch_predictions.csv \
  --chain H \
  --keep-work
'
```

### 已验证 smoke

官方 example：

```bash
/data/qlyu/software/Paragraph/Paragraph/example/example_predictions.csv
```

本轮 VHH wrapper smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222/paragraph_vhh_4edw_heavy.csv
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222/paragraph_vhh_nbb2_smoke.csv
```

其中 `paragraph_vhh_nbb2_smoke.csv` 是用此前 NanoBodyBuilder2 生成的 VHH smoke PDB 跑通的。

### 局限

- 输入 PDB 最好是 IMGT-numbered；NanoBodyBuilder2 输出通常比较适配。
- Paragraph 训练数据主要来自常规抗体复合物，VHH 的 framework-mediated contact 和长 CDR3 可能导致默认阈值偏差。
- 建议把 Paragraph 结果作为 docking/实验约束候选，不单独作为 binding 判定。

## 2.19 TNP — Therapeutic Nanobody Profiler

### 定位

TNP 是当前 VHH 可开发性里最优先看的主评分工具之一。它针对 nanobody/VHH 重新校准了类似 TAP 的 developability descriptor/profile 思路。

### 已部署入口

```bash
/data/qlyu/software/vhh_eval_tools/bin/TNP
```

源码位置：

```bash
/data/qlyu/software/TNP
```

### 单条序列调用

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
SEQ="QVQL...TVSS"
$ROOT/bin/TNP --seq "$SEQ" --name sample_vhh --output /path/to/tnp_out --ncores 1
'
```

### 批量 FASTA 调用

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/TNP --file candidates.fasta --name candidates --output /path/to/tnp_out --ncores 4
'
```

### 输出

主输出 JSON：

```bash
/path/to/tnp_out/TNP_Results_SingleSeqEntry_<name>.json
```

核心字段：

- `Total CDR Length`
- `CDR3 Length`
- `CDR3 Compactness`
- `PSH`：Patch CDR Surface Hydrophobicity
- `PPC`：Patch Positive Charge
- `PNC`：Patch Negative Charge
- `Flags`：`L/L3/C/PSH/PPC/PNC` green/amber/red 等风险等级

### 已验证 smoke

本轮 smoke 输出：

```bash
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222/tnp_smoke/TNP_Results_SingleSeqEntry_vhh_smoke.json
```

关键结果：

```json
{"Flags": {"L": "green", "L3": "green", "C": "green", "PSH": "green", "PPC": "green", "PNC": "green"}}
```

说明：TNP 在当前环境有时会打印非致命 PDB 后处理提示，但主 JSON 评分文件正常生成；`vhh-screen` 读取的是主 JSON。

### 在当前流程中的位置

`vhh-screen` 第三层会自动调用 TNP，并把 TNP flags 合并进 `screen_summary.tsv`：

```text
tnp_L_flag
tnp_L3_flag
tnp_C_flag
tnp_PSH_flag
tnp_PPC_flag
tnp_PNC_flag
tnp_PSH
tnp_PPC
tnp_PNC
```

## 2.20 ProtParam / Compute pI-Mw

### 定位

ProtParam / Compute pI-Mw 是确定性物化性质计算，不是 ML 模型。当前用 BioPython `ProteinAnalysis` 复现核心指标，适合每条 VHH 的基础 QC。

### 本轮新增入口

```bash
/data/qlyu/software/vhh_eval_tools/bin/protparam-vhh
```

脚本位置：

```bash
/data/qlyu/software/vhh_eval_tools/protparam_vhh.py
```

### 用法

TSV 输出：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/protparam-vhh candidates.fasta -o protparam.tsv
'
```

CSV 输出：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/protparam-vhh candidates.fasta -o protparam.csv --csv
'
```

### 输出字段

主要字段：

```text
id
length
valid_aa_len
invalid_aa_count
molecular_weight
theoretical_pI
gravy
instability_index
aromaticity
aliphatic_index
charge_pH7_0
charge_pH7_4
extinction_reduced_cys
extinction_oxidized_cys
cys_count
num_negative_DE
num_positive_KR
count_A ... count_Y
```

### 已验证 smoke

本轮 smoke 输出：

```bash
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222/protparam_smoke.tsv
```

关键结果：

```text
molecular_weight=12861.324
theoretical_pI=8.642
gravy=-0.1916
instability_index=27.055
aliphatic_index=68.067
charge_pH7_4=1.598
extinction_reduced_cys=19940
extinction_oxidized_cys=20065
```

### 在当前流程中的位置

`vhh-screen` 和 `vhh-eval` 已经内置部分 ProtParam 字段：MW、pI、GRAVY、instability、aromaticity、charge pH 7.4。  
如果只想快速计算物化性质而不跑 AbNatiV/TNP/结构，可以直接用 `protparam-vhh`。

## 运行验证摘要

本轮验证命令生成目录：

```bash
/data/qlyu/software/vhh_eval_tools/tests/paragraph_tnp_protparam_20260707_223222
```

文件清单：

```bash
protparam_smoke.tsv
tnp_smoke.log / tnp_smoke/TNP_Results_SingleSeqEntry_vhh_smoke.json
paragraph_example.log
paragraph_vhh_4edw_heavy.csv
paragraph_vhh_nbb2_smoke.csv
```

当前统一 wrapper 清单：

```bash
abnativ
igfold-predict
nanonet-predict
Paragraph
paragraph-vhh
protparam-vhh
sapiens-score
TNP
vhh-eval
vhh-screen
```

