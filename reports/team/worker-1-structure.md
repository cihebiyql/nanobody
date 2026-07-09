# Worker 2 Report: Positive/Reference Antibody and Validator Strategy

## Scope

This note maps the Phase I positive/reference antibody strategy and the validator-first strategy for the PVRIG-blocking VHH scaffold library. It intentionally does not claim any final binder, blocker, or trained positive model.

## Local Evidence Reviewed

- `PROJECT_PROGRESS.md` records that positive references and validator integration are not started yet.
- `docs/PHASE_I_PLAN.md` defines the intended positive/reference artifacts and validator gates.
- `data/structures/8X6B.pdb` and `data/structures/9E6Y.pdb` are the current mechanism structures.
- `data/structures/PVRIG_consensus_interface_residues.csv` contains 23 aligned interface columns: 21 consensus-supported by both structures and 2 single-structure high-priority residues.
- `data/structures/PVRIG_interface_residues_8X6B.csv` and `data/structures/PVRIG_interface_residues_9E6Y.csv` each contain 22 PVRIG interface residues plus a header row.
- `data/structures/PVRIG_ligand_contact_pairs_8X6B.csv` and `data/structures/PVRIG_ligand_contact_pairs_9E6Y.csv` provide residue-residue contact-pair evidence for epitope and mechanism checks.
- `data/structures/PVRIG_epitope_priority_map.pml` is useful for PyMOL review, but the CSV consensus remains the canonical comparison source.
- `data/structures/PVRIG_soft_epitope_hints.csv` records S67, R95, and I97 as soft hints only, not hard Phase I constraints.

## Positive and Reference Antibody Classes

Use three separate classes so downstream scoring does not confuse mechanism references with confirmed sequence positives.

| Class | Examples / candidates | Required local artifact | Allowed Phase I use | Exclusion |
| --- | --- | --- | --- | --- |
| Confirmed sequence positive | Tab5, HR-151, patent antibodies only after full sequence confirmation | `positives/known_positive_antibodies.fasta`, `positives/known_positive_CDR_table.csv`, `positives/positive_antibody_metadata.csv` | Positive controls, CDR similarity exclusion, benchmark sanity checks | Do not use as supervised training labels in Phase I. |
| Mechanism / clinical reference | COM701 unless a complete versioned sequence is obtained | `positives/mechanism_reference_table.csv` | Mechanism rationale, target biology, clinical/program context | Do not include in sequence-positive FASTA without confirmed VH/VL or VHH sequence provenance. |
| Soft epitope / residue hint | S67, R95, I97 from current planning notes | `data/structures/PVRIG_soft_epitope_hints.csv` plus later numbering reconciliation | Low-weight review hints and manual audit prompts | Do not treat as hard contact, docking, or scoring constraints before canonical numbering reconciliation. |

## Positive Artifact Acceptance Rules

A row should enter the confirmed-positive sequence set only when all fields are available and source-confirmed:

1. Antibody name or clone ID.
2. Complete heavy-chain variable sequence and, for conventional antibodies, light-chain variable sequence when relevant.
3. Source document, accession, patent, or challenge-package identifier with version/date.
4. Target specificity statement showing PVRIG/CD112R relevance.
5. Sequence type: VHH, VH/VL antibody, scFv, or other format.
6. Numbering status from ANARCI/IMGT or an explicitly documented failure.
7. CDR1/CDR2/CDR3 strings under the chosen numbering scheme.
8. Usage label: `sequence_positive`, `mechanism_reference`, or `excluded_unconfirmed`.

Rows lacking complete sequences should remain in metadata or mechanism-reference tables, not in positive FASTA or positive CDR tables.

## Validator-First Strategy

Validator gates should run before expensive scaffold selection, design, docking, or diversity optimization.

