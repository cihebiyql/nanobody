# Leader Verification Log

## Team Lifecycle

- Started team: `phase-i-pvrig-blockin-2a7dab99`.
- Verified ACK mailbox messages from worker-1, worker-2, and worker-3.
- Reassigned scaffold exploration after worker-3 reported a claim conflict.
- Final pre-shutdown status: 5 completed, 0 pending, 0 in-progress, 0 failed.
- Shutdown command completed and `omx team status phase-i-pvrig-blockin-2a7dab99` reported no team state found.

## Leader Corrections

- Fixed the initial interface consensus method: raw PDB residue numbers differ across `8X6B` and `9E6Y`, so consensus is now based on PVRIG sequence alignment columns.
- Upgraded `data/structures/PVRIG_epitope_priority_map.pml` from comment-only notes to executable per-structure PyMOL selections using raw residue IDs.
- Confirmed Tab5 and HR-151 sequences from the official competition page and wrote them to `positives/` with CDRs marked `pending_anarci`.
- Kept COM701 out of `known_positive_antibodies.fasta` and recorded it as mechanism reference only.
- Created scaffold schema/registry artifacts without importing unsupported bulk sequence data.

## Verified Artifacts

- `PROJECT_PROGRESS.md`
- `docs/PHASE_I_PLAN.md`
- `docs/PHASE_I_EXPLORATION.md`
- `scripts/extract_pvrig_interface.py`
- `data/structures/8X6B.pdb`
- `data/structures/9E6Y.pdb`
- `data/structures/PVRIG_interface_residues_8X6B.csv`
- `data/structures/PVRIG_interface_residues_9E6Y.csv`
- `data/structures/PVRIG_ligand_contact_pairs_8X6B.csv`
- `data/structures/PVRIG_ligand_contact_pairs_9E6Y.csv`
- `data/structures/PVRIG_consensus_interface_residues.csv`
- `data/structures/PVRIG_epitope_priority_map.pml`
- `data/structures/PVRIG_soft_epitope_hints.csv`
- `data/structures/PVRIG_numbering_reconciliation.csv`
- `data/structures/PVRIG_soft_hint_structure_mapping.csv`
- `positives/known_positive_antibodies.fasta`
- `positives/positive_antibody_metadata.csv`
- `positives/known_positive_CDR_table.csv`
- `positives/positive_CDR_similarity_exclusion_table.csv`
- `positives/mechanism_reference_table.csv`
- `scaffolds/source_registry.csv`
- `scaffolds/vhh_scaffold_quality_table.csv`
- `scaffolds/vhh_scaffold_cluster_table.csv`
- `scaffolds/README.md`
- `reports/external_source_evidence.md`
- `reports/phase_i_b_numbering_reconciliation.md`
- `reports/plabdab_nano_access_review.md`
- `reports/team/*.md`

## Known Verification Gaps

- No bulk scaffold source has been imported.
- Future scaffold/candidate batches still need validator runs before scoring.
- OAS/INDI access and use terms still need final confirmation before bulk import.
- PLAbDab-nano controlled import completed with the dataset-use-term caveat recorded on imported rows.
- Interface prioritization is still distance-only; delta SASA, hydrogen bonds, salt bridges, and hydrophobic-contact enrichment remain future work.

## Automated Verification

Command run from workspace root:

```bash
scripts/verify_phase_i_outputs.py
```

Result: PASS. Checks covered:

