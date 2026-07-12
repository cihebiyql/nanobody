# RFantibody on node1

Date: 2026-07-07
Remote host: `node1`
Remote user: `qlyu`
Software root: `/data/qlyu/software/RFantibody`

## Stable SSH

Use Windows OpenSSH from this WSL workspace:

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 '<command>'
```

For long GPU commands, prefer wrapping the remote command in `tmux` or logging with `tee` under `/data/qlyu/software/tests/...`.

## Deployment Decision

The upstream RFantibody `uv sync` path was too slow on node1 because it was downloading/extracting multi-GB CUDA/Torch wheels into `/data/qlyu/software/.uv-cache`. The old background `uv sync` process was stopped after it showed very slow progress and an empty `.venv`.

The working deployment reuses the existing conda environment:

```text
/data/qlyu/anaconda3/envs/rfdiffusion2
```

Validated core stack:

```text
Python 3.11.14
Torch 2.4.0+cu121, CUDA 12.1, torch.cuda.available=True
DGL 2.4.0+cu121
Biotite 1.2.0
```

RFantibody itself runs from source via `PYTHONPATH`; this avoids the repository's `requires-python ==3.10.*` metadata blocker while keeping a minimal, stable install.

## Installed Paths

```text
Source:       /data/qlyu/software/RFantibody
Weights:      /data/qlyu/software/RFantibody/weights
Wrappers:     /data/qlyu/software/RFantibody/bin
Smoke tests:  /data/qlyu/software/tests/rfantibody_smoke
Install log:  /data/qlyu/software/RFantibody/logs/setup_env_node1_rfdiffusion2.log
```

Weights present and md5 checked:

```text
91d54c97a68bf551114f8c74c785e90f  ProteinMPNN_v48_noise_0.2.pt
7c230a10e6e5243aea81c32b8ed40193  RF2_ab.pt
fe04d77408d0cb4f259300b697159d3f  RFab_noframework-nosidechains-5-10-23_trainingparamsadded.pt
5614b1fc623b9cbc7e18190d0c2dc131  RFdiffusion_Ab.pt
```

## How To Run

All commands should start from the RFantibody source directory:

```bash
cd /data/qlyu/software/RFantibody
```

Use the fixed wrappers:

```bash
bin/rfdiffusion --help
bin/proteinmpnn --help
bin/rf2 --help
bin/rfantibody-env -c 'import torch; print(torch.__version__)'
```

The wrappers set:

```bash
RFANTIBODY_ROOT=/data/qlyu/software/RFantibody
RFANTIBODY_WEIGHTS=/data/qlyu/software/RFantibody/weights
RFANTIBODY_SCRIPTS=/data/qlyu/software/RFantibody/scripts
PYTHONPATH=/data/qlyu/software/RFantibody/src:/data/qlyu/software/RFantibody/include/SE3Transformer
PATH=/data/qlyu/anaconda3/envs/rfdiffusion2/bin:/data/qlyu/software/RFantibody/bin:$PATH
```

`bin/rfantibody-env` is the generic Python wrapper for source modules that do
not have a dedicated executable in `bin/`. The current node1 deployment does
not install Quiver console entry points such as `qvscorefile`; invoke them
through the wrapper:

```bash
bin/rfantibody-env -c \
  'import sys; from rfantibody.cli.quiver import qvscorefile; qvscorefile.main(args=[sys.argv[1]])' \
  /path/to/designs.qv
```

This creates `/path/to/designs.sc`; the current `qvscorefile` writes the table
itself instead of streaming TSV rows to standard output.

Prefer an idle GPU, for example GPU 0:

```bash
CUDA_VISIBLE_DEVICES=0 bin/rfdiffusion ...
```

## Smoke Tests Run

### 1. RFdiffusion nanobody backbone design

```bash
cd /data/qlyu/software/RFantibody
TEST=/data/qlyu/software/tests/rfantibody_smoke
CUDA_VISIBLE_DEVICES=0 bin/rfdiffusion \
  --target test/rfdiffusion/inputs_for_test/rsv_site3.pdb \
  --framework test/rfdiffusion/inputs_for_test/h-NbBCII10.pdb \
  --output "$TEST/rfdiffusion_nb/nb_des" \
  --num-designs 1 \
  --design-loops "H1:7,H2:6,H3:5-13" \
  --hotspots "T305,T456" \
  --diffuser-t 15 \
  --final-step 14 \
  --deterministic \
  --no-trajectory
