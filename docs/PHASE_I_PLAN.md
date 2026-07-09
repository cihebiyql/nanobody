# Phase I Plan: PVRIG-Blocking-Oriented VHH Scaffold Library

## Scope

Phase I builds the design foundation for PVRIG/PVRL2 blocking VHH design. It does **not** claim to identify final PVRIG binders or blockers.

Formal name:

> Mechanism-guided construction of a PVRIG-blocking-oriented VHH scaffold library

## Phase I Deliverables

### 1. Target mechanism and epitope definition

Artifacts:

- `docs/PHASE_I_EXPLORATION.md`
- `data/structures/8X6B.pdb`
- `data/structures/9E6Y.pdb`
- `data/structures/PVRIG_interface_residues_8X6B.csv`
- `data/structures/PVRIG_interface_residues_9E6Y.csv`
- `data/structures/PVRIG_consensus_interface_residues.csv`
- `data/structures/PVRIG_epitope_priority_map.pml`
- `data/structures/PVRIG_soft_epitope_hints.csv`

Rules:

- Extract PVRIG residues within `<=4.5 A` of PVRL2/Nectin-2 heavy atoms.
- Compute consensus by sequence alignment because PDB residue numbering differs across structures.
- Treat consensus PVRIG/PVRL2 interface residues as the highest-priority blocking epitope evidence.
- Treat CC' loop and F-strand/charged interface regions as high-priority structural annotations after mapping.
- Treat S67/R95/I97 as soft epitope hints pending canonical numbering reconciliation.

### 2. Positive/reference antibody table

Artifacts to create:

- `positives/known_positive_antibodies.fasta`
- `positives/known_positive_CDR_table.csv`
- `positives/positive_antibody_metadata.csv`
- `positives/positive_CDR_similarity_exclusion_table.csv`
- `positives/mechanism_reference_table.csv`

Rules:

- Sequence positives may include Tab5, HR-151, and patent antibodies only when complete sequences are confirmed and source/version is recorded.
- COM701 starts in `mechanism_reference_table.csv`; move it to sequence-positive files only if complete and source-confirmed VH/VL sequences are obtained.
- Known positive CDRs are used for positive controls and similarity exclusion, not supervised model training.

### 3. Clean VHH scaffold library

Artifacts to create:

- `scaffolds/raw_vhh_scaffold_pool.fasta`
- `scaffolds/clean_vhh_scaffold_library.fasta`
- `scaffolds/vhh_scaffold_quality_table.csv`
- `scaffolds/vhh_scaffold_cluster_table.csv`
- `scaffolds/top_200_vhh_scaffolds_for_design.fasta`

Main scaffold sources:

- INDI
- PLAbDab-nano
- OAS VHH subset

Reference/benchmark sources:

- SAbDab / SAbDab-nano
- ANDD
- PLAbDab target-related entries

Rules:

- These sources are scaffold/naturalness/background sources unless a record is explicitly PVRIG-specific.
- Scaffold rows must keep source, accession, sequence, numbering status, and filtering reasons.
- Top scaffolds are design-ready starting materials, not final candidates.

### 4. Validator-first gates

Every generated or imported antibody/VHH sequence should pass the earliest possible version of these gates:

- ANARCI / IMGT numbering succeeds.
- FR1-FR4 and CDR1-CDR3 are complete for VHH.
- Official or replicated `ab-data-validator` rules are run when available.
- CDR identity to known positive references is below the challenge threshold.
- Intra-set diversity is checked before selecting top scaffolds.

### 5. Scoring v1.1

```text
VHH Scaffold Score =
0.25 x Completeness
+ 0.20 x Framework Health
+ 0.15 x Developability
+ 0.15 x CDR Designability
+ 0.10 x Naturalness
+ 0.10 x Novelty
+ 0.05 x Diversity
```

Definitions:

- **Completeness:** numbering succeeds and all FR/CDR regions are present.
- **Framework Health:** VHH hallmark residues, conserved cysteines, and FR integrity are acceptable.
- **Developability:** PTM, aggregation, hydrophobicity, abnormal charge, pI, and free cysteine risks are low.
- **CDR Designability:** CDR3 length/composition supports later design; no Phase I claim of precise epitope docking.
- **Naturalness:** sequence lies near natural VHH distribution from scaffold/background sources.
- **Novelty:** known-positive CDR similarity is below exclusion threshold.
- **Diversity:** final scaffold set is not dominated by one cluster/family.

## Out of Scope for Phase I

- Final Top 50 submission sequences.
- Large-scale de novo generation.
- Retraining a PVRIG-positive supervised model.
- Treating docking score as the main Phase I ranking signal.
- Treating INDI/OAS/PLAbDab-nano as PVRIG-positive libraries.
