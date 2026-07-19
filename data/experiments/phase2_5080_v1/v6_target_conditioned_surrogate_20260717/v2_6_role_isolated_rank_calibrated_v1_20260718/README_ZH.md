# V2.6 ROLE-ISOLATED / RANK-CALIBRATED 规划包

本目录是 V2.6 的**开发计划和预注册骨架**，不是训练结果或启动授权。

目标保持为：

```text
VHH sequence + label-free monomer + fixed PVRIG 8X6B/9E6Y
→ direct R8/R9 computational Docking-geometry surrogate
→ exact Rdual=min(R8,R9)
```

证据边界：不是结合概率、Kd、实验阻断概率、Docking Gold 或提交真值。

文件：

- `V2_6_NEXT_GENERATION_TRAINING_PLAN_ZH.md`：中文架构、损失、噪声、消融和停止规则。
- `PREREGISTRATION_SKELETON_V1.json`：启动前必须补全哈希、噪声诊断和冻结选项的机器可读骨架。

本包没有修改 V2.5 live training graph，也没有读取 V2.5 formal outer 结果或 V4-F/test32。
