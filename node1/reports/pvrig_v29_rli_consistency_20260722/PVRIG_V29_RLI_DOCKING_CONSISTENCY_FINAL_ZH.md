# PVRIG V2.9：本人 Node1 docking 与 rli HPC docking 一致性复核

日期：2026-07-22  
结论口径：计算 docking/阻断几何复现性，不等同于实验结合、Kd、IC50 或阻断活性。

## 一句话结论

**两批结果的输入、约束和协议完全相同；粗粒度“是否具有 blocker-like 几何支持”较一致，但具体 pose、精确几何等级和连续分数只达到中等复现，不能视为逐 pose 或逐分数一致。**

因此，rli 结果可作为同协议外部计算 shard 接入，但必须保留运行来源；重复作业不能简单平均或覆盖，最终阳性筛选仍应使用双构象、多 seed、多 pose 共识。

## 1. 当前进展盘点

### 本人 10,000 序列路线

- 冻结候选：10,000 条。
- 可执行 docking 作业：24,826 个；包含 8X6B/9E6Y 双构象和 seed 917/1931/3253 的分层分配。
- 2026-07-22 10:58 CST 对逐 job receipt 实时重数：SUCCESS 10,240、FAILED 2、FAILED_MAX_ATTEMPTS 2；无 receipt/待执行 14,582。
- 当前没有发现仍存活的 controller/watcher/worker；因此全量 10,000 路线尚未完成，当前也没有自动继续推进。

### rli external2000 路线

- 候选：1,907 条。
- 作业：3,814 个，即每条候选 × 8X6B/9E6Y，全部 seed 917。
- SUCCESS 3,811；FAILED 3；完整双构象候选 1,904。
- 3 个失败均为技术失败，应标记 `TECHNICAL_NA`，不是生物学阴性。

## 2. 是否真正同一方法

是。对 rli 的全部 3,814 个 manifest 作业逐项核对，本人与 rli 以下字段均为 **100% 完全一致**：

- `job_hash`
- `sequence_sha256`
- `cfg_hash`
- `restraint_hash`
- `protocol_core_sha256`
- `protocol_hash`

共同协议核心哈希：

`49fffc2c7087b1ff3a8e42463319168fad409687f502b619f3661c978fc6d666`

所以差异不是序列、受体、AIR 约束、seed 或评分协议不同造成的；它反映同协议在不同执行环境/节点上的随机采样、并行顺序、聚类与浮点差异。现有 receipt 未冻结 HADDOCK3/Python 的精确 binary/package 版本，因此“协议相同”不等于“运行环境 bitwise 相同”。

## 3. 严格独立重复样本

rli 的 3,814 个作业中，本人一侧状态为：

| 本人状态 | rli 状态 | 作业数 | 解释 |
|---|---|---:|---|
| SUCCESS | SUCCESS | 465 | 可用于独立重复一致性分析 |
| FAILED | SUCCESS | 1 | 技术执行差异 |
| ABSENT | SUCCESS | 3,345 | 本人侧尚未运行完成，不能评价重复性 |
| ABSENT | FAILED | 3 | rli 技术失败，本人侧无独立结果 |

465 个双成功作业覆盖 444 个候选，其中只有 21 个候选在两边都具备完整的 8X6B+9E6Y 双构象独立重复。

## 4. 一致性结果

### 4.1 作业级 blocker-like 判断

| 指标 | 一致性 |
|---|---:|
| `representative_pair_label` 完全一致 | 65.2% |
| native geometry class 完全一致 | 64.3% |
| cross geometry class 完全一致 | 68.0% |
| blocker-like support 二分类一致（`OTHER` vs 非 `OTHER`） | **91.6%** |
| 等级相差不超过一级 | **96.8%** |

解释：两边大多能一致判断“有没有 blocker-like 几何支持”，但在 `SUPPORTED_AB` 与 `STRICT_A` 之间经常换档，因此不能把一次运行的精确等级视为稳定真值。

### 4.2 连续分数与多 pose 共识

