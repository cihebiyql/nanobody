# PLAbDab-nano Access Review for Phase I-b

## Purpose

This review checks whether PLAbDab-nano is ready for the first controlled scaffold import. It only verifies access route, schema, and use-term risk. It does **not** import scaffold records into the workspace library.

## Sources Checked

- PLAbDab-nano official page: `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/`
- PLAbDab-nano about page: `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/about/`
- PLAbDab GitHub repository: `https://github.com/oxpig/PLAbDab`
- PLAbDab-nano DOI metadata: `https://doi.org/10.1093/nar/gkae881`

## Findings

- The official page describes PLAbDab-nano as a self-updating repository of just under 5000 VHH, VNAR, and single-domain antibody sequences from patents and academic papers.
- The page exposes direct download links:
  - `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/static/downloads/all_sequences.csv.gz`
  - `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/static/downloads/vhh_sequences.csv.gz`
  - `https://opig.stats.ox.ac.uk/webapps/plabdab-nano/static/downloads/vnar_sequences.csv.gz`
- HTTP HEAD checks on 2026-07-06 returned `200` for all three download files. `vhh_sequences.csv.gz` reported `content-length: 334071`, `last-modified: Wed, 22 Oct 2025 11:33:00 GMT`.
- A temporary schema check of `vhh_sequences.csv.gz` in `/tmp` found 4457 rows: 4427 `VHH` and 30 `VHH/sdAb`; no sequences were empty; sequence lengths ranged from 70 to 141 amino acids.
- CSV fields observed: `source`, `model`, `type`, `cdr_lengths`, `cdr_sequences`, `sequence`, `ID`, `definition`, `reference_authors`, `reference_title`, `organism`, `update_date`, `targets_mentioned`.
- The article DOI metadata reports the PLAbDab-nano paper under Creative Commons BY 4.0, but the web page itself does not state a clear data-license/use-term line for the downloadable CSVs.
- The linked `oxpig/PLAbDab` GitHub repository has a BSD 3-Clause license for repository code, but that should not be treated as the data license for every downloaded sequence record.

## Decision

PLAbDab-nano is technically ready for a controlled importer, but bulk workspace import should wait until the importer records source URL, release date, per-record provenance, and the unresolved dataset-use-term note.

Current registry state in `scaffolds/source_registry.csv`:

```text
PLAbDab-nano = download_route_confirmed_not_imported
```

## Import Gate Implications

The first importer should:

1. Start from `vhh_sequences.csv.gz`, not `all_sequences.csv.gz`.
2. Preserve the original source fields and the download URL for every row.
3. Store the PLAbDab-nano file `last-modified` value as `source_release` until a better release identifier is available.
4. Mark `license_or_use_terms` as unresolved/needs review unless a clearer dataset license is found.
5. Limit the first workspace import to 500-2000 rows after deduplication and gate checks.
6. Treat PLAbDab-nano rows as scaffold sources only, not as PVRIG-positive sequences.

## Stop Condition Before Import

Do not create `scaffolds/raw_vhh_scaffold_pool.fasta` yet unless the next task explicitly starts the controlled importer and records the use-term caveat in `vhh_scaffold_quality_table.csv`.

## Follow-up Status

The next task explicitly started the controlled importer. The pre-import stop condition above has therefore been superseded by `reports/plabdab_nano_scaffold_gate_summary.md`. Raw PLAbDab-nano CSV/GZ data remains non-vendored; derived scaffold FASTA/CSV artifacts now exist for local Phase I-b screening.
