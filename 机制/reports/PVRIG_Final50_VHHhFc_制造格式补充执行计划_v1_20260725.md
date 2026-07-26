# PVRIG Final50：VHH-hFc 制造与格式补充执行计划 v1

- 日期：2026-07-25
- 输入：`common4_rerank_v2_20260725/final50/final50_ranked.tsv`；每条候选 4 seed × 2 构象的 400 个代表 HADDOCK 复合物。
- 输出：`/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/final50_vhhfc_developability_v1_20260725/`
- 不改变：现有四 seed、双构象 blocker 几何主排序；不将计算 proxy 翻译成 CHO Yield、SDS/HPLC 纯度、BLI、Kd 或 IC50。

## 资源与安全边界

- Node1 CPU：最多 32 逻辑核。
- Node1 GPU：最多 GPU 0–3；不占用已在运行任务的 GPU 4–7。
- 所有新输出写入 `/data`；`/data1` 剩余空间过低，不写入。
- 任何新分数均为制造/格式侧车字段，不能伪装成实验得分。

## 执行顺序

### P0-A：TNP 证据补齐（Final50）

1. 从 Final50 审计表识别 TNP 六分量缺失候选。
2. 使用已部署 TNP 批量重跑，保存原始 JSON 和提取表。
3. 记录 `tnp_component_evidence_completeness`；缺失或失败只标 review，不因此删除候选。

### P0-B：结构制造侧车（Final50 × 8 pose）

在每条候选 8 个代表复合物中，计算：

- VHH 游离和结合态近似 SASA；
- 表面疏水 patch、正/负电荷 patch；
- CDR 的 DG/DS/DD/DT、DP、M/W 位点；
- motif 暴露、PVRIG 接触频率、结合遮蔽程度；
- C 端连接方向与抗原/复合物最小距离。

使用跨 pose 的中位数与范围；任何 motif 仅作风险复核，不为 hard fail。

### P0-C：格式几何预审（Top10）

- 先对现有 8 pose 检查 C 端可达性和 Fc/linker 可能受限区域。
- 官方 PDF 仅定义 VHH-hFc，未定义 hinge/linker/Fc 的精确序列；因此先建立通用 human-IgG1-hFc 情景输入。
- 使用 Chai-1/Boltz-2 先做 Top2（D1 #2 与 D3 #10）试运行；仅当输出结构完整、模型质量可用时扩展 Top10。
- 输出只能标记为 `generic_hFc_scenario`，不得替代主办方固定构建的真实验证。

### P1：整合与组合决策

- 保留 `mechanism_rank`，新增 `manufacturability_tier`、`format_review_status`、`ptm_review_status`。
- 生成 Pareto 分层：机制核心、机制多样性、制造复核、高风险格式对照。
- 输出分层，不生成未经校准的“预测官方分数”。

## 成功标准

- Final50 TNP 六分量有可追溯 PASS/REVIEW/FAILED 记录。
- Final50 每条均有 8 pose 的结构侧车结果与完整性审计。
- Top10 有格式预审；若通用 hFc pilot 不可信，记录技术边界而不强行扩展。
- 所有表均保留输入/参数/hash/claim boundary。
