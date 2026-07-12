# Large-scale PVRIG VHH cascade run

Input: `/data/qlyu/projects/pvrig_rfantibody_validation_20260712/inputs/pvrig_rfantibody_1000.canonical.fasta`
Output: `/data/qlyu/projects/pvrig_rfantibody_validation_20260712/qc/cascade`

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
      "chunks": 4,
      "status": "complete",
      "updated_epoch": 1783855231.1568048
    },
    "full": {
      "chunks": 0,
      "reason": "no survivors",
      "status": "complete",
      "updated_epoch": 1783855231.2343729
    },
    "merge_fast": {
      "excluded_due_cap": 0,
      "full_shortlist": 0,
      "hard_pass": 0,
      "merged": 1000,
      "status": "complete",
      "updated_epoch": 1783855231.231331
    },
    "prepare": {
      "config": {
        "fast_chunk_size": 250,
        "full_chunk_size": 100,
        "full_qc_limit": 300,
        "full_run_tnp": false,
        "geometry_cluster_limit": 3,
        "geometry_limit": 50,
        "geometry_pool_size": 150,
        "length_max": 160,
        "length_min": 95,
        "skip_final_diversity": false
      },
      "duplicates": 0,
      "fast_chunks": 4,
      "input_digest": "b28d70cedced92f0e55d2d490f6962a6d702e382dc7786a0dbf90c56fbc70ada",
      "input_fasta": "/data/qlyu/projects/pvrig_rfantibody_validation_20260712/inputs/pvrig_rfantibody_1000.canonical.fasta",
      "input_records": 1000,
      "quick_rejects": 0,
      "schema_version": 1,
      "status": "complete",
      "unique_ready": 1000,
      "updated_epoch": 1783855069.3836746
    }
  }
}
```
