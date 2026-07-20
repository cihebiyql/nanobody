# V29 open same-seed snapshot 审计摘要

## 冻结结果

冻结时刻：`2026-07-20T08:52:13.626517+00:00`

| 项目 | 数量 |
|---|---:|
| V29 候选总数 | 9,934 |
| 冻结时已产生 `job_result.json` | 4,469 |
| 严格同 seed 双受体 train 候选 | 421 |
| 严格同 seed 双受体 development 候选 | 83 |
| open 可训练/开发候选合计 | **504** |
| frozen_test 严格同 seed 双受体候选 | 197（仅计数） |
| open 配对 job provenance 行 | 1,118 |
| open scorer technical-invalid job | 63 |

open 可靠性层级：

- `DUAL_1_SEED`: 459
- `DUAL_2_SEED`: 35
- `DUAL_3_SEED`: 10

## 与 3,388 条旧 teacher 的关系

- sequence SHA overlap：0
- candidate ID overlap：0
- 原始 open 合并规模：`3388 + 504 = 3892`
- V29 当前 open 覆盖 52 个 parent，其中 35 个是旧 teacher 未覆盖 parent
- V29 train 为 421 条，development 为 83 条

当前严格 open 数据尚未达到 4,000 条。不能通过加入 197 条 `frozen_test` 来凑数。
Docking 继续完成后，应另起不可变 snapshot；不得更新本目录内的已冻结输出。

## Split 边界

本 snapshot 仅输出：

- `train` 标签；
- `development` 标签；
- open candidate split manifest；
- open paired-job provenance。

`frozen_test` 只输出总数和 seed-tier 计数：

- 标签输出：0
- candidate ID 输出：0
- sequence 输出：0
- parent ID 输出：0

后续合并 D0 时，任何与 V29 `frozen_test` parent 重合的旧行都必须从 fit 中排除。该排除应在能读取 sealed split 的独立 merger 内完成；本 snapshot 不泄露 frozen parent ID。

## 监督定义

只有同一 seed 的 8X6B 和 9E6Y 均成功，才纳入该 seed：

```text
paired_seeds = successful_8X6B_seeds intersection successful_9E6Y_seeds
R8 = median(score_8X6B over paired_seeds)
R9 = median(score_9E6Y over paired_seeds)
Rdual = exact min(R8, R9)
```

V29 的固定 scorer、`run_job.py`、参考结构、hotspot 文件及 blocker rules 与 V4-H/V4-I 字节一致，兼容状态为：

```text
PASS_BYTE_IDENTICAL_TO_V4H_V4I_FIXED_SCORING_COMPONENTS
```

## 验证证据

- 冻结单元测试：6/6 PASS
- `SHA256SUMS`：全部通过
- receipt SHA256：`f6fad4161e60f9c929b5d0964b89c9aa234bad83723e4c8054827e093c1d3b9f`
- SHA256SUMS SHA256：`8372983ec62710104df9b5c2e679bde2266f734efed63898713eb825d5f3112e`

边界：这些标签仅表示 active-campaign computational Docking geometry，不代表结合、亲和力、竞争、实验阻断或 Docking Gold。
