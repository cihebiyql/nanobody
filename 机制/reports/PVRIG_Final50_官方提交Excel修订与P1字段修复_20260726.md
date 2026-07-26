# PVRIG Final50 官方提交 Excel 修订与 P1 字段修复

日期：2026-07-26

## 结论

已修复 P1 开发性分级中 `instability_index` 的字段来源错误，并基于
Node1 原始输入重建 P1、最终冻结收据和官方提交 Excel。最终推荐排序
仍为 `PVRIG_CAND_001–050`，前 10 条为 `PVRIG_CAND_001–010`。

当前最终 Excel：

```text
C:\Users\ciheb\Downloads\PVRIG_Final50_抗体赛道初赛作品提交表_修订版v2_20260726.xlsx
```

## 1. P1 修复

旧脚本从不含 `instability_index` 的 screen summary 读取该字段，导致风险
判断静默跳过。修订后：

- 从 `vhh_eval.tsv` 读取真实 `instability_index`；
- 强制 50/50 条记录存在可解析、有限的数值；
- PRIMARY 分级从 `17 A / 30 B / 3 C` 修正为
  `13 A / 34 B / 3 C`；
- `PVRIG_CAND_014/036/038/039` 从 A 调整为 B；
- Top10 恢复为 `PVRIG_CAND_001–010`。

修订证据目录：

```text
机制/data/audits/PVRIG_QC397_Final50_P0P1提交冻结与证据闭环_v1_2_20260726/
```

## 2. fixed-pose 三个 CDR 全设计证据

对当前 Final50 中 15 条 `fixed_pose_mpnn` 候选逐条追溯至 Node1
`pvrig_1m_fixed_pose_mpnn150k_v1_20260722` 原始冻结生成记录：

- 15/15 匹配唯一冻结生成记录；
- 15/15 任务 `loop_string=H1,H2,H3`；
- RFantibody mask 实现将 H1/H2/H3 全部残基设为可设计位点，其他 VHH
  framework 和 PVRIG target 固定；
- 15/15 的最终 CDR1、CDR2、CDR3 均与各自 parent CDR 不同；
- 15/15 对应生成 PDB 存在并完成 SHA256。

证据：

```text
机制/data/audits/PVRIG_QC397_Final50_P0P1提交冻结与证据闭环_v1_2_20260726/fixed_pose_provenance/Final50_fixed_pose_CDR123_redesign_audit.tsv
机制/data/audits/PVRIG_QC397_Final50_P0P1提交冻结与证据闭环_v1_2_20260726/fixed_pose_provenance/FIXED_POSE_CDR_REDESIGN_RECEIPT.json
```

该证据证明 ProteinMPNN 设计 mask 覆盖三个 CDR，不代表实验结合、阻断、
表达、纯度、Kd 或 IC50。

## 3. 官方 Excel 文案修订

正式 Excel 保持官方 13 列，不增加内部列，并完成以下调整：

1. 删除“机制 Rank”，仅保留官方“推荐排序(Rank)”。
2. 将内部 blocker/seed/cluster 术语改写为评审可读中文。
3. 每条记录明确声明 0–100 分是内部归一化计算代理分，不是实验概率、
   BLI、表达量、纯度、Kd 或 IC50。
4. CDR identity 全部改为百分数。
5. 区分 RFantibody 新骨架/全新 CDR 与 fixed-pose 全新 CDR 两种从头设计。
6. 自检列增加长度、非法氨基酸、队内 CDR1/2/3 多样性、Cys、全序列
   N-糖基化 motif 的精确位置、融合硬冲突及内部开发性硬风险。
7. 模型依据列增加双构象一致性、开发性具体原因和融合兼容性窄范围预检查。

## 4. fixed-pose 谱系与全序列糖基化补充修订

对 15 条 `fixed_pose_mpnn` 候选保留“从头设计（全新 CDR 区）”分类，
理由是三条 CDR 均由 ProteinMPNN 全部重新设计，15/15 候选均有逐条生成
日志和 parent-CDR 对照证据。但正式设计说明不再笼统写成“经质量门控的
天然 VHH framework”，而是逐条披露：

- 保留的 framework 来自公开专利阳性 VHH；
- 使用的是该阳性 VHH 计算获得的 PVRIG 结合 pose；
- CDR1、CDR2、CDR3 均全部重新设计；
- 未直接沿用任何已知阳性抗体的完整 CDR。

当前 15 条的 framework/pose 来源为 `PVRIG-151/HR-151`、`151H7` 或
`PVRIG-38`，均在 Excel 的“设计说明”列逐条展示。

糖基化自检从“只看拼接 CDR 字符串”改为扫描完整 VHH 序列并定位 motif：

- Rank 26、32、34：明确写为 `NVT@58`，跨 CDR2/FR3 邻接区域；
- Rank 50：明确写为 `NLS@101`，位于 CDR3；
- 其余无 motif 候选写为“全序列 N-X-S/T motif=无”。

这项修订只改变风险披露文字，不改变任何序列、设计类型或推荐 Rank。

## 5. C 级候选

保留 Rank 45、49、50 作为高几何分但高开发风险的尾部储备，并在每条
Excel 记录中明确标注“不建议列入前10优先”：

- Rank 45：表面疏水斑块过大等风险；
- Rank 49：表面疏水、单域适配性及 instability 风险；
- Rank 50：CDR N-糖基化 motif。

它们不影响当前 Top10 推荐。

## 6. 候选替换与 Top10 决策

当前版本不静默替换候选，也不改变 Top10：

- Rank 50 是六条建议替换候选中风险最明确者；
- Rank 45、49 是开发性 C 级，应在存在同流程完整验证的 A/B 替补时优先
  替换；
- Rank 26、32、34 为 B 级且带完整序列 NVT motif，建议进入替补复核，
  但不能仅凭 motif 无验证换序列；
- Rank 10 只有 1 项 TNP 黄色警示，且保留独立的第 6 类接触模式，暂不建议
  下调；
- Rank 9 是 Top10 中更值得与 Rank 13/16 比较的候选，但目前没有独立
  affinity 证据证明 13/16 更优，因此未自动换位。

任何序列替换都必须重新走同一套四种子双构象 docking、static review、
官方 validator、阳性 CDR identity、队内矩阵、开发性、融合检查及冻结
哈希流程。

## 7. 最终核验

- Excel：50 条、13 列；
- 排名：严格为 1–50；
- Top10：`PVRIG_CAND_001–010`；
- 从头设计 27 条、优化改造 23 条；
- fixed-pose 三 CDR 全设计审计：15/15 PASS；
- 官方 validator：50/50 PASS；
- 下载文件与归档副本 SHA256 一致；
- 当前最终 Excel SHA256：
  `7e84590db5dfe0c9d89a27abb4f1cb3fb45a07c0d35d168fe246edbac4342ccd`。
- 15/15 fixed-pose 候选逐条披露公开阳性 framework/pose 来源；
- Rank 26/32/34 的边界 `NVT@58` 和 Rank 50 的 CDR3 `NLS@101` 已逐条
  写入自检列。
