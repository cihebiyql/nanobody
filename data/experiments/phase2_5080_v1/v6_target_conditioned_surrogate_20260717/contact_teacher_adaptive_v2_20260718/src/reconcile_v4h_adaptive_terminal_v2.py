#!/usr/bin/env python3
"""Build an immutable sidecar reconciliation for the V4-H adaptive terminal.

This reads manifests, rankings, terminal/status metadata, and job_result JSON only.
It never opens pose coordinates and never mutates the canonical campaign root.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,stat
from collections import Counter
from pathlib import Path
from typing import Any,Mapping

SCHEMA_VERSION='pvrig_v6_v4h_adaptive_terminal_reconciliation_v2'
ROOT_EXPECTED='/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717'
RECEPTORS=('8x6b','9e6y'); SEEDS=(917,1931,3253)
MANIFESTS={917:'manifests/stage1_all_seed917.tsv',1931:'manifests/stage2_selected_seed1931.tsv',3253:'manifests/stage3_selected_seed3253.tsv'}
CANDIDATES='inputs/candidates_290.tsv'; FINAL='release/final_adaptive_seed_ranking.tsv'
STAGE2='release/stage2_seed917_1931_ranking.tsv'; UPSTREAM='release/ADAPTIVE_DOCKING_RECEIPT.json'
EXPECTED_HASHES={
 CANDIDATES:'220926f45bca69464588b8eebcb8855d3235876ab98e0840d2e374bf94cdeec0',
 MANIFESTS[917]:'c76de07a2725939e62b4fab9cd9af4a7c72b30398f68bfa18727a223f277c1d0',
 MANIFESTS[1931]:'0b07ace3fd233db1980143dd174ffd6a0b67c3d6a92462c009f4437d2b74ae15',
 MANIFESTS[3253]:'759eace448be5c2ace4b745139d2cc53fd2d2864ea756f751d7efdda35772113',
 STAGE2:'7c3768d52128770765df7db3c51cb4d32bcff905dbfc91b09bea04b17772ce85',
 FINAL:'144da9b8ce2a25db73813df2e23c1f48f9bebca8f565e50b15e4c1670e8c040e',
 UPSTREAM:'03c52f1011087276ca04fe54d8afe869fef7f2dbd30ae69ae52e7647a20d9941',
}
EXPECTED_MANIFEST_ROWS={917:2640,1931:768,3253:256}
EXPECTED_TIERS={'DUAL_1_SEED':917,'DUAL_2_SEED':241,'DUAL_3_SEED':123,'TECHNICAL_INCOMPLETE':39}
EXPECTED_TERMINALS={917:{'SUCCESS':2636,'FAILED_MAX_ATTEMPTS':4},1931:{'SUCCESS':768},3253:{'SUCCESS':255,'FAILED_MAX_ATTEMPTS':1}}
TIER_N={'DUAL_1_SEED':1,'DUAL_2_SEED':2,'DUAL_3_SEED':3,'TECHNICAL_INCOMPLETE':0}
CLAIM='Sidecar reconciliation of adaptive docking terminal metadata and job-result identity only; no pose coordinates opened; not biological truth or Docking Gold.'
class ReconciliationError(RuntimeError):pass
def req(x,m):
 if not x:raise ReconciliationError(m)
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def regular_bytes(path,label):
 try:s=path.lstat()
 except FileNotFoundError as e:raise ReconciliationError(f'missing:{label}:{path}') from e
 req(stat.S_ISREG(s.st_mode),f'not_regular_or_symlink:{label}:{path}');return path.read_bytes()
def rows(path,label):
 raw=regular_bytes(path,label)
 text=raw.decode('utf-8-sig').splitlines()
 reader=csv.DictReader(text,delimiter='\t');out=list(reader);req(reader.fieldnames,f'header:{label}');return raw,out
def seedset(v):return {int(x) for x in v.split(',') if x}
def within(path,root):
 try:path.relative_to(root);return True
 except ValueError:return False
def atomic(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f'.{path.name}.{os.getpid()}.tmp')
 with tmp.open('xb') as f:f.write((json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n').encode());f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
def reconcile(root:Path,output:Path)->dict[str,Any]:
 root=root.resolve();output=output.resolve();req(str(root)==ROOT_EXPECTED,'canonical_root');req(root.is_dir() and not root.is_symlink(),'root_missing_or_symlink')
 req(not output.exists() and not output.is_symlink(),'output_exists');req(not within(output,root),'output_inside_source')
 actual={}
 loaded={}
 for rel,expected in EXPECTED_HASHES.items():
  raw=regular_bytes(root/rel,rel);observed=sha_bytes(raw);req(observed==expected,f'hash:{rel}');actual[rel]={'sha256':observed,'size_bytes':len(raw)}
  if rel.endswith('.tsv'):
   _r,rs=rows(root/rel,rel);actual[rel]['rows']=len(rs);loaded[rel]=rs
 upstream=json.loads(regular_bytes(root/UPSTREAM,UPSTREAM));req(isinstance(upstream,dict),'upstream_object')
 declared=str(upstream.get('final_ranking_sha256',''))
 req(declared==EXPECTED_HASHES[FINAL],'upstream_final_ranking_hash_mismatch')
 req(declared!=EXPECTED_HASHES[STAGE2],'upstream_final_ranking_hash_matches_stage2')
 candidates=loaded[CANDIDATES];ranking=loaded[FINAL]
 req(len(candidates)==1320 and len(ranking)==1320,'candidate_or_ranking_count')
 cids={r['candidate_id'] for r in candidates};req(len(cids)==1320,'candidate_duplicate');req(cids=={r['candidate_id'] for r in ranking},'candidate_ranking_closure')
 tier_counts=Counter(r['docking_evidence_tier'] for r in ranking);req(dict(tier_counts)==EXPECTED_TIERS,f'tiers:{dict(tier_counts)}')
 jobs={};stage_job_counts={}
 for seed,rel in MANIFESTS.items():
  rs=loaded[rel];req(len(rs)==EXPECTED_MANIFEST_ROWS[seed],f'manifest_rows:{seed}');stage_job_counts[str(seed)]=len(rs)
  for r in rs:
   req(int(r['seed'])==seed and r['conformation'] in RECEPTORS,'job_seed_or_receptor')
   key=(r['entity_id'],r['conformation'],seed);req(key not in jobs,f'duplicate_job:{key}');jobs[key]=r
 paired={};asym_valid=[];asym_all=[];selected_keys=[]
 for r in ranking:
  left=seedset(r['successful_seed_ids_8X6B']);right=seedset(r['successful_seed_ids_9E6Y']);common=tuple(sorted(left&right));tier=r['docking_evidence_tier']
  req(len(common)==TIER_N[tier],f'paired_seed_count:{r["candidate_id"]}');req(common==SEEDS[:len(common)],f'paired_seed_order:{r["candidate_id"]}')
  paired[r['candidate_id']]=common
  if left!=right:
   asym_all.append(r['candidate_id'])
   if tier!='TECHNICAL_INCOMPLETE':asym_valid.append(r['candidate_id'])
  if tier!='TECHNICAL_INCOMPLETE':
   for seed in common:
    for receptor in RECEPTORS:
     key=(r['candidate_id'],receptor,seed);req(key in jobs,f'selected_manifest_missing:{key}');selected_keys.append(key)
 req(len(selected_keys)==3536,'selected_common_jobs');req(len(asym_valid)==25,'valid_asymmetry_count');req(len(asym_all)==64,'all_asymmetry_count')
 states=Counter();missing=[];missing_status_bad=[];identity_bad=[];selected_missing=[];selected_bad=[];selected_inventory=[]
 selected_set=set(selected_keys)
 for key,job in sorted(jobs.items(),key=lambda item:item[1]['job_id']):
  p=root/'results'/job['job_id']/'job_result.json'
  if not p.is_file():
   missing.append(job['job_id']);
   status_path=root/'status/jobs'/f"{job['job_id']}.json"
   try:status_payload=json.loads(regular_bytes(status_path,'missing_job_status'))
   except (json.JSONDecodeError,ReconciliationError):missing_status_bad.append(job['job_id']);status_payload={}
   status_value=status_payload.get('state') or status_payload.get('status')
   if status_value!='FAILED_MAX_ATTEMPTS':missing_status_bad.append(job['job_id'])
   if key in selected_set:selected_missing.append(job['job_id'])
   continue
  raw=regular_bytes(p,'job_result');d=json.loads(raw);states[str(d.get('state'))]+=1
  ok=(d.get('state')=='SUCCESS' and d.get('job_id')==job['job_id'] and d.get('job_hash')==job['job_hash'] and d.get('entity_id')==job['entity_id'] and str(d.get('dock_conformation'))==job['conformation'] and int(d.get('seed'))==int(job['seed']))
  if not ok:
   identity_bad.append(job['job_id']);
   if key in selected_set:selected_bad.append(job['job_id'])
  if key in selected_set:selected_inventory.append((job['job_id'],sha_bytes(raw)))
 req(states==Counter({'SUCCESS':3659}),f'result_states:{dict(states)}');req(len(missing)==5,'missing_count');req(not missing_status_bad,'missing_status_bad');req(not identity_bad,'identity_bad')
 req(not selected_missing and not selected_bad and len(selected_inventory)==3536,'selected_result_closure')
 terminal=upstream.get('terminals') or {}
 observed_terminal={917:terminal['stage1']['terminal_counts'],1931:terminal['stage2']['terminal_counts'],3253:terminal['stage3']['terminal_counts']}
 for seed,expected in EXPECTED_TERMINALS.items():req(observed_terminal[seed]==expected,f'terminal_counts:{seed}')
 req(sum(v.get('FAILED_MAX_ATTEMPTS',0) for v in observed_terminal.values())==len(missing),'missing_terminal_failure_closure')
 inventory_basis=''.join(f'{sha}  {jid}\n' for jid,sha in sorted(selected_inventory)).encode()
 receipt={
  'schema_version':SCHEMA_VERSION,'status':'PASS_RECONCILED_V4H_ADAPTIVE_TERMINAL_CLOSURE','claim_boundary':CLAIM,
  'canonical_raw_root':str(root),'upstream_receipt':{'path':UPSTREAM,'sha256':EXPECTED_HASHES[UPSTREAM],
   'final_ranking_field':'final_ranking_sha256','declared_value':declared,'field_correctly_bound':True,
   'actual_final_ranking_path':FINAL,'actual_final_ranking_sha256':EXPECTED_HASHES[FINAL],
   'upstream_receipt_mutated':False},
  'actual_files':actual,
  'closures':{'candidate_rows':1320,'ranking_rows':1320,'tier_counts':dict(sorted(tier_counts.items())),
   'manifest_rows_by_seed':stage_job_counts,'declared_jobs':len(jobs),'result_states':dict(states),'missing_result_files':len(missing),
   'terminal_failed_jobs':len(missing),'job_identity_mismatches':len(identity_bad),'paired_successful_jobs':len(selected_keys),
   'paired_successful_job_identity_mismatches':len(selected_bad),'paired_successful_job_missing_results':len(selected_missing),
   'selected_job_result_inventory_sha256':sha_bytes(inventory_basis),'valid_receptor_seed_asymmetry_candidates':len(asym_valid),
   'all_receptor_seed_asymmetry_candidates':len(asym_all),'excluded_nonteacher_success_results':states['SUCCESS']-len(selected_keys)},
  'teacher_seed_policy':{'scope':'intersection_of_ranking_declared_successful_seed_ids','tier_to_paired_seed_count':TIER_N,
   'unmatched_single_receptor_success':'excluded_without_pose_access'},
  'read_only_boundary':{'source_mutation_operations':0,'pose_coordinate_files_opened':0,'v4_f_access_count':0},
 }
 atomic(output,receipt);return {'status':receipt['status'],'receipt_sha256':sha_bytes(output.read_bytes()),**receipt['closures']}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(reconcile(a.campaign_root,a.output),sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
