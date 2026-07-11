# PVRIG Existing Structure and Node1 Asset Rediscovery V1

- Date: 2026-07-10
- Status: **FOUND_AND_EXPLAINED**
- Scope: local workspace `/mnt/d/work/抗体` plus a read-only check of the existing node1 project root
- Main conclusion: the remembered PVRIG/PVRL2 and HR-151 assets do exist. The V2.3 P3 result of `0/50` is still correct because those structures belong to known-positive/calibration cases, not to the current `zym_test_*` top-50 candidates.

## 1. Decisive findings

1. `8X6B` and `9E6Y` are available locally as experimental PVRIG-PVRL2 reference complexes.
2. HR-151 has a verified local and node1-mirrored NanoBodyBuilder2 monomer.
3. HR-151/PVRIG candidate complexes exist from Chai-1, Boltz-2, and hotspot/CDR-guided HADDOCK3.
4. The most reusable structural assets are the fixed-receptor HADDOCK3 poses aligned to `8X6B` and `9E6Y`, together with PVRL2-overlay and occlusion reports.
5. These HR-151 structures are computational predictions, not experimental antibody-PVRIG complex structures.
6. The current P3 top-50 contains 50 `zym_test_*` sequences with zero exact sequence or candidate-ID overlap with the 11 known PVRIG positive/calibration VHHs.
7. The workspace contains useful same-target positive families and mutant controls, but no row-level, experimentally verified PVRIG non-blocker sequence table yet.

## 2. Structure inventory and chain verification

| Asset | Evidence type | Verified chain composition | Intended use |
| --- | --- | --- | --- |
| `/mnt/d/work/抗体/机制/data/structures/8X6B.pdb` | Experimental PVRIG-PVRL2 reference | chain B: PVRIG, 103 aa; chain A: PVRL2, 126 aa | Primary receptor/ligand baseline and interface reference |
| `/mnt/d/work/抗体/机制/data/structures/9E6Y.pdb` | Experimental PVRIG-PVRL2 reference | chain A: PVRIG, 108 aa; chain D: PVRL2, 130 aa | Independent receptor/ligand baseline |
| `/mnt/d/work/抗体/docking/case02_hr151_pvrig/monomer/hr151_nanobodybuilder2.pdb` | Predicted HR-151 monomer | chain H: HR-151, 127 aa | Reliable VHH starting model |
| `/mnt/d/work/抗体/docking/case02_hr151_pvrig/complex/chai1_8x6b/out_steps50/pred.model_idx_0.pdb` | Predicted co-folded complex | chain A: exact HR-151, 127 aa; chain B: exact 8X6B PVRIG, 103 aa | Comparison only; not the primary blocker geometry |
| `/mnt/d/work/抗体/docking/case02_hr151_pvrig/aligned/boltz_steps50_hr151_pvrig_8x6b_aligned_to_8x6b.pdb` | Predicted co-folded complex | chain H: exact HR-151, 127 aa; chain B: exact 8X6B PVRIG, 103 aa | Comparison only; not the primary blocker geometry |
| `/mnt/d/work/抗体/docking/case02_hr151_pvrig/haddock3/top_models_unzipped/cluster_1_model_1.pdb` | Hotspot/CDR-guided docking pose | chain A: exact HR-151, 127 aa; chain B: exact 8X6B PVRIG, 103 aa | Positive-control docking and blocker-geometry calibration |
| `/mnt/d/work/抗体/docking/case02_hr151_pvrig/overlays/cluster_1_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb` | Synthetic overlay for competition geometry | chain A: HR-151; chain B: PVRIG; chain L: reference PVRL2 | Direct visual and numerical PVRL2-occlusion check |

The HR-151 sequence SHA256 is `4e01a499c9625e7acec711f477dcdb9008279cf95763572ece323ba45581d220`. It matches the HR-151 chain extracted from the monomer, Chai, Boltz, HADDOCK, and overlay files exactly.

## 3. Local/node1 mirror verification

The existing remote project is still reachable at:

