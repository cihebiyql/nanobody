# Commands retained for V2.4 top2 pose asset run

Working constraints:
- Local write scope: `/mnt/d/work/抗体/docking/candidates/v2_4_top2/`
- Remote write scope: `/data/qlyu/projects/pvrig_v2_4_top2/`

Key executed commands:

```bash
# candidate extraction and bounded local asset package creation
python3 scripts/make_candidate_haddock_assets.py

# node1 connectivity/tool check
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \
  'hostname && whoami && date -Is && test -x /data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2 && test -x /data/qlyu/anaconda3/envs/haddock3/bin/haddock3 && echo tools_ok'

# remote project creation and package sync
ssh.exe -o BatchMode=yes node1 "mkdir -p /data/qlyu/projects/pvrig_v2_4_top2"
( cd /mnt/d/work/抗体/docking/candidates/v2_4_top2 && tar -cf - inputs scripts manifests haddock3 ) | \
  ssh.exe -o BatchMode=yes node1 "cd /data/qlyu/projects/pvrig_v2_4_top2 && tar -xf -"

# first remote run: zym_test_9743 completed; zym_test_108006 default NBB2 refinement failed and was logged
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20 node1 \
  'cd /data/qlyu/projects/pvrig_v2_4_top2 && bash scripts/run_node1_v2_4_top2.sh'

# fallback for zym_test_108006, retaining failed default log and using NanoBodyBuilder2 -u
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20 node1 \
  'cd /data/qlyu/projects/pvrig_v2_4_top2 && bash -s' <fallback_no_sidechain_bond_check_commands>

# sync remote evidence back into local bounded directory
ssh.exe -o BatchMode=yes node1 \
  "cd /data/qlyu/projects/pvrig_v2_4_top2 && tar -cf - inputs scripts manifests logs reports monomer haddock3" | \
  tar -xf - -C /mnt/d/work/抗体/docking/candidates/v2_4_top2/remote_sync
```

Important log files:
- `remote_sync/logs/run_node1_v2_4_top2.20260711_001703.log`
- `remote_sync/logs/zym_test_108006_nanobodybuilder2.log`
- `remote_sync/logs/zym_test_108006_fallback_no_sidechain_bond_check.20260711_002549.log`
- `remote_sync/haddock3/zym_test_9743/logs/zym_test_9743_haddock3_run.log`
- `remote_sync/haddock3/zym_test_108006/logs/zym_test_108006_haddock3_run.log`
