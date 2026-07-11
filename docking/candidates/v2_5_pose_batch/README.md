# Node1 PVRIG V2.5 Pose/QC Batch Package

Bounded local package for the next Node1 pose/QC batch. This directory is the only intended local write scope:

- Local root: `/mnt/d/work/抗体/docking/candidates/v2_5_pose_batch`
- Remote root: `/data/qlyu/projects/pvrig_v2_5_pose_batch`
- Source package reused: `/mnt/d/work/抗体/docking/candidates/v2_4_top2`
- V2.4 covered candidates excluded: `zym_test_9743`, `zym_test_108006`

## Claim Boundary

This package preserves the computational-proxy boundary. It prepares NanoBodyBuilder2 monomers, sequence validation, backbone geometry QC, receptor geometry QC, and optionally HADDOCK3 hotspot/CDR-guided docking. These outputs are computational pose/QC proxies only; they are not binding evidence, blocking proof, or wet-lab validation.

## Selected Candidates

Top 8 from `experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv` after excluding the V2.4 top2 coverage:

1. `zym_test_359954`
2. `zym_test_5495`
3. `zym_test_21966`
4. `zym_test_3633872`
5. `zym_test_8787`
6. `zym_test_665332`
7. `zym_test_2510237`
8. `zym_test_6823`

## Package Contents

- `manifests/selected_candidates_manifest.tsv` and `.json` - selected candidates, hashes, source paths, source hashes, ranks, CDR coordinates, and evidence boundary.
- `inputs/v2_5_pose_batch_vhh.fasta` - VHH FASTA for the 8 selected candidates.
- `inputs/candidate_cdr_ranges.tsv` - CDR1/CDR2/CDR3 sequence-numbering ranges used for HADDOCK ambiguous restraints.
- `inputs/pvrig_8x6b_chainB.pdb` and `inputs/hotspot_residues_8x6b.txt` - receptor/hotspot inputs reused from V2.4.
- `scripts/make_candidate_haddock_assets.py` - reusable local/remote asset generator for per-candidate HADDOCK3 configs and restraint files.
- `scripts/run_node1_v2_5_pose_batch.sh` - remote Node1 runner; default mode runs monomer + sequence/geometry QC only and skips HADDOCK3 unless explicitly gated on.
- `tests/test_v2_5_package.py` - local unit/smoke checks for selection, hashes, CDR ranges, generated assets, and remote-script gates.

## Remote Runner Gates

`run_node1_v2_5_pose_batch.sh` is safe-by-default for production scheduling:

- GPU assignment is configurable with `V2_5_CUDA_DEVICES`.
- NanoBodyBuilder2 threads are configurable with `V2_5_NBB2_THREADS`.
- HADDOCK3 is disabled unless `V2_5_RUN_HADDOCK3=1` is set.
- HADDOCK3 refuses to start when `/proc/loadavg` 1-minute load exceeds `V2_5_MAX_LOAD1`.
- Default remote root is `/data/qlyu/projects/pvrig_v2_5_pose_batch`.

## Local Validation

Run from this package root:

```bash
python3 scripts/build_v2_5_pose_batch.py
python3 scripts/make_candidate_haddock_assets.py
python3 -m unittest discover -s tests -v
bash -n scripts/run_node1_v2_5_pose_batch.sh
```

No command in this package SSHes or starts production by itself.
