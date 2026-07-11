# Large-scale PVRIG VHH cascade run

Input: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450/panel_blinded.fasta`
Output: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450/cascade`

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
      "updated_epoch": 1783755610.3400807
    },
    "finalize": {
      "docking_imported": 1,
      "final_positive_high": 1,
      "geometry_candidates": 4,
      "status": "complete",
      "updated_epoch": 1783760844.7290044
    },
    "full": {
      "chunks": 1,
      "status": "complete",
      "updated_epoch": 1783755729.9908316
    },
    "merge_fast": {
      "excluded_due_cap": 0,
      "full_shortlist": 4,
      "hard_pass": 4,
      "merged": 24,
      "status": "complete",
      "updated_epoch": 1783755610.3566573
    },
    "merge_full": {
      "geometry_diversity_excluded": 0,
      "geometry_pool": 4,
      "geometry_shortlist": 4,
      "hard_pass": 4,
      "merged": 4,
      "status": "complete",
      "updated_epoch": 1783755731.0085275
    },
    "prepare": {
      "config": {
        "fast_chunk_size": 24,
        "full_chunk_size": 24,
        "full_qc_limit": 0,
        "full_run_tnp": false,
        "geometry_cluster_limit": 3,
        "geometry_limit": 24,
        "geometry_pool_size": 24,
        "length_max": 160,
        "length_min": 95,
        "skip_final_diversity": false
      },
      "duplicates": 0,
      "fast_chunks": 1,
      "input_digest": "2bd593e74a1e8dd97d2d9604d159a46877c69f7a12b32991eb34006f7988a1c7",
      "input_fasta": "/data/qlyu/software/vhh_eval_tools/runs/pvrig_v25_panel_cascade_20260711_1450/panel_blinded.fasta",
      "input_records": 24,
      "quick_rejects": 0,
      "schema_version": 1,
      "status": "complete",
      "unique_ready": 24,
      "updated_epoch": 1783755599.614532
    }
  }
}
```
