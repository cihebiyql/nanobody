# PVRIG V4-H QC96 prospective/formal 权威退役记录

**日期：** 2026-07-17  
**性质：** 回顾性 authority retirement / supersession；不修改原始 prereg、manifest、receipt 或运行态  
**状态：** `RETIRED_V4_H_QC96_PROSPECTIVE_FORMAL_AUTHORITY_RETAINED_DEVELOPMENT_RESEARCH_ONLY`

## 结论

V4-H QC96 的 96 条序列仍是完整、可追溯的 label-free QC 交付，但已经不能继续充当 untouched prospective/formal Docking holdout：Node23 research Docking 在任何 H96 prediction freeze 之前启动，且 QC96 与运行候选池、Stage-1 候选均为 `96/96` 交集；审计快照时至少已有一条 H96 候选的 8X6B 和 9E6Y 作业完成。

因此本记录只改变**权威解释**，不改任何原始文件：

- `prospective authority = retired`；
- `formal holdout authority = retired`；
- `untouched Docking holdout = false`；
- QC96 可保留为明确版本化的 post-hoc development/research computational geometry data；
- 不得据此宣称 prospective performance、binding、Kd、competition、experimental blocking 或 Docking Gold；
- V4-D test32 不受本次退役影响，继续 `SEALED_UNTOUCHED`。

## 关键证据

### 1. 原始 H96 交付保持不变

| 文件 | SHA256 |
|---|---|
| `qc96_manifest_v1.tsv` | `f128f7b2389ea5e9887b931460332ce42898aece0314e7320975c204a692f723` |
| `qc96_selected_source_provenance_v1.tsv` | `e64317b9ff7b68b1dbaf8ece55fb8d051644c36b875e7f3bd28253d50fa65dc4` |
| `qc96_receipt_v1.json` | `a28a4a419c91c4d4f73b5d9088d114b6fb427cede0d10eb0ba8856a488bb912d` |

Manifest 仍为 96 行、96 个唯一 candidate ID，原始 `model_split` 仍是 `V4_H_QC96_PROSPECTIVE_HOLDOUT`。本次没有修改它；该字符串现在只记录原计划身份，不再赋予 prospective/formal 权威。

### 2. 事前兼容性审计没有产生预测冻结

兼容性审计：

```text
PVRIG_V4_H_QC96_DEV1_PREDICTION_ADAPTER_COMPATIBILITY_AUDIT_20260717_ZH.md
SHA256 = ace16206654a962cc5d5d10f25b6f8be831d654c9f428e74a9f49faddb8f0320
```

其结论是当前 DEV1 sequence-only model 与原 formal contact-model 契约不兼容，只能另建 DEV-only prediction version；该审计本身没有创建 H96 predictions。

### 3. Node23 已经先启动 Docking，并消费全部 H96

回顾性 research audit：

```text
phase2_v4_h_research_dual_docking_v1_retrospective_governance_audit_20260717.json
SHA256 = 1960432625f8cb1c6ca4fdc2e9f267b718689e13f81464bafe02b901859822a7
```

冻结的只读 Node23 快照显示：

- orchestrator：PID `2460094`，启动于 `2026-07-17T09:00:53+08:00`；
- runtime candidate manifest：1,320 条，SHA256 `7f2883849934fd286c969afbf38067e5a90a2b682eca62c195c10e0a00a0adf7`；
- Stage-1：1,320 个候选、2,640 个双受体作业，SHA256 `c76de07a2725939e62b4fab9cd9af4a7c72b30398f68bfa18727a223f277c1d0`；
- H96 与 runtime candidate overlap：`96/96`；
- H96 与 Stage-1 candidate overlap：`96/96`；
- H96 对应 Stage-1 作业：`192 = 96 × 2 receptors`；
- 快照前，`V4H__PLDNANO_VHH_00118__A_CENTER__H1H3__B02__M00` 的 8X6B 和 9E6Y 作业均已成功结束。

本次只读取 manifest、protocol lock、controller 和 job status JSON；没有打开 `job_result.json` 或 pose metric 文件，也没有创建预测或标签。

## 后续使用规则

QC96 以后只能进入明确写有以下边界的 development/research 版本：

```text
post-hoc sequence-to-independent-dual-docking computational geometry evidence
```

如需真正的 prospective 验证，必须重新建立完全未 Docking 的面板，并在第一条 Docking job 启动前冻结：model、config、exact per-candidate predictions、uncertainty、manifest 和 content-addressed receipt。

## 不变项

- 当前 Node23 research runtime 继续运行，本记录未停止、重启或修改它；
- 原 V4-H prereg、formal protocol、H96 manifest/provenance/receipt 均未改动；
- V4-D test32 继续封存，不能转作 development 数据；
- 本记录不赋予任何 biological truth 或 Docking Gold 语义。

机器可读退役审计：

```text
experiments/phase2_5080_v1/audits/
phase2_v4_h_qc96_prospective_formal_authority_retirement_v1_20260717.json
SHA256 = d36d7e371f885f420917d9e37867705b768925a03484136ee06ea1a7e303d6b0
```
