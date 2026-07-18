# V2.2 claim-boundary 技术性 supersession

V2.2 只修复 V2.1 calibration observation 与 manifest 的 `claim_boundary` 精确字符串不一致。

冻结不变：

- 1507 条 adaptive-multiseed teacher；
- outer-fold-0 的 8 个 hash-bound batch；
- grid `[0.25,0.5,0.75,1.0,1.5,2.0,3.0,5.0,7.5,10.0]`；
- median gate `5%–15%`；
- per-batch maximum gate `<=30%`；
- pair:marginal ratio `0.5`；
- base trainer、模型、seed、BF16 和所有输入；
- V2.1 已观测权重：C=`1.5/0`，D=`1.0/0.5`。

V2.2 必须在新 bundle/runtime 下重新运行 calibration，不复用或改写 V2.1 observation。新 wrapper 直接输出与 manifest 完全一致的 claim；runner 和 materializer 都进行 exact equality 验证，并额外要求选中权重与 V2.1 一致。

V2.2 ready manifest 和 implementation freeze 仅授权后续 tiny smoke。当前任务明确禁止启动 formal training。
