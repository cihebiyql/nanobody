# PVRIG 50 万条 VHH 生成、筛选、结构预测与复核 Docking 执行方案

日期：2026-07-21  
状态：执行版 v1（先做 25,000 条五路线 pilot，通过门禁后扩展到 500,000 条）

## 1. 目标与证据边界

最终目标是建立一个 **500,000 条唯一、通过序列硬 QC、来源完整可追溯的 PVRIG VHH 序列库**，利用已完成的 V29 Docking 教师训练模型逐级富集具有更好“双构象阻断样几何”的候选。

必须始终区分四类证据：

1. 序列结合模型输出是 weak binding prior，不是可信 Kd；
2. 可开发性模型输出是表达、纯度、聚集等风险代理，不是实验表达量或纯度；
3. 单体结构和 Docking surrogate 预测的是计算几何及其排序；
4. 双受体 HADDOCK 结果仍只是 blocker-like geometry，不等同于实验阻断。

教师标签沿用冻结协议：

```text
8X6B 独立 Docking + 9E6Y 独立 Docking
Rdual = exact min(R8, R9)
固定 Top-8、hotspot/restraint、score_pose.py 和 blocker 规则
技术失败记 NA，绝不改写为低分负样本
```

## 2. 当前真实起点

V29 canonical teacher release 已物化：

```text
Node1 SSD: /data1/qlyu/projects/pvrig_v29_canonical_training_release_v1_20260721
Node1 NFS: /data/qlyu/projects/pvrig_v29_canonical_training_release_v1_20260721
主表: release/pvrig_v29_sequence_docking_weaklabels.tsv
```

已核验规模：

| 项目 | 数量 |
|---|---:|
| master Docking jobs | 24,826 |
| successful jobs | 24,815 |
| technical NA jobs | 11 |
| unique VHH candidates | 9,934 |
| seed917 双受体成功候选 | 9,927 |
| candidate-seed rows | 12,413 |
| Top-8 pose-reference rows | 393,296 |

严格防泄漏后的可用划分：

| split | 数量 | 说明 |
|---|---:|---|
| train | 6,878 | 6,872 有标签 + 6 NA |
| development | 719 | 全部有标签 |
| frozen_test | 688 | 全部有标签，模型选择期间封存 |
| quarantine | 1,649 | parent/CDR3 family 跨 split 冲突隔离 |

active splits 中 parent leakage 和 CDR3-family leakage 均为 0。不能把 quarantine 静默并回训练，也不能在筛选器冻结前反复查看 frozen-test 指标。

## 3. 教师数据给出的生成先验

在 9,927 条可分析候选中：

- `Rdual >= 0.65`：456 条，4.59%；
- `Rdual >= 0.70`：8 条；
- 严格多 seed 稳定强候选：42 条；
- `Rdual` 中位数 0.5589，95% 分位数 0.6482，最大值 0.7144。

观察到的富集方向：

| 维度 | 高分率或趋势 |
|---|---|
| FIXED_FRAMEWORK_CDR_PERTURBATION | 7.41% |
| CONSERVATIVE_PROFILE_LOCAL_REDESIGN | 6.57% |
| NATURAL_CDR_DONOR_REDESIGN | 4.48% |
| DE_NOVO_CDR_EXPLORATION | 2.63% |
| RFANTIBODY_RFDIFFUSION_PROTEINMPNN | 2.61% |
| C_CROSS / B_LOWER / A_CENTER | 4.90% / 4.54% / 4.34% |
| H1H2H3 / H1H3 / H3 | 6.57% / 4.81% / 3.17% |
| CDR3 18–22 aa | 明显优于 14–17 aa；21 aa 在本批最高 |

这些只是同一生成批次内的观察先验，含 parent、CDR3 长度和 generator 混杂，不能解释为因果规律。因此正式生成必须同时保留 exploitation、边界、不确定性、新 parent 和随机对照。

## 4. 总体漏斗

不为全部 50 万条预测结构。采用“序列先降采样、结构再降采样、Docking 最后确认”的资源配置：

