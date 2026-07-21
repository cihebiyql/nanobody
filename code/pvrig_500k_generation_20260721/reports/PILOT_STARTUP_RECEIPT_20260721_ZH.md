# PVRIG 500k generation：25k pilot 启动收据

日期：2026-07-21  
状态：已启动部分可验证路线；全 25k 尚未完成

## 已冻结

- 正式方案：`docs/PVRIG_500K_VHH_GENERATION_AND_SCREENING_EXECUTION_PLAN_20260721_ZH.md`
- 机器配置：`config/pilot25000_spec.json`
- campaign：`run/pvrig_500k_generation_pilot25k_v1_20260721`
- raw task manifest：32,500 行，五路线各 6,500；目标是各冻结 5,000 条有效序列。
- parent panel：180 个 parent clusters；单 parent raw-task 最大占比 0.828%；新 parent raw-task 占比 65.04%。
- 静态输入校验：`run/.../manifests/SHA256SUMS`，8/8 校验通过。

## 本机 CPU 路线

已经实际生成：

| 路线 | raw | unique/QC 结果 | 当前状态 |
|---|---:|---:|---|
| conservative CDR redesign | 6,500 | fast-QC pass 6,107，有效冻结 5,000 | PASS |
| natural CDR donor | 6,500 | fast-QC pass 5,517，有效冻结 5,000 | PASS |

两路线合并的 10,000 条 pre-ANARCI 序列 exact unique=10,000，known-positive any-CDR identity `>=80%` 为 0。

首轮 ANARCI 对 10,000 条主候选返回 9,947 条真实 PASS；53 条因 ANARCI 重定义的 CDR 边界与设计记录不一致而 fail-closed。随后对 1,624 条未使用备用候选补跑 ANARCI，其中 1,616 条 PASS，最终重新冻结为两路线各 5,000 条。

终态与可复现输出：

```text
CPU: 2（主批次和补位批次均已结束）
有效 TSV: run/.../qc/local_cpu_routes_effective.tsv
有效 FASTA: run/.../qc/local_cpu_routes_effective.fasta
终态: run/.../status/LOCAL_CPU_ANARCI_TERMINAL.json
校验和: run/.../manifests/local_cpu_effective_SHA256SUMS
```

这里的 fast QC 只是 ANARCI 前置便宜筛选；保守 Cys 的 IMGT 23/104 位置、FR/CDR 完整性和 CDR sequence-order 一致性由 finalizer 做正式编号门禁。

本地有效集的进一步硬校验：序列和 candidate ID 均 10,000/10,000 唯一；已知 PVRIG 阳性 any-CDR identity `>=80%` 为 0；180 个 parent clusters；新 parent 占 65.32%；按等长 CDR3、Hamming identity `>=80%` 建连通家族后共 195 族，最大家族恰为 100，通过每族上限 100 的门禁。

## Node1 RFantibody 路线

远程目录：

```text
/data1/qlyu/projects/pvrig_500k_rfantibody_pilot_v1_20260721
```

启动证据：

- 四臂 RFdiffusion → ProteinMPNN → fast-QC smoke：PASS；
- 正式 36 个 primary arms 已启动；
- GPU：1、2、3、4、5、7；
- 每 arm 24 backbones × 8 ProteinMPNN sequences；
- raw target 6,912，计划冻结 5,000 exact-unique；
- 每 GPU lane 的 OMP/MKL/OpenBLAS 线程限制为 1；
- 输出写 Node1 SSD `/data1`，不是 NFS campaign 输出目录。

自动终态同步：

```text
tmux: pvrig-500k-pilot-node1-rfantibody-sync-20260721
本地镜像: run/.../node1_rfantibody_mirror
终态: run/.../status/NODE1_RFANTIBODY_TERMINAL.json
```

该路线使用 P1–P6 hotspot grid，不能静默改名为 A/B/C；进入合并 release 前需要显式 patch mapping/分层审计。

## 保持 BLOCKED 的路线

| 路线 | 原因 |
|---|---|
| fixed-pose ProteinMPNN / AntiFold | 没有冻结的 pose manifest；未找到可验证 AntiFold 部署 |
| de novo / disagreement control | 没有通过 smoke 的独立 generator |

这些路线只有 task 定义，没有被写成“已生成”。后续应优先复用已有高质量 Docking pose 建 fixed-pose input；de novo 路线要先做小规模 smoke 和唯一率/QC 审计。

## 执行中发现并修复的数据问题

Top200 的旧 ANARCI CSV 解析存在 insertion-column 顺序问题。全 Top200 有 170/200 条 CDR3 表格值与原序列顺序不一致；当前 180-parent panel 中为 CDR2 3 条、CDR3 155 条。pilot 使用原始序列恢复 sequence-order CDR，并在 ANARCI finalizer 中显式实现 IMGT CDR2 60/61 与 CDR3 111/112 两侧插入位点的序列顺序，不使用旧错序字符串做 graft。

## 当前停止条件

本启动收据不代表 25k 已完成。只有以下条件全部满足才可发布 terminal pilot：

1. 本地两路线各 5,000 ANARCI/FR-CDR/Cys PASS；
2. RFantibody 冻结 5,000 exact-unique 且 checksum 通过；
3. fixed-pose 与 de novo 路线各 5,000 有效序列，或形成经过审批的显式回拨版本；
4. 25k 合并后重新执行 exact dedup、80% CDR3 family cap、Top-parent cap、可开发性审计和校验和；
5. 发布明确的 `PASS` 或 `HOLD` 扩展决定。

合并 release 的 fail-closed 入口已实现：

```text
scripts/build_effective_pilot_release.py
```

它要求五条路线各恰好 5,000 条、全局 exact duplicate=0、提供恰好 20 个 parent 的权威 current-top20 清单、current-top20 合计不超过 35%，并按等长 CDR3/Hamming identity ≥80% 的连通家族执行每族最大 100 条门禁。任一条件不满足时不会生成 `READY.json`。
