# canonical10644 coarse-pose 36D Node1 部署

## 执行边界

方案不修改冻结 V2.5 coarse_pose_features_v1.py。canonical10644 structure manifest 被确定性拆成
16--32 个 shard，每个 shard 仍执行固定的 2 个 public PVRIG target × 300 poses，最后验证每个
receipt、TSV 和输入哈希并按原 structure manifest 顺序合并。全过程不读取 teacher 数值列或候选
Docking pose，也不改变冻结 train/development split。

## Node1 输入

| 输入 | 路径 | SHA256 / 闭合 |
|---|---|---|
| structure manifest | /data1/qlyu/projects/pvrig_v2_11_canonical10644_m2_features_v1_20260721/full10644_features/canonical10644_structure_manifest_v1.tsv | 从 PASS_FULL10644_M2_TERMINAL 读取，并复核 structure receipt 和实际文件 |
| target NPZ | /data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_cache_v2.npz | b3081b7e91a5492f7765a721d9114dcb11f8ae095f40bfbcdcc3fe2b36edc108 |
| 8X6B PDB | /data1/qlyu/projects/pvrig_v2_11_canonical10644_coarse_pose_features_v1_20260721/inputs/fixed_targets/pvrig_8x6b_chain_b.pdb | 03af8f415847b8b6b246e787ec1e8d3cae4f024aa7bff6393ca344e0d7b02bcd |
| 9E6Y PDB | /data1/qlyu/projects/pvrig_v2_11_canonical10644_coarse_pose_features_v1_20260721/inputs/fixed_targets/pvrig_9e6y_chain_a.pdb | a65a26f0a50c36765f29930cd425a566028d216864ce5d835595e6db5b3e334a |

现有远端 V6 closure 有 NPZ，但没有列出两个 PDB，所以 launcher 要求把两个 PDB 显式放入新项目，
不猜测未闭合远端路径。

## 代码布局与哈希

新项目 code 目录保留以下层级：

- frozen/coarse_pose_features_v1.py
- src/prepare_full10644_coarse_pose_shards_v1.py
- src/merge_full10644_coarse_pose_shards_v1.py
- tests/test_full10644_coarse_pose_sharding_v1.py

对应 SHA256：

- frozen extractor: a87cda436379e768755f05aa0006c7a7dae8dd445a08b75339fc5a2bd0dfa591
- shard planner: 9e469327d9ab0e74577f79eb303c542636a328d68d6da040b207e53d1d739c74
- merger: ef602091701d759ef1d36899f33cbeb8500ba0af9c070ccc0296e6856ac4fa16
- test: 9ff1359ef6842fd6405d76a9e6d0e403f4a25e23adeeb492ddc583fed4b7ac9f
- launcher: 2eaaf29cdb6743852584aab2c8f5c2c136a3db3c9ba8c42567a4f3f0e105b550

## 并发与闭合

默认 SHARDS=32、MAX_PARALLEL=16，即 32 个近等长 shard 分两波运行；20 个 shard 为 333 条，
12 个为 332 条。Node1 明确授予 32 CPU worker 时可设 MAX_PARALLEL=32。合并器检查：

1. shard manifest 数量、顺序投影及 SHA；
2. V2.5 receipt schema/status、36D、每 receptor 300 poses；
3. manifest、NPZ、两个 PDB 的 receipt 路径和 SHA；
4. feature TSV SHA、精确列顺序、finite 数值及 feature schema；
5. candidate/monomer SHA 精确连接、无重复无缺失；
6. 最终 10,644 行按冻结 structure manifest 顺序输出。

唯一成功终态为 status/TERMINAL.json 中 status 等于 PASS_FULL10644_COARSE_POSE_TERMINAL。
它只证明特征物化与哈希闭合，不表示训练性能提升。

## 时长

Open1507 实测 feature loop 为 353.54 秒，均值 0.2345 秒/候选，外部 wall time 393.23 秒。
10,644 条单进程约 41.6 分钟 feature loop、按原比例约 46.3 分钟 wall time。理想下限为：

- 16 并发约 2.6 分钟；
- 32 并发约 1.3 分钟。

计入进程启动、target 装载、PDB 哈希、I/O、计划与合并，部署预算为：默认 16 并发 4--9 分钟，
32 并发 3--7 分钟；共享存储或 CPU 拥塞时预留 10--20 分钟。该估时来自已有 1,507 条实测，
当前仓库未启动任何 Node1 作业。
