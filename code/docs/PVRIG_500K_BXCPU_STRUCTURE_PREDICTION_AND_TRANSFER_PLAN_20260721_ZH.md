# PVRIG 500k：bxcpu 结构预测与滚动回传执行方案

日期：2026-07-21  
目标：使用 bxcpu 8 个 CPU 节点承担主要 CPU 工作，将 500,000 条有效 VHH 序列生成与硬 QC 控制在 24 小时内，并将后续约 50,000 个 VHH 单体结构预测尽可能放在 bxcpu 并行执行。所有结果按分片边计算边回传到本地，再校验后上传 Node1 SSD。

## 1. 已验证资源

- bxcpu 账户 `GrpTRES=node=8`；
- 分区 `amd_256q`；
- 每节点 64 CPU、约 256 GiB RAM；
- 8 任务单节点 job array `11939031` 已实际同时运行，8/8 成功、0 字节 stderr；
- 正式调度必须使用 `--array=0-7%8`，不使用一个整体 8-node job；
- bxcpu compute node 为 RHEL 7.9 / glibc 2.17 / Python 3.6.8；
- Node23 的 NanoBodyBuilder2 环境为 Ubuntu glibc 2.35，整体 8.2 GiB，不能直接复制到 bxcpu；
- Node23 纯 CPU NanoBodyBuilder2 单条实测：4 threads，19 s，输出 PDB 约 140 KiB；
- bxcpu 公共文件系统 `df` 显示 4.4 PiB 可用，但用户配额无法通过 `quota/lfs quota` 直接读取，因此必须使用滚动回传，不依赖表面全局剩余容量；
- 本地 `/mnt/d` 剩余约 104 GiB；
- Node1 `/data1` 剩余约 240 GiB，已建 staging：`/data1/qlyu/projects/pvrig_500k_structure_prediction_v1_20260721/incoming`。

## 2. 500,000 条序列的完整构成

| 路线 | 有效数量 | 主要资源 |
|---|---:|---|
| conservative CDR redesign | 200,000 | bxcpu CPU |
| natural CDR donor | 100,000 | bxcpu CPU |
| disagreement/random control | 50,000 | bxcpu CPU |
| fixed-pose ProteinMPNN | 75,000 | Node1 GPU |
| RFantibody | 75,000 | Node1 GPU |
| **总计** | **500,000** | CPU 350,000 + GPU 150,000 |

35 万只是 CPU 生成路线，不是总数。

## 3. bxcpu NanoBodyBuilder2 环境硬门禁

bxcpu 上现有 Python 3.11 portable runtime 可复用，但其原 NumPy 2.4.0 需要 glibc 2.27，在 compute node 上不可用。NanoBodyBuilder2 环境必须单独建立 EL7/glibc 2.17 兼容版，不得直接复制 Node23 Conda 环境。

上线前必须通过：

1. `torch` CPU import；
2. `openmm` import；
3. `ImmuneBuilder` / `NanoBodyBuilder2` import；
4. 单条 VHH 产生非空 PDB；
5. PDB 序列与输入一致；
6. 与 Node23 同序列结构进行主链几何合理性和 FR RMSD 对照；
7. 32 条、8 并发 smoke 无 OOM、无非法 PDB。

环境部署和 smoke 的时间上限为 2 小时。超时或不通过时：

- bxcpu 继续执行序列生成、fast QC、exact dedup 和 CDR3 聚类；
- 结构预测自动切换到 Node17/18/19/23；
- 不因 bxcpu 环境问题阻塞 500k 主时间线。

## 4. 50,000 个结构的 bxcpu 分片

- 候选只在 500k 序列前筛到约 50k 后建模，不对 500k 全量建模；
- 对 RFantibody/fixed-pose 候选，优先复用已生成 backbone，并显式标记 `structure_source`；
- 需从序列重新预测的部分使用 NanoBodyBuilder2 CPU 主线；
- 输入冻结为 8 个无重叠 top-level shards，每节点约 6,250 条；
- 每节点 16 个持久 worker，每 worker 4 CPU threads，合计 64 CPU；
- worker 只加载一次模型，然后处理本 worker 的连续候选，避免每条重新启动 Python/加载权重；
- 每 500 条形成一个 transfer chunk，全部 50k 约 100 chunks；
- 失败写入 TSV 并补跑，不把失败序列当成低分候选。

