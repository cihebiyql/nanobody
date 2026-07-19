# V2.6 `delta_noise` 绑定

本目录只冻结下一版评估可引用的测量噪声容差，不修改 V2.6 prereg skeleton，也不重写 V2.5 结果。

公式：

```text
delta_noise
= clip(
    median_candidate(MAD_seed(Rdual))
    × 1.4826
    × sqrt(2),
    0.01,
    0.03
  )
```

数据只使用非自适应的 V4-D `OPEN_TRAIN` 三 seed完整候选。V4-H 被排除，因为其 seed2/3 是看过 seed917 后才选择的高分子集，不能提供无偏的全范围噪声容差。

`MAD` 先在每个候选的三个同 seed `Rdual=min(R8,R9)` 内计算，再跨候选取中位数；候选是统计单位，seed 不是独立样本。

唯一权威数值见 `V2_6_DELTA_NOISE_BINDING.json`。
