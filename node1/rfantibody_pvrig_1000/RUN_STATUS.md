# PVRIG RFantibody 1,000-sequence run status

Updated: 2026-07-12 15:02 CST  
Remote host: `node1`  
Remote root: `/data/qlyu/projects/pvrig_rfantibody_1000_20260712`

## Current state

`RUNNING`

Four background shards are active:

| Set | GPU | Hotspots | Target backbones | Raw MPNN sequences |
|---|---:|---|---:|---:|
| A | 1 | `T57,T101,T106` | 50 | 400 |
| B | 2 | `T62,T101,T106` | 50 | 400 |
| C | 3 | `T97,T101,T105,T106` | 50 | 400 |
| D | 4 | `T33,T36,T105,T106` | 50 | 400 |

The finalizer waits for all four `complete.json` markers, then extracts H-chain
sequences, validates full-length/CDR fields, exact-deduplicates globally, and
selects 250 sequences per hotspot set.

## Smoke evidence

- RFdiffusion accepted the PVRIG chain-T target and all three set-A hotspots.
- One 50-step backbone completed successfully.
- ProteinMPNN generated eight full-length VHH sequences from the smoke backbone.
- Smoke sequence length: 113 aa.
- Smoke CDR lengths: H1=7, H2=6, H3=5.
- Smoke RFdiffusion hotspot distances: minimum 4.97 A, average 8.11 A.

## Commands

```bash
ssh.exe node1 '
  cd /data/qlyu/projects/pvrig_rfantibody_1000_20260712
  bash scripts/status.sh
  tail -n 50 logs/finalizer.log
'
```

## Scientific boundary

The output is a hotspot-conditioned sequence/pose candidate pool. RF2 has not
been run in this generation stage, and the records are not validated PVRIG
binders or PVRIG-PVRL2 blockers.
