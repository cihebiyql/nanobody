# V2.5 ORTHO 跨 lane 与 nested meta 正式评估冻结

## 结论

本目录在 V2.5 正式 outer 结果完整产生前冻结跨 lane 决策，避免看到结果后在三个 lane 中挑选最漂亮者。

- **正式主 lane 固定为 `E_DECOUPLED_CONTACT_SHARED`**。
- `B_CLEAN_TARGET_ATTENTION` 和 `E_DECOUPLED_CONTACT_DETACHED` 只能作为诊断，不得替代正式主 lane。
- 正式主 stack 固定为 `M2 + C2 + E_SHARED scalar + 2D persisted contact`。
- 模型只直接预测 `R8/R9`，`Rdual` 必须取精确 `min(R8,R9)`。
- 任一正式 gate 失败时，生产决策精确回退到冻结 M2，而不是改 gate、换 lane 或挑消融结果。

证据边界仍然是**独立双受体计算 Docking 几何 surrogate**，不是结合概率、Kd、实验阻断、Docking Gold 或提交真值。

## 为什么 Detached 不是严格“动力学独立”对照

`E_DETACHED` 切断了 contact loss 到 shared encoder 的直接 autograd 路径；但当前 trainer 对全部可训练参数统一执行 `clip_grad_norm_`。contact branch 的梯度范数仍可能改变全局缩放因子，从而间接影响 scalar branch 更新。因此本版本只称它为：

> no-direct-contact-autograd diagnostic

不能称为完全 dynamics-independent control。

## 当前可用于正式 meta 的 contact 信息只有 2 维

冻结 prediction writer 只持久化：

```text
contact_score_R8
contact_score_R9
```

`formal_metrics_v1.py` 的 ensemble TSV 又会丢弃 contact 列，因此正式 evaluator 必须从每个 seed 的不可变 `score_predictions_no_metrics.tsv` 中重建 contact 均值，并用对应 `RESULT.json` 校验哈希。

这意味着：

- 当前 primary 不能声称使用 14D contact summaries；
- 不能在结果出现后从 checkpoint 临时生成更多 contact 特征；
- seed 标准差只作诊断，不进入本版本 primary predictor。

## 冻结 meta 公式

每个受体分别计算，但三个参数在 R8/R9 间共享：

```text
pred_r = M2_r
       + w_E  * (E_SHARED_r - M2_r)
       + w_C2 * (C2_r       - M2_r)
       + beta_C * robust_z(contact_score_r)
```

约束：

```text
w_E >= 0
w_C2 >= 0
w_E + w_C2 <= 1
beta_C >= 0
无 intercept
```

contact score 不是 R 预测，**禁止**使用 `contact-M2`。contact 的 median、IQR 和 clip 只可在当前 outer fold 的 outer-train inner-OOF 行上拟合。

目标函数固定为 R8/R9 的 Huber loss（beta=0.03），加：

```text
0.01 * (w_E^2 + w_C2^2) + 0.10 * beta_C^2
```

## 双层 cross-fitting

对每个 outer parent fold：

1. 仅用 outer-train 的五个 inner folds 选择 E_SHARED H0/H1/H2。
2. 从被选 H 的 inner jobs 重建 E_SHARED inner-OOF scalar/contact；每个 outer-train candidate 只出现一次。
3. M2/C2 的 inner evidence 也必须在 outer-train 内重建，C2 的 scaler/filter/PCA/Ridge 均不得接触 outer-test。
4. 只在这些 inner-OOF 行上拟合 contact robust scaling 和 constrained meta。
5. E_SHARED outer-test 使用 43/97/193 三 seed 的均值；contact 同样从 per-seed TSV 重建均值。
6. 应用已冻结 outer-train transform/meta，生成一次性 outer-test R8/R9，再取精确 min。
7. 只有预测和 fit artifact 均冻结后，才读取 outer-test truth 计算正式指标。

已有的 1507 行 M2/C2 outer OOF 表只能提供 fold-matched outer-test evidence，不能替代 inner meta evidence。

## 正式 gate

所有条件必须同时满足：

- `Rdual Spearman >= 0.6194011215999979`
- `Rdual MAE <= 0.0323587150283071`
- `Rdual RMSE <= 0.04290748546218935`
- 两个 teacher source 各自 Rdual MAE 不劣于 M2
- 两个 source 的 Rdual Spearman delta 均不小于 0
- parent-macro Rdual MAE 不劣于 M2
- 至少 16/31 parent 的 Rdual MAE 不劣于 M2
- paired parent bootstrap 的 Rdual Spearman delta 95% CI 下界大于 0
- R8 与 R9 各自 Spearman 相对 M2 不低于 -0.03

失败则 `DO_NOT_PROMOTE`，并精确回退 M2。B、Detached、无 contact 消融、GBDT 或 reliability challenger 都不能在本契约下事后接替 primary。

## 文件

- `CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json`：机器可读冻结契约。
- `validate_cross_lane_contract_v1.py`：fail-closed 静态验证器。
- `tests/test_validate_cross_lane_contract_v1.py`：正常与篡改测试。

本目录不修改、不重启，也不读取远端 live job graph 的 outer 指标。
