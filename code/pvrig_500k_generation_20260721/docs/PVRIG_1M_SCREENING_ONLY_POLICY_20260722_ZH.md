# PVRIG 100 万 VHH：筛选库目标修正（2026-07-22）

## 目标

本批 1,000,000 条 VHH 是**生产筛选候选池**，不是新增 Docking 训练集。

- 不再为了训练分布主动保留低分、决策边界或随机负例配额。
- 不再把本批候选划分为 train/dev/test。
- 不再为训练模型新增 Docking 标签。
- 后续使用此前约 10,000 条同协议 Docking 数据训练得到的冻结 surrogate，对本批候选做全量推理。
- surrogate 预测的是 PVRIG 固定靶点双构象计算阻断样几何，不是实验结合、Kd、IC50 或真实阻断概率。

## 当前计算如何处理

当前 CPU 700k 与 GPU 300k 计算继续执行，不删除、不重跑：

1. 现有五条生成路线构成 1M **proposal pool**；路线配额仅用于保证原始候选来源覆盖。
2. ANARCI、DeepNano、NanoBind、Sapiens、AbNatiV、NBB2、TNP 继续作为全量 QC/弱先验。
3. CPU 规则生成路线不被保证进入最终 shortlist；只有 surrogate 和 QC 表现足够好才保留。
4. 最终 shortlist 不维持 400k/200k/100k/150k/150k 路线比例，也不保留训练对照配额。

## Docking surrogate 全量推理合同

模型团队交付必须包含：

- `MODEL_READY.json`
- 冻结模型文件及 SHA256
- 训练数据集 SHA256、Docking 协议 SHA256、特征 schema SHA256
- 适用于 1M 候选的批量推理入口
- 每条候选至少输出：
  - `candidate_id`
  - `sequence_sha256`
  - `monomer_pdb_sha256`
  - `predicted_R8`
  - `predicted_R9`
  - `predicted_Rdual`
  - `prediction_uncertainty`
  - `ood_score`
  - `model_id`

必须验证：

- 1M candidate ID 集合精确闭合；
- sequence SHA256 精确闭合；
- 单体结构 SHA256 与 NBB2 发布表精确闭合；
- `MODEL_READY.json` 绑定 8X6B、9E6Y、PVRIG 位点 mask/prompt 和特征 schema 的 SHA256；
- 所有预测为有限数；
- `predicted_Rdual = min(predicted_R8, predicted_R9)`；
- 不把技术失败或缺失预测填成低分；
- 模型训练数据不得混入当前 1M 推理候选的未来 Docking 结果。

## 筛选漏斗

1. **1,000,000 proposal pool**：完成严格 ID、序列、生成来源和哈希闭合。
2. **硬门控**：ANARCI PASS、NBB2 SUCCESS、TNP PASS、比赛 novelty gate PASS。
3. **全量 surrogate 推理**：以保守预测值（如 `predicted_Rdual - uncertainty_penalty`）排序。
4. **Top 100k**：模型主筛；不保留低分训练对照。
5. **Top 20k–50k**：结合 AbNatiV/Sapiens、表达纯度风险、DeepNano/NanoBind 弱先验做 Pareto/次级排序。
6. **Top 5k**：进入冻结双构象 Docking 做最终计算验证，而不是用于重新训练本轮模型。
7. **最终组合**：Docking blocker-like geometry 为主，结合弱先验、可开发性与家族多样性为辅。

主排序采用冻结验证集上预注册的保守分数，例如
`predicted_Rdual - lambda * prediction_uncertainty`；`lambda` 必须由训练模型的冻结验证结果确定，不能查看本批候选后再调参。DeepNano/NanoBind、AbNatiV/Sapiens 和表达纯度风险不覆盖 surrogate 主分数，而作为硬风险排除、Pareto 维度或同分候选的次级排序。

## 防止单一家族坍缩

筛选以 surrogate 高分为主，但应设置宽松的多样性上限：

- 单一 parent/framework cluster 不超过 Top5k 的 3%；
- 单一 near-CDR3 family 不超过 Top5k 的 1%；
- 完全重复序列为 0；
- 若达到上限，则选取下一条高分候选，而不是保留随机低分对照。

## 生成路线富集审计与补充生成

100 万推理完成后，按每条生成路线报告：

- QC、ANARCI、NBB2、TNP 通过率；
- surrogate 分数和 uncertainty/OOD 分布；
- Top1%、Top5%、Top10%、Top100k、Top20k、Top5k 的相对富集；
- parent/CDR3 family 集中度；
- 结合弱先验和可开发性 Pareto 前沿占比。

如果 RFantibody/fixed-pose ProteinMPNN 在 Top5% 与 Top10% 均稳定显示明显更高富集，而 CPU 规则路线在高分区贡献很低，则启动额外 target-conditioned reserve generation。新增 reserve 与原 1M 使用完全相同的 QC、NBB2、TNP 和 surrogate 推理流程，再按分数竞争进入 shortlist；不为了维持旧路线比例保留低分 CPU 候选。

补充生成只由冻结的路线富集报告触发，不能根据人工挑选的个别高分序列临时改变规则。

## 当前旧模型边界

仓库中的 V2.7 Stage0 模型是早期小规模 open-development 原型，不能冒充用户指定的约 10k Docking 冻结模型。正式 1M 筛选必须等待并验证新的 `MODEL_READY.json` 与模型/训练集/协议哈希后才启动。
