# HR-151 / PVRIG Case 02 docking first-pass report

Date: 2026-07-07
Local root: `/mnt/d/work/抗体/docking/case02_hr151_pvrig`
Remote root: `/data/qlyu/projects/pvrig_case02_hr151_docking`

## What was run

1. Prepared local and remote inputs from existing mechanism-package structures:
   - `inputs/8X6B_PVRIG_chainB.pdb`
   - `inputs/8X6B_PVRL2_chainA.pdb`
   - `inputs/9E6Y_PVRIG_chainA.pdb`
   - `inputs/9E6Y_PVRL2_chainD.pdb`
   - `inputs/hr151_vhh.fasta`
2. Built the HR-151 nanobody monomer with NanoBodyBuilder2:
   - `monomer/hr151_nanobodybuilder2.pdb`
   - log: `logs/nanobodybuilder2_hr151.log`
3. Ran Chai-1 and Boltz-2 co-folding attempts against 8X6B PVRIG:
   - Minimal/smoke settings generated invalid or low-confidence complex geometry.
   - Higher sampling (`steps50`) generated geometrically sane proteins, but the predicted PVRIG chain still needed large alignment to 8X6B, so these are not used as primary fixed-receptor docking evidence.
4. Ran HADDOCK3 fixed-receptor, hotspot-guided docking:
   - config: `haddock3/hr151_pvrig_hotspot_test.cfg`
   - restraints: `haddock3/data/hr151_cdr_to_pvrig_hotspot_ambig.tbl`
   - run folder: `haddock3/run_hr151_pvrig_hotspot_test`
   - selected top cluster models: `haddock3/top_models_unzipped/`
   - aligned-to-8X6B models: `haddock3/top_models_aligned_to_8x6b/`

## HR-151 CDR note

The local FASTA sequence contains this CDR3-like segment:

```text
AAGDSPDGRCPPLGQGLNY  positions 98-116 in the modeled sequence
```

The case-study text/table contains `AAGDSPDGRCGLPPQGLNY`, which does not exactly match the FASTA. For structural scoring in this run, CDR ranges were based on the actual modeled FASTA sequence:

```text
CDR1: 26-35
CDR2: 53-59
CDR3: 98-116
```

This should be reconciled before using HR-151 CDR identity for leakage/similarity decisions.

## Best first-pass HADDOCK poses

Detailed table: `reports/haddock3_top_model_mechanism_scores.csv`

| Model | HADDOCK rank | HADDOCK score | PVRIG align RMSD to 8X6B | Hotspot overlap | CDR contact residues | PVRL2 occluding atom contacts | Initial interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `cluster_1_model_1` | 1 | -99.226 | 5.184 A | 18 / 23 | 11 | 681 | Best energy + strong hotspot coverage + strong PVRL2 occlusion; primary first-pass pose |
| `cluster_8_model_1` | 8 | -38.019 | 3.576 A | 14 / 23 | 14 | 982 | Strongest steric occlusion and lowest receptor-alignment distortion; useful alternative mechanism pose |
| `cluster_3_model_1` | 3 | -48.980 | 11.259 A | 18 / 23 | 16 | 694 | Good contacts/occlusion, but receptor alignment distortion is higher |
| `cluster_2_model_1` | 2 | -51.219 | 17.422 A | 20 / 23 | 15 | 0 | High hotspot contact but no PVRL2 occlusion after overlay; likely binder-like/nonblocking pose |

## Overlay structures for visual inspection

These combine aligned HR-151/PVRIG pose chains with reference 8X6B PVRL2 renamed to chain `L`:

```text
overlays/cluster_1_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb
overlays/cluster_8_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb
overlays/cluster_3_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb
overlays/cluster_10_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb
```

Open these in PyMOL/ChimeraX and inspect whether VHH chain `A` occupies the same space as PVRL2 chain `L` around PVRIG chain `B`.

## Interpretation boundary

- These are computational docking poses, not experimental PVRIG-HR151 structures.
- HADDOCK run used a small test sampling (`rigidbody sampling=40`, top 10 flexref/emref), enough to prove the pipeline and generate first-pass poses, not enough for final ranking.
- Chai/Boltz co-folding was useful as a tool check, but the de novo predicted PVRIG conformation is not reliable enough to replace fixed-receptor HADDOCK for the blocking question.
- The first-pass result supports using HADDOCK fixed-receptor docking plus PVRL2 overlay as the main path for Case 02 mechanism calibration.

## Recommended next run

1. Increase HADDOCK sampling to the full/example scale (`rigidbody sampling` hundreds to 1000; select top 100-200 for refinement).
2. Add a second receptor baseline using `9E6Y` PVRIG and its PVRL2 chain for independent occlusion scoring.
3. Add solvent-accessible/passive residue filtering so constraints do not over-force buried hotspots.
4. After manual OCR completes PVRIG-20/30/38/39/151 full VHH sequences, repeat this same workflow as a multi-positive calibration set.
