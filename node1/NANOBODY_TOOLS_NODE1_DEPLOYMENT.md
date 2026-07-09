# Node1 Nanobody Structure/Complex Tool Deployment

Date: 2026-07-07
Remote: `node1` as `qlyu`
Software root: `/data/qlyu/software`
SSH: `ssh.exe -o BatchMode=yes node1 '...'`

## Network / Proxy Notes

- node1 has a local sing-box SOCKS5 listener on `127.0.0.1:10800`.
- GitHub DNS/direct access can fail on node1; for code, prefer uploading cached local source tarballs from this workspace.
- The node1 conda/pip global config currently contains HTTP proxy entries pointing at `127.0.0.1:10800` and `127.0.0.1:7890`; `10800` is SOCKS5, not HTTP. For pip installs that should use direct PyPI access, use:

```bash
PIP_CONFIG_FILE=/dev/null python -m pip install ...
```

## Source Layout Uploaded

Local cached source was uploaded to:

```text
/data/qlyu/software/src/ImmuneBuilder.tar.gz
/data/qlyu/software/src/chai-lab.tar.gz
/data/qlyu/software/src/boltz.tar.gz
/data/qlyu/software/src/haddock3.tar.gz
/data/qlyu/software/src/anarci.tar.gz
/data/qlyu/software/src/anarci_dat.tar.gz
```

Extracted source directories:

```text
/data/qlyu/software/ImmuneBuilder
/data/qlyu/software/chai-lab
/data/qlyu/software/boltz-src
/data/qlyu/software/haddock3
/data/qlyu/software/anarci-src
/data/qlyu/software/anarci-dat
```

Important: do not delete or overwrite `/data/qlyu/software/boltz`; it contains prior Boltz data/output state. The active Boltz source for inference is `/data/qlyu/software/boltz-src`.

## 1. NanoBodyBuilder2 / ImmuneBuilder

Purpose: VHH/nanobody single-chain structure prediction.

Environment reused: `/data/qlyu/anaconda3/envs/boltz`

Why this env: it already has PyTorch `2.6.0+cu124` and CUDA working, avoiding a duplicate multi-GB Torch install.

Installed components:

- `ImmuneBuilder` package manually copied into the env site-packages from `/data/qlyu/software/ImmuneBuilder`.
- CLI wrappers created in `/data/qlyu/anaconda3/envs/boltz/bin`:
  - `NanoBodyBuilder2`
  - `ABodyBuilder2`
  - `TCRBuilder2`
- `ANARCI` installed manually using local source plus prebuilt HMM database from `anarci_dat.tar.gz`.
- Offline conda cache packages installed into the env:
  - `openmm 8.4.0`
  - `pdbfixer 1.9`
  - `hmmer 3.4`
  - `openmpi 4.1.6` for HMMER runtime library.

NanoBodyBuilder2 weights:

```text
/data/qlyu/anaconda3/envs/boltz/lib/python3.11/site-packages/ImmuneBuilder/trained_model/nanobody_model_1  61050011 bytes  md5 4591075f467ca9f76a37a5d1d3cfe591
/data/qlyu/anaconda3/envs/boltz/lib/python3.11/site-packages/ImmuneBuilder/trained_model/nanobody_model_2  214267291 bytes md5 620fc916720bc7068cd18c7afa1aea8d
/data/qlyu/anaconda3/envs/boltz/lib/python3.11/site-packages/ImmuneBuilder/trained_model/nanobody_model_3  214267291 bytes md5 f1ef0a66a54efb9d14ddbb97fdc30785
/data/qlyu/anaconda3/envs/boltz/lib/python3.11/site-packages/ImmuneBuilder/trained_model/nanobody_model_4  214267291 bytes md5 a7e14a33f4c00e96df896120e9cf8522
```

Weight downloader used:

```bash
bash /data/qlyu/software/scripts_download_nanobody_weights_parallel.sh
```

Smoke test output:

```text
/data/qlyu/software/tests/immunebuilder/anarci_smoke_H.csv
/data/qlyu/software/tests/immunebuilder/nanobodybuilder2_smoke.pdb
/data/qlyu/software/tests/immunebuilder/nanobodybuilder2_smoke.log
```

Validated evidence:

- `ANARCI --help` works.
- `NanoBodyBuilder2 --help` works.
- VHH example produced a refined PDB with header:

