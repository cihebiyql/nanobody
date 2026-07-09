# node1 VHH 筛选/评价工具部署记录

更新时间：2026-07-07 16:05 +08:00  
本地目录：`/mnt/d/work/抗体/node1`  
远端：`node1`，用户：`qlyu`  
软件根目录：`/data/qlyu/software`  
统一评价工具目录：`/data/qlyu/software/vhh_eval_tools`

## 快速结论

这批 VHH/nanobody 筛选评价工具已经补齐到可以直接做批量序列评价、human-likeness/VHH-ness 打分、可开发性主评分、单体结构交叉验证、paratope 预测和 VHH-Ag 复合物建模的状态。

综合健康检查日志：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_eval_health_20260707_155602.log
```

健康检查覆盖：`vhh-eval`、Sapiens、AbNatiV、NanoNet、IgFold、TNP、Paragraph、ABlooper help。

## 稳定 SSH 入口

后续 AI 或脚本默认用这个连接方式：

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 '<remote command>'
```

GPU 检查：

```bash
ssh.exe node1 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits'
```

## 工具状态总表

| 模块 | 工具/功能 | 状态 | 入口/环境 | 验证证据 |
| --- | --- | --- | --- | --- |
| 编号和边界 | ANARCI | 已可用 | `/data/qlyu/anaconda3/envs/boltz`，由 AbNumber/AbNatiV 调用 | `vhh-eval` 和 AbNatiV smoke 均完成 IMGT/Kabat/ANARCI 对齐 |
| 编号和边界 | AbNumber | 已可用 | `/data/qlyu/software/envs/vhh-eval` | `abnumber 0.4.4`，`final_vhh_eval.tsv` 输出 IMGT/Kabat FR/CDR |
| VHH 特征 | AbNumber 提取 Kabat/IMGT 位点 | 已可用 | `vhh-eval` | 输出 `imgt_fr*`、`imgt_cdr*`、`kabat_fr*`、`kabat_cdr*` |
| VHH 特征 | 自定义 FR2 hallmark scanner | 已可用 | `vhh-eval` | smoke: `fr2_hallmark_score=1.0`，`H37/H44/H45/H47` 命中 |
| VHH 特征 | AbNatiV VHH-ness | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/abnativ` | smoke: `AbNatiV VHH Score=0.7664` |
| VHH 特征 | Sapiens/BioPhi human-likeness | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/sapiens-score` | smoke: `mean_self_probability=0.7058` |
| 可开发性 | TNP 主评分 | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/TNP` | smoke JSON 输出 L/L3/C/PSH/PPC/PNC 全 green |
| 可开发性 | ProtParam/BioPython | 已可用 | `vhh-eval` | 输出 MW、pI、GRAVY、instability、aromaticity、charge pH 7.4 |
| 可开发性 | 自定义 liability scanner | 已可用 | `vhh-eval` | 输出 N-glyc、deamidation、oxidation、RGD、Cys、hydrophobic run 等 |
| 可开发性 | NetNGlyc 或 motif scan | motif scan 已可用 | `vhh-eval` | smoke: `NTTY@76-79` N-glyc motif 命中；真正 NetNGlyc 未自动装 |
| 可开发性 | A3D/CamSol | 未自动部署 | 后续结构后可补 | PyPI A3D 包老旧，Conda `lcbio` 网络 reset；CamSol 未找到可靠开源 CLI 路线 |
| 结构稳定性 | NanoBodyBuilder2 / ImmuneBuilder | 已可用 | `/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2` | 前序部署文档已有 VHH PDB smoke |
| 结构稳定性 | IgFold | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/igfold-predict` | smoke PDB: `final_igfold/vhh_smoke_igfold.pdb` |
| 结构稳定性 | NanoNet | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/nanonet-predict` | smoke PDB: `final_nanonet/vhh_smoke_nanonet_backbone_cb.pdb` |
| 结构稳定性 | ABlooper | 已安装，有边界 | `/data/qlyu/software/envs/vhh-eval/bin/ABlooper` | `--help` 可用；VHH-only 不适合直接跑，要求 IMGT numbered H+L PDB |
| 结构稳定性 | Chai-1 | 已可用 | `/data/qlyu/software/envs/chai1/bin/chai-lab` | 见 `NANOBODY_TOOLS_NODE1_DEPLOYMENT.md` |
| 结构稳定性 | Boltz-2 | 已可用 | `/data/qlyu/anaconda3/envs/boltz/bin/boltz` | 见 `NANOBODY_TOOLS_NODE1_DEPLOYMENT.md` |
| 结构稳定性 | HADDOCK3 | 已可用 | `/data/qlyu/anaconda3/envs/haddock3/bin/haddock3` | 见 `NANOBODY_TOOLS_NODE1_DEPLOYMENT.md` |
| 结构稳定性 | Paragraph | 已可用 | `/data/qlyu/software/vhh_eval_tools/bin/Paragraph` | `--example` 生成 `example_predictions.csv` |

## 统一序列评价：vhh-eval

用途：一次性输出编号、FR/CDR 边界、FR2 hallmark、ProtParam、简单 liability 和 N-glyc motif。

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-eval input.fasta -o out.tsv --json out_numbering.json
'
```

