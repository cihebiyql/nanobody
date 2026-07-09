# Phase I Exploration Report

## Executive Summary

Phase I has started in the corrected order: define the PVRIG/PVRL2 blocking mechanism, map the receptor-ligand interface, separate confirmed sequence positives from mechanism references, and define scaffold-source/validator gates before importing VHH datasets.

Current state:

- Structure exploration is complete for the first baseline: `8X6B` and `9E6Y` PDB files are local, parsed, and converted into per-structure and alignment-consensus interface maps.
- Positive-reference exploration is materialized for the official positives: the official challenge page was fetched locally, Tab5/HR-151 sequences were recorded, and CDRs were populated using the official validator ANARCI/IMGT wrapper.
- COM701 remains a mechanism reference, not a sequence-positive entry.
- Scaffold exploration is complete at the source-strategy level: source roles, import order, schemas, risk controls, and scoring rules are recorded; no bulk scaffold sequences have been imported yet.
- Validator integration is complete for known-positive controls: the official `ab-data-validator` repository was cloned, ANARCI/MUSCLE were installed via micromamba, and known positives produced expected high-identity failures against built-in references.

## Source Evidence

Local source evidence snapshot: `reports/external_source_evidence.md`.

Confirmed from the official competition page fetched on 2026-07-05:

- The antibody track target is PVRIG/CD112R.
- PVRIG-PVRL2 binding suppresses T-cell and NK-cell function and promotes tumor immune escape.
- Candidate antibodies should bind PVRIG extracellular domain, preferentially target the PVRIG/PVRL2 binding interface, and block PVRIG-PVRL2 interaction.
- Reference structures include `8X6B` and `9E6Y`.
- Accepted submitted formats include IgG VH/VL or VHH amino-acid sequences.
- Numbering should use IMGT; CDR similarity is computed using ANARCI-defined CDRs, MUSCLE alignment, Hamming distance, and Identity.
- The official validator link is `https://github.com/clickmab-bio/ab-data-validator#`.
- The official page provides Tab5 VH/VL and HR-151 VHH positive-reference sequences.

Other fetched evidence:

- RCSB `8X6B`: crystal structure of immune receptor PVRIG in complex with ligand Nectin-2.
- RCSB `9E6Y`: structure of CD112/Nectin-2 domain 1 bound to CD112R/PVRIG.
- PLAbDab-nano: self-updating repository of just under 5000 VHH/VNAR/single-domain antibody sequences from patents and academic papers.
- OAS: over one billion antibody sequences from over 80 studies, cleaned/annotated/translated/numbered and downloadable/filterable.
- ANARCI page: OPIG numbering tool surface.
- INDI2: curated single-domain antibody/Nanobody sequence/structure/metadata resource.

## Structure Exploration

### Inputs

- `data/structures/8X6B.pdb`
- `data/structures/9E6Y.pdb`

Chain mapping from PDB headers and local parsing:

| PDB | PVRIG chain | Ligand chain | Ligand label |
| --- | --- | --- | --- |
| `8X6B` | `B` | `A` | Nectin-2/PVRL2 |
| `9E6Y` | `A` | `D` | CD112/Nectin-2/PVRL2 |

### Method

Script: `scripts/extract_pvrig_interface.py`.

Baseline method:

- Parse local PDB `ATOM` records.
- Ignore hydrogens.
- Keep blank or `A` altlocs.
- Define PVRIG interface residues as residues with any heavy atom within `<=4.5 A` of any ligand heavy atom.
- Write nearest-contact per-residue CSVs and residue-residue contact-pair CSVs.
- Build consensus by aligning PVRIG chain sequences, not by raw PDB residue numbers.

The alignment-based consensus is required because the two structures use different PVRIG residue-number offsets.

### Outputs

| Artifact | Meaning | Current evidence |
| --- | --- | --- |
| `data/structures/PVRIG_interface_residues_8X6B.csv` | Per-residue PVRIG contacts in 8X6B | 22 data rows |
| `data/structures/PVRIG_interface_residues_9E6Y.csv` | Per-residue PVRIG contacts in 9E6Y | 22 data rows |
| `data/structures/PVRIG_ligand_contact_pairs_8X6B.csv` | Residue-residue contact-pair details | 57 data rows |
| `data/structures/PVRIG_ligand_contact_pairs_9E6Y.csv` | Residue-residue contact-pair details | 56 data rows |
| `data/structures/PVRIG_consensus_interface_residues.csv` | Alignment-column consensus map | 23 data rows; 21 supported by both structures |
| `data/structures/PVRIG_epitope_priority_map.pml` | PyMOL helper using raw structure residue IDs | Executable per-structure selections for all/consensus/single-structure residues |
| `data/structures/PVRIG_soft_epitope_hints.csv` | Soft patent-hint tracking | S67/R95/I97 marked advisory and excluded from hard PyMOL selections |
| `data/structures/PVRIG_numbering_reconciliation.csv` | PDB/alignment/UniProt residue reconciliation | 211 mapped PVRIG structure residues |
| `data/structures/PVRIG_soft_hint_structure_mapping.csv` | S67/R95/I97 structure-coordinate mapping | 6 rows; hints remain soft-only |

