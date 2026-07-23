# V2.19 C2 Top7500 发布闭合验证 V1

本包只验证已经冻结并完成的 C2 Top30K/Top7500 交付链，不重新打分、不改变排序、
不清理或恢复任何失败目录。

验证链为：

```text
Stage1 receipt + 30K hash
→ NBB2 staging receipt + manifest hashes
→ SHARD_PLAN + 32 manifests
→ 32 coarse-pose tables + FEATURE_RECEIPT
→ C2 32D receipt/table
→ V2.11 adapter receipt/predictions
→ final Top7500 receipt/TSV/FASTA/core/SHA256SUMS
```

只有候选集合、序列哈希、parent、PDB、target、模型、代码、特征顺序、输出哈希、
7500 配额和零 truth access 全部闭合时，才发布：

```text
status/C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json
```

任何失败均保持 fail-closed；本包不会删除、覆盖或原地修复冻结流水线的目录。
