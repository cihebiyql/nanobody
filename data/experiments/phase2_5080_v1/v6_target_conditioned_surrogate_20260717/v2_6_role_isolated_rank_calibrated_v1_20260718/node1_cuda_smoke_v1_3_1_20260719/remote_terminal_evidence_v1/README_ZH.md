# Node1 V2.6 CUDA smoke 终态证据

- V1.2：`FAIL_CLOSED`，真实训练后触发 `be_scalar_trajectory_mismatch`，未晋级。
- V1.3：`FAIL_CLOSED`，依赖路径替换错误导致导入失败，未开始训练、未晋级。
- V1.3.1：`PASS`，BF16/CUDA 真实 smoke 完成。

核心结果：

- B/E 20 个 step 的 scalar trajectory hash 全部精确一致；最大共享参数差 `0.0`。
- F 20 个 step 全部通过 post-lambda gradient budget；违规 `0`。
- `R_dual = min(R8,R9)` 最大误差 `0.0`。
- 40 个 microbatch、累积因子 2、20 个 optimizer step。
- V4-F/test32、score truth、outer metrics、candidate Docking pose 输入访问均为 `0`。

该证据只证明独立 8X6B/9E6Y computational Docking-geometry surrogate 的 CUDA/BF16 技术门通过，不证明结合、Kd、实验阻断或 Docking Gold。下一步仍需由独立 pilot gate 验证并启动正式 pilot。
