# Phase 2 V1 训练评估报告

Updated: 2026-07-09

## 结论边界

本报告对应第一版 GPU 可训练架构 `VHH-Ag CrossContactNetV1`。它已经在 RTX 5080 上完成一次 site + weak-contact + pair-binding 训练/评估。
当前 contact head 使用 ZYM paratope/epitope mask 构造 weak contact proxy，不等价于真实 heavy-atom contact-map；真实结构 contact-map 训练将在 V2 接入 `prepared/structure_contact_pairs_mvp_v1.csv` 的序列映射后完成。

## 环境

```json
{
  "device": "cuda",
  "torch": "2.13.0+cu130",
  "cuda_available": true,
  "cuda_version": "13.0",
  "gpu_name": "NVIDIA GeForce RTX 5080",
  "best_epoch": 7,
  "run_id": "phase2_v1_20260709_5080_seed7"
}
```

## 配置

```json
{
  "root": "/mnt/d/work/抗体/data",
  "out_root": "experiments/phase2_5080_v1",
  "seed": 7,
  "d_model": 192,
  "layers": 3,
  "heads": 4,
  "dropout": 0.1,
  "max_vhh_len": 160,
  "max_antigen_len": 512,
  "batch_size_site": 24,
  "batch_size_pair": 48,
  "epochs": 8,
  "lr": 0.0002,
  "weight_decay": 0.01,
  "contact_pos_per_sample": 32,
  "contact_neg_per_sample": 128,
  "site_loss_weight": 1.0,
  "contact_loss_weight": 0.5,
  "pair_loss_weight": 1.0,
  "use_amp": true
}
```

## 最终 Test 指标

```json
{
  "checkpoint": "/mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v1_20260709_5080_seed7/best_checkpoint.pt",
  "dataset_sizes": {
    "pair_test": 954,
    "pair_train": 3345,
    "pair_val": 552,
    "site_test": 240,
    "site_train": 851,
    "site_val": 139
  },
  "pair_test": {
    "pair_auprc": 0.26837667444110264,
    "pair_auroc": 0.5152952847805788,
    "pair_f1": 0.33984962406015035,
    "pair_fn": 127.0,
    "pair_fp": 312.0,
    "pair_n": 954.0,
    "pair_positive_rate": 0.25157232704402516,
    "pair_precision": 0.26588235294117646,
    "pair_recall": 0.4708333333333333,
    "pair_tn": 402.0,
    "pair_tp": 113.0
  },
  "pair_test_by_negative_type": {
    "N1_easy_cross_antigen": {
      "auprc": 0.512790416307883,
      "auroc": 0.5035416666666667,
      "f1": 0.49130434782608695,
      "fn": 127.0,
      "fp": 107.0,
      "n": 480.0,
      "positive_rate": 0.5,
      "precision": 0.5136363636363637,
      "recall": 0.4708333333333333,
      "tn": 133.0,
      "tp": 113.0
    },
    "N2_same_family_hard_antigen": {
      "auprc": 0.5425861236323274,
      "auroc": 0.5334757834757835,
      "f1": 0.5,
      "fn": 127.0,
      "fp": 99.0,
      "n": 474.0,
      "positive_rate": 0.5063291139240507,
      "precision": 0.5330188679245284,
      "recall": 0.4708333333333333,
      "tn": 135.0,
      "tp": 113.0
    },
    "N3_framework_similar_hard_vhh": {
      "auprc": 0.5149205547031974,
      "auroc": 0.5093229166666666,
      "f1": 0.4923747276688453,
      "fn": 127.0,
      "fp": 106.0,
      "n": 480.0,
      "positive_rate": 0.5,
      "precision": 0.5159817351598174,
      "recall": 0.4708333333333333,
      "tn": 134.0,
      "tp": 113.0
    }
  },
  "pair_val_by_negative_type": {
    "N1_easy_cross_antigen": {
      "auprc": 0.5436261777741123,
      "auroc": 0.5148284250297603,
      "f1": 0.4609665427509294,
      "fn": 77.0,
      "fp": 68.0,
      "n": 278.0,
      "positive_rate": 0.5,
      "precision": 0.47692307692307695,
      "recall": 0.4460431654676259,
      "tn": 71.0,
      "tp": 62.0
    },
    "N2_same_family_hard_antigen": {
      "auprc": 0.5809614836577944,
      "auroc": 0.538449240607514,
      "f1": 0.4787644787644788,
      "fn": 77.0,
      "fp": 58.0,
      "n": 274.0,
      "positive_rate": 0.5072992700729927,
      "precision": 0.5166666666666667,
      "recall": 0.4460431654676259,
      "tn": 77.0,
      "tp": 62.0
    },
    "N3_framework_similar_hard_vhh": {
      "auprc": 0.5408978377015337,
      "auroc": 0.4926763625071166,
      "f1": 0.4492753623188406,
      "fn": 77.0,
      "fp": 75.0,
      "n": 278.0,
      "positive_rate": 0.5,
      "precision": 0.45255474452554745,
      "recall": 0.4460431654676259,
      "tn": 64.0,
      "tp": 62.0
    }
  },
  "pvrig_prediction_rows": 50,
  "site_test": {
    "epitope_auprc": 0.15410052732313168,
    "epitope_auroc": 0.6533547648581988,
    "epitope_f1": 0.1935106856634016,
    "epitope_fn": 1856.0,
    "epitope_fp": 27126.0,
    "epitope_n": 67956.0,
    "epitope_positive_rate": 0.0784772499852846,
    "epitope_precision": 0.11361631212626214,
    "epitope_recall": 0.65197824864054,
    "epitope_tn": 35497.0,
    "epitope_tp": 3477.0,
    "paratope_auprc": 0.6244340297865512,
    "paratope_auroc": 0.9031712679368745,
    "paratope_f1": 0.5937678673527731,
    "paratope_fn": 661.0,
    "paratope_fp": 5023.0,
    "paratope_n": 29287.0,
    "paratope_positive_rate": 0.16440741625977395,
    "paratope_precision": 0.4526533725618394,
    "paratope_recall": 0.8627206645898234,
    "paratope_tn": 19449.0,
    "paratope_tp": 4154.0,
    "weak_contact_auprc": 0.6862518966648451,
    "weak_contact_auroc": 0.9073526975666296,
    "weak_contact_f1": 0.6053486997635933,
    "weak_contact_fn": 3551.0,
    "weak_contact_fp": 1791.0,
    "weak_contact_n": 38368.0,
    "weak_contact_positive_rate": 0.1993327773144287,
    "weak_contact_precision": 0.6958220108695652,
    "weak_contact_recall": 0.5356956066945606,
    "weak_contact_tn": 28929.0,
    "weak_contact_tp": 4097.0
  }
}
```

