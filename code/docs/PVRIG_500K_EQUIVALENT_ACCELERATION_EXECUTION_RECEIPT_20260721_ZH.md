# PVRIG 50 万 VHH 等效加速执行收据（2026-07-21）

## 当前结论

已按“Node1 每块可用 GPU 3 个并行 + bxcpu 8 节点 CPU 并行”执行。当前不是最终 50 万冻结库，而是已经完成大规模原始生成、全局 exact 去重和自动接力部署。

## Node1 GPU 路线

- 远端目录：`/data1/qlyu/projects/pvrig_500k_rfantibody75k_v1_20260721`
- 使用 GPU：1–7；GPU0 保留给既有任务。
- 并发：每 GPU 3 个 worker，共 21 条 lane。
- 3× smoke：21/21 输入完成，得到 336/336 sequence PDB，无 CUDA OOM，随后自动转入正式任务。
- 正式目标：36 arms × 157 backbones × 16 sequences = 90,432 raw；冻结目标 75,000 exact-unique RFantibody 候选。
- 2026-07-21 22:26 CST 快照：404/5,652 backbones，controller 状态 `GENERATING`。

## bxcpu CPU 路线

### 主批次

- 220,000 conservative CDR redesign + 120,000 natural CDR donor = 340,000 raw。
- 8 个节点 × 64 worker，SLURM job `11939130`。
- FAST-QC PASS：317,221。
- exact-unique FAST-QC PASS：286,872。

### 天然供体补充批次

- 原因：主批次 natural-donor H3-only 空间饱和，24,000 PASS 中仅 2,321 exact-unique。
- 补充 60,000 个 H1+H3 / H1+H2+H3 组合任务，SLURM job `11939171`。
- FAST-QC PASS：53,893。
- 相对主批次新增 exact-unique：46,472。

### 独立 exploration/control 批次

- 路线名：`profile_diversified_exploration_control`。
- 70,000 raw，SLURM job `11939226`。
- FAST-QC PASS 且 exact-unique：60,951。
- 设计模式：H3 40%、H1+H3 35%、H1+H2+H3 25%。
- 该路线是较宽松的 CDR profile exploration/control，不冒充真正 de novo 结构生成。

### 合并状态

- 合并后 exact-unique FAST-QC 候选：394,295。
- 路线构成：
  - conservative CDR redesign：204,265；
  - natural CDR donor：129,079；
  - profile exploration/control：60,951。
- 本地：`pvrig_500k_generation_20260721/run/pvrig_500k_cpu_control_combined394k_v1_20260721/`
- Node1：`/data1/qlyu/projects/pvrig_500k_cpu_generation_v1_20260721/combined_cpu_control_exact_unique/`
- 以上均已进行 archive SHA256、回传后 SHA256 和 task-ID 唯一性检查。

## fixed-pose ProteinMPNN 自动接力

- 资产：11 个已知阳性/阻断参考 × 9 个冻结 HADDOCK pose = 99 poses。
- 源链 A/B 已明确归一化为 H/T：H=VHH，T=PVRIG。
- 计划：99 poses × 1,200 sequences = 118,800 raw；目标冻结 75,000。
- Node1：`/data1/qlyu/projects/pvrig_500k_fixed_pose_mpnn75k_v2_20260721`
- controller 已启动，当前 `WAITING_RFANTIBODY`。
- RFantibody 完成后将自动执行：
  1. 21 pose、每 pose 16 序列的 7 GPU × 3 worker smoke；
  2. 校验 H/T 链、CDR label 和 smoke 唯一性；
  3. 99 pose 全量 118,800 raw；
  4. 对 11 条阳性 CDR 做 `<80%` hard gate、fast QC、exact dedup 和 75k 均衡冻结。

## ANARCI 自动接力

- Node1 watcher PID：见 `/data1/qlyu/projects/pvrig_500k_cpu_generation_v1_20260721/status/anarci_watcher.pid`。
- watcher 先等 RFantibody 和 fixed-pose ProteinMPNN 达到终态，再合并 CPU/control 394,295 条、RFantibody 75,000 条及可用的 fixed-pose 75,000 条，以 20 CPU 统一运行 ANARCI/IMGT；fixed-pose 若进入 HOLD，则保留其 HOLD 语义并继续处理其余已闭合路线。
- 本机不承担该大批量 ANARCI，避免再次出现高温负载。

## 尚未完成的门禁

1. RFantibody 75k 尚在生成；
2. fixed-pose ProteinMPNN 尚待 smoke，不能提前声称 75k 有效；
3. 394,295 条仅通过 fast QC 和 exact dedup，尚未完成 ANARCI、CDR3-family cap 和最终配额冻结；
4. 结构预测和 docking surrogate 前筛尚未开始；
5. 所有分数仍属于计算先验或阻断样几何，不等于实验结合、Kd、IC50 或真实阻断。

## 时间预估

按当前 Node1 RF backbone 实测速率，RFantibody 主批次约还需 10–14 小时；其后 fixed-pose ProteinMPNN 和 ANARCI 预计再需数小时。若 smoke 和 I/O 不出现新故障，整体仍以 24 小时内完成生成与硬 QC 为目标，但不把该时间写成保证。
