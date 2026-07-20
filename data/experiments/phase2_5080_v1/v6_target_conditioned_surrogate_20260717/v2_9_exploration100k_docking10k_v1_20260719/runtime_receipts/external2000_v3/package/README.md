# PVRIG external 2000-sequence Docking bundle v3

V3 preserves the exact V2 sequence set, monomer structures, job IDs, job hashes, receptor pair and seed. It only closes runtime dependencies and adds a shard-appropriate aggregator.

## Scope

- 2,000 unique VHH sequences.
- 4,000 jobs: 8X6B + 9E6Y, seed 917.
- No calibration controls and no technical multiseed repeats in this external shard.
- This shard is computational Docking geometry evidence only; it is not an affinity, Kd, IC50, expression, purity or experimental-blocking result.

## V3 fixes

- Adds `reports/reference_normalization_summary.json`, required by `score_pose.py`.
- Adds `scripts/validate_protocol.py`, required for importing legacy `aggregate_results.py`.
- Adds `scripts/analyze_p2_p3_p4_enrichment.py`, the legacy aggregator's downstream helper.
- Adds `scripts/aggregate_external2000_results.py`, specifically for 2,000 candidates, dual receptor, one seed, no controls.

## Launch

```bash
cd /data/qlyu/projects/pvrig_v29_external2000_sequences_v3_20260720
HADDOCK3=/path/to/haddock3 PVRIG_PYTHON=/path/to/python \
  nohup scripts/launch_external2000.sh 4 /local/ssd/pvrig_external2000 \
  > logs/external2000.log 2>&1 < /dev/null &
```

The first argument is concurrent jobs. Each frozen job uses `ncores=4`. Required HADDOCK3 version: 2025.11.0.

## Standalone progress/final aggregation

```bash
PVRIG_PYTHON=/path/to/python \
  /path/to/python scripts/aggregate_external2000_results.py --root "$PWD"
```

Outputs:

- `reports/external_job_results.tsv`
- `reports/external_pose_scores.tsv`
- `reports/external_candidate_dual.tsv`
- `reports/EXTERNAL2000_AGGREGATION.json`

The external aggregator uses exact worst-of-two categorical support across 8X6B/9E6Y. The ordinal mapping is `OTHER=0`, `SUPPORTED_AB=1`, `STRICT_A=2`; it is not a Kd or affinity score. Technical failures remain `NA`, not negatives.

## Return to the complete project

After the external shard finishes, return these trees:

```text
status/jobs/
results/
runs/
```

Merge only by matching `job_id`, `job_hash`, and `protocol_core_sha256`. Then run the canonical `scripts/aggregate_results.py` in the complete V29 project. Do not apply the complete project's 47-control or multiseed gates to this isolated shard.

## Upgrade from a running V2 directory

Pause the V2 launcher, extract V3, then copy the existing mutable runtime outputs into the V3 root:

```bash
rsync -a V2_ROOT/status/jobs/ V3_ROOT/status/jobs/
rsync -a V2_ROOT/results/ V3_ROOT/results/
rsync -a V2_ROOT/runs/ V3_ROOT/runs/
rsync -a V2_ROOT/failed_attempts/ V3_ROOT/failed_attempts/
```

Do not overwrite V3 `scripts/`, `reports/reference_normalization_summary.json`, `status/READY.json`, or `SHA256SUMS` with V2 files.
