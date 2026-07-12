# PVRIG Teacher Pilot96 运行状态

## 当前状态

- 更新时间：2026-07-12 19:35 Asia/Shanghai
- Node1 路径：`/data/qlyu/projects/pvrig_teacher_v1_20260712/pilot96`
- 96/96 NanoBodyBuilder2 raw monomer 已生成。
- 96/96 normalization、sequence validation、monomer geometry QC 和 receptor geometry QC 已通过。
- 首批 8 条 HADDOCK run 已完成，后续 shard 正在可恢复运行。
- 首批 4 条已完成本地 8X6B/9E6Y 后处理，39/39 实际 selected poses 全部完成双参考分类和 contact extraction。

## 已修正的运行问题

1. 复用 runner 将 normalization 的期望残基数硬编码为 130，已改为当前序列长度 `${#seq}`。
2. 初始 HADDOCK 配置每 shard 使用 8 cores，四 shard 在共享节点上产生过高瞬时负载。
3. 后续 92 条已改为每 shard 4 cores，并重新计算每条候选的 asset SHA256。前 4 条保留实际运行时的 8-core 配置。
4. 生产包的新默认值为 4 cores/shard，且 controller 启动和内部门控均为 `load1 <= 48`。
5. `6_seletopclusts` 可能合法输出 4-10 个唯一 pose，并可同时保留同一 model stem 的 `.pdb`/`.pdb.gz`；后处理按 model stem 去重，不伪造缺失 pose，也不重复计数。

## 本地已就绪的下游

- 96 条 exact CDR masks：96/96 `exact_annotation`。
- ESM2 residue cache：96 VHH + 1 PVRIG，97/97 tensor validation PASS。
- V3-G1 head-only smoke 已完成；有标签区分提升，但 target-dependence 仍弱，不是 formal PASS。
- pilot96 sync、dual-baseline postprocess、teacher aggregation 和 V3-P1 smoke 脚本已完成单测与有界前向/反向验证。

## 剩余串行步骤

```text
Node1 96/96 HADDOCK complete
→ sync selected runtime evidence
→ 96/96 dual-baseline postprocess
→ aggregate candidate/pose/contact teacher files
→ V3-P1 single-framework pipeline smoke
→ final audit and report
```

## 声明边界

- Docking teacher 是 geometry surrogate，不是 binding/blocking 实验真值。
- 96 条全部来自 `h-NbBCII10`，只能用于 pipeline smoke。
- 正式 V3-P 还需要多 parent 的 400-600 条首批 teacher，以及后续 300-500 条主动学习数据。
