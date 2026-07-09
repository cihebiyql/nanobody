# Download Status

Generated: 2026-07-06 18:25 CST
Workspace: `/mnt/d/work/抗体/code`

## What Is Already Local

| Asset | Local path | Status |
|---|---|---|
| DeepNano code | `downloaded_models/DeepNano/` | Downloaded from `ddd9898/DeepNano`. |
| DeepNano data | `downloaded_models/DeepNano-data/` | Downloaded from `ddd9898/DeepNano-data`. |
| DeepNano 8M checkpoints | `downloaded_models/DeepNano/output/checkpoint/` | Complete: PPI seq, NAI seq, site, and full DeepNano NAI 8M checkpoints. |
| NABP-BERT code | `downloaded_models/NABP-BERT/` | Downloaded from `FMoonlightS/NABP-BERT`. |
| NABP-LSTM-Att code | `downloaded_models/NABP-LSTM-Att/` | Downloaded from `FMoonlightS/NABP-LSTM-Att`. |
| Sequence-Based NABP code/data | `downloaded_models/Sequence-Based-NABP/` | Downloaded from `sarwanpasha/Nanobody_Antigen`; paper PDF also saved. |
| NanoBinder code | `downloaded_models/NanoBinder/` | Downloaded from `pallucs/NanoBinder`; upstream does not include `dataset.csv`. |
| NanoBind code/data | `downloaded_models/NanoBind/` | Downloaded from `zhaosq17/NanoBind`. |
| NanoBind checkpoints | `downloaded_models/NanoBind/output/checkpoint/` | Complete for `seq`, `site`, `pro`, and `pair` models; the original 134-byte LFS pointer is preserved as `.lfs-pointer.txt`. |

## Background Resumable Downloads

The long downloads are running through resumable tools in the background. The launcher is:

```bash
cd /mnt/d/work/抗体/code
bash downloads_background/scripts/start_all_downloads.sh
bash downloads_background/scripts/status.sh
```

Current jobs:

| Job | Tool | Target | Notes |
|---|---|---|---|
| `deepnano_checkpoints` | `wget -c` | DeepNano 35M/150M/650M checkpoint matrix from Tsinghua Cloud | Continues beyond the already complete 8M checkpoints; active checkpoint job may leave partial files until log reports each file complete. |
| `deepnano_esm2` | `wget -c` | ESM2 35M/150M/650M encoder files from Hugging Face | Completed; rerun only for verification/resume. |
| `google_drive_assets` | `gdown --continue` | NABP-BERT Google Drive model zip, then NABP-LSTM-Att Google Drive folder | Completed: `NABP-BERT-models.zip`, `data.rar`, `model.rar`. |
| `nabpbert_training_data` | `wget -c` | HINT binary PPI files and UniProt Swiss-Prot/TrEMBL FASTA files | TrEMBL is very large; this may run for hours. |
| `nanobind_site_lfs` | `curl -C -` via Git LFS batch API | NanoBind site checkpoint | Complete; rerunning exits quickly. |

Logs and PID files:

```text
downloads_background/logs/*.log
downloads_background/pids/*.pid
downloads_background/scripts/*.sh
```

## Known Missing Or Author-Limited Assets

- `NABP-BERT`: Google Drive package downloaded as `downloaded_models/NABP-BERT/_downloads/google_drive/NABP-BERT-models.zip`; it is not extracted yet.
- `NABP-LSTM-Att`: Google Drive folder downloaded as `downloaded_models/NABP-LSTM-Att/_downloads/google_drive/data.rar` and `downloaded_models/NABP-LSTM-Att/_downloads/google_drive/model.rar`; archives are not extracted yet.
- `NanoBinder`: upstream repository does not publish the paper `../data/Dataset/dataset.csv` or a ready inference weight. Reproduction requires rebuilding Rosetta feature data from SAbDab complexes or obtaining it from the authors/webserver.
- `Sequence-Based NABP`: no released neural/ML weight is expected; it is a traditional ML baseline that should be retrained from the provided CSV/notebook data.

## Reproduction Manual

See the Chinese reproduction manual:

```text
docs/NANOBODY_MODEL_REPRODUCTION_GUIDE_ZH.md
```