输入：FASTA，每条记录一条 VHH/抗体重链序列。  
输出：

- `out.tsv`：每条序列一行，包含 IMGT/Kabat FR/CDR、pI、MW、GRAVY、liability counts。
- `out_numbering.json`：编号 map，后续可以按 Kabat/IMGT 位点取残基。

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_vhh_eval.tsv
/data/qlyu/software/vhh_eval_tools/tests/final_vhh_eval.json
```

smoke 关键结果：

- `pI=8.642`
- `GRAVY=-0.1916`
- `fr2_hallmark_score=1.0`
- `nglyc_motif_hits=NTTY@76-79`

## VHH-ness：AbNatiV

入口 wrapper 固定了模型路径和 `hmmscan` 路径：

```bash
/data/qlyu/software/vhh_eval_tools/bin/abnativ
```

已部署：

- Python 包：`abnativ 2.0.8`
- VHH classic checkpoint：`/data/qlyu/software/AbNatiV_models/vhh_model.ckpt`
- 模型目录环境变量：`ABNATIV_MODELS_DIR=/data/qlyu/software/AbNatiV_models`

单条/批量 FASTA 打分：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/abnativ score \
  -nat VHH \
  -mean \
  -i $ROOT/tests/smoke_vhh.fasta \
  -odir $ROOT/tests/abnativ_vhh_run \
  -oid vhh_batch \
  -align -isVHH -ncpu 1
'
```

输出：

```bash
<data output dir>/<output_id>_abnativ_seq_scores.csv
```

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_abnativ_vhh/vhh_smoke_abnativ_seq_scores.csv
```

smoke 关键结果：

- `AbNatiV VHH Score=0.7664149963731643`
- `AbNatiV FR-VHH Score=0.8608752270100815`

说明：

- 当前部署的是 `VHH` classic checkpoint，足够跑 `abnativ score -nat VHH`。
- 官方 `abnativ init` 会尝试下载多个 checkpoint，其中 `vhh2_model.ckpt` 单文件约 1.09GB；node1 直连 Zenodo 约 20-50KB/s，预计 10 小时以上，所以没有全量下载 VHH2/VH/VL/paired/AntibodyBuilder3 模型。
- 许可证：包元数据为 `CC BY-NC-SA 4.0`，商业使用前需要确认授权。

## Human-likeness：Sapiens / BioPhi 模型

入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/sapiens-score
```

已部署本地模型快照：

```bash
/data/qlyu/software/Sapiens_models/tokenizer
/data/qlyu/software/Sapiens_models/vh
/data/qlyu/software/Sapiens_models/vl
```

