# Submission requirement map

| Requested review item | Included artifact(s) |
| --- | --- |
| One-page abstract; official Top50 sequences/FASTA | `SUMMARY.md`; `data/submission/final_top50_ranked.fasta`; `final50.official_submit.xlsx` |
| CPU CDR, donor, exploration, RFantibody/RFdiffusion, ProteinMPNN, fixed-pose/local optimization | `code/generation/` |
| Multimodal preparation, training, evaluation, inference, fusion | `code/multimodal/` |
| ANARCI/IMGT, validator, positive CDR similarity, developability, diversity | `code/qc/`; `third_party/ab-data-validator/`; `data/qc/` |
| 8X6B/9E6Y, HADDOCK, multi-seed, blocking geometry | `data/targets/`; `code/docking/`; `code/selection/` |
| Hard gate, aggregate score, Top50, Excel export | `code/selection/`; `data/submission/final50.official_submit.xlsx` |
| Weights/download/version/SHA256 | `data/provenance/model_weights_manifest.tsv` |
| Final Top50 evidence; Top10 poses | `data/submission/final_top50_ranked.tsv`; `candidate_traceability.tsv`; `evidence/top10_poses/` |
| Environment, commands, tests, reproducibility | `requirements/`; `docs/REPRODUCTION.md`; `scripts/`; `tests/` |
| License, third-party sources, contributions | `LICENSE`; `docs/THIRD_PARTY.md`; `docs/TEAM_CONTRIBUTIONS.md` |

The package intentionally omits raw libraries, full docking trees, all poses,
Conda environments, caches, logs, credentials, historic intermediate versions,
and non-redistributable weights.
