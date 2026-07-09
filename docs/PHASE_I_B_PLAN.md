# Phase I-b Plan: Controlled Scaffold Import and Validation

## Status

Phase I-a is accepted as complete for exploration and engineering foundation. Phase I-b is approved to start.

Phase I-b must **not** generate final antibody candidates. Its purpose is to move from a scaffold-import-ready framework to a first validated clean VHH scaffold library.

Current Phase I-b structure-side status:

- `tests/test_extract_pvrig_interface.py` exists and covers golden-output regeneration for the interface extractor.
- `tests/test_reconcile_pvrig_numbering.py` exists and covers golden-output regeneration plus S67/R95/I97 mapping statuses.
- `data/structures/PVRIG_numbering_reconciliation.csv` maps 211 PVRIG structure residues to UniProt Q6DKI7 positions via PDB DBREF offsets.
- `data/structures/PVRIG_soft_hint_structure_mapping.csv` maps S67/R95/I97 in both `8X6B` and `9E6Y`; all remain soft hints, not hard constraints.

## Phase I-a Acceptance Summary

Phase I-a established:

- PVRIG/PVRL2 blocking mechanism and official challenge constraints.
- Structure-derived PVRIG/PVRL2 interface baseline from `8X6B` and `9E6Y`.
- Alignment-column consensus interface map with 23 aligned interface columns, 21 supported by both structures.
- Confirmed sequence-positive references: Tab5 VH/VL and HR-151 VHH.
- ANARCI/IMGT CDR extraction for Tab5 and HR-151.
- Official `ab-data-validator` execution against known positives.
- Correct positive leakage behavior: HR-151 matches built-in `151`; Tab5 matches built-in `CPA.7.021`; all corresponding CDR identities are 100% against an 80% threshold.
- Scaffold data-source strategy and schema, without bulk scaffold import.

## Phase I-b Objective

Controlled scaffold import and validation:

```text
structure numbering reconciliation
+ small-scale curated scaffold import
+ validator gate dry run
+ first clean VHH scaffold library
```

## Non-Goals

- No final Top 50 candidates.
- No AntiFold/RFantibody/de novo generation.
- No PVRIG interface docking as primary ranking.
- No claim that imported scaffolds bind or block PVRIG.
- No large INDI/OAS bulk import before source terms and gates are stable.

## Workstream 1: Structure-Side Hardening

Tasks:

1. Add golden-output regression tests for `scripts/extract_pvrig_interface.py`. **Status: done.**
2. Reconcile PVRIG numbering systems. **Status: done for PDB/alignment/UniProt Q6DKI7 mapping.**
   - PDB residue numbering for `8X6B` and `9E6Y`.
   - Alignment-column consensus numbering.
   - UniProt PVRIG/CD112R numbering where feasible.
   - Patent/sequence hint numbering for S67/R95/I97.
3. Map S67/R95/I97 to structure coordinates if numbering reconciliation supports it. **Status: done under the UniProt Q6DKI7 assumption.**
4. Keep S67/R95/I97 as soft hints unless independently supported by structure/interface evidence. **Status: enforced in artifacts and tests.**

Current soft-hint interpretation:

| Hint | Status |
| --- | --- |
| S67 | Mapped in both structures but not in the current `<=4.5 A` distance interface. |
| R95 | Mapped in both structures and supported by the consensus distance interface. |
| I97 | Mapped in both structures, but only `8X6B` is a current distance-interface contact. |

Potential later structure enrichments:

- Delta SASA / buried surface area.
- Hydrogen bonds.
- Salt bridges.
- Hydrophobic contacts.
- Charged residue annotation.

## Workstream 2: Controlled Scaffold Import

Preferred initial data source:

1. PLAbDab-nano first, because it is curated and traceable. **Status: first controlled local-screening import complete.**
2. OAS VHH-compatible subset second.
3. INDI/INDI2 third, after access/terms confirmation.

Initial scale:

```text
500-2000 VHH/sdAb scaffold records
```

The first import should test the gate pipeline, not maximize quantity.

Current PLAbDab-nano access note:

- Direct `vhh_sequences.csv.gz` route is reachable and schema-readable.
- Controlled import scanned 4457 source rows and imported 1965 unique VHH/sdAb records.
- The page exposes downloads but does not make the downloadable CSV data license explicit enough for unqualified redistribution; importer metadata preserves this caveat.
- Gate output retained 1591 clean scaffolds, formed 1268 clusters, and wrote 200 top design-ready scaffolds.

## Workstream 3: Gate-First Validation

Run gates before scoring:

1. Raw sequence/provenance gate.
2. License/use-term gate.
3. VHH/sdAb classification gate.
4. ANARCI/IMGT numbering gate.
5. Framework health gate.
6. Developability gate.
7. Positive leakage gate with official validator evidence.
8. Diversity/cluster gate.
9. Mechanism-orientation review using the PVRIG/PVRL2 interface map.

## Revised Phase I-b Scaffold Score

The Phase I-b operational score shifts weight from CDR designability to developability and naturalness, because CDRs have not yet been redesigned.

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

Definitions:

- **Completeness:** ANARCI/IMGT numbering succeeds and all FR/CDR regions are present.
- **Framework Health:** conserved cysteines, VHH hallmarks, and FR integrity are acceptable.
- **Developability:** PTM, free cysteine, hydrophobicity, aggregation, abnormal charge, and pI risks are low.
- **Naturalness:** sequence falls inside plausible VHH/sdAb source distributions.
- **CDR Designability:** CDR3 length/composition is suitable for later design but not treated as docking evidence.
- **Novelty:** known-positive and target-related CDR similarity is below exclusion threshold.
- **Diversity:** cluster selection prevents one source/family from dominating.

## Phase I-b Deliverables

Minimum deliverables before candidate design can start:

- `tests/test_extract_pvrig_interface.py` (done)
- `tests/test_reconcile_pvrig_numbering.py` (done)
- `data/structures/PVRIG_numbering_reconciliation.csv` (done)
- `data/structures/PVRIG_soft_hint_structure_mapping.csv` (done)
- `scaffolds/raw_vhh_scaffold_pool.fasta` (done; 1965 records)
- `scaffolds/raw_vhh_scaffold_metadata.csv` (done; 1965 rows)
- `scaffolds/clean_vhh_scaffold_library.fasta` (done; 1591 records)
- `scaffolds/vhh_scaffold_quality_table.csv` with data rows (done; 1965 rows)
- `scaffolds/vhh_scaffold_cluster_table.csv` with data rows (done; 1268 rows)
- `scaffolds/top_200_vhh_scaffolds_for_design.fasta` (done; 200 records)
- `scaffolds/top_200_vhh_scaffolds_for_design.csv` (done; 200 rows)
- validator/import reports for imported scaffold records (done)

## Stop Condition

Phase I-b stops when the first clean, validated, provenance-tracked VHH scaffold library exists and passes validator/naturalness/developability/diversity gates. This condition is met for the first PLAbDab-nano batch. Phase II CDR redesign should still start explicitly, and docking remains downstream of redesign.
