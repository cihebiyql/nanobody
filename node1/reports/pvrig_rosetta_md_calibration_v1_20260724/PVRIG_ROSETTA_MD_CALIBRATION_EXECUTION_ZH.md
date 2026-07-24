# PVRIG Rosetta 与短程动力学校准执行报告

更新时间：2026-07-24 19:18 CST

## 最终结论

本轮 Rosetta 和短程 MD 均已完成，但都没有达到进入主筛选或硬门控的校准要求：

- Rosetta InterfaceAnalyzer：`ROSETTA_DESCRIPTIVE_ONLY`。
- 四家族短程 MD：`MD_DESCRIPTIVE_ONLY`。
- 两者可以用于结构解释、异常排查和次级特征研究。
- 两者目前都不能替代 docking blocker geometry，也不能证明实验结合或阻断。

## 1. Rosetta 校准

- 总任务：150/150 完成，失败 0。
- 已知阳性：66 jobs、11 个实体。
- CDR3 破坏性 Ala 对照：84 jobs、14 个实体。
- 匹配 job pairs：84。
- 预注册标准：
  - 实体 AUROC 不低于 0.70；
  - 阳性召回不低于 0.80；
  - 破坏性对照 FPR 不高于 0.30；
  - 配对实体及家族方向一致率不低于 0.70。
- 接受指标：0。
- 判定：`ROSETTA_DESCRIPTIVE_ONLY`。

## 2. MD Pilot

体系：

- HR-151 positive；
- PVRIG-20 positive；
- PVRIG-20 F99A destructive。

条件：

- CHARMM36m February 2026 GROMACS port；
- TIP3P；
- 0.15 M NaCl；
- 100 ps NVT + 100 ps NPT + 2 ns production；
- seeds：917、1931、3253。

结果：

- 拓扑和最小化：3/3 完成。
- 轨迹：9/9 完成，失败 0。
- 分析窗口：1.0–2.0 ns。
- P20 的三个界面指标均达到 2/3 seed 同方向：
  - 最小界面距离；
  - 0.45 nm 接触数；
  - 界面氢键数。
- Pilot gate：`PASS`。
- 阶段判定：`ELIGIBLE_TO_EXPAND_P30_P38_P39`。

## 3. 四家族扩展

新增配对：

- P30 positive vs W100A；
- P38 positive vs F100A；
- P39 positive vs F99A。

执行规模：

- 6 个体系；
- 3 seeds/体系；
- 18 条轨迹；
- 18/18 完成；
- 失败 0；
- 无无效 COMPLETE；
- 无 LINCS WARNING、Fatal error、segmentation fault、NaN 或 core dumped。

并发：

- GPU 0、1、2、4、5、6、7 共 7 个独立队列；
- 每 GPU 同时最多一条轨迹；
- GPU3 因已有其他任务而避让；
- 18 条 production 从约 18:23 至 19:02 完成；
- 自动分析于 19:05 完成。

## 4. 四家族方向校准

每个家族要求三个界面指标中至少两个达到 2/3 seed 同方向：

| 家族 | 最小距离 | 接触数 | 氢键数 | 界面通过数 |
|---|---:|---:|---:|---:|
| P20_F99A | 通过 | 通过 | 通过 | 3 |
| P30_W100A | 不通过 | 通过 | 不通过 | 1 |
| P38_F100A | 不通过 | 不通过 | 通过 | 1 |
| P39_F99A | 不通过 | 通过 | 通过 | 2 |

跨家族指标：

| 指标 | 通过家族 | 家族方向比例 | 是否可作次级指标 |
|---|---:|---:|---|
| receptor-fitted VHH RMSD | 2/4 | 0.50 | 否 |
| complex RMSD | 3/4 | 0.75 | 是 |
| minimum interface distance | 1/4 | 0.25 | 否 |
| 0.45 nm contacts | 3/4 | 0.75 | 是 |
| interface H-bonds | 3/4 | 0.75 | 是 |

虽然 complex RMSD、contacts 和 H-bonds 各达到 3/4 家族，但 P30 和 P38 均只有一个界面指标通过，因此：

