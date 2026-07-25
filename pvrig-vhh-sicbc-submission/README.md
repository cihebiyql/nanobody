# PVRIG VHH SICBC submission

Lightweight, audit-oriented competition repository for the PVRIG VHH Top50
portfolio.  It is a **submission package**, not a copy of the active research
workspace: it retains final sequences, compact evidence, reproducible code
paths, tests, and hashes while excluding raw pools, full docking trees, model
weights, Conda environments, caches, logs, keys, and prohibited redistribution
payloads.

## Reviewer entry points

1. Read the one-page [`SUMMARY.md`](SUMMARY.md).
2. Use the official deliverables in [`data/submission/`](data/submission/):
   `final_top50_ranked.fasta`, `final50.official_submit.xlsx`,
   `final_top50_ranked.tsv`, and `candidate_traceability.tsv`.
3. Inspect 10 representative 9E6Y complexes in
   [`evidence/top10_poses/`](evidence/top10_poses/).
4. Verify the frozen package with `python scripts/verify_submission.py` or
   `pytest -q`.

## Directory guide

| Path | Contents |
| --- | --- |
| `code/generation/` | CPU CDR redesign, donor/control exploration, fixed-pose ProteinMPNN, and RFantibody/RFdiffusion integration. |
| `code/multimodal/` | Data preparation, feature extraction, training, evaluation, inference delivery, and late fusion. |
| `code/qc/` | ANARCI/IMGT, official validator integration, similarity, developability, and diversity code. |
| `code/docking/` | 8X6B/9E6Y target prep, HADDOCK packaging, multi-seed aggregation, and blocking geometry. |
| `code/selection/` | Hard gates, evidence aggregation, ranking, Top50 selection, and export. |
| `data/submission/` | Official Top50 FASTA/Excel, evidence master table, audit, and candidate traceability. |
| `data/qc/` | Final-only ANARCI/IMGT, AbNatiV, Sapiens, validator, and static-pose metrics. |
| `data/targets/` | Public 8X6B/9E6Y structures and compact target-interface artifacts. |
| `data/provenance/` | Parental CDR authority, model weight acquisition/version information, and source hashes. |
| `evidence/` | Top10 representative PDB complexes and SHA256 manifests. |
| `requirements/`, `scripts/`, `tests/` | Environment contract, package build/validation utilities, and regression test. |
| `third_party/` | MIT-licensed official validator source, retained with its upstream license. |
| `docs/` | Reproduction, third-party sources, limits, and team contribution statement. |

## Scope and claim boundary

The frozen final manifest reports 50 candidates, zero hard failures, and 50/50
official-validator and similarity-filter passes.  Ranking evidence is
computational: fixed-pose design, sequence/structure surrogate support,
NanoBodyBuilder2, constrained dual-receptor HADDOCK, blocking geometry, and
static review.  It is **not** a claim of measured expression, purity, affinity,
or PVRL2-blocking activity; those require organizer or wet-lab measurements.

See [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) for exact commands and
[`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) for redistribution boundaries.