用法：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/sapiens-score input.fasta -o sapiens_scores.csv --chain H
'
```

输出列：

- `mean_self_probability`：原序列每个位点在 Sapiens 模型下的平均 self probability，可作为 human-likeness 粗筛分数。
- `best_sapiens_sequence`：模型逐位最偏好氨基酸。
- `suggested_mutations`：与输入序列不同的逐位建议。

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_sapiens.csv
```

smoke 关键结果：

- `mean_self_probability=0.7058360434857299`
- 建议突变数：`24`

说明：

- `sapiens-score` 已设置 `TRANSFORMERS_OFFLINE=1` 和 `HF_HUB_OFFLINE=1`，不会在运行时访问 HuggingFace。
- 当前只做 VH/VL 模型打分；VHH 按重链 `--chain H` 评估 human-likeness。

## 可开发性主评分：TNP

入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/TNP
```

单条序列：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
SEQ="QVQL...TVSS"
$ROOT/bin/TNP --seq "$SEQ" --name sample_vhh --output $ROOT/tests/tnp_run --ncores 1
'
```

批量 FASTA：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/TNP --file input.fasta --name batch_vhh --output /path/to/tnp_out --ncores 4
'
```

主要输出：

```bash
/path/to/tnp_out/TNP_Results_SingleSeqEntry_<name>.json
```

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_tnp/TNP_Results_SingleSeqEntry_vhh_smoke.json
```

smoke JSON：

```json
{"vhh_smoke": {"Total CDR Length": 28, "CDR3 Length": 13, "CDR3 Compactness": 0.9128976430372244, "PSH": 103.3488, "PPC": 0.0092, "PNC": 0.0}}
```

注意：TNP 目前会打印一个非致命提示：

```text
ERROR: Failed to process output PDB. cannot convert dictionary update sequence element #1 to a sequence
```

但主 JSON 评分文件正常生成，L/L3/C/PSH/PPC/PNC flags 正常。这个错误来自 TNP 的 PDB 后处理/注释步骤，不影响当前用于筛选的主评分 JSON。

## 结构交叉验证：IgFold

入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/igfold-predict
```

用法：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/igfold-predict input.fasta -o out_igfold.pdb --models 1
'
```

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_igfold/vhh_smoke_igfold.pdb
```

说明：

- IgFold 启动时会打印 JHU Academic Software License 的非商业使用提示；商业使用前需要确认授权。
- 当前 wrapper 对 PyTorch 2.6 的 checkpoint `weights_only` 行为做了兼容处理。

## 结构交叉验证：NanoNet

入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/nanonet-predict
```

环境：

```bash
/data/qlyu/software/envs/nanonet
/data/qlyu/software/NanoNet
```

用法：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/nanonet-predict input.fasta -o /path/to/nanonet_out
'
```

输出：

```bash
/path/to/nanonet_out/<seq_id>_nanonet_backbone_cb.pdb
```

已验证 smoke：

```bash
/data/qlyu/software/vhh_eval_tools/tests/final_nanonet/vhh_smoke_nanonet_backbone_cb.pdb
```

说明：

- NanoNet 默认输出 backbone + C-beta PDB，适合与 NanoBodyBuilder2/IgFold 做快速结构交叉验证。
- 侧链重建需要 Modeller 或 SCWRL4 许可证，未自动安装。
- 已对 `NanoNet.py` 做了新版 BioPython 兼容补丁：替代已移除的 `Bio.PDB.Polypeptide.one_to_three`。

## Paratope 预测/约束：Paragraph

入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/Paragraph
```

官方 example smoke：

```bash
ssh.exe node1 '
cd /data/qlyu/software/Paragraph
CUDA_VISIBLE_DEVICES=0 /data/qlyu/software/vhh_eval_tools/bin/Paragraph --example
'
```

已验证输出：

