# RFantibody PVRIG VHH 结构预测与 Docking 决策及实跑报告

更新日期：2026-07-12

## 1. 一句话结论

**这个流程要做，但必须做成分层漏斗，而不是把 1,000 条全部盲目 docking。对当前这批 RFantibody 候选，正式高置信通道应在 RF2 阶段判定 no-go；已完成的 30 条 NanoBodyBuilder2 + HADDOCK3 只是诊断性 fallback。**

实际结果：

- 78 条候选全部有 RF2 输出，但严格 blind pose-recovery 为 `0/78`。
- 30 条诊断候选的 NanoBodyBuilder2 和 HADDOCK3 均成功。
- 260 个 docking selected models 中，只有 5 个在 8X6B 和 9E6Y 两个 PVRIG-PVRL2 基线上同时达到 `BLOCKER_LIKE_A`。
- 这 5 个 A/A 模型分属 5 个候选；没有任一候选具有至少 2 个 A/A 模型。
- 因为 30 条都是 RF2 严格失败后的 fallback，最终标签全部被锁定为 `FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED`；`FINAL_POSITIVE_HIGH=0`。

因此，这个流程的最大价值不是“证明我们已经找到 blocker”，而是防止把 hotspot-guided 生成和 hotspot-guided docking 的自我一致性错当成独立证据。

## 2. 为什么这个课题仍然需要结构与 Docking

我们的目标不是任意 PVRIG binder，而是能够阻断 PVRIG-PVRL2/CD112 界面的 VHH。下列问题不能只靠序列模型回答：

1. VHH 是否从正确方向靠近 PVRIG。
2. 它覆盖的是否是 PVRL2 真实界面，而不是远端非功能表位。
3. CDR3 是否对配体界面产生足够遮挡，还是主要由 framework 擦边接触。
4. 结论是否对 8X6B 和 9E6Y 中观测到的两种 PVRIG-PVRL2 几何都稳健。

NanoBodyBuilder2 从序列独立重建 VHH 单体，可以减少直接重用 RFantibody 原始复合物姿势造成的循环论证。HADDOCK3 则用来生成并筛查实际的 VHH-PVRIG 相对方向。两者都有价值，但都不直接产生可靠 Kd，也不能代替竞争阻断实验。

## 3. 本轮实际漏斗

```text
1,000 条 RFantibody final exact-unique sequences
  -> 1,000 条 fast sequence QC
  -> 200 个 RFdiffusion backbone 的原始 design-pose 审计
  -> 52 个 backbone 通过三项 occlusion proxy
  -> final1000 中实际覆盖 39 个通过 backbone
  -> 每个 backbone 选 2 条，得到 78 条定向 full-QC + RF2 候选
  -> RF2 blind pose-recovery: 0/78 strict pass
  -> 选 30 个不同 backbone 作为 diagnostic fallback
  -> NanoBodyBuilder2: 30/30
  -> HADDOCK3 full-interface-guided docking: 30/30
  -> 8X6B/9E6Y 双基线遮挡几何分类
  -> 30/30 FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED
```

不对 1,000 条全量 docking 的原因：

- 1,000 条只覆盖 171 个 RFdiffusion backbones，同 backbone 上的多条 ProteinMPNN 序列高度相关。
- 全量 docking 会把相关序列当成独立证据，放大看似稳定的阳性数。
- RFantibody 已经给出 design pose，首先应该审计和独立恢复该姿势，而不是直接丢掉这一证据进行大规模重对接。
- 结构阶段的成本应集中在 backbone-diverse 短名单上。

## 4. 输入和序列处理

### 4.1 RFantibody 交付

- raw sequence-pose records：1,600。
- raw exact-unique sequences：1,494。
- final exact-unique sequences：1,000。
- hotspot set A/B/C/D：250/250/250/250。
- final1000 中不同 backbone：171。

### 4.2 FR4 末端 Ser

RFantibody 官方 `h-NbBCII10` PDB 模板末端是 `WGQGTLVTVS`，本地 VHH L1 gate 和拟合成序列要求完整 `WGQGTLVTVSS`。因此：