```text
约 600k–650k raw，可断点续生成
  -> 500k unique + provenance-complete + sequence hard-QC pass
  -> 100k sequence-model shortlist
  -> 50k VHH monomer structures
  -> 约 40k–45k structure-QC pass
  -> sequence + structure ensemble 选 5,000
  -> 5,000 × 双受体 × seed917 = 10,000 primary Docking jobs
  -> Top 1,000 × 双受体 × seed1931 = 2,000 jobs
  -> Top 250 × 双受体 × seed3253 = 500 jobs
  -> 合计约 12,500 个 Docking jobs
```

## 5. 正式 500k 有效库配额

| 生成路线 | 有效序列目标 | 主要作用 |
|---|---:|---|
| 高质量 parent 上的保守 CDR redesign | 200,000 | 主 exploitation；提高高分密度和可开发性 |
| 新 parent 天然 CDR donor redesign | 100,000 | 扩大 parent/CDR 家族覆盖 |
| fixed-pose ProteinMPNN/AntiFold | 75,000 | 利用已知界面几何做局部序列优化 |
| 改进的表位条件 RFantibody | 75,000 | 探索新 backbone、patch 和姿势机制 |
| de novo / disagreement / random exploration | 50,000 | 保持分布外覆盖和主动学习能力 |

全库附加配额：

- target patch：C 40%、B 35%、A 25%；
- design mode：H1/H2/H3 45%、H1+H3 35%、H3-only 20%；
- CDR3 长度：18–22 aa 70%、16–17 aa 20%、10–15 aa 10%；
- 120–180 个 parent clusters；
- 单 parent 不超过有效库 1.5%；
- 当前高分 Top20 parents 合计不超过 35%；
- 至少 30% 来自当前 65 个 parent 之外的新 parent；
- 80% identity 的 CDR3 family 每族最多 50–100 条。

## 6. 第一轮执行：25,000 条五路线 pilot

先生成五个互不覆盖的 5,000 条有效子库：

1. `conservative_cdr_redesign_5000`；
2. `natural_cdr_donor_5000`；
3. `fixed_pose_mpnn_antifold_5000`；
4. `epitope_conditioned_rfantibody_5000`；
5. `denovo_disagreement_control_5000`。

这里的 5,000 指 **去重和硬 QC 后有效序列**。每条路线允许多生成 20%–40%，再通过相同门禁补齐；任何路线不足时不得用另一条路线静默冒充，而要在 manifest 记录回拨决策。

pilot 放行条件：

- 每路线 5,000 条有效唯一序列；
- 全局 exact duplicate 为 0；
- ANARCI/IMGT 成功率达到预注册门槛；
- parent、patch、mode、CDR3 长度和 CDR3-family 配额均可审计；
- known-positive CDR identity `<80%`，正式池优先 `<75%`；
- provenance、sequence hash、generator/version/seed 完整率 100%；
- 无单 parent、单 family 或单 generator 异常垄断；
- 快速可开发性风险分布不比 Top200 parent 基线显著恶化。

只有 pilot 达标，才按同一配置扩大到 500k；不达标则只修正失败路线，不重做已通过路线。

## 7. 序列硬 QC 与可开发性前筛

### 7.1 Hard gate

- 仅标准 20 种氨基酸；
- 长度 95–160 aa；
- ANARCI/IMGT 编号成功；
- FR1–FR4、CDR1–CDR3 完整；
- VHH framework 和保守 Cys 基本完整；
- 无 stop、非法字符、严重低复杂度；
- 无明显长疏水串、异常游离 Cys；
- 完全序列去重；
- CDR3 近重复聚类并限额；
- 与已知 PVRIG 阳性任一 CDR identity `<80%`。

### 7.2 独立软风险列

以下列只做风险排序或 Pareto 组合，不得改写 Docking 标签：

```text
developability_score
expression_purity_risk_score
AbNatiV
Sapiens
TNP
CDR glycosylation / deamidation / isomerization / oxidation flags
pI / charge / GRAVY / hydrophobic-run / aggregation proxies
```

TNP、AbNatiV 等较慢模型不必在 650k raw 阶段全量运行，可在快速规则和轻量模型降到 100k 后再运行。

## 8. 100k 序列短名单构成

不能只取当前模型 Top：

