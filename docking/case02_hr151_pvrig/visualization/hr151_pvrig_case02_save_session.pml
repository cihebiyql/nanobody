reinitialize
load /mnt/d/work/抗体/docking/case02_hr151_pvrig/overlays/cluster_1_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb, cluster1_rank1
load /mnt/d/work/抗体/docking/case02_hr151_pvrig/overlays/cluster_8_model_1_aligned_with_ref8x6b_pvrl2_chainL.pdb, cluster8_occlusion
hide everything
show cartoon, cluster1_rank1
show cartoon, cluster8_occlusion
color forest, cluster1_rank1 and chain A
color cyan, cluster1_rank1 and chain B
color gray70, cluster1_rank1 and chain L
color palegreen, cluster8_occlusion and chain A
color lightblue, cluster8_occlusion and chain B
color gray50, cluster8_occlusion and chain L
# HR-151 CDRs based on the modeled FASTA sequence.
select hr151_cdrs_cluster1, cluster1_rank1 and chain A and resi 26-35+53-59+98-116
select hr151_cdr3_cluster1, cluster1_rank1 and chain A and resi 98-116
show sticks, hr151_cdrs_cluster1
color yelloworange, hr151_cdrs_cluster1
color red, hr151_cdr3_cluster1
# PVRIG 8X6B hotspot residues from PVRIG_hotspot_set_v1.csv refs.
select pvrig_hotspots_cluster1, cluster1_rank1 and chain B and resi 33+34+36+43+44+45+49+52+54+57+58+59+60+62+97+99+100+101+102+103+104+105+106
show sticks, pvrig_hotspots_cluster1
color orange, pvrig_hotspots_cluster1
select pvrig_R95_cluster1, cluster1_rank1 and chain B and resi 57
show spheres, pvrig_R95_cluster1
color magenta, pvrig_R95_cluster1
# PVRL2 reference chain from 8X6B, renamed L in overlay.
show surface, cluster1_rank1 and chain L
set transparency, 0.65, cluster1_rank1 and chain L
# Make cluster8 available but hidden by default to reduce visual clutter.
disable cluster8_occlusion
set cartoon_transparency, 0.0
set stick_radius, 0.18
set sphere_scale, 0.45
set ray_opaque_background, off
bg_color white
orient cluster1_rank1
zoom cluster1_rank1, 8
# Labels for orientation.
pseudoatom label_hr151, pos=[30,65,58], label="HR-151 VHH chain A green / CDR3 red"
pseudoatom label_pvrig, pos=[-12,18,18], label="PVRIG chain B cyan / hotspots orange / R95 magenta"
pseudoatom label_pvrl2, pos=[12,20,62], label="8X6B PVRL2 reference chain L (transparent gray)"
show labels, label_*
set label_color, black
set label_size, 16

save /mnt/d/work/抗体/docking/case02_hr151_pvrig/visualization/hr151_pvrig_case02_view.pse
