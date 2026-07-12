# 1,000 条 FR4 修复后 QC 的完成范围

该 cascade 已完成本流程需要的 sequence-QC 证据：

- 1,000/1,000 通过 fast hard gate。
- 300/300 full-QC shortlist 无 hard-fail。
- 300 条共同为 `REVIEW_DEVELOPABILITY`，原因均为固定 `h-NbBCII10` scaffold 的 `not_vhh_like;hydrophobic_run`。
- 其余 700 条为 `full_qc_excluded_due_cap`，表示容量延后，不是生物学阴性。

父进程在 full merge 完成后被主动终止，因为剩余工作只是对 150 条 geometry pool 做约 33,525 次 CDR pair MUSCLE alignment。该全局 diversity 不能改变已经由 RFantibody backbone pose 审计冻结的 78 条 RF2 primary 候选，且会持续占用共享 node1 CPU。

因此，后续使用独立的 `qc/rf2_primary_78_full` 对 78 条 pose-primary 候选做无容量截断的定向 full QC。全局 cascade 不得被标记为完整 finalize run，也不得把 700 条 capacity-deferred 解释为失败。