`/data/qlyu/projects/pvrig_case02_hr151_docking`

The following local and remote files are byte-identical:

| File | SHA256 |
| --- | --- |
| `monomer/hr151_nanobodybuilder2.pdb` | `e8862ed9b6ab9365829fc94cad02f9010354621a44c0d33bb054a1891cd3f4cf` |
| `inputs/hr151_vhh.fasta` | `55c59d50a20aee8b16dc9c4655329090927eead424215782eb651dab3bc9c103` |
| `inputs/8X6B_PVRIG_chainB.pdb` | `b8560ca059ca5f16b85a8e17219864a644089fbdc51d0b4f98cc71e469c56b10` |

The node1 project contains completed NanoBodyBuilder2, Chai-1, Boltz-2, and HADDOCK3 outputs. The local workspace contains the downstream uncompressed, aligned, scored, and PVRL2-overlay artifacts.

## 4. Existing reusable workflow

The shortest validated route is:

```text
VHH FASTA
  -> NanoBodyBuilder2 monomer
  -> geometry QC
  -> fixed PVRIG receptor + hotspot/CDR-guided HADDOCK3
  -> align pose to 8X6B and 9E6Y
  -> overlay reference PVRL2
  -> score hotspot contact, total occlusion, and CDR3 occlusion
  -> retain a pose ensemble and inspect baseline agreement
```

Key entry points:

- `/mnt/d/work/抗体/node1/NODE1_ANTIBODY_TOOLS_QUICKSTART.md`
- `/mnt/d/work/抗体/node1/CASE02_PVRIG_VHH_DOCKING_PLAN.md`
- `/mnt/d/work/抗体/docking/scripts/pdb_geometry_qc.py`
- `/mnt/d/work/抗体/docking/scripts/align_pdb_by_chain.py`
- `/mnt/d/work/抗体/docking/scripts/score_pvrig_vhh_pose.py`
- `/mnt/d/work/抗体/docking/scripts/score_cdr_region_occlusion.py`
- `/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/blocker_validation_protocol_v1.md`
- `/mnt/d/work/抗体/docking/case02_hr151_pvrig/reports/hr151_positive_control_8x6b_9e6y_consensus.csv`

The HR-151 first-pass `cluster_1_model_1` is computationally classified as blocker-like against both reference baselines. This is useful positive-control calibration, not experimental proof of that exact pose.

## 5. Same-target VHH and label assets

### 5.1 Curated PVRIG positive/calibration lane

- `/mnt/d/work/抗体/data/model_data/pvrig_blocker_positive_calibration_v0.csv`
  - 11 unique PVRIG VHH sequences.
  - 109 docking-pose summary rows in total: ten cases have 10 poses and one has 9.
  - Five cases have blocking IC50 values, ten have Kd values, and five have reporter EC50 values.
  - This is the strongest current PVRIG-specific positive/calibration table.
- `/mnt/d/work/抗体/docking/calibration/patent_success_validation/batch_manifest.csv`
  - The matching 11-case sequence and workflow manifest.
- `/mnt/d/work/抗体/positives/known_positive_antibodies.fasta`
  - Three official sequence records: Tab5 VH, Tab5 VL, and HR-151 VHH.

These rows must remain in the positive calibration and leakage-control lane. They must not be relabeled as ordinary new candidates.

### 5.2 Same-family mutant/control lane

- `/mnt/d/work/抗体/data/model_data/pvrig_blocker_mutant_control_calibration_v0.csv`
  - 36 rows: 7 exact base references and 29 mutants.
  - All are explicitly labeled `mutant_or_leakage_control_not_new_design`.
- `/mnt/d/work/抗体/data/model_data/pvrig_blocker_mutant_pose_labels_v0.csv`
  - 357 docking-derived pose labels.
  - Classes: 210 `BLOCKER_PLAUSIBLE_B`, 109 `SINGLE_BASELINE_BLOCKER_RECHECK`, 30 `EVIDENCE_INFERENCE_ONLY_E`, and 8 `CONSENSUS_BLOCKER_LIKE_A`.

