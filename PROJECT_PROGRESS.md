# PVRIG Blocking VHH Project Progress

This is the continuously maintained progress document for Phase I. Update it whenever Phase I evidence, gates, or artifacts change.

## Current Objective

**Phase I: Mechanism-guided construction of a PVRIG-blocking-oriented VHH scaffold library**

Build a reproducible first-stage foundation for PVRIG/PVRL2 blocking VHH design. Phase I produces design-ready scaffold inputs and evidence maps, not final antibody candidates.

## Success Criteria

- [x] Phase I planning is written and versioned in `docs/PHASE_I_PLAN.md`.
- [x] PVRIG/PVRL2 structure files are collected for `8X6B` and `9E6Y`.
- [x] PVRIG interface residues are extracted per structure using a reproducible script.
- [x] Interface consensus is computed by sequence-alignment columns, not raw residue numbers.
- [x] S67/R95/I97 are documented as soft epitope hints, not hard constraints.
- [x] Positive/reference antibody strategy is documented, separating sequence positives from mechanism references.
- [x] Official-page Tab5/HR-151 sequences are recorded as sequence positives with ANARCI/IMGT CDRs.
- [x] Scaffold data source strategy is documented, separating scaffold pools from benchmarks/references.
- [x] Validator-first gates are documented for ANARCI/IMGT, ab-data-validator, CDR identity, and diversity.
- [x] Leader verification records commands, files, findings, risks, and next steps.
- [x] ANARCI/IMGT has populated known-positive CDRs.
- [x] Official `ab-data-validator` has been installed/run and versioned.
- [x] PLAbDab-nano download route has been checked without creating workspace scaffold FASTA.
- [x] Controlled PLAbDab-nano scaffold import has started after source/use-term caveat and validator gates were ready.
- [x] Phase I-b regression tests cover structure interface extraction.
- [x] PVRIG numbering reconciliation maps PDB/alignment/UniProt/patent-hint coordinates.
- [x] S67/R95/I97 have explicit structure-coordinate mapping under the UniProt Q6DKI7 numbering assumption.
- [x] First controlled PLAbDab-nano scaffold import has passed gate-first validation.

## Phase Gate

- Phase I-a status: accepted complete.
- Phase I-b status: first controlled PLAbDab-nano import complete.
- Current phase goal: controlled scaffold import and validation, not final candidate design.
- Candidate design remains out of scope for this phase; a clean validated scaffold library now exists for later Phase II redesign.

## Current Status

| Area | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Workspace setup | Done | `data/`, `docs/`, `positives/`, `scaffolds/`, `reports/` | Repo-local project scaffold initialized. |
| Structure collection | Done | `data/structures/8X6B.pdb`, `data/structures/9E6Y.pdb` | Downloaded from RCSB. |
| Interface extraction | Done | `scripts/extract_pvrig_interface.py`, `data/structures/PVRIG_*csv` | Heavy-atom contact baseline at `<=4.5 A`; alignment-column consensus. |
| Epitope map | Done | `data/structures/PVRIG_epitope_priority_map.pml` | Executable PyMOL selections for each structure; soft hints remain excluded from hard selections. |
| Numbering reconciliation | Done | `scripts/reconcile_pvrig_numbering.py`, `data/structures/PVRIG_numbering_reconciliation.csv`, `data/structures/PVRIG_soft_hint_structure_mapping.csv` | PDB residue IDs, alignment columns, UniProt Q6DKI7 positions, and S67/R95/I97 hints reconciled. |
| Positive references | Done for official positives | `positives/known_positive_antibodies.fasta`, `positives/positive_antibody_metadata.csv`, `positives/known_positive_CDR_table.csv` | Tab5 VH/VL and HR-151 VHH recorded from official page; CDRs populated by ANARCI/IMGT. |
| Mechanism references | Started | `positives/mechanism_reference_table.csv` | COM701 mechanism reference only; no confirmed sequence in positive FASTA. |
| Hotspot constraints | Done | `data/structures/PVRIG_hotspot_set_v1.csv` | 21 core, 2 secondary, 3 soft hints; no hard contact constraint on soft hints. |
| Scaffold source mapping | Done for PLAbDab-nano | `scaffolds/source_registry.csv`, `reports/plabdab_nano_access_review.md`, `reports/plabdab_nano_license_decision.md` | PLAbDab-nano used for local screening with raw-data redistribution caveat. |
| Scaffold import/gate | Done for first PLAbDab-nano batch | `scaffolds/raw_vhh_scaffold_pool.fasta`, `scaffolds/raw_vhh_scaffold_metadata.csv`, `scaffolds/vhh_scaffold_quality_table.csv`, `reports/plabdab_nano_scaffold_gate_summary.md` | 1965 unique records imported; 1591 clean scaffolds retained. |
| Scaffold clustering/top set | Done for first PLAbDab-nano batch | `scaffolds/vhh_scaffold_cluster_table.csv`, `scaffolds/top_200_vhh_scaffolds_for_design.fasta`, `scaffolds/top_200_vhh_scaffolds_for_design.csv` | 1268 retained clusters; 200 top design-ready scaffolds selected. |
| Validator integration | Done for known positives | `tools/ab-data-validator`, `reports/validator/KNOWN_POSITIVE_VALIDATION.md` | Official validator cloned at commit `97df17aa09bc576a861cf0d8242de97af379fd80`; known positives trigger expected high-identity failures. |
| Team exploration | Done | `reports/team/*.md`, `reports/leader_verification.md` | Team completed and shut down cleanly. |

## Current Quantitative Evidence

