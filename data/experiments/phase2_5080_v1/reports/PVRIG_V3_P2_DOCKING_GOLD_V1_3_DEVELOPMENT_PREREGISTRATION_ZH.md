# PVRIG V3-P2 Docking Gold V1.3 Development 预注册

## 1. 预注册状态与目标

```text
PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION
FORMAL_ELIGIBLE_FALSE_BY_DESIGN
P2_TRAINING_BLOCKED
```

V1.3 的唯一目标是回答：

> 对同一批 47 个 calibration cases 分别执行独立 8X6B-receptor docking 和独立 9E6Y-receptor docking 后，native-only 的五通道几何校准、per-receptor Top-8 聚合和 candidate-level dual pairing 是否可闭包、可复现并达到预先冻结的 development 稳定性门？

V1.3 不是 formal holdout，也不是 Docking Gold label release。当前 anchor-readiness 审计确认仍只有 11 anchors / 5 families，新增合格独立 blocker-VHH family 为 0；因此即使全部 development gates 通过，仍必须保持：

```text
formal_eligible = false
docking_gold_release_eligible = false
training_label_release_eligible = false
p2_training_ready = false
```

对应机器预注册：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_development_preregistration.json`

Anchor readiness：

- `experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_anchor_readiness_audit.json`
- `experiments/phase2_5080_v1/reports/PVRIG_V3_P2_DOCKING_GOLD_V1_3_ANCHOR_READINESS_ZH.md`

## 2. 与 V1.2 的版本边界

V1.2 已作为失败 RC 冻结：

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
bootstrap modal-tier gate: observed 7/11, required >=9/11
P2_TRAINING_BLOCKED
```

V1.2 的 47 cases 全部只来自 8X6B receptor docking，9E6Y 仅是对同一批 pose 的 post-hoc reference scoring。V1.3 不修改 V1.2 的 q20/q50、support、Top-K、LOFO、bootstrap 或失败结论，而是另起版本，补齐真正独立的两个 receptor docking lane，并改变 primary aggregation 的统计单位：

```text
V1.2:
one 8X6B-docked pose
-> two post-hoc reference scores
-> rank-paired S_pair

V1.3:
independent 8X6B-docked Top-8 run
+ independent 9E6Y-docked Top-8 run
-> aggregate each receptor separately
-> pair only at candidate/run level
```

V1.3 严禁把两个 receptor 的相同 rank 当作同一个 pose，严禁计算 `S_pair_r=(S_8,r+S_9,r)/2`，也严禁先把两套 pose 合并后重新排序。

## 3. Development cohort 与运行账本

### 3.1 固定 cohort

```text
success anchors = 11
perturbation/control cases = 36
total cases = 47
families = 5 (151, 20, 30, 38, 39)
```

11 个 anchor 只用于 threshold fit、family-balanced LOFO、hierarchical bootstrap 和 receptor-consistency development。36 个 perturbation/control 不被预设为 non-binder，只用于 exact-base paired sensitivity 和失败模式诊断。

### 3.2 独立双 receptor 运行构成

将 47-case manifest 与 Pilot64 manifest 按 `source_candidate_id/case_id` 精确连接：

| 来源 | case | receptor runs | 处置 |
| --- | ---: | ---: | --- |
| clean Pilot64 main runs | 32 | 64 | 仅在完整 release/hash/reuse audit 通过后复用 |
| calibration-only missing cases | 15 | 30 | 按本文冻结协议新运行 |
| 合计 | 47 | 94 | 每 case 恰好 8X6B main + 9E6Y main |

Primary development calibration 不使用 Pilot64 replicate seed runs。已有 replicate 可另作诊断，但不能进入 94-run primary denominator、阈值拟合、LOFO、bootstrap 或 `R_dual_dev`。

复用不是按目录名推断。每个复用 run 必须由后续 V1.3 release manifest 逐项绑定 config、monomer、receptor、restraint、hotspot、completion、`4_emref/io.json` 和所选坐标哈希；任何不匹配都必须在同一冻结协议下重跑，不能以 G5、E 或缺失值占位。

