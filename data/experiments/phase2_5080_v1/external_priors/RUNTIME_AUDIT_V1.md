# External Priors Runtime Audit V1

Date: 2026-07-10 (Asia/Shanghai)
Workspace: `/mnt/d/work/抗体/data`
Allowed edit scope used: `experiments/phase2_5080_v1/external_priors/` and `experiments/phase2_5080_v1/src/setup_external_priors_env_v1.sh` only.

## Boundary

- Adapter under test: `experiments/phase2_5080_v1/src/run_external_priors_v1.py`.
- Adapter source was not edited.
- External-prior outputs remain `external_nanobody_antigen_prior_not_blocker_score`; no blocker score was fabricated.
- The repository FASTA `model_data/pvrig_target_sequence_v0.fasta` is explicitly annotated as the full Q6DKI7 sequence. It was not treated as a final ECD.
- Self-test antigen FASTA created here: `external_priors/pvrig_ecd_candidate_pos39_171_unreviewed_v1.fasta`.
  - Sequence source: local `model_data/pvrig_full_sequence_mask_v0.csv` rows with `uniprot_position` 39-171.
  - Length: 133 aa.
  - Header says `candidate_ECD_positions_39_171_unreviewed_not_final_ECD` to prevent downstream misuse as a reviewed/final ECD.

## Environment Inspection

Command:

```bash
command -v python; command -v python3; command -v conda || true; command -v mamba || true; command -v micromamba || true
find experiments/phase2_5080_v1 -maxdepth 2 \( -name pyvenv.cfg -o -name conda-meta \) -print
conda env list 2>/dev/null || true
```

Findings:

- `python`: `/usr/bin/python`
- `python3`: `/usr/bin/python3`
- `conda`, `mamba`, `micromamba`: not found in PATH during this audit.
- Nearby reusable venv found: `experiments/phase2_5080_v1/.venv-phase2-5080/pyvenv.cfg`.
- The reusable venv already had working `torch==2.13.0+cu130` with CUDA available on `NVIDIA GeForce RTX 5080`.

Initial dependency probe before enablement:

- `experiments/phase2_5080_v1/.venv-phase2-5080/bin/python`: `torch`, `numpy`, `pandas` present; `transformers`, `Bio` missing.
- `/usr/bin/python3` and `/usr/bin/python`: `numpy`, `pandas` present; `torch`, `transformers`, `Bio` missing.

## Local Model Requirements

NanoBind root: `/mnt/d/work/抗体/code/downloaded_models/NanoBind`

- Local requirement file: `NanoBind_env.yml`.
- Relevant pip pins from `NanoBind_env.yml`: `torch==1.13.1`, `biopython==1.78`, `pandas==1.3.5`, `scikit-learn==1.0.2`, `transformers==4.27.4` plus CUDA 11.6 PyTorch wheel index.
- Local ESM2 directory exists: `models/esm2_t6_8M_UR50D`.
- Self-test checkpoint exists: `output/checkpoint/NanoBind_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model`, 38904282 bytes, mtime `2026-07-06 17:08:19.711816400 +0800`.

DeepNano root: `/mnt/d/work/抗体/code/downloaded_models/DeepNano`

- Local requirement file: `requirements.txt`.
- Pins: `transformers==4.27.4`, `biopython==1.78`, `pandas==1.3.5`, `scikit-learn==1.0.2`.
- README recommends `python==3.9` and `torch==1.13.1+cu116`, but the existing Phase 2 venv was reused to avoid creating a second torch stack.
- Local ESM2 directory exists: `models/esm2_t6_8M_UR50D`.
- DeepNano-seq checkpoint exists: `output/checkpoint/DeepNano_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model`, 42541827 bytes, mtime `2026-07-06 17:22:15.750437800 +0800`.

## Runtime Enablement

Created helper: `experiments/phase2_5080_v1/src/setup_external_priors_env_v1.sh`.

The helper reuses the existing Phase 2 venv and installs only the adapter-missing model dependencies:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python -m pip install \
  'transformers==4.27.4' \
  'biopython==1.78'
