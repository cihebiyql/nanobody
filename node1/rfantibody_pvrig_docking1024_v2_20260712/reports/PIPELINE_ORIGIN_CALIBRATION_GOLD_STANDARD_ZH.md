# RFantibody-PVRIG V2 来源、双结构基线与校准标准说明

更新日期：2026-07-14

## 1. 先给出直接结论

1. `P2`、`P3`、`P4` 不是 docking 的第二、第三、第四阶段，也不是已知阳性 VHH 家族。它们是 RFantibody 生成时使用的三组 **PVRIG 界面热点 patch prompt**。
2. `8X6B` 和 `9E6Y` 是同一对生物分子 PVRIG-PVRL2/CD112 的两个独立 X-ray 实验结构，不是两个完全相同的坐标文件。
3. 当前 V2 **只进行了一次 8X6B-derived PVRIG 受约束 HADDOCK docking**。9E6Y 只用于对同一个 pose 做第二套 reference-overlay scoring，不是第二次独立 docking。
4. HR-151/PVRIG-151、PVRIG-20 等公开阳性 VHH 确实被用过，但用途是 **计算规则校准、敏感性检查和阳性泄漏排除**；它们没有被当作 1,024 条序列的生成母本，也没有把其预测 pose 当作 docking template。
5. 当前 node1 项目中的 `blocker_judgment_rules_v2.json` 与之前 success-case calibration 目录中的规则文件完全相同，SHA256 均为：

   ```text
   60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5
   ```

6. 因此，“当前评分是否用了之前校准后的 V2 规则？”的答案是 **是**。但“当前 docking pose 是否已有实验金标准？”的答案是 **否**。

## 2. 一个 candidate_id 到底表示什么

例如：

```text
PVRIG_RFAb_v2_P2_qkg_L_bb001_mpn03
```

可拆解为：

| 字段 | 含义 |
| --- | --- |
| `PVRIG_RFAb_v2` | PVRIG 靶向 RFantibody V2 生成批次 |
| `P2` | 生成时使用 `P2_bridge_N_C` 热点 patch |
| `qkg` | 使用 qkg 版 h-NbBCII10 VHHified scaffold |
| `L` | long-H3 设计档：H3 长度 11-15 aa |
| `bb001` | 该 arm 内 RFdiffusion 生成的第 2 个 backbone（0 起始编号） |
| `mpn03` | ProteinMPNN 为该 backbone 生成的第 4 条序列 |

所以 `P2/P3/P4` 是候选的“生成来源标签”，不是候选通过了哪个 docking 等级。

## 3. P1-P6 是什么

### 3.1 热点 patch 定义

| Patch | 生成意图 | 8X6B-derived chain T 编号 | UniProt Q6DKI7 编号 |
| --- | --- | --- | --- |
| `P1_core_blocker` | 两个 PVRIG-PVRL2 参考结构共享的核心阻断锚点 | `T57,T97,T101,T103,T105,T106` | `R95,K135,F139,E141,S143,W144` |
| `P2_bridge_N_C` | 同时覆盖 PVRIG 界面的 N 端区域和 C 端区域 | `T33,T36,T57,T60,T101,T105,T106` | `S71,T74,R95,R98,F139,S143,W144` |
| `P3_charge_aromatic` | 突出带电/芳香锚点，修复过度偏疏水的设计方向 | `T57,T60,T62,T97,T101,T105,T106` | `R95,R98,W100,K135,F139,S143,W144` |
| `P4_cterm_robust` | 主要覆盖 C-terminal interface，希望对受体局部构象变化更稳健 | `T97,T99,T101,T102,T103,T105,T106` | `K135,A137,F139,P140,E141,S143,W144` |
| `P5_upper_interface` | 探索不由 W144 主导的上部界面方位 | `T43,T44,T45,T52,T54,T57,T60` | `N81,G82,A83,V90,H92,R95,R98` |
| `P6_holdout_ablation` | 稀疏热点消融对照，用未 prompt 位点检查泛化 | `T57,T97,T101,T105,T106` | `R95,K135,F139,S143,W144` |

