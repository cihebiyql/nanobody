#!/usr/bin/env bash
set -euo pipefail

WD=/mnt/d/work/抗体/docking/calibration/patent_success_validation/case02_pos_06_20H5
REMOTE=/data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5

# Run HADDOCK3 on node1 after `run_node1_structure_prediction.sh` has uploaded inputs.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 'set -euo pipefail
cd /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/haddock3
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 case02_pos_06_20H5_pvrig_hotspot_test.cfg
'

# Bring the run directory back for local scoring/postprocessing.
mkdir -p "$WD/haddock3"
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'cd /data/qlyu/projects/pvrig_candidates/case02_pos_06_20H5/haddock3 && tar -cf - run_case02_pos_06_20H5_pvrig_hotspot_test' | tar -C "$WD/haddock3" -xf -
