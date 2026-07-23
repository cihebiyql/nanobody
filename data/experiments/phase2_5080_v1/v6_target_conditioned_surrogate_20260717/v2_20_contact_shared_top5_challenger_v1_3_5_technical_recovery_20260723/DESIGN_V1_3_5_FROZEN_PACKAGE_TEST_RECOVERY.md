# V2.20 V1.3.5：Stage-A preflight 绑定与 CLI 恢复

## V1.3.4 为什么被拒绝

独立审查确认 V1.3.4 虽然通过 Python 3.11.14 的 legacy102 + new44 精确文件测试，
但其 Stage-A preflight 存在两项确定性阻断：

1. preflight 绑定的 legacy launcher SHA 过期，实际冻结文件为
   `c3bae8a57009bb05106c74c3fc0e6d4d614c198e96cea6ad25633a455e5b73e6`；
2. receipt builder 暴露 `--v1-3-3-test-log`，但 `build()` 读取
   `args.v1_3_4_test_log`，真实 CLI 到达时会触发 `AttributeError`。

V1.3.4 保持冻结，不修改、不重试、不得训练或部署。

## V1.3.5 唯一因果修复

- 原样保留 V1.3.4 的 exact-file loader 与 legacy102 launcher 字节；
- preflight 绑定 legacy launcher 的实际 SHA；
- receipt builder 与 preflight launcher 统一使用
  `--v1-3-5-test-log` / `args.v1_3_5_test_log`；
- 新增两条回归：实际文件 SHA 等值、真实 subprocess CLI parse/build；
- 新测试计数 46，legacy102 + new46 合计 148。

五个执行核心、数据、模型、split、loss、optimizer、阈值和全部超参数保持不变。
V1.3.5 当前仅允许测试与独立审查；禁止训练和部署。
