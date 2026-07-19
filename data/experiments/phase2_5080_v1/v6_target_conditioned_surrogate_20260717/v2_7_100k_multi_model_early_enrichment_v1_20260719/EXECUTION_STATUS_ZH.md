# V2.7 100K 多模型早期富集：执行状态

更新时间：2026-07-19

## 已完成

1. 已将生产目标从“选择唯一冠军模型”改为：

   ```text
   多模型共识 + 单模型救援 + 不确定性 + 多样性 + 随机 sentinel
   ```

2. 已完成 100K → 20K → 2K → Docking 的分层规划，见 `PLAN_ZH.md`。

3. 已在同一个 open outer0/inner0 score split 上完成第一版 M2/B/F0 审计：

   - 184 条、6 个 unseen parent clusters；
   - M2 Rdual Spearman 0.3066；
   - B seed43 Rdual Spearman 0.2630；
   - F0 三 seed Rdual Spearman 0.3173；
   - M2 与 F0 的预测 Spearman 0.8451，存在有限互补；
   - B 与 F0 的预测 Spearman 0.9246，头部更冗余。

4. 在真实 Top10%（19 条）上，第一版固定 tie-break 审计得到：

   - 预测 Top10%：M2 12 hits，F0 12 hits；
   - M2+F0 best-rank OR：13 hits；
   - raw M2/F0 Top10 union：21 条中 13 hits，Recall 68.4%；
   - B 加入该 union 未增加 hit。

5. within-parent Top20 第一版结果：

   - M2：Recall 37.5%，EF 1.65x；
   - F0：Recall 36.1%，EF 1.58x；
   - M2+F0 rank mean：Recall 49.3%，EF 2.17x。

这些只是 6 个 parent 的 open-development 证据，尚不足以发布正式融合器。

## 已完成的追加对照

1. Node1 已完成 B seeds 97/193，与 seed43 构成 matched 三 seed 对照：

   ```text
   runtime:
   /data1/qlyu/projects/pvrig_v2_6_b_matched_seeds_runtime_v1_20260719

   seed97: PASS, 544 optimizer steps
   seed193: PASS, 544 optimizer steps
   V4-F/test32 / outer truth / outer metrics access: 0 / 0 / 0
   ```

   matched B3 的初步 Rdual Spearman 为 0.2983，F0 三 seed为 0.3173；matched 增量约 0.019，而不是此前拿 B 单 seed比较时的 0.054。

   更关键的是，B3 与 F0 在 true Top10%/Top20%、predicted Top5%/10%/20% 的 hit、Recall 和 EF 全部相同。因此当前 fold 不能证明 contact 监督改善了 early enrichment。

2. early-enrichment collector 已通过，并新增 tie-aware 统计、`ceil` 主计数和 `floor` 敏感性审计。

3. 已建立独立 contact-ablation implementation copy，用于：

   ```text
   marginal-only
   pair-only
   combined
   ```

   V1.4 首次 CUDA smoke 因 package 缺少 immutable delta-noise vendor artifact 而 fail-closed；失败 runtime 和日志已保留，未覆盖。V1.4.1 只修复依赖闭包，不改变科学协议，并已完成两个 CUDA smoke：

   ```text
   marginal-only: PASS, 68 optimizer steps
   pair-only: PASS, 68 optimizer steps
   V4-F/test32 / outer truth / outer metrics access: 0 / 0 / 0
   ```

## 已完成的 contact 消融终态

V1.4.2 六个完整任务全部 PASS：

```text
marginal-only × seeds 43/97/193
pair-only × seeds 43/97/193
每项 8 epochs / 544 optimizer steps
V4-F/test32 / outer truth / outer metrics access: 0 / 0 / 0
```

结果：

| Variant | Rdual Spearman | within-parent Top20 EF |
|---|---:|---:|
| B 三 seed | 0.29837 | 1.582 |
| F0 combined | 0.31726 | 1.582 |
| marginal-only | **0.32455** | 1.582 |
| pair-only | 0.31510 | **1.341** |

四者在所有 global Top5/10/20 hit、Recall 和 EF 上完全相同。contact 监督改善了中段连续排序，但没有改善本 split 的早期富集。下一轮保留 marginal-only challenger，暂停 pair-only 扩张。

## 已完成的 Stage 0 sequence-only 基线

严格使用 outer0/inner0 whole-parent split（1085 train / 184 score），输入只包括 ESM2-650M、ESM2-3B 序列表征和序列/CDR 理化特征；不读取候选单体结构或 Docking pose。

关键结果：

- Ridge ESM2-650M：Rdual Spearman 0.4255；
- Ridge 650M+3B：predicted Top10% 找回 true Top10% 的 12/19，Recall 63.2%，EF 6.12x；
- ElasticNet：predicted Top20% 找回 true Top10% 的 16/19，Recall 84.2%，EF 4.19x；
- 浅层 MLP 失败，Rdual Spearman -0.0147；未经校准的普通均值集成被 MLP 污染，不得使用；
- within-parent EF 约 0.9–1.2x，主要信号仍来自跨 parent/scaffold。

## 已完成的 100K label-free 选择器原型

合成 100,000 → 20,000 选择器 smoke：

```text
PASS
wall time: 3.60 s
peak RSS: 439,484 KB
20,000 candidate IDs 全唯一
固定通道配额: 14000/2000/1600/1400/1000
all label/sealed access: 0
```

该速度只表示已有模型分数表上的选择器吞吐，不包含 ESM embedding 和模型推理时间。

## 当前运行状态

上述相关 Node1 训练均已完成，无相关训练进程在运行；GPU 1–7 均已释放。GPU0 有约 19.8 GB 静态占用但利用率为 0，且不是上述训练进程。

## 新发现的评估风险

B/F0 输出存在较多相同分数：

- B seed43：184 行仅 23 个 unique score，最大 tie 36；
- F0 ensemble：184 行仅 67 个 unique score，最大 tie 9。

因此固定 TopK 必须显式处理 cutoff tie，避免指标随未声明的排序规则变化。此前 F0 Top5 出现的 6 与 7 hits 已经复核，直接原因不是 boundary tie，而是正例集合和预测预算分别使用 `floor` 或 `ceil` 的整数化约定不同：本版统一使用 `ceil/ceil`，即 true Top10%=19 条、predicted Top5%=10 条，F0 命中 7 条；若 true Top10% 使用 `floor=18`，则命中 6 条。

正式 collector 必须同时输出：

```text
固定 candidate_id tie-break 结果
true-positive 和 prediction budget 的 floor/ceil 约定
cutoff tie 大小和需要抽取的槽位
tie-aware pessimistic / expected / optimistic hits
必要时包含完整 boundary tie 的扩展预算结果
```

在 tie-aware 审计完成前，任何单个 Top5/Top10 hit count 都只能视为初步结果。

## 下一停止点

本轮开发阶段的下一停止点是同时获得：

1. 将 B3、marginal-only、M2、Ridge/ElasticNet 扩展到其余 open whole-parent folds；
2. 用严格 cross-fit 而非 raw mean 训练融合/配额模型；
3. 重点验证 global early enrichment 是否能转化为 within-parent/sibling enrichment；
4. 在真实 100K 候选表上测量 ESM embedding、模型推理和选择器完整吞吐；
5. 冻结下一轮 Docking 的 exploitation、disagreement、diversity 和 random sentinel 配额。

V4-F/test32 和 formal outer-test truth 在这些开发选择冻结前继续 sealed。
