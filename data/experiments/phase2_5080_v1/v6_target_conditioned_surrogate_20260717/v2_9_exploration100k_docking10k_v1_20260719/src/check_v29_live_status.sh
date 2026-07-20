#!/usr/bin/env bash
set -euo pipefail
MONO=/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720
PILOT=/data/qlyu/projects/pvrig_v29_pilot7_dual_docking_v1_20260720
FULL=/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720
TAIL=/data/qlyu/projects/pvrig_v29_monomers_tail4000_node23_v1_20260720
MID=/data/qlyu/projects/pvrig_v29_monomers_mid1000_node23_v1_20260720
echo '=== Node1 monomer ==='
ssh.exe node1 "cat '$MONO/full10k/status/PROGRESS.json'; ps -p \$(cat '$MONO/status/full10k.pid') -o pid,state,etime,cmd || true; ps -p \$(cat '$MONO/status/full_docking_waiter.pid') -o pid,state,etime,cmd || true; nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader"
echo '=== Node23 monomer tail + importer ==='
ssh.exe node23 "cat '$TAIL/run/status/PROGRESS.json'; ps -p \$(cat '$TAIL/status/run.pid') -o pid,state,etime,cmd || true; uptime"
ssh.exe node1 "cat '$MONO/full10k/status/NODE23_IMPORT_PROGRESS.json'; ps -p \$(cat '$MONO/status/node23_tail_importer.pid') -o pid,state,etime,cmd || true"
echo '=== Node23 monomer mid1000 chained acceleration ==='
ssh.exe node23 "if [ -f '$MID/run/status/PROGRESS.json' ]; then cat '$MID/run/status/PROGRESS.json'; else echo WAITING_FOR_TAIL4000_TERMINAL; fi; ps -p \$(cat '$MID/status/run.pid') -o pid,state,etime,cmd || true"
ssh.exe node1 "if [ -f '$MONO/full10k/status/NODE23_MID1000_IMPORT_PROGRESS.json' ]; then cat '$MONO/full10k/status/NODE23_MID1000_IMPORT_PROGRESS.json'; fi; ps -p \$(cat '$MONO/status/node23_mid1000_importer.pid') -o pid,state,etime,cmd || true"
echo '=== Pilot Docking ==='
ssh.exe node23 "python3 - <<'PY'
import collections, glob, json
root='$PILOT'; rows=[]
for path in glob.glob(root+'/status/jobs/*.json'):
    try: rows.append(json.load(open(path)))
    except Exception: pass
print({'states':dict(collections.Counter(row.get('status',row.get('state','')) for row in rows)),'results':len(glob.glob(root+'/results/*/job_result.json')),'jobs':len(rows)})
PY"
echo '=== Full Docking ==='
ssh.exe node23 "if [ -f '$FULL/status/LAUNCHED.json' ]; then cat '$FULL/status/LAUNCHED.json'; else echo WAITING_FOR_MONOMER_TERMINAL; fi"
ssh.exe node1 "if [ -f '$MONO/status/full_docking_launch_acceptance_waiter.pid' ]; then ps -p \$(cat '$MONO/status/full_docking_launch_acceptance_waiter.pid') -o pid,state,etime,cmd || true; fi; if [ -f '$FULL/status/LAUNCH_ACCEPTANCE.json' ]; then cat '$FULL/status/LAUNCH_ACCEPTANCE.json'; fi"
