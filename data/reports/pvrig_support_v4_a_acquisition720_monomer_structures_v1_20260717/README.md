# Support V4-A 720 单体结构预计算 V1

该版本在 Node1 SSD 上对冻结的 720 条 Full-QC hard-pass 序列执行：

- 全 720 条 NanoBodyBuilder2 primary；refined 失败时仅允许一次明确记录的 unrefined fallback；
- 全 720 条 IgFold crosscheck，固定全集而非按结构结果抽样；
- 4 张 GPU（0–3）× 每 worker 8 CPU threads，总上限 32/64 CPU 与 4/8 GPU；
- 无替换、无插补、无 docking、无模型分数、无 geometry 或实验标签访问。

远程根：

`/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_monomer_structures_v1_20260717`

本目录仅保留轻量代码、冻结契约、输入闭包和启动证据；不得复制 PDB、模型缓存、运行日志全集或其他大体积 runtime 输出进 Git。

## 精确 allowlist 建议

只建议 allowlist：

- `README.md`
- `DEPLOYMENT_RECORD.json`
- `prepare_and_run_support_v4a720_structures.py`
- `test_prepare_and_run_support_v4a720_structures.py`
- `launch_node1_support_v4a720_structures.sh`
- `LOCAL_TEST_RESULTS.log`
- `node1_evidence/PREREGISTRATION.json`
- `node1_evidence/audit/{IMPLEMENTATION_FREEZE.json,PRELAUNCH_HASH_CLOSURE.json,STARTUP_RUNTIME_RECEIPT.json,LIGHTWEIGHT_CONTRACT_FILES.txt,LIGHTWEIGHT_CONTRACT_SHA256SUMS,prelaunch_tests.log}`
- `node1_evidence/status/{prepared.json,zero_work_preflight.json,launch_receipt.json}`
- `node1_evidence/inputs/support_v4a720_structure_manifest.tsv`
- `node1_evidence/upstream/{full_qc_terminal_summary.json,terminal_process_closure_v1.json}`
- `SHA256SUMS`

继续忽略所有 `*.pdb`、cache、remote runtime logs、candidate terminal records 与模型文件。

## Terminal result

Node1 completed all 720 frozen candidates. Independent closure validation confirmed 720/720 NanoBodyBuilder2 successes, 720/720 IgFold successes, 23 explicitly recorded NBB2 unrefined fallback successes, exact candidate/sequence-hash closure, 1,440 regular non-symlink PDB hash matches, zero replacement, runner return code 0, and no remaining runner/resource-monitor process.

Lightweight terminal evidence is in `node1_evidence/status/structures.complete.json` and `node1_evidence/status/TERMINAL_VALIDATION_V1.json`. PDB files and runtime logs remain remote-only and are not Git-allowlisted.
