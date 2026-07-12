# PVRIG RFantibody 1,000-sequence generation run

Run date: 2026-07-12  
Remote root: `/data/qlyu/projects/pvrig_rfantibody_1000_20260712`

## Objective

Generate a traceable pool of 1,000 unique full-length VHH sequences conditioned
on four sparse PVRIG-PVRL2 interface hotspot sets. This is a generation run,
not a binder or blocker validation run.

## Design

- RFdiffusion: 50 backbones per hotspot set, 200 total.
- ProteinMPNN: 8 CDR sequences per backbone, 1,600 raw sequence-pose records.
- Final selection: 250 exact-unique sequences per hotspot set, 1,000 total.
- Framework: official humanized `h-NbBCII10` example framework.
- CDR lengths: `H1:7,H2:6,H3:5-13`.
- RFdiffusion: 50 timesteps, deterministic indexing, no trajectories.
- ProteinMPNN: H1/H2/H3, temperature 0.2, omit C/X, deterministic mode.
- RF2: not run in this generation stage.

Hotspot sets are stored in `config/hotspot_sets.tsv`.

## Remote commands

```bash
cd /data/qlyu/projects/pvrig_rfantibody_1000_20260712
bash scripts/launch_all.sh
bash scripts/status.sh
python3 scripts/collect_sequences.py
```

Final artifacts:

```text
final/pvrig_rfantibody_1000.fasta
final/pvrig_rfantibody_1000.tsv
final/raw_candidates.tsv
final/summary.json
final/sha256sums.txt
```

Each final record remains labelled `NEEDS_RF2_DOCKING`. Hotspot targeting alone
does not establish PVRIG binding, affinity, or PVRIG-PVRL2 blockade.
