reinitialize
bg_color white
set ray_opaque_background, off
set cartoon_fancy_helices, on

# Native 8X6B chains: PVRL2 A and PVRIG B
# Native 9E6Y chains: PVRL2 D and PVRIG A
# Candidate docked chains: VHH A and PVRIG T
load references/8X6B.pdb, native8
load references/9E6Y.pdb, native9
load models/rank07_8X6B.pdb, cand8
load models/rank07_9E6Y.pdb, cand9
align cand8 and chain T, native8 and chain B
align cand9 and chain T, native9 and chain A

hide everything, all
show surface, cand8 and chain T
color marine, cand8 and chain T
set transparency, 0.28, cand8 and chain T
show cartoon, cand8 and chain A
color green, cand8 and chain A
show sticks, byres (cand8 and chain A within 4.5 of (cand8 and chain T))
color yellow, byres (cand8 and chain A within 4.5 of (cand8 and chain T))
show surface, native8 and chain A
color red, native8 and chain A
set transparency, 0.60, native8 and chain A
hide everything, native8 and chain B
hide everything, native9
hide everything, cand9
zoom cand8 or native8, 5
scene 8X6B_blocking_overlay, store

hide everything, all
show surface, cand9 and chain T
color slate, cand9 and chain T
set transparency, 0.28, cand9 and chain T
show cartoon, cand9 and chain A
color orange, cand9 and chain A
show sticks, byres (cand9 and chain A within 4.5 of (cand9 and chain T))
color yellow, byres (cand9 and chain A within 4.5 of (cand9 and chain T))
show surface, native9 and chain D
color magenta, native9 and chain D
set transparency, 0.60, native9 and chain D
hide everything, native9 and chain A
hide everything, native8
hide everything, cand8
zoom cand9 or native9, 5
scene 9E6Y_blocking_overlay, store
scene 8X6B_blocking_overlay, recall
