# Phase 2 V2.5 GPU Telemetry Summary V1

- GPU used: **True** (`NVIDIA GeForce RTX 5080`)
- ESM2 embedding sampler: 26 samples; peak device-wide sampled memory `5477 MiB`.
- Shallow-head training sampler: 44 samples; peak device-wide sampled memory `3147 MiB`; peak sampled utilization `17%`.
- PyTorch training peak allocated memory: `67.57 MiB`; formal inference peak: `32.62 MiB`.

The model after embedding extraction is a 64-hidden-unit shallow ranker over frozen pooled features. Its short kernels do not saturate an RTX 5080, and the low sampled utilization is expected rather than evidence of CPU fallback. All three training seeds and all three formal inference passes report `actual_device=cuda` and the RTX 5080 device name.
