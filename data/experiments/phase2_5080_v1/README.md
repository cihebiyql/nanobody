# Phase 2 RTX 5080 Training Workspace

This folder is reserved for the upgraded structure+sequence VHH-antigen model.

See documentation in:

```text
docs/phase2_5080_training/
```

## Subdirectories

| Directory | Purpose |
| --- | --- |
| `configs/` | Training configs |
| `data_splits/` | Split manifests |
| `prepared/` | Preprocessed training caches |
| `negative_sets/` | Negative sample sets and audits |
| `checkpoints/` | Model weights |
| `runs/` | Run-specific logs and checkpoints |
| `reports/` | Evaluation reports |
| `logs/` | Generic logs |
| `predictions/` | Model predictions |
| `audits/` | Validation/audit reports |
| `src/` | Phase 2 training code |

Do not overwrite MVP outputs under `model_data/`, `models/phase1_sequence_baseline/`, or `reports/`.

## Current Completed Runs

| Run | Status | Key output |
| --- | --- | --- |
| V1 | Completed | `reports/phase2_v1_eval.md` |
| V2 | Completed | `reports/phase2_v2_eval.md` |
| V2.1 Expanded800 | Completed / PASS | `audits/PHASE2_V2_1_FINAL_VALIDATION.md` |
| V2.2 Full2277 | Completed / PASS | `audits/PHASE2_V2_2_FULL2277_FINAL_VALIDATION.md` |

V2.2 is the current completed deliverable for full real-contact training:

- Contact dataset: `prepared/structure_contact_maps_v2_full2277.jsonl`
- Checkpoint: `checkpoints/phase2_v2_2_full2277_best_checkpoint.pt`
- Metrics: `runs/phase2_v2_2_full2277_20260709_seed41/test_metrics.json`
- PVRIG re-score: `predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv`
- Re-runnable validation: `src/validate_phase2_v2_2_training.py`

V2.2 remains computational evidence only; it does not prove experimental binding or blocking.
