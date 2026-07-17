# PVRIG V4-H Research 双构象 Docking 回顾性审计

审计快照：2026-07-17 09:09（Asia/Shanghai）  
审计方式：只读检查本地代码、启动日志、H96 冻结 manifest 和 Node23 实时运行目录；未停止或修改任何运行中任务。

## 结论

```text
RECOMMENDATION = CONTINUE_RESEARCH_COMPUTE_BUT_QUARANTINE_FORMAL_AUTHORITY
```

这是一个真实正在运行的大规模研究性 Docking campaign，其代码、输入 receipt、运行状态和报告都明确限定为：

> fixed-PVRIG 8X6B/9E6Y computational geometry only；不是 binding、Kd、competition、experimental blocking、Docking Gold 或 formal validation。

因此，从“扩大研究性计算几何证据”的角度可以继续运行。但它不能承担现有 V4-H formal/prospective 权威，也不能用于宣称序列 surrogate 的 prospective 性能。

## 1. 谁启动了什么

启动链是本地 root-owned 脚本：

```text
prepared/pvrig_v4_h_research_pool_v1/scripts/
monitor_monomers_and_launch_adaptive_docking.sh
```

其 SHA256 为：

```text
df880ef7f858e752c474e719acd29471fcf0e32dd07d3b1df4c1b45e08f998d9
```

该脚本在完成 Node1 1,320 条单体建模、技术失败恢复、portable input 发布和 Node1→Node23 传输后，通过 `ssh.exe node23` 在 Node23 以 `qlyu` 用户启动：

```text
/data/qlyu/anaconda3/envs/haddock3/bin/python
/data/qlyu/projects/pvrig_v4_h_research_stage_tools_v1_20260717/run_adaptive_v4h.py
  --root /data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717
  --scorer /data/qlyu/projects/pvrig_v4_h_research_stage_tools_v1_20260717/stage_base_v4f.py
  --max-parallel 12 --stage2-count 384 --stage3-count 128
```

Node23 orchestrator PID 为 `2460094`，于 2026-07-17 09:00:53 +08:00 启动。本地 monitor PID `958262` 已正常退出，现在由 Node23 后台 orchestrator 独立持有 campaign。

部署脚本与本地字节一致：

| 文件 | SHA256 |
|---|---|
| `stage_v4h_research.py` | `86171da0967e69dc60f14476688227077c6f6b1f199cde763303cda04ba9eb46` |
| `run_adaptive_v4h.py` | `dca1694fe04ecd9d1763956bad73528e12dc21e9baf1e94d38395cd823b03721` |
| `stage_base_v4f.py` | `ef0e06f2ed30f575a7ecfe3d7c7bb390b0ecd9e02b1ce3824a82dc35a6aec024` |

## 2. 候选和对照选择

研究池从 1,440 条 exact-unique 生成序列中选择：

| 状态 | 数量 |
|---|---:|
| `RESEARCH_READY` | 1,320 |
| C0371 N 端证据不足、隔离 | 120 |

Docking 候选是所有 1,320 条 `RESEARCH_READY`，没有模型预测或排名再选择：

- 11 个 parent framework cluster，各 120 条；
- `A_CENTER` / `B_LOWER` / `C_CROSS` 各 440 条；
- `H3` / `H1H3` 各 660 条；
- 运行时 `model_split` 统一写为 `RESEARCH_V4_H`。

源候选 manifest SHA256：

```text
f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551
```

冻结的完整 job template 包含 47 个继承的 calibration controls：11 个 patent/series positives、7 个 base-reference positives、15 个 mutant perturbations 和 14 个 destructive-alanine controls。每个 control 有两个 receptor、三个 seed，因此 template 中有 282 个 control jobs。

但自适应 runner 实际只执行了 smoke control：

```text
CTRL_PATENT_001_case02_pos_01_PVRIG-151_HR151
seed 917; 8X6B + 9E6Y; 2 jobs
```

其余 280 个 control template jobs 不在 Stage 1–3 执行清单中。

## 3. Job 规模和资源

冻结的完整 template：

```text
7,920 candidate jobs = 1,320 x 2 conformations x 3 seeds
  282 control jobs   =    47 x 2 conformations x 3 seeds
8,202 total template jobs
```

自适应 campaign 实际计划执行的 unique jobs：

```text
Stage 1: 1,320 candidates x 2 conformations x seed 917  = 2,640
Stage 2: top/diverse 384 x 2 conformations x seed 1931 =   768
Stage 3: top/diverse 128 x 2 conformations x seed 3253 =   256
Smoke control: HR-151 x 2 conformations x seed 917      =     2
Total planned unique executed jobs                       = 3,666
```

