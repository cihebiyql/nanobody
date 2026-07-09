# Lightweight Sync Inventory

- Generated: 2026-07-09 10:29:56 Asia/Shanghai
- Workspace: `/mnt/d/work/抗体`
- Target remote: `git@github.com:cihebiyql/nanobody.git`
- SSH identity: `/root/.ssh/id_ed25519_github_yuqiule` copied from the Windows key whose public comment is `yuqiule@gmail.com`.
- Remote state before first sync: `git ls-remote` returned 0 refs, so the repository was treated as empty.

## Selection Result

- Selected files: 1,179
- Selected bytes: 37,297,298 (35.57 MiB)
- Per-file threshold: 5 MiB by default (`NANOBODY_SYNC_MAX_BYTES`).
- Included classes: source code, shell/Python scripts, notebooks under the threshold, Markdown/text docs, JSON/YAML/TOML config, small CSV/TSV/FASTA/PDB/CIF structure or table artifacts, and small documentation assets such as PNG/PDF/HTML.

## Included By Top-Level Area

| Area | Files | Size MiB |
| --- | ---: | ---: |
| `docking` | 760 | 10.02 |
| `机制` | 74 | 9.71 |
| `code` | 145 | 5.09 |
| `scaffolds` | 9 | 4.42 |
| `reports` | 65 | 3.66 |
| `tools` | 58 | 0.98 |
| `data` | 28 | 0.75 |
| `visualization` | 3 | 0.52 |
| `node1` | 12 | 0.15 |
| `docs` | 5 | 0.14 |
| `scripts` | 9 | 0.10 |
| `.` | 4 | 0.01 |
| `tests` | 2 | 0.01 |
| `positives` | 5 | 0.01 |

## Largest Included Files

| Size MiB | Path |
| ---: | --- |
| 4.46 | `机制/data/patents/WO2021180205A1/WO2021180205A1.pdf` |
| 1.98 | `scaffolds/vhh_scaffold_quality_table.csv` |
| 1.96 | `code/downloaded_models/Sequence-Based-NABP-paper.pdf` |
| 1.51 | `scaffolds/raw_vhh_scaffold_metadata.csv` |
| 1.29 | `机制/figures/pvrig_pvrl2_interface_overlay.png` |
| 1.29 | `reports/figures/pvrig_pvrl2_interface_overlay.png` |
| 1.04 | `机制/figures/pvrig_pvrl2_8x6b_interface.png` |
| 1.04 | `reports/figures/pvrig_pvrl2_8x6b_interface.png` |
| 1.01 | `机制/figures/pvrig_pvrl2_9e6y_interface.png` |
| 1.01 | `reports/figures/pvrig_pvrl2_9e6y_interface.png` |
| 0.52 | `visualization/pvrig_pvrl2_mechanism_view.html` |
| 0.52 | `机制/visualization/pvrig_pvrl2_mechanism_view.html` |
| 0.40 | `code/downloaded_models/DeepNano/fig1.png` |
| 0.39 | `tools/nanobody_tool_survey/report/nanobody_tool_survey_full.pdf` |
| 0.34 | `code/downloaded_models/Sequence-Based-NABP/Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv` |
| 0.34 | `code/downloaded_models/NABP-LSTM-Att/Supplementary_Materials.pdf` |
| 0.32 | `data/structures/8X6B.pdb` |
| 0.32 | `机制/data/structures/8X6B.pdb` |
| 0.29 | `code/downloaded_models/Sequence-Based-NABP/Code/Antigene_Antibody_Data_Preprocessing_PWM.ipynb` |
| 0.28 | `scaffolds/clean_vhh_scaffold_library.fasta` |
| 0.27 | `scaffolds/raw_vhh_scaffold_pool.fasta` |
| 0.22 | `code/downloaded_models/Sequence-Based-NABP/Plots/nanobody_kmers_embedding.png` |
| 0.19 | `scaffolds/top_200_vhh_scaffolds_for_design.csv` |
| 0.19 | `data/structures/9E6Y.pdb` |
| 0.19 | `机制/data/structures/9E6Y.pdb` |

## Explicit Exclusions

- `.conda-envs/`, `.local/`, any `.omx/` directory at any level, cache directories, `__pycache__/`, logs, pid/status/tmp directories.
- `data/datasets/`, `data/models/`, and `data/model_data/` because they are large downloaded corpora, model outputs, and training data rather than lightweight source/docs.
- `code/downloads_background/`, `code/repro_outputs/`, model weight directories such as `NABP-BERT-models`, and downloaded model data/output folders.
- `docking/**/haddock3`, `docking/**/workdirs`, pose/model output folders, remote/log/test-output folders; lightweight docking scripts, reports, inputs, and small aligned structures remain eligible.
- `tools/nanobody_tool_survey/code/` and `tools/nanobody_tool_survey/papers/`, which are bulky external tool/paper mirrors; local survey metadata and reports remain eligible.
- Any file over the size threshold or with a non-allowlisted binary/generated extension.

## Pre-push Sensitive Pattern Scan

A manifest-scoped scan checked for private-key blocks, GitHub/OpenAI/HuggingFace/AWS-style tokens, and password/secret assignments. It found only reviewed false positives: protein sequence text containing `AKIA...`, ordinary source variables named `token`, and a `gsk-...` URL slug that matched the OpenAI-key shape. No real private key or API token was found in the selected manifest at the time of sync.

## Re-sync Command

```bash
scripts/sync_lightweight_to_github.sh
```

The sync script regenerates `docs/lightweight_sync_manifest.txt`, temporarily bypasses manifest-selected embedded Git checkout boundaries without adding their internal `.git/` directories, force-adds only the manifest-selected files, commits using the configured Git identity, and pushes with the dedicated GitHub SSH key.
