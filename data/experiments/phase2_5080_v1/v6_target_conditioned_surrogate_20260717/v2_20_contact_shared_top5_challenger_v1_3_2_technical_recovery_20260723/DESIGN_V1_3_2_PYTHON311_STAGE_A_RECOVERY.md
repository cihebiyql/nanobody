# V2.20 V1.3.2：Python 3.11 Stage-A 最小技术恢复

## 失败边界

V1.3.1 在 Node1 的 Python 3.11.14 环境中，将 13 个绝对测试文件路径直接传给
`python -m unittest`。Python 3.11 将这些路径解释为模块名，产生 13 个
`ModuleNotFoundError`。失败发生在共享校准、模型构建、优化器和训练之前；该版本
已经终止，禁止同版本重试。

## 唯一行为改动

旧调用：

```text
python -m unittest /absolute/path/tests/test_a.py ...
```

V1.3.2 调用：

```text
cd LEGACY_ROOT
python -m unittest tests/test_a.py ... tests/test_m.py -v
```

适配器固定且逐一校验 13 个相对路径及其 SHA256；同时检查 `tests/` 顶层的
`test_*.py` 文件集合恰好等于这 13 个文件。适配器禁止 `discover`，因此不会递归
执行未被哈希绑定的嵌套测试。

V1.3.2 自身的技术测试 launcher 也继承了相同的绝对路径调用形态；在任何正式
Stage-A 部署前已将它改为 `cd PACKAGE_ROOT` 后传入两个精确相对路径，并逐一校验
两份测试文件 SHA256。因此本版本的最小因果修复范围是两个 Stage-A unittest
launcher，而不是科学代码、校准或训练路径。

## 不变的核心

以下 V1.3.1 文件保留原文件名和原字节：

```text
launchers/run_shared_fold_materialization_once_v1_3_1.sh
src/materialize_v220_shared_fold_calibration_v1_3_1.py
src/run_v220_contact_shared_fold_v1_3_1.py
src/v220_shared_calibration_artifact_v1.py
src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py
```

数据、split、seed43 初始状态、ESM2、架构、损失、优化器、batch 顺序、所有超参、
lambda 网格/选择、冲突门、评价、bootstrap、核心 gates 和 claim boundary 均不变。

## 两阶段授权

当前只允许冻结并独立审核 Stage A。获得独立批准后，Stage A 可运行：

1. Node1 Python 3.11.14 上精确 13 文件、102 tests；
2. V1.3.2 新增回归测试；
3. 五个 fold 各一次共享校准 materialize；
4. 五个 fold 各一次 load-only 验证；
5. 验证 optimizer/backward/training/output 均不存在并签发 receipt。

Stage A 不得调用 arm training runner。Stage B 仍需成功的 Stage-A receipt、独立批准、
finalizer 和最终授权文件；在此之前训练不被授权。

## 验收

- Python 3.11.14 精确运行 102 tests 并 `OK`；
- 不含 `unittest discover`；
- 额外嵌套 `test_*.py` 不会执行；
- 13 个文件任一增删或哈希变化均 fail-closed；
- V1.3.1 核心五文件与原包逐字节一致；
- V1.3.1 failure receipt 被绑定，且 `same_version_retry_allowed=false`；
- Stage A 完成前不存在 training authorization。
