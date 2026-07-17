# V4-D DEV1 OPEN-only native overlay RMSD 根因诊断 V1

## 结论

已确认的大幅离群（`>5 Å`）不是序列层面的“受体真实变形”，也不是 Kabsch 或 JSON 序列化假象。根因是：

```text
8X6B 归一化 PVRIG 链 T 在 51→57 有缺失残基断点
→ T41–T51 成为一个独立的 11-aa 坐标片段
→ HADDOCK flexref 将该片段与其余受体分离数十到数百 Å
→ score_pose 对所有共同 T-chain CA 做 Kabsch
→ 完整但相对位置已断裂的小片段导致 5–162.8 Å 的 native overlay RMSD
```

因此，这些大幅失败应被解释为 **pose-level technical invalidity**，不能直接归因于 VHH 候选序列。

## 已冻结的全 99 条证据

权威明细仍是：

```text
experiments/phase2_5080_v1/audits/
phase2_v4_d_dev1_open_overlay_rmsd_diagnostic_v2.json
SHA256 ef31a254de83dec7aa0f073154c8a7176eaa43c406df0aec8c9fd65df448aead
```

| 指标 | 结果 |
|---|---:|
| OPEN native overlay metric | 14,490 |
| `>1 Å` | 99（0.6832%） |
| 受影响 job | 98 |
| 受影响 candidate | 83 |
| 8X6B / 9E6Y | 89 / 10 |
| `>5 Å` / `1–5 Å` | 83 / 16 |
| 范围 | 1.020382–162.77925 Å |
| 剩余 model pair 仍 `>=4` 的受影响 job | 98 / 98 |

冻结的 selected-pose index 分布为：

```text
1:9, 2:4, 3:2, 4:2, 5:2,
6:5, 7:3, 8:7, 9:17, 10:48
```

注意：这是 `job_result.json` 中的 selected-pose index，**不能改称为 helper-sort rank**。截止本版冻结，99 条的独立 helper-sort rank/HADDOCK/AIR 重放未完成，因此本报告不对全 99 条做权重或 utility 声明。

## 直接因果证据

最大 OPEN-only 离群 pose：

```text
candidate: RFV1__PLDNANO_VHH_00698__A_CENTER__H1H3__B05__M02
job:       ..._8x6b_s917_9feb595f6f7e
model:     cluster_7_model_1.pdb.gz
RMSD:      162.77925 Å
T-CA:      103/103，103 个唯一残基位置
HADDOCK:   +137.60741
AIR:       1364.29
```

阶段追踪：

| 阶段 | T-CA | x 范围（Å） | 51→57 距离（Å） |
|---|---:|---:|---:|
| rigidbody_36 | 103 | 18.751 至 50.835 | 5.622 |
| flexref_6 | 103 | -484.728 至 65.569 | 535.055 |
| emref_6 / final | 103 | -484.651 至 65.426 | 535.086 |

断裂在 `flexref` 首次出现，并保留到最终 pose。该 PDB 并未截断，CA 数量、唯一残基号和 common positions 均完整。

8X6B 参考链有两个内部断点：`51→57` 和 `120→125`；9E6Y 只有 `120→126`，没有会产生 11-aa N 端独立片段的 `51→57` 断点。这与 8X6B 出现 89 条、高达 162.8 Å，而 9E6Y 仅有 10 条 1.02–1.34 Å 轻度越界的非对称结果一致。

## 证据边界

* 本次根因 metric 读取只使用 v2 已冻结的 OPEN-only 精确 pose 路径。
* test32 raw run directory addressed = 0。
* test32 pose file opened = 0。
* test32 metric value read = 0。
* 初始协议源定位时曾枚举顶层 `results` 文件名，但没有打开非 OPEN metric payload；因此这里只作上述 raw/pose/metric 的精确零访问声明，不作“零文件名枚举”的过度声明。

## 治理结论

本诊断没有：

* 修改 `1.0 Å` 阈值；
* 从旧版 teacher 中事后删除 pose；
* 生成 teacher 或训练模型；
* 改写 V1/V1.1 失败状态；
* 解封 test32。

它只支持一个新版本设计事实：大幅 8X6B 失败是 pose-level 技术无效性事件。任何“保留其他 pose、排除该无效 model pair”的处理，都必须在新版本中事先注册，不能回溯修改 V1/V1.1。
