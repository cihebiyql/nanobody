# 运行状态

更新时间：2026-07-12

## 总体状态

`COMPLETE_DIAGNOSTIC_NO_STRICT_RF2_RECOVERY`

正式结构高置信通道的结论是 **no-go for current batch**：RF2 严格姿势恢复为 `0/78`。为了区分“RF2 无法恢复”与“约束下也无法形成 blocker-like 几何”，已额外完成 30 条诊断性 NanoBodyBuilder2 + HADDOCK3 和 8X6B/9E6Y 双基线后处理。

## 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| RFantibody 1,000 条交付核验 | complete | 1,000 exact-unique；A/B/C/D 各 250 |
| canonical QC 输入 | complete | 1,000 个稳定 candidate_id；FASTA/TSV 一一对应 |
| FR4 末端修复 | complete | 1,000/1,000 显式补回合成序列末端 Ser；原始 pose PDB 不变 |
| 1,000 条 sequence QC | evidence complete | 1,000/1,000 fast hard-pass；300/300 full 无 hard-fail |
| 200-backbone 原始 pose 审计 | preliminary complete | 8X6B 单基线；52 个 backbone 通过三项 occlusion |
| pose-primary 定向 full QC | complete | 78/78 无 hard-fail；39 个 backbone；均为 `REVIEW_DEVELOPABILITY` |
| RF2 blind pose-recovery | complete, strict fail | 78/78 输出完整；0 个 strict recovered；68 low-interaction-confidence + 10 pose-not-recovered |
| 诊断 fallback 选择 | complete | 30 条、30 个不同 backbone；A/B/C/D = 10/4/7/9 |
| NanoBodyBuilder2 | complete | 30/30 原始 PDB、序列完全匹配和主链几何 QC 通过 |
| HADDOCK3 guided docking | complete | 30/30 成功；260 个 selected models；30/30 `rc=0` |
| 8X6B/9E6Y consensus | complete | 30/30 后处理完成；5 个候选各有 1 个 A/A 模型；无候选有 >=2 个 A/A |
| 最终计算标签 | complete | 30/30 `FINAL_DIAGNOSTIC_ONLY_RF2_NOT_RECOVERED`；`FINAL_POSITIVE_HIGH=0` |

## 关键数据

```text
raw sequence-pose records:               1600
final exact-unique sequences:            1000
audited RFdiffusion backbones:            200
pose-pass backbones:                       52
pose-pass backbones in final1000:          39
RF2 primary candidates:                    78
strict RF2 pose-recovered:                  0
diagnostic docking candidates:             30
NanoBodyBuilder2 exact/sane:             30/30
HADDOCK3 candidate success:              30/30
HADDOCK3 selected models:                  260
dual-baseline A/A models:                    5
candidates with >=2 A/A models:              0
final positive high:                         0
```

## 结果口径

- RF2 的 `0/78` 是“严格姿势未恢复”，不是实验不结合证明。
- HADDOCK 使用每个 CDR 残基到 8X6B 完整 23 位界面集合的歧义约束，属于 confirmatory guided docking。
- `500/100` 遮挡阈值的单位是 VHH-PVRL2 近接残基对计数，不是埋藏面积 `A^2`。
- 9E6Y 只在后处理时作为第二 PVRIG-PVRL2 叠合基线；本轮未独立对 9E6Y PVRIG 构象重新 docking。
- 所有标签均为计算优先级，不是 binder、Kd、competition 或 cell-blockade 证据。

## 主要输出

```text
RF2 metrics:
  rf2/results/rf2_metrics.tsv
  rf2/results/rf2_parse_summary.json

diagnostic docking input:
  rf2/results/rf2_diagnostic_docking_top.tsv
  rf2/results/rf2_diagnostic_docking_summary.json

docking evidence:
  docking/remote_selected/
  docking/postprocessed/
  manifests/docking_postprocess_audit.json

final results:
  reports/final/final_blocker_screen.tsv
  reports/final/final_blocker_summary.json
  reports/PVRIG_RFANTIBODY_VALIDATION_FINAL_ZH.md
```

## 路径

```text
local:  /mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712
remote: /data/qlyu/projects/pvrig_rfantibody_validation_20260712
source: /data/qlyu/projects/pvrig_rfantibody_1000_20260712
```
