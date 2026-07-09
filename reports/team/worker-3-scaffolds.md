# Worker-3 Scaffold Source Strategy: PVRIG-Blocking-Oriented VHH Library

## Scope

This note maps scaffold data sources and first-pass filtering/scoring strategy for Phase I. It treats scaffold sources as natural/background VHH starting material, not as PVRIG-positive binders or final antibody candidates.

Task boundary: only `reports/team/worker-3-scaffolds.md` was edited. `PROJECT_PROGRESS.md` and `docs/*` are leader-owned integration surfaces and were not edited.

## Source Roles

| Source | Phase I role | Use in this project | Availability / license risk |
| --- | --- | --- | --- |
| INDI / INDI2 | Main VHH/nanobody sequence pool if bulk access is available under acceptable terms | Broad natural and literature/patent-derived nanobody background for scaffold diversity and naturalness checks | Medium. INDI is described as integrating public nanobody sequence, structure, and metadata at >11M sequences, but current NaturalAntibody data pages indicate free academic/non-commercial download and commercial contact requirements. Confirm account, bulk-export route, allowed use, and redistribution limits before importing. |
| PLAbDab-nano | Main curated patent/literature nanobody reference pool; useful for avoiding close patented/literature sequences | Curated VHH/VNAR/single-domain antibody sequences with primary-source links; good for novelty exclusion and literature/patent overlap checks | Low-to-medium. OPIG page and publication describe free query/download access, but primary sources include patents and literature; retain source IDs and avoid treating entries as freely reusable designs without legal review. |
| OAS VHH subset | Main repertoire-scale naturalness/background pool after strict VHH filtering | Large repertoire background to estimate natural VHH distributions and diversity; filter to heavy-chain-only/VHH-compatible records before use | Medium. OAS provides bulk download/filtering and >1B antibody sequences, but VHH subset selection must be explicit and metadata-driven; check study-level consent/licensing and species/isotype labels before redistribution or model training. |
| SAbDab / SAbDab-nano | Reference/benchmark structural set, not a bulk scaffold main library | Structural templates, framework sanity checks, CDR length/geometry priors, and possible PVRIG/PVRL2 structural context if target-related entries exist | Low. SAbDab is public and updated weekly; coverage is structure-biased and non-random, so use as benchmark/template evidence rather than natural repertoire distribution. |
| ANDD | Reference/benchmark antibody/nanobody design dataset | Cross-check antigen-pair metadata, binding-data schemas, and benchmark splits; not primary clean scaffold source | Low-to-medium. Zenodo record states CC BY 4.0, but integrated upstream data may carry heterogeneous provenance; cite ANDD and preserve original source fields. |
| PLAbDab target-related entries | Target-specific reference screen only | Search for PVRIG, PVRL2, CD112, Nectin-2, COM701, Tab5, HR-151, and patent-family names to identify exclusions or references | Medium. Use only complete sequences with source/version; otherwise record as mechanism/literature reference. |

## Recommended Import Order

1. Start with PLAbDab-nano as the smallest curated nanobody/literature-patent pool.
2. Add OAS VHH-compatible records for broad naturalness and diversity, but only after metadata filters are written down.
3. Add INDI/INDI2 only after confirming current bulk-download terms and allowed project use.
4. Add SAbDab-nano/SAbDab as structural benchmark annotations, not as a high-volume scaffold source.
5. Add ANDD as an external benchmark/provenance cross-check, not as the first scaffold pool.

## Minimum Record Schema

Every imported scaffold row should keep:

- `source`: INDI, PLAbDab-nano, OAS, SAbDab-nano, ANDD, or other.
- `source_accession`: stable source ID, patent/publication ID, structure ID, or repertoire unit ID.
- `source_url_or_release`: exact URL, release/date, and download timestamp.
- `sequence_aa`: raw amino-acid sequence.
- `species`: camelid/shark/humanized/synthetic/unknown where available.
- `chain_class`: VHH, VNAR, sdAb, VH-like, or unknown.
- `numbering_status`: ANARCI/IMGT pass/fail and scheme version.
- `region_boundaries`: FR1-CDR1-FR2-CDR2-FR3-CDR3-FR4 coordinates.
- `filter_status`: keep/exclude/review.
- `filter_reasons`: semicolon-delimited reason list.
- `known_positive_similarity`: max CDR identity to confirmed positives once those exist.
- `cluster_id`: diversity cluster after deduplication.
- `score_v1_1`: scaffold score using the Phase I formula.

## Filtering Strategy

### Hard Exclusions

- Non-amino-acid characters, stop codons, frameshifts, or severe truncation.
- Sequence length incompatible with VHH/sdAb variable domains after numbering.
- ANARCI/IMGT numbering failure unless manually rescued for a documented reason.
- Missing conserved cysteine pattern or incomplete FR/CDR segmentation.
- Duplicate sequences after normalizing case, gaps, and terminal padding.
- Complete or near-complete match to known patented/literature positives when the source role is scaffold background rather than positive control.

### Review Flags

- Ambiguous VHH/VH/VNAR classification.
- Extreme CDR3 length or unusual charge/hydrophobicity.
- Unpaired provenance, missing source accession, or missing license/terms metadata.
- Species/source labels inconsistent with VHH expectation.
- High similarity to Tab5, HR-151, COM701-derived sequences, or PVRIG/PVRL2 target-related patent entries once confirmed sequences are available.

