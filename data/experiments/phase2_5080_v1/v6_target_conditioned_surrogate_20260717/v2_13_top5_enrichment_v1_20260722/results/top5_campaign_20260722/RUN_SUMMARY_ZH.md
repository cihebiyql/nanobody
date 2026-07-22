# Top5 富集训练阶段总结（2026-07-22）

## 冻结评价边界

- 9,849 条 teacher，54 个 parent framework cluster，5 个 whole-parent OOF folds。
- 真阳性定义：独立双受体 Docking `R_dual_min` 的全体 top10%。
- 主指标：只保留模型排序 top5% 时的 enrichment factor。
- open development 与 frozen test 均未用于本轮训练和选择。

## 结果

| 方法 | EF@5% | Top5 命中数 / 493 | 结论 |
|---|---:|---:|---|
| V2.12 clean-attention baseline | 2.211 | 109 | 基线 |
| V2.13 L1 top-weighted Huber | **3.083** | **152** | 当前最佳，已按冻结规则晋级 |
| V2.13 L2 PairLogit 0.25 | 2.819 | 139 | Spearman 门失败 |
| V2.13 L3 PairLogit 0.50 | 2.900 | 143 | 合格但不如 L1 |
| V2.14 N1 ListMLE | 2.819 | 139 | MAE/单 fold 稳定性失败 |
| V2.14 N2 SoftTopK | 2.616 | 129 | MAE 失败 |
| V2.14 N3 mixed listwise | 2.941 | 145 | MAE/Spearman 失败 |
| V2.15 raw 126D+36D HGB R8/R9 | 3.083 | 152 | 未超过 L1 |
| V2.16 raw hard-negative reranker | 最高 2.961 | 146 | 未超过 L1 |
| V2.17 expanded-union reranker | 最高 3.002 | 148 | 未超过 L1 |
| V2.18 pose-aux nested Ridge | 2.414 | 119 | 严格双层 cross-fit，未超过 L1 |
| V2.18 pose-aux nested HGB2 | 2.961 | 146 | Spearman 提高但 Top5 未超过 L1 |

L1 在 top5% 预算下的 precision 为 30.83%，recall 为 15.43%。这已经能用于大库富集，但没有达到预期 EF=5。

## 关键诊断

- L1、V2.15-G3、N1/N2/N3 的 Top5 候选并集包含 346 个真阳性；如果能在并集中完美挑出 493 条，oracle EF5 约为 7.02。
- 因而问题不是“所有模型都找不到阳性”，而是现有 sequence/monomer/coarse-pose 特征不足以识别并集中的困难阳性。
- 全样本分类、hard-negative 分类、raw-feature HGB/ExtraTrees、ListMLE、SoftTopK 均未解决这个可分性问题；继续只调分类头或损失函数的预期收益很低。

## 正在运行

V2.13 L1 的 seed917/seed1931 三种子 whole-parent OOF 已恢复，输入缺失部署事故已经按 content hash 修复。当前因 Node1 上 RFantibody 150k 生成任务占用 GPU，冻结的 `>=18 GiB free` 门在等待；未降低资源门槛。GPU 释放后将自动执行：

```text
L1 seed917/1931 10 folds
→ 3-seed exact-min aggregate
→ C1 nested multimodal
→ hard-negative C1
```

## 下一步判断

1. 先完成 L1 三种子，检查 EF5 是否稳定高于单 seed 3.083。
2. 若三种子没有明显增益，停止在当前 9,849 条数据上继续枚举头部/损失。
3. 下一轮优先加入真正正交的信息：更多独立 Docking teacher、随机多 seed sentinel、候选级粗姿势/approach-angle 稳定性、receptor-specific contact-frequency，而不是再换一个树模型。
4. 生产筛选暂用 L1/三种子 ensemble + 多模型探索配额；它能富集，但不能宣称 EF5=5 已达成。

## V2.18 新证据

- 从 V29 release 的 primary seed917 Top-8 表物化了 6,872 条训练专用 pose 分解监督，包含 hotspot、occlusion、CDR3 contribution、geometry utility、A/B support 和 job consensus；输出哈希为 `f7a9f1614b7f26c1d4d16c67e02a64fb6814c94b09237a60bbf59a0294f30bd0`。
- 使用 5-fold outer + 4-fold inner whole-parent cross-fitting；outer-test 只读取 162 维 label-free monomer/coarse-pose，真实 pose 指标只在 outer-train 作为辅助标签。
- 全部 parent-overlap 审计为 0，open development 与 frozen test 访问均为 0。
- 最佳 pose-aux challenger 为 depth-2 HGB：146/493 hits，`EF5=2.9612`，Spearman `0.6088`；仍低于 L1 的 152 hits、`EF5=3.0829`。
- 结论：现有 label-free 162 维不足以稳定重建 pose 分解监督的 Top5 判别力；按冻结停止线，不再在相同输入上继续枚举融合头。
- 结果：`../v2_18_pose_aux_crossfit_v1_20260722/results/strict_oof_v1_1/`。

下一正交分支是 V4-H residue-contact 辅助监督：strict train 可用 1,169 条、478,191 residue-pair 行；必须保持 parent-fold cross-fit，且不得使用 frozen parent C0360 的 120 条有效序列。
