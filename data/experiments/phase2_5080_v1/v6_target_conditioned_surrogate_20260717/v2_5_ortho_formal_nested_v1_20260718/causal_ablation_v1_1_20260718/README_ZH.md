# V2.5 target/contact 因果消融 V1.1（null 有效性硬化）

## 状态

`FROZEN_PRE_OUTER_RESULT_NONLAUNCHING_V1_1_HARDENED`

本目录是 V1 的**新版本硬化包**。冻结的
`../causal_ablation_v1_20260718/` 没有被修改；V1.1 也不会启动训练、推理或评价，不会修改正在运行的 301-job V2.5 正式图。

V1.1 只修复两个因果解释缺口：

1. 原 mask swap 同时改变位置与两类 mask 的基数，必须加入等基数、等阳性率的空间位置 null；
2. same-parent donor shuffle 虽然保证 donor 不同，却不保证 contact supervision payload 实际改变到足以构成有效 null，必须在训练前审计距离与功效。

## 一、等基数/等阳性率空间位置 null

冻结控制名：

```text
MATCHED_CARDINALITY_PREVALENCE_MASK_POSITION_NULL
```

每个 receptor 都把 clean 的：

```text
[hotspot_mask, interface_mask]
```

作为两列联合 payload，用同一个 permutation 在 target residue 位置间重新分配。它严格保持：

- hotspot cardinality；
- interface cardinality；
- 两者 prevalence；
- hotspot/interface overlap；
- 完整 2×2 joint contingency table；
- node feature、edge、拓扑、receptor key 和 frozen contact map。

因此该 null 只破坏“mask 位于哪些 PVRIG residue”，不改变 mask 规模。冻结参数：

```text
replicates = 256
master_seed = 1931
```

若某个 receptor 的 joint mask 完全退化、无法真正移动位置，直接 fail closed。

V1.1 的 contact-localization claim 必须同时满足：

1. 原 `HOTSPOT_INTERFACE_MASK_SWAP` gate；
2. clean functional masks 相对 256 个 matched-prevalence position null 的优势；
3. conditional-randomization empirical p ≤ 0.05；
4. whole-parent bootstrap CI 下界 > 0。

这使“模型只响应 mask 大小/阳性率”的解释不能单独支持 localization claim。

## 二、donor-recipient contact payload 距离/功效审计

冻结审计名：

```text
DONOR_RECIPIENT_CONTACT_PAYLOAD_DISTANCE_POWER_AUDIT_V1_1
```

每个 inner-train 和 outer-train donor map 都必须在**模型/optimizer 初始化前**独立执行审计。审计只读取当前 train partition 的 canonicalized contact payload，不读取：

- scalar Docking truth；
- held-out inner/outer rows；
- V4-F/test32；
- candidate/parent/campaign ID 作为 predictor。

距离定义：

- numeric probability/uncertainty：field-normalized mean absolute distance；
- bool mask：Hamming distance；
- categorical tier/missingness：0/1 mismatch；
- complete payload 与 supervision-only payload 分开报告；
- mapped distance 还要与同 train partition 内全部 eligible same-parent non-self pair 的距离比较。

冻结 fail-closed 门：

```text
complete payload changed fraction             >= 0.90
supervision changed fraction                  >= 0.80
supervision median distance                   >= 0.01
mapped / eligible supervision median ratio    >= 0.50
Kish distance effective fraction              >= 0.50
每 parent supervision changed fraction         >= 0.50
```

以下任一情况都必须在训练前失败：

- payload 字段缺失；
- non-finite；
- canonical tensor shape 不兼容；
- self/cross-parent donor；
- 任一强度/覆盖门未通过；
- audit receipt 缺失。

因此 donor shuffle 不能因为“换到一个几乎相同的 contact payload”而被误认为有效因果 null。

## 三、嵌套、exact-min 和防火墙保持不变

- outer unit：`parent_framework_cluster`；
- 5 outer × 5 inner；
- inference ablation 使用 clean frozen outer model 与 clean fold meta 参数；
- donor 只来自当前 inner-train 或 outer-train；
- shuffle 复用 clean fold 选择的 H；
- `Rdual=min(R8,R9)`，容差 `1e-12`；
- parent bootstrap 10,000 次，seed 1931；
- V4-F/test32 access count = 0；
- 不允许修改正式 301-job graph。

## 四、仍为 131-job 非启动图

两项硬化嵌入原作业接口，不增加 task 数：

- 15 个 mask-swap inference job 同时从同一个 frozen contact map 重评分 256 个 mask null；不增加 model forward；
- 25 个 inner + 15 个 outer shuffle retrain job 在初始化模型/optimizer 前先执行 payload power audit。

```text
GPU_TOTAL = 85
CPU_TOTAL = 46
TOTAL     = 131
execution_authorized = false
```

job graph 中没有 command，也没有 launcher。未来如需执行，必须另建 executable adapter 版本并独立审计。

## 五、证据边界

V1.1 最多支持 open-development computational Docking-geometry target/contact sensitivity。它不能说明实验 binding、Kd、PVRIG 阻断概率、Docking Gold、V4-F sealed performance 或比赛提交真实性，也不能事后改变 V1/V2.5 的 formal predictive metrics。