```

Idempotence check:

```bash
experiments/phase2_5080_v1/src/setup_external_priors_env_v1.sh
```

Result: exit code 0; `transformers==4.27.4` and `biopython==1.78` already satisfied; probe printed `external-priors runtime ready /mnt/d/work/抗体/data/experiments/phase2_5080_v1/.venv-phase2-5080/bin/python`.

Final runtime versions:

```text
python_executable=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/.venv-phase2-5080/bin/python
python_version=3.10.12 (main, Jun 22 2026, 18:55:27) [GCC 11.4.0]
torch=2.13.0+cu130 cuda_available=True cuda_version=13.0
transformers=4.27.4
biopython=1.78
numpy=2.2.6
pandas=2.3.3
gpu=NVIDIA GeForce RTX 5080
```

## Self-test Inference

NanoBind-seq one-candidate model-load and inference command:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python experiments/phase2_5080_v1/src/run_external_priors_v1.py \
  --candidates-csv reports/mvp_pvrig_top_candidates_v0.csv \
  --pvrig-ecd-fasta experiments/phase2_5080_v1/external_priors/pvrig_ecd_candidate_pos39_171_unreviewed_v1.fasta \
  --models nanobind_seq \
  --max-candidates 1 \
  --device cuda:0 \
  --output-csv experiments/phase2_5080_v1/external_priors/selftest_nanobind_seq_one_candidate_v1.csv
```

Result: exit code 0.

Adapter summary:

```json
{
  "output_csv": "experiments/phase2_5080_v1/external_priors/selftest_nanobind_seq_one_candidate_v1.csv",
  "candidate_count": 1,
  "row_count": 1,
  "models": ["nanobind_seq"],
  "status_counts": {"ok": 1},
  "candidate_id_column": "candidate_id",
  "candidate_sequence_column": "vhh_seq",
  "antigen_id": "PVRIG_HUMAN_Q6DKI7",
  "evidence_boundary": "external_nanobody_antigen_prior_not_blocker_score"
}
```

Output row:

```text
candidate_id=zym_test_17428
model_key=nanobind_seq
status=ok
raw_score=0.1106349602
raw_prediction=0
raw_score_name=probability
evidence_boundary=external_nanobody_antigen_prior_not_blocker_score
```

The score above is the raw external NanoBind-seq probability emitted by the loaded local model for this self-test only. It is not calibrated as PVRIG blocker evidence.

Expected model-load warnings observed:

- ESM language-model head weights were not used when initializing `EsmModel`.
- ESM pooler weights were newly initialized.
- NanoBind local code emitted tensor-copy construction warnings.

These warnings did not prevent the self-test inference from returning `status=ok`.

## DeepNano Diagnostic

DeepNano-seq smoke command:

```bash
experiments/phase2_5080_v1/.venv-phase2-5080/bin/python experiments/phase2_5080_v1/src/run_external_priors_v1.py \
  --candidates-csv reports/mvp_pvrig_top_candidates_v0.csv \
  --pvrig-ecd-fasta experiments/phase2_5080_v1/external_priors/pvrig_ecd_candidate_pos39_171_unreviewed_v1.fasta \
  --models deepnano_seq \
  --max-candidates 1 \
  --device cuda:0 \
  --output-csv experiments/phase2_5080_v1/external_priors/selftest_deepnano_seq_one_candidate_v1.csv
```

Result: exit code 0, but the row is explicitly unavailable:

```text
candidate_id=zym_test_17428
model_key=deepnano_seq
status=unavailable
error=prediction failed: ValueError: not enough values to unpack (expected 2, got 1)
```

Likely demonstrated adapter/runtime incompatibility, not fixed in this pass because `run_external_priors_v1.py` was out of edit scope unless explicitly asked after reporting:

- `DeepNano.models.DeepNano_seq.forward()` tokenizes without `return_tensors="pt"` and appears to expect batched sequence input from its original `DataLoader` path.
- The adapter currently passes scalar strings to `model(nb_seq, ag_seq, device)`.
- In contrast, NanoBind-seq uses `return_tensors="pt"` and succeeded through the same adapter call shape.

## Files Created/Updated

- `experiments/phase2_5080_v1/src/setup_external_priors_env_v1.sh` - idempotent helper for the minimal missing dependencies in the reused Phase 2 venv.
- `experiments/phase2_5080_v1/external_priors/pvrig_ecd_candidate_pos39_171_unreviewed_v1.fasta` - local provisional self-test antigen slice, explicitly not final ECD.
- `experiments/phase2_5080_v1/external_priors/selftest_nanobind_seq_one_candidate_v1.csv` - successful one-candidate NanoBind-seq self-test output.
- `experiments/phase2_5080_v1/external_priors/selftest_deepnano_seq_one_candidate_v1.csv` - diagnostic DeepNano-seq unavailable row preserving the observed runtime error.
- `experiments/phase2_5080_v1/external_priors/RUNTIME_AUDIT_V1.md` - this audit.

## Known Gaps / Next Safe Step

- Superseded by `audits/EXTERNAL_PRIORS_FULL50_AUDIT_V1.md`.
- The adapter batching and package-isolation issues were fixed and independently rerun.
- The full 50-candidate, five-model batch now has 250/250 `status=ok` rows.
- The target is intentionally named a 39-171 structural ectodomain proxy, not a reviewed UniProt topological-domain annotation.