- `8X6B` PVRIG chain: `B`; ligand chain: `A`.
- `9E6Y` PVRIG chain: `A`; ligand chain: `D`.
- Interface cutoff: any PVRIG heavy atom within `<=4.5 A` of ligand heavy atom.
- `8X6B`: 22 PVRIG interface residues; 57 residue-residue contact pairs.
- `9E6Y`: 22 PVRIG interface residues; 56 residue-residue contact pairs.
- Consensus map: 23 aligned interface columns; 21 supported by both structures; 2 single-structure.
- PVRIG numbering reconciliation: 211 mapped structure residues (`8X6B=103`, `9E6Y=108`) to UniProt Q6DKI7 positions via PDB DBREF offsets.
- S67/R95/I97 structure mappings: 6 rows total. S67 maps outside the current `<=4.5 A` interface in both structures; R95 maps to consensus interface column 50 in both structures; I97 maps to alignment column 52 and is an `8X6B` single-structure contact only.
- PLAbDab-nano access review: direct `vhh_sequences.csv.gz` route responds `200`; source file has 4457 rows (`4427` VHH, `30` VHH/sdAb). First controlled import has now produced scaffold FASTA/CSV artifacts with the raw-data redistribution caveat preserved.
- PVRIG hotspot set v1: 26 rows total = 21 core hotspots, 2 secondary hotspots, 3 soft hints.
- Controlled PLAbDab-nano import: 4457 source rows scanned, 1965 unique VHH/sdAb records imported.
- ANARCI/IMGT gate: 1965/1965 imported records passed numbering.
- Developability/framework/positive-leakage gates: 374 records dropped; Clean scaffold records retained: 1591.
- Drop reasons: fail_developability 345, CDR3 length outside designable range 32, fail_framework_health 29, incomplete IMGT regions 8, positive CDR identity >=80% 1.
- Diversity gate: 1591 retained scaffolds formed 1268 greedy clusters at 0.90 sequence-identity threshold.
- Top scaffold records written: 200 to `scaffolds/top_200_vhh_scaffolds_for_design.fasta` and `.csv`.
- Positive FASTA entries: 3 (`tab5_vh`, `tab5_vl`, `hr151_vhh`).
- Known-positive CDR rows: 3 with `anarci_success`.
- Official-validator high-identity rows: 9, all 100.0% identity against 80.0% threshold.
- Confirmed scaffold imports: first PLAbDab-nano controlled batch complete.

## Decisions

- Phase I output is a **design-ready VHH scaffold library foundation**, not final PVRIG binders.
- COM701 is a mechanism/clinical reference unless a complete, versioned sequence is confirmed.
- S67/R95/I97 are soft evidence, not hard constraints.
- First-stage CDR scoring uses **CDR designability**, not precise docking geometry.
- SAbDab/SAbDab-nano/ANDD are benchmark/reference sources, not scaffold main libraries.
- Validator gates must be applied before expensive design/docking stages.
- Bulk scaffold FASTA files are allowed only through controlled import scripts after source terms, numbering, and validator gates are ready; this condition is now met for the first PLAbDab-nano batch.
- Raw PLAbDab-nano CSV/GZ is not vendored; imported rows retain `do_not_redistribute_raw_csv`.
- The first top 200 are design-ready scaffolds only, not PVRIG binders/blockers.

## Latest Findings

- Official challenge page was directly fetched on 2026-07-05 and confirms PVRIG/CD112R, PVRL2, `8X6B`, `9E6Y`, IMGT/ANARCI/MUSCLE/Hamming/Identity similarity logic, ab-data-validator URL, and Tab5/HR-151 reference sequences.
- Official `clickmab-bio/ab-data-validator` was cloned at commit `97df17aa09bc576a861cf0d8242de97af379fd80`; ANARCI/MUSCLE environment was created locally with micromamba.
- RCSB and local PDB headers confirm structure titles and chain mapping.
- Raw PDB residue numbers differ between `8X6B` and `9E6Y`; alignment-column consensus prevents false disagreement.
- Numbering reconciliation now maps structure residues to UniProt Q6DKI7 positions and confirms S67/R95/I97 are still soft hints: R95 has strongest interface support, I97 partial support, and S67 is not a current distance-interface residue.
- PLAbDab-nano, OAS, INDI2, ANARCI, and ANDD web pages were fetched and summarized in `reports/external_source_evidence.md`.
- PLAbDab-nano download route is confirmed, but the page does not state a sufficiently explicit dataset-use license; `reports/plabdab_nano_license_decision.md` limits use to local screening and source disclosure without raw CSV/GZ redistribution.
- First controlled PLAbDab-nano gate produced `clean_vhh_scaffold_library.fasta` with 1591 records and `top_200_vhh_scaffolds_for_design.fasta` with 200 records.

## Verification Log

Latest leader verification command:

```bash
scripts/verify_phase_i_outputs.py
```

Result: PASS. The script verified structure row counts, byte-identical regeneration, numbering reconciliation, hotspot set v1, S67/R95/I97 soft-hint mapping, positive/reference separation, ANARCI/IMGT CDR extraction, official-validator similarity evidence, PLAbDab-nano license/access-review state, controlled scaffold import counts, clean library, cluster table, top 200 outputs, and docs/report anchors.

## Next Actions

1. Review `scaffolds/top_200_vhh_scaffolds_for_design.csv` for any project-specific exclusions before Phase II.
2. Confirm source access and terms for OAS/INDI before importing those larger scaffold sources, if more scaffold diversity is needed.
3. Keep `scripts/run_known_positive_validator.py` as the reusable template for future candidate validator runs.
4. Add later structure enrichment (`delta SASA`, hydrogen bonds, salt bridges, hydrophobic contacts) before Phase II docking/redesign.
5. Only after explicit Phase II start: CDR redesign against `PVRIG_hotspot_set_v1.csv`; still no claim that current scaffolds bind PVRIG.
