# PVRIG Teacher Pilot96 运行状态

## 当前状态

- 更新时间：2026-07-12 22:35 Asia/Shanghai
- Node1 路径：`/data/qlyu/projects/pvrig_teacher_v1_20260712/pilot96`
- Node1 `docking.complete` 已生成，96/96 HADDOCK run 完成。
- 96/96 NanoBodyBuilder2、normalization、sequence validation、monomer geometry QC 和 receptor geometry QC 完成。
- 本地同步 96 个 run、96 个 traceback consensus、813 个 unique selected models。
- 813/813 poses 完成 8X6B classification、9E6Y rescoring、consensus 和 residue contact extraction。
- 96/96 candidate summaries 为 `COMPLETE`。
- V3-P1 single-parent pipeline smoke 已完成。

## 已修正的运行问题

1. 复用 runner 将 normalization 的期望残基数硬编码为 130，已改为当前序列长度 `${#seq}`。
2. 运行过程经历 controller 重启和配置状态变化，不能由最终 `.cfg` 反推每条 run 的实际核数。
3. 逐条解析 96 个 HADDOCK 日志后，实际最大 selected-core 分布为：14 条使用 4 cores，82 条使用 8 cores。
4. 当前 96 个 post-run `.cfg` 均显示 `ncores = 8`；该字段只记录最终文件状态，不是运行时证据。
5. 生产包源码默认值仍为 4 cores/shard，controller 启动和内部门控均为 `load1 <= 48`。
6. `6_seletopclusts` 可能合法输出 4-10 个唯一 pose，并可同时保留同一 model stem 的 `.pdb`/`.pdb.gz`；后处理按 model stem 去重，不伪造缺失 pose，也不重复计数。

## 本地已就绪的下游

- 96 条 exact CDR masks：96/96 `exact_annotation`。
- ESM2 residue cache：96 VHH + 1 PVRIG，97/97 tensor validation PASS。
- V3-G1 head-only smoke 已完成；有标签区分提升，但 target-dependence 仍弱，不是 formal PASS。
- V3-P1 smoke 已完成；ordinal 仅略胜常数基线，9E6Y total-occlusion lane 为负相关，不是 formal PASS。
- 五个 teacher 主产物复跑 SHA256 完全一致。
- selection/candidate/pose/contact/teacher manifest 的 96 个 candidate ID 完全一致。
- 与 11 条已知阳性的 exact-sequence 重叠为 0。
- Phase2 完整测试集 216/216 通过。

## pilot96 串行步骤

```text
[完成] Node1 96/96 HADDOCK
→ [完成] sync selected runtime evidence
→ [完成] 96/96 dual-baseline postprocess
→ [完成] aggregate candidate/pose/contact teacher files
→ [完成] V3-P1 single-framework pipeline smoke
→ [完成] final audit and report
```

正式下一阶段见：

`experiments/phase2_5080_v1/reports/PVRIG_DOCKING_TEACHER_DECISION_AND_FORMAL_NEXT_STEPS_ZH.md`

## 声明边界

- Docking teacher 是 geometry surrogate，不是 binding/blocking 实验真值。
- 96 条全部来自 `h-NbBCII10`，只能用于 pipeline smoke。
- 正式 V3-P 还需要多 parent 的 400-600 条首批 teacher，以及后续 300-500 条主动学习数据。
