# V2.20 V1.3.4：Python 3.11 exact-file unittest 恢复

## V1.3.3 为什么失败

V1.3.3 在 bxcpu 的真实 Python 3.11.14 环境执行 legacy102 时，标准命令
`python -m unittest tests/test_x.py` 将路径转换为 `tests.test_x`。该环境存在无关的
site-packages `tests` 包，13 个冻结测试模块全部被 namespace shadowing，得到
13 个 `ModuleNotFoundError`；没有进入测试体，也没有启动训练。V1.3.3 不修改、不重试。

## V1.3.4 唯一因果修复

新增 `src/run_unittest_file_paths_v1_3_4.py`：

1. 只接受显式 allowlist 中、位于 `tests/` 直属目录的 regular `.py` 文件；
2. 拒绝绝对路径、重复项、symlink 和路径逃逸；
3. 用 `importlib.util.spec_from_file_location` 赋予私有模块名；
4. 用 `loadTestsFromModule` 收集，不执行 discovery，也不导入 `tests.*`；
5. legacy102 与 new44 两个 launcher 都绑定同一 runner SHA，并保留精确文件哈希、
   精确计数、`OK` 与 Python 3.11.14 marker gate。

## 科学范围不变

以下五个执行核心与 V1.3.3 字节一致：

- `launchers/run_shared_fold_materialization_once_v1_3_1.sh`
- `src/materialize_v220_shared_fold_calibration_v1_3_1.py`
- `src/run_v220_contact_shared_fold_v1_3_1.py`
- `src/v220_shared_calibration_artifact_v1.py`
- `src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py`

数据、split、模型、loss、optimizer、阈值、超参数、初始状态和训练计划均未改变。
V1.3.4 当前只允许 146 项测试与五折 materialize/load-only Stage-A；禁止训练。