| lane | 数量 |
|---|---:|
| sequence surrogate / ensemble 高分 | 60,000 |
| 多模型分歧或高不确定性 | 15,000 |
| 新 parent / 新 CDR3 family / 新 generator | 10,000 |
| binding prior 与 Docking surrogate 共识 | 10,000 |
| QC-pass 分层随机对照 | 5,000 |

DeepNano、NABP-BERT、NanoBind 等只保留为独立 weak binding prior 和 disagreement 列，不作为 hard fail，也不称为 Kd。

## 9. 结构阶段和 5,000 条 Docking panel

对 100k 做轻量综合排序后，仅给约 50k 建模；复用 RFantibody/fixed-pose 已有 backbone 时必须记录结构来源，不能与独立预测结构混淆。

最终 5,000 条建议：

| lane | 数量 |
|---|---:|
| predicted blocker-like geometry high | 3,000 |
| uncertainty / disagreement | 750 |
| parent/CDR3/patch diversity | 500 |
| binding-prior consensus | 500 |
| QC-pass random controls | 250 |

模型进入生产前至少满足：

1. parent-held-out frozen test 合法且无 sibling 泄漏；
2. Top5% enrichment factor 目标至少 2；
3. R8、R9、Rdual 分别可预测，Rdual 推理时 exact-min；
4. 新 parent challenge 不崩溃；
5. parent-only、CDR3-length-only shortcut 不能解释主要增益；
6. 不确定性或模型分歧能识别一部分高误差样本。

按当前 4.59% 的随机基线，5,000 条随机 Docking 约有 230 条 `Rdual>=0.65`；若前筛达到 EF2/EF3/EF4，期望约为 460/690/920 条。实际目标设为 500–800 条计算高分候选，但不是保证值。

## 10. 每条候选必须保存的 provenance

```text
candidate_id, sequence, sequence_sha256
parent_id, parent_sequence, parent_cluster
design_method, design_seed, generation_batch
target_patch, design_mode, designed_regions
CDR1/2/3 before, CDR1/2/3 after
generator, generator_version, weight_hash, config_hash
sequence_QC results and failure reasons
monomer_model, monomer_version, monomer_pdb_hash
docking_protocol_hash, receptor, seed
R8, R9, Rdual, successful_seed_count, seed_dispersion
Top-8 pose paths/hashes and technical failure reason
```

parent、campaign、candidate ID、generator 仅用于审计、分层、split 和采样，不直接作为模型输入特征。

## 11. 执行与停止条件

当前执行顺序：

1. 冻结本执行文档和 machine-readable pilot spec；
2. 核验 Top200 parent、五类生成器、已部署权重和 QC 入口；
3. 生成 25k pilot 的 parent/patch/mode/method task manifests；
4. 逐路线可恢复生成，并持续进行 exact dedup 与 fast QC；
5. 完成 ANARCI 和基础可开发性审计；
6. 发布 pilot terminal release、失败原因和扩到 500k 的 PASS/HOLD 决策；
7. PASS 后分批生成到 500k，每批独立 hash、manifest 和可恢复状态；
8. 按 500k → 100k → 50k → 5k 漏斗执行预测和复核 Docking。

本阶段停止条件不是“启动了生成进程”，而是：25,000 条 pilot 有可验证的序列、QC、配额、provenance 和校验和，并给出可扩量判定。

## 12. 执行中发现的数据修复项

启动 pilot 时的 fail-closed 审计发现：Top200 CSV 中 200 条 parent 有 170 条 `cdr3` 字段与原始 `sequence_aa` 中的氨基酸顺序不一致，另有 3 条 `cdr2` 同类不一致；HR-151 和 Tab5 重链的表格 CDR3 也存在同类现象。原因是 ANARCI 插入位点列在旧解析器中按列名顺序拼接，而不是按原序列顺序拼接。

本 campaign 不直接使用该错序字符串做序列替换，而是用原始抗体序列中 FR3 末端 conserved-C 后、按已编号 CDR3 长度恢复 sequence-order CDR3，并把原表和恢复值都保留用于审计。旧表不能静默覆盖；后续应单独修复通用 ANARCI CSV parser 并做回归测试。
