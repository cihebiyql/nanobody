# PVRIG RFantibody 1,000-sequence generation run

Run date: 2026-07-12  
Remote root: `/data/qlyu/projects/pvrig_rfantibody_1000_20260712`

## Objective

Generate a traceable pool of 1,000 unique full-length VHH sequences conditioned
on four sparse PVRIG-PVRL2 interface hotspot sets. This is a generation run,
not a binder or blocker validation run.

## Completion

The run completed successfully on 2026-07-12. Four shards produced 200
RFdiffusion backbones and 1,600 ProteinMPNN sequence-pose records. Global exact
deduplication and balanced allocation produced 1,000 exact-unique full-length
VHH sequences, with 250 sequences from each hotspot set.

The synced local deliverables are under:

```text
/mnt/d/work/抗体/node1/rfantibody_pvrig_1000/results/
```

`results/LOCAL_VERIFICATION.json` records an independent post-transfer check of
FASTA/TSV consistency, exact uniqueness, CDR lengths, hotspot-set quotas,
completion markers, known-positive exact matches, and SHA256 hashes. See
`RUN_STATUS.md` for the detailed Chinese report and the set-B geometry warning.

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
nohup bash scripts/finalize_when_ready.sh > logs/finalizer.log 2>&1 < /dev/null &
```

The finalizer waits for all four `complete.json` markers and then runs
`collect_sequences.py` automatically. Manual collection remains available with
`python3 scripts/collect_sequences.py`.

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
