# Nanobody Workspace Lightweight Snapshot

This repository is a lightweight Git snapshot of the local nanobody/PVRIG workspace at `/mnt/d/work/抗体`.

It intentionally tracks code, scripts, tests, runbooks, reports, small structure/table artifacts, and documentation needed to understand and reproduce the work. It intentionally excludes the large local datasets, model weights, Conda/local environments, caches, and docking/model run outputs that make the workspace hundreds of GB.

## Sync Policy

- Build the allowlist with `scripts/build_lightweight_sync_manifest.py`.
- Sync future lightweight changes with `scripts/sync_lightweight_to_github.sh`.
- Default per-file limit: 5 MiB (`NANOBODY_SYNC_MAX_BYTES` can override).
- Git ignores new files by default; the sync script force-adds only manifest-selected lightweight artifacts.

See `docs/LIGHTWEIGHT_SYNC_INVENTORY.md` for the latest inventory and exclusion rationale.