| Gate | Purpose | PASS condition | FAIL / HOLD handling |
| --- | --- | --- | --- |
| Sequence format | Prevent malformed inputs | Amino-acid sequence only; no stop, gap, nucleotide, or ambiguous-heavy records unless explicitly allowed | Exclude or quarantine with reason. |
| ANARCI / IMGT numbering | Ensure antibody/VHH interpretability | Numbering succeeds and FR1-FR4/CDR1-CDR3 are recoverable | Hold for manual review or exclude if regions are incomplete. |
| VHH completeness | Keep scaffold-ready VHHs | Single-domain VHH-like record with complete framework and CDR boundaries | Do not score as design-ready scaffold. |
| ab-data-validator | Match official challenge rules when available | Official validator passes; if unavailable, local replicated checks are clearly marked provisional | Keep both official and provisional status fields. |
| Known-positive CDR similarity | Prevent copying positives | CDR identity to confirmed positives stays below the challenge threshold once known positives exist | Exclude or flag as too close to known positive reference. |
| Intra-set diversity | Avoid redundant scaffold picks | Cluster selection does not overrepresent one family/source | Down-rank or cap cluster members. |
| Mechanism compatibility | Preserve PVRIG/PVRL2 blocking orientation | Candidate design review can target consensus interface residues without relying on unreconciled hints | Treat precise docking/epitope claims as out-of-scope for Phase I. |

## Interface Evidence for Mechanism Checks

The current hard mechanism evidence is the extracted PVRIG/PVRL2 interface, not antibody-binding data. Any future positive/reference table should connect back to these files as evidence for blocking-oriented review:

- Highest-priority consensus interface columns: 26, 27, 29, 36, 37, 38, 45, 47, 50, 51, 53, 55, 86, 88, 89, 90, 91, 92, 93, 94, and 95.
- High-priority single-structure columns: 42 and 52.
- Structure chain mapping: `8X6B` uses PVRIG chain `B` and ligand chain `A`; `9E6Y` uses PVRIG chain `A` and ligand chain `D`.
- Consensus should continue to use alignment columns because raw PDB residue numbers differ between structures.

## Recommended Positive Table Schema

`positives/positive_antibody_metadata.csv` should use at least:

```csv
record_id,name,class,target,format,heavy_variable_sequence,light_variable_sequence,source_id,source_version,source_url_or_path,sequence_status,numbering_scheme,numbering_status,cdr_source,allowed_use,exclusion_reason,notes
```

`positives/known_positive_CDR_table.csv` should use at least:

```csv
record_id,name,chain,numbering_scheme,cdr1,cdr2,cdr3,cdr1_len,cdr2_len,cdr3_len,source_id,sequence_status
```

`positives/mechanism_reference_table.csv` should use at least:

```csv
record_id,name,reference_type,target,mechanism_claim,sequence_available,sequence_status,source_id,source_version,allowed_use,notes
```

## Integration Risks

- Tab5 and HR-151 are named in the plan, but no local sequence source is present yet; adding them as positives now would overclaim.
- COM701 should remain a mechanism reference until a complete, source-confirmed sequence is available locally.
- ab-data-validator is not present in this repo yet; any local wrapper must distinguish official validator output from provisional replicated checks.
- S67/R95/I97 are not mapped to current structure numbering and should not be used as hard filters.
- `PVRIG_epitope_priority_map.pml` is a visualization aid, not the canonical source of truth for cross-structure residue mapping.
- Positive CDR similarity thresholds depend on the challenge or validator specification; until located, the report should define the gate but not invent a numeric threshold.

## Next Feasible Implementation Steps

1. Create empty positive/reference CSV and FASTA templates with the schemas above.
2. Locate official Tab5, HR-151, patent, and COM701 source/version evidence before populating sequence-positive rows.
3. Add a validator wrapper that runs ANARCI/IMGT first, then official `ab-data-validator` when available, then local provisional checks.
4. Wire CDR similarity exclusion only after at least one confirmed sequence-positive row exists.
5. Keep mechanism checks tied to `data/structures/PVRIG_consensus_interface_residues.csv` and treat precise antibody docking as out of Phase I scope.

## Verification Evidence

- Read `docs/PHASE_I_PLAN.md` positive/reference and validator sections.
- Read `PROJECT_PROGRESS.md` current status and decisions.
- Counted `data/structures/PVRIG_consensus_interface_residues.csv`: 23 data rows, including 21 `highest` consensus rows and 2 `high` single-structure rows.
- Counted per-structure interface files: 22 data rows each for `8X6B` and `9E6Y`.
- Confirmed `reports/team/` had no existing report file before writing this one.
