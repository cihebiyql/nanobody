#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,math,os,shutil,subprocess,sys
from pathlib import Path
PYTHON=Path('/data1/qlyu/software/envs/pvrig-v6-tc/bin/python')
AUTH_SHA='200192ca81a2da670716fbcdd5734d2c20c3f6ad6ca8d0ce0ca11a50b09492bb'
DRIVER_FREEZE_SHA='06def2d0f84f72a0dc81e59098884a3f307272599f9f0bb017de6120daf64778'
INTEGRATION_FREEZE_SHA='538abbcc495cd357b74880e6cef02626c7c969929ca891d566f99ab3e694b681'
TRAINER_SHA='036fb5f1d8b443bc3fd514ae6fe43970af42b6d078c378233f2825550b61d4e4'
DRIVER_SHA='a83e75f6662ab324dd1cfe65049be164f410dce06751022021c6c49bed27532c'
TRUST_SHA='2acf16069e3609a8160d9193818fa707a5105405e28354956f3431634756959e'
V25_TERMINAL=Path('/data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_runtime_v1_3_20260718/TERMINAL.json')
def req(c,m):
 if not c:raise RuntimeError(m)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def read(p):req(p.is_file() and not p.is_symlink(),f'not_regular:{p}');return json.loads(p.read_text())
def main():
 a=argparse.ArgumentParser();a.add_argument('--package-root',type=Path,required=True);a.add_argument('--runtime-root',type=Path,required=True);x=a.parse_args();root=x.package_root.resolve()
 files={root/'AUTHORIZATION_V1_2.json':AUTH_SHA,root/'DRIVER_FREEZE_V1_2.json':DRIVER_FREEZE_SHA,root/'vendor/integration/IMPLEMENTATION_FREEZE_V1_2.json':INTEGRATION_FREEZE_SHA,root/'vendor/integration/real1507_role_isolated_trainer_v1_2.py':TRAINER_SHA,root/'src/run_node1_cuda_smoke_v1_2.py':DRIVER_SHA,root/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json':TRUST_SHA}
 for p,h in files.items():req(p.is_file() and not p.is_symlink(),f'missing:{p}');req(sha(p)==h,f'hash:{p.name}')
 auth=read(root/'AUTHORIZATION_V1_2.json');req(auth['execution_authorized'] is True and auth['status']=='EXPLICITLY_AUTHORIZED_NODE1_CUDA_SMOKE','authorization');req(auth['v4_f_test32_access_count']==0,'authorization_v4f')
 term=read(V25_TERMINAL);req(term['status']=='PASS' and term['completed']==301 and term['returncode']==0,'v25_terminal');req(term['job_graph_sha256']==auth['v25_terminal_job_graph_sha256'],'v25_graph');req(term['v4_f_test32_access_count']==0,'v25_v4f')
 req(shutil.disk_usage('/data1').free>=100*(1024**3),'data1_free')
 q=subprocess.run(['nvidia-smi','--query-gpu=index,name,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True)
 row=[z for z in q.stdout.splitlines() if z.split(',')[0].strip()=='1'];req(len(row)==1,'gpu1_missing');f=[z.strip() for z in row[0].split(',')];req(f[1]=='NVIDIA GeForce RTX 4090' and float(f[2])<=128 and float(f[3])<=5,'gpu1_busy')
 req(str(x.runtime_root).startswith('/data1/qlyu/projects/') and not os.path.lexists(x.runtime_root),'runtime_path')
 env=os.environ.copy();env.update({'CUDA_VISIBLE_DEVICES':'1','OMP_NUM_THREADS':'8','MKL_NUM_THREADS':'8','OPENBLAS_NUM_THREADS':'8','NUMEXPR_NUM_THREADS':'8','TORCH_NUM_THREADS':'8'})
 cmd=[str(PYTHON),str(root/'src/run_node1_cuda_smoke_v1_2.py'),'--package-root',str(root),'--runtime-root',str(x.runtime_root),'--result',str(x.runtime_root/'SMOKE_RESULT.json')]
 done=subprocess.run(cmd,env=env,check=False);req(done.returncode==0,f'driver_rc:{done.returncode}')
 result=read(x.runtime_root/'SMOKE_RESULT.json');req(result['status']=='PASS' and result['precision']=='bf16','result');req(result['physical_gpu_index']==1 and result['logical_cuda_index']==0,'gpu_map');req(result['be_trajectory']['optimizer_steps']==20 and result['be_trajectory']['exact_scalar_trajectory_hash_match_every_step'] is True,'be');req(result['f_shared_gated']['post_lambda_budget_pass_every_step'] is True,'f');req(result['firewall']=={'v4_f_test32_access_count':0,'score_partition_truth_access_count':0,'outer_metrics_access_count':0,'candidate_docking_pose_input_count':0},'firewall')
 evidence=result['per_step_evidence_hashes'];req(all(len(v)==20 for v in evidence.values()) and len(evidence)==3,'step_evidence')
 for events in evidence.values():
  for e in events:req(all(isinstance(v,str) and len(v)==64 for v in e.values()),'step_hash')
 print(json.dumps({'status':'PASS','runtime_root':str(x.runtime_root),'result_sha256':sha(x.runtime_root/'SMOKE_RESULT.json')},sort_keys=True));return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print('FAIL_CLOSED:'+str(e),file=sys.stderr);raise SystemExit(2)
