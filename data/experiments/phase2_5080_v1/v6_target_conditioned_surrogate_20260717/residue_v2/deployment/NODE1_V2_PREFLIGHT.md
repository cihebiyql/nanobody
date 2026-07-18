# Node1 Residue V2 训练就绪性预检

## 结论

**当前状态：`CONDITIONALLY_READY / NOT_READY_TO_LAUNCH_YET`。**

Node1 的 4 卡算力、CPU/RAM、本地 ESM2 权重、PyTorch/CUDA 环境和 V1.5
训练框架均可复用。但是在正式启动 V2 前，仍必须完成并冻结：

1. V4D/V4H 合并后的 1507 条 canonical contact target；
2. 1507 条 label-free VHH 单体三维残基图缓存；
3. 8X6B/9E6Y 两个固定 PVRIG target graph 缓存；
4. V2 代码、输入、运行矩阵和测试的最终哈希；
5. 新运行根目录的不存在检查与单 fold smoke。

本预检为只读审计：没有启动训练，没有安装依赖，没有修改 Node1
环境或远程文件。

## 1. 计算资源

只读实测时间：`2026-07-18T08:02:08+08:00`。

| 项目 | 实测结果 | V2 判定 |
|---|---|---|
| CPU | Intel Xeon Gold 6326，64 logical / 32 physical cores，2 sockets | 足够同时供给 4 个 lane 的 dataloader/collector |
| RAM | 503 GiB total，487 GiB available | 足够；建议缓存图索引而不是将所有 pair 张量常驻每个 worker |
| Swap | 2 GiB，未使用 | 不应依赖 swap |
| Load | 0.19 / 0.11 / 0.04 | 预检时 CPU 基本空闲 |
| GPU | 8 × RTX 4090，每卡 24,564 MiB | 本次冻结使用 GPU1、2、4、5；augmentation 使用 GPU6 |
| GPU0 | 18,459 MiB used，其他用户进程 `build_protein_lmdb.py` | **禁止占用** |
| GPU3 | 约 8.8 GiB used，其他用户训练进程 | **本次禁止占用** |
| GPU1、2、4–7 | 各约 18 MiB used，0% util | 预检时空闲；启动器仍须在启动瞬间重新检查 |

GPU0 实测占用进程：用户 `jjfang`，PID `3634744`，约 18,436 MiB GPU
内存。V2 启动器应 fail-closed 禁止 physical GPU0，不得根据空闲情况动态抢占。

### 冻结的 lane → GPU 映射

| lane | physical GPU | 建议环境变量 |
|---|---:|---|
| `A_DOMAIN` | 1 | `CUDA_VISIBLE_DEVICES=1` |
| `B_VHH3D` | 2 | `CUDA_VISIBLE_DEVICES=2` |
| `C_PATCH` | 4 | `CUDA_VISIBLE_DEVICES=4` |
| `D_FULL_PAIR` | 5 | `CUDA_VISIBLE_DEVICES=5` |

GPU6 固定用于 target ESM2 augmentation；GPU7 保留。GPU0、GPU3 均禁止分配。
每个 augmentation、trainer 和 collector 进程固定
`OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=NUMEXPR_NUM_THREADS=8`。

## 2. 存储可用性与安全运行根

| 路径 | 容量 | 已用 | 可用 | 使用率 |
|---|---:|---:|---:|---:|
| `/data1` | 7.0 TiB | 6.3 TiB | **305 GiB** | **96%** |
| `/data1/qlyu` | 当前约 64 GiB | - | - | - |

inode 使用仅约 3%，不是当前限制。容量可支持首轮 V2，但 `/data1`
已达 96%，因此不允许复制 ESM2 权重、Docking pose 树或多份相同 PDB。

**推荐的新建、版本化、fail-closed 运行根：**

```text
/data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718
```

推荐子目录：

```text
code/                         # 冻结 V2 代码，只读
inputs/                       # 哈希闭合的 teacher/split/M2 基线
cache/per_residue_esm2_650m/ # 新的逐残基 PLM 缓存
cache/vhh_graphs/            # 1507 条 label-free VHH graph
cache/pvrig_graphs/          # 8X6B/9E6Y fixed target graph
runtime/A_DOMAIN/
runtime/B_VHH3D/
runtime/C_PATCH/
runtime/D_FULL_PAIR/
status/
logs/
```

启动器必须在创建前断言该根不存在，且不是 symlink。建议容量门：

- 启动时可用空间 `<200 GiB` 时拒绝启动新矩阵；
- 运行中可用空间 `<150 GiB` 时停止新 fold/lane，保留已完成证据。

权重保留在 `/data/qlyu/.cache/huggingface`只读使用；训练时间、图缓存与
checkpoint 放到 `/data1/qlyu/projects/...`，禁止同步回 NFS pose 目录。

## 3. Python / PyTorch / CUDA 环境

