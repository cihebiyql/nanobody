# Phase I-b Numbering Reconciliation Report

## Purpose

This report records the first Phase I-b structure-side hardening step: reconciling PVRIG structure residue IDs with alignment columns, UniProt Q6DKI7 positions, and the patent-derived soft epitope hints S67/R95/I97.

This does **not** convert S67/R95/I97 into hard constraints. They remain soft evidence below the 8X6B/9E6Y distance-interface consensus.

## Inputs

- Structures: `data/structures/8X6B.pdb`, `data/structures/9E6Y.pdb`
- Interface baseline: `data/structures/PVRIG_consensus_interface_residues.csv`
- Reconciliation script: `scripts/reconcile_pvrig_numbering.py`
- Numbering assumption: PDB DBREF offset to UniProt accession `Q6DKI7`

## Outputs

- `data/structures/PVRIG_numbering_reconciliation.csv`
- `data/structures/PVRIG_soft_hint_structure_mapping.csv`

## Quantitative Summary

| Artifact | Rows | Interpretation |
| --- | ---: | --- |
| `PVRIG_numbering_reconciliation.csv` | 211 | 103 PVRIG residues from `8X6B` and 108 from `9E6Y` mapped to UniProt Q6DKI7 positions. |
| `PVRIG_soft_hint_structure_mapping.csv` | 6 | S67/R95/I97 each mapped in both structures under the UniProt-position assumption. |

## Soft Hint Mapping

| Hint | 8X6B mapping | 9E6Y mapping | Interface interpretation |
| --- | --- | --- | --- |
| S67 | chain B, PDB residue 29, S | chain A, PDB residue 27, S | Not a current `<=4.5 A` interface residue in either structure. |
| R95 | chain B, PDB residue 57, R | chain A, PDB residue 55, R | Consensus `<=4.5 A` interface residue; alignment column 50. |
| I97 | chain B, PDB residue 59, I | chain A, PDB residue 57, I | Alignment column 52; interface contact only in `8X6B` under the current cutoff. |

## Engineering Conclusions

- The structure-side numbering problem is now controlled enough to support scaffold import gates.
- R95 is the strongest of the three patent hints because it overlaps the consensus distance-interface in both structures.
- I97 is weaker and should be treated as partial support because only `8X6B` places it within the current `<=4.5 A` interface.
- S67 should not drive Phase I scoring because it does not overlap the current distance-interface baseline.
- All three hints remain `soft_hint_only_not_hard_constraint`; candidate/scaffold filtering must not require contact with these residues.

## Remaining Structure Caveats

- The interface remains a distance-only baseline, not an energetic model.
- Later prioritization should add delta SASA, hydrogen bonds, salt bridges, hydrophobic contacts, and charged-contact annotation.
- The mapping assumes UniProt Q6DKI7 positions via PDB DBREF offsets; any patent-specific numbering ambiguity should be revisited if a patent sequence context is later parsed directly.
