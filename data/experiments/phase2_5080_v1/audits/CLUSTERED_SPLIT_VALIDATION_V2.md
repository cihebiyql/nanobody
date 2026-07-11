# Clustered Split V2 Validation

Verdict: PASS

## Manifests

| Manifest | Rows | Split counts | Ratios |
| --- | ---: | --- | --- |
| site | 1230 | `{"test": 184, "train": 861, "val": 185}` | `{"test": 0.14959349593495935, "train": 0.7, "val": 0.15040650406504066}` |
| pair | 4844 | `{"test": 721, "train": 3389, "val": 734}` | `{"test": 0.14884393063583815, "train": 0.6996284062758051, "val": 0.15152766308835672}` |
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
| site_vhh_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| site_cdr3_proxy_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| site_antigen_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| site_split_group_id_complete | PASS | `missing_rows=[] count=0` |
| pair_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/pair_binding_split_v2_clustered.csv rows=4844` |
| pair_rows_nonempty | PASS | `rows=4844` |
| pair_split_values_valid | PASS | `missing=[] invalid=[]` |
| pair_split_nonempty | PASS | `{"test": 721, "train": 3389, "val": 734}` |
| pair_split_ratios_reasonable | PASS | `{"test": 0.14884393063583815, "train": 0.6996284062758051, "val": 0.15152766308835672}` |
| pair_vhh_sequences_present | PASS | `missing_rows=[]` |
| pair_antigen_sequences_present | PASS | `missing_rows=[]` |
| pair_vhh_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| pair_cdr3_proxy_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| pair_antigen_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| pair_split_group_id_complete | PASS | `missing_rows=[] count=0` |
| contact_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl rows=8414` |
| contact_rows_nonempty | PASS | `rows=8414` |
| contact_split_values_valid | PASS | `missing=[] invalid=[]` |
| contact_split_nonempty | PASS | `{"test": 1262, "train": 5890, "val": 1262}` |
| contact_split_ratios_reasonable | PASS | `{"test": 0.14998811504635132, "train": 0.7000237699072973, "val": 0.14998811504635132}` |
| contact_vhh_sequences_present | PASS | `missing_rows=[]` |
| contact_antigen_sequences_present | PASS | `missing_rows=[]` |
| contact_vhh_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| contact_cdr3_proxy_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| contact_antigen_cluster_id_complete | PASS | `missing_rows=[] count=0` |
| contact_split_group_id_complete | PASS | `missing_rows=[] count=0` |
| site_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_vhh_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_cdr3_proxy_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_antigen_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_split_group_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| site_pdb_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_vhh_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_cdr3_proxy_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_antigen_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_split_group_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_pdb_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_vhh_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_cdr3_proxy_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_antigen_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_split_group_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| contact_pdb_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_exact_vhh_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_exact_antigen_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_vhh_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_cdr3_proxy_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_antigen_cluster_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_split_group_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| combined_pdb_id_overlap_zero | PASS | `all pairwise overlaps=0` |
| pair_labels_are_tristate_domain | PASS | `{"positive": 1230, "unlabeled": 3614}` |
| pair_has_positive_and_nonpositive_supervision_state | PASS | `{"positive": 1230, "unlabeled": 3614}` |
| pair_label_source_complete | PASS | `missing_label_source_rows=0` |
| pair_source_detail_complete | PASS | `missing_source_detail_rows=0` |
| pvrig_controls_manifest_present | PASS | `path=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/data_splits/pvrig_external_calibration_manifest_v1.csv rows=97` |
| pvrig_controls_not_marked_as_ordinary_split | PASS | `ordinary_split_rows=[]` |
| pvrig_controls_have_exclusion_or_calibration_policy | PASS | `bad_policy_rows=[]` |
| site_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| pair_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| contact_pvrig_controls_absent_from_train_vhh | PASS | `train_control_hits=0` |
| combined_pvrig_controls_absent_from_ordinary_training | PASS | `train_control_hits=0` |