## 4. 冻结 docking 协议

两个 receptor 均使用 HADDOCK3 `2025.11.0` 的 clean Pilot64 main-run 协议：

| 参数 | 8X6B native run | 9E6Y native run |
| --- | ---: | ---: |
| `ncores` | 4 | 4 |
| `topoaa.iniseed` | 917 | 917 |
| `rigidbody.iniseed` | 917 | 20917 |
| rigidbody pose seed range | 918--957 | 20918--20957 |
| `rigidbody.sampling` | 40 | 40 |
| `rigidbody.tolerance` | 5 | 5 |
| `seletop.select` | 10 | 10 |
| `flexref.tolerance` | 20 | 20 |
| `emref.tolerance` | 20 | 20 |
| receptor-native hotspot 数 | 23 | 23 |
| primary source stage | `4_emref` | `4_emref` |
| primary selected poses | fixed Top-8 | fixed Top-8 |

`flexref=20` 和 `emref=20` 在这里表示允许缺失输出的百分比 tolerance，不是生成 20 个模型。每个 primary run 至少要求：

```text
topoaa outputs = 2
rigidbody outputs >= 38/40
seletop outputs = 10
flexref outputs >= 8
4_emref outputs >= 8
```

同一 candidate 在两个 receptor lane 必须使用字节相同的 frozen VHH monomer。Receptor、23-hotspot 文件、restraint、config、HADDOCK 版本和 seed 均须进入 release hash closure。禁止 candidate-specific tolerance override。

## 5. 固定 `4_emref` Top-8 选择

每个 run 只读取自己的 `4_emref/io.json`，按以下稳定顺序排序：

```text
1. ascending HADDOCK score
2. original io index
3. file_name
```

取前 8 个，标为 native rank 1--8。规则为：

- 不读取 `6_seletopclusts`；
- 不按 cluster size 加权；
- 不从 rigidbody/flexref/backfill pose；
- 不因另一个 receptor 的结果改变本 receptor 的 rank；
- 少于 8 个 `4_emref` pose 时整个 candidate dual record 失败，不生成 E/G5 标签。

Primary closure 必须恰好为：

```text
47 cases x 2 native receptors x 8 poses = 752 native poses
8X6B primary rows = 376
9E6Y primary rows = 376
all primary rows = 752
```

## 6. Primary native-only 指标与五通道阈值

每个 native pose 只用其 generation receptor 对应的 PVRL2 reference 计算 primary O/P；PVRL2 只读 protein `ATOM` heavy atoms，所有 `HETATM` 均排除。

### 6.1 三个 pose 指标

对 docking receptor `d in {8X6B, 9E6Y}`：

| 指标 | 定义 | 变换 |
| --- | --- | --- |
| `H_d` | canonical PVRIG hotspot contact weight fraction | identity |
| `O_d` | native PVRL2 total occluding residue-pair count | `log1p` once |
| `P_d` | `(CDR1_pairs+CDR2_pairs+CDR3_pairs)/O_d`，`O_d=0` 时为 0 | identity |

H 使用冻结的 PVRIG numbering reconciliation 映射到 canonical residue key。两个 receptor 的 pose 不相同，因此 H 数值不要求相等；“common H”只表示两套 native pose 共用一组 pooled threshold。

### 6.2 五个且仅五个 primary threshold channels

```text
canonical pooled H
8X6B-native O
8X6B-native P
9E6Y-native O
9E6Y-native P
```

不得建立 receptor-specific H 阈值，不得用 cross-reference O/P 拟合 primary 阈值，也不得把两个 receptor 的 O/P 先平均后拟合。

### 6.3 Family 与 receptor 权重

对 rank `r=1..8`：

```text
q_r = 1/log2(r+1)
Q_r = q_r / sum(q_1..q_8)
```