`T` 是为 RFantibody 和后续 pipeline 统一处理而使用的受体链名。它来自 8X6B PVRIG chain B；`T57` 不等于 UniProt 57，本项目通过 `PVRIG_hotspot_set_v1.csv` 在 PDB 编号、alignment column 和 UniProt 编号之间映射。

### 3.2 P2、P3、P4 不会在 HADDOCK 时继续使用各自的局部 patch

这是当前流程最容易被误解的地方：

- RFdiffusion 生成阶段：P2、P3、P4 分别使用自己的 5-7 个热点 prompt。
- HADDOCK 阶段：所有 P1-P6 候选都统一使用：

  ```text
  该候选的所有 CDR1/CDR2/CDR3 residues
      -> 8X6B PVRIG 全界面 23-residue hotspot union
  ```

- 因此 P2/P3/P4 可以用于后续统计“哪种生成假设更容易产生好 pose”，但不能说 P2/P3/P4 使用了三套不同的 docking 约束。

## 4. 1,024 条序列是怎么来的

### 4.1 起点不是 HR-151 或 PVRIG-20

生成起点是通用 h-NbBCII10 scaffold，之后做了三种 VHHified framework 版本：

| Scaffold | Kabat framework 修改 |
| --- | --- |
| `qrg` | `H44Q,H45R,H47G,H50S` |
| `ekg` | `H44E,H45K,H47G,H50S` |
| `qkg` | `H44Q,H45K,H47G,H50S` |

`orig` 未 VHHify 版本仅用于诊断对照，不进入最终 1,024 条 cohort。

### 4.2 生成矩阵

```text
6 个 hotspot patches
x 3 个 primary VHHified scaffolds
x 2 个 H3 长度档
= 36 个 primary generation arms
```

H3 长度档：

- `S`：`H1:7,H2:6,H3:5-10`；
- `L`：`H1:7,H2:6,H3:11-15`。

每个 arm 执行：

```text
8 个 RFdiffusion backbones
x 每个 backbone 4 条 ProteinMPNN sequences
= 32 条 raw sequence records/arm
```

因此：

```text
36 x 8 x 4 = 1,152 条 primary raw records
```

### 4.3 RFdiffusion 和 ProteinMPNN 分别做什么

1. RFdiffusion 输入：8X6B-derived PVRIG、VHHified scaffold、H1/H2/H3 长度范围、P1-P6 中某一组热点。
2. RFdiffusion 输出：面向目标热点的 VHH-PVRIG 设计 backbone/pose。
3. ProteinMPNN 在每个 backbone 上设计 H1/H2/H3 序列，每个 backbone 生成 4 条序列，温度为 0.2，并排除 `C` 和 `X`。
4. 这一步产生的是“对某组 PVRIG 热点有设计倾向的新 VHH”，不是对 HR-151 或 PVRIG-20 做局部突变。

### 4.4 1,152 -> 1,067 -> 1,024

```text
1,152 raw records
  -> 全局 exact sequence 去重
1,067 exact-unique sequences
  -> arm 平衡 + backbone round-robin + RFdiffusion 几何优先
     + exact-known-positive 排除 + max-flow 选择
1,024 frozen candidates
```

最终 1,024 条覆盖全部 36 arms 和 288 个 primary RFdiffusion backbones；每个 backbone 最多保留 4 个 ProteinMPNN siblings。

### 4.5 阳性泄漏检查

- `inputs/leakage_reference.fasta` 包含 32 个已知阳性/相关序列条目，包括 HR-151、PVRIG-20/30/38/39 及其多个 humanized 版本。
- 原始 1,152 条中 `raw_exact_known_positive_matches=0`。
- 最终 1,024 条中 `exact_known_positive_match=False` 为 1,024/1,024。
- 后续 sequence QC 的 `max_CDR_identity_to_positive` 范围为 0.375-0.75，1,024/1,024 通过 similarity filter；25 条在当前阈值边界被标记为 `BORDERLINE`。

注意：冻结器的硬排除是 full-sequence exact match；CDR 近邻相似度是后续 QC 的另一个证据轴。

## 5. 8X6B 和 9E6Y 为什么同时出现

