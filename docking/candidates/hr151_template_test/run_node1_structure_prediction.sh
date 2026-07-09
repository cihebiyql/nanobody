#!/usr/bin/env bash
set -euo pipefail

# 1) Check GPU first; choose an idle device before longer jobs.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits'

# 2) Build VHH monomer with NanoBodyBuilder2 on node1.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 'set -euo pipefail
BIN=/data/qlyu/anaconda3/envs/boltz/bin
mkdir -p /data/qlyu/projects/pvrig_candidates/hr151_template_test/monomer
SEQ="HVQLVESGGGSVQAGGSLRLSCVASASGFTYRPYCMAWFRQAPGKEREAVAGIDIFGGTTYADSVKGRFTASRDNAGFSLFLQMNDLKPEDTAMYYCAAGDSPDGRCPPLGQGLNYWGQGTQVTVSS"
CUDA_VISIBLE_DEVICES=0 PATH="$BIN:$PATH" NanoBodyBuilder2 -H "$SEQ" -o /data/qlyu/projects/pvrig_candidates/hr151_template_test/monomer/hr151_template_test_nanobodybuilder2.pdb --n_threads 4 -v
'

# 3) Copy the monomer PDB back, then rename/set chain A if needed.
scp node1:/data/qlyu/projects/pvrig_candidates/hr151_template_test/monomer/hr151_template_test_nanobodybuilder2.pdb docking/candidates/hr151_template_test/monomer/hr151_template_test_nanobodybuilder2.pdb

# 4) Put the prepared chain-A monomer at:
#    docking/candidates/hr151_template_test/haddock3/data/hr151_template_test_vhh_chainA.pdb
# Then run HADDOCK3 from node1 or from the machine where HADDOCK3 is available:
# ssh.exe node1 'cd /data/qlyu/projects/pvrig_candidates/hr151_template_test/haddock3 && /data/qlyu/anaconda3/envs/haddock3/bin/haddock3 hr151_template_test_pvrig_hotspot_test.cfg'