对 receptor-specific O/P，family `f`、family 内 anchor case `c`：

```text
w_fcr = (1/5) * (1/n_f) * Q_r
```

对 pooled canonical H：

```text
w_dfcr = (1/2) * (1/5) * (1/n_f) * Q_r
```

其中 `d` 是 receptor。这样每个 receptor 在 pooled H 中严格占一半，每个 family 在每个 receptor 内等权；不因 family 有更多 anchor 而增权。

### 6.4 Hurdle cutpoint

每个通道都先报告加权 zero mass，只在正值部分重新归一化权重：

```text
L = weighted positive-part q20
U = weighted positive-part q50
```

必须满足 `L>0` 且 `U>L`。不允许 epsilon、旧 V1.2 阈值、手工补值或从 sensitivity grid 中换一个“更好看”的组合。

Membership：

```text
mu(x)=0, if x=0
mu(x)=clip((T(x)-T(L))/(T(U)-T(L)),0,1), if x>0

T_O=log1p
T_H=identity
T_P=identity
```

## 7. Native pose score 与 A/B/C/E

对 receptor `d` 的 native pose：

```text
S_d = sqrt(mu_dO * ((mu_commonH + mu_dP)/2))
```

按顺序赋 native class：

| class | 条件 | relevance strength |
| --- | --- | ---: |
| A | `O_d>=U_dO and H_d>=U_H and P_d>=L_dP` | 4 |
| B | 非 A，且 `O_d>=L_dO and (H_d>=L_H or P_d>=L_dP)` | 2 |
| C | `H_d>=L_H and O_d<L_dO` | 1 |
| E | 其他 | 0 |

Strength `4/2/1/0` 用于 support 集合，不是概率、Kd 或实验 blocker 标签。缺失计算不能标作 E。

## 8. 先做 per-receptor Top-8 聚合

每个 receptor 独立聚合：

```text
R_d = sum(Q_r * S_d,r)

F_d,A = sum(Q_r * I[class=A])
N_d,A = count(class=A)

F_d,B = sum(Q_r * I[class in {A,B}])
N_d,B = count(class in {A,B})

F_d,C = sum(Q_r * I[class in {A,B,C}])
N_d,C = count(class in {A,B,C})
```

冻结中心 support gate：

```text
support_fraction >= 0.25
supporting_pose_count >= 2
```

Native run class 从强到弱判定：

```text
A, if F_d,A>=0.25 and N_d,A>=2
B, else if F_d,B>=0.25 and N_d,B>=2
C, else if F_d,C>=0.25 and N_d,C>=2
E, otherwise
```

这一步完全在各 receptor 内完成。两个 receptor 的 rank 不对齐、不配对、不互相改变 support。

## 9. Candidate-level dual pairing

只有两个 native run 均完成聚合后，才在 candidate 层配对：

```text
R_dual_dev = (R_8X6B + R_9E6Y)/2
R_dual_min = min(R_8X6B,R_9E6Y)
R_dual_max = max(R_8X6B,R_9E6Y)
R_dual_gap = abs(R_8X6B-R_9E6Y)
```

Dual tier 不是对 G 编号取数值最小值，而是由两个 native run class 精确定义：

| 8X6B class | 9E6Y class | dual tier |
| --- | --- | --- |
| A | A | G1 |
| A | B | G2 |
| B | A | G2 |
| B | B | G3 |
| A/B/C | A/B/C，且至少一个为 C | G4 |
| 任意 | 任一为 E | G5 |

同时报告保守 support：

```text
F_dual,A = min(F_8,A,F_9,A)
N_dual,A = min(N_8,A,N_9,A)
F_dual,B = min(F_8,B,F_9,B)
N_dual,B = min(N_8,B,N_9,B)
F_dual,C = min(F_8,C,F_9,C)
N_dual,C = min(N_8,C,N_9,C)
```

