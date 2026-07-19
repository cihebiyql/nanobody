# V2.6 real1507 integration V1.2

这是 V1.1 的最小审查修复版，仍然是非启动、CPU 已测试的集成冻结件。

只修复四项：

1. 运行时不再接受 caller 自报的单 anchor SHA；trainer 硬绑定 25-anchor set receipt 的固定 SHA，并从 receipt 选择当前 outer/inner anchor。
2. fold-local calibration 只能从冻结 inner/outer manifest、冻结 teacher、checkpoint receipt 和 prediction receipt 派生；candidate/fold/seed/truth/prediction 不再由 caller 直接声明。
3. optimizer state SHA 使用稳定参数名排序，不再使用 Python `id(parameter)`。
4. 保留 V1.1 的 post-lambda F 梯度预算、精确不等权 accumulation、物理/逻辑 GPU 映射和逐 step evidence hash。

证据边界仍是独立 8X6B/9E6Y computational Docking geometry surrogate；不是结合、Kd、实验阻断或 Docking Gold。

本冻结件没有访问 V4-F/test32、outer metrics 或 score truth，也没有启动远程训练。下一门是 Node1 GPU1 BF16 20-step real1507 smoke。