- QC、合成和 NanoBodyBuilder2 使用显式补回 1 个末端 Ser 的序列。
- RF2 仍使用原始 RFantibody pose PDB 及其原始序列，不修改已生成结构。
- 1,000/1,000 修复都有显式 candidate-level mapping，不是隐式替换。

### 4.3 序列 QC

- 1,000/1,000 fast hard-pass。
- 全局 full-QC 容量短名单 300/300 无 hard-fail；其余是 capacity-deferred，不是生物学阴性。
- 78 条 RF2 primary 的定向 full QC 为 78/78 无 hard-fail。
- 78 条均有 `REVIEW_DEVELOPABILITY`，共同提示是 `not_vhh_like;hydrophobic_run`。这主要是共享 scaffold 风险，不是个别 CDR 已证实不可开发。

### 4.4 ProteinMPNN 分数

从生成日志恢复了全部 1,600 条 ProteinMPNN NLL，final1000 的范围为 `0.8728535-1.521795`，数值越低表示序列与给定 backbone 越相容。该分数不是 affinity、Kd 或 blocker score。

## 5. 原始 Design-Pose 审计

对 200 个 RFdiffusion backbone 各取一个 MPNN pose，将 PVRIG 对齐到 8X6B 后计算三项遮挡代理：

- VHH-PVRL2 总遮挡残基对计数 `>=500`。
- CDR3-PVRL2 遮挡残基对计数 `>=100`。
- CDR3 遮挡残基对占比 `>=0.15`。

注意：`500/100` 是在重原子距离截断下得到的**近接残基对计数**，不是埋藏表面积 `A^2`。

结果：

- A/B/C/D 通过 backbone：16/9/13/14，总计 52/200。
- final1000 只覆盖其中 39 个 backbone，因此正式 RF2 primary 为 39 x 2 = 78 条。
- 200 个 pose 都未达到旧规则的 `hotspot_overlap >=14/23`。本轮生成只暴露了 3-4 个稀疏 hotspot，而旧分类器要求完整界面覆盖；两者口径不同，不能用此直接全批淘汰，也不能事后降阈值制造阳性。

## 6. RF2 Blind Pose-Recovery

### 6.1 参数和严格门槛

```text
candidates:             78
num_recycles:           10
hotspot_show_prop:       0
seed:                   42
strict interaction_pAE: <10
strict target-aligned antibody RMSD: <2 A
strict target-aligned CDR RMSD:      <2 A
```

`hotspot_show_prop=0` 用于检查模型在不显示设计 hotspot 时能否恢复接近原 RFantibody pose 的方向。

### 6.2 结果

| 指标 | min | median | max |
|---|---:|---:|---:|
| interaction pAE | 3.54 | 14.50 | 18.27 |
| predicted LDDT | 0.87 | 0.90 | 0.92 |
| target-aligned antibody RMSD, A | 1.93 | 11.24 | 42.74 |
| target-aligned CDR RMSD, A | 0.94 | 10.14 | 28.03 |
| framework-aligned antibody RMSD, A | 0.43 | 0.54 | 2.79 |
| framework-aligned CDR RMSD, A | 0.59 | 0.84 | 6.06 |

状态：

- `RF2_LOW_INTERACTION_CONFIDENCE`: 68。
- `RF2_POSE_NOT_RECOVERED`: 10。
- `RF2_POSE_RECOVERED`: 0。

这组数字的关键含义是：RF2 对 VHH 单体折叠普遍有较高置信，框架对齐后的 CDR 构象也大多接近；失败的主要是 VHH 相对 PVRIG 的整体结合方向。因此不能将 `0/78` 解释为“78 条都无法折叠”，也不能解释为实验不结合；它表示原设计姿势没有获得独立恢复。

最接近门槛的例子：