### 5.1 它们不是两种不同靶点

| PDB | 内容 | 实验方法 | 分辨率 | 当前 pipeline 链 |
| --- | --- | --- | ---: | --- |
| `8X6B` | PVRIG-PVRL2/NECTIN-2 复合物 | X-ray diffraction | 2.00 A | PVRIG B，PVRL2 A |
| `9E6Y` | PVRIG/CD112R-PVRL2/CD112 复合物 | X-ray diffraction | 2.20 A | PVRIG A，PVRL2 D |

它们观察的是同一对蛋白，但是两次独立的实验结构，局部坐标、晶体环境、残基编号和 PVRL2 相对位置不会完全一样。

本次复核使用 23 个界面 CA 对做映射对齐：

- 8X6B PVRIG 对齐到 9E6Y PVRIG 后 RMSD 约 0.358 A；
- 固定该 PVRIG 对齐后，两个 PVRL2 的对应 CA 无二次 refit RMSD 约 0.997 A，最大对应 CA 位移约 2.448 A。

它们很相似，但对基于原子/残基距离阈值的遮挡评分而言，1-2 A 的差异已可改变 hotspot overlap 和 occlusion 计数。

### 5.2 当前 V2 的真实流程

```text
候选 VHH 序列
    |
    +-- NanoBodyBuilder2 --> VHH 单体结构（chain A）
                                |
8X6B PVRIG chain B --> chain T -+-- HADDOCK3（只做这一次）
                                     |
                                     +--> 8X6B-guided VHH-PVRIG poses
                                              |
                         +--------------------+--------------------+
                         |                                         |
                         v                                         v
             对齐到 8X6B PVRIG                    对齐到 9E6Y PVRIG
             放入 8X6B PVRL2 A 位置               放入 9E6Y PVRL2 D 位置
             计算热点/遮挡/CDR3                  计算热点/遮挡/CDR3
                         |                                         |
                         +--------------------+--------------------+
                                              |
                                      dual-baseline consensus
```

这里的“对齐”是：使用同一蛋白 PVRIG 的对应 CA 坐标计算刚体变换，然后把同一变换同时应用到 VHH pose。

它不是：

- 把 8X6B 整个复合物与 9E6Y 整个复合物互相 docking；
- 把两个“相同的结构”做重复匹配；
- 使用 9E6Y 另外运行一次 HADDOCK。

在 HADDOCK 计算中，PVRL2 本身没有作为第三个分子参与。它在后处理时被放回实验参考位置，像一个“虚拟占位参考”，用于问：“如果 PVRL2 还要按实验结构结合，这个 VHH 是否会占位/冲突？”

### 5.3 为什么两个基线的结果差别很大

在当前 4,096 个后处理 pose 中：

- 8X6B 单基线 `BLOCKER_LIKE_A`：1,282/4,096（31.30%）；
- 9E6Y overlay `BLOCKER_LIKE_A`：66/4,096（1.61%）；
- 两个基线都是 A 的 `CONSENSUS_BLOCKER_LIKE_A`：63 poses，来自 47 条候选。

这说明 9E6Y 在当前阈值下是很严格的跨构象过滤器。它不能被解释为“9E6Y 一定更真”；也可能包含残基阈值、映射和对 8X6B-guided pose 使用第二基线时产生的严格性。

## 6. 阳性 VHH 参考到了什么程度

### 6.1 已完成的阳性序列校准批次

当前本地有 11 个公开成功/阳性序列 case：

```text
PVRIG-151_HR151
PVRIG-20
PVRIG-30
PVRIG-38
PVRIG-39
20H5
30H2
39H2
39H4
151H7
151H8
```

对每条序列都执行了：

```text
known-positive sequence
  -> NanoBodyBuilder2 monomer
  -> hotspot/CDR-guided HADDOCK3
  -> 8X6B scoring
  -> 9E6Y overlay scoring
  -> dual-baseline consensus
```

这些阳性序列有公开的 binding/blocking 或专利成功信息，但本项目中的 VHH-PVRIG pose 是计算生成的，不是 X-ray/cryo-EM 解析的 VHH-PVRIG 复合物真值。

