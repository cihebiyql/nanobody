# PVRIG VHH screening runtime estimate

Updated: 2026-07-08

## Bottom line

- Sequence-only QC for 11 VHHs is about 3-4 minutes end-to-end on node1 with the current full settings.
- The slow sequence-QC item is TNP through `vhh-screen`; L1/basic checks are seconds, AbNatiV and Sapiens are tens of seconds per 11 sequences.
- Structure+docking dominates if blocker geometry is required: current single-candidate path is roughly 4-6 minutes per sequence, mostly HADDOCK3.
- For batch mode, structure prediction is kept sequential by the runner, while docking/postprocess can be parallelized with `--jobs`; wall time depends heavily on queue/GPU/CPU contention.

## Observed timing table

| Stage / metric | Basis | n | Total | Per sequence / distribution | Confidence | Notes |
| --- | --- | ---: | ---: | --- | --- | --- |
| parse/write input | stage_timings.tsv, 11 sequences | 11 | 0.0s | <0.01 | high | FASTA parsing and small file writes are negligible. |
| official ab-data-validator / positive CDR identity | stage_timings.tsv, 11 sequences | 11 | 22.8s | 2.1s | high | Includes official validator setup and 48 built-in positive references. |
| vhh-screen L1 + basic physicochemical/liability scan | skip-abnativ/skip-sapiens/skip-tnp benchmark, 11 sequences | 11 | 2.7s | 0.2s | high | Numbering, CDR extraction, length, pI/charge/GRAVY, simple liabilities. |
| AbNatiV VHH scoring incremental | abnativ_only - l1_basic benchmark | 11 | 32.6s | 3.0s | medium-high | Wrapper/model overhead included; 9/11 produced scores in this positive set. |
| Sapiens human-likeness incremental | sapiens_only - l1_basic benchmark | 11 | 21.3s | 1.9s | medium-high | Human-likeness and suggested mutation scoring. |
| TNP developability incremental through vhh-screen | tnp_only - l1_basic benchmark | 11 | 1.86min | 10.2s | medium-high | TNP wrapper/model overhead; direct standalone batch was faster in one observed run. |
| vhh-screen full | full benchmark, 11 sequences | 11 | 3.13min | 17.1s | high | Full run includes ~19.4s residual wrapper/interaction overhead in this split benchmark. |
| local positive CDR novelty | stage_timings.tsv, 11 sequences vs local positive CDRs | 11 | 24.5s | 2.2s | high | Local CDR novelty/leakage check. |
| team diversity clustering | stage_timings.tsv, 11 sequences | 11 | 1.9s | 0.2s | high | Pairwise team identity and cluster scoring. |
| portfolio merge/ranking/report writes | stage_timings.tsv, 11 sequences | 11 | 0.0s | <0.01 | high | Negligible for this batch size. |
| NanoBodyBuilder2 monomer structure prediction | mutant-panel sequential normalized-PDB mtime cadence, 34 usable deltas | 34 |  | median 24.0; mean 32.2; range 20.9-137.5 | medium | No unified timer in logs; cadence includes ssh/copy/normalization. Long pauses excluded. |
| HADDOCK3 docking | HADDOCK3 final log duration, mutant panel | 34 |  | median 159.5; mean 172.6; range 145.0-244.0 | high | Current cfg around 40 rigidbody jobs, 10 flexref/emref, 8 cores. |
| 8X6B + 9E6Y scoring/classification/postprocess | timed rerun on /tmp copy for one completed workdir | 1 | 20.5s | 20.5s | medium | Local CPU postprocess of 10 models; varies with number of top models. |

## Practical estimates

- Fast prefilter without TNP/structure: about 1 minute for 11 sequences, dominated by official validator and local novelty checks.
- Full sequence QC with AbNatiV + Sapiens + TNP: about 3.1 minutes for 11 sequences in the split benchmark; prior integrated competition QC measured `vhh_screen=176.168s` plus validator/novelty/diversity for ~225s total.
- Full blocker workflow for one sequence after QC: NanoBodyBuilder2 structure ~0.4-1.0 min typical cadence, HADDOCK3 ~2.4-4.1 min observed, postprocess ~0.3 min; plan ~4-6 min per sequence including ssh/copy overhead.
- Full blocker workflow for 36 sequences with `--jobs 4` docking is not simply 36x single time; docking CPU parallelism and node load are the limiting factors.

## Evidence files

- `reports/qc_positive_metric_ranges/node1_pvrig_11_positive_qc/stage_timings.tsv`
- remote benchmark directory: `/data/qlyu/software/vhh_eval_tools/runs/pvrig_11_positive_qc_20260708/timing_bench_vhh_screen`
- `docking/calibration/mutant_validation_panel/workdirs/*/reports/stage_logs/haddock3.log`
- `reports/qc_positive_metric_ranges/timing_evidence/postprocess_timing.out` and `reports/qc_positive_metric_ranges/timing_evidence/postprocess_timing.err`
