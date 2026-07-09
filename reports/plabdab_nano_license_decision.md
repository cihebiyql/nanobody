# PLAbDab-nano License and Use-Term Decision

## Decision

PLAbDab-nano can be used for **local internal Phase I-b scaffold screening** in this workspace, with provenance and citation retained. The raw downloaded PLAbDab-nano CSV/GZ data should **not** be redistributed with submitted code or release artifacts unless a clearer dataset license is confirmed.

Practical decision for this project:

| Question | Decision | Rationale |
| --- | --- | --- |
| Can we use it for the competition workflow? | Yes, for local screening and scaffold selection. | The competition allows open data/code with attribution, and PLAbDab-nano exposes public downloads with source links. |
| Can we use it for training/screening? | Screening yes; model training only with explicit provenance and caution. | Phase I-b uses filtering/scoring, not supervised PVRIG-positive model training. |
| Can we keep a download/import script in code? | Yes. | Script records source URL/release metadata and does not vendor raw data. |
| Can we commit/distribute the raw PLAbDab-nano CSV/GZ? | No, not by default. | The page exposes downloads, but the downloadable CSV dataset license is not explicit enough. |
| What should submission include? | Source citation, download URL, release metadata, importer code, derived scaffold IDs/sequences only if competition rules allow. | Avoid bundling unmodified third-party bulk data. |

## Evidence Used

- Official PLAbDab-nano page states it is a self-updating repository of just under 5000 VHH, VNAR, and single-domain antibody sequences from patents and academic papers.
- Official page provides direct downloads for `all_sequences.csv.gz`, `vhh_sequences.csv.gz`, and `vnar_sequences.csv.gz`.
- Temporary access review confirmed HTTP `200` for the download routes and 4457 rows in `vhh_sequences.csv.gz`.
- PLAbDab-nano article DOI metadata reports the article itself under CC BY 4.0.
- The linked `oxpig/PLAbDab` GitHub repository has BSD 3-Clause licensing for code, but this should not be assumed to license every sequence record in the downloadable dataset.
- PLAbDab-nano rows include per-record provenance fields such as source, original ID/model, reference authors/title, organism, update date, and targets mentioned.

## Operating Rules for Importer

1. Do not store the original `vhh_sequences.csv.gz` under the workspace as a durable source artifact.
2. Download to a temporary file or user cache only.
3. Write derived scaffold artifacts required by Phase I-b:
   - `scaffolds/raw_vhh_scaffold_pool.fasta`
   - `scaffolds/raw_vhh_scaffold_metadata.csv`
   - `scaffolds/vhh_scaffold_quality_table.csv`
   - `scaffolds/clean_vhh_scaffold_library.fasta`
   - `scaffolds/top_200_vhh_scaffolds_for_design.fasta`
   - `scaffolds/top_200_vhh_scaffolds_for_design.csv`
4. Keep `license_or_use_terms` as `PLAbDab-nano_public_download_dataset_license_not_explicit; local_internal_screening_only; do_not_redistribute_raw_csv` for imported rows.
5. Preserve per-record source URL/path and original identifiers.
6. Treat all imported rows as scaffold candidates only, not PVRIG-positive binders.
7. If final competition submission needs source disclosure, cite PLAbDab-nano and provide the importer/download URL rather than bundling raw downloaded data.

## Current Risk Level

Medium-low for local internal screening; medium for redistribution or external release.

The main risk is not technical access. The risk is ambiguous data-use terms for the downloadable CSVs relative to the code license and article license. The importer must therefore keep a clear provenance/use-term caveat.

## Verification Anchor

Plain-language anchor for automated checks: raw PLAbDab-nano CSV/GZ should not be redistributed with submissions unless a clearer dataset license is confirmed.
