# Positive Mechanism Structural Validation Audit

Updated: 2026-07-08

## Bottom line

- The executable sequence-to-blocker screening workflow is documented and reproducible in `docking/success_case_validation/README.md` and `docking/success_case_validation/SEQUENCE_TO_BLOCKER_WORKFLOW_STATUS.md`.
- The full local structure-prediction -> HADDOCK3 docking -> 8X6B/9E6Y PVRL2-occlusion -> consensus path has been run for the 11 WO2021180205A1 VHH positive calibration sequences.
- Other successful mechanisms are encoded as judgment standards and context gates, but most have not been locally structure-predicted and docked because they are IgG/scFv/bispecific/receptor-trap biology cases or lack verified local Fv/complex inputs.
- Do not describe mechanism-only cases as structurally docked. Use the status labels below.

## Status labels

- `STRUCTURE_DOCKING_DONE`: local monomer/model + HADDOCK3 docking + 8X6B and 9E6Y postprocessing exist.
- `PARTIAL_ARM_DOCKED`: a relevant VHH arm was docked, but the full drug format was not docked.
- `RULES_ONLY_NOT_LOCAL_DOCKED`: mechanism contributes rules but no local structure/docking run exists.
- `REFERENCE_INTERFACE_ONLY`: used as receptor/ligand structure baseline or interface prior, not antibody docking.
- `BIOLOGY_CONTEXT_ONLY`: used for downstream assay/context labels, not structural validation.

## Executable VHH positive calibration batch

- Cases with complete local workdirs: 11/11.
- Poses summarized: 109.
- `CONSENSUS_BLOCKER_LIKE_A`: 3.
- `SINGLE_BASELINE_BLOCKER_RECHECK`: 36.
- `BLOCKER_PLAUSIBLE_B`: 57.
- `EVIDENCE_INFERENCE_ONLY_E`: 13.
- Evidence files: `docking/calibration/patent_success_validation/batch_status.csv`, `docking/calibration/patent_success_validation/batch_consensus_summary.csv`, and per-case `reports/*_8x6b_9e6y_consensus.csv`.

