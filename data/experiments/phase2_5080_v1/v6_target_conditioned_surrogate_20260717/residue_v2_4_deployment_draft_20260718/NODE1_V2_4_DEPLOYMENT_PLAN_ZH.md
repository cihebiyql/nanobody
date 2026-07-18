# Residue V2.4 Node1 四卡部署草案

## 路径

- Deployment bundle：`/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v1_20260718`
- Fresh runtime：`/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v1_20260718`
- 固定 Python：`/data1/qlyu/software/envs/pvrig-v6-tc/bin/python`
- 未来 V2.4 freeze：`residue_v2/IMPLEMENTATION_FREEZE_V2_4.json`

runtime 路径必须保持不存在，直到 V2.4 的代码、参数、数值稳定性修复、输入清单和 launcher 全部完成独立冻结与 dry-run。

## 四卡映射

| Lane | 物理 GPU |
|---|---:|
| A_DOMAIN | 1 |
| B_VHH3D | 2 |
| C_PATCH | 4 |
| D_FULL_PAIR | 5 |

- GPU 0、3 禁止占用；当前已有其他任务。
- GPU 6 仅预留给目标图增强或闭包重放，不能与正式四 lane 混用。
- GPU 7 保留。
- 每进程最多 8 CPU threads；四 lane 合计上限 32 threads。

## 数据闭包

V2.4 草案暂时复用已验证的 open 监督：

- V4-D：226 candidates，20 parent clusters；其中 225 条三 seed 完整，1 条 partial seed，不做 zero imputation。
- V4-H：1281 Stage-1 seed917 candidates，11 parent clusters。
- 合计：1507 candidates，31 parent clusters。
- marginal：186328 rows。
- pair：593346 rows；3014 candidate-receptor groups。
- label-free VHH graph：1507 entities、186328 nodes、2926274 edges。

`teacher_source` 只可用于 sampler、loss balance 和 audit，禁止进入模型特征。

## 启动门

当前脚本仅支持 `--plan` 与 `--preflight`，故意没有训练模式。正式启动前必须另行完成：

1. V2.4 数值/实现 amendment；
2. 新 implementation freeze 及独立 replay；
3. 新 launcher tests；
4. runtime fresh-root、磁盘、GPU 空闲和输入 SHA preflight；
5. 明确确认没有读取 sealed evaluation 或预测性能指标。

## 时间与磁盘预算

V2.3 同规格实测从 bootstrap 到 20 folds + 4 collectors 为约 64.6 分钟，runtime 约 407 MiB。当前 Node1 同时有 CPU Docking 任务，因此 V2.4 若保持 650M frozen backbone、1507 条、8 epochs，建议预算 75–100 分钟；若改变模型或 epoch，必须在新 freeze 中重新估算。

尽管实测产物小于 1 GiB，fresh runtime 仍保留 `/data1` 至少 200 GiB 的保守启动门。
