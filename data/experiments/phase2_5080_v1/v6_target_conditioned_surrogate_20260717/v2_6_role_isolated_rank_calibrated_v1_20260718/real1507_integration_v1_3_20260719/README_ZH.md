# V2.6 real1507 integration V1.3

V1.2 的真实 CUDA smoke 在 B/E step 0 fail-closed。初始参数、batch、rank cache 均一致，但 B 使用 clean-B forward，E 使用 E-capable forward，控制变量没有保持相同的标量计算图。

V1.3 只做一个方法学修复：B、E、F 全部使用同一个 E-capable model 和 `MODEL_LANE_E` 标量 forward；B 仍然只运行 scalar optimizer，E 运行严格 detached contact optimizer，F 运行 shared-gated contact transfer。这样 B/E 的区别只剩优化器角色，不再是模型 forward 图。

保留 V1.2 全部 provenance、anchor-set、OOF receipt、exact accumulation、post-lambda budget 和 stable-name optimizer hash。GPU driver 还必须启用 CUDA deterministic algorithms、CUBLAS workspace、关闭 TF32，并保持 exact trajectory hash gate，不放宽阈值。
