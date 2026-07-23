# V2.20 V1.3.3：冻结包测试夹具最小恢复

## V1.3.2 为什么被拒绝

V1.3.2 freeze `882f60a3...` 在冻结前的 43 项测试通过，但独立审查从最终冻结包
重新执行同一 launcher 时出现 2 failures 和 1 error。原因不是科学代码：测试夹具先
复制了已经包含 production freeze 和 sidecar 的 `ROOT`，随后又将同两个文件名追加
到 synthetic allowlist，得到 21 项但只有 19 项唯一值，触发 fail-closed。

该拒绝由 content-addressed review `eaf1ba9e...` 固定。V1.3.2 不得编辑、部署或重试。

## V1.3.3 唯一因果修复

`FinalizationLifecycleTests.fixture` 在复制包时仅排除两个精确文件：

```text
IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json
IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_3.json.sha256
```

随后由夹具创建自己的 freeze 和 sidecar。除此之外不忽略任何文件、目录、symlink
或 pycache。新增回归会：

1. 复制当前实现并创建完整 freeze 与 sidecar；
2. 从该完全冻结的包运行精确 `run_tests_v1_3_3.sh`；
3. 使用环境哨兵避免回归自身无限递归；
4. 要求完整 44 tests 和 `OK`。

## 不变范围

以下科学/执行核心与 V1.3.2、V1.3.1 字节一致：

```text
launchers/run_shared_fold_materialization_once_v1_3_1.sh
src/materialize_v220_shared_fold_calibration_v1_3_1.py
src/run_v220_contact_shared_fold_v1_3_1.py
src/v220_shared_calibration_artifact_v1.py
src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py
```

数据、split、初始状态、ESM2、架构、损失、优化器、超参数、校准算法、评价和 gates
均不改变。V1.3.3 的其他版本字符串变化只用于新的 fail-closed 生命周期命名。

## 冻结顺序

1. 冻结前运行 44 项测试，其中包含 fully-frozen nested regression；
2. 生成新的 implementation freeze 和精确 sidecar；
3. 从最终冻结包再次运行同一个 test launcher，要求 44/44 PASS；
4. 将该 post-freeze 日志放在 sibling evidence 并绑定哈希；
5. 此后包内不得修改任何字节。

Node1 Python 3.11.14 的 legacy102 + new44 仍是独立 Stage-A 批准后必须通过的门槛，
当前不得写成已有证据。Stage A 只允许五折 materialize/load-only，禁止训练。