Strongest current interface evidence:

- Consensus-supported alignment columns: 21.
- Single-structure high-priority alignment columns: 2.
- Charged consensus interface annotations appear in the consensus CSV and should inform later CDR design, not Phase I scaffold scoring.

### Numbering Reconciliation and Soft Hints

Script: `scripts/reconcile_pvrig_numbering.py`.

Current Phase I-b mapping assumes S67/R95/I97 are UniProt Q6DKI7 positions and uses PDB DBREF offsets to map them into each structure:

| Hint | 8X6B mapping | 9E6Y mapping | Current interpretation |
| --- | --- | --- | --- |
| S67 | chain B, PDB residue 29, S | chain A, PDB residue 27, S | Not a current `<=4.5 A` interface residue in either structure. |
| R95 | chain B, PDB residue 57, R | chain A, PDB residue 55, R | Consensus interface residue; alignment column 50. |
| I97 | chain B, PDB residue 59, I | chain A, PDB residue 57, I | Alignment column 52; interface contact only in `8X6B` under the current cutoff. |

Engineering interpretation:

- R95 is the strongest soft hint because it overlaps the two-structure consensus interface.
- I97 is a weaker soft hint because the current distance baseline supports it in only one structure.
- S67 should not drive Phase I scaffold scoring because it does not overlap the current distance-interface baseline.
- All three remain `soft_hint_only_not_hard_constraint`.

### Structure Caveats

- This is a distance-only interface baseline, not an energetic binding model.
- It does not model water, glycosylation, side-chain dynamics, biological assembly, or crystallographic symmetry contacts.
- It does not identify an antibody paratope, docking pose, affinity, or blocker.
- S67/R95/I97 are intentionally not selected in the PyMOL helper even after mapping, because they are soft patent hints rather than hard Phase I constraints.

## Positive and Reference Antibodies

### Materialized Artifacts

- `positives/known_positive_antibodies.fasta`
- `positives/positive_antibody_metadata.csv`
- `positives/known_positive_CDR_table.csv`
- `positives/positive_CDR_similarity_exclusion_table.csv`
- `positives/mechanism_reference_table.csv`

### Current Confirmed Sequence Positives

These entries were extracted from the official challenge page and recorded as sequence positives:

| Record | Type | Status | Use |
| --- | --- | --- | --- |
| `tab5_vh` | IgG VH | confirmed sequence, ANARCI/IMGT success | positive control and similarity exclusion |
| `tab5_vl` | IgG VL | confirmed sequence, ANARCI/IMGT success | positive control and similarity exclusion |
| `hr151_vhh` | VHH | confirmed sequence, ANARCI/IMGT success | positive control and similarity exclusion |

Important: `known_positive_CDR_table.csv` now contains ANARCI/IMGT-derived CDRs. No CDR boundaries were guessed manually.

### Mechanism Reference

COM701 is stored in `positives/mechanism_reference_table.csv` as `clinical_mechanism_reference` only. It is not present in `known_positive_antibodies.fasta` because complete source-confirmed VH/VL sequence was not established in this Phase I exploration.

### Similarity Exclusion

The official page states that CDR similarity is evaluated using ANARCI-defined IMGT CDRs, MUSCLE alignment, Hamming distance, and Identity; the working threshold is `<80%` CDR similarity to positive references. In this workspace:

- The metadata and FASTA are ready.
- ANARCI has been run via the official validator wrapper.
- MUSCLE has been run via the official validator workflow.
- `ab-data-validator` has been cloned at commit `97df17aa09bc576a861cf0d8242de97af379fd80`.
- Similarity exclusion is computed for known-positive controls: HR-151 matches built-in `151` and Tab5 matches built-in `CPA.7.021` at 100% CDR identity.

## Scaffold Source Exploration

### Materialized Artifacts

- `scaffolds/source_registry.csv`
- `scaffolds/raw_vhh_scaffold_pool.fasta`
- `scaffolds/raw_vhh_scaffold_metadata.csv`
- `scaffolds/vhh_scaffold_quality_table.csv`
- `scaffolds/clean_vhh_scaffold_library.fasta`
- `scaffolds/vhh_scaffold_cluster_table.csv`
- `scaffolds/top_200_vhh_scaffolds_for_design.fasta`
- `scaffolds/top_200_vhh_scaffolds_for_design.csv`
- `scaffolds/README.md`
- `reports/plabdab_nano_access_review.md`
- `reports/plabdab_nano_license_decision.md`
- `reports/plabdab_nano_scaffold_gate_summary.md`

A first controlled PLAbDab-nano scaffold import has now completed. The importer preserves the unresolved raw-data redistribution caveat from the access/license review and treats all rows as scaffold starting material, not PVRIG-positive binders.

