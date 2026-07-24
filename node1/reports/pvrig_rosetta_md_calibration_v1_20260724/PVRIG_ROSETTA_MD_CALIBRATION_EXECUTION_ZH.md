# PVRIG Rosetta 与短程动力学校准执行状态

更新时间：2026-07-24 17:55 CST

## 当前结论

1. 已冻结并完成 150 个 V3 代表复合物的 Rosetta InterfaceAnalyzer：
   - 已知阳性：66 jobs，11 个实体。
   - CDR3 破坏性 Ala 对照：84 jobs，14 个实体。
   - 完成 150/150，失败 0。
2. Rosetta 所有单项均未同时达到预注册门槛：
   - 实体 AUROC 不低于 0.70；
   - 阳性召回不低于 0.80；
   - 破坏性对照 FPR 不高于 0.30；
   - 配对实体及家族方向一致率不低于 0.70。
3. 因此 Rosetta 当前结论为 `ROSETTA_DESCRIPTIVE_ONLY`：
   - 可以用于结构解释、异常排查和次级特征；
   - 不得作为候选硬门控；
   - 不得替代 docking blocker geometry、实验 Kd 或 IC50。
4. 三个 GROMACS 体系均已完成 CHARMM36m/TIP3P、0.15 M NaCl 建系和最小化：
   - HR-151 positive；
   - PVRIG-20 positive；
   - PVRIG-20 F99A destructive。
5. OpenMM 8.4 独立 HR-151 最小化已完成：
   - CUDA 首次建系通过、Context 创建因 PTX 版本不兼容失败，错误已归档；
   - 同一体系、同一 CHARMM36/TIP3P 条件下使用 OpenCL GPU 完成；
   - 势能由约 -198,319 降至 -783,051 kJ/mol。
6. 9 条短程轨迹正在 Node1 后台运行：
   - 3 个体系 × 3 seeds；
   - 每条 100 ps NVT + 100 ps NPT + 2 ns production；
   - 当前 3 完成、3 运行、3 待续接、失败 0；
   - GPU 0/1/2 使用率约 61–71%；
   - 预计 20–25 分钟收口。

## 自动续接

`node1_md_analysis_watcher.sh` 已在后台等待 9 条轨迹全部完成。完成后自动分析生产段后 1 ns：

- PVRIG 对齐后的 VHH backbone RMSD；
- 复合物 backbone RMSD；
- 界面最小距离；
- 0.45 nm 界面接触数；
- 界面氢键数；
- PVRIG-20 positive 与 F99A destructive 的三 seed 配对方向。

至少 2/3 个界面指标满足 2/3 seed 同方向，才标记为可扩大到 PVRIG-30、38、39；否则动力学保持稳定性/解释性证据，不进入主排序。

## 远端路径与进程

- 项目：`/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724`
- Rosetta 状态：`status/ROSETTA_STATUS.json`
- Rosetta 校准：`reports/ROSETTA_CALIBRATION_RECEIPT.json`
- MD 生产状态：`status/MD_PRODUCTION_STATUS.json`
- MD 分析状态：`status/MD_ANALYSIS_STATUS.json`
- MD controller PID：`1670360`
- MD analysis watcher PID：`1709798`

## 重要边界

短程 MD 只能用于：

- 初始 pose 是否快速散开；
- 界面接触与氢键是否稳定；
- 阳性和定向破坏突变能否给出一致方向。

它不能直接证明实验亲和力或阻断活性。只有在阳性/破坏性对照校准达标后，才可以作为几千条候选中的末级昂贵筛选。
