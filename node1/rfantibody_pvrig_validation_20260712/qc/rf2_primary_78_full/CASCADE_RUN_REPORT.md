# Large-scale PVRIG VHH cascade run

Input: `/data/qlyu/projects/pvrig_rfantibody_validation_20260712/inputs/rf2_primary_78.fr4_restored.fasta`
Output: `/data/qlyu/projects/pvrig_rfantibody_validation_20260712/qc/rf2_primary_78_full`

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
      "updated_epoch": 1783857462.9211178
    },
    "finalize": {
      "docking_imported": 0,
      "final_positive_high": 0,
      "geometry_candidates": 4,
      "status": "complete",
      "updated_epoch": 1783857926.065072
    },
    "full": {
      "chunks": 1,
      "status": "complete",
      "updated_epoch": 1783857743.0689383
    },
    "merge_fast": {
      "excluded_due_cap": 0,
      "full_shortlist": 78,
      "hard_pass": 78,
      "merged": 78,
      "status": "complete",
      "updated_epoch": 1783857462.9396179
    },
    "merge_full": {
      "geometry_diversity_excluded": 74,
      "geometry_pool": 78,
      "geometry_shortlist": 4,
      "hard_pass": 78,
      "merged": 78,
      "status": "complete",
      "updated_epoch": 1783857926.0617383
    },
    "prepare": {
      "config": {
        "fast_chunk_size": 78,
        "full_chunk_size": 78,
        "full_qc_limit": 0,
        "full_run_tnp": false,
        "geometry_cluster_limit": 2,
        "geometry_limit": 50,
        "geometry_pool_size": 78,
        "length_max": 160,
        "length_min": 95,
        "skip_final_diversity": false
      },
      "duplicates": 0,
      "fast_chunks": 1,
      "input_digest": "dd332d22b3628be833858f5da851fa6e6aeaf290b606d91aecc15472bb8e292f",
      "input_fasta": "/data/qlyu/projects/pvrig_rfantibody_validation_20260712/inputs/rf2_primary_78.fr4_restored.fasta",
      "input_records": 78,
      "quick_rejects": 0,
      "schema_version": 1,
      "status": "complete",
      "unique_ready": 78,
      "updated_epoch": 1783857441.931913
    }
  }
}
```
