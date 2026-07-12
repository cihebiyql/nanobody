# Phase 2 V3-G / V3-P 与 PVRIG Docking Teacher 执行计划

## 1. 当前决策

当前应当先生成 PVRIG 微调所需的 docking teacher 数据，同时继续完成 V3-G 通用绑定先验。原因是 V3-P 的主要瓶颈不是模型代码，而是缺少对应同一批候选的：

- Top-K docking poses；
- 8X6B 和 9E6Y 双参考几何评分；
- G1-G5 有序标签；
- pose/cluster 稳定性；
- VHH-PVRIG residue contact-frequency 软标签。

不应等 V3-G 成为完整正式模型后才开始 docking。两条线可以并行，但产品依赖顺序必须是：

```text
V3-G residue/contact backbone
        +
PVRIG prospective docking teacher
        ↓
V3-P1 sequence-to-geometry surrogate
        ↓
Node1 full structure/docking funnel
```

## 2. 模型边界

### V3-G

`Generic target-conditioned binding/contact prior`

学习的是：

- paratope；
- epitope；
- residue-pair contact；
- 真实 binder/non-binder 先验；
- 同 target/family 内的 affinity ranking。

V3-G 不输出 PVRIG 阻断真值。

### V3-P

`PVRIG geometry-surrogate frontscreen`

学习的是：

- PVRIG 功能界面的 contact mass；
- hotspot/interface specificity；
- 8X6B/9E6Y 几何层级；
- occlusion 连续指标；
- Top-K pose 和 cluster 稳定性；
- 模型不确定性。

V3-P 是前筛代理，不能替代 Node1 docking，也不能声称已证明 binding 或 blocking。

## 3. 当前已有数据

### 3.1 Calibration replay

已统一聚合：

- 11 个已知 PVRIG 成功案例；
- 36 个 mutant/control；
- 47 cases；
- 466 poses；
- 466/466 residue-contact extraction 成功。

这一层只用于机制、阈值、家族留一和 leakage control，不进入正式候选池。

### 3.2 Prospective pilot96

已冻结 96 条 RFantibody 候选，A/B/C/D 四个 hotspot set 各 24 条。截至 2026-07-12：

- 96/96 NanoBodyBuilder2 raw monomer 已生成；
- 96/96 规范化完成；
- 96/96 序列校验通过；
- 96/96 monomer geometry QC 完成；
- 96/96 PVRIG receptor geometry QC 完成；
- HADDOCK 受 Node1 `load1 <= 48` 安全门控，等待自动启动。

这 96 条全部来自 `h-NbBCII10` 单一 parent framework，因此只能验证管线和 V3-P1 smoke，不能支撑 unseen-parent 正式结论。

### 3.3 V3-G1 head-only smoke

已完成 2 epoch 真实 binder/non-binder head-only smoke：

| 指标 | 冻结 backbone | 训练后 head |
| --- | ---: | ---: |
| Dev AUPRC | 0.4103 | 0.5291 |
| Dev AUROC | 0.3981 | 0.5666 |
| Macro-target AUPRC | 0.4129 | 0.5357 |
| Target-shuffle mean absolute delta | 0.0066 | 0.0115 |
| Positive true minus shuffled target | -0.0002 | 0.0019 |

这说明 head 已学到部分标签区分，但 antigen-conditioned 信号仍很弱。该结果只是 smoke PASS，不是 V3-G formal PASS。

## 4. 立即执行顺序

### Step 1: 完成 pilot96 HADDOCK

Node1 controller 保持可恢复和负载门控：

```text
96 monomer QC complete
→ wait until load1 <= 48
→ 4 HADDOCK shards
→ 96 x Top-10 selected poses
```

不强制绕过负载门。已完成的 raw monomer 和 HADDOCK run 由 runner 自动跳过。

### Step 2: 同步最小必要运行证据

完成标记出现后运行：

```bash
python experiments/phase2_5080_v1/src/sync_pvrig_teacher_pilot96_outputs.py
```

只同步：

- `6_seletopclusts` models；
- `traceback/consensus.tsv`；
- monomer/receptor QC JSON；
- normalized monomer；
- run/controller logs；
- completion markers。

### Step 3: 运行双参考几何后处理

```bash
python experiments/phase2_5080_v1/src/process_pvrig_teacher_pilot96.py --workers 4
```

每条候选输出：

- Top-10 pose；
- 8X6B classification；
- 9E6Y interface rescoring；
- consensus class；
- aligned pose 和 per-model score。

### Step 4: 聚合 teacher labels

```bash
python experiments/phase2_5080_v1/src/build_pvrig_teacher_pilot96.py
```

主要产物：

```text
prepared/pvrig_teacher_pilot96/candidate_summary.csv
prepared/pvrig_teacher_pilot96/pose_summary.csv
prepared/pvrig_teacher_pilot96/pose_contact_frequency.jsonl
prepared/pvrig_teacher_pilot96/teacher_config.json
data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_teacher_manifest.tsv
audits/PVRIG_TEACHER_PILOT96_AUDIT.md
```

pilot 验收线：

```text
96 candidates
960 pose rows
960/960 dual-baseline classifications
960/960 contact extraction
96/96 COMPLETE candidate summaries
```

### Step 5: V3-P1 pipeline smoke

第一版只做工程验证：

```text
frozen V2.3/V3-G residue backbone
→ PVRIG fixed residue/structure features
→ small cross-attention/pooling head
→ ordinal G1-G5 + geometry regression + contact-frequency loss
```

由于单 parent 限制，pilot96 不做随机 train/test 的正式宣称。只验证：

- 数据能否加载；
- loss 能否有限下降；
- ordinal/contact/regression heads 能否同时运行；
- 推理输出能否交给 Node1 frontscreen。

## 5. 正式 teacher 数据的下一轮

pilot96 通过后，立即切换到多 parent 数据：

```text
40-60 parent frameworks
× 3 target patches
× multiple design modes
→ 8,000-12,000 raw candidates
→ fast hard gate
→ stratified 400-600 candidate teacher batch
```

首批 400-600 不能只取当前模型 Top，必须同时覆盖：

- 高 contact/interface 先验；
- 中间决策边界；
- 低分但 QC 通过的失败模式；
- parent/patch/method/CDR3 多样性；
- 少量校准突变和方法外探索。

第二批主动学习再增加 300-500 条，最终形成约 800-1,000 条 PVRIG-specific teacher candidates。

## 6. 正式训练前的强制门

V3-P formal 必须同时满足：

1. 以 `parent_framework_cluster` 为 split 单位；
2. 同 parent 的 seed、变体和近邻 CDR3 不得跨 split；
3. 已知阳性和其突变全部保持 calibration-only；
4. 阳性 CDR identity 只作模型外 hard gate，不作输入特征；
5. 主指标是 G1+G2 Recall@20%、EF@10%、NDCG 和 geometry Spearman；
6. target swap/hotspot shuffle/antigen ablation 必须显示可测的性能下降；
7. 三 seed 均优于最强 baseline，且 bootstrap/permutation 门通过。

## 7. 当前最短路径

```text
完成 pilot96 HADDOCK
→ 聚合 96 x Top-10 prospective teacher
→ V3-P1 pipeline smoke
→ 生成多 parent 400-600 正式 teacher
→ 完成 V3-G target-dependence 加强
→ 训练 V3-P formal
→ 主动学习扩展到 800-1,000
→ 冻结 frontscreen 版本
```

所以，“先生成 PVRIG Docking 微调监督”是当前正确优先级，但要分清两个里程碑：`pilot96` 用于打通管线，多 parent `400-600` 批次才是 V3-P 正式监督数据的起点。
