# 运行状态

更新时间：2026-07-12

## 总体状态

`RUNNING_SEQUENCE_QC_AND_FREEZING_STRUCTURE_FUNNEL`

## 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| RFantibody 1,000 条交付核验 | complete | 1,000 exact-unique；A/B/C/D 各 250 |
| canonical QC 输入 | in progress | 去除 FASTA 描述字段，只保留稳定 candidate_id，防止 `|` 被 QC CLI 改写 |
| 1,000 条 sequence QC | pending launch | node1 后台、可恢复 cascade |
| 200-backbone 原始 pose 审计 | preliminary complete | 8X6B 单基线；需固化为正式 TSV/JSON |
| RF2 pose-recovery | pending | 10 recycles、`hotspot_show_prop=0`，预计 52-104 条 |
| NanoBodyBuilder2/HADDOCK3 | pending | 仅 RF2 通过的 Top 30-50 |
| 8X6B/9E6Y consensus | pending | 只有双基线 A/A 可进入最高计算优先级 |

## 关键限制

- 不对 1,000 条全量运行结构预测或 docking。
- 不把 sequence-only、RF2 confidence 或 HADDOCK score 单独升级为 blocker 阳性。
- 原始生成目录只读，所有增强结果写入本目录和对应远端新目录。

## 路径

```text
local:  /mnt/d/work/抗体/node1/rfantibody_pvrig_validation_20260712
remote: /data/qlyu/projects/pvrig_rfantibody_validation_20260712
source: /data/qlyu/projects/pvrig_rfantibody_1000_20260712
```

