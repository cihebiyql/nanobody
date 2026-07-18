# V5-RC Docking Contact Residual 实施说明

## 目的

V5-TB 已证明简单双受体头、理化描述符、分类头和 pairwise 头不能稳定超过 `B1/M2 structure-only Ridge`。V5-RC 因此引入一种真正不同的信息：从独立 8X6B/9E6Y Docking 的 Top-K pose 提取 VHH–PVRIG residue contact teacher，再训练一个推理时不读取 Docking 的 contact proxy。

## 已核对的远程事实

远程 campaign：

```text
/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
```

截至合同冻结前：

```text
2022 jobs terminal
2021 SUCCESS
1 FAILED_MAX_ATTEMPTS
37816 native/cross pose-score rows
每个成功 job 有 4–10 个 selected pose
pose PDB.GZ、candidate/receptor/seed provenance、VHH A 链与 PVRIG T 链均可追溯
```

V4-D evaluator 的 threshold-sensitivity 总门仍为 `FAIL`，所以本分支只能称为 open-development computational contact evidence，不能恢复为 Docking Gold。

## 实施顺序

1. **批量提取**：物理上先筛选 `OPEN_TRAIN226` candidate ID，再打开对应 raw `job_result.json` 和 pose；不读取 development32/test32 pose。
2. **候选级聚合**：4.5 Å heavy-atom contact；job 内按 HADDOCK score 取 Top-8 并 rank-weight；seed 只作测量重复，不作训练行。
3. **闭合审计**：验证序列与 pose A 链一致、每 receptor 至少两个成功 seed、所有输出哈希闭合、sealed pose 打开数为 0。
4. **无泄漏 proxy**：在每个 whole-parent outer fold 内，使用 outer-train contact teacher 训练 label-free structure/sequence → contact proxy；held-out candidate 的真实接触只能用于最后评估。
5. **残差融合**：比较 structure-only、非线性 structure baseline、contact bottleneck 和 contact-residual stack；任何模型替换都必须同时改善全局、parent-centered 与 Top20 指标。

## 停止条件

- 远程 pose 或链/序列映射不能闭合：停止，不生成伪标签；
- 任一 OPEN_TRAIN candidate/receptor 少于两个成功 seed：该候选不得进入完整 dual-contact teacher；
- contact proxy 不能超过同等容量的非线性 structure baseline：判定“contact supervision 暂无增益”，保留 M2；
- 不通过修改 cutoff、Top-K、parent split 或删除困难 parent 来修成成功。