| candidate | iPAE | antibody RMSD | CDR RMSD | 结论 |
|---|---:|---:|---:|---|
| `PVRIG_RFAb_v0_D_bb012_mpn04` | 3.91 | 2.25 | 2.23 | 交互置信好，两个 RMSD 均略高于门槛 |
| `PVRIG_RFAb_v0_D_bb028_mpn04` | 5.06 | 2.27 | 1.53 | CDR 达标，整体 VHH RMSD 略高 |
| `PVRIG_RFAb_v0_D_bb028_mpn02` | 10.07 | 1.93 | 1.54 | 姿势达标，iPAE 超阈值 0.07 |
| `PVRIG_RFAb_v0_D_bb015_mpn01` | 10.67 | 2.14 | 0.94 | CDR 达标，其他两项接近但未达标 |

严格阈值未事后放宽。这一点对避免选择后偏差很重要。

## 7. NanoBodyBuilder2

### 7.1 目的

对 30 条诊断 fallback 从 FR4-restored 序列重建独立 VHH 单体，而不把 RFantibody 原始复合物中的 VHH 坐标直接送入 docking。

### 7.2 运行与质控

- 第一次调用因 `hmmscan` 不在 `PATH` 中而失败。
- 将 `/data/qlyu/anaconda3/envs/boltz/bin` 前置到 `PATH` 后重跑。
- 30/30 raw PDB 完成。
- 30/30 规范化为 chain A。
- 30/30 PDB 序列与预期序列 exact match，SHA256 一致。
- 30/30 主链几何 QC 通过；无相邻 CA 距离 `>6 A`。

这一阶段只证明得到了序列一致、几何可用的 VHH 单体输入，不证明与 PVRIG 结合。

## 8. HADDOCK3 诊断性 Docking

### 8.1 参数

```text
candidates:                  30
independent backbones:       30
shards:                       4
cores per candidate:          4
rigidbody sampling:           40
seletop:                      10
flexref:                     enabled
emref:                       enabled
clustfcc min_population:       1
seletopclusts top_models:      4 per retained cluster
```

远端 docking 从 2026-07-12 20:24:06 +08:00 开始，于 21:12:20 +08:00 完成。30/30 候选 `rc=0`，共保留 260 个 selected models。

### 8.2 约束策略与确认偏差

本轮对每个 CDR 残基施加到 8X6B PVRIG 完整 23 位界面集合的歧义距离约束。这个设置适合回答：

> 在明确要求 CDR 靠近 PVRIG-PVRL2 界面时，该 VHH 能否形成无明显几何破坏且具有遮挡的姿势？

它不适合独立回答：

> 该 VHH 在没有人为界面提示时是否自然选择这个结合位点？

所以本轮是 confirmatory guided docking，不是 blind docking。RF2 盲恢复失败时，HADDOCK 的优秀姿势不能“救回”为高置信阳性。

### 8.3 本轮双基线的真实含义

HADDOCK3 实际对接的是 8X6B 中的 PVRIG 构象。9E6Y 用于将已生成 pose 对齐到第二个 PVRIG-PVRL2 实验结构并重新计算遮挡。因此“8X6B/9E6Y 双基线”是双几何 overlay 检查，不是在两个受体构象上各自进行一次独立 docking。

## 9. Blocker 几何分类

### 9.1 单基线 A 级条件

VHH pose 在某一 PVRIG-PVRL2 基线上同时满足：

- hotspot overlap `>=14`。
- VHH-PVRL2 总遮挡残基对计数 `>=500`。
- CDR3-PVRL2 遮挡残基对计数 `>=100`。
- CDR3 遮挡占比 `>=0.15`。

才记为该基线上的 `BLOCKER_LIKE_A`。

### 9.2 双基线模型级结果

| 类别 | 8X6B | 9E6Y | 双基线 consensus |
|---|---:|---:|---:|
| `BLOCKER_LIKE_A` / A-A consensus | 138 | 5 | 5 |
| `BLOCKER_PLAUSIBLE_B` | 117 | 246 | 117 |
| `EVIDENCE_INFERENCE_ONLY_E` | 5 | 9 | 5 |
| single-baseline recheck | - | - | 133 |