以及 assigned-tier support：对每个 receptor 使用建立其 native class 的 A/B/C support，再在两者间取 `min(F)` 和 `min(N)`。所有 G1--G4 均必须保持 `F>=0.25` 且 `N>=2`；否则 fail closed 为计算/规则失败，而不是静默降级。

`R_dual_dev` 只表示 development computational geometry score。由于 anchor readiness 未通过，它不得命名为 `R_gold`。

## 10. Cross-reference scoring 只作诊断

每个 native pose 可以额外对另一个 PVRL2 reference 做 cross-reference scoring，用于检查 numbering、reference sensitivity 和构象迁移，但必须：

1. 写入独立 diagnostic table；
2. 明确标记 generation receptor 与 scoring reference；
3. 不进入五通道 threshold fit；
4. 不改变 native A/B/C/E；
5. 不改变 `R_8X6B`、`R_9E6Y`、dual tier 或 `R_dual_dev`；
6. 不把相同 rank 跨 receptor 配对。

Primary audit 的分母始终是 752 poses / 752 native rows，而不是 native 加 cross-reference 后的 1,504 rows。

## 11. 中心设置与 sensitivity grid

中心设置保持：

```text
q_low = 0.20
q_high = 0.50
support_fraction = 0.25
minimum_supporting_poses = 2
```

完整 sensitivity grid 保持 54 组：

```text
q_low in {0.10,0.20,0.30}
q_high in {0.40,0.50,0.60}
support_fraction in {0.20,0.25,0.33}
minimum_supporting_poses in {2,3}
```

54 组一次性输出。禁止按 G1/G2 数量、anchor recall、mutant 方向或 receptor agreement 从中选择 best-looking row。

## 12. LOFO 与 hierarchical bootstrap

### 12.1 LOFO

以 family 为最小留出单位，共 5 折。每折只用其余 4 families 的 anchors 重拟合全部五个通道，对留出 family 生成 dual tier。

冻结门：

```text
each family has >=1 held-out anchor in G1-G3
macro-family G1-G3 recall >=0.80
>=9/11 anchors have absolute dual-tier shift <=1
no anchor has absolute dual-tier shift >2
```

任何折的任一阈值不可定义，LOFO 直接 FAIL。

### 12.2 Bootstrap

```text
seed = 20260714
B = 2000
level 1 = family block with replacement
level 2 = cases within sampled family with replacement
atomic unit = both native receptor Top-8 runs of one case
```

每个 replicate 重拟合五个通道并重算 per-receptor class、dual tier 和 `R_dual_dev`。未定义 replicate 计入 B=2000 的失败分母，不从概率分母删除。

保留 V1.2 的 dual-tier 稳定性门：

```text
>=9/11 anchors have dual modal-tier probability >=0.70
each family has >=1 anchor with P(G1-G3)>=0.70
```

## 13. 新增 receptor-consistency gates

Native class 的 ordinal step 独立定义为：

```text
A=3, B=2, C=1, E=0
```

它与 relevance strength `4/2/1/0` 是两个不同变量，不得混用。

在同一 2,000 次 hierarchical bootstrap 中，新增两个硬门：

```text
>=9/11 anchors have
P(abs(ordinal_class_8X6B-ordinal_class_9E6Y)<=1) >=0.70

each family has >=1 anchor with
P(class_8X6B!=E and class_9E6Y!=E) >=0.70
```

未定义 replicate 计入 B=2000 的失败分母。

以下只作诊断，不是 hard gate：

- 11 anchors 上 `Spearman(R_8X6B,R_9E6Y)`；
- `R_dual_gap` 分布；
- class confusion matrix；
- 每 family 的 receptor-specific score/tier 分布；
- cross-reference 与 native score 的差异。

特别地，不设置 `Spearman>=0.30` 之类的小样本硬阈值，避免在 n=11 上制造事后显著性门。

## 14. Mutant paired sensitivity

36 个 perturbation/control 只与其 exact base 配对：