**唯一推荐解释器：**

```text
/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
```

| 组件 | 实测版本/状态 |
|---|---|
| Python | 3.11.14 |
| PyTorch | 2.6.0+cu124 |
| Torch CUDA | 12.4 |
| CUDA available | true，8 devices |
| cuDNN | 90100 |
| Transformers | 4.57.6 |
| NumPy | 1.26.4 |
| SciPy | 1.13.1 |
| pandas | 2.3.3 |
| scikit-learn | 1.6.1 |
| Biopython | 1.84 |
| safetensors | 0.8.0 |
| accelerate | 1.14.0 |
| torch-geometric | **未安装** |
| `nvcc` | PATH 中不可用 |

当前 V2 实现的 `residue_model_v2.py` 和 graph builders 仅依赖
PyTorch/NumPy 等已有库，**没有 `torch_geometric`/PyG import**，因而上述缺失
不是当前阻塞。启动 freeze 应显式扫描导入；若后续代码引入 PyG 或需要
本地 CUDA extension 编译，则必须终止新版本而不得临时安装依赖。

已有环境 receipt：

```text
/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/
status/environment_receipt.json
status = PASS_NODE1_V6_ENVIRONMENT_READY
```

## 4. 本地 ESM2 权重

### ESM2-650M（V2 首轮冻结 backbone）

```text
/data/qlyu/.cache/huggingface/hub/
models--facebook--esm2_t33_650M_UR50D/
snapshots/08e4846e537177426273712802403f7ba8261b6c/model.safetensors
```

- bytes: `2,609,506,392`
- SHA256: `a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0`
- expected config: 33 transformer layers，hidden size 1280

### ESM2-3B（可选 comparator，不得替代首轮 650M）

```text
/data/qlyu/.cache/huggingface/hub/
models--facebook--esm2_t36_3B_UR50D/
snapshots/476b639933c8baad5ad09a60ac1a87f987b656fc/
```

| shard | bytes | SHA256 |
|---|---:|---|
| `pytorch_model-00001-of-00002.bin` | 9,976,735,419 | `0f971f11c449d21422aa982b791619c10351972992c735f4c3cd43fe09790412` |
| `pytorch_model-00002-of-00002.bin` | 1,390,347,055 | `7560b46fc383c691fb74b915b7d4bcef40d3df181447f16ba4b298845e308d0c` |

expected config: 36 transformer layers，hidden size 2560。ESMC-600M 也已下载，但不在
V2 首轮预注册矩阵中。

不应重新下载或复制这些权重。生产启动器应绑定 snapshot 路径和上述
SHA256，并使用 `local_files_only=True`。

## 5. 已有 embedding 缓存可复用边界

V6 项目中已有 1507 条的完整 pooled cache：

| cache | rows | shard | payload |
|---|---:|---:|---|
| `runtime/full1507_esm2_650m_embeddings_v1/` | 1507 | 12 | `[batch,5120]`, float16 |
| `runtime/full1507_esm2_3b_embeddings_v1/` | 1507 | 24 | `[batch,10240]`, float16 |

两者 receipt 均为 `PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE`，输入表哈希均为：

```text
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633
```

这些是固定维度 pooled/concatenated feature，可用于：

- V1.5/M2 对照复现；
- V2 辅助 global feature；
- smoke 与基线检查。

**不能**直接满足 V2 的逐残基 ESM2 state，也无法单独支撑 VHH graph node
或 VHH×PVRIG residue-pair head。V2 必须新建受 receipt 保护的 per-residue
ESM2-650M cache，或在每次训练时从冻结 backbone 现场计算；考虑 4 lane×5
fold 的重复成本，优先一次性缓存逐残基 state。

## 6. V1.5 可复用项

Node1 项目根：

```text
/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
```

V1.5 已终止且通过生产闭包：

```text
status/residue_v1_5_production/terminal.json
status = PASS_RESIDUE_V1_5_PRODUCTION_TERMINAL
detail = lanes=4;fold_runs=20;collectors=4;gpu0_forbidden=true
```

可复用的已验证内容：

```text
code_v1_5/residue_v1/IMPLEMENTATION_FREEZE_V1_5.json
code_v1_5/residue_v1/src/train_nested_residue_surrogate_v1_5.py
code_v1_5/residue_v1/src/collect_residue_oof_v1_5.py
deployment_v1_5/RESIDUE_PRODUCTION_MATRIX_V1_2.json
deployment_v1_5/residue_v1_5_common.sh
inputs_v1_2/full1507/v6_supervised1507.tsv
```

`v6_supervised1507.tsv` SHA256：

```text
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633
```

V1.5 中惟一晋级的 lane 为 `F3_contact_low_rank_frozen`：

