# 运行状态

更新时间：2026-07-12

## 总体状态

`RUNNING_RF2_10RECYCLE_BLIND_RECOVERY`

## 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| RFantibody 1,000 条交付核验 | complete | 1,000 exact-unique；A/B/C/D 各 250 |
| canonical QC 输入 | complete | 1,000 个稳定 candidate_id；FASTA/TSV 一一对应 |
| FR4 末端修复 | complete | 官方 h-NbBCII10 PDB 少 1 个末端 Ser；1,000/1,000 显式映射为完整 `WGQGTLVTVSS` |
| 1,000 条 sequence QC | full evidence complete | 1,000/1,000 fast hard-pass；300/300 full 无 hard-fail；冗余全局 MUSCLE diversity 尾段主动停止 |
| 200-backbone 原始 pose 审计 | preliminary complete | 8X6B 单基线；52 个 backbone 通过三项 occlusion |
| pose-primary 定向 full QC | complete | 78/78 无 hard-fail；39 个 backbone；共同 scaffold 警报为 `not_vhh_like;hydrophobic_run` |
| RF2 pose-recovery | running | 78 条，GPU 1/2/3/4/6/7 各 13 条；10 recycles、`hotspot_show_prop=0`、seed 42 |
| NanoBodyBuilder2/HADDOCK3 | queued | RF2 通过者中按 backbone 多样性选择 Top 50；4 shard、可恢复 |
| 8X6B/9E6Y consensus | pending | 只有双基线 A/A 可进入最高计算优先级 |

## 关键限制

- 不对 1,000 条全量运行结构预测或 docking。
- 不把 sequence-only、RF2 confidence 或 HADDOCK score 单独升级为 blocker 阳性。
- 原始生成目录只读，所有增强结果写入本目录和对应远端新目录。
- RFantibody pose PDB 保持原始末端长度；补回的 Ser 仅用于 QC、合成序列和 de novo 单体建模。
- HADDOCK 使用完整界面 hotspot 的 CDR 引导约束，因此是 confirmatory pose generator；最终必须单独报告该确认偏差。

## 当前计数

```text
raw sequence-pose records:       1600
final exact-unique sequences:    1000
audited RFdiffusion backbones:    200
pose-pass backbones:               52
pose-pass backbones in final1000:  39
RF2 primary candidates:            78
RF2 sequence-QC hard failures:       0
RF2 running shards:                  6
```

另一个远端任务 `/data/qlyu/projects/pvrig_teacher_v1_20260712/pilot96` 是独立的 96 条 teacher-pilot；与本批 78 条仅有 14 条 key 重叠，不作为本流程完成证据。

## 路径

```text
local:  /mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712
remote: /data/qlyu/projects/pvrig_rfantibody_validation_20260712
source: /data/qlyu/projects/pvrig_rfantibody_1000_20260712
```