```text
delta_R8 = R8_mutant - R8_base
delta_R9 = R9_mutant - R9_base
delta_R_dual_dev = R_dual_dev_mutant - R_dual_dev_base
delta_native_class_8/9
delta_dual_tier
```

正负方向全部保留。不得把 mutant 自动标为 non-binder、G5 或实验失败。Exact-base 缺失、序列错配或 receptor run 不闭包均为 hard failure。

## 15. Development acceptance gates

| gate | 通过条件 |
| --- | --- |
| frozen upstream | V1.2 failed RC hash/状态不漂移；旧 family rules 不被复用为 Gold |
| cohort closure | 47 cases = 11 anchors + 36 controls；32 reuse + 15 new case 账本精确闭包 |
| run closure | 94/94 native main runs；每 case 恰好 8X6B + 9E6Y |
| pose closure | 每 run fixed `4_emref` ranks 1--8；752/752 native poses |
| metric closure | 752/752 primary native rows；8X6B=376，9E6Y=376；数值 finite |
| protocol/hash closure | monomer/receptor/restraint/hotspot/config/seed/software/completion/io/pose 均由 release manifest 绑定 |
| ATOM-only | PVRL2 reference `HETATM used=0`；record inventory 闭包 |
| threshold validity | 五个通道均可定义，positive-part `L>0` 且 `U>L` |
| family/receptor balance | family 等权；pooled H 中两个 receptor 各占 1/2 |
| central/grid | 中心 q20/q50、0.25/min2 不变；54/54 sensitivity rows 完整且不选优 |
| LOFO | 第 12.1 节全部条件通过 |
| bootstrap | 第 12.2 节全部条件通过，seed=20260714、B=2000 |
| receptor consistency | 第 13 节两个 bootstrap hard gates 均通过 |
| mutant sensitivity | exact-base 配对闭包；方向原样保留；无 binary negative assignment |
| diagnostic isolation | cross-reference/replicate 数据不进入 primary threshold、class、tier 或 score |
| claim boundary | 只声称 computational dual-receptor development geometry |
| formal veto | 无论上述结果如何，formal/Gold/training eligibility 均为 false |

全部 development gates 通过时，允许的状态仅为：

```text
PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD
FORMAL_ANCHOR_READINESS_FAILED
P2_TRAINING_BLOCKED
```

任一 development gate 失败时：

```text
FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN
P2_TRAINING_BLOCKED
```

## 16. Fail-closed 规则

- 任一 run 少于 8 个合法 `4_emref` pose：candidate 不评分；
- 任一 primary metric 缺失或非 finite：candidate 不评分；
- 任一阈值不可定义：整个 RC FAIL；
- 不能把计算失败编码为 E/G5；
- 不允许 candidate-specific threshold、tolerance 或 backfill；
- 不允许查看结果后改变 q20/q50、support、minimum poses、seed/B 或 receptor-consistency gate；
- 不允许删除 bootstrap 不稳定 anchor；
- 不允许用 cross-reference rows 扩大 primary 样本数；
- 不允许把 `R_dual_dev`、A/B/C/E 或 G1-G5 解释为 binder、Kd、affinity 或实验 blocking truth。

## 17. 实现与 release-manifest 依赖

