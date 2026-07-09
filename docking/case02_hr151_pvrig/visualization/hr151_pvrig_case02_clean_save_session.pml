reinitialize
load /mnt/d/work/抗体/docking/case02_hr151_pvrig/overlays/cluster_1_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb, cluster1_clean
hide everything
# Main proteins: keep simple.
show cartoon, cluster1_clean and chain A+B
color forest, cluster1_clean and chain A
color cyan, cluster1_clean and chain B
# Reference PVRL2 as faint ghost surface only.
show surface, cluster1_clean and chain L
color gray70, cluster1_clean and chain L
set transparency, 0.78, cluster1_clean and chain L
# Only show key mechanism residues, not all hotspots.
select hr151_cdr3, cluster1_clean and chain A and resi 98-116
show sticks, hr151_cdr3
color red, hr151_cdr3
select hr151_cdr12, cluster1_clean and chain A and resi 26-35+53-59
show sticks, hr151_cdr12
color yelloworange, hr151_cdr12
# Key PVRIG residues in 8X6B numbering: H92=B54, R95=B57, R98=B60, W100=B62, K135=B97, F139=B101, S143=B105, W144=B106.
select pvrig_key, cluster1_clean and chain B and resi 54+57+60+62+97+101+105+106
show sticks, pvrig_key
color orange, pvrig_key
select pvrig_R95, cluster1_clean and chain B and resi 57
show spheres, pvrig_R95
color magenta, pvrig_R95
# Hide waters and all nonessential atoms.
hide everything, resn HOH
# Visual settings.
set cartoon_transparency, 0
set surface_quality, 1
set stick_radius, 0.16
set sphere_scale, 0.45
set ray_opaque_background, off
set depth_cue, 0
bg_color white
# Named selections for quick toggles from right-side panel.
select VHH_HR151_chain_A, cluster1_clean and chain A
select PVRIG_chain_B, cluster1_clean and chain B
select PVRL2_reference_chain_L, cluster1_clean and chain L
# Scene 1: overall clean blocker view.
orient cluster1_clean
zoom cluster1_clean and chain A+B+L, 6
scene 001_overall_blocking_view, store
# Scene 2: zoom on interface and CDR3.
zoom hr151_cdr3 or pvrig_key or pvrig_R95, 8
scene 002_cdr3_hotspot_zoom, store
# Scene 3: just PVRIG + ghost PVRL2, temporarily hide VHH for baseline.
disable cluster1_clean
create pvrig_pvrl2_baseline, cluster1_clean and chain B+L
enable pvrig_pvrl2_baseline
show cartoon, pvrig_pvrl2_baseline and chain B
show surface, pvrig_pvrl2_baseline and chain L
color cyan, pvrig_pvrl2_baseline and chain B
color gray70, pvrig_pvrl2_baseline and chain L
set transparency, 0.78, pvrig_pvrl2_baseline and chain L
select baseline_key, pvrig_pvrl2_baseline and chain B and resi 54+57+60+62+97+101+105+106
show sticks, baseline_key
color orange, baseline_key
zoom pvrig_pvrl2_baseline, 6
scene 003_pvrig_pvrl2_baseline, store
disable pvrig_pvrl2_baseline
enable cluster1_clean
scene 001_overall_blocking_view, recall

save /mnt/d/work/抗体/docking/case02_hr151_pvrig/visualization/hr151_pvrig_case02_clean_view.pse
