# Commands for Node1 V2.5 Pose/QC Batch

All commands are scoped to the V2.5 package and remote root only. Do not overwrite V2.4 top2 outputs or NanoBind checkpoints.

## Local Rebuild and Smoke Checks

```bash
cd /mnt/d/work/抗体/docking/candidates/v2_5_pose_batch
python3 scripts/build_v2_5_pose_batch.py
python3 scripts/make_candidate_haddock_assets.py
python3 -m unittest discover -s tests -v
bash -n scripts/run_node1_v2_5_pose_batch.sh
find inputs manifests scripts haddock3 tests README.md COMMANDS.md -type f ! -path 'manifests/local_project_sha256.tsv' ! -path 'manifests/remote_project_sha256.tsv' -print0 | sort -z | xargs -0 sha256sum > manifests/local_project_sha256.tsv
```

## Leader-Run Remote Sync

These are documented for the leader; they were not run during package creation.

```bash
ssh.exe -o BatchMode=yes node1 "mkdir -p /data/qlyu/projects/pvrig_v2_5_pose_batch"

( cd /mnt/d/work/抗体/docking/candidates/v2_5_pose_batch && tar -cf - inputs scripts manifests haddock3 README.md COMMANDS.md ) | \
  ssh.exe -o BatchMode=yes node1 "cd /data/qlyu/projects/pvrig_v2_5_pose_batch && tar -xf -"
```

## Remote Monomer + Sequence/Geometry QC Only

Default runner mode builds NanoBodyBuilder2 monomers, validates sequence, runs geometry QC, copies per-candidate HADDOCK-ready assets, then stops before HADDOCK3.

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20 node1 \
  'cd /data/qlyu/projects/pvrig_v2_5_pose_batch && V2_5_CUDA_DEVICES=1 V2_5_NBB2_THREADS=4 bash scripts/run_node1_v2_5_pose_batch.sh'
```

## Separately Gated HADDOCK3 Step

Only run after reviewing monomer sequence/geometry QC outputs. The script checks the 1-minute load average before each candidate and exits with refusal when it exceeds `V2_5_MAX_LOAD1`.

```bash
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20 node1 \
  'cd /data/qlyu/projects/pvrig_v2_5_pose_batch && V2_5_RUN_HADDOCK3=1 V2_5_MAX_LOAD1=32 bash scripts/run_node1_v2_5_pose_batch.sh'
```

## Sync Evidence Back

```bash
mkdir -p /mnt/d/work/抗体/docking/candidates/v2_5_pose_batch/remote_sync
ssh.exe -o BatchMode=yes node1 \
  "cd /data/qlyu/projects/pvrig_v2_5_pose_batch && tar -cf - inputs scripts manifests logs reports monomer haddock3" | \
  tar -xf - -C /mnt/d/work/抗体/docking/candidates/v2_5_pose_batch/remote_sync
```

## Claim Boundary

Treat all outputs as `computational_pose_qc_proxy_not_binding_or_blocker_proof`; do not report them as binding or blocker validation.
