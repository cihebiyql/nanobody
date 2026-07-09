#!/usr/bin/env bash
set -euo pipefail

WD=/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_06_20H5

# 1) Check GPU first; choose an idle device before longer jobs.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits'

# 2) Build VHH monomer with NanoBodyBuilder2 on node1.
# -u avoids an ImmuneBuilder/OpenMM strained-sidechain repair bug observed in
# rare mutant controls; local pdb_geometry_qc.py still checks backbone sanity.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 'set -euo pipefail
BIN=/data/qlyu/anaconda3/envs/boltz/bin
mkdir -p /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/monomer
SEQ="EVQLVESGGGLVQPGGSLRLSCAASGYTSRTDCMGWFRQAPGKEHEGVAHIDSDGIPRYVDSVKGRFTISQDHAKNSLYLQMNSLRAEDTAVYYCVVGFKFDEDYCAPNDWGQGTMVTVSS"
CUDA_VISIBLE_DEVICES=0 PATH="$BIN:$PATH" NanoBodyBuilder2 -H "$SEQ" -o /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/monomer/case02_pos_06_20H5_nanobodybuilder2.pdb -u --n_threads 4 -v
'

# 3) Copy the monomer PDB back through ssh.exe. Linux scp may not know the
#    Windows SSH alias/proxy for node1.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'cat /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/monomer/case02_pos_06_20H5_nanobodybuilder2.pdb' > "$WD/monomer/case02_pos_06_20H5_nanobodybuilder2.pdb"

# 4) Normalize the monomer to chain A and sequential residue numbering.
#    The CDR ranges in this workdir are sequence-position ranges.
python /mnt/d/work/抗体/docking/scripts/normalize_pdb_chain.py \
  --in-pdb "$WD/monomer/case02_pos_06_20H5_nanobodybuilder2.pdb" \
  --out-pdb "$WD/haddock3/data/case02_pos_06_20H5_vhh_chainA.pdb" \
  --chain-id A \
  --expected-residue-count 121

# 5) Upload the prepared HADDOCK3 input bundle to node1.
tar -C "$WD/haddock3" -cf - . | ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'mkdir -p /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/haddock3 && tar -C /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/haddock3 -xf -'
