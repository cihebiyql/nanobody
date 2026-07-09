# Sequence-to-blocker workflow status

Updated: 2026-07-08

## Direct answer

The sequence-to-blocker workflow is now calibrated beyond HR-151:

1. The curated WO2021180205A1 PVRIG VHH success series has completed structure,
   HADDOCK3 docking, 8X6B scoring, 9E6Y scoring, and multi-baseline consensus
   postprocessing for all 11 selected positives.
2. The completed VHH calibration covers families 20, 30, 38, 39, and 151, so
   HR-151 is no longer the only executed positive-control geometry.
3. COM701/CPA.7.021/Tab5, IBI352g4a, GSK4381562/SRF813, SHR-2002,
   PM1009/SIM0348, CD112RIVE, and NK biology cases are encoded as explicit
   judgment criteria and context gates.
4. The workflow now supports a single new VHH sequence through candidate
   workdir generation -> monomer structure -> HADDOCK3 docking -> 8X6B/9E6Y
   PVRL2-occlusion scoring -> per-baseline classification -> consensus label.

The key aggregate report is
`docking/calibration/patent_success_validation/PATENT_SUCCESS_SERIES_POSTPROCESS_SUMMARY.md`.
The machine-readable aggregate table is
`docking/calibration/patent_success_validation/batch_consensus_summary.csv`.
The execution-safe CDR table is
`机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv`.
The mechanism-vs-structure audit is
`docking/success_case_validation/POSITIVE_MECHANISM_STRUCTURAL_VALIDATION_AUDIT.md`.
The final workflow completion audit is
`docking/success_case_validation/WORKFLOW_COMPLETION_AUDIT.md`.

## What is learned from other successful cases

- COM701/CPA.7.021/Tab5: binder is not enough; require ligand blocking or PVRL2 competition. R95 is a high-weight soft hotspot, I97 weaker, S67 advisory only. Do not copy positive-control CDRs.
- IBI352g4a: after molecular blocking, Fc/CD16a/NK context is an independent efficacy layer; docking alone cannot predict Fc/NK effect.
- GSK4381562/SRF813: distinct epitopes are allowed, but blocking CD112/PVRL2 remains required. This prevents overfitting to HR-151/Tab5/R95-I97.
- SHR-2002 and other bispecifics: VHH/scFv arms can succeed in format-level TIGIT/PVRIG co-blocking; naked VHH docking is not the whole drug-format story.
- CD112RIVE: structure-guided interface engineering supports contact-density and interface-priority features, but it is not an antibody CDR template.
- NK biology cases: NK activation and PVRL2-high tumor context must be retained as downstream labels.

These are encoded in:

- `success_case_mechanism_criteria_matrix.csv`
- `blocker_judgment_rules_v2.json`
- `blocker_design_judgment_standards_v2.md`

## What happens if we have one new VHH sequence

Current supported path:

```text
VHH sequence
  -> prepare candidate workdir
  -> NanoBodyBuilder2 monomer structure on node1
  -> hotspot/CDR-guided HADDOCK3 docking to fixed PVRIG
  -> align poses to 8X6B and score PVRL2 occlusion
  -> align poses to 9E6Y and score PVRL2 occlusion
  -> classify each baseline
  -> combine baselines into consensus
  -> report blocker-like / plausible / binder-like / discordant
```

Scaffold command:

```bash
python docking/success_case_validation/prepare_candidate_sequence_workflow.py \
  --name candidate_name \
  --sequence 'HVQL...' \
  --out-root docking/candidates \
  --auto-cdr
```

The generated candidate directory contains the ANARCI-derived CDR range table,
node1 structure-prediction command, HADDOCK3 config template, CDR-to-hotspot
restraints, and post-docking classification commands. If local ANARCI is not
available, the same command accepts manual `--cdr1/--cdr2/--cdr3` ranges.

For the 11 patent positives, do not use `docking/candidates` as the destination.
They are positive controls/leakage references, not candidate submissions:

```bash
python docking/success_case_validation/prepare_patent_success_validation_batch.py
bash docking/calibration/patent_success_validation/run_all_node1_structure_predictions.sh
bash docking/calibration/patent_success_validation/run_all_node1_haddock3.sh
bash docking/calibration/patent_success_validation/postprocess_all_haddock3_runs.sh
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
```

## What has been tested

