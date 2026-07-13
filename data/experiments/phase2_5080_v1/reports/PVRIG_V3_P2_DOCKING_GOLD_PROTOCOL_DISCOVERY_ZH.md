# PVRIG V3-P2 Docking Gold 协议发现记录

## 状态

```text
PROTOCOL_DISCOVERY_COMPLETE
DG_A_PILOT64_V1_0_REJECTED_BEFORE_FULL_RUN
DG_A_PILOT64_V1_1_REQUIRES_REVISED_SMOKE
```

本记录保存正式 Pilot64 全量运行之前的 smoke 证据。它用于解释为什么初始
`5/10/5` HADDOCK 模块失败容忍度被全局修订，不是 Docking Gold 的最终验证报告。

## 冻结输入闭环

- Pilot64：64 条，包含 11 条已知阳性、21 条 matched controls、32 条 Teacher500 分层候选。
- 重复 seed：16 条候选，两个 receptor 均重复，共规划 32 个 replicate runs。
- frozen monomer：64/64 唯一解析，PDB 序列与清单完全一致；同一个字节级单体复用于两个 receptor。
- receptor：8X6B PVRIG chain B；9E6Y PVRIG chain A 仅改 chain ID 为 B，保留原始残基编号和 81--85 缺口。
- docking hotspots：8X6B 和 9E6Y 各 23 个 core/secondary residues。
- HADDOCK3：`2025.11.0`。
- 随机流：8X6B main/replicate 为 `917/10917`，9E6Y main/replicate 为 `20917/30917`；实际 rigidbody 范围分别为 `918--957`、`10918--10957`、`20918--20957`、`30918--30957`。

初始 V1.0 package：

```text
run_manifest SHA256 = f5c459627d005bc2eda954c54466fb0d7f1317cd1764361b34f71e60556f5f10
controller SHA256   = 82bddc7af769cce0091295b74167e53fa453360437effab396005f5ed12a28b6
```

## 先修正的跨构象编号错误

旧 DG-B 后处理把 8X6B 编号的 pose 对齐到 9E6Y 后，直接用 9E6Y hotspot
残基号与未重编号的 pose 比较。两个结构的 PVRIG 编号不相同，因此跨构象
`hotspot_overlap_count` 会系统性错误。

新 DG-A 后处理执行：

```text
generation receptor native numbering
-> coordinate alignment to scoring receptor
-> PVRIG residue IDs remapped through PVRIG_numbering_reconciliation.csv
-> hotspot/occlusion/classification
-> canonical contact pairs mapped to UniProt positions
```

HR-151 的同一个旧 8X6B-generated rank-1 pose 回归检查为：

| 方法 | 9E6Y hotspot overlap | 9E6Y class |
| --- | ---: | --- |
| 旧流程，未重映射 | 10 | `BLOCKER_PLAUSIBLE_B` |
| 修正流程，显式重映射 | 15 | `BLOCKER_LIKE_A` |

因此旧 9E6Y hotspot 数和由它派生的 A/B/C 标签不能直接充当新 DG-A 金标签。

## V1.0 八运行 smoke

Smoke 选择：

```text
P2PILOT_001 = known positive HR-151
P2PILOT_033 = Teacher500 stratified candidate
2 candidates x 2 receptors x 2 seed roles = 8 runs
```

结果：

```text
7/8 PASS_DOCKING_OUTPUT_COMPLETE
1/8 FAIL_DOCKING_OUTPUT_INCOMPLETE
```

7 个通过运行均为：

```text
rigidbody = 40
flexref = 10
emref = 10
final selected = 10
clusters >= 4
```

失败运行：

```text
run_id = P2PILOT_001__8X6B__replicate
rigidbody = 40
seletop = 10
flexref = 8
HADDOCK exit = 1
```

失败原因不是少于 DG-A 要求的 8 个有效 pose，而是 HADDOCK 的
`flexref.tolerance=10` 表示最多允许 10% 模块输出缺失；实际缺失为 20%，
因此工作流在已有 8 个 flexref 输出时提前终止。

## 独立双构象后处理 smoke

四个 main runs（2 candidates x 2 receptors）完成了四路参考评分和 canonical
contact extraction：

```text
4/4 postprocess complete
40/40 selected poses have dual-baseline geometry
40/40 selected poses have canonical PVRIG--VHH contact records
contact extraction failures = 0
```

示例连续结果：

| candidate | R_8X6B | R_9E6Y | R_gold |
| --- | ---: | ---: | ---: |
| P2PILOT_001 / HR-151 | 2.6094 | 3.0515 | 2.8305 |
| P2PILOT_033 | 3.2618 | 3.4251 | 3.3435 |

这些数值只证明新评分/编号/contact 管线可执行，不是实验 binding 或 blocking 证据。

## 模块 failure tolerance 的含义

HADDOCK `tolerance` 是“允许缺失的模块输出百分比”，不是：

- ambiguous restraint distance；
- hotspot 阈值；
- PVRL2 遮挡阈值；
- blocker 几何分类阈值。

源码在 `faulty > tolerance` 时才中止。对 `seletop=10` 且 DG-A 最终至少 8
个 pose 的协议，20% 是不提前杀死任何 DG-A-capable run 的最小精确上限。

同一失败序列、同一 receptor、同一 monomer、同一 seed 的非正式全局探针：

```text
rigidbody.tolerance = 5
flexref.tolerance = 20
emref.tolerance = 20

rigidbody = 40
flexref = 8
emref = 8
final selected = 8
clusters = 5
exit = 0
```

`tolerance=100` 不是合法 HADDOCK3 参数；合法范围为 `0--99`。也不采用 99，
因为它只会让最终不足 8 个 pose 的不合格运行继续消耗计算，不会增加任何
DG-A-capable run。

## V1.1 冻结决定

在查看全量 Pilot64 结果之前，全局修订所有 160 个 run：

```text
protocol_id = DG_A_PILOT64_V1_1
rigidbody.tolerance = 5
flexref.tolerance = 20
emref.tolerance = 20
per_candidate_failure_tolerance_override = false
scientific_geometry_thresholds_changed = false
```

显式硬门独立于 HADDOCK exit code：

```text
topoaa outputs = 2
rigidbody outputs >= 38/40
seletop outputs = 10
flexref outputs >= 8/10
emref outputs >= 8
final selected poses >= 8
final pose clusters >= 2
dual-baseline geometry rows = 100% final poses
canonical contact rows = 100% final poses
same monomer SHA across receptors/seeds
fixed receptor/restraint/config/seed/software hash closure
```

若任何硬门失败：

- 标记 `FAIL_DG_A`；
- 不从 rigidbody/flexref 回填 pose；
- 不把计算失败行伪装成 G5；
- 不针对候选单独增加 tolerance；
- 基础设施重跑必须保持完全相同的输入、config、seed 和软件版本，并保留 attempt 记录。

## 下一步

1. 在新 package 和新 Node1 root 中统一重建、重哈希 160 个 V1.1 configs。
2. 完整重跑上述 8-run smoke，而不是只补跑 V1.0 的失败 run。
3. 只有 revised smoke 达到 8/8 docking、8/8 postprocess 和零 contact failure，才启动全量 Pilot64。
4. 全量结束后计算 64/64 DG-A completeness、16 条 `R_gold` repeat Spearman 和 stable-tier quadratic weighted kappa。
5. 通过才冻结 Docking Gold；失败则保留失败结论并再次修订协议，禁止开始 P2 训练。

