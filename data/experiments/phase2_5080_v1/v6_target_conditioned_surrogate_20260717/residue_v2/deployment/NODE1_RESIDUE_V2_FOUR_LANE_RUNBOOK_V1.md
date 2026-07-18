# Residue V2.3 Node1 四 Lane 部署运行手册 V1

## 1. 目标和边界

该部署只训练一个代理模型，用 VHH 序列、label-free VHH 单体图和固定 PVRIG
图去逼近独立 8X6B/9E6Y Docking 的连续几何。它不是结合、亲和力、实验竞争
或实验阻断真值。

部署器严格禁止读取或同步 V4-F/test32，也不从任何 Docking campaign 复制 pose。
所有静态文件 SHA 均来自正式的 `IMPLEMENTATION_FREEZE_V2.json`；部署脚本没有
散落的输入 SHA 常量。

## 2. 固定路径和资源

```text
不可预先存在的运行根：
/data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718

只读部署 bundle：
/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718

唯一 Python：
/data1/qlyu/software/envs/pvrig-v6-tc/bin/python

target ESM2 augmentation：physical GPU6
A_DOMAIN：physical GPU1
B_VHH3D：physical GPU2
C_PATCH：physical GPU4
D_FULL_PAIR：physical GPU5
physical GPU0、GPU3：本次运行始终禁止
physical GPU7：保留，不分配
每个 augmentation/trainer/collector 进程：OMP/MKL/OpenBLAS/NumExpr 均固定 8 threads
```

初次运行要求新运行根不存在且不是 symlink，`/data1` 对应文件系统可用空间至少
200 GiB。恢复运行仅接受由同一 freeze、同一静态输入 SHA 和同一命令 SHA 生成的
闭合 PASS terminal。

部署 bundle 必须保存 `RESIDUE_V2_PRODUCTION_MATRIX.json` 的完整
`implementation_allowlist`，包括代码、tests 和审计文档；不能只复制 trainer。
launcher 会按 freeze 中的 `implementation_files` 对这棵树逐文件复算 SHA。
bundle 还必须包含 trainer 的三个 `residue_v1/src` 传递依赖：
`residue_model.py`、`train_nested_residue_surrogate.py`、
`train_nested_residue_surrogate_v1_5.py`。launcher 会把 Python 实际导入的这三个
本地 sibling 文件与 freeze 中同名 V1 静态证据的 SHA 逐个对齐，不接受
仅验证归档路径、却执行未绑定拷贝的部署。`build_residue_graph_cache_v2.py` 和
`domain_balance_v2.py` 也必须处于 implementation freeze 闭包内。

正式训练额外绑定 V2.2 lane-specific contact amendment、calibration report 和
receipt。四 lane 权重分别为：A `0.01/0.005`、B `0.0025/0.00125`、
C `0.000625/0.0003125`、D `0.000625/0.0003125`（marginal/pair）。
formal trainer 必须显式传入 `--contact-loss-amendment`；smoke 不携带该参数，
且不得据 smoke 结果重新调权。

V2.2 在 C/D fold0 正式训练中因 BF16 饱和概率的 entropy 路径出现
`component_loss_nonfinite`，已终止且不得恢复。V2.3 只将 entropy 敏感
计算提升到 FP32，并增加命名有限值门和 non-finite gradient gate；数据、
loss 权重、优化器、学习率、epoch、seed、fold 和 promotion gate 全部不变。
`NUMERICAL_STABILITY_AMENDMENT_V2_3.json` 必须在 freeze 和 implementation tree
中以同一 SHA 绑定。

## 3. V2.3 数值 soak（正式运行前必须）

在新的 implementation freeze 完成后，使用独立、不可被正式运行复用的
soak root，分别执行 C_PATCH/fold0 和 D_FULL_PAIR/fold0，两者都使用
冻结的 `max_epochs=8` 和 V2.2 contact weights。soak 只允许读取：

```text
return code
component/total/gradient finite gates
RESULT/terminal 与输出哈希闭包
```

