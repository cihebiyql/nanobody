# PVRIG Final50：比赛 Top10 组合选择说明

日期：2026-07-25  
状态：`PROVISIONAL_COMPUTATIONAL_PRIORITY`；不改写冻结 `mechanism_rank`。

## 结论

原 Top10 priority 含两个 D3 高风险 151H8 衍生候选（Final50 rank 21、31）。考虑比赛实际只优先选择不超过 10 条进入实验，本版只保留一个 D3 作为格式/机制高风险哨兵，移除 Final50 rank 31，并以 Final50 rank 35 的 D1、PVRIG-38、不同 CDR3 cluster 候选替代。

本排序不是亲和力预测：无约束 Boltz/Chai 控制校准不能区分阳性与计算扰动对照；PRODIGY/FoldX/Rosetta/短 MD 也未通过候选级排名校准。因此优先级只使用冻结机制排序、D1/D2/D3 风险分层和亲本/CDR3 多样性。

## 推荐提交顺序

| 提交优先级 | Final50 mechanism rank | candidate_id | 制造风险 proxy | 组合角色 |
|---:|---:|---|---|---|
| 1 | 2 | `P1MCPUFP__CPUFP500K_0188__00519` | D1 | 首个低风险机制核心 |
| 2 | 6 | `P1MCPUFP__CPUFP500K_0100__00188` | D1 | HR-151 线独立 CDR3 核心 |
| 3 | 7 | `P1MCPUFP__CPUFP500K_0002__00919` | D1 | 第二个 HR-151 CDR3 核心 |
| 4 | 1 | `P1MCPUFP__CPUFP500K_0288__00659` | D2 | 机制最强但需制造复核 |
| 5 | 3 | `P1MCPUFP__CPUFP500K_0100__00092` | D2 | HR-151 线机制覆盖 |
| 6 | 4 | `P1MCPUFP__CPUFP500K_0090__00532` | D2 | 不同 CDR3 的机制备份 |
| 7 | 5 | `P1MCPUFP__CPUFP500K_0188__00282` | D2 | 第二层机制备份 |
| 8 | 28 | `P1MCPUFP__CPUFP500K_0032__00118` | D1 | PVRIG-38 parent 多样性锚点 |
| 9 | 35 | `P1MCPUFP__CPUFP500K_0029__00647` | D1 | PVRIG-38 的第二 CDR3 cluster 备份 |
| 10 | 21 | `P1MCPUFP__CPUFP500K_0091__00550` | D3 | 唯一 151H8 高风险格式/机制哨兵，不作为主力 |

## 明确未纳入 Top10 的旧候选

- `P1MCPUFP__CPUFP500K_0289__00496`（Final50 rank 31，D3）：151H8 线、single-domain suitability poor，且暴露非接触 acid-clipping 记录较多；降为 Final50 reserve。

## 必须保留的不确定性

- 50/50 候选都在 PVRIG `NTT@129` 潜在糖基化 anchor 的 10–20 Å 邻近范围内；无显式糖链、膜平面或真实 VHH-hFc 构建，因此此项不能用于候选间硬排序。
- Top10 的候选在提交前仍须以**精确 FASTA**重跑官方 validator、CDR novelty、队内多样性与文件哈希。
- 本表不是实际 BLI、Yield、纯度、Kd、IC50 或阻断活性证明；湿实验仍是唯一决定性证据。
