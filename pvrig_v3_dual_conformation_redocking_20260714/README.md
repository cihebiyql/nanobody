# PVRIG V3 双构象独立重对接评价器

本目录固定一套面向 PVRIG-PVRL2 界面遮挡几何的可恢复计算流程。它不是对旧 8X6B pose 做第二参考系打分，而是对每个实体分别在 `8X6B` 和 `9E6Y` 两个 PVRIG 实验构象上执行独立 HADDOCK3 对接，再把每个 pose 放入 native/cross 两个参考系评分。

当前冻结目标：

- 固定候选：128 条；
- 协议回归控制：47 条；
- 独立构象：`8x6b`、`9e6y`；
- 显式随机种子：`917`、`1931`、`3253`；
- 任务总数：`(128 + 47) x 2 x 3 = 1050`；
- 下一批 P2/P3/P4 生成：评价器稳定门禁通过前硬锁定。

## 为什么需要 V3

旧 V2 对接只在 8X6B 受体上生成 pose，再把坐标叠合到 9E6Y。审计发现两个会系统性扭曲结果的问题：

1. 叠合只改变坐标，不改变 8X6B 残基号；旧 9E6Y scorer 却按 9E6Y 原始残基号查热点，因此跨构象热点重合率不可直接解释为真实构象差异。
2. 旧遮挡 scorer 同时读取 `ATOM` 和 `HETATM`；9E6Y 的水、EDO 等小分子可能被误计入 PVRL2 遮挡或 clash。

V3 的修复是：

- 两个 PVRIG 结构都改成 UniProt Q6DKI7 编号和受体链 `T`；
- 两个 PVRL2 链都改为 `L`；
- 仅保留 20 种标准氨基酸的 `ATOM`；
- 8X6B、9E6Y 分别独立 HADDOCK3；
- 23 个唯一界面位点拆为 12 个 AIR anchor 和 11 个不参与对接的 holdout；
- native/cross 评分使用同一 UniProt 编号，不再依赖两套 PDB 原始残基号。

## 固定128候选

面板由旧 1024 条候选确定性选出，不按 `sequence_qc.tsv` 的 `candidate_id` 连接，因为该文件使用不同 ID 命名空间；QC 只能按序列 SHA256 一一连接。

| 选择桶 | 数量 | 用途 |
| --- | ---: | --- |
| `LOCKED_DUAL_REFERENCE_A` | 47 | 全部保留当前双参考 A 信号，供 V3 重新判断 |
| `RF2_FORMAL_PASS` | 4 | RF2 正式多 seed 通过 |
| `RF2_NEAR_PASS` | 28 | RF2 接近门槛的校准候选 |
| `SINGLE_BASELINE_RECHECK` | 25 | 旧流程仅单参考支持，需真正双构象复核 |
| `DIVERSE_PLAUSIBLE` | 24 | 补足结构族和 CDR3 多样性 |

硬性多样性上限固定在 `config/protocol_spec.json`：backbone group 4、near-CDR3 family 12、arm 8、scaffold 48；H3-L 不超过96且 H3-S 不少于32。

## 评价证据矩阵

每个候选/控制的每个 seed 都形成四个评分单元：

```text
dock_8x6b -> score_8x6b_native
dock_8x6b -> score_9e6y_cross
dock_9e6y -> score_9e6y_native
dock_9e6y -> score_8x6b_cross
```

每个 pose 输出：

- HADDOCK score 和 AIR energy/violation proxy；
- PVRIG-VHH 接触残基；
- 23 个 full、12 个 anchor、11 个 holdout 热点重合；
- VHH-PVRL2 总遮挡，以及 CDR1/CDR2/CDR3/framework 分区；
- CDR3 遮挡占比；
- 2.5 A clash 原子对和残基对；
- native/cross 参考系和对齐 RMSD。

旧 `BLOCKER_LIKE_A` 阈值只作为兼容性参考，必须由47条同协议控制重新评估；在稳定门禁通过前，不能把旧阈值称为已经重新校准。

## 目录

```text
config/                  协议参数和旧阈值兼容参考
inputs/source/           冻结的原始结构和热点表
inputs/normalized/       UniProt编号、T/L链、无HETATM参考结构
inputs/candidates_128.tsv
inputs/calibration_controls_47.tsv
manifests/               协议锁与1050任务清单
scripts/                 构建、对接、评分、汇总、门禁和状态脚本
tests/                   标准库 unittest 回归测试
reports/                 轻量汇总、漂移和稳定性报告
status/ logs/ data/      本地状态入口；远端原始运行数据不进入Git
```

## 执行顺序

```bash
cd /mnt/d/work/抗体/pvrig_v3_dual_conformation_redocking_20260714

# 1. 标准化两个参考结构，构建固定候选和控制面板
python3 scripts/prepare_references.py
python3 scripts/build_candidate_panel.py
python3 scripts/build_calibration_manifest.py

# 2. 先锁协议核心；任务ID必须绑定这个hash
python3 scripts/freeze_protocol.py core

# 3. 构建2构象x3 seed任务并做本地验证
python3 scripts/build_docking_jobs.py
python3 -m unittest discover -s tests -v
python3 scripts/validate_protocol.py

# 4. 完成最终协议锁，再部署node1
python3 scripts/freeze_protocol.py final
```

node1 的固定运行目录是：

```text
/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714/
```

控制器按节点 1-minute load 自适应并发：`>=62: 0`、`56-62: 1`、`48-56: 2`、`<48: 4`，每个 HADDOCK3 任务4核、`nice -n 15`。HADDOCK3 是 CPU 工作负载，空闲 GPU 不会直接加速它。

## 稳定性门禁

只有 `reports/EVALUATOR_STABLE.json` 同时满足下列条件，状态才允许为 `PASS`：

1. 47/47 控制均按完全相同的 V3 协议进入评价；
2. 每个实体在两个构象上均至少 2/3 seeds 成功；
3. 两个构象是独立 HADDOCK run，且每个 pose 的 native/cross 2x2 评分完整；
4. UniProt 编号、23=12+11 热点拆分和 HETATM 排除测试通过；
5. 阳性控制不能整体塌陷为 evidence-only；
6. 破坏性/alanine 控制若仍为 A，必须被报告为异常或评价器不稳定；
7. 已生成 control drift 和 threshold sensitivity 报告；
8. 报告中的协议核心 hash、最终协议锁 hash和任务清单 hash完全匹配。

任何下一批生成入口都必须先运行 `scripts/guard_next_generation.py`。门禁不是 `PASS`、hash 不匹配或报告缺失时，该脚本非零退出。

## 解释边界

本流程评价的是“对接 pose 是否具有 PVRIG-PVRL2 界面遮挡样几何”。HADDOCK 分数、界面遮挡、一般结合倾向、亲和力和真实功能阻断是不同证据轴；本目录不会把几何分数直接表述为 Kd 或实验阻断结论。