| order | molecule | family | structural status | pose count | case call | strongest evidence | top model call | evidence path |
| ---: | --- | ---: | --- | ---: | --- | --- | --- | --- |
| 1 | PVRIG-151_HR151 | 151 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=5 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_01_PVRIG-151_HR151/reports/case02_pos_01_PVRIG-151_HR151_8x6b_9e6y_consensus.csv` |
| 2 | PVRIG-20 | 20 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=4 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_02_PVRIG-20/reports/case02_pos_02_PVRIG-20_8x6b_9e6y_consensus.csv` |
| 3 | PVRIG-30 | 30 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=4 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_03_PVRIG-30/reports/case02_pos_03_PVRIG-30_8x6b_9e6y_consensus.csv` |
| 4 | PVRIG-38 | 38 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=3 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_04_PVRIG-38/reports/case02_pos_04_PVRIG-38_8x6b_9e6y_consensus.csv` |
| 5 | PVRIG-39 | 39 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=3 | BLOCKER_PLAUSIBLE_B | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_05_PVRIG-39/reports/case02_pos_05_PVRIG-39_8x6b_9e6y_consensus.csv` |
| 6 | 20H5 | 20 | STRUCTURE_DOCKING_DONE | 10 | HAS_CONSENSUS_BLOCKER_LIKE_A | A/A consensus=3 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_06_20H5/reports/case02_pos_06_20H5_8x6b_9e6y_consensus.csv` |
| 7 | 30H2 | 30 | STRUCTURE_DOCKING_DONE | 9 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=1 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_07_30H2/reports/case02_pos_07_30H2_8x6b_9e6y_consensus.csv` |
| 8 | 39H2 | 39 | STRUCTURE_DOCKING_DONE | 10 | BLOCKER_PLAUSIBLE_B_ONLY | plausible=5 | BLOCKER_PLAUSIBLE_B | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_08_39H2/reports/case02_pos_08_39H2_8x6b_9e6y_consensus.csv` |
| 9 | 39H4 | 39 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=2 | SINGLE_BASELINE_BLOCKER_RECHECK | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_09_39H4/reports/case02_pos_09_39H4_8x6b_9e6y_consensus.csv` |
| 10 | 151H7 | 151 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=5 | BLOCKER_PLAUSIBLE_B | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_10_151H7/reports/case02_pos_10_151H7_8x6b_9e6y_consensus.csv` |
| 11 | 151H8 | 151 | STRUCTURE_DOCKING_DONE | 10 | HAS_SINGLE_BASELINE_BLOCKER_RECHECK | single-baseline A=4 | BLOCKER_PLAUSIBLE_B | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_11_151H8/reports/case02_pos_11_151H8_8x6b_9e6y_consensus.csv` |

## Mechanism-case structural audit

| mechanism case | status | what was locally validated | what was not structurally docked | why / boundary | how it is used in the standard |
| --- | --- | --- | --- | --- | --- |
| PVRIG-20/30/38/39/151 and HR-151 | STRUCTURE_DOCKING_DONE | 11 selected VHH/HCVR positives have monomer PDBs, HADDOCK3 run dirs, 8X6B classifications, 9E6Y classifications, and consensus CSVs. | Full Fc-fusion or bispecific architecture is not modeled here. | The local workflow evaluates naked VHH/Fv-like paratope geometry first. | Primary executable positive calibration and leakage-exclusion family. |
| COM701 / CPA.7.021 / Tab5 | RULES_ONLY_NOT_LOCAL_DOCKED | Binder-vs-blocker logic, R95/I97/S67 soft-hotspot weighting, and leakage rules are encoded in criteria. | No local COM701/Tab5 Fv structure prediction or docking run. | Public/local artifact set lacks a verified sequence/complex suitable for this VHH scaffold workflow. | Hard negative control: binding alone is not blocking; R95 is high-weight soft hint; sequence copying is forbidden. |
| IBI352g4a | RULES_ONLY_NOT_LOCAL_DOCKED | Blocking-first plus Fc/CD16a/NK context rules are encoded. | No local IgG1 Fv docking or Fc/NK structural modeling. | It is an Fc-competent IgG1 biology case; static naked VHH docking cannot validate Fc/NK effects. | Keeps binding, blocking, Fc engagement, NK context, and model context as separate scores. |
| GSK4381562 / SRF813 | RULES_ONLY_NOT_LOCAL_DOCKED | Distinct-epitope anti-overfit and blocking-still-required rules are encoded. | No local SRF813/GSK4381562 structure prediction or docking run. | Exact public epitope/complex inputs are not in the local artifact set. | Allows non-HR151 epitopes only if they still occlude/interfere with PVRL2/CD112. |
| SHR-2002 / TIGIT-8-PVRIG-30-IgG4 | PARTIAL_ARM_DOCKED | The PVRIG-30 VHH arm family is included and docked through the patent positive batch. | The full TIGIT/PVRIG bispecific architecture, linker exposure, and co-engagement geometry were not docked. | Whole-format modeling needs TIGIT arm, linker, Fc/IgG4 architecture, and co-engagement constraints. | Keeps PVRIG-30 as a real positive family and adds format/fusion-exposure checks. |
| PM1009 / SIM0348 | RULES_ONLY_NOT_LOCAL_DOCKED | Multi-axis TIGIT/PVRIG/DNAM/CD226 labels are encoded. | No local sequence, structure prediction, or docking. | Available local evidence is mechanism-summary level, not residue/structure level. | Adds co-blocking and effector-function annotations, not numeric docking thresholds. |
| CD112RIVE / engineered CD112R variants | REFERENCE_INTERFACE_ONLY | PVRIG/PVRL2 interface structures and contact-density concepts support 8X6B/9E6Y baselines and interface priors. | Not anti-PVRIG antibody docking; no antibody CDR/paratope run. | It is receptor/ligand engineering, not antibody modality. | Supports interface-residue priority and contact-density rationale. |
| NK-cell blockade biology | BIOLOGY_CONTEXT_ONLY | NK/PVRL2-high tumor context is encoded as downstream validation requirement. | No local structural docking. | Functional biology paper lacks residue-level antibody docking input. | Adds NK activation and tumor-context labels; docking cannot substitute for assays. |

## What would be required to structurally validate the non-VHH mechanism cases

- A verified heavy/light Fv or scFv/VHH sequence for each molecule, not just a drug name or mechanism summary.
- A modality-specific structural template or modeling route: IgG/Fab for COM701/IBI352g4a/SRF813, bispecific architecture for SHR-2002/PM1009/SIM0348, receptor/ligand model for CD112RIVE-like traps.
- Chain normalization and ANARCI/IMGT CDR extraction under the same CDR source-of-truth rules used for the VHH batch.
- Docking or complex prediction against PVRIG followed by the same 8X6B/9E6Y PVRL2 overlay scoring where the modality is comparable.
- Separate reporting for paratope blocking geometry versus Fc/NK/TIGIT/CD226 biological context.

## Recheck commands

```bash
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
python docking/success_case_validation/validate_patent_sequence_artifacts.py
python docking/success_case_validation/validate_success_case_standards.py
python docking/success_case_validation/test_success_case_workflow.py
```
