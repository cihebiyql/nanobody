# PVRIG V3-P2 Docking Gold V1.2 失败 RC 冻结说明

## 1. 冻结结论

V1.2 当前状态被作为一个不可静默改写的失败 release candidate 冻结：

```text
FAIL_DOCKING_GOLD_NOT_VALIDATED
P2_TRAINING_BLOCKED
```

冻结的唯一 family-aware 失败门是 bootstrap modal-tier stability：预注册要求至少 `9/11` 个 anchor 的 modal-tier probability `>=0.70`，实测为 `7/11`。其他 9 个通过门不能抵消该 veto。

## 2. 冻结边界

机器可读的冻结清单为：

`experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_failed_rc_freeze_manifest.json`

它逐文件绑定：

- V1.1 最终否决及其主要支持证据；
- V1.2 方法文档、shared-H/来源修订和 processor release manifest；
- fixed `4_emref` Top-8 连续指标包、758 文件精确哈希清单和确定性重建审计；
- family-aware 失败 RC 的 10 个数据/规则/审计文件及中文报告；
- 最终验证报告和执行状态修订；
- smoke8/failed52 坐标恢复审计及 selector；
- 本说明和只读冻结 validator。

## 3. 唯一允许的复用

当前产物只允许两类复用：

1. **连续输入复用**：Top-8 连续几何量、residue contacts 和对齐坐标可作为一个新的、独立预注册版本的校准输入；
2. **provenance 复用**：失败规则、family 输出和 Pilot64 恢复资产可用于复现、审计、回归检查和新版本的方法论论证。

这些复用不会使 V1.2 的阈值、tier 或训练标签变成已冻结真值。

## 4. 明确禁止

在新版本完成独立预注册并通过全部 acceptance gates 之前，禁止：

- 将当前 A/B/C/E、G1-G5 或 `R_calibration_run_8x6b_dock` 当作 Gold；
- 将 family rules/tiers 或 recovered smoke8/failed52 坐标用于 P2 训练、标签发布或当前规则评分；
- 声称已冻结独立 dual-receptor `R_gold`；
- 将计算几何 teacher 声称为 binder、Kd、affinity 或实验 blocking 真值；
- 在 V1.2 名义下事后更改 q20/q50、support、Top-K、bootstrap 或 acceptance gate；
- 覆盖或修改本 manifest 绑定的旧产物并仍沿用 V1.2 版本号。

## 5. 校验

只读校验命令：

```bash
python experiments/phase2_5080_v1/src/validate_phase2_v3_p2_v1_2_failed_rc_freeze.py
```

校验器会重算所有绑定文件的 SHA256 和字节数，以 Top-8 确定性 listing 逐一校验 758 个 package 文件，并直接核对 family audit 和 recovery audit 中的状态字段。任一哈希、文件集、失败门或训练边界漂移都会 fail closed。