| 指标 | Pearson r | Spearman rho | MAE |
|---|---:|---:|---:|
| HADDOCK score | 0.555 | 0.541 | 9.61 |
| AIR energy | 0.518 | 0.496 | 56.44 |
| strict-A fraction | **0.780** | **0.757** | 0.148 |
| pair consensus fraction | 0.471 | 0.458 | 0.129 |

连续 HADDOCK 分数只有中等相关；多 pose 的 strict-A fraction 明显比单个代表 pose 更稳定，支持后续以共识而非单 pose 排名。

### 4.3 Top-k 排名重合

| 排名依据 | Top 5% | Top 10% | Top 20% |
|---|---:|---:|---:|
| HADDOCK score | 29.2% | 29.8% | 52.7% |
| strict-A fraction | 37.5% | 40.4% | 53.8% |
| pair consensus fraction | 41.7% | 36.2% | 43.0% |

这说明单次运行不足以稳定决定非常窄的 Top 5%/10%；Top 20% 相对稳定一些，但仍不应作为唯一淘汰依据。

### 4.4 三维 pose 直接复核

对 465 个作业的 `cluster_1_model_1`，先以 PVRIG chain T 做 Kabsch 对齐，再计算 VHH chain A 的 Cα RMSD：

- 465/465 成功完成结构比较，无解析失败。
- VHH RMSD：中位数 **14.81 Å**，均值 13.86 Å，P90 24.99 Å。
- RMSD ≤2 Å：13.3%；≤5 Å：28.4%；≤10 Å：39.4%。
- VHH 质心位移中位数：6.64 Å。
- 8X6B 的 VHH RMSD 中位数 12.33 Å；9E6Y 为 16.91 Å。

结论：代表 pose 在三维位置/方向上并不高度复现；粗粒度 blocker-like 几何可以一致，但不能认为两边得到了相同复合物构象。

### 4.5 双构象候选级结果

在仅有的 21 个完整双构象独立重复候选中：

- 双构象最弱侧等级完全一致：52.4%。
- 双构象是否仍有 blocker-like support：85.7%。

样本偏小，只能作为校准信号，不能据此冻结全流程阈值。

## 5. 最终判断与接入规则

1. **方法一致：通过。** manifest 与协议哈希均完全一致。
2. **粗粒度 blocker-like 支持：基本一致。** 二分类一致率 91.6%。
3. **精确等级、单 pose、连续分数、窄 Top-k：不够一致。** 不适合直接当作稳定真值。
4. rli 的 3,811 个成功作业可以补充本人尚未完成的同协议作业，但应采用确定的 canonical precedence，并保留 `compute_host`、adapter、完成时间和 archive hash。
5. 对 465 个重复作业，保留两份结果作为 reproducibility replicate；不要静默覆盖，不要把连续分数简单平均。
6. 最终候选升级建议至少要求：双构象支持 + 多 seed 支持 + 多 pose 共识；单 seed 的 `STRICT_A` 不能单独判阳性。
7. 下一轮应冻结 HADDOCK3/依赖版本、CPU 线程数和容器哈希，并用约 100–200 个分层候选做跨节点重复，目标是提高 Top 10% 重合和双构象等级一致率。

## 6. 机器可读产物

Node1：

`/data1/qlyu/projects/pvrig_v29_rli_consistency_audit_20260722/`

- `reports/CONSISTENCY_SUMMARY.json`
- `reports/REPRESENTATIVE_STRUCTURE_SUMMARY.json`
- `reports/job_level_comparison.tsv`
- `reports/model_set_comparison.tsv`
- `reports/pose_level_common_model_comparison.tsv`
- `reports/representative_structure_comparison.tsv`
- `reports/dual_conformation_21_comparison.tsv`
- `manifests/independent_success_overlap465.tsv`

本地副本：

`/mnt/d/work/抗体/node1/reports/pvrig_v29_rli_consistency_20260722/`

注：465-job 子集聚合器的 evaluator 总门状态为 FAIL，是因为该子集不包含全量 control/multi-seed 完整性，不表示这 465 个成功 docking 文件损坏。
