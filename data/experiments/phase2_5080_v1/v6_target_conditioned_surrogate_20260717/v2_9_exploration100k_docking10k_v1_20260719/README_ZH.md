# PVRIG V2.9：100k 探索池、10k Docking 面板与双节点执行

## 当前结论

- 已生成 `100,000` 条完全去重探索序列。
- 全部 fast-QC 与 `<75%` 阳性 CDR identity 候选中，`42,810` 条进入 ANARCI；`40,676` 条 IMGT 编号通过。
- 原 70-parent 计划在 fail-closed ANARCI 后容量不足。技术容量修订后冻结 `65` 个 parent、`10,000` 条最终面板；每 parent `153–154` 条，仍满足预先建议的 `60–100 parent` 和 `80–200 条/parent`。
- 最终 `10,000/10,000` 条均为标准氨基酸、序列唯一、ANARCI/IMGT 通过且 CDR1/2/3 非空。
- 已冻结 `25,000` 个候选级双受体/多 seed 分配：seed917 `20,000` jobs、seed1931 `4,000` jobs、seed3253 `1,000` jobs。

## 最终本地输入

```text
prepared/final_panel10k_v3/docking_panel10000.tsv
prepared/final_panel10k_v3/docking_allocation25000.tsv
prepared/structure_inputs10k_v1/structure_candidates10000.tsv
prepared/structure_inputs10k_v1/STRUCTURE_INPUT_RECEIPT.json
ACCEPTANCE_REPORT.json
SHA256SUMS_V1
```

`STRUCTURE_INPUT_RECEIPT.json` 的冻结结果：

```text
candidate_count       10000
unique_sequence_count 10000
parent_count          65
ANARCI/IMGT pass      10000
manifest SHA256       5afdcb713f997175bc10eed2b93226551ce3a7750a9216d57e9cbdac6f5cdf9e
```

`ACCEPTANCE_REPORT.json` 已独立验证 100k 唯一性、10k ANARCI/阳性 CDR gate、65-parent 容量、方法/mode/acquisition 配额、parent 隔离 split、open3388 零序列重叠和 25k 双受体/seed 闭合。

## Node1：全量单体结构预测

项目：

```text
/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720
```

执行策略：

- NanoBodyBuilder2；优先 refined，失败后 unrefined fallback；
- GPU `1–7`，每 lane `3` CPU threads，约占 `21` 个 CPU 核；GPU0 未占用；
- 每个候选写独立 status JSON；序列必须与 PDB chain A 完全一致；CA 邻接几何必须通过；
- 技术失败记录为 `TECHNICAL_FAILURE/NA`，不当作 Docking 低分或负样本；
- runner 可恢复，已成功的 hash-bound PDB 不重复计算。

为缩短结构关键路径，冻结面板末尾 4,000 条同时在 Node23 运行 CPU NBB2：

```text
/data/qlyu/projects/pvrig_v29_monomers_tail4000_node23_v1_20260720
```

Node23 最终采用 `24 workers × 1 thread`；`32 × 1` 的短测会使 load average 升至约 69，因而未作为持续配置。Node1 上的导入器每 30 秒校验 candidate ID、序列 SHA256、PDB SHA256 和 chain-A 精确序列后，将成功结构原子导入主运行目录；Node1 原 runner 随后自动跳过这些已完成项。Node23 技术失败不会导入，仍由 Node1 尝试，避免把基础设施失败误当成结构失败。

尾部 4,000 条完成后，Node23 自动接续冻结清单中 `selection_rank=5001–6000` 的中段 1,000 条；该区段与尾部不重叠，并在启动时与 Node1 本地推进位置保留安全间隔。第二导入器使用独立锁和状态前缀，仍执行相同的 ID、序列与 PDB 哈希校验。

关键状态：

```text
full10k/status/PROGRESS.json
full10k/status/COMPLETE.json
full10k/outputs/monomer_manifest.tsv
status/full10k.pid
status/node23_tail_importer.pid
full10k/status/NODE23_IMPORT_PROGRESS.json
```

## Node1 + Node23：Docking

### 已真实启动的计算 smoke

7 条 NBB2 smoke 结构已全部通过，并冻结 14 个 `8X6B/9E6Y × seed917` jobs：

```text
/data/qlyu/projects/pvrig_v29_pilot7_dual_docking_v1_20260720
```

