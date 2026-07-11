# node1 抗体设计工具速查

更新时间：2026-07-07 14:28 +08:00
本地目录：`/mnt/d/work/抗体/node1`
远端：`node1`，用户：`qlyu`
软件根目录：`/data/qlyu/software`

## 1. 稳定 SSH 连接

后续从 WSL/Codex 访问 node1，默认使用 Windows OpenSSH：

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 '<remote command>'
```

交互登录或快速检查：

```bash
ssh.exe node1 'hostname && whoami && date -Is'
ssh.exe node1 'nvidia-smi'
ssh.exe node1
```

已验证当前稳定连接返回：`host=node1 user=qlyu`。

连接机制来自 `NODE1_SSH.md`：`node1` 和 `qlyu-node1` 都走 `C:\Users\ciheb\.ssh\qlyu-node1-proxy.cmd`，脚本会动态读取 Windows WLAN 上的 `10.101.x.x` 地址，避免校园网 IP 改变后手动改 `BindAddress`。

## 2. 当前只使用已安装可用工具

本文件只记录已经部署并有 smoke evidence 的工具。当前仍在安装或后台同步的新工具不纳入使用建议，也不需要干预。

| 工具 | 主要用途 | 远端入口 | 已验证证据 |
| --- | --- | --- | --- |
| DeepNano | VHH-抗原 sequence-only / prompt-site 第一层结合筛选 | `/data/qlyu/software/DeepNano/run_deepnano_predict.sh` | 8M 和 650M model 1/2 均跑通过 PVRIG smoke test |
| vhh-competition-qc | 比赛提交前官方合规、CDR novelty、可开发性、结构 summary、Top N portfolio 总门控 | `/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc` | 1/3/4 条序列 smoke、NanoBodyBuilder2 结构 smoke、docking summary import smoke 已跑通；非秒级，1 条约 96-116s |
| vhh-large-scale-screen | 大库去重、分层 QC、断点续跑、geometry shortlist、docking consensus 最终标签 | `/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen` | 50 条真实 scaffold 50->10->5 cascade 169.82s；resume 1.15s |
| NanoBodyBuilder2 / ImmuneBuilder | 单条 VHH/nanobody 结构预测 | `/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2` | `--help` 可用，smoke PDB 已生成 |
| Boltz-2 | VHH-抗原复合物候选生成 | `/data/qlyu/anaconda3/envs/boltz/bin/boltz` | `--help` 可用，GPU smoke PDB/confidence 已生成 |
| Chai-1 | VHH-抗原 co-folding / complex pose | `/data/qlyu/software/envs/chai1/bin/chai-lab` | `--help` 可用，smoke CIF/score 已生成 |
| HADDOCK3 | 有表位/互作约束时的信息驱动 docking/refinement | `/data/qlyu/anaconda3/envs/haddock3/bin/haddock3` | `--help` 可用，nanobody-antigen example `--setup` 已完成 |
| RFantibody | RFdiffusion backbone + ProteinMPNN sequence + RF2 filtering | `/data/qlyu/software/RFantibody/bin/{rfdiffusion,proteinmpnn,rf2}` | 三个 wrapper `--help` 可用，RFdiffusion/MPNN/RF2 smoke 输出已生成 |

## 3. 推荐组合流程

### 快速序列筛选

用于大量候选 VHH 和目标抗原序列的低成本预筛：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=5 MODEL=1 ESM2=8M ./run_deepnano_predict.sh input.fasta pairs.tsv output.csv'
```

- 输入 `input.fasta` 里放候选 VHH 和抗原序列。
- `pairs.tsv` 必须有表头：`Nanobody-ID<TAB>Antigen-ID<TAB>Label`。
- 快速调格式用 `MODEL=1 ESM2=8M`。
- 批量正式筛选优先用 `MODEL=2 ESM2=650M`，但要选择空闲 GPU。

### 大规模最终阳性筛选

大库不要直接全量运行 TNP、team diversity 和 docking。使用：

```bash
ssh.exe node1 '/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen \
  /path/to/candidates.fasta -o /data/qlyu/software/vhh_eval_tools/runs/my_cascade \
  --fast-chunk-size 500 --chunk-jobs 2 \
  --full-qc-limit 1000 --full-chunk-size 100 --full-chunk-jobs 1 \
  --geometry-pool-size 100 --geometry-limit 50 --geometry-cluster-limit 3 \
  --workers 16 --tnp-ncores 4'
```

详细策略、输出和最终 blocker 标签见 `VHH_LARGE_SCALE_SCREENING_RUNBOOK.md`。

