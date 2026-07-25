# Environment contract

- Python: 3.10+ (the captured assembly host used Python 3.10.12).
- Core Python packages: `requirements.txt`.
- External executables (not vendored): ANARCI/AbNumber, MUSCLE, NanoBodyBuilder2,
  HADDOCK3, AbNatiV, Sapiens/BioPhi, and the RFantibody/RFdiffusion stack.
- The official validator source is vendored under `third_party/ab-data-validator`
  under its MIT license.  Install it separately with `pip install -e` before
  invoking its CLI.
- GPU is required only for RFantibody/RFdiffusion or model re-training;
  `scripts/verify_submission.py` is CPU-only.
