# Phase 2 phase2_v2_1_expanded800 真实结构 Contact-map 训练评估报告

Updated: 2026-07-09

## 结论

V2 已接入真实 SAbDab2 heavy-atom contact-map 监督；contact labels 来自同一复合物 residue pair 距离 <=4.5 A，负样本来自 >=8.0 A。pair head 使用 top-k contact pooling。

## 环境

```json
{
  "device": "cuda",
  "torch": "2.13.0+cu130",
  "cuda_available": true,
  "cuda_version": "13.0",
  "gpu_name": "NVIDIA GeForce RTX 5080",
  "best_epoch": 8,
  "run_id": "phase2_v2_1_expanded800_20260709_seed31"
}
```

## 配置

```json
{
  "root": "/mnt/d/work/抗体/data",
  "out_root": "experiments/phase2_5080_v1",
  "seed": 17,
  "d_model": 160,
  "contact_dim": 96,
  "layers": 2,
  "cross_layers": 1,
  "heads": 4,
  "dropout": 0.1,
  "max_vhh_len": 180,
  "max_antigen_len": 512,
  "batch_site": 24,
  "batch_contact": 12,
  "batch_pair": 24,
  "epochs": 8,
  "lr": 0.0002,
  "weight_decay": 0.01,
  "contact_pos_sample": 64,
  "contact_neg_sample": 256,
  "site_weight": 0.8,
  "contact_weight": 1.5,
  "pair_weight": 1.2,
  "use_amp": true
}
```

## Test 指标

```json
{
  "checkpoint": "/mnt/d/work/抗体/data/experiments/phase2_5080_v1/runs/phase2_v2_1_expanded800_20260709_seed31/best_checkpoint.pt",
  "contact_test": {
    "contact_auprc": 0.6157458658402079,
    "contact_auroc": 0.8617162507810164,
    "contact_f1": 0.5909383171160358,
    "contact_fn": 3786.0,
    "contact_fp": 5757.0,
    "contact_n": 53387.0,
    "contact_positive_rate": 0.20002996984284563,
    "contact_precision": 0.544901185770751,
    "contact_precision_at_poscount_or_50": 0.076344941648774,
    "contact_recall": 0.6454724225114711,
    "contact_tn": 36951.0,
    "contact_tp": 6893.0
  },
  "dataset_sizes": {
    "contact_test": 318,
    "contact_train": 1932,
    "contact_val": 475,
    "pair_test": 954,
    "pair_train": 3345,
    "pair_val": 552,
    "site_test": 240,
    "site_train": 851,
    "site_val": 139
  },
  "pair_test": {
    "pair_auprc": 0.26859930619441885,
    "pair_auroc": 0.5160364145658264,
    "pair_f1": 0.3755186721991701,
    "pair_fn": 59.0,
    "pair_fp": 543.0,
    "pair_n": 954.0,
    "pair_positive_rate": 0.25157232704402516,
    "pair_precision": 0.25,
    "pair_recall": 0.7541666666666667,
    "pair_tn": 171.0,
    "pair_tp": 181.0
  },
  "pair_test_by_negative_type": {
    "N1_easy_cross_antigen": {
      "auprc": 0.5180160238633867,
      "auroc": 0.52328125,
      "f1": 0.601328903654485,
      "fn": 59.0,
      "fp": 181.0,
      "n": 480.0,
      "positive_rate": 0.5,
      "precision": 0.5,
      "recall": 0.7541666666666667,
      "tn": 59.0,
      "tp": 181.0
    },
    "N2_same_family_hard_antigen": {
      "auprc": 0.5007937148256416,
      "auroc": 0.48753561253561256,
      "f1": 0.6003316749585407,
      "fn": 59.0,
      "fp": 182.0,
      "n": 474.0,
      "positive_rate": 0.5063291139240507,
      "precision": 0.4986225895316804,
      "recall": 0.7541666666666667,
      "tn": 52.0,
      "tp": 181.0
    },
    "N3_framework_similar_hard_vhh": {
      "auprc": 0.5559594822800006,
      "auroc": 0.5365798611111111,
      "f1": 0.6023294509151413,
      "fn": 59.0,
      "fp": 180.0,
      "n": 480.0,
      "positive_rate": 0.5,
      "precision": 0.5013850415512465,
      "recall": 0.7541666666666667,
      "tn": 60.0,
      "tp": 181.0
    }
  },
  "pair_val_by_negative_type": {
    "N1_easy_cross_antigen": {
      "auprc": 0.5490446552883896,
      "auroc": 0.5438641892241602,
      "f1": 0.6481994459833795,
      "fn": 22.0,
      "fp": 105.0,
      "n": 278.0,
      "positive_rate": 0.5,
      "precision": 0.527027027027027,
      "recall": 0.841726618705036,
      "tn": 34.0,
      "tp": 117.0
    },
    "N2_same_family_hard_antigen": {
      "auprc": 0.5694091344083857,
      "auroc": 0.5515054622968292,
      "f1": 0.6610169491525425,
      "fn": 22.0,
      "fp": 98.0,
      "n": 274.0,
      "positive_rate": 0.5072992700729927,
      "precision": 0.5441860465116279,
      "recall": 0.841726618705036,
      "tn": 37.0,
      "tp": 117.0
    },
    "N3_framework_similar_hard_vhh": {
      "auprc": 0.5796093155446341,
      "auroc": 0.5841312561461622,
      "f1": 0.6554621848739497,
      "fn": 22.0,
      "fp": 101.0,
      "n": 278.0,
      "positive_rate": 0.5,
      "precision": 0.536697247706422,
      "recall": 0.841726618705036,
      "tn": 38.0,
      "tp": 117.0
    }
  },
  "pvrig_prediction_rows": 50,
  "site_test": {
    "epitope_auprc": 0.183870095040085,
    "epitope_auroc": 0.6854276289606139,
    "epitope_f1": 0.23392923496139714,
    "epitope_fn": 2500.0,
    "epitope_fp": 16055.0,
    "epitope_n": 67956.0,
    "epitope_positive_rate": 0.0784772499852846,
    "epitope_precision": 0.14998941126641255,
    "epitope_recall": 0.5312207012938308,
    "epitope_tn": 46568.0,
    "epitope_tp": 2833.0,
    "paratope_auprc": 0.6410665123085403,
    "paratope_auroc": 0.9096884327845213,
    "paratope_f1": 0.6215846994535519,
    "paratope_fn": 720.0,
    "paratope_fp": 4266.0,
    "paratope_n": 29287.0,
    "paratope_positive_rate": 0.16440741625977395,
    "paratope_precision": 0.4897739504843918,
    "paratope_recall": 0.8504672897196262,
    "paratope_tn": 20206.0,
    "paratope_tp": 4095.0
  }
}
```

