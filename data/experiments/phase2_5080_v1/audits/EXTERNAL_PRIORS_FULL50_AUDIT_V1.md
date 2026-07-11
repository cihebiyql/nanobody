# External Priors Full-50 Audit V1

Verdict: PASS

## Scope

- Candidate pool: current V2.2 full2277 top 50.
- Target input: Q6DKI7 structural ectodomain proxy, UniProt positions 39-171, 133 aa.
- Models: NanoBind-seq, NanoBind-site, NanoBind-pro, DeepNano-seq, and DeepNano-site.
- Device: `cuda:0`, NVIDIA GeForce RTX 5080.

## Outputs

- Long-form raw rows: `experiments/phase2_5080_v1/external_priors/external_prior_scores_full50_final_v1.csv`.
- Candidate feature table: `experiments/phase2_5080_v1/external_priors/external_prior_features_full50_v1.csv`.
- Summary JSON: `experiments/phase2_5080_v1/audits/external_prior_summary_full50_v1.json`.
- GPU telemetry: `experiments/phase2_5080_v1/external_priors/external_priors_full50_gpu_telemetry_v1.csv`.
- Target contract: `model_data/pvrig_target_domain_contract_v1.json`.

## Completion Evidence

- Candidates: 50.
- Expected model rows: 250.
- `status=ok`: 250.
- Missing or unavailable rows: 0.
- Site-vector length: 133 for all 100 site-model rows.
- Target-domain mapping: model index 0-132 maps to full-sequence positions 39-171.
- Known PVRIG hotspots represented inside the target domain: 24 unique full-sequence positions.

## Runtime Fixes

- DeepNano expects DataLoader-style string batches; the adapter now sends one-element lists.
- NanoBind and DeepNano both use a top-level package named `models`; the adapter now clears foreign package modules and model-root paths before switching families.
- NanoBind-pro drops its batch dimension at batch size 1; the adapter now duplicates the inference row to batch size 2 and retains item 0. This preserves the input and eval-mode output while avoiding the public-code shape bug.

## GPU Evidence

- Initial full invocation elapsed time: 4:07.89; retry of the three initially failed models: 0:45.83.
- Telemetry samples: 110 at two-second intervals.
- GPU memory used: 5,985-6,646 MiB; peak increase over sampled baseline: 661 MiB.
- GPU utilization: mean 1.65%, maximum 14%.
- Power draw: mean 47.22 W, maximum 56.79 W.

The low utilization is expected for five small ESM2-8M models run one candidate at a time with repeated tokenization and Python/model-loading overhead. It proves CUDA execution but is not a throughput-optimized inference path. V2.3 embedding preparation must use batched unique-sequence inference to use the RTX 5080 more effectively.

## Score Boundary

- NanoBind-seq range: 0.01685-0.41324.
- NanoBind-pro range: 0.00546-0.07041.
- DeepNano-seq range: 0.08470-0.30396.
- These are raw model outputs and are not mutually calibrated probabilities.
- Site summaries retain both whole-domain statistics and hotspot-weighted statistics.
- No external-prior field is a PVRIG blocker probability, Kd, IC50, or experimental efficacy claim.

## Target Boundary

The 39-171 input is a structure-supported model proxy, not a reviewed UniProt topological-domain annotation. Its start follows the official 8X6B Q6DKI7 coverage, and its end is immediately before the UniProt-predicted 172-192 transmembrane segment. Local residue mapping directly observes 41-153, while structure-backed blocker-interface evidence is concentrated at 71-144.