- Required Phase I files exist.
- Structure interface row counts are `8X6B=22`, `9E6Y=22`, contact pairs are `57/56`, consensus is `23` rows with `21` two-structure-supported columns.
- Regenerating structure artifacts with `scripts/extract_pvrig_interface.py` is byte-identical to checked workspace outputs.
- PVRIG numbering reconciliation has `211` mapped residues (`8X6B=103`, `9E6Y=108`) and regenerates byte-identically with `scripts/reconcile_pvrig_numbering.py`.
- S67/R95/I97 structure mapping has `6` rows and remains marked `soft_hint_only_not_hard_constraint`.
- Positive FASTA has exactly 3 official-page entries: `tab5_vh`, `tab5_vl`, `hr151_vhh`.
- CDR table is populated from ANARCI/IMGT and contains no guessed CDRs.
- COM701 is mechanism-only and absent from positive FASTA.
- Controlled PLAbDab-nano scaffold files exist: raw FASTA/metadata, quality table, clean FASTA, cluster table, and top 200 FASTA/CSV.
- Progress, plan, exploration, external evidence, and team report anchors are present.

## Validator Follow-up Verification

- Cloned official validator into `tools/ab-data-validator` at commit `97df17aa09bc576a861cf0d8242de97af379fd80`.
- Created local micromamba environment `.conda-envs/ab-data-validator` with ANARCI 2021.02.04 and MUSCLE 5.3.
- Generated official-format input workbook `reports/validator/known_positive_submit.xlsx` for HR-151 VHH and Tab5 full IgG.
- Ran official validator successfully; known positives failed as expected due to 100% CDR identity to built-in references `151` and `CPA.7.021`.
- Populated `positives/known_positive_CDR_table.csv` with ANARCI/IMGT CDRs.
- Populated `positives/positive_CDR_similarity_exclusion_table.csv` with 9 high-identity exclusion rows.
- Validator unit tests passed: `69 passed, 2 deselected`.
- Updated `scripts/verify_phase_i_outputs.py` and reran successfully.

## Phase I-b Numbering Follow-up Verification

- Added `scripts/reconcile_pvrig_numbering.py` output-dir support so numbering artifacts can be regenerated in a temporary directory for byte-identical tests.
- Added `tests/test_reconcile_pvrig_numbering.py`.
- Confirmed S67 maps to `8X6B` B:29 and `9E6Y` A:27, outside the current distance interface.
- Confirmed R95 maps to `8X6B` B:57 and `9E6Y` A:55, both at consensus interface alignment column 50.
- Confirmed I97 maps to `8X6B` B:59 and `9E6Y` A:57, with only `8X6B` counted as a current distance-interface contact at alignment column 52.

## Phase I-b PLAbDab-nano Access Follow-up

- Confirmed official page exposes direct downloads for `all_sequences.csv.gz`, `vhh_sequences.csv.gz`, and `vnar_sequences.csv.gz`.
- Confirmed `vhh_sequences.csv.gz` returns HTTP `200` and was last modified on `Wed, 22 Oct 2025 11:33:00 GMT` during the 2026-07-06 check.
- Performed a temporary `/tmp` schema check only: 4457 rows, with 4427 `VHH` and 30 `VHH/sdAb` records.
- This access review was then followed by the controlled importer; scaffold FASTA/CSV outputs now exist.
- Updated `scaffolds/source_registry.csv` to `controlled_import_completed_local_screening_only` for PLAbDab-nano while preserving the raw CSV redistribution caveat.


## Phase I-b PLAbDab-nano Scaffold Gate Verification

- Ran `scripts/import_plabdab_nano_scaffolds.py --limit 2000 --top-n 200`.
- Scanned 4457 PLAbDab-nano VHH source rows and imported 1965 unique VHH/sdAb scaffold records.
- ANARCI/IMGT succeeded for 1965/1965 imported records.
- Gate dropped 374 records and retained 1591 clean scaffolds.
- Drop reasons: `fail_developability=345`, `cdr3_length_outside_designable_range=32`, `fail_framework_health=29`, `incomplete_imgt_regions=8`, `positive_cdr_identity_ge_80pct=1`.
- Diversity clustering retained 1268 greedy clusters at sequence identity threshold 0.90.
- Wrote `scaffolds/top_200_vhh_scaffolds_for_design.fasta` and `scaffolds/top_200_vhh_scaffolds_for_design.csv` with 200 records.
- No docking, RFantibody, AntiFold, or final Top 50 generation was performed.
