#!/usr/bin/env python3
"""Bounded fail-closed scheduler for frozen V2.5 formal nested DAG."""
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
def atomic(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name('.'+p.name+f'.{os.getpid()}.tmp');q.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');os.replace(q,p)
def valid_result(job):
 p=Path(job['expected_result'])
 if not p.is_file() or p.is_symlink():return False
 try:r=json.loads(p.read_text())
 except Exception:return False
 return str(r.get('status','')).startswith('PASS') and r.get('job_id')==job['job_id'] and r.get('v4_f_test32_access_count')==0
def main():
 p=argparse.ArgumentParser();p.add_argument('--job-graph',type=Path,required=True);p.add_argument('--expected-job-graph-sha256',required=True);p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--poll-seconds',type=float,default=2);a=p.parse_args()
 req(sha(a.job_graph)==a.expected_job_graph_sha256,'graph_hash');g=json.loads(a.job_graph.read_text());req(g['status']=='FROZEN_NONLAUNCHING' and not g['execution_authorized'],'graph_nonlaunch_contract');req(g['v4_f_test32_access_count']==0,'sealed_access')
 jobs={x['job_id']:x for x in g['jobs']};req(len(jobs)==301,'job_count');req(set(g['resources']['physical_gpu_allowlist'])=={1,2,4,5},'gpu_allowlist')
 # Explicit authorization occurs outside graph and must not mutate the graph.
 a.runtime_root.mkdir(parents=True,exist_ok=True);logs=a.runtime_root/'logs';logs.mkdir(exist_ok=True)
 completed={j for j,x in jobs.items() if valid_result(x)};pending=set(jobs)-completed;running={};failed=None
 atomic(a.runtime_root/'GRAPH_STATUS.json',{'status':'RUNNING_OR_RESUMING','completed':len(completed),'pending':len(pending),'running':0,'job_graph_sha256':a.expected_job_graph_sha256,'v4_f_test32_access_count':0})
 while pending or running:
  for jid,(proc,fh,gpu) in list(running.items()):
   rc=proc.poll()
   if rc is None:continue
   fh.close();del running[jid]
   if rc!=0 or not valid_result(jobs[jid]):failed={'job_id':jid,'returncode':rc,'valid_result':valid_result(jobs[jid])};break
   completed.add(jid)
  if failed:break
  active_gpus={gpu for _,_,gpu in running.values() if gpu is not None};active_cpu=sum(gpu is None for _,_,gpu in running.values())
  started=False
  for jid in sorted(pending):
   job=jobs[jid]
   if not set(job['dependencies'])<=completed:continue
   gpu=job.get('physical_gpu')
   if gpu is not None:
    if gpu in active_gpus or len(active_gpus)>=g['resources']['max_gpu_jobs']:continue
   elif active_cpu>=g['resources']['max_cpu_jobs']:continue
   out=Path(job['output_dir']);req(not out.exists(),f'output_exists_without_valid_result:{jid}')
   env=os.environ.copy();env.update({'OMP_NUM_THREADS':'4','MKL_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4'})
   if gpu is not None:env['CUDA_VISIBLE_DEVICES']=str(gpu)
   log=(logs/f'{jid}.log').open('ab',buffering=0);proc=subprocess.Popen(job['command'],stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
   running[jid]=(proc,log,gpu);pending.remove(jid);active_gpus.add(gpu) if gpu is not None else None;active_cpu+=gpu is None;started=True
  atomic(a.runtime_root/'GRAPH_STATUS.json',{'status':'RUNNING','completed':len(completed),'pending':len(pending),'running':len(running),'running_jobs':sorted(running),'job_graph_sha256':a.expected_job_graph_sha256,'v4_f_test32_access_count':0})
  if pending and not running and not started:
   blocked={j:sorted(set(jobs[j]['dependencies'])-completed) for j in sorted(pending)};failed={'job_id':'DAG_DEADLOCK','blocked':blocked};break
  if pending or running:time.sleep(a.poll_seconds)
 if failed:
  for proc,fh,_ in running.values():proc.terminate();fh.close()
  atomic(a.runtime_root/'TERMINAL.json',{'status':'FAIL','returncode':1,'failure':failed,'completed':len(completed),'job_graph_sha256':a.expected_job_graph_sha256,'v4_f_test32_access_count':0});return 1
 req(len(completed)==301 and valid_result(jobs['formal_open_outer.collect']),'terminal_closure')
 atomic(a.runtime_root/'TERMINAL.json',{'status':'PASS','returncode':0,'completed':301,'job_graph_sha256':a.expected_job_graph_sha256,'final_result':jobs['formal_open_outer.collect']['expected_result'],'v4_f_test32_access_count':0});return 0
if __name__=='__main__':raise SystemExit(main())
