# PVRIG 下一阶段执行顺序：先补足 10k Docking 教师，再启动正式 500k 序列库

更新日期：2026-07-19

## 决策

正式 50 万条序列库暂不作为第一步。当前优先级是：

```text
冻结并训练现有 3,388 条基线
  -> 生成约 10 万条探索性候选池
  -> 按信息价值选择约 7,000 条
  -> 完成同口径双受体 Docking
  -> 形成约 10,000 条有效教师标签
  -> 重训和验证筛选模型
  -> 再生成正式 500,000 条序列库
```

原因：当前 3,388 条监督数据只有 31 个 parent clusters，新增 V4-I 又主要来自既有 11 个 parent。如果现在直接生成 50 万条，很可能只是把当前 scaffold 偏差和当前模型偏好放大。先补一轮有针对性的 Docking，才能校准正式 500k 的生成配比和筛选器。

## 阶段 0：冻结当前基线

输入：当前同口径 `open3388` 数据。

执行：

1. 对 D0=1,507、D1=2,007、D2=3,388 使用相同 whole-parent split 训练 sequence baseline；
2. 比较 parent-held-out 和 within-parent early enrichment；
3. 冻结模型、预测、split、训练配置和 hash；
4. 建立 parent-only、CDR3-length-only shortcut baseline。

停止条件：只有在 unseen-parent 和 within-parent 指标均有可解释结果后，才允许该模型参与 7,000 条 acquisition；模型分数不能作为唯一选择依据。

## 阶段 1：探索性序列池，不是正式 500k

先生成约 100,000 条 raw sequences。该批次用于构造 Docking 教师集，可以迭代，不作为最终参赛库。

建议来源：

| 来源 | 比例 | 目的 |
|---|---:|---|
| 天然 VHH framework 上的保守 CDR redesign | 35% | 提高可开发性和新 parent 覆盖 |
| ProteinMPNN/AntiFold fixed-backbone 或局部设计 | 25% | 利用结构条件 |
| RFantibody/表位条件化设计 | 20% | 扩展结构与表位机制 |
| fixed-pose interface redesign | 10% | 构造局部排序和反事实 |
| 激进 de novo/latent 探索 | 10% | 扩大分布外覆盖 |

生成约束：

- 至少 60–100 个 parent clusters；
- 单个 parent 不超过 raw pool 的 3%；
- CDR3 14–20 aa 均覆盖；
- A_CENTER、B_LOWER、C_CROSS 均保留；
- H3-only、H1+H3、H1/H2/H3 平衡设计均有覆盖；
- 完全序列去重，近 CDR3 聚类；
- 与已知阳性任一 CDR identity <80%，正式候选尽量 <75%。

## 阶段 2：快速 QC 和 7,000 条 Docking panel

100k raw pool 先经过：

```text
字符/长度/编号/FR-CDR完整性
  -> 明显异常 Cys、严重疏水串等 hard gate
  -> pI、charge、GRAVY、instability、liability
  -> AbNatiV 和可开发性软排序
  -> 当前 Docking surrogate 的分数/不确定性
```

不要只选当前模型 Top。建议最终 7,000 条：

| acquisition lane | 比例 | 数量 | 作用 |
|---|---:|---:|---|
| 高分 exploitation | 30% | 2,100 | 提高好 Docking 候选密度 |
| matched hard negatives / counterfactuals | 30% | 2,100 | 防止模型只学 scaffold/长度 |
| 新 parent、CDR 和方法多样性 | 25% | 1,750 | 提高泛化 |
| 模型分歧/高不确定性 | 10% | 700 | 主动学习决策边界 |
| 突变阶梯和机制对照 | 5% | 350 | 提供局部因果和排序监督 |

额外约束：

- 至少 50% 来自当前 31 个以外的新 parent；
- 单个 parent 不超过 5%；
- 每个高分 lineage 都必须配套相同 parent、相近长度和 QC 的反事实负例；
- 保留约 10–15% 模型低分但 QC 合格的随机 sentinel；
- acquisition 前冻结 candidate manifest，不能看 Docking 结果后换样本。

## 阶段 3：补足约 10k 同口径 Docking 标签

当前严格同口径可用标签约 3,290 条。为了最终得到约 10,000 条有效标签，首轮建议提交 7,000 条，而不是只提交 6,000 条。

### 第一 seed：全部 7,000 条

```text
8X6B 独立 Docking × seed917
9E6Y 独立 Docking × seed917
= 14,000 jobs
```

禁止用 8X6B pose overlay 冒充 9E6Y 独立 Docking。

### 第二 seed：分层 1,500 条

```text
1,000 条：按首 seed score decile 分层随机
250 条：高分候选
250 条：边界、模型分歧或高不确定候选
```

增加双受体 seed1931，共 3,000 jobs。

### 第三 seed：300 条

覆盖高分、高 seed dispersion、机制对照和模型分歧候选，增加 seed3253，共 600 jobs。

候选 Docking jobs 总量约 17,600；另行运行 protocol controls，但 controls 不进入训练行。

按既有约 95%–96% 的有效 paired-label 率，7,000 条预计产生约 6,700 条新有效标签，与当前约 3,290 条合并后接近 10,000 条同口径教师。

## 阶段 4：训练约 10k 教师模型

模型名称必须是：

> sequence-to-docking / blocker-like geometry surrogate

不能命名为实验阻断概率模型。

主要任务：

1. 分别预测 R8 和 R9；
2. `Rdual = exact min(R8, R9)`；
3. 辅助预测 receptor gap、seed dispersion、技术失败概率和界面几何分量；
4. 对 matched counterfactual 使用 within-parent pairwise ranking loss；
5. 使用 ensemble disagreement 或 heteroscedastic uncertainty。

数据划分必须按 parent framework cluster、近 CDR3 family 和生成批次分组。禁止把 sibling 随机拆入训练与测试两侧。

升级条件：

- parent-held-out EF/Recall 明显优于 parent-only baseline；
- within-parent enrichment 不下降；
- 多个训练 seed 方向一致；
- 新 parent 和新 generator challenge 有有效富集；
- 预测不确定性能够识别高误差样本。

## 阶段 5：正式 500k 序列库

只有约 10k 教师模型完成冻结验证后，才启动正式 500,000 条生成。

正式漏斗建议：

```text
500,000 raw sequences
  -> 去重、CDR相似度、编号与 hard QC
  -> 约 100,000–150,000 条
  -> binding prior + 可开发性/表达纯度风险 + sequence Docking surrogate
  -> 约 30,000–50,000 条
  -> 结构预测/M2/contact 模型
  -> 约 5,000–10,000 条
  -> 约 5,000 条正式双受体 Docking
  -> 多 seed 复核和最终多目标排序
```

不建议给 50 万条全部预测高精度结构；sequence 模型应先承担主要降采样，再把 GPU/CPU 结构和 Docking 预算投向前 3–10 万条或更小短名单。

## 当前立即执行项

1. 完成 `open3388` 的 D0/D1/D2 baseline 训练和冻结；
2. 冻结 100k 探索池生成配方和 provenance schema；
3. 生成 100k 探索池并完成 fast QC；
4. 按五条 acquisition lane 冻结 7,000 条 Docking manifest；
5. 再启动 Node1/Node23 分片 Docking。

因此，当前不是在“50 万生成”和“10k Docking”中二选一；正确顺序是：

> **先用约 10 万条探索性生成池服务于 7,000 条信息密度高的 Docking 扩充，得到约 10k 教师后，再做正式 50 万条。**