## 训练历史

| epoch | train_loss | val_paratope_auprc | val_epitope_auprc | val_weak_contact_auprc | val_pair_auprc | val_pair_auroc |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3.3660 | 0.5854 | 0.1439 | 0.6279 | 0.2675 | 0.5051 |
| 2 | 3.1139 | 0.6174 | 0.1487 | 0.6686 | 0.2718 | 0.5113 |
| 3 | 3.0484 | 0.6258 | 0.1524 | 0.6818 | 0.2815 | 0.5149 |
| 4 | 3.0245 | 0.6405 | 0.1550 | 0.6937 | 0.2867 | 0.5296 |
| 5 | 2.9937 | 0.6489 | 0.1602 | 0.7022 | 0.2872 | 0.5126 |
| 6 | 2.9456 | 0.6622 | 0.1686 | 0.7168 | 0.2728 | 0.5094 |
| 7 | 2.9109 | 0.6733 | 0.1814 | 0.7329 | 0.3120 | 0.5151 |
| 8 | 2.8539 | 0.6672 | 0.1884 | 0.7342 | 0.2877 | 0.4996 |

## PVRIG Top 候选 Phase2 重评分预览

| candidate_id | phase2_combined_rank_score | phase2_pair_binding_probability | phase2_pvrig_target_epitope_mass | phase2_cdr3_hotspot_contact_mean | phase1_mvp_rank_score |
| --- | --- | --- | --- | --- | --- |
| zym_test_381993 | 0.569890847586414 | 0.48108941316604614 | 13.493433952331543 | 0.3671296536922455 | 0.7921436200504218 |
| zym_test_665332 | 0.5582813707603731 | 0.4797126352787018 | 13.493433952331543 | 0.41019555926322937 | 0.7676947970138357 |
| zym_test_7635 | 0.5148817609564316 | 0.4763444662094116 | 13.493433952331543 | 0.40173783898353577 | 0.7764816471578397 |
| zym_test_3394 | 0.48942419674753224 | 0.4766176640987396 | 13.493433952331543 | 0.4276491701602936 | 0.7510368956630187 |
| zym_test_1937 | 0.4822197774706552 | 0.47518134117126465 | 13.493433952331543 | 0.3532644212245941 | 0.8035287308549333 |
| zym_test_17428 | 0.4554033612421274 | 0.47603756189346313 | 13.493433952331543 | 0.32914671301841736 | 0.8069838284535936 |
| zym_test_7332 | 0.4534158615091779 | 0.4755311906337738 | 13.493433952331543 | 0.398261696100235 | 0.7644836715930876 |
| zym_test_3633872 | 0.45312892788612574 | 0.4813367426395416 | 13.493433952331543 | 0.35971251130104065 | 0.7612740693297597 |
| zym_test_2596311 | 0.45177134096217136 | 0.475240558385849 | 13.493433952331543 | 0.3904959261417389 | 0.7703756452461398 |
| zym_test_8787 | 0.4477431062487234 | 0.4757140874862671 | 13.493433952331543 | 0.3830524981021881 | 0.7716908584101728 |
| zym_test_6516 | 0.4455970431308408 | 0.4759725034236908 | 13.493433952331543 | 0.39278021454811096 | 0.7635765852242107 |
| zym_test_6847 | 0.44025756396388327 | 0.47574639320373535 | 13.493433952331543 | 0.3543625771999359 | 0.7877350754174937 |
| zym_test_21966 | 0.4397558973227699 | 0.46991705894470215 | 13.493433952331543 | 0.44794222712516785 | 0.755518999283512 |
| zym_test_359954 | 0.4370279992926941 | 0.4804125130176544 | 13.493433952331543 | 0.3603246212005615 | 0.7605669195416402 |
| zym_test_13839 | 0.427132989995375 | 0.47789105772972107 | 13.493433952331543 | 0.37957024574279785 | 0.7573994712624521 |
| zym_test_6720 | 0.41770299032769553 | 0.4701361358165741 | 13.493433952331543 | 0.3972001075744629 | 0.7805185727479244 |
| zym_test_3809 | 0.4156871369325025 | 0.47236716747283936 | 13.493433952331543 | 0.3616270124912262 | 0.7920418374017449 |
| zym_test_2065 | 0.3860500329263916 | 0.47571510076522827 | 13.493433952331543 | 0.34357723593711853 | 0.7788153148021894 |
| zym_test_9290 | 0.3813496093073123 | 0.47622260451316833 | 13.493433952331543 | 0.3531540334224701 | 0.768849159962709 |
| zym_test_1078 | 0.37730415515047167 | 0.4782210886478424 | 13.493433952331543 | 0.31825166940689087 | 0.7804592882706202 |

