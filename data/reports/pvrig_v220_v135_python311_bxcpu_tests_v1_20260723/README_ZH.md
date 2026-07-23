# V2.20 V1.3.5 技术恢复验证证据

状态：`PASS_V1_3_5_EXACT_148_PENDING_INDEPENDENT_REVIEW`。

- 新版本包未修改 V1.3.4；
- preflight 绑定 legacy launcher 实际 SHA `c3bae8a5...`；
- receipt builder 真实 CLI 使用 `--v1-3-5-test-log`；
- 本地 new46 通过；
- bxcpu Python 3.11.14 legacy102 + new46 = 148 通过；
- post-freeze 运行前后包内 20 个文件逐文件哈希不变；
- 未训练、未部署、未授权 Stage-A。

下一步仅允许新的独立审查。只有独立审查明确授权后，才能另行决定是否执行 Stage-A。