PLAbDab-nano update: its direct VHH CSV download route is confirmed and schema-readable. The controlled import scanned 4457 source rows, imported 1965 unique VHH/sdAb records, retained 1591 clean scaffolds, clustered them into 1268 greedy sequence clusters, and wrote 200 top design-ready scaffolds.

### Source Roles

| Source | Phase I role | Status |
| --- | --- | --- |
| PLAbDab-nano | first curated scaffold/reference pool | controlled local-screening import complete |
| OAS VHH subset | naturalness/background pool | explored, not imported |
| INDI/INDI2 | large nanobody/VHH pool after access/terms check | explored, not imported |
| SAbDab/SAbDab-nano | structure benchmark/reference | explored, not imported |
| ANDD | benchmark/schema/provenance cross-check | explored, not imported |
| PLAbDab target-related entries | target leakage/reference screen | planned |

### Import Order

Recommended import order:

1. PLAbDab-nano
2. OAS VHH-compatible subset
3. INDI/INDI2 after access/terms confirmation
4. SAbDab/SAbDab-nano as structural benchmark annotations
5. ANDD as benchmark/provenance cross-check

### Validator Gate Order

1. Raw sequence/provenance gate.
2. License/use-term gate.
3. VHH/sdAb classification gate.
4. ANARCI/IMGT numbering gate.
5. Framework health gate.
6. Developability gate.
7. Positive-leakage gate.
8. Diversity/cluster gate.
9. Mechanism-orientation review using the PVRIG/PVRL2 interface map.

## Phase I Scoring

Phase I-b uses the revised scaffold score:

```text
VHH Scaffold Score =
0.25 x Completeness
+ 0.20 x Framework Health
+ 0.20 x Developability
+ 0.15 x Naturalness
+ 0.10 x CDR Designability
+ 0.05 x Novelty
+ 0.05 x Diversity
```

Docking score is explicitly excluded from the primary Phase I ranking. It belongs after CDR design/redesign.

## Team Exploration Evidence

Team run: `phase-i-pvrig-blockin-2a7dab99`.

Lifecycle evidence:

- Team launched with 3 executor workers.
- Worker ACKs were received for worker-1/2/3.
- A task-decomposition issue assigned scaffold work incorrectly; leader created task 5 for worker-3 and later reconciled duplicate task 4.
- Final state before shutdown: 5 completed, 0 pending, 0 in-progress, 0 failed.
- Shutdown completed and team state was removed.

Raw team reports:

- `reports/team/worker-1_structure_interface_method_review.md`
- `reports/team/worker-1-structure.md` (worker-2 positive/reference report; filename was produced by task wording)
- `reports/team/worker-2-positives-validator.md`
- `reports/team/worker-3-scaffolds.md`

Leader integration notes:

- Worker reports are evidence inputs, not final authority.
- The leader verified the core row counts, source files, and final task lifecycle state.
- The canonical integrated account is this document plus `PROJECT_PROGRESS.md`.

## Remaining Gaps Before Full Phase I Library Construction

1. Optionally confirm source access and terms for OAS/INDI before importing those larger scaffold sources.
2. Keep validator gates on any future scaffold/candidate batch before scoring.
3. Keep `scripts/run_known_positive_validator.py` as the template for future candidate validator runs.
4. Add later structure enrichment: delta SASA, hydrogen bonds, salt bridges, hydrophobic contacts, and charged-contact annotation.
5. Only after explicit Phase II start: redesign CDRs against `PVRIG_hotspot_set_v1.csv`; current scaffolds are not PVRIG binders/blockers.

## Phase I-a Acceptance and Phase I-b Start

Assessment: Phase I-a is complete, and the first Phase I-b controlled PLAbDab-nano import/gate is complete. The current outputs define the mechanism, interface baseline, positive-reference exclusion system, validator path, hotspot set, clean scaffold library, and top 200 design-ready scaffolds. They do **not** include final PVRIG-specific candidates.

Key caveats carried into Phase I-b:

- The current interface is a distance-only baseline. Treat it as a blocking-interface seed, not the only possible epitope.
- S67/R95/I97 are now mapped under the UniProt Q6DKI7 assumption, but remain soft hints rather than hard contact constraints.
- PLAbDab-nano scaffold import is complete for the first controlled batch; top 200 design-ready scaffolds exist, but no final PVRIG-specific candidate exists yet.
- Phase I-b should prioritize controlled import and validation over docking, AntiFold, or RFantibody.

Updated operational score for Phase I-b:

```text
VHH Scaffold Score =
0.25 x Completeness
+ 0.20 x Framework Health
+ 0.20 x Developability
+ 0.15 x Naturalness
+ 0.10 x CDR Designability
+ 0.05 x Novelty
+ 0.05 x Diversity
```

Rationale: before CDR redesign, developability and naturalness should weigh more than CDR designability.