### 6.2 初始阈值如何来

HR-151 阳性对照首次运行产生了第一版 `BLOCKER_LIKE_A` 阈值：

```text
PVRIG hotspot overlap count              >= 14
total VHH-PVRL2 residue-pair occlusion   >= 500
CDR3-PVRL2 residue-pair occlusion        >= 100
CDR3 occlusion fraction                  >= 0.15
```

原始 protocol 已明确注明：这些不是通用生物物理阈值，而是 HR-151 positive-control run 的 first-pass calibration values。

后续做了：

- 11 个阳性 case 的完整后处理；
- 81 组阈值网格的敏感性分析；
- 36 条阳性家族突变/消融 control panel 的流程和阈值稳健性检查。

### 6.3 当前规则对阳性的实际表现

11 个阳性 case 共 109 个 pose：

| Consensus label | Pose 数 |
| --- | ---: |
| `CONSENSUS_BLOCKER_LIKE_A` | 3 |
| `SINGLE_BASELINE_BLOCKER_RECHECK` | 36 |
| `BLOCKER_PLAUSIBLE_B` | 57 |
| `EVIDENCE_INFERENCE_ONLY_E` | 13 |

按 case 计：

- 至少有一个单基线 A 信号：10/11 cases；
- 至少有一个严格双基线 A/A pose：1/11 cases；
- 唯一有严格双基线 A/A 的 case 是 `20H5`。

HR-151 和 PVRIG-20 本身的 top pose 都是：

- 8X6B 达到 A；
- 9E6Y 因 hotspot overlap 不足而只达到 plausible B；
- case-level 为 `HAS_SINGLE_BASELINE_BLOCKER_RECHECK`，不是严格 consensus A。

因此，当前 `CONSENSUS_BLOCKER_LIKE_A` 比多数已知阳性更严格。它适合作为高精度计算优先级标签，但不是一个已经用完整阳性/阴性数据做 ROC 标定的通用分类器。

### 6.4 阳性 pose 没有被用为生成或 docking template

当前 1,024 条流程中：

- RFdiffusion 使用 PVRIG-PVRL2 实验界面热点，不使用 HR-151/PVRIG-20 pose；
- ProteinMPNN 为 RFdiffusion backbone 重新设计 CDR 序列，不从 HR-151/PVRIG-20 序列突变拓展；
- HADDOCK AIR 是“候选所有 CDR residues -> 8X6B 全界面 hotspot union”，不是“复现 HR-151 接触对”；
- HR-151/PVRIG-20 用于评分规则校准和 leakage reference。

## 7. “金标准”应该怎样分层

| 层次 | 当前有什么 | 能作为什么标准 | 不能证明什么 |
| --- | --- | --- | --- |
| 实验配体界面参考 | 8X6B、9E6Y PVRIG-PVRL2 X-ray 复合物 | PVRL2 真实结合位置、PVRIG-PVRL2 界面参考 | VHH 真实结合 pose |
| 实验/专利阳性序列 | HR-151、PVRIG-20/30/38/39 等 | 已知 binder/blocker 序列锚点、泄漏控制 | 它们与 PVRIG 的原子级 pose |
| 计算校准规则 | `blocker_judgment_rules_v2.json` | 阳性案例锚定的 blocker-like geometry screen | 实验阻断、Kd、IC50，或 pose 真值 |
| 候选 docking pose | NBB2 + HADDOCK3 + dual overlay | 受约束构象假设和几何排序 | 真实结合方位或必然阻断 |

最准确的命名是：

```text
阳性案例锚定、经阈值敏感性审查的双参考计算遮挡几何判别基准
```

不应直接命名为：

```text
VHH-PVRIG docking 实验金标准
```

### 7.1 当前规则确实是之前的校准版，但 docking 执行协议不是完全相同副本

相同部分：

- V2 规则 JSON 文件字节级一致，SHA256 相同；
- A 级阈值与 A/B/C/E 解释相同；
- 都使用 CDR-to-PVRIG-interface 受约束 HADDOCK 和 8X6B/9E6Y 后处理。

不完全相同的部分：

