# V2.5 strict meta formal autostart V1

本目录不改变既有 V2.5 execution manifest、模型矩阵或 promotion gates。

它新增一个显式授权后的终态 watcher：

```text
WAITING_STRICT_V1_2_1_TERMINAL
→ PASS_INPUTS_READY_UNAUTHORIZED
→ 重验 freeze / manifest / canonical inputs / D evidence / C2 / V4-F=0
→ 物化绑定真实 input-closure SHA256 的 explicit overlay
→ 启动 frozen evaluator 子进程
→ wait 子进程终态
→ 校验 formal receipt 和全部 artifact SHA256
→ 写 TERMINAL.json PASS/FAIL
```

## 授权分层

`EXPLICIT_AUTHORIZATION_INTENT_V1.json` 已明确授权，但规定在 input closure 通过前
不得物化可执行 overlay。

`EXPLICIT_AUTHORIZATION_OVERLAY_TEMPLATE_V1.json` 不是可执行 overlay：

- `execution_authorized=false`；
- `input_closure_receipt_sha256=PENDING_PASS_INPUT_CLOSURE`。

Watcher 只有在所有检查通过后，才在运行目录生成：

```text
authorization/EXPLICIT_AUTHORIZATION_OVERLAY_V1.json
```

该文件会精确绑定：

- frozen execution manifest SHA256；
- 实际 PASS input-closure receipt SHA256；
- explicit authorization intent SHA256；
- runtime token SHA256；
- V4-F/test32 access count = 0。

## Token 边界

原始 token 只由启动环境变量传入。Launcher receipt 不保存原始 token，子进程命令行
也不包含 token。`run_frozen_evaluator_from_env_v1.py` 在子进程内存中将其交给 frozen
evaluator，并立即从环境删除。

## 终态保证

Watcher 不会以 `launched` 作为成功：

- 使用 `child.wait()` 等待 evaluator；
- evaluator return code 非零即写 `TERMINAL.json: FAIL`；
- return code 为零后还必须验证 `FORMAL_EXECUTION_RECEIPT.json`；
- receipt 中每个 artifact 都重新计算 SHA256；
- 全部通过才写 `TERMINAL.json: PASS`。

## 固定输入

- Execution manifest SHA256：
  `ee6264048ae4e5612aeca1d092d5ade9cb1f347ae3b54c4f06caf60ce56370c3`
- Execution adapter freeze SHA256：
  `6304bcbbfe4b5697b87f2079b75f6472f5c2254f57ef370519e7c0e289605b4e`
- Execution contract SHA256：
  `d77b6181f780c632fda05056b44aea2d7c9eec3715e24c80c3b19b777b852d55`
- Frozen evaluator SHA256：
  `d8a33a36309ec3363ce470b30228193e93af5784b1d6d739f16b5b11cfed4152`

正式结果仍只代表独立双受体 Docking 连续几何 surrogate，不代表实验结合或阻断真值。
