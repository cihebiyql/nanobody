# Top150K B-only V3 技术恢复

## 原因

旧 V2 恢复已经成功生成并验证 Graph 与 L1，但 B 四种子在真正推理前被通用
V2.19 适配器拒绝：V2.11 checkpoint 的 schema 不在通用允许表中。四个权重的
架构、配置和 state signature 与当前 `OrthogonalTargetHead` 严格兼容。

## V3 的最小修复

V3 **不修改通用适配器**，也不把 V2.11 schema 全局放开。独立 wrapper 只有在
四个 checkpoint、四个训练 RESULT、seed、split、backbone、head config、state
signature、输入防火墙和 frozen-test=0 全部符合冻结 profile 时，才在本次调用的
作用域内临时允许该 schema。退出时恢复原允许表。

V3 只重跑 B：现有 Graph 与 L1 先做全量闭合并记录 hash，推理完成后再次验证
hash 未变化。150,000 行、有限值、exact-min、candidate/sequence/parent/order、四权重
provenance 和零 truth/Docking/contact 访问全部通过后，才原子发布 canonical terminal。

## 当前状态

本目录仅完成本地实现、测试、预注册和冻结，**没有启动 Node1 远端恢复**。
