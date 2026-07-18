#!/usr/bin/env python3
"""Synchronize label-free graph manifests with V1.2 frozen split candidates."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import shutil
from pathlib import Path

HERE=Path(__file__).resolve()
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path); v=importlib.util.module_from_spec(s); assert s and s.loader; s.loader.exec_module(v); return v
base=module('base121',HERE.with_name('build_v2_2_2_strict_nested_package_v1.py'))
auth=module('auth121',HERE.with_name('authorize_v2_2_2_strict_nested_package_v1.py'))
v12=module('v12_121',HERE.with_name('recover_authorized_v2_2_2_split_contacts_v1_2.py'))

OLD_PACKAGE=v12.NEW_PACKAGE; OLD_RUNTIME=v12.NEW_RUNTIME
NEW_PACKAGE='/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718'
NEW_RUNTIME='/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718'

def write_json(path,payload): path.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n')
def rewrite(value):
    if isinstance(value,str): return value.replace(OLD_PACKAGE,NEW_PACKAGE).replace(OLD_RUNTIME,NEW_RUNTIME)
    if isinstance(value,list): return [rewrite(x) for x in value]
    if isinstance(value,dict): return {k:rewrite(v) for k,v in value.items()}
    return value

def build(source:Path,output:Path)->dict:
    source,output=source.resolve(),output.resolve(); base.require(not output.exists(),f'output_exists:{output}'); base.require(v12.audit(source)['status']=='PASS_AUTHORIZED_V1_2_READY_FOR_PREOPTIMIZER_SMOKE','source_audit')
    try:
        shutil.copytree(source,output)
        runner=output/'node1_bundle/src'/base.RUNNER.name; shutil.copy2(base.RUNNER,runner)
        graph_path=output/'node1_bundle/plan/job_graph.json'; graph=rewrite(json.loads(graph_path.read_text())); graph['code_contracts']['runner']['path']=str(base.RUNNER); graph['code_contracts']['runner']['sha256']=base.sha256_file(runner)
        ready=base.load_json(base.READY); arts=ready['artifacts']; cache_src=Path(arts['vhh_graph_cache_npz']['source_path']); manifest_src=Path(arts['vhh_graph_manifest']['source_path']); receipt_src=Path(arts['vhh_graph_receipt']['source_path'])
        manifest_rows=base.read_tsv(manifest_src); columns=list(manifest_rows[0]); by_id={row['entity_id']:row for row in manifest_rows}; base.require(len(by_id)==1507,'global_graph_manifest_count')
        split_candidates={}
        for key,a in graph['split_training_inputs'].items():
            local=output/'node1_bundle/inputs/split_training'/Path(a['node1_path']).name; rows=base.read_tsv(local); split_candidates[key]={r['candidate_id'] for r in rows}
        graph_dir=output/'node1_bundle/inputs/split_graphs'; graph_dir.mkdir(parents=True); graph['split_graph_inputs']={}
        global_cache={'path':str(cache_src),'node1_path':arts['vhh_graph_cache_npz']['node1_path'],'sha256':arts['vhh_graph_cache_npz']['sha256']}
        global_manifest={'path':str(manifest_src),'node1_path':arts['vhh_graph_manifest']['node1_path'],'sha256':arts['vhh_graph_manifest']['sha256']}
        global_receipt={'path':str(receipt_src),'node1_path':arts['vhh_graph_receipt']['node1_path'],'sha256':arts['vhh_graph_receipt']['sha256']}
        for key,candidates in sorted(split_candidates.items()):
            if 'inner' not in key:
                graph['split_graph_inputs'][key]={'cache':global_cache,'manifest':global_manifest,'receipt':global_receipt,'candidates':1507,'filter_semantics':'canonical full graph cache for outer split'}; continue
            directory=graph_dir/key; directory.mkdir(); cache=directory/'graph_cache_v2.npz'
            try: os.link(cache_src,cache)
            except OSError: shutil.copy2(cache_src,cache)
            rows=[row for row in manifest_rows if row['entity_id'] in candidates]; base.require({r['entity_id'] for r in rows}==candidates,f'graph_manifest_candidate_closure:{key}')
            manifest=directory/'graph_manifest_v2.tsv'
            with manifest.open('x',newline='',encoding='utf-8') as h:
                w=csv.DictWriter(h,fieldnames=columns,delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(rows)
            receipt=json.loads(receipt_src.read_text()); receipt['counts']['entities']=len(rows); receipt['outputs']['graph_cache_v2.npz']=base.sha256_file(cache); receipt['outputs']['graph_manifest_v2.tsv']=base.sha256_file(manifest); receipt['subset_contract']={'source_cache_sha256':arts['vhh_graph_cache_npz']['sha256'],'candidate_filter':'frozen split train U score','label_or_feature_values_changed':False}
            receipt_path=directory/'graph_cache_receipt_v2.json'; write_json(receipt_path,receipt)
            node_dir=Path(NEW_PACKAGE)/'inputs/split_graphs'/key
            graph['split_graph_inputs'][key]={
                'cache':{'path':str(cache),'node1_path':str(node_dir/cache.name),'sha256':base.sha256_file(cache)},
                'manifest':{'path':str(manifest),'node1_path':str(node_dir/manifest.name),'sha256':base.sha256_file(manifest)},
                'receipt':{'path':str(receipt_path),'node1_path':str(node_dir/receipt_path.name),'sha256':base.sha256_file(receipt_path)},
                'candidates':len(candidates),'filter_semantics':'same canonical NPZ arrays plus frozen-split manifest subset; no feature values changed'
            }
        split_by_manifest={a['node1_path']:k for k,a in graph['split_manifests'].items()}
        for job in [j for j in graph['jobs'] if j['kind'].startswith('GPU_')]:
            key=split_by_manifest[job['split_manifest']]; bundle=graph['split_graph_inputs'][key]; command=job['command']; command[command.index('--graph-cache-dir')+1]=str(Path(bundle['cache']['node1_path']).parent)
        jobs=[j for j in graph['jobs'] if j['kind'].startswith('GPU_')]; base.require(len(graph['jobs'])==195 and len(jobs)==90,'jobs'); base.require({j['physical_gpu'] for j in jobs}=={2,4,5},'gpus')
        graph['recovery_contract']={'schema_version':'pvrig_v2_4_v2_2_2_split_synchronous_training_contacts_graphs_recovery_v1_2_1','reason':'V1.2 real pre-optimizer smoke graph_candidate_exact_closure','trainer_changed':False,'split_membership_changed':False,'label_or_graph_feature_values_changed':False,'model_or_hyperparameter_changed':False,'lane_weights_changed':False,'training_marginal_pair_graph_candidate_closure':True,'graph_subset_semantics':'canonical NPZ arrays unchanged; manifest and receipt subset to frozen split candidates','failed_runtimes':[auth.NODE1_RUNTIME_ROOT,v12.v11.NEW_RUNTIME],'failed_smoke_root':'/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_smoke_v1_2_20260718'}
        write_json(graph_path,graph); graph_sha=base.sha256_file(graph_path); receipt_path=output/'node1_bundle/plan/receipt.json'; receipt=json.loads(receipt_path.read_text()); receipt['job_graph_path']=str(Path(NEW_PACKAGE)/'plan/job_graph.json'); receipt['job_graph_sha256']=graph_sha; write_json(receipt_path,receipt)
        overlay_path=output/'contracts/EXPLICIT_AUTHORIZATION_OVERLAY.json'; overlay=json.loads(overlay_path.read_text()); overlay['schema_version']='pvrig_v2_4_v2_2_2_strict_nested_explicit_authorization_recovery_v1_2_1'; overlay['recovery_scope']=graph['recovery_contract']; overlay['node1_package_root']=NEW_PACKAGE; overlay['node1_runtime_root']=NEW_RUNTIME; write_json(overlay_path,overlay)
        launcher=output/'node1_bundle/src/launch_authorized_strict_nested_v1.py'; text=auth.launcher_source(graph_sha,base.sha256_file(runner),base.sha256_file(overlay_path)).replace(auth.NODE1_PACKAGE_ROOT,NEW_PACKAGE).replace(auth.NODE1_RUNTIME_ROOT,NEW_RUNTIME); launcher.write_text(text); launcher.chmod(0o755)
        manifest_path=output/'PACKAGE_MANIFEST.json'; m=json.loads(manifest_path.read_text()); m['schema_version']='pvrig_v2_4_v2_2_2_strict_nested_authorized_recovery_package_v1_2_1'; m['status']='PASS_AUTHORIZED_FULL_SPLIT_INPUT_CLOSURE_AUDITED_READY_TO_SMOKE'; m['node1_package_root']=NEW_PACKAGE; m['node1_runtime_root']=NEW_RUNTIME; m['job_graph']={'relative_path':'node1_bundle/plan/job_graph.json','sha256':graph_sha,'job_count':195,'gpu_job_count':90,'cpu_job_count':105,'physical_gpus':[2,4,5]}; m['authorization_overlay_sha256']=base.sha256_file(overlay_path); m['launcher']={'relative_path':'node1_bundle/src/launch_authorized_strict_nested_v1.py','sha256':base.sha256_file(launcher)}; m['recovery_contract']=graph['recovery_contract']; m['split_graph_input_count']=30; m['filtered_inner_graph_input_count']=25; m['source_failed_smoke']='/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_smoke_v1_2_20260718/SMOKE_FAILURE.json'; write_json(manifest_path,m)
        sums=output/'SHA256SUMS'; files=sorted(p for p in output.rglob('*') if p.is_file() and p!=sums)
        with sums.open('w') as h:
            for p in files: h.write(f'{base.sha256_file(p)}  {p.relative_to(output)}\n')
        return m
    except Exception: shutil.rmtree(output,ignore_errors=True); raise

def audit(root:Path)->dict:
    root=root.resolve(); checked=0
    for line in (root/'SHA256SUMS').read_text().splitlines():
        expected,rel=line.split('  ',1); p=root/rel; base.require(p.is_file() and not p.is_symlink() and base.sha256_file(p)==expected,f'hash:{rel}'); checked+=1
    m=json.loads((root/'PACKAGE_MANIFEST.json').read_text()); g=json.loads((root/'node1_bundle/plan/job_graph.json').read_text()); base.require(m['status']=='PASS_AUTHORIZED_FULL_SPLIT_INPUT_CLOSURE_AUDITED_READY_TO_SMOKE','status'); base.require(g['execution_authorized'] is True and len(g['jobs'])==195,'graph'); base.require(len(g['split_training_inputs'])==len(g['split_contact_inputs'])==len(g['split_graph_inputs'])==30,'split_inputs'); base.require(g['sealed_evaluation_access_count']==g['prediction_metrics_access_count']==0,'sealed')
    return {'status':'PASS_AUTHORIZED_V1_2_1_READY_FOR_REAL_PREOPTIMIZER_SMOKE','checked_file_count':checked,'job_count':195,'gpu_job_count':90,'cpu_job_count':105,'split_training_input_count':30,'split_contact_input_count':30,'split_graph_input_count':30,'physical_gpus':[2,4,5],'sealed_evaluation_access_count':0}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--source-v1-2-package',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args(); m=build(a.source_v1_2_package,a.output_dir); print(json.dumps({'status':m['status'],'job_graph_sha256':m['job_graph']['sha256'],'node1_package_root':m['node1_package_root'],'node1_runtime_root':m['node1_runtime_root']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
