# PVRIG 阳性 VHH 静态能量与动力学校准方案

更新时间：2026-07-24

## 1. 结论

这个方向正确，但不能只跑阳性。

- **11 条已知阳性 VHH**可以定义“阳性参考包络”及已知 Kd/IC50 的方向。
- **破坏性突变、弱扰动和错位 pose**用于测量假阳性与方法稳定性。
- 现有突变对照没有湿实验阴性标签，因此只能称为**计算扰动对照**，不能称为已证实 non-binder/non-blocker。
- FoldX、PRODIGY、Rosetta、MD/MMGBSA 都只能形成内部排序证据，不能替代官方 BLI Kd 和竞争 ELISA IC50。

因此建议把动力学放在最后一层：验证 docking 得到的阻断姿势在显式溶剂中是否持续，而不是直接把 MD 能量解释成亲和力或阻断活性。

## 2. 与官方评分的对应

官方目标不是单纯 binder，而是：

1. 结合 PVRIG 胞外区；
2. 靶向 PVRIG-PVRL2 界面；
3. 阻断 PVRIG-PVRL2；
4. 同时满足表达、纯度和序列合规。

官方初筛权重：

- BLI 单浓度结合：70%；
- 表达量：20%；
- 纯度：10%。

官方复筛权重：

- BLI Kd 排名：50%；
- 竞争 ELISA IC50 排名：50%。

所以计算流程必须保持四条证据线分离：

| 证据线 | 计算代理 | 能否代替实验 |
|---|---|---|
| 表达/纯度 | VHH 完整性、可开发性、聚集/疏水/PTM 风险 | 不能 |
| 结合 | docking、PRODIGY、FoldX、Rosetta、MMGBSA | 不能 |
| 阻断 | 双构象热点覆盖、PVRL2 遮挡、CDR3 遮挡、MD 中遮挡保持率 | 不能 |
| 合规/新颖性 | ANARCI/IMGT、CDR identity、官方 validator | 可以作为提交前硬门控 |

## 3. 当前已经完成的阳性测试

### 3.1 阳性面板

共有 11 条：

- PVRIG-151_HR151
- PVRIG-20
- PVRIG-30
- PVRIG-38
- PVRIG-39
- 20H5
- 30H2
- 39H2
- 39H4
- 151H7
- 151H8

其中：

- 10 条有已知 Kd；
- 5 条有已知阻断 IC50；
- 11 条均作为校准/泄漏排除对照，不作为新设计提交。

### 3.2 已完成的静态亲和力 benchmark

已有 99 个冻结 HADDOCK pose，即 11 条 × 9 pose。

| 方法 | 观察结果 | 当前决定 |
|---|---|---|
| PRODIGY | 对实验 pKd 的 Spearman 0.310；pKd 中位绝对误差 2.63 log10 | 只保留弱先验 |
| FoldX AnalyseComplex | 对实验 pKd 的 Spearman 0.236 | 不用于跨候选绝对亲和力排序 |
| FoldX fixed-pose ΔΔG | 5 个已知 parent-child pair 中方向正确 2/5 | 仅同 parent 诊断 |
| Graphinity | 4 个可评估 pair 中方向正确 1/4 | 当前多突变排名拒绝使用 |
| Rosetta InterfaceAnalyzer | 只完成过天然 PVRIG-PVRL2 smoke | 尚未完成 11 阳性同面板校准 |
| MD/MMGBSA | 无 PVRIG-VHH 正负配对轨迹 | 尚未校准 |

这说明“软件能运行”与“软件能判别”是两件不同的事。

## 4. 当前 docking 判别力为什么仍不够

V3 已经用同一冻结协议完成：

- 11 条专利阳性；
- 36 条突变/控制；
- 2 个 PVRIG 构象；
- 3 个 docking seed；
- 总计 1,050 个任务，1,049 个成功；
- 47 个控制实体共 282 个任务全部成功。

本轮把 11 条独立专利阳性的 66 个任务与 14 条破坏性 Ala 控制的 84 个任务比较。

实体级 AUROC：

| 指标 | AUROC |
|---|---:|
| strict-A job fraction | 0.571 |
| selected model strict-A fraction | 0.636 |
| 最小热点覆盖 | 0.679 |
| 最小 CDR3 遮挡 | 0.646 |
| 最小 CDR3 遮挡比例 | 0.623 |
| 最小总遮挡 | 0.442 |
| HADDOCK score | 0.468 |

解释：