```text
REMARK  NANOBODY STRUCTURE MODELLED USING NANOBODYBUILDER2
REMARK  STRUCTURE REFINED USING OPENMM 8.4, 2026-07-07
```

Run command:

```bash
BIN=/data/qlyu/anaconda3/envs/boltz/bin
SEQ='QVQLVESGGGLVQPGESLRLSCAASGSIFGIYAVHWFRMAPGKEREFTAGFGSHGSTNYAASVKGRFTMSRDNAKNTTYLQMNSLKPADTAVYYCHALIKNELGFLDYWGPGTQVTVSS'
CUDA_VISIBLE_DEVICES=1 PATH="$BIN:$PATH" NanoBodyBuilder2 \
  -H "$SEQ" \
  -o /data/qlyu/software/tests/immunebuilder/nanobodybuilder2_smoke.pdb \
  --n_threads 4 -v
```

## 2. Boltz-2

Purpose: biomolecular complex prediction; useful for VHH-antigen complex candidate generation. Affinity outputs should not be interpreted as direct VHH-Ag KD.

Environment: `/data/qlyu/anaconda3/envs/boltz`

Active source: `/data/qlyu/software/boltz-src`

Repair performed:

```bash
/data/qlyu/anaconda3/envs/boltz/bin/python -m pip install -e /data/qlyu/software/boltz-src --no-deps --no-build-isolation --no-index
```

Model/data cache already present:

```text
/data/qlyu/.boltz/boltz2_conf.ckpt  ~2.29 GB
/data/qlyu/.boltz/boltz2_aff.ckpt   ~2.06 GB
/data/qlyu/.boltz/mols.tar          ~1.86 GB
/data/qlyu/.boltz/mols/             extracted molecule cache
```

Smoke test output:

```text
/data/qlyu/software/tests/boltz_smoke/out/boltz_results_prot_no_msa/predictions/prot_no_msa/prot_no_msa_model_0.pdb
/data/qlyu/software/tests/boltz_smoke/out/boltz_results_prot_no_msa/predictions/prot_no_msa/confidence_prot_no_msa_model_0.json
```

Validated evidence:

- `boltz --help` works.
- PyTorch CUDA works: `torch 2.6.0+cu124`, CUDA visible, 8 GPUs.
- GPU smoke test ran on `CUDA_VISIBLE_DEVICES=1` and produced PDB/confidence files.

Minimal smoke command:

```bash
BENV=/data/qlyu/anaconda3/envs/boltz
TEST=/data/qlyu/software/tests/boltz_smoke
CUDA_VISIBLE_DEVICES=1 BOLTZ_CACHE=/data/qlyu/.boltz "$BENV/bin/boltz" predict \
  "$TEST/prot_no_msa.yaml" \
  --out_dir "$TEST/out" \
  --cache /data/qlyu/.boltz \
  --recycling_steps 1 \
  --sampling_steps 2 \
  --diffusion_samples 1 \
  --max_parallel_samples 1 \
  --num_workers 0 \
  --preprocessing-threads 1 \
  --output_format pdb \
  --no_kernels \
  --override
```

## 3. Chai-1

Purpose: VHH-antigen co-folding / complex pose generation.

Source: `/data/qlyu/software/chai-lab`

Environment: `/data/qlyu/software/envs/chai1`

The Chai venv was created from the Boltz conda Python with `--system-site-packages` to reuse PyTorch/CUDA:

```bash
/data/qlyu/anaconda3/envs/boltz/bin/python -m venv --system-site-packages /data/qlyu/software/envs/chai1
source /data/qlyu/software/envs/chai1/bin/activate
PIP_CONFIG_FILE=/dev/null python -m pip install -e /data/qlyu/software/chai-lab
```

Important: Chai installed newer packages inside its venv, including `rdkit 2025.09.6` and `gemmi 0.7.5`. These shadow the Boltz conda packages only when the Chai venv is active.

Model cache:

```text
/data/qlyu/software/models/chai1/conformers_v1.apkl
/data/qlyu/software/models/chai1/models_v2/feature_embedding.pt
/data/qlyu/software/models/chai1/models_v2/bond_loss_input_proj.pt
/data/qlyu/software/models/chai1/models_v2/token_embedder.pt
/data/qlyu/software/models/chai1/models_v2/trunk.pt
/data/qlyu/software/models/chai1/models_v2/diffusion_module.pt
/data/qlyu/software/models/chai1/models_v2/confidence_head.pt
```

