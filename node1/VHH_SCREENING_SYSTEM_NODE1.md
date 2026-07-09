# node1 VHH 四层筛选体系

更新时间：2026-07-07 18:15 +08:00  
本地目录：`/mnt/d/work/抗体/node1`  
远端：`node1`，用户：`qlyu`  
统一入口：`/data/qlyu/software/vhh_eval_tools/bin/vhh-screen`

## 目标

把当前已经部署的 VHH/nanobody 工具组织成一条可重复调用的筛选流水线：

1. 第一层：编号和结构完整性。失败即停止，不进入后续评分。
2. 第二层：VHH 特征和单域适配性。这一层是关键门槛。
3. 第三层：可开发性风险。
4. 第四层：结构建模稳定性。默认不跑，按需启用结构工具。

## 已重新核验的应用

2026-07-07 17:59 左右重新检查过 node1：

- GPU：0/1/6/7 基本空闲；2/3/4/5 有任务占用。
- 统一 wrapper 均存在并能响应 help：
  - `/data/qlyu/software/vhh_eval_tools/bin/vhh-eval`
  - `/data/qlyu/software/vhh_eval_tools/bin/sapiens-score`
  - `/data/qlyu/software/vhh_eval_tools/bin/abnativ`
  - `/data/qlyu/software/vhh_eval_tools/bin/nanonet-predict`
  - `/data/qlyu/software/vhh_eval_tools/bin/igfold-predict`
  - `/data/qlyu/software/vhh_eval_tools/bin/TNP`
  - `/data/qlyu/software/vhh_eval_tools/bin/Paragraph`
  - `/data/qlyu/software/vhh_eval_tools/bin/vhh-screen`
- 结构/复合物工具入口可响应：
  - `/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2`
  - `/data/qlyu/anaconda3/envs/boltz/bin/boltz`
  - `/data/qlyu/software/envs/chai1/bin/chai-lab`
  - `/data/qlyu/anaconda3/envs/haddock3/bin/haddock3`

## 新增脚本

远端脚本：

```bash
/data/qlyu/software/vhh_eval_tools/vhh_screen.py
/data/qlyu/software/vhh_eval_tools/bin/vhh-screen
```

查看帮助：

```bash
ssh.exe node1 '/data/qlyu/software/vhh_eval_tools/bin/vhh-screen --help'
```

## 快速用法

### 只跑序列层级：1-3 层

适合批量初筛，大量候选先用这个：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-screen candidates.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/my_batch_screen \
  --prefix my_batch \
  --tnp-ncores 4
'
```

### 完整 4 层，包括结构交叉验证

适合少量候选或 top hits：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-screen candidates.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/my_batch_screen_struct \
  --prefix my_batch \
  --tnp-ncores 1 \
  --structure-tools igfold,nanonet,nanobodybuilder2 \
  --max-structures 20 \
  --gpu 0
'
```

说明：

- `--max-structures 20` 表示只对前 20 个通过前 3 层的候选建模。
- 如果候选很多，先不加 `--structure-tools`，否则 TNP + 结构会比较耗时。
- 第一层失败的序列会被自动跳过，不送入 AbNatiV/TNP/结构建模。

## 输出文件

每次运行输出目录中固定生成：

```bash
screen_summary.tsv      # 主表，适合 Excel/R/Python 汇总
screen_details.json     # 完整 JSON，包括编号、TNP、AbNatiV、Sapiens、结构路径
screen_report.md        # 简短 Markdown 报告
logs/                   # 每个外部工具的日志
```

中间结果包括：

```bash
<prefix>.vhh_eval.tsv
<prefix>.numbering.json
<prefix>.layer1_pass.fasta
<prefix>.sapiens.csv
layer2_abnativ/*_abnativ_seq_scores.csv
layer3_tnp/<seq_id>/TNP_Results_SingleSeqEntry_<seq_id>.json
structures/<seq_id>/{igfold.pdb,nanobodybuilder2.pdb,nanonet/*.pdb}
```

## 总体判定

`final_verdict` 可能值：

