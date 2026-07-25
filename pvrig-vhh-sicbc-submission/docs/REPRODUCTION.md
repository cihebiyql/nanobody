# Reproduction and verification

## Fast reviewer verification

```bash
python3 scripts/verify_submission.py
pytest -q
```

The first command validates the exact 50-member final set, final FASTA, Excel
export, traceability schema, Top10 pose count, no prohibited transient payload,
and all package SHA256 values.

## Environment

Use Python 3.10+ and install `requirements/requirements.txt`.  Install the
official validator separately if a full validator replay is required:

```bash
python3 -m pip install -r requirements/requirements.txt
python3 -m pip install -e third_party/ab-data-validator
```

External executables are deliberately not packaged: ANARCI/AbNumber, MUSCLE,
NanoBodyBuilder2, HADDOCK3, AbNatiV, Sapiens/BioPhi, RFantibody/RFdiffusion,
and ProteinMPNN.  Their versions and weight boundaries are in
`requirements/environment.md` and `data/provenance/model_weights_manifest.tsv`.

## Rebuild the compact traceability table

The submission does not duplicate Top7500 campaign pools.  Given the two
immutable upstream score tables used in the original workspace, recreate the
final-only traceability table with:

```bash
python3 scripts/build_traceability.py \
  --old-priority /path/to/old_priority_top7500_candidates.tsv \
  --c2-refined /path/to/TOP7500_C2_REFINED.tsv
python3 scripts/write_sha256s.py
python3 scripts/verify_submission.py
```

The script preserves route semantics: legacy rows carry their original
`S0_R8/S0_R9/S0_Rdual_exact_min`; C2 rows carry their C2 ensemble utility
fields.  All rows additionally record direct static 8X6B/9E6Y HADDOCK scores
and their mean, which are not interchangeable with binding measurements.

## Full compute replay outline

1. Prepare public 8X6B/9E6Y targets with `code/docking/extract_pvrig_interface.py`.
2. Run a desired generator in `code/generation/`; the current final lineage is
   fixed-pose CPU ProteinMPNN under a deterministic seed-42 contract.
3. Run QC in `code/qc/`, then use the MIT official validator package.
4. Create monomers, run constrained multi-seed HADDOCK docking for both
   receptor conformations, and aggregate using `code/docking/` plus
   `code/selection/` scripts.
5. Apply selection scripts in Top200 → Top80 → Top50 order and emit the Excel
   export.  This full path requires the non-redistributed raw inputs and tools.

Do not use this repository to treat proxy scores as experimental affinity or
blocking measurements.