总模型数为 260。从 8X6B 的 138 个 A 降到 9E6Y 的 5 个 A，说明本轮姿势对参考构象非常敏感，单看 8X6B 会大幅高估阻断几何稳健性。

### 9.3 候选级结果

- 5 个候选各有 1 个 A/A 模型。
- 25 个候选没有 A/A 模型。
- 没有候选具有 `>=2` 个 A/A 模型。
- 没有候选满足候选级 `FINAL_POSITIVE_HIGH` 规则。
- 30/30 最终都是 `FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED`。

有且仅有 1 个 A/A 模型的 5 个候选：

| candidate | A/A 模型排名 | RF2 iPAE | RF2 antibody RMSD | RF2 CDR RMSD | 解读 |
|---|---:|---:|---:|---:|---|
| `PVRIG_RFAb_v0_A_bb005_mpn01` | 3 | 3.54 | 7.53 | 6.79 | 有一个双基线 pose，但 RF2 整体方向不恢复 |
| `PVRIG_RFAb_v0_C_bb012_mpn05` | 1 | 3.95 | 17.64 | 12.91 | guided docking 几何强，RF2 姿势差很大 |
| `PVRIG_RFAb_v0_A_bb015_mpn01` | 2 | 15.43 | 6.18 | 5.56 | 一个 A/A，但 RF2 交互置信和姿势均不通过 |
| `PVRIG_RFAb_v0_B_bb015_mpn01` | 7 | 15.13 | 6.41 | 6.59 | A/A 出现在较后模型，RF2 不通过 |
| `PVRIG_RFAb_v0_B_bb016_mpn04` | 4 | 13.19 | 10.32 | 10.50 | A/A 稀疏，RF2 不通过 |

这五条不是“已预测 blocker”，而是“在强界面约束下出现过一个双基线 blocker-like pose 的 RF2-failed 候选”。

## 10. 这个流程应该怎样用

### 10.1 当前批次

| 用途 | 决策 | 原因 |
|---|---|---|
| 证明已获得 PVRIG binder/blocker | no-go | 无实验，且 RF2 strict pass = 0 |
| 把 HADDOCK 分数当作 Kd | no-go | docking energy/rank 不是经标定亲和力 |
| 对 1,000 条全量 NBB2 + docking | no-go | backbone 冗余、算力浪费、假独立证据 |
| 对 30 条诊断 fallback 做几何分层 | complete / useful | 可区分单基线敏感姿势，为重设计和小规模实验面板提供信息 |
| 将结果作为下一轮设计负证据 | go | 0/78 和 8X6B/9E6Y 差异能帮助修正姿势稳健性 |

如果比赛时间迫近，可以从两条正交证据轴选一个小型实验面板：

- 几何轴：覆盖上述 5 个各有 1 个 A/A 模型的候选。
- RF2 接近门槛轴：包含 `D_bb012_mpn04`、`D_bb028_mpn04` 和 `D_bb015_mpn01` 等接近盲恢复门槛的候选。
- 从 A/B/C/D 和不同 backbone 中保持多样性，不只按一个诱导性总分排序。

这种面板仍是高风险诊断面板，不是预测阳性面板。

### 10.2 下一轮正式流程

```text
sequence/developability QC
  -> RFantibody design-pose audit + backbone deduplication
  -> blind complex pose-recovery
  -> only strict-pass candidates enter formal docking lane
  -> VHH monomer ensemble, not one structure only
  -> restrained / partial-restraint / unrestrained ablation
  -> independent docking against both 8X6B and 9E6Y PVRIG conformers
  -> blocker geometry consensus
  -> BLI/SPR binding
  -> PVRIG-PVRL2 competition assay
  -> cell-based functional blockade
```

具体改进：