Smoke test output:

```text
/data/qlyu/software/tests/chai1_smoke/out/pred.model_idx_0.cif
/data/qlyu/software/tests/chai1_smoke/out/scores.model_idx_0.npz
/data/qlyu/software/tests/chai1_smoke/chai1_smoke.log
```

Validated evidence:

- `chai-lab --help` works.
- Import works: `chai_lab 0.6.1`, torch CUDA true.
- Minimal VHH + peptide co-folding smoke test produced a CIF and score file.

Minimal smoke command:

```bash
CHAI_ENV=/data/qlyu/software/envs/chai1
TEST=/data/qlyu/software/tests/chai1_smoke
CUDA_VISIBLE_DEVICES=1 CHAI_DOWNLOADS_DIR=/data/qlyu/software/models/chai1 \
  "$CHAI_ENV/bin/chai-lab" fold \
  "$TEST/vhh_ag_smoke.fasta" \
  "$TEST/out" \
  --no-use-esm-embeddings \
  --num-trunk-recycles 1 \
  --num-diffn-timesteps 2 \
  --num-diffn-samples 1 \
  --num-trunk-samples 1 \
  --device cuda:0
```

For better production-quality Chai predictions, remove the smoke-test reductions and consider enabling MSA/templates:

```bash
chai-lab fold --use-msa-server --use-templates-server input.fasta output_dir
```

## 4. HADDOCK3

Purpose: information-driven docking/refinement when epitope/paratope or other restraints are known.

Environment: `/data/qlyu/anaconda3/envs/haddock3`

Source path imported by env: `/home/qlyu/software/haddock3/src/haddock` (same software area); current uploaded source also exists at `/data/qlyu/software/haddock3`.

Fix performed:

```bash
PIP_CONFIG_FILE=/dev/null /data/qlyu/anaconda3/envs/haddock3/bin/python -m pip install psutil==7.2.2
```

Validated evidence:

- `haddock3 --help` works.
- `haddock3-restraints --help` works.
- Version: `haddock3 - 2025.11.0`.
- Official nanobody-antigen example setup completed with `--setup`.

Smoke setup output:

```text
/data/qlyu/software/haddock3/examples/docking-nanobody-antigen/run1-Para-Epi-test/data/configurations/enhanced_haddock_params.toml
/data/qlyu/software/haddock3/examples/docking-nanobody-antigen/run1-Para-Epi-test/data/00_topoaa/7tgfB-nb_ens.pdb
/data/qlyu/software/haddock3/examples/docking-nanobody-antigen/run1-Para-Epi-test/data/01_rigidbody/7tgfB_real_ambig.tbl
```

Run command:

```bash
cd /data/qlyu/software/haddock3/examples/docking-nanobody-antigen
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 --setup docking-nanobody-antigen-Para-Epi-test.cfg
```

Full HADDOCK runs may require CNS license/runtime compatibility depending on modules; `--setup` verifies Python package, config parsing, data staging, and restraints/tooling path.

## Quick Health Check

Run this from local WSL/current workspace:

```bash
ssh.exe -o BatchMode=yes node1 'set -e
/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2 --help | head -n 5
/data/qlyu/anaconda3/envs/boltz/bin/boltz --help | head -n 8
/data/qlyu/software/envs/chai1/bin/chai-lab --help | head -n 12
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 --help | head -n 12
ls -lh \
  /data/qlyu/software/tests/immunebuilder/nanobodybuilder2_smoke.pdb \
  /data/qlyu/software/tests/chai1_smoke/out/pred.model_idx_0.cif \
  /data/qlyu/software/tests/boltz_smoke/out/boltz_results_prot_no_msa/predictions/prot_no_msa/prot_no_msa_model_0.pdb
'
```

## Caveats / Operational Notes

- Use GPU 0 or 1 for tests when free; both were free after this deployment (`~18 MiB used`) at the final check.
- Chai and Boltz are best used as candidate complex generators. For nanobody campaigns, run multiple seeds/samples and filter with interface confidence, geometry, and downstream docking/refinement.
- HADDOCK3 should be used when you have paratope/epitope/mutagenesis/HDX/competition constraints. It is not a blind deep co-folding model.
- The old RFantibody `uv sync` process from the prior deployment was still running at final health check; it is unrelated to the four tools above.
