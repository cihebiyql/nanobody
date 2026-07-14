# PVRIG V3 P2 Docking Gold V1.2 family-aware 校准结果

## 结论

```text
FAIL_V1_2_FAMILY_CALIBRATION_NOT_FROZEN
pose_rule_threshold_freeze_eligible=false
formal_eligible=false
dual_receptor_r_gold_freeze_eligible=false
training_label_release_eligible=false
```

失败 acceptance gates：`['bootstrap']`。
本产物只涉及 8X6B docking 单一 pose ensemble 上的计算几何校准；两个 baseline 是同一 pose 的 post-hoc scoring channel，不是独立双 receptor docking。

## 中心阈值与单位

| channel | metric | L raw | U raw | L transformed | U transformed | raw unit | transform |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| canonical_shared | H | 0.49107143 | 0.61160714 | 0.49107143 | 0.61160714 | unitless_fraction | identity |
| 8x6b | O | 400 | 489 | 5.9939614 | 6.1944054 | residue_pair_count | log1p |
| 8x6b | P | 0.39877301 | 0.4587156 | 0.39877301 | 0.4587156 | unitless_fraction | identity |
| 9e6y | O | 398 | 487 | 5.9889614 | 6.1903154 | residue_pair_count | log1p |
| 9e6y | P | 0.39658849 | 0.46721311 | 0.39658849 | 0.46721311 | unitless_fraction | identity |

O 的 raw cutpoint 单位是 residue-pair count；membership 中只执行一次 `log1p`，禁止对已变换 cutpoint 再取对数。

## 中心结果

- 11 个 success anchors：`{'G1': 4, 'G2': 1, 'G3': 6, 'G4': 0, 'G5': 0}`。
- 47 个全部 case：`{'G1': 12, 'G2': 6, 'G3': 28, 'G4': 1, 'G5': 0}`。
- LOFO passed：`True`；macro-family G1-G3 recall=`1`；tier shift<=1 为 `11/11`。
- mutant paired deltas：29；median(delta_R)=`-0.131217`；不产生 binary negative label。
- sensitivity grid：54 行；固定 54 组合；所有行 `best_row_selected=false`。

## Bootstrap

- seed=20260714，B=2000。
- threshold rows=20000；anchor evaluation rows=22000。
- undefined replicates=33；U==L 被记录为 undefined，不使用 step membership。
- modal probability>=0.70：`7/11`，要求 >=9。
- each-family retention gate：`True`。

### 未通过 modal/retention 的 anchors

- `case02_pos_04_PVRIG-38` family=38 modal=G3 p_modal=0.4565 P(G1-G3)=0.9830
- `case02_pos_05_PVRIG-39` family=39 modal=G3 p_modal=0.5035 P(G1-G3)=0.9835
- `case02_pos_06_20H5` family=20 modal=G1 p_modal=0.5845 P(G1-G3)=0.9830
- `case02_pos_09_39H4` family=39 modal=G3 p_modal=0.5330 P(G1-G3)=0.9835

## Acceptance summary

| gate | passed |
| --- | --- |
| upstream_provenance | `True` |
| pose_and_metric_closure | `True` |
| atom_only_inventory | `True` |
| threshold_validity | `True` |
| family_balance | `True` |
| sensitivity_grid | `True` |
| lofo | `True` |
| bootstrap | `False` |
| mutant_sensitivity | `True` |
| claim_boundary | `True` |

## Artifact hashes

| artifact | rows | SHA256 |
| --- | ---: | --- |
| `pvrig_v1_2_family_rules.json` |  | `7efdf44939816b7c81d3f968c661f50c381b86319a6535cdd537035d6f95b4c8` |
| `pvrig_v1_2_pose_scores.csv` | 752 | `0447b8b5c83e3d8eed9aa491719c55bc3ab3ea01554654288b189cd06b33155e` |
| `pvrig_v1_2_calibration_run_scores.csv` | 47 | `eee5cf099b762e45d4550f1e6d53be80aefb8f011163cf89fda13e70a44f5d5e` |
| `pvrig_v1_2_family_lofo.csv` | 11 | `bb21526b21f31c416e6e0984c0ca40a963eb24088c86dcbf9dfe8d8693d20f44` |
| `pvrig_v1_2_bootstrap_thresholds.csv` | 20000 | `05d9c54e68ce8c02e3f8e217df107551d8545f04ef2262a0c582d036bc62d449` |
| `pvrig_v1_2_bootstrap_anchor_evaluations.csv` | 22000 | `97bd09f075c5e33c562b51a73acbcfb05589b714ba6cfc1e221dedfa8496a553` |
| `pvrig_v1_2_fingerprint_diagnostics.csv` | 376 | `dc7748d56a4aa6d1cc4784c23f811bef618144fd4d2b5c6e356ceae65c9a3d7a` |
| `pvrig_v1_2_mutant_paired_deltas.csv` | 29 | `e2f3ffb3d28cf01bb80a26a71bfdfb9a1a2389da083f49d81f1b43058cb320ff` |
| `pvrig_v1_2_robustness_grid.csv` | 54 | `d394f55288a18bafd51f487e02bf98d1fa1afe14a4c8adc7dda72eca246da050` |

> Claim boundary: Computational geometry teacher calibration on fixed Top-8 poses from one 8X6B docking ensemble with two post-hoc scoring baselines; not binder, affinity, experimental blocking, independent dual-receptor docking, or formal-holdout truth.
