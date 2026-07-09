# PVRIG VHH Pose Scoring

`score_pvrig_vhh_pose.py` is a standalone, standard-library Python scorer for local PVRIG VHH docking poses.
It parses PDB `ATOM`/`HETATM` records and reports:

- PVRIG-VHH heavy-atom residue contacts within 4.5 A by default.
- PVRIG hotspot overlap using residue numbers from hotspot CSV `pdb_*_ref` columns such as `B:33S` or `A:31S`.
- Optional VHH CDR contact support when `--cdr-ranges` is supplied.
- VHH occlusion/clash against the reference PVRL2 chain, assuming the pose has already been aligned to the reference PVRIG coordinates.

## Example

```bash
python /mnt/d/work/抗体/docking/scripts/score_pvrig_vhh_pose.py \
  --pose-pdb pose_aligned_to_8X6B.pdb \
  --reference-pdb /mnt/d/work/抗体/data/structures/8X6B.pdb \
  --pvrig-chain B \
  --vhh-chain H \
  --ref-pvrig-chain B \
  --ref-pvrl2-chain A \
  --hotspots-csv /mnt/d/work/抗体/data/structures/PVRIG_hotspot_set_v1.csv \
  --assume-aligned \
  --cdr-ranges 'CDR1:26-35,CDR2:50-65,CDR3:95-102' \
  --out-json pose_score.json
```

Use `--out-csv pose_score.csv` instead of `--out-json` for a one-row tabular summary.

## Reference-baseline alignment

`align_pdb_by_chain.py` supports two alignment modes:

- default chain mode: pairs the first `N` CA atoms from both chains;
- mapped residue mode: uses a CSV map such as `PVRIG_hotspot_set_v1.csv` to pair
  residues across references.

Use mapped residue mode when moving 8X6B-aligned poses onto 9E6Y:

```bash
python /mnt/d/work/抗体/docking/scripts/align_pdb_by_chain.py \
  --mobile-pdb pose_aligned_to_8x6b.pdb \
  --reference-pdb /mnt/d/work/抗体/data/structures/9E6Y.pdb \
  --mobile-chain B \
  --reference-chain A \
  --pair-map-csv /mnt/d/work/抗体/data/structures/PVRIG_hotspot_set_v1.csv \
  --mobile-ref-column pdb_8x6b_ref \
  --reference-ref-column pdb_9e6y_ref \
  --out-pdb pose_aligned_to_9e6y.pdb
```

Check the alignment math with:

```bash
python /mnt/d/work/抗体/docking/scripts/test_align_pdb_by_chain.py
```

## Post-scoring blocker judgment

After scoring PVRL2 occlusion and hotspot overlap, apply the success-case
classifier:

```bash
python /mnt/d/work/抗体/docking/success_case_validation/apply_blocker_judgment.py \
  --occlusion-csv candidate_cdr_region_occlusion_summary.csv \
  --mechanism-csv candidate_pose_score.csv \
  --candidate-name candidate_name \
  --format-context naked_vhh \
  --out-csv candidate_blocker_classification.csv \
  --out-md candidate_blocker_classification.md
```

Run the regression test before changing thresholds or output columns:

```bash
python /mnt/d/work/抗体/docking/success_case_validation/test_success_case_workflow.py
```

When both 8X6B and 9E6Y classification CSVs are available, combine them with:

```bash
python /mnt/d/work/抗体/docking/success_case_validation/summarize_multibaseline_judgment.py \
  --classification 8x6b=8x6b_blocker_classification.csv \
  --classification 9e6y=9e6y_blocker_classification.csv \
  --out-csv candidate_multibaseline_consensus.csv
```

## Limits

- Kabsch/superposition is not implemented yet. The script intentionally fails unless `--assume-aligned` is present.
- Hotspot overlap assumes pose PVRIG residue numbering matches the selected reference hotspot column. Use `--hotspot-ref-column pdb_8x6b_ref` or `pdb_9e6y_ref` to force a mapping column.
- CDR ranges are optional and numbering-scheme dependent; the script does not infer IMGT/Kabat/Chothia boundaries.
- PVRL2 occlusion is a geometric proxy, not a binding-energy estimate.
- Multi-model PDB files are read as one atom set; split models before scoring if needed.
