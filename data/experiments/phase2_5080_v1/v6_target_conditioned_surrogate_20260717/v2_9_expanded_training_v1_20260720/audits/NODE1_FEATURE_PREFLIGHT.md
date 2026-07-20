# Node1 V2.9 feature preflight

Audit time: `2026-07-20T16:29+08:00` to `2026-07-20T16:31+08:00`

Scope: read-only inspection of Node1/Node23 resources, frozen model artifacts,
existing feature code/caches, and the V29 candidate/monomer inputs.  No training
code was edited and no production computation was launched by this preflight.

## Verdict

`PASS_SEQUENCE_FEATURE_LANES_READY_WITH_VERSIONED_LAUNCHER`

The sequence feature lanes can start immediately on Node1 GPUs 1--4 after the
new V2.9 input copies and launcher are frozen.  The existing ESM2-650M and
ESM2-3B models, Python environment, and resumable pooling implementation are
present and previously completed the 1,507-row production cache.  V29 inputs
are visible from Node1 and Node23 through the same `/data` NFS path and have
matching hashes.

The 126-dimensional monomer feature *kernel* is reusable, but the existing V4-H
wrapper is hard-coded to the old 1,320-row manifests and hashes.  A new
versioned V29 adapter/receipt is required before the structure-feature lane is
launched.  This does not block the sequence-only Ridge/ElasticNet training
lane.

## Node1 resource evidence

At the audit snapshot:

| Resource | Observation | Decision |
|---|---:|---|
| `/data1` | 7.0 TiB total, 6.4 TiB used, **243 GiB free**, 97% used | Use only compact tables/caches; do not copy the 9,934 PDB tree |
| `/data` | 19 TiB free, NFSv4.2 mounted read/write | Read the frozen V29 source inputs here; copy only manifests into the versioned `/data1` project |
| RAM | 503 GiB total, 470 GiB available | Four embedding processes are safe |
| CPU | 64 logical CPUs, load average about 21 | Embedding lanes are GPU-bound; avoid broad CPU fan-out |
| GPU 0 | 18,189 MiB used by PID 219317 (`build_protein_lmdb.py`) | **Do not use** |
| GPUs 1--4 | 18 MiB used each, 0% utilization | Safe allocation for V2.9 feature lanes |
| GPUs 5--7 | 18 MiB used each, 0% utilization | Leave free for other work/fallback |

The output payload is small.  Raw float16 pooled vectors require approximately:

- V29 9,934 x ESM2-650M: 97 MiB;
- V29 9,934 x ESM2-3B: 194 MiB;
- D0 3,388 x ESM2-650M: 33 MiB;
- D0 3,388 x ESM2-3B: 66 MiB.

Including PyTorch shard metadata, receipts, logs, and model outputs, a 10 GiB
budget is already conservative.  The model weights remain under `/data`, not
`/data1`.

## Frozen model/runtime evidence

Python runtime:

```text
/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
torch 2.6.0+cu124
CUDA available: true
CUDA devices: 8
transformers 4.57.6
scikit-learn 1.6.1
```

Models:

```text
ESM2-650M
/data/qlyu/.cache/huggingface/hub/
models--facebook--esm2_t33_650M_UR50D/snapshots/
08e4846e537177426273712802403f7ba8261b6c
model.safetensors: 2,609,506,392 bytes

ESM2-3B
/data/qlyu/.cache/huggingface/hub/
models--facebook--esm2_t36_3B_UR50D/snapshots/
476b639933c8baad5ad09a60ac1a87f987b656fc
pytorch_model-00001-of-00002.bin: 9,976,735,419 bytes
pytorch_model-00002-of-00002.bin: 1,390,347,055 bytes
```

Existing immutable implementation:

```text
/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/
code_v1_1/src/cache_v6_esm_embeddings.py
SHA256 69d1de369e175bdf1645256f31552cf78247dbb5e793d7f6f010f1f975fb518b
```

The implementation:

- validates candidate and sequence uniqueness;
- validates `sequence_sha256`;
- requires each CDR to occur exactly once in its sequence;
- pools whole sequence plus CDR1/CDR2/CDR3;
- stores float16 resumable shards;
- binds the input hash, model-artifact fingerprint, model config, candidate IDs,
  sequence hashes, and output shard hashes in its receipt.

It emits a warning that the Hugging Face pooler weights are newly initialized,
but the implementation consumes `last_hidden_state` directly and never consumes
the pooler output.  The warning therefore does not change the frozen pooled
features.