理论上，128 个四核 worker 在 19 s/条时约为 24,000 structures/hour。考虑共享文件系统、精修、归档和失败重试，bxcpu 正式目标设为 8,000–16,000 structures/hour，50k 预计 3–6 小时。

## 5. 滚动归档与三地镜像

禁止对 50,000 个 PDB 逐文件跨网络复制。每个 500-结构 chunk 发布：

```text
chunk_000001.tar.gz
chunk_000001.manifest.tsv
chunk_000001.sha256
chunk_000001.READY.json
```

manifest 至少包含：

```text
candidate_id
sequence_sha256
structure_model
structure_model_version
structure_source
pdb_relative_path
pdb_sha256
elapsed_seconds
worker_id
slurm_job_id
status
failure_reason
```

归档使用 `tar | gzip -1`，优先速度而非最大压缩率。

自动 watcher 流程：

1. 只读取 `READY.json` 已存在的 chunk；
2. 用 `ssh.exe bxcpu "cat ..." > local.partial` 下载到本地；
3. 本地 SHA256 通过后原子改名；
4. 用流式 SSH 上传到 Node1 `incoming/*.partial`；
5. Node1 重算 SHA256，通过后原子改名；
6. 写入本地和 Node1 ACK；
7. 仅在 bxcpu/local/Node1 三方 hash 一致后，才允许清理 bxcpu raw chunk；
8. 任何时刻 bxcpu 最多保留 4 个尚未 ACK 的完整 chunk，控制账户占用。

本地作为不可变归档镜像，Node1 作为后续特征抽取、模型预测和 Docking 的工作副本。

## 6. 磁盘预算和止损线

按 Node23 实测 140 KiB/PDB：

- 50,000 PDB raw 约 6.7 GiB；
- manifest/log/status 预留 1–2 GiB；
- gzip-1 archive 预计 2–5 GiB；
- 三地同时存在时，本地和 Node1 均有足够容量。

止损线：

- bxcpu campaign 目录达到 20 GiB 或写入错误时暂停新 chunk；
- 本地 `/mnt/d` 剩余低于 50 GiB 时暂停下载；
- Node1 `/data1` 剩余低于 100 GiB 时暂停上传；
- watcher 不得因为上游容量问题删除唯一副本。

## 7. 时间线

### 500k 序列生成与硬 QC

| 时间 | 工作 |
|---|---|
| 0–2 h | bxcpu 运行 350k CPU 路线；Node1 同时运行 150k GPU 路线 |
| 1–5 h | bxcpu fast QC / exact dedup / CDR3 聚类 |
| 2–10 h | Node1 RFantibody + fixed-pose ProteinMPNN |
| 4–12 h | ANARCI 分片、family cap、补位 |
| 12–18 h | 500k 合并、provenance、SHA256 冻结 |
| 18–24 h | 失败重试和缓冲 |

### 50k 结构预测

- bxcpu NBB2 环境通过：3–6 h 主计算 + 1–2 h 回传/终态校验；
- bxcpu 环境失败回退 Node17/18/19/23：6–12 h；
- IgFold 不全量运行，仅在后续 Top 1k–5k 做 GPU 交叉复核。

## 8. 完成定义

500k 序列完成必须同时满足：

- 500,000 条 exact-unique 有效序列；
- 五条路线数量符合配额；
- ANARCI/IMGT、FR/CDR、保守 Cys、阳性 CDR 相似性和 CDR3 family cap 通过；
- provenance 和 sequence SHA256 完整；
- 发布 terminal receipt 和 SHA256SUMS。

50k 结构完成必须同时满足：

- 每个候选有非空 PDB 或明确技术失败；
- sequence/PDB 一致性和基础几何 QC 通过；
- 每个 PDB 有 SHA256 和 model provenance；
- 本地与 Node1 都有 hash-bound 副本；
- bxcpu 原始分片只在两个下游副本均 ACK 后清理。

