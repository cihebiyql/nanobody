#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,math,os,shutil,subprocess,sys
from pathlib import Path
PYTHON=Path('/data1/qlyu/software/envs/pvrig-v6-tc/bin/python')
AUTH_SHA='7fae10df0821f197ad316e2a177dfce10ce2955c63e173e32c6757055437dc73'
DRIVER_FREEZE_SHA='7e93f3bb190fb62f97fc465e1480f5a32df93a4b5254a997f23d923beb03ec20'
INTEGRATION_FREEZE_SHA='e73335c32e8495d609f9b5e6379ba648d1c38e4da49c40088468eae7308e3faa'
TRAINER_SHA='e99146be166cab7f703bd6cbcad3594e196d7a155c422459cb16f8cbfc2b6a24'
DRIVER_SHA='3513a28ca3e7ad3e1051567105d7308ebcccef2db82e50c3bbccb015e637ed9f'
TRUST_SHA='2acf16069e3609a8160d9193818fa707a5105405e28354956f3431634756959e'
V25_TERMINAL=Path('/data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_runtime_v1_3_20260718/TERMINAL.json')
V25_SOURCE_ROOT=Path('/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_2_20260718/src')
V25_SOURCE_HASHES={'run_real1507_split_v1.py':'f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f','train_v2_5_ortho_heads.py':'af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0','residue_model_v2_5_ortho.py':'26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521'}
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
 files={root/'AUTHORIZATION_V1_3_1.json':AUTH_SHA,root/'DRIVER_FREEZE_V1_3_1.json':DRIVER_FREEZE_SHA,root/'vendor/integration/IMPLEMENTATION_FREEZE_V1_3.json':INTEGRATION_FREEZE_SHA,root/'vendor/integration/real1507_role_isolated_trainer_v1_3.py':TRAINER_SHA,root/'src/run_node1_cuda_smoke_v1_3_1.py':DRIVER_SHA,root/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json':TRUST_SHA}
 for p,h in files.items():req(p.is_file() and not p.is_symlink(),f'missing:{p}');req(sha(p)==h,f'hash:{p.name}')
 for name,h in V25_SOURCE_HASHES.items():
  p=V25_SOURCE_ROOT/name;req(p.is_file() and not p.is_symlink(),f'v25_source_missing:{name}');req(sha(p)==h,f'v25_source_hash:{name}')
 auth=read(root/'AUTHORIZATION_V1_3_1.json');req(auth['execution_authorized'] is True and auth['status']=='EXPLICITLY_AUTHORIZED_NODE1_CUDA_SMOKE','authorization');req(auth['v4_f_test32_access_count']==0,'authorization_v4f')
 term=read(V25_TERMINAL);req(term['status']=='PASS' and term['completed']==301 and term['returncode']==0,'v25_terminal');req(term['job_graph_sha256']==auth['v25_terminal_job_graph_sha256'],'v25_graph');req(term['v4_f_test32_access_count']==0,'v25_v4f')
 req(shutil.disk_usage('/data1').free>=100*(1024**3),'data1_free')
 q=subprocess.run(['nvidia-smi','--query-gpu=index,name,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True)
 row=[z for z in q.stdout.splitlines() if z.split(',')[0].strip()=='1'];req(len(row)==1,'gpu1_missing');f=[z.strip() for z in row[0].split(',')];req(f[1]=='NVIDIA GeForce RTX 4090' and float(f[2])<=128 and float(f[3])<=5,'gpu1_busy')
 req(str(x.runtime_root).startswith('/data1/qlyu/projects/') and not os.path.lexists(x.runtime_root),'runtime_path')
 env=os.environ.copy();env.update({'CUDA_VISIBLE_DEVICES':'1','OMP_NUM_THREADS':'8','MKL_NUM_THREADS':'8','OPENBLAS_NUM_THREADS':'8','NUMEXPR_NUM_THREADS':'8','TORCH_NUM_THREADS':'8','CUBLAS_WORKSPACE_CONFIG':':4096:8'})
 cmd=[str(PYTHON),str(root/'src/run_node1_cuda_smoke_v1_3_1.py'),'--package-root',str(root),'--runtime-root',str(x.runtime_root),'--result',str(x.runtime_root/'SMOKE_RESULT.json')]
 done=subprocess.run(cmd,env=env,check=False);req(done.returncode==0,f'driver_rc:{done.returncode}')
 result=read(x.runtime_root/'SMOKE_RESULT.json');req(result['status']=='PASS' and result['precision']=='bf16','result');req(result['physical_gpu_index']==1 and result['logical_cuda_index']==0,'gpu_map');req(result['be_trajectory']['optimizer_steps']==20 and result['be_trajectory']['exact_scalar_trajectory_hash_match_every_step'] is True,'be');req(result['f_shared_gated']['post_lambda_budget_pass_every_step'] is True,'f');req(result['firewall']=={'v4_f_test32_access_count':0,'score_partition_truth_access_count':0,'outer_metrics_access_count':0,'candidate_docking_pose_input_count':0},'firewall')
 evidence=result['per_step_evidence_hashes'];req(all(len(v)==20 for v in evidence.values()) and len(evidence)==3,'step_evidence')
 for events in evidence.values():
  for e in events:req(all(isinstance(v,str) and len(v)==64 for v in e.values()),'step_hash')
 print(json.dumps({'status':'PASS','runtime_root':str(x.runtime_root),'result_sha256':sha(x.runtime_root/'SMOKE_RESULT.json')},sort_keys=True));return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print('FAIL_CLOSED:'+str(e),file=sys.stderr);raise SystemExit(2)