1. **两个受体构象独立 docking**：不只将 8X6B docking pose 叠合到 9E6Y，而是对 8X6B 和 9E6Y PVRIG 各自运行 docking。
2. **约束消融**：比较 full-interface restraint、仅用生成时 3-4 个 hotspot、局部 hotspot 以及无约束姿势。
3. **hold-out 界面评分**：用一部分 hotspot 生成 pose，用未暴露的其余界面残基评分，降低“按题画答案”。
4. **VHH 构象集成**：对少量 final candidates 使用多个单体模型/多 seed，检查 CDR3 构象敏感性。
5. **docking 重复**：对终选候选增大 rigidbody sampling，使用多 seed，并报告 cluster 稳定性、restraint violations、界面面积、静电和去溶剂化项。
6. **已知阳性和阴性只用于 calibration**：不将 HR-151 或已知 blocking VHH 混入普通训练正例，并执行 exact/near leakage 检查。

## 11. 不能从本轮结果得出的结论

本轮不能声称：

- 任一候选已被证明结合 PVRIG。
- 任一候选具有某个 Kd。
- 任一候选已被证明阻断 PVRIG-PVRL2。
- HADDOCK score 可以在不同序列间直接转换成亲和力。
- 9E6Y 后处理等价于在 9E6Y 受体构象上独立 docking。
- 不能把 `0/78` 改写为“78 条实验不结合”。

在完成 SPR/BLI、PVRIG-PVRL2 竞争结合和细胞功能实验前，最高只能使用 `diagnostic computational priority` 或 `computational blocker-geometry hypothesis` 这类表述。

## 12. 复现路径与输出

### 12.1 本地与远程目录

```text
local validation root:
  /mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712

remote validation root:
  /data/qlyu/projects/pvrig_rfantibody_validation_20260712

read-only RFantibody source delivery:
  /mnt/d/work/抗体/node1/rfantibody_pvrig_1000
  /data/qlyu/projects/pvrig_rfantibody_1000_20260712
```

### 12.2 关键输出

```text
inputs and provenance:
  inputs/pvrig_rfantibody_1000.canonical.fasta
  inputs/pvrig_rfantibody_1000.fr4_restored.fasta
  manifests/fr4_terminal_repair_mapping.tsv
  manifests/mpnn_scores/mpnn_scores_selected.tsv
  manifests/docking_reference_provenance.json

pose audit:
  pose_audit/backbone_pose_audit_8x6b_preliminary.tsv
  pose_audit/preliminary_pose_shortlist_summary.json

RF2:
  rf2/results/rf2_metrics.tsv
  rf2/results/rf2_parse_summary.json
  rf2/results/rf2_diagnostic_docking_top.tsv
  rf2/results/rf2_diagnostic_docking_summary.json

NBB2/HADDOCK:
  docking/remote_selected/
  docking/postprocessed/
  manifests/docking_postprocess_audit.json

final:
  reports/final/final_blocker_screen.tsv
  reports/final/final_blocker_summary.json
```

### 12.3 后处理命令

```bash
ROOT=/mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712

bash "$ROOT/scripts/sync_node1_results.sh"

python3 "$ROOT/scripts/postprocess_docking_batch.py" \
  --manifest "$ROOT/rf2/results/rf2_diagnostic_docking_top.tsv" \
  --sync-root "$ROOT/docking/remote_selected" \
  --work-root "$ROOT/docking/postprocessed" \
  --audit "$ROOT/manifests/docking_postprocess_audit.json" \
  --top-n 10 \
  --min-models 4 \
  --workers 4

python3 "$ROOT/scripts/aggregate_docking_consensus.py" \
  "$ROOT/rf2/results/rf2_diagnostic_docking_top.tsv" \
  "$ROOT/docking/postprocessed" \
  "$ROOT/reports/final"
```

## 13. 最终决策

### 对“是否要做这个流程”的回答

- **要做**：因为阻断任务必须有结构方向和 PVRL2 界面遮挡证据。
- **不全量做**：先按 backbone 去冗余，经序列 QC、design-pose 审计和 blind pose-recovery 后只对小批候选 docking。
- **不把 guided docking 当作阳性证明**：它是假设验证和弱排序工具。
- **当前批次正式 no-go，诊断性 complete**：最高只能作为重设计或小型实验面板的计算优先级。

本轮流程因此是有价值的：它没有产生一个可对外声称的 blocker，但它用可复核证据阻止了一个更危险的错误结论。