Smoke candidate 的 2 jobs 同时属于 Stage 1，resume 时复用，不重复计数。

资源约束：

- Node23 64 logical CPU；
- 每个 HADDOCK job `ncores=4`；
- smoke 最多 4 个并行 jobs；
- Stage 1–3 最多 12 个并行 jobs，最大约 48 logical CPU；
- nice 级别 15；
- 不使用 GPU；
- scratch 位于 Node23 local `/tmp/pvrig_v4_h_research_dual_docking_v1_20260717`。

09:09 快照：

```text
smoke: 4/4 SUCCESS
Stage 1 controller: 2 SUCCESS + 12 RUNNING + 2,626 PENDING
orchestrator PID 2460094 alive
load1 = 44.28
release files = 0
```

## 4. H96 预测冻结与 prospective 边界

未发现在本 campaign 前完成的 H96 sequence-surrogate prediction freeze。当前代码直接对全部 1,320 条 research-ready 候选建模和 Docking，输入和运行时 manifest 均没有预测分数列或 prediction receipt。

H96 冻结 manifest：

```text
96 rows
model_split = V4_H_QC96_PROSPECTIVE_HOLDOUT
SHA256 = f128f7b2389ea5e9887b931460332ce42898aece0314e7320975c204a692f723
```

与 research-ready 1,320 池的 exact candidate-ID 交集为：

```text
96 / 96
```

而且在 09:09 快照中，H96 候选
`V4H__PLDNANO_VHH_00118__A_CENTER__H1H3__B02__M00`
的 8X6B 和 9E6Y jobs 已同时处于 `RUNNING`。

因此，对 Docking-label 意义而言，现有 H96 不再是 untouched prospective panel。其结果可在明确的 research/development 语义下使用，但不能再验证未事先冻结的 H96 surrogate 预测。

## 5. V4-D test32 和 formal authority

静态代码与运行目录审计未发现 V4-D test32 的路径或 ID 引用。适配器从 V4-D 只验证/复制了 hash-bound runtime templates、config、tests、normalized references、control monomers 和 calibration-control manifest，没有复制旧 campaign `results` 或 `status/jobs`。新 runtime 的 `results` 目录只包含本轮新生成的结果。

但本轮没有 test32 路径级 I/O instrumentation，所以这是静态和文件库存证据，不是 formal zero-read counter。

正式权威不成立的具体原因：

1. 未发现本 research adapter/runner 的事前 preregistration、implementation-freeze receipt 或 independent launch authorization；
2. 本地代码和研究报告目前被 `.gitignore` 忽略，未进入 Git 追踪；
3. 虽然 Node23 runtime 生成了 core/final protocol locks，但锁内仍保留了继承的误导性 metadata：`v4f96_fullqc_hardpass_no_replacement_v1`、`PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT`、`PASS_V4_F96...`，实际应为 1,320 条 `RESEARCH_V4_H`；
4. adaptive runner 本地单测只覆盖 diversity selection 的 2 个用例，没有覆盖 H96 pre-prediction gate、formal split 隔离、ranking replay 或 release authority；
5. H96 96/96 已进入本轮 Docking，且预测未先冻结。

相对地，运行时 staging 自检的 18 个相关测试及 protocol validation 通过，adaptive diversity tests 在 normal 和 `PYTHONOPTIMIZE=1` 下均 2/2 通过。这支持“可继续研究性计算”，但不能补足 formal governance。

## 6. 处置建议

1. **不停止当前 campaign**：其目标与用户要求的大范围 research Docking 一致，且当前运行正常。
2. **隔离 formal/prospective 权威**：所有输出只能标记为 `RESEARCH_V4_H_COMPUTATIONAL_GEOMETRY`，不得用于现有 V4-H formal V1 PASS/FAIL 或 prospective model validation。
3. **宣告 H96 对 Docking-label 不再 untouched**：可将其降级为 development/research evidence，但不能继续称为未见 formal holdout。
4. **为序列 surrogate 新建真正的 prospective panel**：先冻结 model/config/predictions/receipt，再对完全未开启的新候选运行 Docking。
5. **保持 V4-D test32 sealed**：当前没有理由开启或混入本轮训练/排名。
6. **下一版清理继承标签**：不改动当前正在运行的目录；在新 versioned runtime 中用 research-specific panel/status/split 名称替换 V4-F96/prospective 遗留值。

