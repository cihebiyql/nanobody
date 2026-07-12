# PVRIG V2.5 实验预注册清单 - 2026-07-11

## 当前状态

- 计算筛选已完成：4/4 geometry 候选均有双基线导入记录。
- 冻结实验 panel 保持 24 条，不因计算排名增删。
- 24/24 当前均为 `PENDING_EXPRESSION_QC`。
- `preregistration_complete=false`，13 个实验室参数仍为 `null`。
- 结果 CSV 中只有排程/模板行，没有实验测量。
- 计算标签只表示几何优先级，不是 binder、blocker 或功能真值。

## 实验负责人必须填写的 13 项

以下值必须来自实际实验 SOP、仪器能力和实验负责人决策，不能从 docking、
校准对照、单元测试 fixture 或模型分数推断。

| 字段 | 当前值 | 冻结前所需依据 |
| --- | --- | --- |
| `binding_fit_qc_rule` | `null` | BLI/SPR 拟合 QC SOP |
| `binding_max_analyte_concentration_nM` | `null` | binding 浓度系列与仪器范围 |
| `binding_response_detection_rule` | `null` | 响应检出与背景扣除 SOP |
| `competition_effect_rule` | `null` | PVRIG-PVRL2 competition 判定规则 |
| `competition_max_analyte_concentration_nM` | `null` | competition 浓度系列 |
| `functional_effect_rule` | `null` | 功能 readout 判定规则 |
| `functional_max_analyte_concentration_nM` | `null` | 功能实验最高浓度 |
| `functional_viability_rule` | `null` | 功能实验活率 QC 规则 |
| `maximum_aggregation_fraction` | `null` | 聚集比例上限 SOP |
| `minimum_expression_yield_mg_per_l` | `null` | 表达产量下限 SOP |
| `minimum_functional_viability_fraction` | `null` | 最低可接受活率 |
| `minimum_purity_fraction` | `null` | 纯度下限 SOP |
| `minimum_sec_monomer_fraction` | `null` | SEC 单体比例下限 SOP |

## 冻结顺序

1. 实验负责人在
   `assays/pvrig_v2_5_prospective_v1/assay_preregistration.json` 中填写全部
   13 项，并记录对应 SOP/仪器/批次依据。
2. 在任何非 pending 测量或测量 payload 写入前运行：

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/freeze_pvrig_v2_5_assay_preregistration.py
```

3. 重新运行结果分析器，确认 package manifest、冻结状态和空白结果模板仍通过：

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python \
  experiments/phase2_5080_v1/src/analyze_pvrig_v2_5_assay_results.py
```

4. 保存预注册 JSON、冻结记录、SOP 标识和 SHA256；不得在看到测量结果后修改阈值。

## 实验执行顺序

1. 构建身份、表达、纯化和 SEC QC。
2. 对全部 24 条候选完成三个独立 binding run，覆盖至少两个 day block。
3. 仅对 verified binder 运行 PVRIG-PVRL2 competition。
4. 仅对 verified biochemical blocker 运行 functional assay。
5. 每个非 pending 调用必须提供独立 raw-data path 和 SHA256。

## 固定真值边界

- 表达失败或 assay failure 是 exclusion，不能自动标为 nonbinder。
- binding 不等于 blocking。
- 混合调用保持 `INCONCLUSIVE`。
- E6 行只进入人工 review；训练前仍需新的 V2.6 registry、split、seal、
  readiness audit 和 one-shot formal protocol。

## 实验负责人签署项

- 实验负责人：待填写
- 独立复核人：待填写
- SOP/仪器版本：待填写
- 预注册冻结时间：待填写
- 冻结产物 SHA256：待填写

