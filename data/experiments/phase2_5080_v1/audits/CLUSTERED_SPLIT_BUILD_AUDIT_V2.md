# Clustered Split Build Audit V2

Verdict: PASS

## Thresholds

- VHH ungapped identity: 0.8
- Antigen ungapped identity: 0.7
- CDR3 proxy-window identity: 0.9

## Global Assignment

- Global manifest: `/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/phase2_global_split_manifest_v2_clustered.csv`
- Connected components: 513
- Largest connected component: 5116
- Combined split counts: {'train': 6751, 'val': 1447, 'test': 1446}
- Task-balanced split counts: {'site': {'train': 861, 'val': 185, 'test': 184}, 'contact': {'train': 5890, 'val': 1262, 'test': 1262}}
- Cross-task overlap: `{"vhh_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "vhh_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "cdr3_proxy_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}}`

## Site / Pair

- Site split counts: {'train': 861, 'val': 185, 'test': 184}
- Pair rows: 4844
- Ranking triplets: 3614
- Pair label states: {'observed_positive': 1230, 'unlabeled_contrastive': 3614}
- Cross-split overlap: `{"vhh_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "vhh_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "cdr3_proxy_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}}`

## Contact

- Contact split counts: {'train': 5890, 'val': 1262, 'test': 1262}
- Positive pairs: 855922
- Negative pairs: 3423688
- Cross-split overlap: `{"vhh_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_seq": {"train_val": 0, "train_test": 0, "val_test": 0}, "vhh_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "cdr3_proxy_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}, "antigen_cluster_id": {"train_val": 0, "train_test": 0, "val_test": 0}}`

## PVRIG Calibration Boundary

- Exact control overlap: `{"site_exact_control_overlap": 0, "contact_exact_control_overlap": 0}`

## Limitations

- cdr3_proxy_cluster_id uses a C-terminal proxy window and is not an ANARCI/IMGT CDR3 assignment
- sequence clustering uses deterministic ungapped positional identity and can miss indel-shifted homologs
- constructed pairs are contrastive candidates, not experimentally verified non-binders