## 不能过度解释

- 这些指标是计算训练/验证指标，不是实验 Kd/IC50。
- PVRIG 候选的 Phase2 分数是进入结构预测/docking 的优先级，不是最终 blocker 证明。
- hard negative 是构造负样本，不是全部实验 confirmed non-binder。

## 与 Phase 1 baseline 对比

```json
{
  "phase1_paratope_test_auprc": 0.41744344000115485,
  "phase2_paratope_test_auprc": 0.6244340297865512,
  "phase1_epitope_test_auprc": 0.13251513532736475,
  "phase2_epitope_test_auprc": 0.15410052732313168,
  "phase2_pair_test_auprc": 0.26837667444110264,
  "phase2_pair_test_auroc": 0.5152952847805788,
  "phase2_weak_contact_test_auprc": 0.6862518966648451,
  "paratope_auprc_delta": 0.2069905897853963,
  "epitope_auprc_delta": 0.021585391995766923
}```

解读：Phase 2 V1 的 residue-level paratope 和 epitope 指标已经超过 Phase 1 NumPy baseline；其中 paratope AUPRC 提升明显。pair binding 头目前仍弱，test AUROC 约 0.515，说明当前构造负样本和 pair pooling 还不足以支持“强 pair-level binder 判别”。因此 V1 可以作为 site/contact-prior 训练版本，但不能单独作为最终 PVRIG binder 判定模型。

## V1 已知问题和 V1.1 修改方向

1. 当前 antigen epitope head 主要由 antigen encoder 决定，对 VHH 条件化不足；V1.1 应加入 cross-attention 或以 contact matrix pooling 反哺 epitope head。
2. Pair binding head 使用 mean pooling，表达力不足；V1.1 应加入 top-k contact pooling、CDR3 pooling 和 hard-negative focal loss。
3. 当前 contact head 是 weak-contact proxy，不是真实 heavy-atom contact-map；V2 应接入 `prepared/structure_contact_pairs_mvp_v1.csv` 并补全 chain sequence mapping。
4. Pair 负样本是 constructed negatives，不是 confirmed non-binders；所有 easy/hard negative 指标必须分开报告。
