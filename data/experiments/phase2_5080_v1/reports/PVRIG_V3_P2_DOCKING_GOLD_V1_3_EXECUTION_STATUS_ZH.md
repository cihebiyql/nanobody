# PVRIG V3-P2 Docking Gold V1.3 执行状态

**更新时间：** 2026-07-14  
**当前结论：** `REMOTE_COMPLETION_PENDING`  
**必须保持的状态：** `P2_TRAINING_BLOCKED`

## 1. 本轮目标和停止线

本轮只验证一件事：在固定 47-case development cohort 上，是否能用真正独立的 8X6B 和 9E6Y native docking，生成可重现的双受体计算几何证据。

本轮不会因为开发方法通过而自动产生：

- formal Docking Gold；
- P2 training label；
- binder、affinity、Kd 或实验 blocking 声明；
- formal holdout 结论。

原因是当前仍只有 `11 anchors / 5 families / 0 new independent families`，没有达到预注册的 formal 入口线。

## 2. 1–4 项执行进度

### 2.1 项目 1：冻结 V1.2 失败 RC

已完成，且复验通过：

```text
PASS_V1_2_FAILED_RC_FREEZE_VALIDATED
54/54 artifacts
758/758 package files
46/46 semantic assertions
```

关键产物：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_failed_rc_freeze_manifest.json`
- `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_2_FAILED_RC_FREEZE_ZH.md`

V1.2 历史结论没有被修改：

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
P2_TRAINING_BLOCKED
```

### 2.2 项目 2：冻结 V1.3 预注册和 anchor 边界

已完成。

- development preregistration：`phase2_v3_p2_v1_3_development_preregistration.json`
- anchor readiness：`phase2_v3_p2_v1_3_anchor_readiness_audit.json`
- formal readiness：`FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES`

已冻结的核心设计为：

```text
47 cases
94 native main runs
2 receptors per case
Top-8 per run
752 canonical native poses
752 primary native metric rows
```

### 2.3 项目 3：生成真正独立的 9E6Y docking

正在运行，不是模拟或 cross-reference 重评分。

当前执行闭包：

```text
64 runs  = Pilot64 真实独立双受体 main runs 复用
30 runs  = 15 个缺口 case 的 8X6B + 9E6Y 新 docking
94 runs  = V1.3 完整双受体闭包
```

远程包已原子上传到：

```text
/data/qlyu/projects/pvrig_v3_p2_docking_gold_v1_3_dual47_completion15_20260714
```

上传后验证：

```text
86/86 package content hashes PASS
controller --list-only = 30 runs
```

两个边界 case 的 4 个 run 已全部通过：

```text
mut_01_PVRIG-20_base_reference:  8X6B PASS, 9E6Y PASS
mut_36_39H4_fw_cons_Y59F:       8X6B PASS, 9E6Y PASS
```

每个 run 的 stage count 都是：

```text
topoaa=2, rigidbody=40, seletop=10, flexref=10, emref=10
```