## Existing caches and reuse boundary

The only production caches found on Node1 are:

| Cache | Rows | Dimension | Size | Status |
|---|---:|---:|---:|---|
| `full1507_esm2_650m_embeddings_v1` | 1,507 | 5,120 | 15 MiB | PASS |
| `full1507_esm2_3b_embeddings_v1` | 1,507 | 10,240 | 30 MiB | PASS |

They can be retained for the old 1,507-row compatibility analysis, but cannot
be presented as V29 or expanded-3,388 caches.  The cache contract binds an exact
input SHA256 and exact row count, and the current Stage0 loader also hard-codes
the old 1,507-row receipt.  The V2.9 loader must therefore be versioned rather
than patching the old cache or old Stage0 code in place.

For a simple, auditable D0 comparison, recomputing a complete 3,388-row cache is
preferred to manually splicing the old 1,507 rows with 1,881 new rows.  Its disk
and runtime cost is negligible, and it avoids a new cache-union trust surface.

Previous measured Node1 runtimes with the same implementation/hardware:

| Model | Rows | Start | Finish | Wall time |
|---|---:|---|---|---:|
| ESM2-650M | 1,507 | 00:24:34 | 00:24:47 | about 13 s |
| ESM2-3B | 1,507 | 00:42:17 | 00:42:53 | about 36 s |

These timings make full V29 embedding a short job, but the production launcher
must still be resumable and receipt-gated.

## V29 input evidence

Canonical shared root:

```text
/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720
```

The following hashes were identical when read independently from Node1 and
Node23:

```text
inputs/candidates_128.tsv
SHA256 83b60dbebfcee8fc0c073266d613b4cd23612416aae673711d5775eb6070d309
bytes 2,738,861

inputs/candidate_monomers_manifest.tsv
SHA256 d55a9e41cb308a0d4b420b47a636f585bcf0e5580663174f30337e5b91b18bfd
bytes 2,426,810
```

Candidate validation on Node1:

```text
rows                         9,934
unique candidate_id          9,934
unique sequence_sha256       9,934
parent clusters                 65
train                        6,878
development                  1,529
frozen_test                  1,527
sequence length range      106--133
sequence hash failures           0
empty/non-unique CDR failures    0
```

Monomer evidence:

```text
candidate monomer manifest rows  9,934
unique candidate IDs             9,934
PDB files visible on Node23      9,934
manifest-declared PDB bytes      1,444,795,843 (1.346 GiB)
```

Node1 sees the same 9,934 PDBs through `/data`.  They should remain there; the
new V2.9 structure adapter should read them by manifest-relative path and write
only its compact 126-D table/receipt under `/data1`.

The expanded D0 teacher is locally ready for deployment:

```text
v2_8_expanded3388_training_v1_20260719/prepared/
v6_scalar_teacher3388_v2_8.tsv
SHA256 47c20808bdd8a804e8672c4e0c814c1cd40f8d3469723d867ce4b0986b3eec10
rows 3,388; unique sequence hashes 3,388; parent clusters 31
sequence/CDR validation failures 0
```

## Safe four-GPU assignment

This assignment isolates the D0 and V29 input caches and avoids GPU 0:

| Physical GPU | Lane | Batch | Shard |
|---:|---|---:|---:|
| 1 | V29 9,934, ESM2-650M | 8 | 128 |
| 2 | V29 9,934, ESM2-3B | 2 | 64 |
| 3 | D0 3,388, ESM2-650M | 8 | 128 |
| 4 | D0 3,388, ESM2-3B | 2 | 64 |

Do not try to split one input/model across multiple GPUs with the current
script.  It has no row-offset/partition merger contract.  Four independent,
receipt-complete caches are safer than ad hoc shard concatenation.

Before actual launch, re-run `nvidia-smi` and fail if any selected GPU reports a
compute process or more than 1 GiB allocated.

## Exact proposed Node1 launcher commands

These commands are the recommended launcher body **after** the local D0 table
and implementation freeze/launcher have been copied into the versioned project.
They were not executed by this preflight.

