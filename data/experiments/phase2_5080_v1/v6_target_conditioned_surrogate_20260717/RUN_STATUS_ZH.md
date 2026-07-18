# PVRIG V6 运行状态（2026-07-18 02:50 CST）

## 目标和证据边界

主目标是从 VHH 序列和 label-free 单体结构近似独立 8X6B/9E6Y Docking 的连续几何，冻结主目标为 `R_dual_min`。所有结果仅表示 computational Docking geometry，不表示结合概率、Kd、实验竞争阻断、Docking Gold 或最终提交权威。

## 已完成数据

- 监督表：1,507 candidates / 31 whole-parent clusters。
  - V4-D OPEN_TRAIN：226 multi-seed，weight 1.0。
  - V4-H Stage1：1,281 dual single-seed，weight 0.65。
- Stage1 技术不完整：39 条单独隔离，未作负样本。
- 结构特征：每条 126 个 label-free VHH monomer descriptors。
- ESM2-650M pooled/CDR embeddings：1,507/1,507，12 shards，Node1 receipt SHA256 `95371648...`。
- ESM2-3B pooled/CDR embeddings：1,507/1,507，Node1 receipt SHA256 `f808d677...`。

## Stage1 contact teacher

Node23 完成双受体 Top-8、4.5 Å heavy-atom residue-contact 提取：

- 1,281 valid candidates；
- 39 technical-incomplete explicit NA；
- 2,640 receptor rows；
- 460,472 residue-pair rows；
- 19,978 pose coordinate files opened；
- technical-incomplete pose files opened = 0；
- source mutation operations = 0。

本地 compact package：

`experiments/phase2_5080_v1/prepared/pvrig_v6_v4h_stage1_contact_teacher_v1_1_20260718/`

## 已验证训练链

- Node1 环境：`/data1/qlyu/software/envs/pvrig-v6-tc`。
- 93 条、31 parents 的全父系 smoke：embedding、五折 nested OOF、resume/hash closure 全部通过。
- 首个完整 M3 pooled ESM2-650M + structure residual OOF：运行成功，但未晋级。
  - M2 Spearman = 0.58864；M3 = 0.57510。
  - M2 parent-centered = 0.24935；M3 = 0.24481。
  - M3 Top20 recall 略升，但 global/parent-centered/bootstrap 未通过。
  - 结论：高容量 pooled residual 在当前配置下过拟合，不能替换 M2。

## 已完成的 residue/contact 发布门

- V1.5 trainer / collector / implementation freeze 已冻结，关键 SHA256 为 `6c4ee5e9...` / `a15db4ac...` / `3a404646...`。
- 完整 residue-level targets：1,281 Stage1 可分析候选、158,759 residue rows；V4-D 226 条没有伪造或补零 contact 监督。
- 最终 production matrix：`RESIDUE_PRODUCTION_MATRIX_V1_2.json`，SHA256 `48fadb1b...`，在首个 formal outer result 之前冻结。
- 本地编排测试 15/15 PASS；冻结回归测试 41/41 PASS。
- Node1 exact deployment receipt：远端 `py_compile` PASS、41 tests PASS，且未改写 `code_v1_5`。
- Node1 四个 mechanical smoke lane 全部 PASS：
  - 三个 frozen lane 均为 head-only checkpoint，峰值显存约 3,249 MiB；
  - LoRA lane 为 head + 132 LoRA keys/checkpoint，无 base PLM 权重，峰值显存约 3,575 MiB；
  - 所有 lane 的 RESULT/outer seal/resume hash 均闭合。

## 当前运行

Node1 物理 GPU0 保留给既有用户任务。V1.5 production supervisor 在 tmux `pvrig_v6_residue_v1_5_production` 中稳定运行。

第一个预注册 lane `F1_contact_low_frozen` 已完整闭合：

- 5/5 outer folds terminal PASS；
- independent OOF collector terminal PASS；
- 1,507 candidates / 31 parents / bootstrap 1,000 次；
- 全局 Spearman：M2 0.59015 → residue 0.59265；
- parent-centered Spearman：0.25068 → 0.25012；
- Top20 recall 保持 0.38411；
- bootstrap positive fraction 0.842，median delta +0.00203。

由于 parent-centered 指标轻微退化 0.00056，按事先冻结门槛诚实输出 `DO_NOT_PROMOTE_RESIDUE_V1_5`，不会事后放宽。Supervisor 已自动进入第二个 lane `F4_contact_high_frozen`，GPU1–4 均约 3.2 GiB、40%–50% 利用率。`/data1` 仍有约 305 GiB 可用，高于 180 GiB checkpoint guard。

## 后续自动链

1. 完成 F4 high-contact 五折和 collector；
2. 按冻结顺序自动运行 F3 low-contact+rank 和 L1 LoRA r4 `query,value`；
3. 每个 lane 都仅在 5/5 fold terminal PASS 后运行 bootstrap=1,000、seed=20260718 的独立 OOF collector；
4. 任一 fold/collector 失败即 fail-closed，保留可续跑 checkpoint，不修改阈值或临时挑 lane；
5. 全部开发 lane 终态后才比较 M2；V4-F/test32 继续 sealed。
