# Worker-1 Structure/Interface Extraction Method Review

## Scope

Task 1 reviewed the Phase I PVRIG/PVRL2 structure-interface extraction method and documented risks for downstream VHH scaffold design. This is a method audit, not a final binder/blocker claim.

## Method Verified

- Input structures are local PDB files: `data/structures/8X6B.pdb` and `data/structures/9E6Y.pdb`.
- Chain mapping matches PDB headers and project notes:
  - `8X6B`: PVRIG chain `B`, Nectin-2 ligand chain `A`.
  - `9E6Y`: PVRIG chain `A`, Nectin-2/CD112 ligand chain `D`.
- `scripts/extract_pvrig_interface.py` extracts PVRIG residues with any non-hydrogen atom within `<=4.5 A` of ligand non-hydrogen atoms.
- The script writes nearest-contact per-residue rows, residue-residue contact-pair rows, and an alignment-column consensus.
- Consensus is built on PVRIG sequence-alignment columns instead of raw PDB residue numbers, which is necessary because the two structures have different PVRIG numbering offsets.
- S67/R95/I97 are kept in `data/structures/PVRIG_soft_epitope_hints.csv` as unmapped soft hints, not hard structure constraints.

## Reproducibility Evidence

Fresh regeneration to `/tmp/pvrig_interface_verify` matched the checked-in artifacts exactly:

| Artifact | Fresh rows/size | Matches repo |
| --- | ---: | --- |
| `PVRIG_interface_residues_8X6B.csv` | 22 rows | yes |
| `PVRIG_interface_residues_9E6Y.csv` | 22 rows | yes |
| `PVRIG_ligand_contact_pairs_8X6B.csv` | 57 rows | yes |
| `PVRIG_ligand_contact_pairs_9E6Y.csv` | 56 rows | yes |
| `PVRIG_consensus_interface_residues.csv` | 23 rows | yes |
| `PVRIG_soft_epitope_hints.csv` | 3 rows | yes |
| `PVRIG_epitope_priority_map.pml` | 385 bytes | yes |

Consensus summary at the default cutoff:

- 23 total aligned interface columns.
- 21 columns supported by both structures and marked `highest` priority.
- 2 columns supported by one structure and marked `high` priority.

Cutoff sensitivity check:

| Cutoff | 8X6B residues/pairs | 9E6Y residues/pairs | Consensus total / both-supported |
| ---: | --- | --- | --- |
| 4.0 A | 21 / 45 | 20 / 47 | 21 / 20 |
| 4.5 A | 22 / 57 | 22 / 56 | 23 / 21 |
| 5.0 A | 24 / 70 | 25 / 67 | 25 / 24 |

## Method Risks

- Contact definition is a baseline heavy-atom distance rule; it does not model water mediation, side-chain dynamics, energetics, glycosylation, biological assemblies, or crystallographic symmetry contacts.
- The parser uses `ATOM` records from the supplied coordinate files and does not inspect mmCIF metadata, `MODEL` records, biological assemblies, or alternate biological interfaces.
- Altloc handling keeps blank and `A` conformers only; this is reasonable for a first pass but should be regression-tested if future structures use important alternate conformers.
- Consensus alignment columns are stable only when the same reference/spec order is used; future scripts should lock `8X6B` as the reference or explicitly name a canonical PVRIG numbering scheme.
- `PVRIG_epitope_priority_map.pml` is currently a comment-only helper. It warns that PyMOL selections use raw residue numbers and should not be treated as executable residue selections.
- Soft epitope hints S67/R95/I97 remain unmapped to canonical PVRIG/construct numbering and must not be used as hard blocking constraints until numbering reconciliation is complete.
- The extraction outputs identify the native PVRIG/PVRL2 interface, not a VHH paratope, docking pose, affinity predictor, or validated blocker design.

## Missing Regression Checks

- Add a golden-output test that regenerates all structure CSV/PML artifacts into a temporary directory and compares them with `data/structures/`.
- Add small synthetic PDB fixtures for inclusive `<=4.5 A` contact boundaries, hydrogen exclusion, insertion codes, altloc filtering, and nearest atom-pair recording.
- Add unit coverage for `needleman_wunsch` and `build_alignment_maps`, especially numbering offsets and insertions relative to the reference.
- Add a chain-mapping check that fails if future structure downloads no longer contain expected `8X6B:B/A` and `9E6Y:A/D` chains.
- Add an assertion that soft epitope hints remain advisory until canonical numbering reconciliation exists.

## Recommendation

Accept the current extraction as a reproducible Phase I baseline for mechanism-guided epitope prioritization, with caution. Use the 21 two-structure consensus columns as the strongest interface evidence, keep the 2 single-structure columns as lower-confidence context, and avoid converting any structural hint into a hard VHH design constraint until numbering and regression tests are added.

## Coordination

Coordination protocol: coordinated - checked handoff boundaries against `PROJECT_PROGRESS.md`, `docs/PHASE_I_PLAN.md`, generated structure artifacts, and the parallel test-probe findings; no shared integration file was edited.

## Subagent Evidence

Subagents spawned: 1, test coverage probe, agent `019f329f-46af-74f1-a967-56214aaa97c7`.
Subagent model requested: `gpt-5.4-mini`.
Findings integrated: no existing tests/config; suggested golden-output, parser, alignment, chain-map, and soft-hint regression checks; confirmed row-count expectations.
Serial searches before spawn: 2.
