# PVRIG Final50 优先 Top10：PyMOL 审阅包

## 包含内容
- `models/`：Top10每条候选的两个代表 Docking pose（8X6B、9E6Y），共20个PDB。
- `references/8X6B.pdb` 与 `references/9E6Y.pdb`：原生PVRIG–PVRL2复合物参考。
- `pymol/review_rank01.pml` 至 `review_rank10.pml`：一键审阅脚本。
- `tables/`：Top10、Final50、Top10静态pose指标以及候选–PDB映射。

## 打开方法
在 PyMOL 中打开任一 `pymol/review_rankXX.pml`；或命令行进入本目录并运行：

```bash
pymol pymol/review_rank01.pml
```

脚本默认显示 8X6B 场景：
- 蓝色半透明表面：Docking 中的 PVRIG；
- 绿色 cartoon：候选 VHH；黄色 sticks：PVRIG–VHH 接口VHH残基；
- 红色半透明表面：原生 PVRL2，用于检查空间竞争/遮挡。

切换到右侧 Scene 的 `9E6Y_blocking_overlay` 可查看另一参考构象：候选VHH为橙色，原生PVRL2为洋红色。

## 正确解读
- VHH 与红色/洋红色 PVRL2 的空间互斥是**预期竞争遮挡**，因为二者不应同时与PVRIG结合。
- 不应存在 VHH 与蓝色/灰色 PVRIG 明显原子穿插或完全脱离的姿态。
- 单条代表pose只适合视觉复核；多seed一致性仍以 `top10_priority.tsv` 和 `top10_static_pose_metrics.tsv` 的字段为准。
- 这是计算筛选结果，不代表实验结合、Kd、IC50、表达量或纯度已验证。