- Standards validation: 36 criteria across 8 success/biology cases.
- HR-151 8X6B reclassification: 4 `BLOCKER_LIKE_A`, 1 `BINDER_LIKE_C`, matching the earlier artifact.
- HR-151 9E6Y mapped baseline: 1 `BLOCKER_LIKE_A`, 4 `BLOCKER_PLAUSIBLE_B`.
- HR-151 8X6B+9E6Y consensus: `cluster_1_model_1` is `CONSENSUS_BLOCKER_LIKE_A`; `cluster_2_model_1` is discordant and should not be promoted without recheck.
- Kabsch alignment math has a regression test after fixing the row-vector rotation formula.
- Candidate workdir generation has been dry-run with the HR-151 FASTA as `docking/candidates/hr151_template_test`.
- Patent success-series batch generation rebuilds CDR ranges from raw ANARCI IMGT columns and writes 11 isolated calibration workdirs under `docking/calibration/patent_success_validation/`.
- Patent success-series execution is complete: 11/11 monomer chain-A PDBs, 11/11 HADDOCK3 run directories, and 11/11 consensus CSVs.
- Patent success-series aggregate labels across 109 poses: 3 `CONSENSUS_BLOCKER_LIKE_A`, 36 `SINGLE_BASELINE_BLOCKER_RECHECK`, 57 `BLOCKER_PLAUSIBLE_B`, and 13 `EVIDENCE_INFERENCE_ONLY_E`.
- Non-151 calibration evidence is present: PVRIG-20, PVRIG-30, PVRIG-38, PVRIG-39, 20H5, 30H2, 39H2, and 39H4 all have completed 8X6B+9E6Y postprocessing.
- 20H5 is the strongest completed non-151 geometry control in this batch, with 3 `CONSENSUS_BLOCKER_LIKE_A` poses.
- Patent sequence artifact validation now locks FASTA=30, mapping=30, raw ANARCI=30, success series=11, batch=11, HR-151 identity, non-151 family coverage, and expected summary-vs-raw CDR3 audit mismatches.

## CDR source-of-truth for execution

- Use `PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv` for `raw_anarci_imgt_cdr*_exact` and `cdr*_range` scorer inputs.
- Keep `PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv` as legacy summary/display evidence only.
- The summary table CDR3 differs from raw ANARCI exact FASTA order for all 30 rows; this is now a fixed audit warning, not a batch blocker.

## What is not yet complete

- Other non-VHH successful antibody or format cases have not all been structurally docked. Reasons:
  - Some are IgG/scFv/bispecific or receptor-trap formats, not directly comparable naked VHH docking targets.
  - Public residue-level complexes are unavailable for COM701/IBI352g4a/SRF813 in the local artifact set.
- Structural status for each mechanism case is explicitly tracked in `POSITIVE_MECHANISM_STRUCTURAL_VALIDATION_AUDIT.md`.
- Experimental binding/blocking is not proven by this workflow; `BLOCKER_LIKE_A` is a computational prioritization label.

## Correct use going forward

- Use HR-151 as positive control and leakage exclusion, not design template.
- Keep PVRIG-20/30/38/39/151 plus selected humanized arms in the calibration batch so the rules do not overfit to HR-151.
- For any new candidate, require both geometry and success-case-context labels:
  - 8X6B/9E6Y PVRL2 occlusion
  - hotspot/interface coverage
  - CDR/paratope plausibility
  - positive-control sequence leakage check
  - format/NK/Fc/TIGIT/CD226 context annotation

## Positive-control QC metric ranges

The non-docking QC ranges for the 11 PVRIG VHH positives are now captured in
`reports/qc_positive_metric_ranges/PVRIG_POSITIVE_QC_METRIC_RANGES.md`, with
machine-readable summaries in `reports/qc_positive_metric_ranges/pvrig_positive_qc_metric_ranges.csv`
and per-sequence metrics in
`reports/qc_positive_metric_ranges/pvrig_positive_qc_per_sequence_metrics.csv`.

The key interpretation is layered:

- Stable hard gates: standard input, numbering/CDR completeness, and known-positive
  CDR leakage exclusion.
- Warn/ranking gates: FR2/VHH-like, AbNatiV, Sapiens, physicochemical metrics,
  TNP, Cys/liability motifs, and diversity.
- Biology gate: blocker likelihood still requires the separate structure and
  PVRIG/PVRL2 docking/occlusion path; sequence QC metrics do not prove blocking.

Positive-control evidence specifically shows that FR2/VHH-like and TNP flags
must not be used as blocker-biology hard fails: 6/11 known blockers are L2
VHH-feature failures or poor single-domain by the current QC run, and 2/11
known blockers have all-11 TNP PNC red flags.

## Runtime estimate for the screening stack

The current runtime estimate is captured in
`reports/qc_positive_metric_ranges/PVRIG_SCREENING_RUNTIME_ESTIMATE.md`, with
machine-readable rows in
`reports/qc_positive_metric_ranges/pvrig_screening_runtime_estimates.csv`.

On the 11-positive benchmark, sequence-only QC is roughly 3-4 minutes end to
end. The slow sequence-QC item is TNP through `vhh-screen`; L1/basic checks are
seconds, while AbNatiV and Sapiens are tens of seconds per 11 sequences. When
blocker geometry is required, structure plus HADDOCK3 dominates: current
single-sequence planning should reserve roughly 4-6 minutes including
NanoBodyBuilder2, HADDOCK3, transfer, and 8X6B/9E6Y postprocessing.

## 2026-07-08 robustness and batch-readiness refresh

New local robustness layer added after the 11-positive calibration batch:

