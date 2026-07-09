# HR-151 positive-control CDR3 occlusion validation

Date: 2026-07-07
Scope: Case 02 HR-151 / PVRIG first-pass docking, using the known successful HR-151/PVRIG-151-related VHH case as positive-control calibration.

## Question being tested

The visual observation was:

```text
The red CDR3 blocks the PVRL2 reference position, while the green VHH framework stays outside.
```

The mechanistic question is whether this is quantitatively consistent with a blocker-like VHH pose, rather than only a generic PVRIG binder.

## Inputs

- Main pose set: `haddock3/top_models_aligned_to_8x6b/`
- Reference PVRL2 position: `机制/data/structures/8X6B.pdb`, chain `A`
- VHH chain in aligned HADDOCK poses: chain `A`
- PVRIG chain in aligned HADDOCK poses: chain `B`
- HR-151 modeled CDR ranges used for this run:

```text
CDR1: 26-35
CDR2: 53-59
CDR3: 98-116
```

Note: these ranges follow the actual modeled FASTA sequence. The CDR3 spelling mismatch between the case-study table and FASTA still needs separate sequence curation before final leakage/similarity reporting.

## Script

New reusable script:

```text
docking/scripts/score_cdr_region_occlusion.py
```

It partitions VHH-vs-reference-PVRL2 occlusion into:

```text
CDR3
CDR1
CDR2
framework
```

and outputs both atom-contact and residue-pair-contact counts. For blocker validation, residue-pair counts are the preferred coarse metric because they are less sensitive to side-chain atom density.

## Main result

Summary CSV:

```text
reports/cdr_region_occlusion/cdr3_occlusion_summary.csv
reports/hr151_positive_control_blocker_classification.csv
```

Key rows:

| Model | HADDOCK rank | Hotspot overlap | Total PVRL2 occlusion residue-pairs | CDR3-PVRL2 occlusion residue-pairs | CDR3 fraction | Interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cluster_1_model_1` | 1 | 18 | 681 | 194 | 0.285 | best-energy blocker-like positive pose |
| `cluster_8_model_1` | 8 | 14 | 982 | 270 | 0.275 | strongest steric blocker-like alternative pose |
| `cluster_3_model_1` | 3 | 18 | 694 | 118 | 0.170 | blocker-like but less CDR3-centered |
| `cluster_10_model_1` | 10 | 15 | 630 | 110 | 0.175 | blocker-like but weaker overall |
| `cluster_2_model_1` | 2 | 20 | 0 | 0 | 0.000 | hotspot binder-like but nonblocking by PVRL2 overlay |

## Mechanistic interpretation

The observation is reasonable, with one important nuance:

```text
CDR3 is a substantial blocking wedge, but not the only steric contributor.
```

For `cluster_1_model_1`, HR-151 CDR3 accounts for 194 residue-pair occlusion contacts against PVRL2, about 28.5% of the total VHH-PVRL2 residue-pair occlusion. The framework still contributes steric bulk outside the interface, but the CDR3 supplies a focused red wedge into the PVRL2-binding zone.

This fits a VHH-blocker model:

```text
VHH framework = external scaffold / steric wall
long CDR3 = interface-facing wedge
combined effect = PVRL2 cannot dock in its original 8X6B position
```

Therefore the correct future rule should not be `CDR3 must explain >50% of all occlusion`. That would be too strict and would reject plausible VHH blockers. The better rule is:

```text
A successful blocker-like pose should combine:
1. high PVRIG hotspot/interface overlap;
2. substantial total VHH-vs-PVRL2 occlusion;
3. nontrivial CDR3-vs-PVRL2 occlusion;
4. CDR/CDR3 contact with the PVRIG interface;
5. rejection of poses with hotspot contact but zero PVRL2 occlusion.
```

`cluster_2_model_1` is the key negative-control pose inside the same successful-case run: it contacts many hotspot residues, but has zero PVRL2 occlusion. This validates the earlier principle that binding/interface contact alone is not enough.

## Conclusion

This positive-control run supports a practical blocker-validation route for later candidates:

```text
Run docking against fixed PVRIG interface
  -> overlay PVRL2 from 8X6B/9E6Y
  -> quantify total VHH-PVRL2 occlusion
  -> quantify CDR3-specific PVRL2 occlusion
  -> require hotspot/interface coverage
  -> downgrade hotspot-only but non-occluding poses
```

This does not experimentally prove the HR-151 pose. It does validate a computational screening criterion that is consistent with an existing successful VHH blocker case.
