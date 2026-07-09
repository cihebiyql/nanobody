# Candidate sequence workflow: case02_pos_08_39H2

This workdir is for a candidate VHH sequence entering the PVRIG blocker workflow.

## Input

- Candidate: `case02_pos_08_39H2`
- Length: 120 aa
- CDR ranges for first-pass scoring: CDR1 `26-33`, CDR2 `51-57`, CDR3 `96-109`

## What this workflow can decide

It can decide whether docking poses are structurally blocker-like against
PVRIG-PVRL2/CD112 under the success-case-calibrated rules.

It cannot prove experimental blocking. A `BLOCKER_LIKE_A` call means:

```text
pose geometry is consistent with successful PVRIG blocker cases
and should be prioritized for leakage checks, second-baseline scoring, and assay.
```

## Required stages

1. Sequence sanity and optional DeepNano binding-like prescreen.
2. VHH monomer prediction with NanoBodyBuilder2.
3. Hotspot/CDR-guided docking to fixed PVRIG.
4. 8X6B PVRL2 overlay occlusion scoring.
5. 9E6Y PVRL2 overlay occlusion scoring.
6. Multi-baseline consensus classification.
7. Positive-control leakage exclusion against HR-151/Tab5/known positives.

## Files generated here

- `inputs/case02_pos_08_39H2_vhh.fasta`
- `haddock3/case02_pos_08_39H2_pvrig_hotspot_test.cfg`
- `haddock3/data/case02_pos_08_39H2_cdr_to_pvrig_hotspot_ambig.tbl`
- `run_node1_structure_prediction.sh`
- `postprocess_after_docking.sh`

## Current caution

The workflow has learned other successful cases as rules, not as all-structure
positive-control docking runs. HR-151 is the current fully executed positive
control because it has a complete official VHH sequence and local docking output.
Other cases still influence the decision through anti-overfit, Fc/NK, format,
CD226/TIGIT, and binder-vs-blocker criteria.
