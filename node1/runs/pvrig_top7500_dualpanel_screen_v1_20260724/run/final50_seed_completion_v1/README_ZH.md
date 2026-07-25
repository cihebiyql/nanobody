# Final50统一四seed补跑清单

共同seed集合固定为 `42,917,1931,3047`。只有缺失的candidate×seed×conformation组合需要运行；每个seed必须分别完成`8x6b`和`9e6y`两个构象。

- Final50：50条；
- 已满足共同四seed：22条；
- 需要补跑：28条；
- 缺失seed：所有待补候选均缺少42和3047；
- 新增docking jobs：28×2 seeds×2 conformations＝112；
- 9条已有额外seed 3253，该证据保留但不能替代共同seed集合。

`FINAL50_MISSING_SEED_JOBS_RUNNABLE.tsv`沿用冻结HADDOCK3协议、monomer、受体、AIR restraint和protocol core hash，可作为补跑输入。本清单本身不表示这些jobs已经运行。
