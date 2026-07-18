# V2.5 coarse-pose：开放数据 whole-parent OOF 挑战者计划

## 冻结边界

本分支只评估 label-free coarse-pose 信息能否为当前 V2.4 提供增量。输入不得包含候选
Docking pose、Docking score、R8/R9/Rdual、V4-F/test32、candidate/parent/campaign ID 数值编码。

输出仍然只是对独立双受体计算 Docking 几何的 surrogate，不是结合概率、Kd 或实验阻断概率。

## 数据与 split

- 开放候选：1,507；V4-D 226 + V4-H 1,281；31 个 parent clusters。
- 复用冻结的五折 parent-balanced outer split，SHA256：
  `ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55`。
- 复用冻结 inner nested split，SHA256：
  `b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073`。
- 同一个 parent 的全部 sibling 永远在同一折。

## 两个预定义挑战者

### C1：Symmetric12D

直接使用冻结、无拟合的 12D receptor-symmetric/dual summary。每个 outer fold 内训练两个
Ridge 输出 R8/R9，推理时 `Rdual=min(R8,R9)`。alpha 候选网格固定为：

```text
1e-4, 1e-3, 1e-2, 1e-1, 1, 10, 100
```

alpha 只能依据对应 outer-train 内的 whole-parent inner OOF 选择。

### C2：PCA8-Ridge

原始 36D 先固定删除两个 `pose_count` QC 和两个 entropy 近常数列，剩余 32D。每个 inner fold：

```text
inner-train parents
→ train-only mean/std 与常数列过滤
→ train-only PCA8
→ train-only two-output Ridge
→ 仅预测 inner-score parents
```

outer-test 时在完整 outer-train 上重新拟合 scaler/PCA8/Ridge，再预测 outer-score parents。
不同 fold 的 PCA 坐标不能直接拼接成一个共享 meta 输入；只能堆叠 fold-specific base predictions。

## 正式评估顺序

1. 冻结 1,507 行 36D 与 12D 的 hash、代码 hash 和 split hash；
2. 在每个 outer fold 内完成上述 nested selection；
3. 只收集每条候选一次的 outer OOF prediction；
4. 派生 exact-min Rdual；
5. 由独立 evaluator 与 M2、V2.4 比较；
6. 只有通过冻结增量、来源分层、parent macro、MAE 和 target-ablation gates 才可讨论推广；
7. 在预测冻结前，V4-F/test32 始终 sealed。

当前任务只物化 label-free 特征和合同，不训练、不比较性能、不推广。
