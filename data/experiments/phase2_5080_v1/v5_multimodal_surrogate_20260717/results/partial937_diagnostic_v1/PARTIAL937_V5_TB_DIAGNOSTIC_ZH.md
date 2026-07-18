# PVRIG V5-TB partial937 冻结外部诊断

Partial active-campaign development diagnostic with controller completion-order and technical-success selection bias; not independent validation, not model-selection authority, not Docking Gold, binding, affinity, competition, or experimental blocking evidence.

## 结果

| model | Spearman | parent-centered | macro-parent | MAE | NDCG | Top20 recall | ΔSpearman vs B1 CI |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0_train_mean | 0.0000 | 0.0028 | 0.0000 | 0.04034 | 0.97453 | 0.2713 | -0.5369 [-0.6185,-0.3723] |
| B1_structure_direct | 0.5667 | 0.1977 | 0.1995 | 0.03365 | 0.98443 | 0.4574 | reference |
| B2_dual_receptor_min | 0.5698 | 0.2012 | 0.2039 | 0.03400 | 0.98452 | 0.4468 | +0.0030 [-0.0028,+0.0102] |
| B3_structure_plus_physchem | 0.5697 | 0.2041 | 0.1961 | 0.03357 | 0.98449 | 0.4468 | +0.0027 [-0.0032,+0.0104] |
| B4_direct_dual_convex | 0.5676 | 0.1986 | 0.2018 | 0.03355 | 0.98448 | 0.4628 | +0.0009 [-0.0012,+0.0031] |
| B5_top20_ridge_classifier | 0.4879 | 0.1151 | 0.1058 | 0.03652 | 0.98293 | 0.4628 | -0.0708 [-0.1851,-0.0152] |
| B6_within_parent_pairwise_ridge | 0.2504 | -0.1300 | -0.0913 | 0.03939 | 0.97933 | 0.2926 | -0.3091 [-0.5469,-0.1266] |

## 限制

- 这是 active campaign partial snapshot，存在完成顺序和技术成功选择偏差。
- 本结果未用于选择模型、超参数、阈值或输入特征。
- 无论结果方向如何，都不能称为 independent validation 或 formal PASS。

