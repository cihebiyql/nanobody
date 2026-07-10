# Phase 2 External Priors

This directory stores rerunnable external nanobody-antigen prior outputs for PVRIG candidate triage.
The scores are kept as third-party binding or antigen-site priors only; they are not blocker labels and must not be described as blocker scores.

## Adapter

`../src/run_external_priors_v1.py` wraps the local checkouts:

- NanoBind: `/mnt/d/work/抗体/code/downloaded_models/NanoBind`
  - `predict_seq.py` / `NanoBind_seq(...)_good.model`
  - `predict_site.py` / `NanoBind_site(...)_good.model`
  - `predict_pro.py` / `NanoBind_pro(...)_good.model`
- DeepNano: `/mnt/d/work/抗体/code/downloaded_models/DeepNano`
  - `predict.py` documents seq inference but hard-codes input paths, so the adapter imports `models.models` directly.
  - Supported first: DeepNano-seq(NAI) 8M and DeepNano-site 8M checkpoints.

If a Python dependency, model root, or checkpoint is unavailable, the output row is marked `status=unavailable` with an explicit `error`; the adapter does not fabricate scores.

## Example

```bash
python experiments/phase2_5080_v1/src/run_external_priors_v1.py \
  --candidates-csv reports/mvp_pvrig_top_candidates_v0.csv \
  --pvrig-ecd-fasta model_data/pvrig_target_sequence_v0.fasta \
  --models nanobind_seq,deepnano_seq \
  --output-csv experiments/phase2_5080_v1/external_priors/external_prior_scores_v1.csv
```

For smoke tests, add `--max-candidates 2`. Candidate CSVs may include `vhh_seq` directly, or the adapter can resolve `candidate_id` from the default lookup files under `model_data/` and `reports/`.

## Output Contract

The output is long-form CSV with one row per candidate and selected external model. Important columns:

- `status`: `ok` or `unavailable`.
- `raw_score`, `raw_prediction`: original model scalar outputs when a scalar binding-prior model runs.
- `raw_site_scores_json`, `raw_site_positions_json`: original antigen-site scores and thresholded positions for site-prior models.
- `model_family`, `model_name`, `model_version`, `source_script`: model provenance.
- `checkpoint_path`, `checkpoint_status`, `checkpoint_size_bytes`, `checkpoint_mtime`: checkpoint provenance.
- `evidence_boundary`: always `external_nanobody_antigen_prior_not_blocker_score`.
- `error`: explicit reason for unavailable rows.
