#!/usr/bin/env python3
"""Build immutable nonlaunching V2.5 ORTHO 5x5 nested job package."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil
from collections import Counter
from pathlib import Path

LANES=("B_CLEAN_TARGET_ATTENTION","E_DECOUPLED_CONTACT_DETACHED","E_DECOUPLED_CONTACT_SHARED")
HP=("H0","H1","H2"); SEEDS=(43,97,193); GPUS=(1,2,4,5)
PYTHON='/data1/qlyu/software/envs/pvrig-v6-tc/bin/python'
V23='/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718'
V24='/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718'
MODEL='/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c'
MODEL_SHA='a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0'
ADAPTER_SHA='59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f'
class E(RuntimeError):pass
def req(x,m):
 if not x: raise E(m)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def dump(p,x): Path(p).write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
def common(pkg,rt,strict,key,lane,out,split,job_id,phase,outer,inner=None,h=None,selection=None,seed=43):
 inner_key='_'.join(key.split('_')[:4]) if '_inner_' in key else key
 is_inner='_inner_' in key
 training=f'{strict}/inputs/split_training/{key}.tsv'
 if is_inner:
  marginal=f'{strict}/inputs/split_contacts/{key}.marginal.tsv.gz'; pair=f'{strict}/inputs/split_contacts/{key}.pair.tsv.gz'; graph=f'{strict}/inputs/split_graphs/{key}'
 else:
  marginal=f'{V24}/inputs/adaptive_contacts/v6_dual_source_adaptive_multiseed_marginal_targets_v2.tsv.gz'; pair=f'{V24}/inputs/adaptive_contacts/v6_dual_source_adaptive_multiseed_pair_targets_v2.tsv.gz'; graph='/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs'
 c=[PYTHON,f'{pkg}/formal_nested/run_formal_split_v1.py','--job-id',job_id,'--phase',phase,'--outer-fold',str(outer),'--lane-variant',lane,'--seed',str(seed),'--output-dir',out,'--materialized-split-dir',f'{rt}/materialized_splits','--base-runner',f'{pkg}/real1507/run_real1507_split_v1.py','--source-split-manifest',split,'--v2-4-adapter-path',f'{V24}/src/train_v2_4_base_split.py','--expected-v2-4-adapter-sha256',ADAPTER_SHA,'--v2-3-bundle-root',V23,'--training-tsv',training,'--contact-tsv-gz',marginal,'--pair-contact-tsv-gz',pair,'--graph-cache-dir',graph,'--target-graph-pt','/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt','--contact-formula-json',f'{strict}/inputs/contact_score_formula_v1.json','--model-path',MODEL,'--model-identity-file',f'{MODEL}/model.safetensors','--expected-model-sha256',MODEL_SHA,'--device','cuda']
 if inner is not None:c+=['--inner-fold',str(inner)]
 if h:c+=['--hparam-id',h]
 if selection:c+=['--selection-json',selection]
 return c
def build_graph(pkg,rt,strict):
 jobs=[]; gpu_idx=0; inner_dirs={}; selections={}; ensembles=[]
 def add(job): jobs.append(job)
 for o in range(5):
  for lane in LANES:
   lane_inputs=[]
   for h in HP:
    for i in range(5):
     key=f'outer_{o}_inner_{i}'; jid=f'o{o}.{lane}.{h}.i{i}.train'; out=f'{rt}/inner/{lane}/{h}/outer_{o}/inner_{i}'; split=f'{strict}/plan/trainer_splits/{key}.json'; gpu=GPUS[gpu_idx%4];gpu_idx+=1
     cmd=common(pkg,rt,strict,key,lane,out,split,jid,'inner',o,inner=i,h=h,seed=43)
     add({'job_id':jid,'kind':'GPU_INNER','lane':lane,'hparam_id':h,'outer_fold':o,'inner_fold':i,'seed':43,'physical_gpu':gpu,'dependencies':[],'command':cmd,'output_dir':out,'expected_result':f'{out}/RESULT.json'}); lane_inputs.append(out); inner_dirs[(o,lane,h,i)]=out
   sj=f'o{o}.{lane}.inner_select'; sout=f'{rt}/selection/{lane}/outer_{o}'; cmd=[PYTHON,f'{pkg}/formal_nested/formal_metrics_v1.py','select','--job-id',sj,'--lane',lane,'--outer-fold',str(o),'--output-dir',sout]
   deps=[]
   for h in HP:
    for i in range(5): cmd+=['--input-dir',inner_dirs[(o,lane,h,i)]]; deps.append(f'o{o}.{lane}.{h}.i{i}.train')
   add({'job_id':sj,'kind':'CPU_SELECT','lane':lane,'outer_fold':o,'dependencies':deps,'command':cmd,'output_dir':sout,'expected_result':f'{sout}/RESULT.json'}); selections[(o,lane)]=f'{sout}/SELECTION.json'
   outerdirs=[]; outerdeps=[]
   for seed in SEEDS:
    jid=f'o{o}.{lane}.s{seed}.outer_refit'; out=f'{rt}/outer/{lane}/outer_{o}/seed_{seed}'; split=f'{strict}/plan/trainer_splits/outer_{o}.json'; gpu=GPUS[gpu_idx%4];gpu_idx+=1
    cmd=common(pkg,rt,strict,f'outer_{o}',lane,out,split,jid,'outer',o,selection=selections[(o,lane)],seed=seed)
    add({'job_id':jid,'kind':'GPU_OUTER_REFIT','lane':lane,'outer_fold':o,'seed':seed,'physical_gpu':gpu,'dependencies':[sj],'command':cmd,'output_dir':out,'expected_result':f'{out}/RESULT.json'}); outerdirs.append(out); outerdeps.append(jid)
   ej=f'o{o}.{lane}.outer_ensemble'; eout=f'{rt}/outer_eval/{lane}/outer_{o}'; cmd=[PYTHON,f'{pkg}/formal_nested/formal_metrics_v1.py','ensemble','--job-id',ej,'--output-dir',eout]
   for d in outerdirs:cmd+=['--input-dir',d]
   add({'job_id':ej,'kind':'CPU_OUTER_ENSEMBLE_EVAL','lane':lane,'outer_fold':o,'dependencies':outerdeps,'command':cmd,'output_dir':eout,'expected_result':f'{eout}/RESULT.json'}); ensembles.append((ej,eout))
 final='formal_open_outer.collect'; fout=f'{rt}/final';cmd=[PYTHON,f'{pkg}/formal_nested/formal_metrics_v1.py','collect','--job-id',final,'--output-dir',fout]
 for _,d in ensembles:cmd+=['--input-dir',d]
 add({'job_id':final,'kind':'CPU_FINAL_COLLECT','dependencies':[x for x,_ in ensembles],'command':cmd,'output_dir':fout,'expected_result':f'{fout}/RESULT.json'})
 counts=Counter(j['kind'] for j in jobs); req(len(jobs)==301 and counts==Counter({'GPU_INNER':225,'GPU_OUTER_REFIT':45,'CPU_SELECT':15,'CPU_OUTER_ENSEMBLE_EVAL':15,'CPU_FINAL_COLLECT':1}),'dag_counts')
 return {'schema_version':'pvrig_v2_5_ortho_formal_nested_job_graph_v1','status':'FROZEN_NONLAUNCHING','execution_authorized':False,'training_or_prediction_executed':False,'claim_boundary':'computational dual-receptor docking geometry surrogate only','resources':{'physical_gpu_allowlist':list(GPUS),'max_gpu_jobs':4,'max_cpu_jobs':2,'cpu_threads_per_job':4},'job_counts':dict(counts)|{'GPU_TOTAL':270,'CPU_TOTAL':31,'TOTAL':301},'v4_f_test32_access_count':0,'jobs':jobs}
def input_bindings(strict_graph):
 j=json.loads(Path(strict_graph).read_text()); out=[]
 def take(x):
  if isinstance(x,dict):
   if 'node1_path' in x and 'sha256' in x:out.append({'path':x['node1_path'],'sha256':x['sha256']})
   for v in x.values():take(v)
  elif isinstance(x,list):
   for v in x:take(v)
 for k in ('canonical_inputs','split_training_inputs','split_contact_inputs','split_graph_inputs','split_manifests'):take(j[k])
 # Deduplicate exact path, requiring identical hash.
 d={}
 for x in out:
  if x['path'] in d:req(d[x['path']]==x['sha256'],'binding_hash_conflict')
  d[x['path']]=x['sha256']
 d['/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt']='59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc'
 d[f'{V24}/src/train_v2_4_base_split.py']=ADAPTER_SHA; d[f'{MODEL}/model.safetensors']=MODEL_SHA
 return [{'path':p,'sha256':d[p]} for p in sorted(d)]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--strict-bundle-local',type=Path,required=True);p.add_argument('--node-package-root',required=True);p.add_argument('--node-runtime-root',required=True);p.add_argument('--node-strict-root',required=True);a=p.parse_args()
 req(not a.output_root.exists(),'output_exists'); bundle=a.output_root/'node1_bundle'; (bundle/'formal_nested').mkdir(parents=True); (bundle/'model').mkdir();(bundle/'trainer').mkdir();(bundle/'real1507').mkdir();(bundle/'plan').mkdir();(bundle/'contracts').mkdir()
 for src,dst in [(a.source_root/'src/run_formal_split_v1.py',bundle/'formal_nested/run_formal_split_v1.py'),(a.source_root/'src/formal_metrics_v1.py',bundle/'formal_nested/formal_metrics_v1.py'),(a.source_root/'src/run_formal_job_graph_v1.py',bundle/'formal_nested/run_formal_job_graph_v1.py'),(a.source_root/'src/watch_prerequisites_then_launch_v1.py',bundle/'formal_nested/watch_prerequisites_then_launch_v1.py'),(a.source_root/'FORMAL_TRAINING_PLAN_ZH.md',bundle/'contracts/FORMAL_TRAINING_PLAN_ZH.md'),(a.source_root/'FORMAL_TRAINING_FREEZE_V1.json',bundle/'contracts/FORMAL_TRAINING_FREEZE_V1.json')]:shutil.copy2(src,dst)
 v25=a.source_root.parent/'v2_5_ortho_contact_pose_stack_v1_20260718'
 for rel in ('model/residue_model_v2_5_ortho.py','trainer/train_v2_5_ortho_heads.py','real1507/run_real1507_split_v1.py'):
  shutil.copy2(v25/rel,bundle/rel)
 strict_graph=a.strict_bundle_local/'plan/job_graph.json'; graph=build_graph(a.node_package_root+'/node1_bundle',a.node_runtime_root,a.node_strict_root);dump(bundle/'plan/job_graph.json',graph)
 bindings=input_bindings(strict_graph); dump(bundle/'contracts/EXTERNAL_INPUT_BINDINGS.json',{'schema_version':'pvrig_v2_5_external_input_bindings_v1','files':bindings,'count':len(bindings)})
 files={str(x.relative_to(bundle)):sha(x) for x in sorted(bundle.rglob('*')) if x.is_file()}; graph_sha=files['plan/job_graph.json']
 manifest={'schema_version':'pvrig_v2_5_ortho_formal_nested_nonlaunching_package_v1','status':'PASS_IMMUTABLE_NONLAUNCHING_PACKAGE_BUILT','launch_authorized':False,'training_or_prediction_executed':False,'node1_package_root':a.node_package_root,'node1_runtime_root':a.node_runtime_root,'node1_strict_root':a.node_strict_root,'job_graph_sha256':graph_sha,'job_count':301,'gpu_job_count':270,'cpu_job_count':31,'physical_gpus':list(GPUS),'external_input_binding_count':len(bindings),'files':files,'v4_f_test32_access_count':0}
 dump(a.output_root/'PACKAGE_MANIFEST.json',manifest); allfiles={str(x.relative_to(a.output_root)):sha(x) for x in sorted(a.output_root.rglob('*')) if x.is_file()}; (a.output_root/'SHA256SUMS').write_text(''.join(f'{h}  {p}\n' for p,h in sorted(allfiles.items())))
 print(json.dumps({'status':'PASS_NONLAUNCHING_PACKAGE_BUILT','job_graph_sha256':graph_sha,'jobs':301,'gpu_jobs':270,'cpu_jobs':31,'external_bindings':len(bindings)},sort_keys=True))
if __name__=='__main__':main()
