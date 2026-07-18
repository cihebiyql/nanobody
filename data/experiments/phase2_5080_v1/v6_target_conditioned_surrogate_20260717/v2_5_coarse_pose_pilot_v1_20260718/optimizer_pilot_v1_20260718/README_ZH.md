# V2.5 D-lane inner-only optimizer/loss pilot

本实验只使用 `outer0/inner0` 的 frozen inner whole-parent split，在 Node1 GPU1
串行比较少量优化器/损失配置。它不读取 outer-test 或 V4-F/test32，结果只用于
下一版预注册参数选择，不能作为 formal promotion 证据。

固定不变：

- D_SPLIT_PAIR 架构；
- ESM2-650M frozen；
- split、训练/评分 parents、输入表、contact labels、graph cache；
- marginal/pair 权重 `1.0/0.5`；
- batch size 8、gradient accumulation 2、BF16、clip 1.0；
- exact-min 输出。

比较六个预先列出的配置：baseline、16 epochs、低/高 lr、两组 Huber/weight-decay。

V1.1 首次真实执行在第二个 16-epoch variant 被冻结 inner manifest 的
`fixed_epochs=8` 正确拒绝。V1.2 不修改正式 split；它为每个 exploratory variant
复制相同 parent membership，只允许 `fixed_epochs` 字段发生变化，并保存 variant split hash。

运行文件：

```text
PLAN.json
run_inner_optimizer_pilot_v1.py
```

远端输出必须包含：

```text
STATUS.json
RESULTS.tsv
TERMINAL.json
variants/<name>/RESULT.json
```