- docking 几何对阳性有一定信号，但单指标仍不足以形成可靠 hard gate；
- 一些 CDR3 Ala 破坏性对照仍产生 strict-A，说明 docking 约束可以把错误序列推入正确几何区域；
- HADDOCK score 和总遮挡本身几乎不能区分阳性与破坏性对照；
- 最有价值的增量问题是：**这些几何看起来正确的假阳性 pose，在显式溶剂中是否更容易失去界面和阻断遮挡。**

## 5. 静态能量扩展

冻结输入：

- 阳性任务：66；
- 破坏性对照任务：84；
- 合计代表复合物：150。

统一运行：

1. PRODIGY；
2. FoldX RepairPDB + AnalyseComplex；
3. Rosetta InterfaceAnalyzer。

记录：

- 接触数；
- FoldX interaction energy、clash、界面残基和能量分项；
- Rosetta interface dG、dSASA、shape complementarity、界面氢键、埋藏未满足氢键和 packstat。

方法晋级条件：

- 实体级 AUROC ≥ 0.70，优选 ≥ 0.80；
- 已知阳性召回率 ≥ 0.80；
- 计算扰动对照假阳性率 ≤ 0.30；
- leave-one-family-out 方向一致率 ≥ 0.70；
- 未达到条件的方法只能保留为描述性字段，不能成为 hard gate。

## 6. 动力学 pilot

### 6.1 Stage A：最小配对校准

四个同 parent 正负配对：

| 阳性 | 扰动对照 |
|---|---|
| PVRIG-20 | PVRIG-20 F99A |
| PVRIG-30 | PVRIG-30 W100A |
| PVRIG-38 | PVRIG-38 F100A |
| PVRIG-39 | PVRIG-39 F99A |

另加：

- HR-151：官方阳性锚点；
- HR-151 的低支持 pose：只作为 pose-negative，不称生物学阴性。

协议：

- 主引擎：GROMACS 2024.4 CUDA；
- 交叉验证：OpenMM 8.4 CUDA，只跑 HR-151 和一个配对 sentinel；
- CHARMM36m + TIP3P；
- 0.15 M NaCl；
- 2 fs；
- 每体系 3 个独立 velocity seed；
- 先拓扑、最小化、NVT/NPT，再做 3 × 2 ns smoke；
- smoke 稳定后才扩展到 3 × 10–20 ns。

### 6.2 动力学指标

- 界面 backbone RMSD；
- CDR3 RMSF；
- PVRIG hotspot contact occupancy；
- 对齐到 8X6B/9E6Y 后的 PVRL2-interface occlusion persistence；
- 界面氢键与盐桥 occupancy；
- interface SASA；
- 平衡后 snapshots 的 gmx_MMPBSA median 和 IQR。

MMGBSA 只做相对排序，不换算成实验 Kd。

### 6.3 动力学方法晋级条件

- 每体系 3/3 replicate 完成；
- 无拓扑断裂、PBC 或成像伪影；
- 四个配对至少 3/4 方向正确；
- seed 方向一致至少 2/3；
- 阳性召回率 ≥ 0.80；
- 实体级 AUROC ≥ 0.70。

未通过时，动力学仍只作为人工复核证据，不纳入批量综合分。

## 7. 批处理位置

推荐规模：

```text
百万级序列
  -> 序列合规/可开发性
  -> 结构与快速几何筛选
  -> docking 双构象多种子
  -> 约数百条静态能量重打分
  -> 约20–50条短MD
  -> 最终50条提交排序
```

MD 不适合百万级或万级候选；它的价值是减少最后 20–50 条中的 pose 假阳性。

## 8. 当前执行状态

- 校准合同已经生成并验证；
- 阳性 V3 manifest：66 行；
- 破坏性对照 V3 manifest：84 行；
- 所有代表模型均绑定原 V3 job hash；
- Node1 当前 CPU load 约 100，正在运行多批 coarse-pose feature 任务；
- `/data1` 仅约 60 GiB 可用且显示 100% 使用率；
- `/data` 仍约 18 TiB 可用；
- GPU 基本空闲，但 MD 仍需要 CPU、拓扑准备和稳定 I/O。

因此当前不应抢占式启动 150 个 Rosetta/静态任务或全量 MD。下一安全动作是：

1. 在 `/data` 建立独立校准目录；
2. 冻结并校验 150 个代表复合物的实际 PDB SHA256；
3. 等 CPU load 回落后跑静态扩展；
4. 先做 HR-151 单体系 topology/minimization smoke；
5. smoke 通过后启动 Stage A 配对动力学。

## 9. 机器可读资产

- `CALIBRATION_CONTRACT.json`
- `BUILD_RECEIPT.json`
- `positive_v3_job_manifest.tsv`
- `destructive_control_v3_job_manifest.tsv`
- `observed_method_performance.tsv`
- `build_calibration_contract.py`

