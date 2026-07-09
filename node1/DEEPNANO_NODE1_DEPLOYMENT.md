# node1 DeepNano 部署与使用说明

更新时间：2026-07-06
本地说明位置：`/mnt/d/work/抗体/node1/DEEPNANO_NODE1_DEPLOYMENT.md`
远端节点：`node1`
远端用户：`qlyu`

## 当前结论

DeepNano 已可在 `node1` 上运行。检查时发现它已经部署在：

```text
/data/qlyu/software/DeepNano
```

因此本次没有重复上传 20G 模型目录，而是完成了以下工作：

1. 验证 `deepnano` conda 环境可用。
2. 验证 DeepNano 8M/35M/150M/650M checkpoint 文件存在。
3. 用 PVRIG 项目的 `HR-151` VHH 和 `8X6B` PVRIG chain B 结构序列做 smoke test。
4. 修复 prompt-based `model 2` 单条输入时的 batch 维度 bug。
5. 新增通用启动脚本：`/data/qlyu/software/DeepNano/run_deepnano_predict.sh`。

## 远端环境

```text
DeepNano root: /data/qlyu/software/DeepNano
Conda env: /data/qlyu/anaconda3/envs/deepnano
Python: 3.11.0
Torch: 2.6.0+cu124
Transformers: 4.48.1
CUDA visible to torch: yes, 8 GPUs
```

注意：官方文档原始建议是 Python 3.9 / torch 1.13.1 / transformers 4.27.4；远端现有环境版本更高，但本次 smoke test 已证明 8M model 1 和 model 2 都能完成推理。

## Checkpoint 状态

远端 checkpoint 目录：

```text
/data/qlyu/software/DeepNano/output/checkpoint
```

已看到的主要模型：

```text
DeepNano_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model
DeepNano_NAI_8M.model
DeepNano-site_8M.model
DeepNano-seq_PPI_8M.model
DeepNano-seq_NAI_35M.model
DeepNano-site_35M.model
DeepNano_NAI_35M.model
DeepNano-seq_NAI_150M.model
DeepNano-site_150M.model
DeepNano_NAI_150M.model
DeepNano_seq(esm2_t33_650M_UR50D)_SabdabData_finetune1_TF0_best.model
DeepNano-site_650M.model
DeepNano_NAI_650M.model
```

8M 适合快速 smoke test；650M 已有历史大批量输出，但更耗 GPU 显存和时间。

## 本次修复

文件：

```text
/data/qlyu/software/DeepNano/models/models.py
```

备份：

```text
/data/qlyu/software/DeepNano/models/models.py.backup_squeeze_fix_20260706_231818
```

修复内容：

```python
BSite2 = (BSite2.squeeze()>0.5)+0
```

改为：

```python
BSite2 = (BSite2.squeeze(-1)>0.5)+0
```

原因：`model 2` 在单条输入时原始 `squeeze()` 会删除 batch 维度，导致 prompt positional encoding 维度错误。修复后单条和批量输入都能正常推理。

## 通用运行脚本

脚本：

```text
/data/qlyu/software/DeepNano/run_deepnano_predict.sh
```

用法：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=5 MODEL=1 ESM2=8M ./run_deepnano_predict.sh input.fasta pairs.tsv output.csv'
```

参数：

```text
GPU    默认 5；用 CUDA_VISIBLE_DEVICES 指定物理 GPU
MODEL  默认 1；0=DeepNano-seq(PPI), 1=DeepNano-seq(NAI), 2=prompt-based DeepNano NAI
ESM2   默认 8M；可选 8M/35M/150M/650M
```

输入 FASTA 示例：

```fasta
>candidate_vhh_001
HVQLVESGGGSVQAGGSLRLSCVASASGFTYRPYCMAWFRQAPGKEREAVAGIDIFGGTTYADSVKGRFTASRDNAGFSLFLQMNDLKPEDTAMYYCAAGDSPDGRCPPLGQGLNYWGQGTQVTVSS
>pvrig_8x6b_chainB
TPEVWVQVRMESFTIRCGFLGSGSISLVTVSWGGPNGAGGTTLAVLHPERGIRQWAPARQARWETQSSISLILEGSPSANTTFCCKFASFPEGSWEACGSLPP
```

Pair TSV 示例，必须有表头：

```tsv
Nanobody-ID	Antigen-ID	Label
candidate_vhh_001	pvrig_8x6b_chainB	1
```

## Smoke test 结果

测试目录：

```text
/data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b
```

输入：

- VHH：本项目阳性参考 `HR-151`。
- Antigen：从本地 `8X6B.pdb` 提取的 PVRIG chain B 结构序列，103 aa。

已成功运行：

```bash
CUDA_VISIBLE_DEVICES=5 /data/qlyu/anaconda3/envs/deepnano/bin/python predict.py \
  --model 1 --esm2 8M \
  --fasta_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/input.fasta \
  --pair_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/pairs.tsv \
  --output_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/predictions_model1_8M.csv