- `validate_batch_screening_outputs.py`: read-only-style batch integrity validator for the completed 11-case docking outputs; it locks 11 cases, 109 consensus pose rows, and aggregate labels A/A=3, single-A=36, B=57, E=13.
- `analyze_threshold_sensitivity.py`: postprocessing-only threshold grid over existing 8X6B/9E6Y outputs; default row reproduces the locked aggregate counts and writes `threshold_sensitivity_summary.csv` plus `THRESHOLD_SENSITIVITY_REPORT.md`.
- `analyze_mutant_panel_threshold_sensitivity.py`: the same threshold grid over the completed 36-row mutant/control panel; default row reproduces 357 rows and A/A=8, single-A=109, B=210, E=30.
- `prepare_mutant_validation_batch.py`: generates a 36-record non-151-heavy VHH mutant/control panel under `docking/calibration/mutant_validation_panel/` for batch scaffold and later node1 docking validation.
- `check_vhh_sequence_leakage.py`: checks exact and near-positive sequence leakage against the patent/known-positive references; the mutant panel intentionally yields exact=7 and near=29 as positive controls for the leakage gate.
- `test_blocker_screening_robustness.py`: fast regression for classifier boundaries, dual-baseline consensus branches, batch integrity, threshold default counts, candidate scaffold generation, and mutant leakage gate.
- `run_mutant_panel_batch.py`: resumable staged runner for the mutant/control panel; structure runs sequentially, docking/postprocess can run with `--jobs`.
- `validate_mutant_panel_completion.py`: locks the completed 36/36 mutant panel and aggregate consensus counts.
- `summarize_mutant_panel_results.py`: stratifies the completed mutant/control panel by family, mutation class, leakage label, and base molecule, then flags retained-A CDR3 disruptive/alanine controls for manual review.

Current validation evidence:

```bash
python docking/success_case_validation/validate_batch_screening_outputs.py
python docking/success_case_validation/analyze_threshold_sensitivity.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
python docking/success_case_validation/prepare_mutant_validation_batch.py
python docking/success_case_validation/check_vhh_sequence_leakage.py \
  --candidate-csv docking/calibration/mutant_validation_panel/mutant_panel.csv \
  --out-csv docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv
python docking/success_case_validation/run_mutant_panel_batch.py --stage structure --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage docking --jobs 4 --keep-going
python docking/success_case_validation/run_mutant_panel_batch.py --stage postprocess --jobs 4 --keep-going
python docking/success_case_validation/summarize_mutant_panel_status.py
python docking/success_case_validation/validate_mutant_panel_completion.py
python docking/success_case_validation/summarize_mutant_panel_results.py
python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py
python docking/success_case_validation/test_blocker_screening_robustness.py
python3 -m py_compile docking/success_case_validation/*.py docking/scripts/*.py
```

All commands above passed locally on 2026-07-08. The mutant panel has now completed structure prediction, HADDOCK3 docking, 8X6B scoring, 9E6Y scoring, and consensus postprocessing for all 36 rows.

### Mutant panel full execution evidence

After generating the 36-record mutant/control panel, all 36 rows were run through real node1 structure prediction, HADDOCK3 docking, and local 8X6B/9E6Y postprocessing.

- Completion: structure-ready 36/36, structure QC sane 36/36, HADDOCK3 run dirs 36/36, consensus CSVs 36/36.
- Aggregate labels across 357 consensus rows: 8 `CONSENSUS_BLOCKER_LIKE_A`, 109 `SINGLE_BASELINE_BLOCKER_RECHECK`, 210 `BLOCKER_PLAUSIBLE_B`, 30 `EVIDENCE_INFERENCE_ONLY_E`.
- Stratification: family 20/30/38/39 are all represented; mutation classes include unmutated controls, conservative CDR3, aromatic-to-alanine, multi-CDR3 alanine scans, framework controls, and the PVRIG-20 D103E-style row.
- Manual review queue: 12 CDR3 disruptive/alanine rows retain A/A or single-baseline A signal, so they should be inspected for pose/constraint artifacts before biological interpretation.
- Mutant threshold sensitivity: 81 settings tested; default row reproduces locked aggregate counts, 4/81 settings preserve default case-level calls, and default retained-A disruptive/alanine controls are consensus-A=3 and any-A=12.
- Leakage labels: 7 `EXACT_KNOWN_POSITIVE`, 29 `NEAR_KNOWN_POSITIVE`; all rows remain controls/leakage references, not new designs.

The full status is summarized in `docking/calibration/mutant_validation_panel/MUTANT_PANEL_STATUS_SUMMARY.md`, locked by `docking/calibration/mutant_validation_panel/MUTANT_PANEL_COMPLETION_VALIDATION.md`, stratified in `docking/calibration/mutant_validation_panel/MUTANT_PANEL_RESULT_STRATIFICATION.md`, and threshold-audited in `docking/calibration/mutant_validation_panel/MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md`. This validates the mutant batch execution path and exposes cases that need manual pose review, especially CDR3 alanine/aromatic mutants retaining A-level labels.