| 值 | 含义 |
| --- | --- |
| `PASS` | 四层均无 warning/fail，适合进入下一轮 |
| `REVIEW` | 没有硬失败，但存在可开发性或边界 warning，需要人工/后续规则复核 |
| `REJECT_NUMBERING_OR_FRAMEWORK` | 第一层失败；编号或框架不稳定，后续不要用 |
| `REJECT_NOT_VHH_LIKE` | 第二层失败；不像合适的 VHH/单域抗体 |
| `DEPRIORITIZE_DEVELOPABILITY` | 第三层失败；可开发性风险过高 |
| `DEPRIORITIZE_STRUCTURE` | 第四层失败；结构建模不稳定 |

## 第一层：编号和结构完整性

硬门槛，失败即停止。

检查项：

- `ANARCI / AbNumber` 是否能在 IMGT 和 Kabat 下稳定编号。
- 是否识别为 heavy chain：`imgt_chain_type=H`、`kabat_chain_type=H`。
- FR1/2/3/4 和 CDR1/2/3 是否都存在。
- 长度是否合理：绝对范围 95-160 aa；105-145 aa 为更常见范围。
- IMGT 保守 Cys：`H23=C`、`H104=C`。
- FR4 motif：要求以 `W` 开头并以 `TVSS` 结尾；强匹配 `WG.GT.*VTVSS`。
- CDR 长度：CDR3 5-30 aa 为硬范围；CDR1 4-12、CDR2 3-15 作为 warning 范围。

对应输出列：

```text
L1_numbering_integrity
imgt_ok
kabat_ok
imgt_chain_type
imgt_cdr1_len
imgt_cdr2_len
imgt_cdr3_len
conserved_cys_imgt_H23_H104
fr4
L1_reasons
```

## 第二层：VHH 特征

关键门槛。第一层通过后才运行。

检查项：

- Kabat FR2 hallmark score：来自 `H37/H44/H45/H47`。
- 关键 hydrophilic substitutions：要求 `H44 in E/Q` 且 `H45 in R/K`。
- 原 VH-VL 接触面疏水性：统计 `H44/H45/H47` 中疏水残基数量，理想值不超过 1。
- AbNatiV VHH score：
  - `<0.55`：fail
  - `0.55-0.70`：warn
  - `>=0.70`：通过
- 单域适配性：由 hallmark、H44/H45、界面疏水性和 AbNatiV 综合给出 `good/borderline/poor`。

对应输出列：

```text
L2_vhh_features
fr2_hallmark_score
fr2_hallmark_residues
fr2_interface_residues
fr2_interface_hydrophobic_count
single_domain_suitability
abnativ_vhh_score
abnativ_fr_vhh_score
L2_reasons
```

说明：ANARCI/AbNumber 本身通常只稳定判断 heavy chain 和编号，不应把它的 species 标签直接当作 VHH 判定；本体系把“VHH-like”放在第二层，用 FR2 hallmark + AbNatiV 共同判断。

## 第三层：可开发性

第一、二层通过后运行。

检查项：

- TNP 主评分：`L/L3/C/PSH/PPC/PNC` flags。
- 表面疏水 patch：优先看 TNP `PSH` flag。
- 净电荷：`abs(charge_pH7_4)>12` fail，`>8` warn。
- pI：`<4.5` 或 `>10.5` fail；`<5.0` 或 `>9.5` warn。
- N-glyc motif：`N[^P][ST][^P]`，出现即 warn。
- Cys：奇数 Cys fail；不是 2 个 Cys则 warn。
- deamidation / isomerization / acid clipping：出现 motif 即 warn。
- hydrophobic run：5 连疏水残基 fail。
- 多反应性 proxy：由高 pI/高电荷、TNP patch flags、polybasic motif 等推断 `low/moderate/high`。

对应输出列：

```text
L3_developability
mw
pI
gravy
charge_pH7_4
nglyc_motif_count
nglyc_motif_hits
cys_count
deamidation_NG_NS_NT_count
isomerization_DG_DS_DD_DT_count
acid_cleavage_DP_count
hydrophobic_5_count
polyreactivity_proxy
tnp_L_flag
tnp_L3_flag
tnp_C_flag
tnp_PSH_flag
tnp_PPC_flag
tnp_PNC_flag
L3_reasons
```

## 第四层：结构建模稳定性

默认不运行；只有指定 `--structure-tools` 才运行。

当前可用结构工具：

- `igfold`
- `nanonet`
- `nanobodybuilder2`，即 ImmuneBuilder/NanoBodyBuilder2，可视作当前的 ABodyBuilder2 路线

检查项：