### Keep Criteria

- Numbering succeeds and all FR/CDR regions are complete.
- Framework has VHH-compatible hallmarks and no obvious liability cluster.
- CDR3 is designable: long enough for later epitope-directed diversification, but not dominated by extreme hydrophobicity, free cysteine, or abnormal charge.
- Sequence is not redundant with another selected scaffold cluster.
- Source provenance and usage constraints are recorded.

## Scoring Strategy v1.1 Implementation Notes

Use the plan-level formula but make each component auditable:

| Component | Weight | Suggested measurable features |
| --- | ---: | --- |
| Completeness | 0.25 | ANARCI/IMGT success, all FR/CDR regions present, no truncation. |
| Framework Health | 0.20 | Conserved cysteines, VHH hallmark residues, no internal stop/gap, acceptable framework liabilities. |
| Developability | 0.15 | PTM motifs, free cysteine risk, hydrophobic patches, abnormal charge/pI, aggregation heuristics. |
| CDR Designability | 0.15 | CDR3 length/composition, CDR loop completeness, no severe liabilities in CDRs. |
| Naturalness | 0.10 | Distance to OAS/INDI/PLAbDab-nano natural VHH distribution after source filtering. |
| Novelty | 0.10 | Below known-positive CDR identity threshold and not near duplicate of patented/literature target-related sequences. |
| Diversity | 0.05 | Cluster-level down-weighting to avoid one family dominating top scaffolds. |

Do not include docking score in the Phase I primary ranking. The PVRIG/PVRL2 interface map should guide later CDR design constraints, not be used to claim that an unmodified scaffold blocks PVRIG.

## Interface-Aware Design Constraints

The local structure extraction supports an epitope-guided design direction:

- `data/structures/PVRIG_consensus_interface_residues.csv` contains 23 aligned interface columns: 21 highest-priority consensus-supported and 2 high-priority single-structure rows.
- Both `8X6B` and `9E6Y` interface files contain 22 PVRIG interface residues each.
- Consensus charged residues include H/R/R/K/E positions across the aligned interface; later CDR design should preserve electrostatic complementarity without overfitting to one PDB numbering scheme.
- `data/structures/PVRIG_soft_epitope_hints.csv` keeps S67/R95/I97 as soft hints only; do not hard-filter scaffolds against these hints until canonical numbering reconciliation exists.

## Phase I Output Recommendations

Create these scaffold artifacts after source access is confirmed:

- `scaffolds/raw_vhh_scaffold_pool.fasta`: concatenated, source-tagged raw imports.
- `scaffolds/vhh_scaffold_quality_table.csv`: one row per sequence with validation/filtering fields.
- `scaffolds/clean_vhh_scaffold_library.fasta`: deduplicated, validated keep set.
- `scaffolds/vhh_scaffold_cluster_table.csv`: cluster IDs, representatives, source distribution.
- `scaffolds/top_200_vhh_scaffolds_for_design.fasta`: diverse top-scoring representatives only.

## Risks and Mitigations

- License/provenance ambiguity: do not import bulk data without source URL, release date, and use terms; keep commercial-use risk separate from academic research use.
- Source contamination: PLAbDab-nano and INDI include patent/literature sequences, so use them for novelty exclusion and scaffold diversity with caution.
- False VHH labels: require numbering and VHH/sdAb classification before scoring.
- Target leakage: any PVRIG/PVRL2-specific sequence should move to positive/reference tables, not the generic scaffold pool.
- Overclaiming: top scaffolds are starting frameworks for later design, not binders/blockers.

## Verification Evidence

Commands run from `/mnt/d/work/抗体`:

- `omx team api claim-task --input '{"team_name":"phase-i-pvrig-blockin-2a7dab99","worker":"worker-3","task_id":"5","expected_version":1}' --json` -> PASS; task entered `in_progress` with worker-3 claim token.
- `git rev-parse --show-toplevel` -> FAIL expected; this directory is not a git repository, so commit was skipped per task instruction.
- `find . -maxdepth 4 -type f | sort` -> PASS; confirmed project files and empty `reports/team/` before writing this report.
- Python CSV count check -> PASS; consensus/interface row counts summarized above.
- Source availability check -> PASS bounded web/upstream check on 2026-07-05 for INDI/INDI2, PLAbDab-nano, OAS, SAbDab/SAbDab-nano, and ANDD.

No TypeScript/Python package test suite, linter config, or build manifest exists in this workspace, so no full typecheck/lint/test command is applicable for this markdown-only report.

## Source Notes Checked

- INDI NAR paper: integrated nanobody database with >11M nanobody sequences.
- NaturalAntibody INDI2 / antibody data pages: current NaturalAntibody database access and non-commercial/commercial-use caveat.
- OPIG PLAbDab-nano page and NAR/PMC paper: self-updating repository of about 5,000 VHH/VNAR/single-domain sequences from patents and papers; downloadable/queryable.
- OPIG OAS page and documentation: >1B antibody sequences, bulk download/filterable metadata.
- OPIG SAbDab/SAbDab-nano pages: public structural antibody/nanobody structure tracking, updated weekly.
- Zenodo ANDD record and Nature data descriptor: CC BY 4.0 public antibody/nanobody design dataset with binding/antigen-pair metadata.
