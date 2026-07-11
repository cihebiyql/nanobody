# V2.4 top2 candidate-specific PVRIG complex pose assets

Scope: local writes only under `/mnt/d/work/抗体/docking/candidates/v2_4_top2/`; remote writes only under `/data/qlyu/projects/pvrig_v2_4_top2/`.

These are computational pose assets only. They are not experimental binding or blocking evidence.

## Candidate manifest checks

| candidate_id | source_row | VHH SHA256 | CDR3 | CDR3 range | leakage label |
| --- | ---: | --- | --- | --- | --- |
| zym_test_9743 | 7 | `f727c0f37736c65c02c86b039c7729ac82c359b84961af76b2bbbb5d9e9c4023` | `NSFYYYSQAYDNYSVY` | 104-119 | NO_KNOWN_POSITIVE_LEAKAGE |
| zym_test_108006 | 47 | `76413dbdc48ab17b144ab10be41e5ebc07b20faeab5865f6b893aea2d5ddf0bb` | `VRGYFMRLPSSHNFRY` | 104-119 | NO_KNOWN_POSITIVE_LEAKAGE |

Source manifest SHA256: `86b449b16fc32d256580cffb6319d425b2bc0b9fae104d4947998e2e440b7e21`.

## Run status

| candidate_id | NBB2 | monomer sequence | monomer geometry | HADDOCK3 8X6B top PDB.gz |
| --- | --- | --- | --- | ---: |
| zym_test_9743 | completed_refined_default | exact match | sane backbone, CA=130 | 10 |
| zym_test_108006 | completed_with_no_sidechain_bond_check_fallback | exact match | sane backbone, CA=130 | 6 |

## Evidence files

- Local synchronized evidence: `remote_sync/`
- Remote project: `/data/qlyu/projects/pvrig_v2_4_top2/`
- Selected candidate manifest: `manifests/selected_candidates_manifest.tsv`
- Local file SHA256 index: `manifests/local_project_sha256.tsv`
- Remote file listing snapshot: `manifests/remote_file_listing.txt`
- PDB sequence validation: `reports/pdb_sequence_validation.tsv` and `reports/pdb_sequence_validation.json`
- Per-candidate status: `reports/run_status.tsv` and `reports/run_status.json`

## Failure evidence retained

- `remote_sync/logs/zym_test_108006_nanobodybuilder2.log` records the default NBB2 refinement OpenMM `new_Context` TypeError.
- `remote_sync/logs/zym_test_108006_fallback_no_sidechain_bond_check.20260711_002549.log` records the successful NBB2 `-u` fallback and subsequent HADDOCK3 completion.