```bash
set -euo pipefail

ROOT=/data1/qlyu/projects/pvrig_v2_9_expanded_training_v1_20260720
PY=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
CODE=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/cache_v6_esm_embeddings.py
M650=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c
M3B=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t36_3B_UR50D/snapshots/476b639933c8baad5ad09a60ac1a87f987b656fc
D0=$ROOT/inputs/v6_scalar_teacher3388_v2_8.tsv
V29=$ROOT/inputs/v29_candidates_9934.tsv

mkdir -p "$ROOT"/{inputs,runtime,status}

# Freeze compact inputs onto local NVMe.  Do not copy monomer PDBs.
install -m 0444 \
  /data/qlyu/projects/pvrig_v29_docking25k_v1_20260720/inputs/candidates_128.tsv \
  "$V29"

sha256sum -c <<'HASHES'
47c20808bdd8a804e8672c4e0c814c1cd40f8d3469723d867ce4b0986b3eec10  /data1/qlyu/projects/pvrig_v2_9_expanded_training_v1_20260720/inputs/v6_scalar_teacher3388_v2_8.tsv
83b60dbebfcee8fc0c073266d613b4cd23612416aae673711d5775eb6070d309  /data1/qlyu/projects/pvrig_v2_9_expanded_training_v1_20260720/inputs/v29_candidates_9934.tsv
69d1de369e175bdf1645256f31552cf78247dbb5e793d7f6f010f1f975fb518b  /data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_1/src/cache_v6_esm_embeddings.py
HASHES

test "$(df -Pk /data1 | awk 'NR==2{printf "%.0f",$4/1024/1024}')" -ge 50
test -x "$PY"
test -f "$M650/model.safetensors"
test -f "$M3B/pytorch_model.bin.index.json"

for gpu in 1 2 3 4; do
  used=$(nvidia-smi -i "$gpu" --query-gpu=memory.used --format=csv,noheader,nounits)
  test "$used" -lt 1024
done

run_cache () {
  local gpu=$1 input=$2 model=$3 output=$4 status=$5 batch=$6 shard=$7
  mkdir -p "$output" "$status"
  (
    export CUDA_VISIBLE_DEVICES="$gpu"
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
    exec setsid "$PY" "$CODE" \
      --input "$input" --model-path "$model" --output-dir "$output" \
      --device cuda:0 --dtype bfloat16 --batch-size "$batch" --shard-size "$shard"
  ) >"$status/stdout.json.tmp" 2>"$status/stderr.log" &
  echo "$!" >"$status/pid"
}

run_cache 1 "$V29" "$M650" "$ROOT/runtime/v29_9934_esm2_650m_v1" "$ROOT/status/v29_9934_esm2_650m_v1" 8 128
run_cache 2 "$V29" "$M3B"  "$ROOT/runtime/v29_9934_esm2_3b_v1"   "$ROOT/status/v29_9934_esm2_3b_v1"   2 64
run_cache 3 "$D0"  "$M650" "$ROOT/runtime/d0_3388_esm2_650m_v1"  "$ROOT/status/d0_3388_esm2_650m_v1"  8 128
run_cache 4 "$D0"  "$M3B"  "$ROOT/runtime/d0_3388_esm2_3b_v1"    "$ROOT/status/d0_3388_esm2_3b_v1"    2 64
```

The production launcher should add a supervisor that waits for all four PIDs,
atomically renames each `stdout.json.tmp`, validates all four receipts and shard
hashes, and emits one terminal receipt.  A child process exit alone is not a
PASS condition.

## Required gates before model fitting

1. Copy/freeze the 3,388-row D0 table and the 9,934-row V29 candidate table to
   the new `/data1` project; verify the hashes above.
2. Freeze a V2.9 cache consumer that accepts versioned cache row counts instead
   of the old `rows == 1507` constant.
3. Launch the four embedding lanes only after a fresh GPU/disk preflight.
4. Validate receipt input hash, model fingerprint, row count, candidate-to-
   sequence mapping, shard shapes, shard hashes, and finite values.
5. Keep all `model_split == frozen_test` labels sealed.  Computing their
   label-free embeddings is allowed, but no label join or metric access is
   allowed during open development.
6. Build a new V29-specific adapter before starting the 126-D monomer lane;
   reuse only the invariant `structure_features()` kernel, not the hard-coded
   V4-H wrapper.
7. Do not train directly against a mutable live Docking result directory.
   Consume only a separately frozen candidate-level teacher snapshot and its
   receipt.

## Claim boundary

This audit establishes infrastructure and label-free feature-input readiness.
It is not evidence that V2.9 training has started, completed, improved early
enrichment, predicted binding, predicted affinity, or predicted experimental
blocking.