- PDB 是否生成。
- C-alpha 覆盖率：低于 0.90 fail，0.90-0.97 warn。
- FR 区跨工具 C-alpha RMSD：
  - IgFold vs NanoBodyBuilder2 大于 4 Å：fail
  - 任意跨工具大于 5 Å：warn
  - 任意跨工具大于 3 Å：warn
- CDR3 anchor C-alpha distance：作为几何记录，不直接判断好坏。

当前没有自动判断的项：

- AlphaFold：node1 有相关环境痕迹，但没有纳入本 `vhh-screen` 稳定路线。
- RosettaAntibody：未部署为本流水线入口。
- 多 seed 下 FR 一致性：当前是跨工具一致性，不是真正多 seed。
- CDR graft 后是否破坏整体折叠：需要 parent scaffold / graft 元数据。
- CDR3 出口方向是否适合目标表位：需要抗原结构、表位约束或 Chai/Boltz/HADDOCK3 复合物模型。

对应输出列：

```text
L4_structure_stability
igfold_coverage
nanonet_coverage
nanobodybuilder2_coverage
fr_rmsd_igfold_vs_nanobodybuilder2
fr_rmsd_igfold_vs_nanonet
fr_rmsd_nanobodybuilder2_vs_nanonet
cdr3_anchor_ca_distance
L4_reasons
```

## 验证结果

### 好序列 smoke

命令：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
OUT=$ROOT/tests/vhh_screen_smoke_20260707_180843
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-screen $ROOT/tests/smoke_vhh.fasta \
  -o $OUT \
  --prefix smoke \
  --tnp-ncores 1 \
  --structure-tools igfold,nanonet,nanobodybuilder2 \
  --max-structures 1 \
  --gpu 0
'
```

输出目录：

```bash
/data/qlyu/software/vhh_eval_tools/tests/vhh_screen_smoke_20260707_180843
```

关键结果：

```text
final_verdict=REVIEW
L1_numbering_integrity=PASS
L2_vhh_features=PASS
L3_developability=WARN
L4_structure_stability=PASS
fr2_hallmark_score=1.0
abnativ_vhh_score=0.7664
TNP flags=green/green/green/green/green/green
igfold_coverage=1.0
nanonet_coverage=1.0
nanobodybuilder2_coverage=1.0
fr_rmsd_igfold_vs_nanobodybuilder2=0.645 Å
```

为什么是 `REVIEW`：第三层发现 `N-glyc motif NTTY@76-79`、`deamidation` 和 `isomerization` motif，需要后续人工或设计规则复核。

### 坏序列门控测试

输出目录：

```bash
/data/qlyu/software/vhh_eval_tools/tests/vhh_screen_bad_gate_20260707_181148
```

结果：

```text
final_verdict=REJECT_NUMBERING_OR_FRAMEWORK
L1_numbering_integrity=FAIL
L2_vhh_features=SKIPPED
L3_developability=SKIPPED
L4_structure_stability=SKIPPED
```

说明第一层失败后确实不会继续消耗 AbNatiV/TNP/结构建模资源。

## 推荐使用策略

### 大规模候选库

先跑 1-3 层，不开结构：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-screen library.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/library_screen_seq \
  --prefix library \
  --tnp-ncores 8
'
```

然后筛选：

- 保留 `final_verdict in PASS,REVIEW`。
- 优先 `L1=PASS`、`L2=PASS`。
- 第三层只接受可解释 warning，例如单个 N-glyc motif 可通过突变修复。

### Top hits

对 top hits 再开结构：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-screen top_hits.fasta \
  -o /data/qlyu/software/vhh_eval_tools/runs/top_hits_screen_struct \
  --prefix top_hits \
  --structure-tools igfold,nanonet,nanobodybuilder2 \
  --max-structures 50 \
  --gpu 0
'
```

### 进入抗原结合姿势评估

`vhh-screen` 的第四层只评估单体结构稳定性；CDR3 是否朝向目标表位，需要另起复合物流程：

1. 用 `Chai-1` / `Boltz-2` 生成 VHH-Ag pose。
2. 用 `Paragraph` 或已知突变/表位信息给 paratope/epitope 约束。
3. 用 `HADDOCK3` 在约束下 refine。
4. 再评价 CDR3 出口方向、界面覆盖、PVRIG/PVRL2 竞争位点遮挡等。