## 与 V1 / Phase1 对照

```json
{
  "phase1_v1_reference": {
    "phase1_paratope_test_auprc": 0.41744344000115485,
    "phase2_paratope_test_auprc": 0.6244340297865512,
    "phase1_epitope_test_auprc": 0.13251513532736475,
    "phase2_epitope_test_auprc": 0.15410052732313168,
    "phase2_pair_test_auprc": 0.26837667444110264,
    "phase2_pair_test_auroc": 0.5152952847805788,
    "phase2_weak_contact_test_auprc": 0.6862518966648451,
    "paratope_auprc_delta": 0.2069905897853963,
    "epitope_auprc_delta": 0.021585391995766923
  },
  "v2_paratope_auprc": 0.6410665123085403,
  "v2_epitope_auprc": 0.183870095040085,
  "v2_real_contact_auprc": 0.6157458658402079,
  "v2_pair_auroc": 0.5160364145658264,
  "v2_pair_auprc": 0.26859930619441885
}
```

## 训练历史

| epoch | train_loss | val_contact_auprc | val_contact_auroc | val_pair_auprc | val_pair_auroc | val_paratope_auprc | val_epitope_auprc |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.1586 | 0.5240 | 0.8191 | 0.2688 | 0.5211 | 0.6236 | 0.1510 |
| 2 | 3.8032 | 0.5665 | 0.8376 | 0.2854 | 0.5285 | 0.6584 | 0.1620 |
| 3 | 3.6431 | 0.5934 | 0.8472 | 0.3020 | 0.5142 | 0.6714 | 0.1880 |
| 4 | 3.4706 | 0.6184 | 0.8591 | 0.3205 | 0.5580 | 0.6902 | 0.2194 |
| 5 | 3.3340 | 0.6372 | 0.8634 | 0.3147 | 0.5582 | 0.7106 | 0.2385 |
| 6 | 3.1821 | 0.6561 | 0.8702 | 0.3171 | 0.5592 | 0.7187 | 0.2583 |
| 7 | 3.0742 | 0.6647 | 0.8723 | 0.3288 | 0.5609 | 0.7296 | 0.2685 |
| 8 | 2.9585 | 0.6770 | 0.8790 | 0.3158 | 0.5599 | 0.7389 | 0.2702 |