严禁读取或比较 soak 的 Spearman、RMSE、prediction 列或任何 promotion
指标；soak checkpoint、prediction 和 output 不得复制到正式 runtime。任一路
出现 non-finite 或输出闭包失败，V2.3 必须 fail-closed，不启动四路正式训练。

## 4. 正式顺序

```text
IMPLEMENTATION_FREEZE_V2.json 静态哈希闭包
  -> GPU6: base PVRIG graph + frozen ESM2-650M residue augmentation
  -> content-addressed augmented PT + native augmentation receipt
  -> status/DEPLOYMENT_INPUT_CLOSURE.json
  -> GPU1,2,4,5: full1507 / outer fold0 / max_epochs=1 / --smoke-mode
  -> 四个 smoke 全部 PASS
  -> 四 lane 并行；每 lane 内 fold0,1,2,3,4 严格顺序
  -> 全部 20 个独立 fold terminal PASS
  -> 四个 lane collector
  -> status/FOUR_LANE_TERMINAL.json
```

任何失败都会停止下游阶段；不得修改参数、loss、optimizer、fold 或阈值后继续
声称属于同一版本。

## 5. Node1 命令（本文件不执行）

部署 bundle 和正式 production freeze 均完成后，先 dry-run：

```bash
set -euo pipefail

BUNDLE=/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
LAUNCHER="$BUNDLE/residue_v2/deployment/node1_residue_v2_four_lane_v1.py"
FREEZE="$BUNDLE/residue_v2/IMPLEMENTATION_FREEZE_V2.json"

test ! -e /data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718
"$PY" "$LAUNCHER" \
  --implementation-freeze "$FREEZE" \
  --dry-run \
  > /data1/qlyu/pvrig_v6_residue_v2_node1_dry_run_v1.json
```

dry-run 通过后才可初次启动：

```bash
set -euo pipefail
BUNDLE=/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python

setsid "$PY" \
  "$BUNDLE/residue_v2/deployment/node1_residue_v2_four_lane_v1.py" \
  --implementation-freeze "$BUNDLE/residue_v2/IMPLEMENTATION_FREEZE_V2.json" \
  --run \
  > /data1/qlyu/pvrig_v6_residue_v2_node1_launcher_v1.log 2>&1 \
  < /dev/null &
echo $! > /data1/qlyu/pvrig_v6_residue_v2_node1_launcher_v1.pid
```

若进程或机器中断，只有在 bundle、freeze、输入和已有 terminal 均保持原字节时才可：

```bash
set -euo pipefail
BUNDLE=/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python

setsid "$PY" \
  "$BUNDLE/residue_v2/deployment/node1_residue_v2_four_lane_v1.py" \
  --implementation-freeze "$BUNDLE/residue_v2/IMPLEMENTATION_FREEZE_V2.json" \
  --resume \
  >> /data1/qlyu/pvrig_v6_residue_v2_node1_launcher_v1.log 2>&1 \
  < /dev/null &
echo $! > /data1/qlyu/pvrig_v6_residue_v2_node1_launcher_v1.pid
```

不允许删除失败 terminal 或输出目录后用不同参数重跑同一版本。

## 6. 核心证据

```text
status/BOOTSTRAP_RECEIPT.json
status/DEPLOYMENT_INPUT_CLOSURE.json
cache/pvrig_graphs/esm2_650m_v2/CURRENT.json
runtime/smoke/<lane>/TERMINAL.json
runtime/<lane>/production/fold_<0..4>/TERMINAL.json
runtime/<lane>/collector/formal/TERMINAL.json
status/FOUR_LANE_TERMINAL.json
```

生产完成状态必须精确为：

```text
PASS_ALL_FOUR_LANES_20_FOLDS_AND_COLLECTORS
```

collector 的 `PROMOTE_RESIDUE_V2_OVER_M2` 或 `DO_NOT_PROMOTE_RESIDUE_V2` 都是
合法计算终态；它们代表评估结论，而不是运行是否成功。
