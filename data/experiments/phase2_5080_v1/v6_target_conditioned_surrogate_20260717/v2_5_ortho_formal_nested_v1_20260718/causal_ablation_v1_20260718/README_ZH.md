# V2.5 target/contact 因果消融 V1

## 状态

`FROZEN_PRE_OUTER_RESULT_NONLAUNCHING`

本目录冻结的是**诊断协议和非启动作业图**。它不会启动训练、推理或评价，也没有修改正在运行的 301-job V2.5 正式图。

## 五项冻结消融

| 消融 | 执行方式 | 回答的问题 |
|---|---|---|
| hotspot/interface mask swap | 冻结模型推理；使用 clean meta 参数 | contact summary 是否真的定位 PVRIG 功能界面 |
| 8X6B/9E6Y conformer swap | 冻结模型推理；使用 clean meta 参数 | R8/R9 是否依赖正确的 receptor 构象 |
| target residue feature permutation, seed 1931 | 冻结模型推理；使用 clean meta 参数 | 模型是否使用 target residue identity，而非固定位置/槽位 shortcut |
| within-parent contact-label donor shuffle, seed 1931 | E_SHARED 重训；复用 clean fold 的 H；严格 inner/outer train 内 donor | contact supervision 是否通过 shared encoder 给 scalar 路径提供因果增量 |
| no-contact meta evidence | 只在 inner OOF 上重拟合 meta，`beta_C=0` | 两个 label-free contact score 是否在最终 stack 中提供增量 |

## 为什么 mask swap 不重训

V2.5 的 target graph encoder 和 scalar attention 路径不读取 `hotspot_mask/interface_mask`。这两个 mask 只参与 label-free contact summary。因此交换它们只允许改变 contact score 与 contact-aware meta 结果；若 standalone scalar 发生变化，应判定执行实现错误。

## 为什么 conformer swap 是全 payload swap

交换 8X6B/9E6Y 完整 graph payload，但保留 receptor key、conformer embedding 和 R8/R9 输出角色。这样测试的是 receptor role 与实际构象是否对应，而不是做一个无信息的图节点重标号。

## 为什么 residue permutation 只置换 node features

如果同时置换 node features、边、mask，操作只是图同构重标号。冻结协议改为：置换 residue/node feature 行，同时保留图拓扑和界面位置，从而破坏“这个位置是什么 residue/局部特征”的对应关系。

## donor shuffle 防泄漏规则

- inner job：donor 只能来自当前 inner-train；
- outer refit：donor 只能来自当前 outer-train；
- donor 与 recipient 必须同 parent 且不同 candidate；
- singleton parent 直接 fail closed；
- marginal/pair label、mask、uncertainty、missingness、tier 必须作为完整 payload 一起迁移；
- scalar truth、VHH sequence、monomer graph、parent 和 candidate identity 不迁移。

## 严格比较

- 外层单位：`parent_framework_cluster`；
- 5 outer × 5 inner；
- inference ablation 使用 clean frozen model 和 clean fold meta 参数，不允许针对扰动重调；
- contact-label shuffle 复用 clean E_SHARED 每 fold 已选 H，不允许另选有利 H；
- 所有 Rdual 必须由 `min(R8,R9)` 计算，容差 `1e-12`；
- parent bootstrap：10,000 次，seed 1931；
- 所有因果 gate 都是诊断 gate，不是模型 promotion gate。

## 冻结工作量

```text
GPU inference perturbation        45
CPU inference ensemble            15
GPU contact-shuffle inner retrain 25
GPU contact-shuffle outer retrain 15
CPU contact-shuffle ensemble       5
CPU nested meta/evaluation         25
CPU final collect                   1
------------------------------------
Total                             131
GPU                                85
CPU                                46
```

## 启动边界

`watch_formal_terminal_then_mark_ablation_ready_v1.py` 只能写入：

```text
WAITING_FORMAL_V1_3_TERMINAL_NONLAUNCHING
READY_NONLAUNCHING_EXPLICIT_NEW_AUTHORIZATION_REQUIRED
```

它没有 subprocess/launcher 路径。当前目录不会自动执行 131-job 图；未来必须另建 executable adapter 版本并重新审计。

## 证据边界

这些结果最多支持 open-development computational Docking-geometry target/contact sensitivity。它们不能说明实验 binding、Kd、PVRIG 阻断概率、Docking Gold 或比赛提交真实性。V4-F/test32 access count 始终为 0。