## PVRIG V2 Top 预览

| candidate_id | phase2_v2_combined_rank_score | phase2_v2_pair_binding_probability | phase2_v2_pvrig_target_epitope_mass | phase2_v2_cdr3_hotspot_contact_mean | phase1_mvp_rank_score |
| --- | --- | --- | --- | --- | --- |
| zym_test_7635 | 0.7770865480206652 | 0.3513888418674469 | 11.941139221191406 | 0.5671400427818298 | 0.7764816471578397 |
| zym_test_6823 | 0.769896363602073 | 0.373219758272171 | 11.36522388458252 | 0.5033779144287109 | 0.8020455449193398 |
| zym_test_9743 | 0.7693393293331757 | 0.36527150869369507 | 12.214228630065918 | 0.5853169560432434 | 0.7574589084996735 |
| zym_test_1937 | 0.6903589042330517 | 0.31031620502471924 | 11.712576866149902 | 0.4899451434612274 | 0.8035287308549333 |
| zym_test_6847 | 0.647026796781047 | 0.3098328411579132 | 11.609811782836914 | 0.5000078082084656 | 0.7877350754174937 |
| zym_test_2065 | 0.6318907211790445 | 0.32672184705734253 | 11.526639938354492 | 0.49830809235572815 | 0.7788153148021894 |
| zym_test_665332 | 0.6087009766044059 | 0.3064606785774231 | 12.378133773803711 | 0.500545084476471 | 0.7676947970138357 |
| zym_test_9666 | 0.5938052110762034 | 0.34498167037963867 | 9.932283401489258 | 0.5019105076789856 | 0.7794198204552202 |
| zym_test_3361596 | 0.5740884520450295 | 0.3096808195114136 | 11.9126558303833 | 0.4210244119167328 | 0.7977167763717053 |
| zym_test_9290 | 0.5578499110803674 | 0.3400225043296814 | 11.248286247253418 | 0.4685790538787842 | 0.768849159962709 |
| zym_test_6720 | 0.5405993602159134 | 0.25932326912879944 | 10.579948425292969 | 0.517106831073761 | 0.7805185727479244 |
| zym_test_9297 | 0.5303924059607684 | 0.382802277803421 | 10.459405899047852 | 0.42302730679512024 | 0.7752253568549965 |
| zym_test_21705 | 0.5272491179560937 | 0.35364511609077454 | 9.567827224731445 | 0.5258533358573914 | 0.7504998681389008 |
| zym_test_21646 | 0.5271421775029238 | 0.2554031312465668 | 10.268333435058594 | 0.5032200217247009 | 0.7881607189944034 |
| zym_test_3809 | 0.5265129945549407 | 0.3248842656612396 | 10.214256286621094 | 0.43791231513023376 | 0.7920418374017449 |
| zym_test_7954 | 0.5114556650722163 | 0.3314380347728729 | 10.887723922729492 | 0.49756908416748047 | 0.749975066812989 |
| zym_test_11923 | 0.5077713946622291 | 0.33225640654563904 | 11.399652481079102 | 0.4687502384185791 | 0.754963549496142 |
| zym_test_5495 | 0.4889828819692214 | 0.36649349331855774 | 10.989052772521973 | 0.44864365458488464 | 0.7509027298842657 |
| zym_test_7332 | 0.48433281515720883 | 0.3151721954345703 | 10.672672271728516 | 0.4668039381504059 | 0.7644836715930876 |
| zym_test_6492 | 0.4721999184912606 | 0.28568822145462036 | 10.126522064208984 | 0.4173813760280609 | 0.8008552890597735 |

## 边界

- V2 已经是真实 heavy-atom contact-map 训练，但仍不是实验 Kd/IC50 或细胞阻断证明。
- Pair negatives 仍是 constructed negatives；hard-negative 分项必须单独看。
- PVRIG 分数是 docking 前优先级，不是最终 blocker 判定。