```

Result:

```text
/data/qlyu/software/tests/rfantibody_smoke/rfdiffusion_nb/nb_des_0.pdb
/data/qlyu/software/tests/rfantibody_smoke/rfdiffusion_nb/nb_des_0.trb
```

Note: `diffuser.T` must be at least 15; `T=2` fails with `AssertionError: With discrete time and T < 15`.

### 2. ProteinMPNN sequence design

```bash
cd /data/qlyu/software/RFantibody
TEST=/data/qlyu/software/tests/rfantibody_smoke
CUDA_VISIBLE_DEVICES=0 bin/proteinmpnn \
  --input-dir "$TEST/rfdiffusion_nb" \
  --output-dir "$TEST/proteinmpnn_nb" \
  --loops "H3" \
  --seqs-per-struct 1 \
  --temperature 0.1 \
  --augment-eps 0 \
  --deterministic
```

Result:

```text
/data/qlyu/software/tests/rfantibody_smoke/proteinmpnn_nb/nb_des_0_dldesign_0.pdb
```

### 3. RF2 antibody prediction/filtering with main RF2 weight

```bash
cd /data/qlyu/software/RFantibody
TEST=/data/qlyu/software/tests/rfantibody_smoke
CUDA_VISIBLE_DEVICES=0 PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 TORCH_DETERMINISTIC=1 TORCH_USE_CUDA_DSA=0 bin/rf2 \
  --input-dir test/rf2/inputs_for_test \
  --output-dir "$TEST/rf2_ab" \
  --num-recycles 1 \
  --no-cautious \
  --seed 42 \
  --extra "inference.hotspot_show_proportion=0"
```

Result:

```text
/data/qlyu/software/tests/rfantibody_smoke/rf2_ab/ab_proteinmpnn_output_best.pdb
```

Observed smoke score:

```text
Best pLDDT: 0.896
```

### 4. RF2 JSON path with RFab no-framework weight

```bash
cd /data/qlyu/software/RFantibody
TEST=/data/qlyu/software/tests/rfantibody_smoke
CUDA_VISIBLE_DEVICES=0 PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8 TORCH_DETERMINISTIC=1 TORCH_USE_CUDA_DSA=0 bin/rf2 \
  --input-json test/rf2/inputs_for_test/rfab_targets.json \
  --output-dir "$TEST/rf2_json_rfab" \
  --weights weights/RFab_noframework-nosidechains-5-10-23_trainingparamsadded.pt \
  --num-recycles 1 \
  --no-cautious \
  --seed 42 \
  --hotspot-show-prop 0
```

Result:

```text
/data/qlyu/software/tests/rfantibody_smoke/rf2_json_rfab/T00000_A0201_YLQPRTFLL_0_best.pdb
```

Observed smoke score:

```text
Best pLDDT: 0.930
```

### 5. Quiver score extraction helper

The `bin/rfantibody-env` invocation above was checked with a synthetic Quiver
score line on 2026-07-12. It correctly created a score table:

```text
Wrote 1 scores to /tmp/rfantibody_doc_qv_test.sc
interaction_pae  pred_lddt  tag
4.2              0.91       demo
```

This validates the metadata extraction helper only. A complete GPU
RFdiffusion -> ProteinMPNN -> RF2 run using Quiver I/O has not yet been added
to the node1 smoke suite.

## Current Status

RFantibody is deployed and smoke-tested on node1 using the `rfdiffusion2` conda environment. The three RFantibody components are usable through wrappers:

```text
/data/qlyu/software/RFantibody/bin/rfdiffusion
/data/qlyu/software/RFantibody/bin/proteinmpnn
/data/qlyu/software/RFantibody/bin/rf2
/data/qlyu/software/RFantibody/bin/rfantibody-env
```

For production nanobody design, use higher `--diffuser-t`, more `--num-designs`, and more RF2 recycles than the smoke settings above.
