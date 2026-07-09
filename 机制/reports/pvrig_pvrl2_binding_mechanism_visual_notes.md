# PVRIG-PVRL2 Binding Mechanism Visual Notes

## What to Open

- PyMOL script: `visualization/pvrig_pvrl2_mechanism_view.pml`
- PyMOL session: `visualization/pvrig_pvrl2_mechanism_view.pse`
- Key residue table: `data/structures/PVRIG_key_contact_residues_v1.csv`
- Hotspot set: `data/structures/PVRIG_hotspot_set_v1.csv`
- PNG snapshots: `reports/figures/pvrig_pvrl2_interface_overlay.png`, `reports/figures/pvrig_pvrl2_8x6b_interface.png`, `reports/figures/pvrig_pvrl2_9e6y_interface.png`

## Color Legend

- PVRIG receptor: cyan/blue cartoon and surface.
- PVRL2/Nectin-2 ligand: gray cartoon.
- Core hotspots: orange sticks/spheres; these are 21 PVRIG interface positions supported by both 8X6B and 9E6Y.
- Secondary hotspots: yellow sticks/spheres; these are 2 edge contacts supported by one structure under the current 4.5 A cutoff.
- R95: magenta; strongest patent soft hint because it overlaps the consensus distance interface.
- I97: hot pink; weaker soft hint, supported as a current contact only in 8X6B.
- S67: slate; mapped but outside the current PVRIG-PVRL2 distance interface.
- Red dashed lines: ten closest heavy-atom PVRIG-PVRL2 contacts per structure.

## Mechanistic Interpretation

The interface is a broad Ig-like domain surface, not a deep pocket. The current strongest blocking seed is the two-structure consensus interface: a surface patch that includes charged residues such as H92/R95/R98/K135/E141 in UniProt numbering. R95 is especially important for review because it is both a patent-derived soft hint and a consensus interface residue. I97 sits next to this region but has weaker structural support. S67 maps away from the current distance interface and should not drive Phase I scoring.

Use this view to reason about where a VHH CDR3 or redesigned CDR surface would need to occupy space to sterically compete with PVRL2. Do not interpret this view as a docking pose, affinity model, or antibody paratope.