```

输出：

```csv
Nanobody ID,Antigen ID,Prediction
hr151_vhh,pvrig_8x6b_chainB,0.102367945
```

已成功运行 prompt-based model 2：

```bash
CUDA_VISIBLE_DEVICES=5 /data/qlyu/anaconda3/envs/deepnano/bin/python predict.py \
  --model 2 --esm2 8M \
  --fasta_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/input.fasta \
  --pair_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/pairs.tsv \
  --output_path /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/predictions_model2_8M.csv
```

输出：

```csv
Nanobody ID,Antigen ID,Prediction
hr151_vhh,pvrig_8x6b_chainB,0.047819514
```

也验证了 wrapper：

```bash
cd /data/qlyu/software/DeepNano
GPU=5 MODEL=1 ESM2=8M ./run_deepnano_predict.sh \
  smoke_tests/pvrig_hr151_8x6b/input.fasta \
  smoke_tests/pvrig_hr151_8x6b/pairs.tsv \
  smoke_tests/pvrig_hr151_8x6b/predictions_wrapper_model1_8M.csv
```

输出一致：`0.102367945`。

## 后续用于纳米抗体设计的建议

DeepNano 适合作为 sequence-only / prompt-site 的第一层筛选器：

```text
候选 VHH 序列 + PVRIG ECD/结构域序列 -> binding-like score
```

它不直接回答：

```text
是否阻断 PVRIG-PVRL2
Kd/IC50 是多少
是否覆盖 R95/I97 等关键界面位点
```

所以后续排序建议组合：

1. DeepNano model 1/2 给出 VHH-PVRIG sequence score。
2. 用本项目已有 PVRIG-PVRL2 interface/hotspot 表做机制约束。
3. 再接结构预测/对接/界面打分工具筛掉非阻断型 binder。

## 常用远程命令

检查 GPU：

```bash
ssh.exe node1 'nvidia-smi'
```

跑 8M sequence-only：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=5 MODEL=1 ESM2=8M ./run_deepnano_predict.sh smoke_tests/pvrig_hr151_8x6b/input.fasta smoke_tests/pvrig_hr151_8x6b/pairs.tsv smoke_tests/pvrig_hr151_8x6b/new_predictions.csv'
```

跑 8M prompt-based：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=5 MODEL=2 ESM2=8M ./run_deepnano_predict.sh smoke_tests/pvrig_hr151_8x6b/input.fasta smoke_tests/pvrig_hr151_8x6b/pairs.tsv smoke_tests/pvrig_hr151_8x6b/new_predictions_model2.csv'
```

查看测试结果：

```bash
ssh.exe node1 'cat /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/predictions_model1_8M.csv && cat /data/qlyu/software/DeepNano/smoke_tests/pvrig_hr151_8x6b/predictions_model2_8M.csv'
```

## 2026-07-07 最强 650M 模型验证

本次目标：补齐并运行 DeepNano 当前最高档配置，用于后续纳米抗体测试。

结论：650M 最强配置已经可用，无需重新下载。远端已有以下组件：

```text
ESM2 650M encoder:
/data/qlyu/workdata/esm2_t33_650M_UR50D
/data/qlyu/software/DeepNano/models/esm2_t33_650M_UR50D -> /data/qlyu/workdata/esm2_t33_650M_UR50D

DeepNano 650M checkpoints:
/data/qlyu/software/DeepNano/output/checkpoint/DeepNano-seq_PPI_650M.model
/data/qlyu/software/DeepNano/output/checkpoint/DeepNano_seq(esm2_t33_650M_UR50D)_SabdabData_finetune1_TF0_best.model
/data/qlyu/software/DeepNano/output/checkpoint/DeepNano-site_650M.model
/data/qlyu/software/DeepNano/output/checkpoint/DeepNano_NAI_650M.model
```

`run_deepnano_predict.sh` 已升级：会自动识别 `ESM2=650M` 并使用本地 650M encoder，也支持手动传入 `ESM2_PATH=/path/to/encoder`。

已成功运行 650M sequence-only model 1：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=5 MODEL=1 ESM2=650M ./run_deepnano_predict.sh smoke_tests/pvrig_hr151_8x6b/input.fasta smoke_tests/pvrig_hr151_8x6b/pairs.tsv smoke_tests/pvrig_hr151_8x6b/predictions_model1_650M.csv'
```

输出：

```csv
Nanobody ID,Antigen ID,Prediction
hr151_vhh,pvrig_8x6b_chainB,0.00631164
```

已成功运行最强 prompt-based model 2 / 650M：

```bash
ssh.exe node1 'cd /data/qlyu/software/DeepNano && GPU=1 MODEL=2 ESM2=650M ./run_deepnano_predict.sh smoke_tests/pvrig_hr151_8x6b/input.fasta smoke_tests/pvrig_hr151_8x6b/pairs.tsv smoke_tests/pvrig_hr151_8x6b/predictions_model2_650M.csv'
```

输出：

```csv
Nanobody ID,Antigen ID,Prediction
hr151_vhh,pvrig_8x6b_chainB,0.0023118358
```

后续批量测试建议优先用：

```bash
MODEL=2 ESM2=650M
```

如果只是快速预筛或调试输入格式，先用：

```bash
MODEL=1 ESM2=8M
```
