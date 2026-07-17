# Independent replay evidence

This directory contains only lightweight, post-run verifier records. It does
not contain copied `qc_out`, FASTA, numbering JSON, models, or structure data.

- `INDEPENDENT_VERIFIER_AUDIT.json` binds the current 16 chunk commands,
  inputs, portfolio outputs, completion markers, raw-chunk recount, and the
  semantic limits of the census.
- `full_chunk_replay_summary.json` records an isolated replay of original
  `chunk_000001`: 448 candidates completed in 41.049 seconds and reproduced
  the original `portfolio_ranked.tsv` SHA256 exactly.

Verdict scope: `PASS_FROZEN_LARGE_SCALE_FAST_CENSUS_ONLY`. The evidence does
not establish official-validator pass, Full-QC pass, binding, docking geometry,
or experimental blocking.

