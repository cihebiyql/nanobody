reinitialize
load data/structures/8X6B.pdb, pdb8x6b
load data/structures/9E6Y.pdb, pdb9e6y
hide everything
bg_color white
set ray_opaque_background, off
set antialias, 2
set cartoon_fancy_helices, 1
set dash_width, 2.0
set label_size, 16
set label_color, black
# Align both complexes by PVRIG chains to compare interface conservation
align pdb9e6y and chain A, pdb8x6b and chain B
# Base coloring: PVRIG receptor cyan/teal, PVRL2 ligand gray
show cartoon, pdb8x6b and (chain A+B)
show cartoon, pdb9e6y and (chain A+D)
color teal, pdb8x6b and chain B
color marine, pdb9e6y and chain A
color gray70, pdb8x6b and chain A
color gray50, pdb9e6y and chain D
set cartoon_transparency, 0.20, pdb9e6y
# Interface surfaces
show surface, pdb8x6b and chain B
set transparency, 0.55, pdb8x6b and chain B
show surface, pdb9e6y and chain A
set transparency, 0.70, pdb9e6y and chain A
select core_8x6b, pdb8x6b and chain B and resi 33+34+36+43+44+45+52+54+57+58+60+62+97+99+100+101+102+103+104+105+106
color orange, core_8x6b
show sticks, core_8x6b
show spheres, core_8x6b and name CA
set sphere_scale, 0.35, core_8x6b and name CA
select core_9e6y, pdb9e6y and chain A and resi 31+32+34+41+42+43+50+52+55+56+58+60+95+97+98+99+100+101+102+103+104
color orange, core_9e6y
show sticks, core_9e6y
show spheres, core_9e6y and name CA
set sphere_scale, 0.35, core_9e6y and name CA
select secondary_8x6b, pdb8x6b and chain B and resi 59
color yellow, secondary_8x6b
show sticks, secondary_8x6b
show spheres, secondary_8x6b and name CA
set sphere_scale, 0.35, secondary_8x6b and name CA
select secondary_9e6y, pdb9e6y and chain A and resi 47
color yellow, secondary_9e6y
show sticks, secondary_9e6y
show spheres, secondary_9e6y and name CA
set sphere_scale, 0.35, secondary_9e6y and name CA
# Soft hints: R95 magenta, I97 pink, S67 blue-gray; these are not hard constraints
select soft_R95, (pdb8x6b and chain B and resi 57) or (pdb9e6y and chain A and resi 55)
select soft_I97, (pdb8x6b and chain B and resi 59) or (pdb9e6y and chain A and resi 57)
select soft_S67, (pdb8x6b and chain B and resi 29) or (pdb9e6y and chain A and resi 27)
color magenta, soft_R95
color hotpink, soft_I97
color slate, soft_S67
show sticks, soft_R95 or soft_I97 or soft_S67
label (pdb8x6b and chain B and resi 57 and name CA), "R95 (pdb8x6b:B57)"
label (pdb9e6y and chain A and resi 55 and name CA), "R95 (pdb9e6y:A55)"
label (pdb8x6b and chain B and resi 59 and name CA), "I97 (pdb8x6b:B59)"
label (pdb9e6y and chain A and resi 57 and name CA), "I97 (pdb9e6y:A57)"
label (pdb8x6b and chain B and resi 29 and name CA), "S67 (pdb8x6b:B29)"
label (pdb9e6y and chain A and resi 27 and name CA), "S67 (pdb9e6y:A27)"
# Closest heavy-atom contacts at the PVRIG-PVRL2 interface
distance d_8x6b_01, (pdb8x6b and chain B and resi 102 and name O), (pdb8x6b and chain A and resi 62 and name OG)
color red, d_8x6b_01
distance d_8x6b_02, (pdb8x6b and chain B and resi 97 and name NZ), (pdb8x6b and chain A and resi 111 and name OE2)
color red, d_8x6b_02
distance d_8x6b_03, (pdb8x6b and chain B and resi 105 and name N), (pdb8x6b and chain A and resi 51 and name OD1)
color red, d_8x6b_03
distance d_8x6b_04, (pdb8x6b and chain B and resi 105 and name O), (pdb8x6b and chain A and resi 41 and name OE1)
color red, d_8x6b_04
distance d_8x6b_05, (pdb8x6b and chain B and resi 36 and name OG1), (pdb8x6b and chain A and resi 119 and name OG)
color red, d_8x6b_05
distance d_8x6b_06, (pdb8x6b and chain B and resi 52 and name CG1), (pdb8x6b and chain A and resi 115 and name O)
color red, d_8x6b_06
distance d_8x6b_07, (pdb8x6b and chain B and resi 105 and name OG), (pdb8x6b and chain A and resi 39 and name CG2)
color red, d_8x6b_07
distance d_8x6b_08, (pdb8x6b and chain B and resi 101 and name CE1), (pdb8x6b and chain A and resi 60 and name O)
color red, d_8x6b_08
distance d_8x6b_09, (pdb8x6b and chain B and resi 58 and name O), (pdb8x6b and chain A and resi 115 and name CE1)
color red, d_8x6b_09
distance d_8x6b_10, (pdb8x6b and chain B and resi 57 and name NE), (pdb8x6b and chain A and resi 34 and name CD2)
color red, d_8x6b_10
distance d_9e6y_01, (pdb9e6y and chain A and resi 95 and name NZ), (pdb9e6y and chain D and resi 141 and name OE2)
color red, d_9e6y_01
distance d_9e6y_02, (pdb9e6y and chain A and resi 100 and name O), (pdb9e6y and chain D and resi 92 and name OG)
color red, d_9e6y_02
distance d_9e6y_03, (pdb9e6y and chain A and resi 31 and name O), (pdb9e6y and chain D and resi 66 and name OG)
color red, d_9e6y_03
distance d_9e6y_04, (pdb9e6y and chain A and resi 103 and name O), (pdb9e6y and chain D and resi 71 and name NE2)
color red, d_9e6y_04
distance d_9e6y_05, (pdb9e6y and chain A and resi 103 and name OG), (pdb9e6y and chain D and resi 69 and name OG1)
color red, d_9e6y_05
distance d_9e6y_06, (pdb9e6y and chain A and resi 103 and name N), (pdb9e6y and chain D and resi 81 and name OD1)
color red, d_9e6y_06
distance d_9e6y_07, (pdb9e6y and chain A and resi 34 and name OG1), (pdb9e6y and chain D and resi 149 and name OG)
color red, d_9e6y_07
distance d_9e6y_08, (pdb9e6y and chain A and resi 52 and name NE2), (pdb9e6y and chain D and resi 66 and name OG)
color red, d_9e6y_08
distance d_9e6y_09, (pdb9e6y and chain A and resi 100 and name O), (pdb9e6y and chain D and resi 94 and name CG)
color red, d_9e6y_09
distance d_9e6y_10, (pdb9e6y and chain A and resi 99 and name CZ), (pdb9e6y and chain D and resi 90 and name O)
color red, d_9e6y_10
hide labels, d_*
# Views/scenes
orient (core_8x6b or secondary_8x6b or soft_R95 or soft_I97)
zoom (core_8x6b or secondary_8x6b or soft_R95 or soft_I97), 8
scene interface_overlay, store
disable pdb9e6y
zoom (pdb8x6b and (chain A+B)), 5
scene complex_8x6b, store
enable pdb9e6y
disable pdb8x6b
zoom (pdb9e6y and (chain A+D)), 5
scene complex_9e6y, store
enable pdb8x6b
scene interface_overlay, recall
png figures/pvrig_pvrl2_interface_overlay.png, 1800, 1400, ray=1
disable pdb9e6y
png figures/pvrig_pvrl2_8x6b_interface.png, 1800, 1400, ray=1
enable pdb9e6y
disable pdb8x6b
png figures/pvrig_pvrl2_9e6y_interface.png, 1800, 1400, ray=1
enable pdb8x6b
set_name pdb8x6b, 8X6B_PVRIG_PVRL2
set_name pdb9e6y, 9E6Y_PVRIG_PVRL2
save visualization/pvrig_pvrl2_mechanism_view.pse
