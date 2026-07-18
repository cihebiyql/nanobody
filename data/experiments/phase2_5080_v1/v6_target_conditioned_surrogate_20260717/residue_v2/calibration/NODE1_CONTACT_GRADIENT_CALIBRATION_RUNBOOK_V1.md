# Node1 Residue V2 open-only contact-gradient calibration V1

## 目的与边界

本作业只用 open1507 teacher，在四个固定 lane 的 `outer_fold=0` 上各运行一次 `--smoke-mode --max-epochs 1`，读取**第一个 optimizer step 之前**的梯度观测，再由冻结 selector 选择 contact loss 权重。

它不是 formal OOF，不访问 V4-F/test32，不使用 prediction metrics，不更新 `RESIDUE_V2_PRODUCTION_MATRIX.json` 或 implementation freeze，也不产生 binding、Kd、实验阻断或 Docking Gold 结论。

## 固定资源

- bundle：`/data1/qlyu/projects/pvrig_v6_residue_v2_contact_gradient_calibration_bundle_v1_20260718`
- runtime：`/data1/qlyu/projects/pvrig_v6_residue_v2_contact_gradient_calibration_v1_20260718`
- Python：`/data1/qlyu/software/envs/pvrig-v6-tc/bin/python`
- GPU 1/2/3/4：A/B/C/D 四 lane
- GPU 5：target ESM2 augmentation
- 原 preregistration SHA256：`3847414a6db1f233543c08ceb3505d7b82fb952266fdf0c7c1314ebf18fc967e`

matrix 中所有实现、输入、receipt、graph cache 和 ESM2 model identity 都使用固定 SHA256；launcher 本身也由 `launcher_sha256` 绑定。

## 部署闭包

bundle 中必须保持以下相对路径：

```text
residue_v2/calibration/node1_contact_gradient_calibration_v1.py
residue_v2/calibration/CONTACT_GRADIENT_CALIBRATION_MATRIX_V1.json
residue_v2/src/train_nested_residue_surrogate_v2.py
residue_v2/src/residue_model_v2.py
residue_v2/src/augment_target_graph_esm2_v2.py
residue_v2/src/select_contact_loss_gradient_grid_v1.py
residue_v2/PREREGISTRATION_V2.json
residue_v1/src/train_nested_residue_surrogate.py
residue_v1/src/train_nested_residue_surrogate_v1_5.py
residue_v1/src/residue_model.py
inputs/...
```

禁止从 V4-F、test32 或 prospective computational test 路径提供任何输入。

## 执行

```bash
B=/data1/qlyu/projects/pvrig_v6_residue_v2_contact_gradient_calibration_bundle_v1_20260718
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
L=$B/residue_v2/calibration/node1_contact_gradient_calibration_v1.py
M=$B/residue_v2/calibration/CONTACT_GRADIENT_CALIBRATION_MATRIX_V1.json

$PY "$L" dry-run --matrix "$M"
$PY "$L" run --matrix "$M"
```

若已生成完整 bootstrap，但进程中断，可 fail-closed 恢复：

```bash
$PY "$L" resume --matrix "$M"
```

`run` 只接受全新 runtime root；`resume` 要求 bootstrap、静态哈希和已存在结果全部精确重放。任何 partial lane 目录、hash 漂移、GPU 非空闲、sealed path、缺少 first pre-step observation 都会停止。

## 成功证据

```text
<runtime>/status/BOOTSTRAP_RECEIPT.json
<runtime>/lanes/{A_DOMAIN,B_VHH3D,C_PATCH,D_FULL_PAIR}/outer_fold0/RESULT.json
<runtime>/calibration/by_sha256/<amendment_sha>/CONTACT_LOSS_AMENDMENT_V1.json
<runtime>/calibration/by_sha256/<amendment_sha>/CONTACT_GRADIENT_CALIBRATION_REPORT_V1.json
<runtime>/calibration/by_sha256/<amendment_sha>/RUN_RECEIPT.json
<runtime>/calibration/CURRENT.json
<runtime>/status/TERMINAL.json
```

成功 terminal 必须明确：四 lane 均存在 first pre-step observation、V4-F/test32 access 为 0、prediction metrics 未用于选择、formal OOF 未启动、production matrix/freeze 未更新。
