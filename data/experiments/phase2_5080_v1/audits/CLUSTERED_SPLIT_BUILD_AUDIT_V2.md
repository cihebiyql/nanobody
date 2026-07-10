# Clustered Split Build Audit V2

Verdict: PASS

## Thresholds

- VHH ungapped identity: 0.8
- Antigen ungapped identity: 0.7
- CDR3 proxy-window identity: 0.9

## Site / Pair

- Site split counts: {'train': 861, 'val': 185, 'test': 184}
- Connected components: 348
- Pair rows: 4833
- Ranking triplets: 3603
- Pair label states: {'observed_positive': 1230, 'unlabeled_contrastive': 3603}
- Cross-split overlap: `{"vhh_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "vhh_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "cdr3_proxy_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}}`

## Contact

- Contact split counts: {'train': 5890, 'test': 1262, 'val': 1262}
- Connected components: 508
- Positive pairs: 855922
- Negative pairs: 3423688
- Cross-split overlap: `{"vhh_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "vhh_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "cdr3_proxy_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}}`

## PVRIG Calibration Boundary

- Exact control overlap: `{"site_exact_control_overlap": 0, "contact_exact_control_overlap": 0}`

## Limitations

- cdr3_proxy_cluster_id uses a C-terminal proxy window and is not an ANARCI/IMGT CDR3 assignment
- sequence clustering uses deterministic ungapped positional identity and can miss indel-shifted homologs
- constructed pairs are contrastive candidates, not experimentally verified non-binders