- 阳性校准批次的 8X6B AIR 热点列表含 24 个位点，包含早期 soft-hint residue B29；当前 V2 cohort 的 full-interface union 为 23 个位点，已排除 B29；
- 阳性校准 config 通常保留 10 个 top cluster models，当前 V2 统一对每条候选的前 4 个 pose 做 dual-baseline consensus；
- 当前 V2 将 8X6B PVRIG chain B 规范化为 chain T。

因此应说：

> 当前使用的 **后处理判定规则** 是你之前经过阳性案例校准的 V2 版本；当前 **HADDOCK 生成 pose 的执行协议** 是在该思路上规模化后的 cohort 版，不是原始 HR-151 运行的完全复制。

## 8. RF2 pose recovery 与 HADDOCK 双基线不是同一件事

第一代报告中的“78 条 RF2 严格 pose recovery = 0”容易与 8X6B/9E6Y 混淆。

- RF2 pose recovery 比较的是：

  ```text
  RF2 从序列 blind-predict 出的 VHH-PVRIG 复合物
      vs
  RFdiffusion 最初设计出的 candidate backbone/pose
  ```

- 它先对齐 target PVRIG，再计算 antibody RMSD 和 CDR RMSD，并结合 interaction PAE。
- 它检查“序列是否能独立恢复 RFdiffusion 的设计姿势”，不是检查“VHH 是否恢复 HR-151 真实 pose”。
- 当前完整 V2 中，1,024 条 x 3 seeds 共 3,072 条 RF2 记录；正式门控为 4 pass、28 near-calibration、992 fail-complete。RF2 fail 只是 pose-recovery/interaction-confidence QC，不是不结合标签。

HADDOCK dual-baseline 问的是另一个问题：“这个受约束 docking pose 是否在 8X6B 和 9E6Y 两个 PVRL2 参考位置上都呈现遮挡几何？”

## 9. 可复核的核心文件

### 生成来源

```text
config/generation_arms.tsv
config/generation_arms_primary.tsv
config/generation_execution_policy.json
data/generation_freeze_summary.json
data/candidates.tsv
scripts/create_generation_arms.py
scripts/run_generation_arm.sh
scripts/collect_and_freeze_candidates.py
```

### Docking 和双基线

```text
scripts/build_docking_package.py
scripts/postprocess_candidate_dual_baseline.py
scripts/postprocess_helpers/score_reference_baseline.py
scripts/postprocess_helpers/align_pdb_by_chain.py
data/docking_runs.tsv
data/docking_pose_baseline_metrics.tsv
data/docking_pose_consensus.tsv
reports/FINAL_COMPLETION_ZH.md
reports/DOCKING_SCORE_BLOCKER_ANALYSIS_ZH.md
```

### 校准和阳性对照

```text
/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/blocker_validation_protocol_v1.md
/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/hr151_cdr3_occlusion_validation.md
/mnt/d/work/抗体/docking/calibration/patent_success_validation/PATENT_SUCCESS_SERIES_POSTPROCESS_SUMMARY.md
/mnt/d/work/抗体/docking/calibration/patent_success_validation/THRESHOLD_SENSITIVITY_REPORT.md
/mnt/d/work/抗体/docking/success_case_validation/blocker_judgment_rules_v2.json
scripts/postprocess_helpers/blocker_judgment_rules_v2.json
```

## 10. 一句话回答全部问题

> P2/P3/P4 是 RFantibody 生成时的 PVRIG 界面热点提示组；1,024 条是从 VHHified h-NbBCII10 scaffold 经 RFdiffusion backbone 生成和 ProteinMPNN 序列设计后去重平衡冻结得到，不是从 HR-151/PVRIG-20 派生；HADDOCK 实际只对 8X6B-derived PVRIG 做一次，9E6Y 只是同 pose 的第二结构遮挡参考；当前判定 JSON 确实是之前的阳性案例校准 V2 版，但 HR-151/PVRIG-20 pose 本身也是计算预测，所以当前只能称为“阳性案例锚定的计算几何基准”，不能称为有实验 VHH-PVRIG pose 真值的 docking 金标准。
