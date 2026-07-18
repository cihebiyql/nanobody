# V5-RC OPEN_TRAIN226 Contact-Proxy 嵌套验证结果

状态：`COMPLETE_OPEN_TRAIN226_CONTACT_PROXY_NESTED_COMPARISON`

## 证据边界

OPEN_TRAIN-only development comparison of label-free monomer/sequence proxies for computational docking contact intermediates and R_dual_min; not binding, affinity, competition, experimental blocking, Docking Gold, or submission authority.

held-out candidate 的真实 Docking contact 从未作为模型输入；它只在 outer-fold 预测固定后用于 contact-proxy 诊断。

## 主结果

| 模型 | Spearman | Parent-centered | Macro-parent | MAE | Top20 recall |
|---|---:|---:|---:|---:|---:|
| C0_structure_linear | 0.6868 | 0.2818 | 0.2377 | 0.02877 | 0.4348 |
| C1_structure_physchem_random_relu | 0.6643 | 0.2655 | 0.2312 | 0.02808 | 0.3696 |
| C2_predicted_contact_bottleneck | 0.6668 | 0.2782 | 0.1998 | 0.02913 | 0.5217 |
| C3_structure_plus_predicted_contact_stack | 0.6655 | 0.2780 | 0.1919 | 0.02918 | 0.5217 |
| C4_structure_nonlinear_plus_predicted_contact_stack | 0.6651 | 0.2791 | 0.1878 | 0.02916 | 0.5217 |

## Contact proxy 可预测性

- contact target 数：101
- target-wise Spearman 中位数：0.2620
- target-wise Spearman 均值：0.2689
- standardized MSE：1.0845

## 决策

`FAIL_KEEP_C0_STRUCTURE_LINEAR`

只有同时超过 C0，并且相对同容量 C1 仍有优势，才能把增益归因于 contact supervision。