本预注册写入时尚未冻结 V1.3 builder、processor、calibrator、tests 和输出 package。机器 JSON 明确要求后续 release manifest：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_3_development_release_manifest.json`

该 manifest 至少要绑定：

1. builder/selector/processor/calibrator 及全部 tests 的 SHA256；
2. 47-case cohort join 和 32-reuse/15-new 账本；
3. 94 个 config 与每个 run 的全部 protocol/input/output hashes；
4. 752-pose selector 与 752-row primary native metrics；
5. 五通道 threshold、per-receptor scores/classes、dual scores/tiers；
6. 54-row grid、5-fold LOFO、B=2000 bootstrap 与 receptor-consistency outputs；
7. mutant paired deltas、claim boundary 和所有 eligibility false 字段；
8. 确定性重建证据。

在该 release manifest 存在且完整验证前，状态保持 `PENDING_IMPLEMENTATION`，不得启动 threshold/tier 结果解释。

## 18. 冻结执行顺序

```text
1. validate V1.2 failed-RC and anchor-readiness hashes
2. build exact 47-case x 2-receptor run ledger
3. validate 64 reusable clean main runs
4. build and run 30 missing native main runs
5. materialize fixed 4_emref Top-8 for all 94 runs
6. build 752-row native-only primary metric table
7. fit five family-balanced channels
8. aggregate per receptor, then pair at candidate level
9. run 54-grid, LOFO, B=2000 bootstrap, receptor-consistency gates
10. run exact-base mutant sensitivity
11. deterministic rebuild and release-manifest closure
12. issue development PASS/FAIL while retaining formal veto
```

本预注册本身不启动 docking。

## 19. 证据哈希锚点

| 证据 | SHA256 |
| --- | --- |
| V1.2 failed-RC freeze manifest | `341f1f1f6db11d1b874745acddd976dc9bbaf9e38434f578b6ddd91cca25eb1f` |
| V1.2 family calibration audit | `8aef0ed8ba8e2dbaf46f5dffa3940d7da8283469cfe6aa8d98b521518976eac7` |
| V1.2 Top-8 continuous audit | `6d7e67fdf6c25d14723e762e00cbf8058a01661815198ed313079212ea9330d4` |
| V1.2 376-pose selector manifest | `f42ada6cd3fb1ddf754154b6fb076da8c651ecaab2ff28ae58d1806d9a6de70b` |
| Pilot64 cohort manifest | `e67fcab05d93cd3f274c76cc435e9f4b649ace255e230129865d913fa8be3755` |
| clean Pilot64 V1.1 package audit | `9a347b8200b5bb1d06c76e52cf34aa0393facc04e24314d45f333725e3f28280` |
| clean protocol manifest | `db3b4cc629007cfe8de2fc5ff6866fe19ab088e2244437e750f53aa4b99d3d5b` |
| clean run manifest | `e8a420471f68f646c82063ea3254347859f155409cad413a971f37d30b3278a9` |
| positive anchor manifest | `ad1930b5c9938d0969c6645b4be05b9a3b9e49d48b4fb95b8a904a64f31bdef8` |
| mutant/control manifest | `81f42361be2e31dd8a083eb5cf28b35e1d09292635801a9a021fbe29b1d19248` |
| 8X6B reference | `b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868` |
| 9E6Y reference | `fb05ec77e439b8e1f43bfa12d7eb60f05f2c53e2099f06442f6c9ced32d98316` |
| hotspot registry | `9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd` |
| numbering reconciliation | `d7decf3be4a19dd9da2a42d9c8825a0b5d95ca350aea553b0933ad5c30c3c552` |

Builder/test/package hashes 尚不可用，不在本文伪造占位值；它们必须由第 17 节的外部 release manifest 在实现完成后绑定。

## 20. 最终预注册声明

```text
Primary rows are native-only: 752 poses and 752 metric rows.
The two receptor pose ranks are never paired.
Canonical H uses one pooled threshold with half weight per receptor.
Native O/P use receptor-specific thresholds: five primary channels total.
Each receptor is aggregated independently before candidate-level pairing.
Native relevance strength is A/B/C/E = 4/2/1/0.
Dual tier mapping is A/A=G1, A/B=G2, B/B=G3,
both non-E with at least one C=G4, any E=G5.
R_dual_dev is the mean of two native run scores and is not R_gold.
Cross-reference scoring is diagnostic-only.
q20/q50, support 0.25, minimum 2, LOFO, seed 20260714 and B=2000 are frozen.
Receptor-consistency probabilities include undefined replicates in the B denominator.
The unchanged 11-anchor/5-family set creates an unconditional formal veto.
P2 training remains blocked.
```
