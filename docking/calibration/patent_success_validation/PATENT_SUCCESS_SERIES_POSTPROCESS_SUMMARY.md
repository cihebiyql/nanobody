# Patent Success Series Postprocess Summary

Updated: 2026-07-08

## Bottom line

- The 11 WO2021180205A1 positive-control VHH/HCVR sequences now all have monomer structures, HADDOCK3 run directories, 8X6B scoring, 9E6Y scoring, and multi-baseline consensus CSVs.
- The calibration is no longer HR-151-only: families 20, 30, 38, 39, and 151 all have completed postprocessing.
- These sequences remain positive controls and leakage references, not new design candidates.
- The computational label means blocker-like geometry or follow-up priority; it is not experimental proof of PVRIG-PVRL2 blocking.

## Aggregate pose labels

- Total cases: 11
- Total poses summarized: 109
- CONSENSUS_BLOCKER_LIKE_A: 3
- SINGLE_BASELINE_BLOCKER_RECHECK: 36
- BLOCKER_PLAUSIBLE_B: 57
- EVIDENCE_INFERENCE_ONLY_E: 13

## Family coverage

| family | completed cases | case-level calls |
| --- | ---: | --- |
| 151 | 3 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK=3 |
| 20 | 2 | HAS_CONSENSUS_BLOCKER_LIKE_A=1; HAS_SINGLE_BASELINE_BLOCKER_RECHECK=1 |
| 30 | 2 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK=2 |
| 38 | 1 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK=1 |
| 39 | 3 | BLOCKER_PLAUSIBLE_B_ONLY=1; HAS_SINGLE_BASELINE_BLOCKER_RECHECK=2 |

## Per-sequence calibration summary

| order | molecule | family | IC50 nM | Kd M | case call | poses | A/A consensus | single-baseline A | plausible | top model consensus | top 8X6B metrics | top 9E6Y metrics |
| ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 1 | PVRIG-151_HR151 | 151 | 0.37 | 2.00E-10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 5 | 5 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=15; total=875; cdr3=197; frac=0.225143 | BLOCKER_PLAUSIBLE_B; hotspot=10; total=926; cdr3=193; frac=0.208423 |
| 2 | PVRIG-20 | 20 | 1.18 | 2.36E-10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 4 | 4 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=19; total=528; cdr3=158; frac=0.299242 | BLOCKER_PLAUSIBLE_B; hotspot=12; total=511; cdr3=163; frac=0.318982 |
| 3 | PVRIG-30 | 30 | 1.11 | 7.23E-10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 4 | 6 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=14; total=517; cdr3=137; frac=0.26499 | BLOCKER_PLAUSIBLE_B; hotspot=9; total=504; cdr3=142; frac=0.281746 |
| 4 | PVRIG-38 | 38 | 0.93 | 2.17E-09 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 3 | 7 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=18; total=580; cdr3=129; frac=0.222414 | BLOCKER_PLAUSIBLE_B; hotspot=12; total=574; cdr3=120; frac=0.209059 |
| 5 | PVRIG-39 | 39 | 0.76 | 6.96E-10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 3 | 7 | BLOCKER_PLAUSIBLE_B | BLOCKER_PLAUSIBLE_B; hotspot=13; total=696; cdr3=134; frac=0.192529 | BLOCKER_PLAUSIBLE_B; hotspot=10; total=729; cdr3=135; frac=0.185185 |
| 6 | 20H5 | 20 |  | 6.98E-11 | HAS_CONSENSUS_BLOCKER_LIKE_A | 10 | 3 | 5 | 2 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=15; total=592; cdr3=136; frac=0.22973 | BLOCKER_PLAUSIBLE_B; hotspot=12; total=610; cdr3=140; frac=0.229508 |
| 7 | 30H2 | 30 |  | 1.92E-09 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 9 | 0 | 1 | 6 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=15; total=612; cdr3=103; frac=0.168301 | BLOCKER_PLAUSIBLE_B; hotspot=9; total=611; cdr3=87; frac=0.14239 |
| 8 | 39H2 | 39 |  | 6.92E-10 | BLOCKER_PLAUSIBLE_B_ONLY | 10 | 0 | 0 | 5 | BLOCKER_PLAUSIBLE_B | BLOCKER_PLAUSIBLE_B; hotspot=16; total=815; cdr3=103; frac=0.12638 | BLOCKER_PLAUSIBLE_B; hotspot=10; total=831; cdr3=97; frac=0.116727 |
| 9 | 39H4 | 39 |  | 4.82E-10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 2 | 6 | SINGLE_BASELINE_BLOCKER_RECHECK | BLOCKER_LIKE_A; hotspot=17; total=779; cdr3=139; frac=0.178434 | BLOCKER_PLAUSIBLE_B; hotspot=13; total=817; cdr3=142; frac=0.173807 |
| 10 | 151H7 | 151 |  | 1.20E-09 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 5 | 3 | BLOCKER_PLAUSIBLE_B | BLOCKER_PLAUSIBLE_B; hotspot=11; total=582; cdr3=108; frac=0.185567 | BLOCKER_PLAUSIBLE_B; hotspot=11; total=595; cdr3=120; frac=0.201681 |
| 11 | 151H8 | 151 |  |  | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | 10 | 0 | 4 | 6 | BLOCKER_PLAUSIBLE_B | BLOCKER_PLAUSIBLE_B; hotspot=17; total=474; cdr3=111; frac=0.234177 | EVIDENCE_INFERENCE_ONLY_E; hotspot=9; total=472; cdr3=112; frac=0.237288 |

## Judgment rule used

- A-level VHH docking screen: hotspot_overlap_count >= 14, total VHH-PVRL2 residue-pair occlusion >= 500, CDR3-PVRL2 residue-pair occlusion >= 100, CDR3 occlusion fraction >= 0.15.
- Hotspot-only poses with weak PVRL2 occlusion are downgraded instead of treated as blockers.
- 8X6B and 9E6Y are treated as independent baselines; two-baseline support is stronger than one-baseline support.
- Binding/Kd, blocking/IC50, docking geometry, format context, NK/Fc/CD226/TIGIT biology, and positive-control leakage remain separate fields.

## Reproducibility

```bash
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
python docking/success_case_validation/test_success_case_workflow.py
python docking/success_case_validation/validate_success_case_standards.py
```