Node1 与 Node23 各承担 7 jobs，使用不同本地 scratch；所有 job 共享哈希绑定 manifest，并由 per-job lock 防重。首轮暴露缺少 `reference_normalization_summary.json` 的评分依赖，补齐后已从第二 attempt 恢复。最终 `14/14 SUCCESS`：6 jobs 在第一 attempt 完成，8 jobs 在修复后的第二 attempt 完成；两受体各 7 jobs。完成收据：

```text
/data/qlyu/projects/pvrig_v29_pilot7_dual_docking_v1_20260720/status/PILOT_COMPLETE.json
```

实际 selected-model 数为 `4–10`；后续 teacher 聚合必须固定“最多 Top-8”，并显式记录不足 8 个完整 pose 的可靠性/技术状态，不能假装每个 job 都恰有 8 个 pose。

### 全量自动接续

Node1 已启动等待器：

```text
/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720/src/wait_for_v29_monomers_then_launch_docking.sh
```

当 `full10k/status/COMPLETE.json` 出现后，等待器会：

1. 保留所有 10,000 条单体状态；失败项不替换，Docking 标签为 NA；
2. 把成功 PDB 复制并 hash 冻结到共享 NFS；
3. 将 frozen 25,000-row allocation 过滤为可执行 jobs，同时保留原始 25,000-row 清单；
4. 冻结新 protocol core、job manifest 和 Node1/Node23 分片；
5. Node1 用 `5 × 4 cores ≈20 cores`，Node23 用 `8 × 4 cores =32 cores`；
6. Node1 scratch 位于 `/data1/qlyu/scratch`，Node23 scratch 位于 `/tmp`。

全量目标项目：

```text
/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720
```

### 最终启动状态

单体阶段已形成 10,000 条终态：

- `9,934 SUCCESS`；
- `66 TECHNICAL_FAILURE/NA`；
- 无失败替换、无将技术失败当负样本；
- 单体 manifest SHA256：`ca7a7e8aa784ddf7c0f9079d3700c5098159e1fd599253ea64ade04a2cb3fe9f`。

冻结的原始 allocation 仍为 25,000 行。过滤 66 个单体技术失败后，可执行 Docking jobs 为 24,826，均分为：

- Node1：12,413 jobs，启动 PID `1020114`；
- Node23：12,413 jobs，启动 PID `1533157`。

协议锁：

```text
protocol_core_sha256 = 49fffc2c7087b1ff3a8e42463319168fad409687f502b619f3661c978fc6d666
protocol_lock_sha256 = d8f3eb46e7ab781949130739681d9f33c825510ef4bc743f80249c0c26764bda
```

启动验收已证明：两节点分片无重叠、并集等于完整可执行 job manifest、allocation 的 `(candidate, receptor, seed)` 与物化 jobs 完全闭合、两节点进程存活且均产生首批状态。

### CDR 顺序纠正

第一次 staging fail-closed 暴露了 ANARCI CSV 插入位点处理缺陷：旧脚本把 ANARCI 已按生物序列顺序输出的插入列再次按列名排序，导致 insertion-rich CDR2/CDR3 字符顺序错误。序列生成、阳性 CDR 相似度 gate、近邻聚类和面板选择使用的是正确的 `cdr1_after/cdr2_after/cdr3_after`，因此 10,000 条面板选择不受该错误影响。

本次 Docking restraint 已改为仅使用在完整序列中精确且唯一出现的 `cdr1_after/cdr2_after/cdr3_after`，并加入 fail-closed 检查；ANARCI 提取脚本也已改为保持 CSV 原始列顺序，并新增 insertion-order 回归测试。

本地镜像验收材料位于：

```text
runtime_receipts/RUNTIME_ACCEPTANCE_REPORT.json
runtime_receipts/RUNTIME_ARTIFACT_MANIFEST.json
runtime_receipts/monomer_v1/
runtime_receipts/full_docking_v1/
```

全量分片启动后，独立验收器还会校验：冻结 25,000-row allocation 保留、可执行 job 集与 manifest 完全闭合、Node1/Node23 分片无重叠且并集完整、protocol/job/shard 哈希一致、两个分片进程存活且都已产生首批状态。通过收据写入：

```text
/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720/status/LAUNCH_ACCEPTANCE.json
```

## 科学边界

本流程得到的是：

- 单体结构预测与几何 QC；
- 独立 8X6B/9E6Y guided Docking pose；
- blocker-like 几何、遮挡、接触和 pose 稳定性 teacher。

它不等于真实结合、Kd、IC50、实验阻断、表达量或纯度。技术失败必须为 NA，不能当负样本。

## 实时检查

在当前 WSL 运行：

```bash
bash src/check_v29_live_status.sh
```
