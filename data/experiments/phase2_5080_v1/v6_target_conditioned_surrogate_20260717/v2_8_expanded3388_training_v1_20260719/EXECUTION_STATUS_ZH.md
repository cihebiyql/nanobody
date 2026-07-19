# V2.8 扩展教师集：执行状态

更新时间：2026-07-19

## 已完成

1. 已核对 Node23 最新终态 V4-I：
   - Stage 1：3,924 jobs = 1,962 candidates × 2 receptors；
   - 3,921 jobs 成功，3 个 HADDOCK 技术失败；
   - 1,881 条候选具有完整双受体连续标签；
   - 81 条技术不完整，单独保留且未插补。
2. 已核对 Stage 2 重复：
   - 500 条候选，1,000 jobs；
   - 476 条形成双 seed，24 条保持单 seed；
   - Stage 2 是候选级标签覆盖，不重复增加样本数。
3. 已通过 V4-H/V4-I 协议语义兼容审计：固定受体、参考结构、hotspot、blocker rules、Docking/评分脚本一致；差异仅为 panel/job 数与 smoke candidate。
4. 已生成版本化 scalar teacher：
   - D0：旧 1,507；
   - D1：2,007（D0 + Stage 2 的500条）；
   - D2：3,388（D1 + 其余1,381条单-seed）；
   - 3,388 条 sequence SHA256 全唯一；
   - `Rdual = exact min(R8,R9)` 全部通过。
5. 已锁定旧 whole-parent outer fold；V4-I 继承同 parent 的既有 fold，未随机拆 sibling。
6. 构建器 3 项回归测试通过，`SHA256SUMS` 全部通过。

## 当前可训练规模

```text
3,388 条独立 VHH
6,776 个 receptor-specific scalar targets
1,066 条多-seed监督
2,322 条单-seed监督
31 个 parent clusters
```

V4-I 没有新增 parent cluster，因此主要增加已知 scaffold 内的 sibling/generator 覆盖，不等同于 unseen-parent 泛化提升。

## 当前下一步

1. 冻结旧 V2.7 sequence 模型在 V4-I 上的 pre-update 预测，保留 generator-shift 回放；
2. 对 D0/D1/D2 运行相同 whole-parent OOF sequence baseline；
3. 先比较 early enrichment，再决定是否将额外 1,381 条单-seed样本纳入主训练；
4. 在 Node23 物化 V4-I 的 126-D monomer features；
5. 从 raw Top-8 poses 提取 V4-I contact teacher，再训练 marginal/contact lane；
6. 最后用严格 cross-fit 的非负线性 stack/ElasticNet/浅层 GBDT 和 best-rank OR 组合筛选。

当前旧 V2.6/V2.7 launcher 对 1,269/1,507 行和旧 trust anchors 硬编码，不能直接复用；V2.8 必须另起 data/split/cache/trainer/launcher 版本。
