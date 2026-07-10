# Clustered Split V2 Validation

Verdict: FAIL

## Manifests

| Manifest | Rows | Split counts | Ratios |
| --- | ---: | --- | --- |
| site | 1230 | `{"test": 184, "train": 861, "val": 185}` | `{"test": 0.14959349593495935, "train": 0.7, "val": 0.15040650406504066}` |
| pair | 4833 | `{"test": 728, "train": 3380, "val": 725}` | `{"test": 0.15063107800537967, "train": 0.6993585764535485, "val": 0.1500103455410718}` |
| contact | 8414 | `{"test": 1262, "train": 5890, "val": 1262}` | `{"test": 0.14998811504635132, "train": 0.7000237699072973, "val": 0.14998811504635132}` |

## Checks

| Check | Status | Evidence |
| --- | --- | --- |
| site_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2_clustered.csv rows=1230` |
| site_rows_nonempty | PASS | `rows=1230` |
| site_split_values_valid | PASS | `missing=[] invalid=[]` |
| site_split_nonempty | PASS | `{"test": 184, "train": 861, "val": 185}` |
| site_split_ratios_reasonable | PASS | `{"test": 0.14959349593495935, "train": 0.7, "val": 0.15040650406504066}` |
| site_vhh_sequences_present | PASS | `missing_rows=[]` |
| site_antigen_sequences_present | PASS | `missing_rows=[]` |
| pair_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/pair_binding_split_v2_clustered.csv rows=4833` |
| pair_rows_nonempty | PASS | `rows=4833` |
| pair_split_values_valid | PASS | `missing=[] invalid=[]` |
| pair_split_nonempty | PASS | `{"test": 728, "train": 3380, "val": 725}` |
| pair_split_ratios_reasonable | PASS | `{"test": 0.15063107800537967, "train": 0.6993585764535485, "val": 0.1500103455410718}` |
| pair_vhh_sequences_present | PASS | `missing_rows=[]` |
| pair_antigen_sequences_present | PASS | `missing_rows=[]` |
| contact_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl rows=8414` |
| contact_rows_nonempty | PASS | `rows=8414` |
| contact_split_values_valid | PASS | `missing=[] invalid=[]` |
| contact_split_nonempty | PASS | `{"test": 1262, "train": 5890, "val": 1262}` |
| contact_split_ratios_reasonable | PASS | `{"test": 0.14998811504635132, "train": 0.7000237699072973, "val": 0.14998811504635132}` |
| contact_vhh_sequences_present | PASS | `missing_rows=[]` |
| contact_antigen_sequences_present | PASS | `missing_rows=[]` |
| site_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_exact_vhh_overlap_zero | FAIL | `{"train_vs_test": 157, "train_vs_val": 161, "val_vs_test": 87}` |
| combined_exact_antigen_overlap_zero | FAIL | `{"train_vs_test": 157, "train_vs_val": 160, "val_vs_test": 91}` |
| pair_labels_are_tristate_domain | PASS | `{"positive": 1230, "unlabeled": 3603}` |
| pair_has_positive_and_nonpositive_supervision_state | PASS | `{"positive": 1230, "unlabeled": 3603}` |
| pair_label_source_complete | PASS | `missing_label_source_rows=0` |
| pair_source_detail_complete | PASS | `missing_source_detail_rows=0` |
| pvrig_controls_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/pvrig_external_calibration_manifest_v1.csv rows=97` |
| pvrig_controls_not_marked_as_ordinary_split | PASS | `ordinary_split_rows=[]` |
| pvrig_controls_have_exclusion_or_calibration_policy | PASS | `bad_policy_rows=[]` |
| site_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| pair_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| contact_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| combined_pvrig_controls_absent_from_ordinary_training | PASS | `train_control_hits=0` |

## Failed Checks

- combined_exact_vhh_overlap_zero
- combined_exact_antigen_overlap_zero