| metric | V1.5 F3 | M2 | delta |
|---|---:|---:|---:|
| global Spearman | 0.592956844 | 0.590145348 | +0.002811496 |
| MAE | 0.033297452 | 0.033501295 | -0.000203843 |
| Top20 recall | 0.387417219 | 0.384105960 | +0.003311258 |

可复用的是 outer-fold split、M2 cross-fit baseline、训练/收集调度模式、完成标记和
GPU0 禁止契约。V1.5 代码和结果必须保持不可变；V2 只能复制到新的冻结
code package 或以哈希绑定的方式引用。

旧 V1 contact target 仅覆盖 V4H 1281，不包含 V4D 226；它可作 V4H
回归核验，不能充当 V2 canonical merged target。

## 7. V2 当前实现与输入状态

本地已有下列 V2 实现：

```text
residue_v2/src/build_dual_contact_targets_v2.py
residue_v2/src/materialize_graph_inputs_v2.py
residue_v2/src/build_residue_graph_cache_v2.py
residue_v2/src/build_target_graph_cache_v2.py
residue_v2/src/domain_balance_v2.py
residue_v2/src/residue_model_v2.py
residue_v2/src/train_nested_residue_surrogate_v2.py
residue_v2/src/collect_residue_oof_v2.py
```

已同步的 V4D open226 contact teacher：

```text
experiments/phase2_5080_v1/prepared/
pvrig_v6_v4d_open226_contact_teacher_v2_20260718/
```

包含 226 条多 seed 教师的 pair contact、residue marginal、Top-8 pose
inventory、audit、receipt 和 SHA256SUMS。该交付是 V2 的一个关键前置，但不等于
1507 条 merged target 已完成。

### 四 lane 对输入的要求

| lane | 可复用 | 仍需的前置 |
|---|---|---|
| `A_DOMAIN` | V1.5 head/M2/pooled embedding/outer folds | V4D+V4H merged marginal contact、domain-balanced manifests |
| `B_VHH3D` | A 的全部 | 1507 VHH monomer graph + per-residue ESM2-650M state |
| `C_PATCH` | B 的全部 | fixed 8X6B/9E6Y graphs + cross interaction inputs |
| `D_FULL_PAIR` | C 的全部 | merged dual-source pair soft targets/masks/uncertainty weights |

当前本地 V2 graph/model 是自定义 PyTorch/NumPy 实现，不需 PyG。但 Node1
V6 项目内尚未有可被本预检确认为 canonical V2 的 code package、VHH graph cache、
target graph cache 或 merged contact target；因此不应现在直接启动四 lane。

## 8. 启动前必须通过的门

1. **Code gate**：V2 代码、tests、contract、prereg 和 launcher 受 SHA256 闭合；
2. **Teacher gate**：V4D 226 + V4H 1281 = 1507，31 parent clusters，候选/序列/来源闭包；
3. **Graph gate**：1507 VHH graphs 全部与 monomer SHA256/CDR 区间闭合；
4. **Target gate**：8X6B/9E6Y 分开缓存，PVRIG 编号、热点、interface mask 闭包；
5. **Invariance gate**：图特征通过刚体旋转/平移不变性测试；
6. **Environment gate**：绑定 canonical Python、Torch/CUDA、A1/B2/C4/D5、augmentation6，GPU0/3 禁止、GPU7 保留、每进程 CPU threads=8；
7. **Storage gate**：新根不存在、非 symlink、可用空间 `>=200 GiB`；
8. **Smoke gate**：每 lane 先做一个极小的 single-fold smoke，验证 bf16、OOM、mask 与 collector 闭包；
9. **Production gate**：smoke 全通过后才并行启动 4 lane×5 folds。

不得因单个 lane 出现 OOM 而在同一 V2 版本中临时更改 hidden size、pair rank、
loss weight、fold、teacher rows 或 GPU 映射。

## 9. 本次审计的验证缺口

在本地文档写入前的最后一次 Node1 SSH 重试遇到：

```text
ssh: Could not resolve hostname node1: Temporary failure in name resolution
```

因此本文档中的硬件、磁盘、环境、权重和 V1.5 数字基于同一轮此前已成功的
`2026-07-18T08:02:08+08:00` 只读采样与已有 receipt；当前没有声称
上述推荐运行根已被实时确认为 absent。生产 launcher 必须在启动瞬间重新执行：

```bash
test ! -e /data1/qlyu/projects/pvrig_v6_residue_v2_3_four_lane_oof_v1_20260718
nvidia-smi
df -BG /data1
```

并将原始输出写入 environment preflight receipt。

## 10. 推荐的下一个可执行步骤

不是直接训练。先在本地完成 V2 的 teacher merge、graph materializer 和全套单测，
再将受哈希保护的 code/input package 一次性部署到新运行根。并行产生
per-residue ESM2-650M states 与 VHH/PVRIG graphs，通过闭包后先运行四 lane smoke；
只有 smoke 全部 PASS 才进入 4 卡长时 OOF。
