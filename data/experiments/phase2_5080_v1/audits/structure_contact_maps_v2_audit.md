# Structure Contact Maps V2 Audit

Updated: 2026-07-09

## Summary

```json
{
  "input_structures_sampled": 160,
  "negative_min_distance_angstrom": 8.0,
  "negative_pairs": 131228,
  "output_jsonl": "/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared/structure_contact_maps_v2.jsonl",
  "output_summary_csv": "/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared/structure_contact_maps_v2_summary.csv",
  "positive_cutoff_angstrom": 4.5,
  "positive_pairs": 32807,
  "records": 371,
  "seed": 17,
  "split_counts": {
    "test": 32,
    "train": 290,
    "val": 49
  }
}
```

## Boundary

Positive labels are true same-complex residue pairs with heavy-atom distance <= 4.5 A. Negative labels are sampled same-complex residue pairs with min heavy-atom distance >= 8.0 A. Residue indices are 0-based reconstructed sequence indices per chain from mmCIF atom_site records.
