# V2.19：150K 多模型 Docking-geometry surrogate 生产筛选

## 目标

对冻结候选库

```text
/data/qlyu/projects/pvrig_1m_fixed_pose_top150k_multimetric_v2_20260722/
```

中的 150,000 条 VHH 进行 label-free 多模型推理，输出用于后续独立双受体
Docking 的 Top 5%（固定 7,500 条）。本流程预测的是 **computational Docking
geometry surrogate**，不是结合概率、Kd 或实验阻断概率。

## 已冻结的输入事实

- 150,000 个唯一 candidate ID、序列与 sequence SHA256；
- 150,000/150,000 NBB2 结构成功，32 个 archive 与每个 PDB 已全量哈希闭合；
- 150,000/150,000 ANARCI、AbNatiV、TNP 成功；
- 9 个 parent，单一 fixed-pose ProteinMPNN/H1H2H3 生成路线；
- 主表 SHA256：`105bed3b7542a6f1b4d3bbf609101c7ed254be776ca2a3fdacc3c2cc695e88e0`。

## 模型组合

### 全库运行

1. **L1 clean-attention 五折**：严格 whole-parent OOF EF@5%=3.083，主模型；
2. **B clean-attention 四种子**：独立训练的 target-conditioned 互补模型；
3. **S0**：ESM2-650M pooled sequence + CDR/理化特征；
4. **M2**：NBB2 VHH 单体 126D 刚体不变结构描述符；
5. **弱先验/QC**：DeepNano、NanoBind、Sapiens、AbNatiV、TNP 与生产风险分数。

### 二阶段预池运行

6. **C2 coarse-pose**：对全库综合排名前 20% 的并集预池运行双受体低分辨率
   rigid-body 扫描，补充 approach-angle 信息。

## 固定生产策略

第一阶段 rank 融合：

```text
L1 0.50 + M2 0.20 + S0 0.15 + B 0.15
```

对综合前 20% 补 C2。最终 Top 7,500 由以下通道组成：

```text
6,750  consensus exploitation
  500  L1/B high-confidence rescue
  250  parent-balanced diversity/disagreement
```

另输出一个更严格的 `high_confidence_core`：L1 五折与 B 四种子方向一致、模型
rank spread 低、S0/M2 至少一项支持、且无 TNP HIGH_RISK_REVIEW。此 core 只表明
模型一致性更高，不提供可校准的生物学成功概率。

## 执行阶段

1. 输入哈希与 150K label-free Stage-0 先验评分；
2. archive 安全解包、逐 PDB 哈希复核与结构 manifest；
3. 并行物化 ESM2 pooled、M2、label-free graph；
4. L1 五折与 B 四种子推理，保存均值、标准差及模型间 rank spread；
5. 第一阶段 20% 预池；
6. C2 粗姿势特征及冻结 V2.11 融合；
7. 生成 global Top 7,500、parent-capped portfolio、high-confidence core、审计 receipt；
8. 将 Top 7,500 交给独立 8X6B/9E6Y Docking，回流结果用于下一轮主动学习。

## 外推风险

150K 只有 9 个新 parent，且与 teacher framework 无精确匹配。严格 OOF 的 30.83%
Top-5 precision 不能直接搬用成这批候选的成功概率。生产输出必须同时携带模型一致性、
fold/seed 方差、parent 与生成路线，Docking 仍是最终计算教师。

