# Support V4-A 720 Full-QC 独立复验补充

结论：PASS_WITH_MEDIUM_METADATA_AND_SEMANTIC_CAVEATS，无 HIGH 问题。

- 720 条在 manifest、Fast、shortlist、Full 间 ID 集完全闭合；官方 validator、ANARCI、AbNatiV 均 720/720，Sapiens 原始 chunk 输出也是 720/720。
- hard_fail=False 仅表示通过冻结的 sequence hard gate：实际 single-domain suitability 为 good 389、borderline 223、poor 108；自动 SUBMIT=0。
- 原 prereg 的内嵌 frozen_at_utc=17:30Z 是错误元数据；不得作为预注册时间证据。真正的预执行证据是 17:23:38 implementation freeze 和 17:23:39 package receipt 对同一 prereg SHA 的闭合，早于 17:24:11 runner start。
- full_merged.tsv 将多个未运行通道写成非空默认常量。它们必须按 tnp_run=false、blocker_class=NOT_RUN 和本补充 receipt 显式屏蔽，不能作为 Docking surrogate、阻断标签或绝对 final_score 证据。
- 原 prereg、原 Full-QC 输出、阈值、候选集与科学结果均未修改，也不需要重跑。

持久证据：

- node1_evidence/status/PREREGISTRATION_TIMESTAMP_CORRECTION_V1.json
- node1_evidence/status/FULL_QC_UNRUN_CHANNEL_SEMANTICS_V1.json
- node1_evidence/outputs/INDEPENDENT_FIELD_SEMANTICS_REPLAY_V1.json

证据边界：这里只验证 sequence/developability Full-QC 的闭合和字段语义，不提供 Docking、结合、亲和力、竞争、实验阻断或生物学真值。
