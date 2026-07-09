# Patent Success Series Calibration Batch

## Result

- Prepared calibration workdirs: 11
- Families covered: 151=3, 20=2, 30=2, 38=1, 39=3
- Raw ANARCI CDR3 exact FASTA matches: 11/11
- Existing summarized CDR-table CDR3 mismatches kept as audit warnings: 11

## Boundary

- These 11 sequences are positive controls for calibration and leakage exclusion.
- They must not be submitted or ranked as new designs.
- CDR ranges below are sequence-position ranges derived from raw ANARCI IMGT columns.
- `run_node1_structure_prediction.sh` normalizes NanoBodyBuilder2 output to chain A with sequential residue IDs before HADDOCK.
- The NanoBodyBuilder2 command now uses `-u` to avoid rare ImmuneBuilder/OpenMM sidechain-repair failures; local geometry QC still checks backbone sanity.

## Batch Commands

```bash
bash /mnt/d/work/抗体/docking/calibration/patent_success_validation/run_all_node1_structure_predictions.sh
bash /mnt/d/work/抗体/docking/calibration/patent_success_validation/run_all_node1_haddock3.sh
bash /mnt/d/work/抗体/docking/calibration/patent_success_validation/postprocess_all_haddock3_runs.sh
python docking/success_case_validation/check_patent_success_calibration_status.py
python docking/success_case_validation/summarize_patent_success_calibration.py
python docking/success_case_validation/validate_patent_sequence_artifacts.py
```

## Sequences

| order | name | family | IC50 nM | Kd M | CDR1 | CDR2 | CDR3 | workdir |
| ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | PVRIG-151_HR151 | 151 | 0.37 | 2.00E-10 | 26-35 | 53-59 | 98-116 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_01_PVRIG-151_HR151` |
| 2 | PVRIG-20 | 20 | 1.18 | 2.36E-10 | 26-33 | 51-57 | 96-110 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_02_PVRIG-20` |
| 3 | PVRIG-30 | 30 | 1.11 | 7.23E-10 | 26-33 | 52-58 | 97-110 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_03_PVRIG-30` |
| 4 | PVRIG-38 | 38 | 0.93 | 2.17E-09 | 26-33 | 51-58 | 97-112 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_04_PVRIG-38` |
| 5 | PVRIG-39 | 39 | 0.76 | 6.96E-10 | 26-33 | 51-57 | 96-109 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_05_PVRIG-39` |
| 6 | 20H5 | 20 |  | 6.98E-11 | 26-33 | 51-57 | 96-110 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_06_20H5` |
| 7 | 30H2 | 30 |  | 1.92E-09 | 26-33 | 52-58 | 97-110 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_07_30H2` |
| 8 | 39H2 | 39 |  | 6.92E-10 | 26-33 | 51-57 | 96-109 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_08_39H2` |
| 9 | 39H4 | 39 |  | 4.82E-10 | 26-33 | 51-57 | 96-109 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_09_39H4` |
| 10 | 151H7 | 151 |  | 1.20E-09 | 26-35 | 53-59 | 98-116 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_10_151H7` |
| 11 | 151H8 | 151 |  |  | 26-35 | 53-59 | 98-116 | `/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_11_151H8` |

## CDR Audit Note

The previously summarized IMGT CDR table is retained as source evidence, but this batch uses raw ANARCI column order.
That matters for long CDR3s with insertion columns such as 111A/111B/111C/112C/112B/112A.

Execution-safe CDR table:

```text
机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv
```

Use `raw_anarci_imgt_cdr*_exact` and `cdr*_range` from that file for scorer
inputs. The older summarized CDR3 column is retained only as an audit/display
field because it differs from raw exact FASTA order for all 30 patent records.