These mutants are useful for robustness, ordinal ranking, and sensitivity analysis. They are not experimentally verified negative binders or non-blockers.

### 5.3 Existing hard-negative proxies

- `pair_ranking_triplets_v2_clustered.csv`: 3,614 constructed contrastive preferences.
- `pair_negatives_v1.csv`: 3,621 constructed pair negatives.
- `contact_negatives_v1.csv`: 8,696 same-complex residue pairs at least 8 A apart.

Important semantic boundary:

- The pair-negative rows have `binding_label=0`, but their recorded reason is `not_observed_as_cognate_pair_in_ZYMScott_Paratope_current_manifest`.
- Therefore they are unobserved/constructed contrastive negatives, not verified experimental non-binders.
- The 8,696 residue-level noncontacts are valid contact-task negatives, but they do not establish whole-pair non-binding.

### 5.4 Promising missing negative source

`/mnt/d/work/抗体/机制/case_studies/01_COM701_CPA7021_Tab5_机制详解.md` records a patent panel of 29 anti-PVRIG hybridoma binders: 20 clear blockers and 9 non-blockers. This is exactly the biological distinction needed for V2.4.

However, the current workspace only preserves the aggregate 20/9 result. It does not yet contain a row-level sequence-to-blocker/non-blocker mapping for those 29 antibodies. It cannot yet be used as a verified negative training table.

## 6. Why V2.3 P3 still reports 0/50

The current top-50 contains 50 `zym_test_*` candidates. Cross-checking the P3 manifest against the 11 PVRIG positive sequences gives:

- exact candidate-ID overlap: 0
- exact VHH-sequence overlap: 0
- accepted candidate-specific complex poses: 0

P3 scanned the local `docking`, `node1`, and `reports` roots, including the HR-151/calibration assets. It correctly rejected them for ordinary-candidate fusion because they do not belong to any `zym_test_*` candidate.

This is not a chain-parser failure. The geometry extractor never reaches chain parsing for these 50 rows because every `pose_path` is empty.

## 7. Recommended integration, with strict separation

### Lane A: reference and calibration

Use `8X6B`, `9E6Y`, HR-151, the 11 positive VHHs, and the 36 mutant controls to:

- validate receptor alignment and PVRL2-overlay scoring;
- calibrate pose-quality and blocker-geometry thresholds;
- measure model sensitivity to within-family perturbations;
- prevent leakage and overclaiming.

Do not mix this lane into ordinary top-50 candidate evaluation.

### Lane B: candidate-specific geometry

Use the existing node1 workflow to generate real complex poses for a small consensus subset first, beginning with `zym_test_9743` and `zym_test_108006` because both were stable across all three V2.3 seeds.

Each accepted P3 candidate must have:

- an exact `candidate_id` and exact VHH sequence match;
- a complex PDB containing that VHH and PVRIG;
- geometry QC pass;
- explicit VHH and PVRIG chain IDs;
- scoring against both `8X6B` and `9E6Y` PVRL2 baselines;
- a pose ensemble rather than one cherry-picked model.

### Lane C: real pair/ranking supervision

The highest-value data task is to recover row-level identities, sequences, and assay labels for the patent 20-blocker/9-non-blocker panel or another genuine PVRIG binder-but-non-blocker series. Until that exists:

- keep ZYM/re-paired negatives as contrastive proxies;
- keep mutant panels as calibration proxies;
- do not calculate or claim calibrated blocker probabilities;
- do not expect model-size growth alone to solve pair ranking.

## 8. Immediate next executable package

The existing assets support a concrete next package without rebuilding infrastructure:

1. Generate a dedicated calibration-pose manifest for the 11 positives and 109 pose summaries.
2. Build node1 inputs for `zym_test_9743` and `zym_test_108006`.
3. Run NanoBodyBuilder2 plus fixed-receptor HADDOCK3 against both structural baselines.
4. Import only exact candidate-specific, QC-passing complex poses into P3.
5. Separately recover the patent non-blocker identities and sequences before calling them training negatives.

