# V2.11 canonical10644 多模态开放开发集结果

日期：2026-07-21

## 数据与边界

- teacher：10,644 条；train 9,849，open development 795。
- split：whole-parent；train 54 parents，development 10 parents。
- 主目标：`R_dual_min = min(R_8X6B, R_9E6Y)`。
- frozen/sealed truth 未访问；结果仅表示独立双受体计算 Docking 几何代理，不是实验结合/阻断概率。

## 模态

- `S0`：ESM2-650M 序列 embedding + 理化特征。
- `M2`：VHH 单体结构 126D label-free 特征。
- `C2`：VHH 与固定 8X6B/9E6Y PVRIG 表面的 300-pose 低分辨率刚体扫描 36D，fold 内 PCA8。
- `M2+C2`、`S0+M2+C2`：只在 train inner whole-parent OOF 上拟合的非负凸融合。
- `GBDT`：浅层 challenger。

## 结果

`EF@5` = true Top10% 在预测 Top5% 中的富集；`EF@10` = true Top10% 在预测 Top10% 中的富集；`Recall@20` = true Top20% 在预测 Top20% 中的召回。

| 模型 | Rdual Spearman | MAE | EF@5 | EF@10 | Recall@20 | within-parent Top20 macro recall |
|---|---:|---:|---:|---:|---:|---:|
| C2 coarse-pose | 0.60852 | 0.037872 | 2.981 | 1.863 | 0.3899 | 0.3551 |
| M2+C2 | 0.66295 | 0.033724 | 2.733 | 2.733 | **0.4906** | 0.3173 |
| M2 structure | 0.65968 | **0.033153** | 3.230 | **2.981** | 0.4528 | 0.3204 |
| full9849 S0 3-seed ensemble | 0.63966 | 0.033432 | **3.727** | 2.609 | 0.4151 | 0.3010 |
| S0+M2+C2 | **0.66473** | 0.033373 | 3.230 | 2.733 | 0.4717 | 0.3461 |
| matched S0 single fit | 0.61476 | 0.034321 | 2.981 | 2.484 | 0.4151 | **0.3796** |
| shallow GBDT | 0.61019 | 0.034785 | 2.484 | 2.857 | 0.4403 | 0.2636 |

## 结论

1. 三模态融合得到最高整体相关性，`0.66473`，相对冻结 S0 ensemble 的 `0.63966` 有小幅但真实的开放开发集增益。
2. `M2` 的 MAE 最低且 EF@10 最高，单体结构是当前最稳定的新增模态。
3. `M2+C2` 在 20% 预算下召回最高：预测前 20% 找回真实前 20% 的 49.06%，随机期望为 20%，即约 2.45 倍富集。
4. S0 ensemble 在极早 Top5% 预算仍最好，说明扩大序列训练集对榜首筛选十分重要。
5. C2 单独不够强，但与 M2 组合后改善宽预算召回，表明 approach-angle 粗信息具有互补性。
6. 浅层 GBDT 没有形成一致优势，不作为默认生产头。

## 生产筛选建议

对 100,000 条序列不采用单一总分机械截断，而采用预算分层：

- 极高精度主通道：S0 ensemble Top 5%。
- 结构通道：M2 Top 10%。
- 宽召回通道：M2+C2 Top 20%。
- 对三个通道去重后，再以 `S0+M2+C2` 连续分数排序，并保留不确定性/多样性探索配额。

由于 M2/C2 需要单体结构，实际两级部署为：

1. 100,000 条先用 S0 做廉价预筛。
2. 对约 10,000–20,000 条生成/读取单体结构并计算 M2/C2。
3. 用多模型组合选出 1,000–3,000 条进入高成本 Docking。

## 可复现证据

- 本地：`results/canonical10644_multimodal_v1/`
- Node1：`/data1/qlyu/projects/pvrig_v2_11_canonical10644_multimodal_fusion_v1_20260721/training/canonical10644_multimodal_v1/`
- `METRICS.json` SHA256：`dcbcf876fbbf478372c047aa580abde9c6e71e57e2390d5fa01889969c24ef05`
- `SHA256SUMS` 全部通过。
