# V2.5 label-free coarse-pose 特征原型

状态：独立的下一代信息增量试验，不替代、修改或阻塞 V2.4。

## 目标与边界

输入仅为：

1. 候选 VHH 的冻结单体 PDB 与 CDR1/2/3 序列注释；
2. 公开 8X6B/9E6Y 中提取的固定 PVRIG 单体；
3. 冻结的 PVRIG 界面与 hotspot mask。

特征生成不读取候选 Docking pose、Docking 分数、teacher label 或 V4-F。输出只是低分辨率
刚体几何 proxy，不能解释为结合概率、Kd、实验阻断概率或 Docking Gold。

## 方法

VHH 以三条 CDR 的质心为原点，以 framework→CDR 方向和 CDR3 方向建立内禀坐标系；
PVRIG 以界面质心为原点，以蛋白中心→界面方向和 hotspot 偏置建立内禀坐标系。这样输入
整体平移或旋转不会改变输出。

对每个受体使用同一组 300 个 pose 参数：

```text
25 个 approach axes（0/20/40/60 度圆锥）
× 4 个 roll
× 3 个界面距离（5.0/6.5/8.0 Å）
```

每个 pose 只用 CA 层面的形状/接触、热点邻近、氨基酸电荷 proxy、clash、CDR3 朝向打分。
固定门限仅用于计算“可接受 pose 数”，没有根据 Docking label 调参。

## 36 维输出

每个受体 14 维（共 28 维）：pose 数、可接受数/比例、最佳 composite、Top-20 均值/标准差/
IQR/熵、最佳 shape/hotspot/charge/clash/CDR-contact/CDR3 orientation。

双受体 8 维：共同可接受 pose 数/比例、Jaccard、最佳双受体最小分、Top-20 双受体最小分的
均值/标准差、最佳 pose 的构象 gap、同 pose 参数下的构象分数相关性。

## 验证顺序

1. 单元测试先验证 300-pose、36D、finite 与独立刚体旋转不变性；
2. 从 V4-H label-free research pool 与 monomer manifest 构建确定性 20 条 smoke panel；
3. 生成特征并记录候选级 CPU 耗时；
4. 对 3 条真实 PDB 再做整体旋转/平移并复算；
5. **最后**才用开放 teacher 表做小样本描述性相关性；它不参与筛选、特征构造或门限选择。

## 限制

- 只扫描界面中心附近，不是完整全表面 docking；
- CA 形状与残基电荷是粗 proxy，不含溶剂、侧链转子或能量最小化；
- 20 条 smoke 的相关性只用于确认“是否有非恒定信号”，不能用于模型选择；
- 正式使用前必须对全部 open-development parents 做 whole-parent OOF 增量评估。

## 正式 V2.5 的压缩合同

36D 原始表用于几何审计，不直接送入主 stack。主候选使用预定义、与受体命名交换对称的 12D：

```text
best composite: mean / min / gap
Top-20 composite mean: mean / min / gap
best shape min
best hotspot min
best CDR3 orientation min
dual common-acceptable fraction
dual acceptable Jaccard
dual Top-20 min-score std
```

备选方案是 8D PCA，但 scaler、常数列过滤和 PCA 都必须只在每个 inner-train parent 集上拟合，
再变换 inner-validation / outer-test。禁止在全部 1,507 行或 outer-test 上拟合，也禁止根据本 smoke
的 19 条开放 label 选择原始列或 PCA 维度。

## Smoke20 实测结果

```text
候选数                         20
每候选/每受体 pose             300
原始特征维数                   36
总 CPU 时间                    4.40 s
平均每候选                     0.218 s
最大每候选                     0.243 s
最大 RSS                       约 35 MB
finite                         20/20
真实 VHH 旋转不变性最大误差    4.44e-16
固定 target 旋转不变性最大误差 6.94e-15
```

方差审计发现两个 `pose_count` QC 列为常数、两个 Top-20 entropy 列近常数；其余 32 列在
Smoke20 上有可测方差。12D 压缩表无常数列且全部 finite。

特征冻结后才与开放 teacher 表做描述性连接，20 条中 19 条可连接。按 36 个原始特征取绝对值
最大的单特征 Spearman：R8 为 0.405、R9 为 0.521、Rdual 为 0.333。由于同时查看了多个特征、
样本仅 19 条且没有 whole-parent CV，这些数字只能说明存在非恒定信号，不可作为提升证据、
门限选择或压缩列选择依据。

## Open1507 完整物化

已对正式 open-development cohort 的全部 1,507 条生成相同的 label-free 特征：

```text
V4-D label-free monomer             226
V4-H label-free monomer            1,281
parent clusters                       31
raw36D / symmetric12D coverage    1,507/1,507
wall time                          393.23 s
feature-loop time                  353.54 s
mean feature-loop time/candidate     0.235 s
maximum RSS                         45 MB
```

完整表没有运行任何标签相关性、模型训练或 performance comparison。正式 OOF 挑战者边界见：

```text
FORMAL_OPEN_ONLY_WHOLE_PARENT_OOF_CHALLENGER_PLAN_ZH.md
OOF_CHALLENGER_CONTRACT_V1.json
prepared/open1507_v1/DELIVERY_RECEIPT.json
```
