# Candidate generation

This directory contains the curated generators and wrappers rather than raw
candidate pools.  `generate_local_cpu_routes.py` covers conservative CDR
redesign; `prepare_natural_donor_topup_tasks.py` and
`prepare_exploration_control_tasks.py` cover natural-donor and profile/control
exploration; the `fixed_pose_*` files implement fixed-pose ProteinMPNN design.
The RFantibody/RFdiffusion integration is captured by the `rfantibody` and
`qc96_generation` scripts.  The final portfolio uses the fixed-pose
CPU ProteinMPNN lineage; the broader generators are retained for reproducible
method review.
