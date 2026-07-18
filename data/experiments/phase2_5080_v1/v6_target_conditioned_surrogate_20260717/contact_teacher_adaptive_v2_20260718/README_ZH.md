# V4-H adaptive multi-seed contact teacher V2

## 目标

在不修改冻结的 Stage-1 extractor 的前提下，将 V4-H Stage 1/2/3 的独立双受体 docking 结果转换为候选级 residue-pair 与 VHH-residue marginal 软监督：

```text
每个 candidate / receptor / seed：Top-8 pose 先聚合
                         ↓
双受体共同成功 seed（intersection）再等权聚合
                         ↓
pair mean / population variance / std / uncertainty
VHH marginal mean / population variance / std / uncertainty
```

证据边界始终是 **computational docking geometry intermediate**，不是结合、Kd、竞争实验、实验阻断、Docking Gold 或提交证据。

## 为什么使用双受体共同 seed

最终 ranking 中有 64 个候选的两个 receptor seed-set 不对称，其中 25 个仍属于可分析 A/B/C tier。为了不把单受体额外 seed 静默混入双受体 teacher：

- A：123 个候选，使用共同 seeds `917,1931,3253`；
- B：241 个候选，使用共同 seeds `917,1931`；
- C：917 个候选，使用共同 seed `917`；
- NA：39 个 technical incomplete，不打开任何 result/pose，不做插补。

额外的单受体成功 result 会在 receptor state 中显式列为 `excluded_unpaired_seed_ids`，但 extractor 不打开这些 result 或 pose。

## 冻结聚合语义

- contact cutoff：4.5 Å，heavy-atom；
- 每 job：HADDOCK score 排序后的 Top-8，至少 4 poses；
- pose 权重：normalized `1/log2(rank+1)`；
- pair：成功共同 seed 内未出现的 union pair 是观测零；
- seed 权重：共同成功 seeds 等权；
- variance：population variance；
- uncertainty：`1/(1+4*variance)`；
- residue marginal：每个 pose 中某 VHH residue 是否接触任一 PVRIG residue，再做 pose-weighted、seed-equal mean；
- 技术 NA：candidate/receptor 数值字段为空，不使用 `NA` 字符串或数值 sentinel。

## 文件

- `src/extract_v4h_adaptive_multiseed_contact_teacher_v2.py`：主 extractor；动态导入并哈希绑定冻结 Stage-1 PDB/parser helpers。
- `src/reconcile_v4h_adaptive_terminal_v2.py`：Node23 只读 terminal/job-result metadata reconciliation；不打开 PDB。
- `tests/test_extract_v4h_adaptive_multiseed_contact_teacher_v2.py`：聚合、NA、asymmetric seed exclusion、byte determinism、multiprocessing 回归。
- `UPSTREAM_RECEIPT_RECONCILIATION_V2.json`：Node23 独立 closure sidecar（生成后同步）。
- `V4H_ADAPTIVE_MULTISEED_CONTACT_TEACHER_CONTRACT_V2.json`：pre-extraction freeze contract（生成后冻结）。
- `REMOTE_PREFLIGHT_V2.json`：Node23 预检部署/哈希证据。

## 当前执行边界

本版本当前只完成代码、测试、manifest 和只读 metadata preflight。领导审阅前不会启动对 3,536 个 paired-success jobs 的重型 PDB contact extraction。