- `four_family_gate = FAIL`
- `decision = MD_DESCRIPTIVE_ONLY`

## 5. 分析复核与修正

并行审计发现首版 VHH RMSD 的 GROMACS group 输入顺序写成 `3 -> 2`：

- group 2：PVRIG backbone；
- group 3：VHH backbone。

首版实际是“拟合 VHH、测量 PVRIG”，与 `receptor-fitted VHH RMSD` 名称相反。现已：

1. 改成 `2 -> 3`，即拟合 PVRIG、测量 VHH；
2. 显式核验 `interface.ndx` 五个 group 的名称与顺序；
3. 强制分析窗口只包含 1.0–2.0 ns；
4. 检查 positive/destructive seed 集合完全一致；
5. 对全部 27 条轨迹重新分析。

修正影响：

- HR-151 median receptor-fitted VHH RMSD：
  - 首版：0.4479985396 nm；
  - 修正版：0.3418732723 nm。
- 四家族 gate 与最终判定未改变。
- 首版表格已归档到：
  `remote_snapshot/reports/pre_fix_vhh_rmsd_group_swap_20260724/`

## 6. 流程加固

已部署到 Node1：

- manifest 重复 `(system_id, md_seed)` 拒绝；
- manifest GPU ID 合法性检查；
- controller PID 原子写入和退出清理；
- COMPLETE/FAILED marker 原子写入；
- COMPLETE 必须同时满足：
  - `prod.tpr/xtc/cpt/gro/log` 非空；
  - production 最后 step 不低于 1,000,000；
  - `Finished mdrun on rank 0`；
- 无效 COMPLETE 直接进入监控 ALERT；
- expansion chain 任一阶段失败时生成结构化失败收据；
- 已完成 18 条结果的无覆盖回归测试：
  - controller 重新执行；
  - 18/18 被严格验证后跳过；
  - COMPLETE marker 时间哈希不变；
  - 回归结果 `PASS`。

## 7. 为什么 P30/P38 不应直接加长现有轨迹

当前证据更支持“控制不够匹配”，而不只是模拟时间不足：

- P30/P38 的 positive 与 destructive 来自不同代表 pose；
- P38 F100A 在部分 Rosetta 指标上并没有比 positive 更差；
- 2 ns 中 seed 间 contacts/H-bonds 方向翻转；
- 因此直接把当前轨迹延长到更长时间，可能只会放大初始 pose 差异。

下一轮应先建立严格 matched-pose 控制：

1. 从同一个 positive representative pose 原位构建 Ala mutant；
2. 对 positive 和 mutant 使用相同最小化与 restrained relaxation；
3. 每个 pair 使用 6 个配对 seeds；
4. production 延长到 10 ns；
5. 增加 mutation-site contact occupancy；
6. 使用 paired effect-size / bootstrap CI；
7. 标准改为“效应量置信区间排除 0，并且至少 4/6 seeds 同方向”。

若仍不能区分，应将 P30_W100A/P38_F100A 降级为非热点或不适合作为 MD direction calibrator，而不是通过调低阈值强行放行。

## 8. 证据路径

远端根目录：

`/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724`

关键文件：

- `status/MD_EXPANSION_LIVE_STATUS.json`
- `status/MD_EXPANSION_PRODUCTION_STATUS.json`
- `status/MD_EXPANSION_ANALYSIS_STATUS.json`
- `reports/MD_STAGE_A_CALIBRATION_RECEIPT.json`
- `reports/MD_EXPANSION_CALIBRATION_RECEIPT.json`
- `reports/md_expansion_seed_metrics.tsv`
- `reports/md_expansion_pair_directions.tsv`
- `reports/md_combined_four_family_metric_summary.tsv`

本地完整快照：

`/mnt/d/work/抗体/node1/reports/pvrig_rosetta_md_calibration_v1_20260724/remote_snapshot`

## 证据边界

短程 MD 只能回答：

- 初始 pose 是否快速散开；
- 接触、氢键和相对构象是否稳定；
- 定向破坏突变是否能产生可重复的配对方向。

它不能直接证明：

- 实验亲和力；
- 实验阻断；
- BLI response；
- Kd；
- IC50。
