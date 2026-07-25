# One-page submission summary

**Objective.** Produce a diverse, developable VHH portfolio designed to occupy
the PVRIG–PVRL2 interface rather than merely bind PVRIG.  The submitted package
contains the audited computational Top50 and one representative 9E6Y complex
for each Top10 priority candidate.

**Design and screening.** Candidate generation includes conservative CPU CDR
redesign, natural-CDR donor and profile/control exploration, RFantibody/
RFdiffusion plus ProteinMPNN, and fixed-pose ProteinMPNN/local sequence
optimization.  The final Top50 are fixed-pose CPU ProteinMPNN candidates.  A
multimodal layer prepares sequence/structure/contact features, trains and
evaluates surrogate models, and combines independent lanes.  This is followed
by ANARCI/IMGT and official validation, positive-CDR similarity screening,
VHH/developability assessment, and intra-team diversity control.

**Structural evidence.** Public receptor conformations 8X6B and 9E6Y are
prepared with interface residues and hotspot restraints.  HADDOCK runs use
multiple docking seeds; aggregation records both receptor conformations, seed
consistency, PVRL2-occlusion/blocking geometry, and static structure metrics.
Hard gates and a final diversity-aware ranking produce the Top50 and official
Excel export.

**Delivered evidence.** `data/submission/final_top50_ranked.tsv` is the master
evidence table; `final_top50_ranked.fasta` and `final50.official_submit.xlsx` are
the official sequence/export artifacts.  `candidate_traceability.tsv` gives,
for every candidate ID: sequence and SHA256, parent and CDR changes, generation
method/seed/version, QC, monomer status, docking protocol, receptor and docking
seeds, route-aware R8/R9/Rdual values, static review, and final rank.  The
final manifest records 50 candidates with zero final hard failures and 50/50
official-validator and similarity passes.

**Boundary.** All ranking evidence is computational and supports prioritization
only.  No expression, purity, affinity, or experimental PVRL2-blocking result
is claimed.  Heavy raw data, all-pose docking directories, environments,
caches, logs, private keys, and non-redistributable model weights are omitted.