本地哈希收据：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_boundary4_remote_receipt.json`
- status：`PASS_V1_3_BOUNDARY4_REMOTE_RECEIPT_HASH_CLOSED`
- SHA256：`3f878cd24f0c0e6a9c93450f83dee29515a2b084b12b8817915f6ac9ccd6d154`

完整 controller 已启动，且只会在 `load1 <= 50` 时启动新 run。截止本文更新时：

```text
4/30 new runs PASS
26/30 new runs pending behind the frozen load gate
controller alive
```

Node1 同时存在其他长时 CPU/HADDOCK 任务，当前 load 高于 50。本项目没有降低阈值或中断其他任务；controller 会在资源条件满足后自动继续。

### 2.4 项目 4：recovery、processing、calibration 和后续门控

生产运行尚未开始，因为必须等待 30/30 新 runs 闭包。但完整实现、独立资格验证和对抗回归已完成。

#### Selector / recovery

- 合并 64 reuse + 30 new runs；
- 固定 `4_emref` Top-8，禁止 backfill；
- 强制 `94 runs / 752 poses / 376 per receptor`；
- 强制双 receptor lane identity、coordinate/seed 唯一性、冻结 root/release hash 闭包；
- 不发布 geometry class 或 training label。

#### Native processor

- 只计算 generation-receptor-native H/O/P；
- 9E6Y 使用其 native numbering/reference；
- PVRL2 只使用 protein `ATOM` heavy atoms；
- 产生 752 metric rows、752 contact records 和 752 aligned PDB；
- 首次计算只能得到 `BUILT_PENDING_DEVELOPMENT_RELEASE`；
- 两次独立、字节一致的不可变发布经 validator 验证后，才能作为 calibrator 输入。

#### Development calibrator

- 保留 5-channel threshold、54-grid、5-family LOFO、B=2000 hierarchical bootstrap、29 mutant deltas；
- 禁止跨 receptor rank pairing；
- 自身永久只输出 `CALCULATED_PENDING_RELEASE_VALIDATION`；
- 不能自行解锁 smoke、formal、Gold 或 training。

#### Independent development release

- 必须比较两个不同 publication root 中独立生成的 calibrator release；
- 逐字节验证 13 个冻结输出，并重算全部 17 个 development gates；
- 只有该 validator 可以输出 `PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD`；
- development PASS 最多使 `development_smoke_eligible=true`，formal/Gold/training/P2 仍为 `false`；
- 真实计算门失败时发布不可变 FAIL release，并停止后续。

#### Persistent autorun

已启动本地持久会话：

```text
tmux session: pvrig-v13-production-autorun
state:        WAITING_REMOTE_COMPLETION15
remote:       4/30 PASS, 26 pending
```

autorun 使用冻结 manifest SHA、controller PID/argv/cwd/executable/start-ticks 和逐级 upstream release receipt 做 fail-closed 恢复。任何 upstream `current` 变化都会使其本身及所有下游阶段失效重跑。它不包含 smoke、regression、formal、Gold label 或 training 命令。

## 3. 坐标 identity 金标的额外验证

独立 code review 曾发现两个不能忽略的 provenance 漏洞：

1. HADDOCK pose 中 VHH C 端 `OXT` 会消失，原始 atom identity 与 monomer 相差 1 个 atom；
2. 只比较 `ATOM` 会静默忽略 pose-chain `HETATM` 漂移。

本轮没有静默放宽，而是先做 544-pose 证据审计，再分别冻结 v1/v2 amendment。

### 3.1 Terminal OXT

544 poses 中：

```text
chain A residue exact                  544/544
chain A raw ATOM exact                 0/544
chain A terminal-OXT normalized exact  544/544
chain A non-OXT differences            0
chain B raw residue/ATOM exact          544/544
```

只允许：同一个 chain-A 最后 `ATOM` residue 上，单个 `OXT` identity 的存在/缺失。其他任何 residue 或 atom 差异均 fail-closed。

### 3.2 Heavy HETATM

同一批 544 poses 中：

```text
monomer A heavy-HETATM identities  0
receptor B heavy-HETATM identities 0
pose A heavy-HETATM identities     0
pose B heavy-HETATM identities     0
```

V2 amendment 因此冻结为 zero gate：参考和 pose 的 A/B chain 只要存在任意 heavy `HETATM` 就失败。`OXT` normalization 永远不适用于 `HETATM`。

关键产物：

- `phase2_v3_p2_v1_3_atom_identity_difference_audit.json`
- `phase2_v3_p2_v1_3_atom_hetatm_identity_addendum_audit.json`
- `phase2_v3_p2_v1_3_atom_identity_normalization_amendment.json`
- `phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v2.json`

## 4. 最终本地验证

在 selector v2、processor qualification 和 pending-only calibrator 全部冻结后，主线程重新运行了联合回归：

```text
69/69 tests PASS
runtime: 143.168 s
py_compile PASS
git diff --check PASS
v1 amendment validator: valid=true
v2 amendment validator: valid=true
```

这些测试包括：

- release/root/hash 篡改；
- chain A/B ATOM 和 HETATM 注入；
- 非末端 OXT 和 HETATM-OXT；
- 双 receptor identity 错配；
- 重复坐标、错误 seed 和 backfill；
- synthetic/self-signed processor release；
- native/cross-reference 标记混用；
- full B=2000 两次字节一致重建；
- independent development release 自签名/单 release/门控篡改；
- autorun upstream `current` 漂移后的全链路失效重跑；
- 冻结远程 manifest 路径逃逸、重复和 controller 身份伪装；
- atomic `current` pointer 回滚。

## 5. 接下来的自动执行顺序

只有当远程 `30/30` 新 runs 全部达到 `PASS_4_EMREF_TOP8_READY` 后，才依次执行：

```text
94-run dual-source recovery
  -> 752 fixed Top-8 poses
  -> native processor build A
  -> native processor build B
  -> independent processor qualification
  -> V1.3 development calibration
  -> independent development release validation
```

如果 development gate 失败：

```text
停止；不运行 smoke/regression/Pilot64 后续诊断。
```

如果 development gate 通过：

```text
只允许运行 development smoke8 / failed52 / Pilot64 diagnostics。
```

无论 development 结果如何，当前 formal 都必须停在：

```text
BLOCKED_BY_ANCHOR_PANEL
P2_TRAINING_BLOCKED
```

不得把第二 receptor docking 当作新的生物学 family 证据。
