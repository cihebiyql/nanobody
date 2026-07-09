# Worker 2 Report: VHH Scaffold Sources, Positive Leakage, and Validator Strategy

## Scope

Task 3 asks for `reports/team/worker-2-positives-validator.md` while describing a VHH scaffold data-source and filtering/scoring strategy. This report therefore focuses on the validator and positive-leakage controls that make scaffold sources safe for Phase I use. It complements, but does not edit, `reports/team/worker-3-scaffolds.md`.

Phase I output remains a design-ready VHH scaffold library, not final PVRIG binders and not a PVRIG-positive supervised training set.

## Local Evidence Reviewed

- `docs/PHASE_I_PLAN.md` lists scaffold outputs: raw scaffold pool FASTA, clean library FASTA, quality table, cluster table, and top-200 design FASTA.
- `docs/PHASE_I_PLAN.md` names main scaffold sources: INDI, PLAbDab-nano, and OAS VHH subset.
- `docs/PHASE_I_PLAN.md` names benchmark/reference sources: SAbDab/SAbDab-nano, ANDD, and PLAbDab target-related entries.
- `docs/PHASE_I_PLAN.md` requires validator-first gates: ANARCI/IMGT, complete VHH FR/CDR regions, official or replicated `ab-data-validator`, CDR identity below challenge threshold, and intra-set diversity.
- `PROJECT_PROGRESS.md` says scaffold source mapping and validator integration are not started yet and need availability/download/license and validator-location checks.
- `.omx/context/pvrig-phase-i-20260705T141047Z.md` records the current working threshold as CDR identity `<80%`, but this is a context constraint pending official validator confirmation.
- `reports/team/worker-3-scaffolds.md` already maps scaffold-source roles and risks; this report keeps the write boundary to worker-2's assigned file.

## Source Role Separation

| Source | Use in Phase I | Validator / leakage control | Do not use as |
| --- | --- | --- | --- |
| INDI / INDI2 | Broad nanobody/VHH background after access and terms are confirmed | Require source accession, release/date, license/use-term field, numbering pass, deduplication, and target-leakage screen | Do not treat as PVRIG-positive library. |
| PLAbDab-nano | Curated patent/literature single-domain antibody pool; useful for scaffold diversity and novelty exclusion | Preserve patent/publication provenance; flag target-related records; use near-duplicate checks against positives and patent families | Do not import target-related entries into generic scaffold pool without leakage label. |
| OAS VHH subset | Repertoire-scale naturalness and diversity background | Metadata-driven VHH subset selection, study/source terms, numbering success, species/isotype sanity checks | Do not assume every OAS heavy-chain sequence is VHH/scaffold-ready. |
| SAbDab / SAbDab-nano | Structural benchmark/template and geometry sanity check | Keep structure IDs and resolution/chain metadata; use for reference priors, not naturalness distribution | Do not use as main high-volume scaffold source. |
| ANDD | Benchmark/schema/reference cross-check | Preserve dataset license, original source, antigen-pair metadata, and split labels | Do not mix benchmark examples into training/evaluation without provenance boundaries. |
| PLAbDab target-related entries | PVRIG/PVRL2/COM701/Tab5/HR-151 search and exclusion/reference screen | Move complete target-specific sequences to positive/reference review, not scaffold background; incomplete records remain metadata only | Do not treat as clean generic scaffold background. |

Recommended import order is curated-first, then broad background, then higher-risk bulk and benchmark sources: `PLAbDab-nano` -> `OAS VHH subset` -> `INDI/INDI2` -> `SAbDab/SAbDab-nano` -> `ANDD`.

## Validator Gate Order

Run gates in this order so cheap failures are removed before expensive scoring.

1. **Raw record gate:** sequence exists, amino-acid alphabet is valid, source accession and source release/date are present.
2. **Provenance/use gate:** source license/use category is recorded; records with unclear terms are held out of redistributable artifacts.
3. **VHH classification gate:** record is VHH/sdAb-compatible by metadata and numbering; VNAR/VH-like/unknown records are separated unless explicitly allowed.
4. **ANARCI/IMGT gate:** numbering succeeds and FR1, CDR1, FR2, CDR2, FR3, CDR3, and FR4 boundaries are complete.
5. **Framework health gate:** conserved cysteines and VHH hallmark residues are acceptable; severe truncation, stop/gap, and abnormal framework liabilities are excluded.
6. **Developability gate:** PTM motifs, free cysteines, hydrophobicity, abnormal charge, pI, and aggregation heuristics are recorded before scoring.
7. **Positive-leakage gate:** CDR identity and near-duplicate checks are run against confirmed sequence positives and target-related patent/literature entries.
8. **Diversity gate:** cluster scaffolds and cap near-identical representatives before selecting top scaffolds.
9. **Mechanism review gate:** use PVRIG/PVRL2 interface evidence for later design orientation only; do not claim unmodified scaffolds bind/block PVRIG.

## Recommended Scaffold Quality Table Schema

`scaffolds/vhh_scaffold_quality_table.csv` should keep each decision auditable:

```csv
record_id,source,source_accession,source_release,source_url_or_path,license_or_use_terms,sequence_aa,sequence_len,species,chain_class,raw_import_status,numbering_tool,numbering_scheme,numbering_status,fr1_range,cdr1_range,fr2_range,cdr2_range,fr3_range,cdr3_range,fr4_range,framework_health_status,developability_status,known_positive_max_cdr_identity,target_related_similarity_status,cluster_id,score_completeness,score_framework_health,score_developability,score_cdr_designability,score_naturalness,score_novelty,score_diversity,score_v1_1,filter_status,filter_reasons,notes
```

`scaffolds/vhh_scaffold_cluster_table.csv` should keep:

```csv
cluster_id,representative_record_id,member_count,sources_present,max_pairwise_identity,mean_score_v1_1,selected_for_top_200,selection_reason,diversity_notes
```

## Scoring v1.1 Operationalization

Use the plan-level weights without adding docking as a primary Phase I score.

| Component | Weight | Practical measurement |
| --- | ---: | --- |
| Completeness | 0.25 | Numbering succeeds; all FR/CDR regions present; no truncation or invalid symbols. |
| Framework Health | 0.20 | Conserved cysteines, VHH hallmarks, framework integrity, no severe liability clusters. |
| Developability | 0.15 | PTM, aggregation, hydrophobicity, charge/pI, free-cysteine and motif risks. |
| CDR Designability | 0.15 | CDR3 length/composition supports later design; CDRs are not dominated by extreme liabilities. |
| Naturalness | 0.10 | Similarity/distribution support from validated OAS/INDI/PLAbDab-nano background. |
| Novelty | 0.10 | Below confirmed-positive CDR identity threshold and not near-duplicate to target-related patent/literature records. |
| Diversity | 0.05 | Cluster caps prevent one family/source from dominating top-200 selection. |

## Positive Leakage and Reference Controls

- Confirmed positives such as Tab5, HR-151, and patent antibodies require complete source/version-confirmed sequences before they can define CDR exclusion references.
- COM701 remains a mechanism/clinical reference unless full source-confirmed VH/VL sequences are available.
- PVRIG/PVRL2 target-related records found in PLAbDab, patents, SAbDab, ANDD, or other sources should be routed to `positives/` review tables, not merged into generic scaffold background.
- The working `<80%` CDR identity threshold is useful as a temporary guardrail from the context snapshot, but the final threshold should come from the official challenge or `ab-data-validator` specification.
- If no confirmed positive sequences exist yet, keep novelty fields nullable and record `not_evaluable_no_confirmed_positive_set` instead of inventing negative evidence.

## Interface-Aware Boundary

The local structure files and interface CSVs support mechanism orientation, but not scaffold-level binding claims:

- Use `data/structures/PVRIG_consensus_interface_residues.csv` as the canonical PVRIG/PVRL2 blocking interface map.
- Use `data/structures/PVRIG_ligand_contact_pairs_8X6B.csv` and `data/structures/PVRIG_ligand_contact_pairs_9E6Y.csv` for residue-pair review when designing CDR diversification later.
- Keep S67/R95/I97 from `data/structures/PVRIG_soft_epitope_hints.csv` as soft hints until canonical numbering reconciliation exists.
- Do not score raw scaffolds by docking to the interface in Phase I; score scaffold readiness and designability instead.

## Implementation Hazards

- **Source-role contamination:** scaffold/background sources can contain target-specific patent or literature sequences; target-related hits need positive/reference routing.
- **License drift:** INDI/OAS/PLAbDab-nano/SAbDab/ANDD have different access and redistribution terms; record use terms per row.
- **False VHH assumptions:** metadata labels are insufficient; VHH/sdAb classification should be backed by numbering and framework checks.
- **Threshold ambiguity:** CDR identity cutoff must be official-validator driven; `<80%` should remain provisional until confirmed.
- **Overclaiming:** top-200 scaffolds are starting frameworks, not binders, blockers, or final candidates.
- **Duplicate family collapse:** selecting by score alone may overrepresent one source/family; cluster-level caps are required.

## Next Feasible Steps

1. Create empty scaffold CSV/FASTA templates with schema headers only.
2. Locate official `ab-data-validator` package and record its exact accepted input/output schema.
3. Confirm source access, release, and use terms for INDI/INDI2, PLAbDab-nano, OAS VHH, SAbDab/SAbDab-nano, and ANDD before importing bulk data.
4. Implement ANARCI/IMGT numbering extraction before any score or top-200 selection.
5. Implement positive-leakage fields as nullable until confirmed positive CDRs are locally available.
6. Use cluster-aware top-200 selection after quality scoring, not before.

## Verification Evidence

- Read `docs/PHASE_I_PLAN.md` scaffold source, validator gate, and scoring sections.
- Read `PROJECT_PROGRESS.md` current scaffold/validator status and Phase I decisions.
- Read `.omx/context/pvrig-phase-i-20260705T141047Z.md` for current constraints and unknowns.
- Read `reports/team/worker-3-scaffolds.md` as read-only peer context; did not edit it.
- Confirmed `scaffolds/` and `positives/` currently have no files in the local checkout.
