# V2.20 V1.3.4 独立 Stage-A 审查：FAIL CLOSED

## 结论

```text
FAIL_V1_3_4_STAGE_A_DEPLOYMENT_NOT_AUTHORIZED
```

V1.3.4 的 exact-file unittest 适配器本身有效：

- 本地 Python 3.10.12：legacy 102 与新 44 均通过；
- bxcpu Python 3.11.14：冻结的 combined launcher 精确运行 102+44=146，全部通过；
- 没有创建 checkpoint、fold predictions、RESULT 或训练授权文件，训练未启动。

但是，冻结后的 Stage-A 路径存在两个确定性阻断错误，因此 **146 tests PASS
不等于 Stage-A 可部署**：

1. `run_phase1_preflight_node1_v1_3_4.sh` 仍绑定 V1.3.3 legacy launcher 的 SHA
   `e7659f...`，而 V1.3.4 launcher 的真实 SHA 是 `c3bae8...`。Stage-A 会在
   `sha256sum` gate 直接失败。
2. `build_v220_v1_3_4_preflight_receipt.py` 的 CLI 仍声明
   `--v1-3-3-test-log`，生成属性 `v1_3_3_test_log`；但 `build()` 读取
   `args.v1_3_4_test_log`。如果执行到 receipt builder，会触发 `AttributeError`。

新 44 项测试没有覆盖这两个错误：测试只检查 launcher 名称存在，没有比较绑定 SHA；
receipt builder 测试直接手工构造带 `v1_3_4_test_log` 的 Namespace，没有走真实 CLI
parser。

## 已通过的独立检查

- implementation freeze SHA 与 sidecar 精确一致；
- package regular-file allowlist 精确闭合，无 symlink 或额外文件；
- implementation hashes 全部一致；
- 五个执行核心与 V1.3.3、V1.3.1 三方逐字节一致；
- training template 经纯版本字符串归一化后与 V1.3.3 完全一致；
- 因而数据、模型、split、loss、optimizer、阈值和超参数没有改变。

## 处置

V1.3.4 不得修改、不得部署、不得训练、不得重用同版本重试。必须另起新版本，至少：

1. 更新 preflight 对 V1.3.4 legacy launcher 的真实 SHA；
2. 将 receipt builder CLI 与 `args.v1_3_4_test_log` 统一；
3. 增加真实 preflight hash binding 与真实 CLI parser 的回归测试；
4. 再做一次全新 implementation freeze 和独立审查。

本目录只包含审查证据，不包含训练产物，也不授权训练。
