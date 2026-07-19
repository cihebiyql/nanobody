#!/usr/bin/env python3
"""Independent static audit for V2.5 formal nested nonlaunching package."""
import argparse,hashlib,json
from collections import Counter
from pathlib import Path
class E(RuntimeError):pass
def req(x,m):
 if not x:raise E(m)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);a=p.parse_args();m=json.loads((a.package_root/'PACKAGE_MANIFEST.json').read_text());b=a.package_root/'node1_bundle'
 req(m['status']=='PASS_IMMUTABLE_NONLAUNCHING_PACKAGE_BUILT' and not m['launch_authorized'] and not m['training_or_prediction_executed'],'manifest_nonlaunch')
 for rel,h in m['files'].items():req(sha(b/rel)==h,f'hash:{rel}')
 g=json.loads((b/'plan/job_graph.json').read_text());req(sha(b/'plan/job_graph.json')==m['job_graph_sha256'],'graph_hash');req(g['status']=='FROZEN_NONLAUNCHING' and not g['execution_authorized'],'graph_status')
 jobs=g['jobs'];req(len(jobs)==301 and len({x['job_id'] for x in jobs})==301,'job_ids');c=Counter(x['kind'] for x in jobs);req(c==Counter({'GPU_INNER':225,'GPU_OUTER_REFIT':45,'CPU_SELECT':15,'CPU_OUTER_ENSEMBLE_EVAL':15,'CPU_FINAL_COLLECT':1}),'counts')
 req(set(g['resources']['physical_gpu_allowlist'])=={1,2,4,5} and g['resources']['max_gpu_jobs']==4,'gpu_contract')
 forbidden=('v4_f','test32','--structure-dim','--ridge-alpha')
 for x in jobs:
  text=' '.join(x['command']).lower();req(not any(v in text for v in forbidden),'forbidden_command');req(x['expected_result'].startswith(m['node1_runtime_root']+'/'),'runtime_scope');req((m['node1_package_root']+'/node1_bundle/') in ' '.join(x['command']),'bundle_command_scope')
  if x['kind'].startswith('GPU_'):req(x['physical_gpu'] in {1,2,4,5} and '--device' in x['command'],'gpu_job')
  if x['kind']=='GPU_INNER':req('--hparam-id' in x['command'] and x['seed']==43,'inner_contract')
  if x['kind']=='GPU_OUTER_REFIT':req('--selection-json' in x['command'] and x['seed'] in {43,97,193},'outer_contract')
 req(g['v4_f_test32_access_count']==0 and m['v4_f_test32_access_count']==0,'sealed_count')
 print(json.dumps({'status':'PASS_IMMUTABLE_NONLAUNCHING_PACKAGE_AUDIT','jobs':301,'gpu_jobs':270,'cpu_jobs':31,'job_graph_sha256':m['job_graph_sha256'],'external_bindings':m['external_input_binding_count']},sort_keys=True))
if __name__=='__main__':main()