### 单体结构生成

用于把 VHH 序列转为结构，再进入 docking/co-folding/界面分析：

```bash
ssh.exe node1 'BIN=/data/qlyu/anaconda3/envs/boltz/bin; SEQ="QVQL...TVSS"; CUDA_VISIBLE_DEVICES=0 PATH="$BIN:$PATH" NanoBodyBuilder2 -H "$SEQ" -o /data/qlyu/software/tests/immunebuilder/my_vhh.pdb --n_threads 4 -v'
```

### 复合物候选生成

- Boltz-2：适合生成 VHH-抗原复合物候选；不要把 affinity 输出直接解释成 VHH-Ag 的 KD。
- Chai-1：适合 VHH-抗原 co-folding；正式预测时可考虑启用 MSA/templates，并提高采样。
- HADDOCK3：适合已有 epitope/paratope、竞争、突变、HDX 等约束时做 docking/refinement；不是盲 co-folding 模型。

### 生成式抗体设计

RFantibody 当前可用三段：

```bash
ssh.exe node1 'cd /data/qlyu/software/RFantibody && CUDA_VISIBLE_DEVICES=0 bin/rfdiffusion --help'
ssh.exe node1 'cd /data/qlyu/software/RFantibody && CUDA_VISIBLE_DEVICES=0 bin/proteinmpnn --help'
ssh.exe node1 'cd /data/qlyu/software/RFantibody && CUDA_VISIBLE_DEVICES=0 bin/rf2 --help'
```

正式设计时应比 smoke test 使用更大的 `--diffuser-t`、更多 `--num-designs`、更多 RF2 recycle。RFdiffusion 的 `diffuser.T` 不能低于 15。

## 4. GPU 和后台任务约定

运行前先看 GPU：

```bash
ssh.exe node1 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits'
```

本次验证时，GPU 0/1/6 基本空闲，GPU 2/3/4/5/7 有不同程度占用。实际运行前以实时 `nvidia-smi` 为准。

长任务不要裸跑在 SSH 前台，优先用 `tmux` 或把日志写到 `/data/qlyu/software/tests/...` / 项目专用输出目录。

## 5. 轻量健康检查

```bash
ssh.exe -o BatchMode=yes node1 'set -e
/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2 --help | head -n 5
/data/qlyu/anaconda3/envs/boltz/bin/boltz --help | head -n 8
/data/qlyu/software/envs/chai1/bin/chai-lab --help | head -n 12
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 --help | head -n 12
cd /data/qlyu/software/RFantibody
bin/rfdiffusion --help | head -n 8
bin/proteinmpnn --help | head -n 8
bin/rf2 --help | head -n 8
'
```

## 6. 原始文档索引

- `NODE1_SSH.md`：稳定 SSH、动态 ProxyCommand、排障。
- `DEEPNANO_NODE1_DEPLOYMENT.md`：DeepNano 环境、checkpoint、650M 验证、wrapper 用法。
- `NANOBODY_TOOLS_NODE1_DEPLOYMENT.md`：NanoBodyBuilder2、Boltz-2、Chai-1、HADDOCK3 部署和 smoke tests。
- `RFANTIBODY_NODE1_DEPLOYMENT.md`：RFantibody 环境复用、权重、wrapper、smoke tests。
- `VHH_EVALUATION_TOOLS_NODE1_DEPLOYMENT.md`：VHH 编号、VHH-ness、human-likeness、可开发性、结构交叉验证和 paratope 工具总表。
- `VHH_SCREENING_SYSTEM_NODE1.md`：四层 VHH 筛选体系、`vhh-screen` 调用、阈值和 smoke evidence。
- `VHH_COMPETITION_QC_PIPELINE_UPGRADE_PLAN.md`：面向 PVRIG 比赛提交的官方合规、CDR 新颖性、可开发性、结构、docking/blocking 和 Top 50 portfolio 升级方案。
- `VHH_COMPETITION_QC_PIPELINE_RUNBOOK.md`：已经部署的比赛版 `vhh-competition-qc` 入口、调用方式、输出字段和 smoke evidence。
- `VHH_LARGE_SCALE_SCREENING_RUNBOOK.md`：大规模分层漏斗、断点续跑、性能基准、geometry shortlist 和最终 consensus 标签。
- `PARAGRAPH_TNP_PROTPARAM_NODE1_DEPLOYMENT.md`：Paragraph、TNP、ProtParam/Compute pI-Mw 的部署复核、便捷 wrapper 和 smoke tests。
