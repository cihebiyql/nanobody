#!/usr/bin/env python3
"""Wait for strict/meta PASS terminals and idle GPUs, then hash-gated launch."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
class E(RuntimeError):pass
def req(x,m):
 if not x:raise E(m)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(Path(p).read_text())
def atomic(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name('.'+p.name+f'.{os.getpid()}.tmp');q.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');os.replace(q,p)
def inputs_pass(path):
 x=load(path)
 for f in x['files']:
  p=Path(f['path']);req(p.is_file() and not p.is_symlink(),f'external_missing:{p}');req(sha(p)==f['sha256'],f'external_hash:{p}')
def active_allowlisted_gpus():
 q=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True).stdout.strip().splitlines()
 if not q:return []
 m=subprocess.run(['nvidia-smi','--query-gpu=index,uuid','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True).stdout.splitlines(); uu={b.strip():int(a.strip()) for a,b in (x.split(',',1) for x in m)}
 return sorted({uu.get(x.split(',',1)[0].strip()) for x in q if uu.get(x.split(',',1)[0].strip()) in {1,2,4,5}})
def main():
 p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--watch-root',type=Path,required=True);p.add_argument('--strict-terminal',type=Path,required=True);p.add_argument('--meta-terminal',type=Path,required=True);p.add_argument('--authorization-overlay',type=Path,required=True);p.add_argument('--poll-seconds',type=int,default=60);a=p.parse_args()
 a.watch_root.mkdir(parents=True,exist_ok=True);status=a.watch_root/'WATCHER_STATUS.json';terminal=a.watch_root/'WATCHER_TERMINAL.json';poll=0
 manifest=load(a.package_root/'PACKAGE_MANIFEST.json');overlay=load(a.authorization_overlay);req(manifest['status']=='PASS_IMMUTABLE_NONLAUNCHING_PACKAGE_BUILT' and not manifest['launch_authorized'],'package_status');req(overlay.get('status')=='EXPLICITLY_AUTHORIZED_PENDING_PREREQUISITES' and overlay.get('execution_authorized') is True,'authorization')
 req(overlay['package_manifest_sha256']==sha(a.package_root/'PACKAGE_MANIFEST.json'),'authorization_binding');req(overlay['job_graph_sha256']==manifest['job_graph_sha256'],'graph_binding')
 while True:
  poll+=1
  if a.strict_terminal.exists():
   s=load(a.strict_terminal)
   if s.get('status')=='FAIL':atomic(terminal,{'status':'FAIL_CLOSED_STRICT_UPSTREAM','strict':s});return 1
  else:s=None
  if a.meta_terminal.exists():
   m=load(a.meta_terminal)
   if m.get('status')=='FAIL':atomic(terminal,{'status':'FAIL_CLOSED_META_UPSTREAM','meta':m});return 1
  else:m=None
  idle=[] if not (s and m) else active_allowlisted_gpus()
  ready=s=={'returncode':0,'status':'PASS'} and m.get('status')=='PASS' if m else False
  atomic(status,{'status':'READY_TO_HASH_VALIDATE' if ready and not idle else 'WAITING_PREREQUISITES','poll_count':poll,'strict_terminal_seen':s is not None,'meta_terminal_seen':m is not None,'active_allowlisted_gpus':idle,'v4_f_test32_access_count':0})
  if ready and not idle:break
  time.sleep(a.poll_seconds)
 req(not a.runtime_root.exists(),'runtime_root_exists_before_launch');inputs_pass(a.package_root/'node1_bundle/contracts/EXTERNAL_INPUT_BINDINGS.json')
 # Recheck package file closure after long wait.
 for rel,h in manifest['files'].items():req(sha(a.package_root/'node1_bundle'/rel)==h,f'package_hash:{rel}')
 scheduler=a.package_root/'node1_bundle/formal_nested/run_formal_job_graph_v1.py';cmd=['/data1/qlyu/software/envs/pvrig-v6-tc/bin/python',str(scheduler),'--job-graph',str(a.package_root/'node1_bundle/plan/job_graph.json'),'--expected-job-graph-sha256',manifest['job_graph_sha256'],'--runtime-root',str(a.runtime_root)]
 log=(a.watch_root/'scheduler.log').open('ab',buffering=0);proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 atomic(terminal,{'status':'PASS_SCHEDULER_LAUNCHED','pid':proc.pid,'command':cmd,'strict_terminal_sha256':sha(a.strict_terminal),'meta_terminal_sha256':sha(a.meta_terminal),'authorization_overlay_sha256':sha(a.authorization_overlay),'job_graph_sha256':manifest['job_graph_sha256'],'v4_f_test32_access_count':0});return 0
if __name__=='__main__':raise SystemExit(main())
