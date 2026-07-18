# V1.5 residue surrogate：Node1 精确自动编排

该目录只负责已经冻结的 V1.5 residue lane 的部署验证、机械 smoke 与四 lane 生产编排；
不修改或重新生成 `code_v1_5`。当前本地实现和测试不会启动任何远程任务。

## 冻结对象

编排同时验证以下 SHA256：

- V1.5 trainer：`6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af`
- V1.5 collector：`a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0`
- V1.5 freeze：`3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e`
- governance amendment、1507 训练表及 receipt、完整 contact target、`RUN_RECEIPT.json`、
  independent validation、ESM2-650M `model.safetensors`
- `RESIDUE_PRODUCTION_MATRIX_V1_2.json`

V1.5 freeze 内列出的全部 implementation 文件也在部署前由远端逐项闭包验证；随后使用
Node1 的冻结运行环境对 `src/*.py`、`tests/*.py` 做隔离 `py_compile`，并要求远端
`unittest discover` 精确得到 `Ran 41 tests` 和 `OK`。测试数量与结果写入 deployment receipt。
`code_v1_5` 不进入上传 manifest，目标文件已存在但哈希不一致时也不会覆盖。

## 三个入口

### 1. 只部署编排与输入

```bash
deployment/residue_v1_5_exact/deploy_node1_residue_v1_5_exact.sh
```

该命令验证现有 Node1 `code_v1_5`，只安装缺失且哈希一致的编排文件和权威输入，
写入 `DEPLOYMENT_RECEIPT.json`，不会启动 smoke 或生产任务。

### 2. 机械 smoke

在 Node1 执行：

```bash
/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/deployment_v1_5/run_node1_residue_v1_5_smoke.sh
```

固定使用物理 GPU1，按四条 lane 的冻结顺序各跑 fold0、1 epoch，并进行一次 resume replay，
要求 RESULT 哈希不变。`validate_residue_v1_5_smoke_checkpoint.py` 会逐个检查
`adapter_head_final.pt` 和所有 `last.pt`：frozen lane 只能含 `head.*`，L1 lane 必须同时含
`head.*` 和 LoRA 参数，任何 base PLM 参数或未知 trainable key 都会 fail-closed。每条 lane
还会记录 checkpoint 数量、总字节数和物理 GPU1 的峰值显存。任何失败立即停止后续 lane。

### 3. 生产 supervisor

只有 deployment receipt 和 smoke terminal 都通过后才能执行：

```bash
/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/deployment_v1_5/supervise_node1_residue_v1_5_production.sh
```

每条 lane 的固定 GPU 分配：

```text
GPU1: fold0 -> fold4
GPU2: fold1
GPU3: fold2
GPU4: fold3
GPU0: forbidden
```

四条 lane 固定顺序：

```text
F1_contact_low_frozen
F4_contact_high_frozen
F3_contact_low_rank_frozen
L1_contact_low_lora
```

每条 lane 必须先得到五个合法 `PASS_OUTER_FOLD_COMPLETE` 与
`SEALED_COMPLETE_ONE_EVALUATION`，才会运行一次 V1.5 collector。Collector 固定使用
bootstrap 1000 次和 seed 20260718；collector terminal 完成后才进入下一 lane。

## Fail-closed 与恢复

- `/data1` 启动或 checkpoint 前低于 180GB：写 SAFE_STOP terminal；
- trainer 内部 150GB safe-stop 和 180GB checkpoint guard 保持不变；
- 中断后只能用完全相同的 result-affecting binding resume；
- 已开始 outer evaluation 但无 RESULT 的 seal 永不自动重评；
- partial collector output 不覆盖、不删除，必须人工审计；
- 任意 fold、collector 或 receipt 失败都会停止当前和全部后续 lane。

V4-F prospective/test 数据继续密封，不在上传 manifest、训练参数、运行路径或 collector 输入中出现。

## 本地验证

```bash
python3 -m unittest discover \
  -s experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/deployment/residue_v1_5_exact/tests \
  -p 'test_*.py' -v
```

三个运行脚本均支持 `--print-plan`；该模式只输出机器可读 JSON，不访问 Node1 或启动任务。
