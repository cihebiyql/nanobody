# Phase 2 V2.2 GPU Evidence

Updated: 2026-07-09

## Verdict

V2.2 was executed with CUDA on the local RTX 5080. The run was fast because the model and training loop are intentionally compact and sample a bounded number of residue-pair contacts per record per epoch; it did not train over every one of the 4.28M contact pairs in every optimizer step.

## Reproducible Evidence

From `experiments/phase2_5080_v1/reports/phase2_v2_2_full2277_metrics.json`:

```json
{
  "best_epoch": 6,
  "cuda_available": true,
  "cuda_version": "13.0",
  "device": "cuda",
  "gpu_name": "NVIDIA GeForce RTX 5080",
  "run_id": "phase2_v2_2_full2277_20260709_seed41",
  "torch": "2.13.0+cu130"
}
```

Checkpoint probe, loading `experiments/phase2_5080_v1/runs/phase2_v2_2_full2277_20260709_seed41/best_checkpoint.pt` in the Phase 2 venv:

```text
torch 2.13.0+cu130
cuda_available True
gpu_name NVIDIA GeForce RTX 5080
checkpoint_epoch 6
first_tensor_device cuda:0
first_tensor_shape (22, 160)
```

Run timestamps:

```text
config_resolved.json: 2026-07-09 17:27:45 +0800
metrics_history.json: 2026-07-09 17:33:42 +0800
test_metrics.json: 2026-07-09 17:33:42 +0800
```

Approximate wall-clock from config creation to final metrics: about 5 min 56 sec.

## Why It Was Fast

- Architecture is compact: `d_model=160`, `layers=2`, `cross_layers=1`.
- Contact training samples per record: `contact_pos_sample=64`, `contact_neg_sample=256`; it does not backpropagate all positive/negative residue pairs in each pass.
- Batch sizes are small and GPU-friendly: contact batch `12`, site/pair batch `24`.
- Mixed precision AMP was enabled on CUDA.
- The full2277 dataset has 6068 train contact records, not millions of independent training examples at the dataloader level; the millions are residue-pair labels sampled inside records.

## Missing Evidence

No continuous `nvidia-smi` telemetry log was written during this run. Future long runs should launch with a sidecar GPU monitor such as:

```bash
while true; do date -Is; nvidia-smi --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu,power.draw --format=csv,noheader; sleep 5; done \
  > experiments/phase2_5080_v1/logs/<run_id>_gpu_telemetry.log
```

