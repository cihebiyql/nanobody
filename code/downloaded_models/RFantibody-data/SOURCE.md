# RFantibody public antibody training table

Downloaded: 2026-07-12

Source record: <https://zenodo.org/records/15741710>

DOI: `10.5281/zenodo.15741710`

Upstream description: antibody dataset used to train the antibody RFdiffusion
model and fine-tune RoseTTAFold2 in *Atomically accurate de novo design of
antibodies with RFdiffusion*. The record states that it is modified from
SAbDab and releases the table under CC BY 4.0.

## Files

- `AntibodyTrainingDataset.csv`: upstream CSV, byte-for-byte unchanged.
- `zenodo_15741710_metadata.json`: upstream Zenodo record metadata.
- `DATASET_AUDIT.json`: local, dependency-free summary of the released CSV.

Expected checksum:

```text
md5:e2eb7b90e3733e0ac9247dd53857c5aa  AntibodyTrainingDataset.csv
```

## Important interpretation boundary

The CSV is not a table of 11,777 independent experimentally verified
antibody-antigen interactions. It contains repeated structures/copies,
constructed negative examples, heavy-only/light-only entries, records without
a protein target sequence, and a released cluster-split flag.

The exact end-to-end RFantibody training mixture is not fully represented by
this file. The paper supplement also describes TCR-pMHC examples,
loop-mediated PDB interfaces, and an in-house set of 1.6 million experimental
miniprotein designs used during the second RF2 fine-tuning stage.

Re-download command:

```bash
curl --retry 5 --retry-all-errors -L -C - \
  https://zenodo.org/api/records/15741710/files/AntibodyTrainingDataset.csv/content \
  -o AntibodyTrainingDataset.csv
```
