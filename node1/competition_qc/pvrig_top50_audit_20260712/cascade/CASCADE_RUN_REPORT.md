# Large-scale PVRIG VHH cascade run

Input: `/data/qlyu/projects/pvrig_competition_audit_20260712/top50_model_ranked_public_sequences.fasta`
Output: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v24_top50_audit_20260712`

## Safety boundary

- Fast/full sequence scores prioritize candidates but do not prove PVRIG-PVRL2 blocking.
- Only `FINAL_POSITIVE_HIGH` has imported `CONSENSUS_BLOCKER_LIKE_A` geometry.
- `FINAL_RECHECK_SINGLE_BASELINE` must be redocked or manually reviewed.
- Exact duplicates are computed once and remain traceable in `input_map.tsv`.
- Any `full_qc_excluded_due_cap.tsv` rows are capacity-deferred, not biological negatives.
- O(N^2) team diversity is deferred from the full library and recomputed globally on the bounded geometry pool.
- TNP is deferred by default because it is a developability annotation, not a blocker-biology hard gate.

## Stage state

```json
{
  "stages": {
    "fast": {
      "chunks": 1,
      "status": "complete",
      "updated_epoch": 1783835639.0982845
    },
    "finalize": {
      "docking_imported": 0,
      "final_positive_high": 0,
      "geometry_candidates": 29,
      "status": "complete",
      "updated_epoch": 1783835911.5154176
    },
    "full": {
      "chunks": 1,
      "status": "complete",
      "updated_epoch": 1783835856.517461
    },
    "merge_fast": {
      "excluded_due_cap": 0,
      "full_shortlist": 29,
      "hard_pass": 29,
      "merged": 50,
      "status": "complete",
      "updated_epoch": 1783835639.1213043
    },
    "merge_full": {
      "geometry_diversity_excluded": 0,
      "geometry_pool": 29,
      "geometry_shortlist": 29,
      "hard_pass": 29,
      "merged": 29,
      "status": "complete",
      "updated_epoch": 1783835911.5000753
    },
    "prepare": {
      "config": {
        "fast_chunk_size": 50,
        "full_chunk_size": 50,
        "full_qc_limit": 0,
        "full_run_tnp": false,
        "geometry_cluster_limit": 3,
        "geometry_limit": 50,
        "geometry_pool_size": 50,
        "length_max": 160,
        "length_min": 95,
        "skip_final_diversity": false
      },
      "duplicates": 0,
      "fast_chunks": 1,
      "input_digest": "afcd260f8aa4feb55e3d9346b6a431413419c67a35d541363b54a2d996f92877",
      "input_fasta": "/data/qlyu/projects/pvrig_competition_audit_20260712/top50_model_ranked_public_sequences.fasta",
      "input_records": 50,
      "quick_rejects": 0,
      "schema_version": 1,
      "status": "complete",
      "unique_ready": 50,
      "updated_epoch": 1783835601.9435003
    }
  }
}
```