```bash
/data/qlyu/software/Paragraph/Paragraph/example/example_predictions.csv
```

正式使用建议：

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

说明：Paragraph 输入 PDB 应该是 IMGT-numbered；对只有 VHH/heavy chain 的结构，使用 `--heavy` 权重。

## ABlooper 边界

入口：

```bash
/data/qlyu/software/envs/vhh-eval/bin/ABlooper
```

已验证：`ABlooper --help` 可用。

重要边界：

- ABlooper 期望输入是 IMGT numbered antibody PDB。
- 实测 VHH-only PDB 不适合直接作为 smoke 输入，容易因为缺 light chain 或编号格式不完整失败。
- 当前把它记录为“已安装但仅在有严格 IMGT 编号 H+L Fv 或后续专门转换流程时使用”。

## 已有复合物建模工具入口

这些在前序部署中已完成，本轮不重复安装。

### NanoBodyBuilder2 / ImmuneBuilder

```bash
ssh.exe node1 '
BIN=/data/qlyu/anaconda3/envs/boltz/bin
SEQ="QVQL...TVSS"
CUDA_VISIBLE_DEVICES=0 PATH="$BIN:$PATH" NanoBodyBuilder2 -H "$SEQ" -o /path/to/vhh.pdb --n_threads 4 -v
'
```

### Boltz-2

```bash
ssh.exe node1 '/data/qlyu/anaconda3/envs/boltz/bin/boltz --help | head'
```

### Chai-1

```bash
ssh.exe node1 '/data/qlyu/software/envs/chai1/bin/chai-lab --help | head'
```

### HADDOCK3

```bash
ssh.exe node1 '/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 --help | head'
```

详细部署与 smoke evidence 见：

```bash
NANOBODY_TOOLS_NODE1_DEPLOYMENT.md
```



## Paragraph / TNP / ProtParam 便捷入口补充

本轮新增两个便捷 wrapper，并复核 TNP/Paragraph：

```bash
/data/qlyu/software/vhh_eval_tools/bin/paragraph-vhh
/data/qlyu/software/vhh_eval_tools/bin/protparam-vhh
```

详细记录见：

```bash
PARAGRAPH_TNP_PROTPARAM_NODE1_DEPLOYMENT.md
```

- `paragraph-vhh`：为 VHH/heavy-chain PDB 自动生成 Paragraph key CSV，并使用 `--heavy` 权重输出 paratope probability。
- `protparam-vhh`：批量计算 MW、theoretical pI、GRAVY、instability index、aliphatic index、extinction coefficient、charge 等基础物化性质。

## 四层筛选流水线：vhh-screen

已新增统一筛选入口：

```bash
/data/qlyu/software/vhh_eval_tools/bin/vhh-screen
```

详细规则、阈值、调用方式和 smoke evidence 见：

```bash
VHH_SCREENING_SYSTEM_NODE1.md
```

