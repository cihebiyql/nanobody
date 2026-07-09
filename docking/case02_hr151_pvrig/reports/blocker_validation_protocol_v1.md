# Blocker validation protocol v1: success-case-calibrated PVRIG VHH docking

This protocol converts the HR-151/PVRIG-151-related successful VHH case into a reusable computational filter for future PVRIG-blocking VHH candidates.

## Required inputs for each candidate

1. Candidate VHH sequence.
2. Modeled VHH monomer, preferably with NanoBodyBuilder2.
3. Fixed PVRIG receptor structure, initially `8X6B` PVRIG chain `B`.
4. Reference PVRL2 position, initially `8X6B` PVRL2 chain `A`.
5. PVRIG hotspot table: `机制/data/structures/PVRIG_hotspot_set_v1.csv`.
6. Candidate CDR ranges from ANARCI/IMGT or explicitly curated numbering.

## Workflow

```text
1. Model candidate VHH monomer.
2. Dock candidate VHH to fixed PVRIG with hotspot/CDR-guided HADDOCK3.
3. Align each pose to 8X6B PVRIG.
4. Overlay PVRL2 from 8X6B.
5. Score:
   - PVRIG hotspot overlap;
   - total VHH-vs-PVRL2 occlusion;
   - CDR3-vs-PVRL2 occlusion;
   - CDR/CDR3-vs-PVRIG contacts;
   - reject hotspot-only non-occluding poses.
```

## HR-151-calibrated first-pass thresholds

These are not universal biophysical thresholds; they are first-pass calibration values from the HR-151 positive-control run.

A pose is `BLOCKER_LIKE_A` if it meets all:

```text
PVRIG hotspot overlap count >= 14
Total VHH-PVRL2 residue-pair occlusion >= 500
CDR3-PVRL2 residue-pair occlusion >= 100
CDR3 occlusion fraction >= 0.15
```

A pose is `BINDER_LIKE_C` if:

```text
PVRIG hotspot overlap count >= 14
but total VHH-PVRL2 residue-pair occlusion < 50
```

This explicitly catches poses like HR-151 `cluster_2_model_1`: strong interface contact but no predicted blocking geometry.

## Commands

Score region-specific occlusion:

```bash
python docking/scripts/score_cdr_region_occlusion.py \
  --pose-pdb aligned_pose.pdb \
  --reference-pdb 机制/data/structures/8X6B.pdb \
  --vhh-chain A \
  --ref-pvrl2-chain A \
  --cdr1 26-35 \
  --cdr2 53-59 \
  --cdr3 98-116 \
  --out-csv candidate_cdr_region_occlusion.csv \
  --out-json candidate_cdr_region_occlusion.json
```

Score hotspot overlap and total pose metrics:

```bash
python docking/scripts/score_pvrig_vhh_pose.py \
  --pose-pdb aligned_pose.pdb \
  --reference-pdb 机制/data/structures/8X6B.pdb \
  --pvrig-chain B \
  --vhh-chain A \
  --ref-pvrig-chain B \
  --ref-pvrl2-chain A \
  --hotspots-csv 机制/data/structures/PVRIG_hotspot_set_v1.csv \
  --hotspot-ref-column pdb_8x6b_ref \
  --assume-aligned \
  --cdr-ranges 'CDR1:26-35,CDR2:53-59,CDR3:98-116' \
  --out-csv candidate_pose_score.csv
```

## Interpretation

- Passing this protocol means `structurally blocker-like`, not experimentally confirmed blocking.
- Failing the occlusion test even with high hotspot contact means `binder-like` or wrong pose, not a prioritized blocker.
- Final candidate ranking should repeat the same protocol against `9E6Y` as a second receptor/PVRL2 baseline.
