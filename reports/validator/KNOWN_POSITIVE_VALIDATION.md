# Known Positive Validator Run

## Purpose

Run the official `clickmab-bio/ab-data-validator` workflow against the confirmed official-page PVRIG positive references now stored under `positives/`.

This is a validator and reference-control check, not a candidate-design run.

## Tooling

- Repository: `tools/ab-data-validator`
- Commit: `97df17aa09bc576a861cf0d8242de97af379fd80`
- Package version from `pyproject.toml`: `0.1.0`
- License: MIT, per `tools/ab-data-validator/LICENSE`
- Python environment: `.conda-envs/ab-data-validator`
- ANARCI: `.conda-envs/ab-data-validator/bin/ANARCI`, conda package `anarci-2021.02.04`
- MUSCLE: `.conda-envs/ab-data-validator/bin/muscle`, version output `muscle 5.3.linux64`
- Built-in positive library: `tools/ab-data-validator/src/ab_data_validator/data/positive.csv`, 48 records

Docker was not used because Docker Desktop WSL integration is not enabled in this environment. Local micromamba was installed under `.local/bin/micromamba` and used to create the conda-style environment.

## Input

Generated input workbook:

- `reports/validator/known_positive_submit.xlsx`

Rows submitted in official validator column format:

| Name | Type | VH | VL |
| --- | --- | --- | --- |
| `HR-151_VHH` | nanobody | HR-151 VHH sequence | empty |
| `Tab5_full_IgG` | full antibody | Tab5 VH sequence | Tab5 VL sequence |

The standalone Tab5 VL was not submitted as a separate candidate because the validator requires column 3 as VH. Tab5 VL CDRs were instead extracted through the Tab5 full-antibody row and by direct ANARCI chain numbering.

## Command

```bash
PATH="$PWD/.conda-envs/ab-data-validator/bin:$PATH" \
PYTHONPATH=tools/ab-data-validator/src \
.conda-envs/ab-data-validator/bin/python -m ab_data_validator.cli validate \
  --input reports/validator/known_positive_submit.xlsx \
  --output reports/validator/known_positive_failed_reasons.csv \
  --anarci-bin ANARCI \
  --muscle-bin muscle \
  --workers 1
```

## Result

Validator exit code: `0`.

Summary:

```text
Validation summary
Total antibodies: 2
Passed: 0
Failed: 2
Failure report: reports/validator/known_positive_failed_reasons.csv
```

This is the expected behavior for known positive controls: the submitted official positives are highly similar or identical to built-in positive references.

Key failures:

- `HR-151_VHH` matched built-in positive `151` at 100% identity for CDRH1/CDRH2/CDRH3.
- `Tab5_full_IgG` matched built-in positive `CPA.7.021` at 100% identity for CDRH1/CDRH2/CDRH3 and CDRL1/CDRL2/CDRL3.

The converted similarity evidence is stored in:

- `positives/positive_CDR_similarity_exclusion_table.csv`

## Extracted IMGT CDRs

CDRs were extracted using the official validator ANARCI wrapper and IMGT ranges documented by the tool: CDR1 27-38, CDR2 56-65, CDR3 105-117.

| Record | Chain | CDR1 | CDR2 | CDR3 |
| --- | --- | --- | --- | --- |
| `tab5_vh` | VH | `GFTFGTSS` | `ISFDGTEI` | `AKGSGNIYYFSGMDV` |
| `tab5_vl` | VL | `QSISGW` | `ETS` | `QQYYSYPLT` |
| `hr151_vhh` | VHH | `ASGFTYRPYC` | `IDIFGGT` | `AAGDSPDGRCGLPPQGLNY` |

Updated artifacts:

- `positives/positive_antibody_metadata.csv` now marks all three records `anarci_success`.
- `positives/known_positive_CDR_table.csv` now contains CDRs and lengths.
- `positives/positive_CDR_similarity_exclusion_table.csv` now contains official-validator high-identity evidence.

## Additional Verification

Validator unit tests:

```bash
PATH="$PWD/.conda-envs/ab-data-validator/bin:$PATH" \
PYTHONPATH=tools/ab-data-validator/src \
.conda-envs/ab-data-validator/bin/python -m pytest tools/ab-data-validator/tests -m 'not integration' -q
```

Result: `69 passed, 2 deselected`.

Phase I verification:

```bash
scripts/verify_phase_i_outputs.py
```

Result: PASS after updating the script to expect ANARCI-success CDRs and populated similarity evidence.

## Notes

- The first direct validator attempt failed because `ANARCI` was not installed.
- The first conda-backed validator attempt failed because ANARCI could not find `hmmscan`; adding `.conda-envs/ab-data-validator/bin` to `PATH` fixed this.
- No scaffold sequences were imported or scored in this run.