典型调用：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-screen candidates.fasta -o /data/qlyu/software/vhh_eval_tools/runs/my_screen --prefix my_batch --tnp-ncores 4
'
```

完整结构层调用：

```bash
ssh.exe node1 '
ROOT=/data/qlyu/software/vhh_eval_tools
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/vhh-screen candidates.fasta -o /data/qlyu/software/vhh_eval_tools/runs/my_screen_struct --prefix my_batch --structure-tools igfold,nanonet,nanobodybuilder2 --max-structures 20 --gpu 0
'
```

## 建议的 VHH 筛选调用顺序

1. 序列基础筛选：`vhh-eval` 生成 IMGT/Kabat、FR2 hallmark、ProtParam、liability、N-glyc motif。
2. VHH-ness：`abnativ score -nat VHH`，筛掉不像 VHH 分布的候选。
3. Human-likeness：`sapiens-score --chain H`，记录 self probability 和建议突变。
4. 可开发性主评分：`TNP`，优先看 L/L3/C/PSH/PPC/PNC flags。
5. 单体结构：NanoBodyBuilder2 为主，IgFold/NanoNet 交叉验证。
6. Paratope/约束：结构 IMGT 编号后用 `Paragraph --heavy` 做 paratope probability。
7. VHH-Ag pose：Chai-1/Boltz-2 先出候选，HADDOCK3 用实验/预测约束 refine。

## 一键健康检查模板

```bash
ssh.exe -o BatchMode=yes node1 '
set -e
ROOT=/data/qlyu/software/vhh_eval_tools
$ROOT/bin/vhh-eval $ROOT/tests/smoke_vhh.fasta -o /tmp/vhh_eval.tsv --json /tmp/vhh_eval.json
$ROOT/bin/sapiens-score $ROOT/tests/smoke_vhh.fasta -o /tmp/sapiens.csv --chain H
$ROOT/bin/abnativ score -nat VHH -mean -i $ROOT/tests/smoke_vhh.fasta -odir /tmp/abnativ_vhh -oid smoke -align -isVHH -ncpu 1
$ROOT/bin/nanonet-predict $ROOT/tests/smoke_vhh.fasta -o /tmp/nanonet_smoke
CUDA_VISIBLE_DEVICES=0 $ROOT/bin/igfold-predict $ROOT/tests/smoke_vhh.fasta -o /tmp/igfold_smoke.pdb --models 1
$ROOT/bin/TNP --seq "$(awk "BEGIN{ORS=\"\"} /^>/ {next} {print}" $ROOT/tests/smoke_vhh.fasta)" --name smoke --output /tmp/tnp_smoke --ncores 1
cd /data/qlyu/software/Paragraph && CUDA_VISIBLE_DEVICES=0 $ROOT/bin/Paragraph --example >/tmp/paragraph.log 2>&1
'
```

## 未自动部署/暂缓项

| 项 | 现状 | 替代方案 |
| --- | --- | --- |
| 真正 NetNGlyc | 未自动安装；常见 NetNGlyc 服务/包涉及外部服务或授权边界 | `vhh-eval` 已做 `N[^P][ST][^P]` motif scan，先用于批量预警 |
| A3D / Aggrescan3D | PyPI 包 setup 为 Python 2 风格；Conda `lcbio` 通道在 node1 上反复 connection reset | 后续网络稳定后可单独建 `a3d` conda env；当前先用 TNP + liability + structure flags |
| CamSol | 未找到可靠、可直接 pip/conda 的开放 CLI 安装路径 | 后续若拿到 standalone 或许可证包，再加入结构后可开发性评分 |
| AbNatiV VHH2/全模型 | `vhh2_model.ckpt` 约 1.09GB，node1 直连 Zenodo 极慢；仅部署了 VHH classic | 当前 `-nat VHH` 已可用；若以后需要 VHH2，可本机下载后上传 |
| ABlooper VHH-only smoke | 工具已装，但 VHH-only PDB 不满足输入假设 | 有严格 IMGT-numbered H+L Fv 后再用；VHH loop 暂以 NanoBodyBuilder2/IgFold/NanoNet 交叉验证为主 |

## 官方/上游来源索引

- ANARCI / ImmuneBuilder / NanoBodyBuilder2：`https://github.com/oxpig/ANARCI`，`https://github.com/oxpig/ImmuneBuilder`
- AbNumber：`https://github.com/prihoda/abnumber`
- Sapiens：`https://github.com/Merck/Sapiens`；本地缓存模型来自 HuggingFace `prihodad/biophi-sapiens1-vh`、`prihodad/biophi-sapiens1-vl`、`prihodad/biophi-sapiens1-tokenizer`
- NanoNet：`https://github.com/dina-lab3D/NanoNet`
- Paragraph：`https://github.com/oxpig/Paragraph`
- TNP：OPIG/Oxford Protein Informatics Group Therapeutic Nanobody Profiler，本地源码在 `/data/qlyu/software/TNP`

