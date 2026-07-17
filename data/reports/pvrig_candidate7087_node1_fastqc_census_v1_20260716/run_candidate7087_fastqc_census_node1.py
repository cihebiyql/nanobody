#!/usr/bin/env python3
"""Run the preregistered 7,087-candidate label-free Node1 Fast-QC census."""
from __future__ import annotations
import csv,hashlib,json,math,os,shutil,subprocess,sys,time
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path('/data1/qlyu/projects/pvrig_candidate7087_node1_fastqc_census_v1_20260716')
RUNTIME=Path('/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure')
RUNTIME_MANIFEST=RUNTIME/'RUNTIME_MANIFEST.json'
INPUTS=ROOT/'inputs'; WORK=ROOT/'work/fast_chunks'; OUTPUTS=ROOT/'outputs'; STATUS=ROOT/'status'; LOGS=ROOT/'logs'
FASTA=INPUTS/'candidate7087.fasta'; LINEAGE=INPUTS/'candidate7087_lineage.tsv'; INPUT_AUDIT=INPUTS/'INPUT_AUDIT.json'
PREREG=INPUTS/'phase2_candidate7087_node1_fastqc_census_v1_preregistration.json'
FREEZE=ROOT/'IMPLEMENTATION_FREEZE.json'
EXPECTED={'prereg':'0112cd909702d85f760ebef92b7bc1ab5db83705c5c8546e45cdfe21b08c175b','fasta':'82d89ca0b35f38e87a26b9ccca9ed97ce64255db33250ddb694fe2a072494b88','lineage':'2000415243a044131e1e12704d3a1e0f31b5b84d790d14fdeee4af4db5aea777','runtime_manifest':'603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d'}
CHUNK_SIZE=448; CHUNK_JOBS=16; WORKERS_PER_CHUNK=2
CLAIM='This census is sequence/developability QC only. It is not docking geometry, binding, affinity, competition, experimental blocking, model correctness, or a teacher label.'

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):
 d=hashlib.sha256()
 with p.open('rb') as h:
  for b in iter(lambda:h.read(1024*1024),b''):d.update(b)
 return d.hexdigest()
def atomic_json(path,value,mode=0o644):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f'.{path.name}.tmp.{os.getpid()}');tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');tmp.chmod(mode);os.replace(tmp,path)
def read_tsv(path):
 if not path.is_file() or not path.stat().st_size:raise RuntimeError(f'missing_or_empty:{path}')
 with path.open(newline='',encoding='utf-8-sig') as h:return list(csv.DictReader(h,delimiter='\t'))
def write_tsv(path,rows,fields=None):
 if fields is None:
  fields=[];seen=set()
  for r in rows:
   for k in r:
    if k not in seen:seen.add(k);fields.append(k)
 tmp=path.with_name(f'.{path.name}.tmp.{os.getpid()}')
 with tmp.open('w',newline='',encoding='utf-8') as h:
  w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
 os.replace(tmp,path)
def fasta_records(path):
 records=[];cid=None;parts=[]
 for line in path.read_text().splitlines():
  if line.startswith('>'):
   if cid is not None:records.append((cid,''.join(parts)))
   cid=line[1:].split()[0];parts=[]
  else:parts.append(line.strip())
 if cid is not None:records.append((cid,''.join(parts)))
 return records

def verify_frozen_inputs():
 if sha(PREREG)!=EXPECTED['prereg'] or sha(FASTA)!=EXPECTED['fasta'] or sha(LINEAGE)!=EXPECTED['lineage'] or sha(RUNTIME_MANIFEST)!=EXPECTED['runtime_manifest']:raise RuntimeError('frozen_input_hash_mismatch')
 audit=json.loads(INPUT_AUDIT.read_text());prereg=json.loads(PREREG.read_text());freeze=json.loads(FREEZE.read_text())
 if audit['candidate_count']!=7087 or audit['parent_count']!=40 or prereg['status']!='FROZEN_BEFORE_GLOBAL_7087_NODE1_FAST_QC_RESULTS':raise RuntimeError('input_or_prereg_closure_failed')
 if freeze['status']!='FROZEN_BEFORE_CENSUS_EXECUTION' or freeze['preregistration_sha256']!=EXPECTED['prereg'] or freeze['runtime_manifest_sha256']!=EXPECTED['runtime_manifest']:raise RuntimeError('implementation_freeze_binding_failed')
 if freeze['implementation_hashes'].get(Path(__file__).name)!=sha(Path(__file__).resolve()):raise RuntimeError('worker_self_hash_not_bound_by_freeze')
 if freeze['resource_policy']!={'chunk_jobs':16,'workers_per_chunk':2,'maximum_cpu_workers':32,'gpu_count':0}:raise RuntimeError('resource_policy_mismatch')
 if any(p.is_symlink() for root in [INPUTS,RUNTIME] for p in root.rglob('*')):raise RuntimeError('symlink_in_input_or_runtime_closure')
 manifest=json.loads(RUNTIME_MANIFEST.read_text())
 for rel,e in manifest['files'].items():
  p=RUNTIME/rel
  if not p.is_file() or sha(p)!=e['sha256'] or p.stat().st_size!=e['size']:raise RuntimeError(f'runtime_file_hash:{rel}')
 lineage=read_tsv(LINEAGE);records=fasta_records(FASTA)
 if len(lineage)!=7087 or len(records)!=7087:raise RuntimeError('7087_row_closure_failed')
 by={r['candidate_id']:r for r in lineage}
 if len(by)!=7087 or len({r['sequence_sha256'] for r in lineage})!=7087 or len({r['parent_framework_cluster'] for r in lineage})!=40:raise RuntimeError('id_sequence_parent_closure_failed')
 for cid,seq in records:
  if cid not in by or hashlib.sha256(seq.encode()).hexdigest()!=by[cid]['sequence_sha256']:raise RuntimeError(f'fasta_lineage_hash:{cid}')
 return lineage,records

def write_chunks(records):
 WORK.mkdir(parents=True,exist_ok=True); specs=[]
 for idx,start in enumerate(range(0,len(records),CHUNK_SIZE),1):
  chunk=f'chunk_{idx:06d}';cr=WORK/chunk;cr.mkdir(exist_ok=True);subset=records[start:start+CHUNK_SIZE];inp=cr/'input.fasta'
  raw=''.join(f'>{cid}\n{seq}\n' for cid,seq in subset)
  if inp.exists() and inp.read_text()!=raw:raise RuntimeError(f'existing_chunk_input_mismatch:{chunk}')
  inp.write_text(raw);specs.append((chunk,subset))
 if len(specs)!=16:raise RuntimeError(f'expected_16_chunks:{len(specs)}')
 return specs

def validate_chunk(chunk,records):
 cr=WORK/chunk;marker=json.loads((cr/'complete.json').read_text());rows=read_tsv(cr/'qc_out/portfolio_ranked.tsv');expected=[x[0] for x in records];observed=[r.get('candidate_id','') for r in rows]
 if marker.get('status')!='complete' or marker.get('chunk')!=chunk or marker.get('candidate_count')!=len(expected):raise RuntimeError(f'chunk_marker:{chunk}')
 if len(observed)!=len(set(observed)) or set(observed)!=set(expected):raise RuntimeError(f'chunk_ids:{chunk}')
 if marker.get('input_fasta_sha256')!=sha(cr/'input.fasta') or marker.get('portfolio_ranked_sha256')!=sha(cr/'qc_out/portfolio_ranked.tsv'):raise RuntimeError(f'chunk_hash:{chunk}')
 if marker.get('runtime_manifest_sha256')!=EXPECTED['runtime_manifest']:raise RuntimeError(f'chunk_runtime:{chunk}')
 return marker

def run_chunk(chunk,records):
 cr=WORK/chunk;marker=cr/'complete.json'
 if marker.is_file():
  try:return {**validate_chunk(chunk,records),'execution_status':'reused'}
  except Exception:pass
 if (cr/'qc_out').exists():
  archive=ROOT/'preserved_attempts'/f'{chunk}.{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.{os.getpid()}';archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(cr/'qc_out'),archive)
 command=[str(RUNTIME/'bin/vhh-competition-qc'),str(cr/'input.fasta'),'-o',str(cr/'qc_out'),'--prefix',chunk,'--workers','2','--tnp-ncores','1','--identity-cache-size','500000','--gate-policy','blocker_calibrated','--skip-team-diversity','--top-n','100000000','--reserve-n','0','--vhh-screen-bin',str(RUNTIME/'bin/vhh-screen'),'--validator-bin',str(RUNTIME/'bin/ab-data-validator'),'--anarci-bin',str(RUNTIME/'bin/ANARCI'),'--muscle-bin',str(RUNTIME/'bin/muscle'),'--positive-csv',str(RUNTIME/'validator_src/ab_data_validator/data/positive.csv'),'--official-positive-cdr-cache',str(RUNTIME/'references/official_positive_library_cdrs.csv'),'--local-positive-cdr-csv',str(RUNTIME/'references/local_pvrig_positive_vhh_cdrs.csv'),'--large-scale-fast']
 (cr/'command.json').write_text(json.dumps(command,indent=2)+'\n');start=time.monotonic();env=dict(os.environ);env.update({'PATH':f'{RUNTIME/"bin"}:/data1/qlyu/anaconda3/envs/boltz/bin:'+env.get('PATH',''),'PYTHONPATH':f'{RUNTIME/"validator_src"}:{RUNTIME/"src"}','AB_DATA_VALIDATOR_SRC':str(RUNTIME/'validator_src'),'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'})
 with (cr/'runner.stdout.log').open('w') as o,(cr/'runner.stderr.log').open('w') as e:done=subprocess.run(command,stdout=o,stderr=e,text=True,env=env,check=False)
 if done.returncode:raise RuntimeError(f'chunk_rc:{chunk}:{done.returncode}')
 rows=read_tsv(cr/'qc_out/portfolio_ranked.tsv');expected={x[0] for x in records};observed=[r.get('candidate_id','') for r in rows]
 if len(observed)!=len(expected) or len(set(observed))!=len(expected) or set(observed)!=expected:raise RuntimeError(f'chunk_output_id_closure:{chunk}')
 payload={'schema_version':'candidate7087_node1_fastqc_chunk_v1','status':'complete','chunk':chunk,'candidate_count':len(records),'elapsed_seconds':round(time.monotonic()-start,3),'finished_at_utc':now(),'input_fasta_sha256':sha(cr/'input.fasta'),'portfolio_ranked_sha256':sha(cr/'qc_out/portfolio_ranked.tsv'),'runtime_manifest_sha256':EXPECTED['runtime_manifest']};atomic_json(marker,payload,0o444);validate_chunk(chunk,records);return payload

def merge(lineage,specs,markers):
 by={r['candidate_id']:r for r in lineage};qc=[]
 for chunk,_ in specs:qc.extend(read_tsv(WORK/chunk/'qc_out/portfolio_ranked.tsv'))
 if len(qc)!=7087 or len({r.get('candidate_id','') for r in qc})!=7087 or set(r['candidate_id'] for r in qc)!=set(by):raise RuntimeError('merge_7087_id_closure_failed')
 out=[]
 for row in qc:
  cid=row['candidate_id'];lin=by[cid];seq=row.get('sequence','')
  if hashlib.sha256(seq.encode()).hexdigest()!=lin['sequence_sha256']:raise RuntimeError(f'merge_sequence_hash:{cid}')
  hard=str(row.get('hard_fail','')).lower()
  if hard not in {'true','false'}:raise RuntimeError(f'invalid_hard_fail:{cid}')
  out.append({'candidate_id':cid,'sequence_sha256':lin['sequence_sha256'],'parent_framework_cluster':lin['parent_framework_cluster'],'fast_hard_fail':'True' if hard=='true' else 'False','reason_summary':row.get('reason_summary',''),'official_validator_failed_reason':row.get('official_validator_failed_reason',''),'census_role':lin['census_role']})
 out.sort(key=lambda r:r['candidate_id']);OUTPUTS.mkdir(parents=True,exist_ok=True);candidate=OUTPUTS/'candidate7087_node1_fastqc_census_v1.tsv';write_tsv(candidate,out,['candidate_id','sequence_sha256','parent_framework_cluster','fast_hard_fail','reason_summary','official_validator_failed_reason','census_role'])
 grouped=defaultdict(list)
 for r in out:grouped[r['parent_framework_cluster']].append(r)
 parents=[]
 for parent in sorted(grouped):
  rs=grouped[parent];passes=sum(r['fast_hard_fail']=='False' for r in rs);n=len(rs)
  parents.append({'parent_framework_cluster':parent,'candidate_count':str(n),'fast_hard_pass_count':str(passes),'fast_hard_fail_count':str(n-passes),'fast_hard_pass_fraction':f'{passes/n:.6f}','support_v4_capacity_state':'READY_FOR_24_TEACHER_PLUS_12_AUDIT_ACQUISITION' if passes>=36 else 'INSUFFICIENT_FAST_QC_CAPACITY'})
 if len(parents)!=40 or sum(int(r['candidate_count']) for r in parents)!=7087:raise RuntimeError('parent40_closure_failed')
 parent_path=OUTPUTS/'parent40_node1_fastqc_capacity_v1.tsv';write_tsv(parent_path,parents,['parent_framework_cluster','candidate_count','fast_hard_pass_count','fast_hard_fail_count','fast_hard_pass_fraction','support_v4_capacity_state'])
 status_path=OUTPUTS/'fast_chunk_status.tsv';write_tsv(status_path,[{'chunk':m['chunk'],'status':'complete','elapsed_seconds':m.get('elapsed_seconds',0),'candidate_count':m['candidate_count']} for m in sorted(markers,key=lambda x:x['chunk'])],['chunk','status','elapsed_seconds','candidate_count'])
 audit={'schema_version':'candidate7087_node1_fastqc_census_audit_v1','status':'PASS_7087_FAST_QC_CENSUS_AUDIT','candidate_count':7087,'parent_count':40,'fast_hard_pass_count':sum(r['fast_hard_fail']=='False' for r in out),'fast_hard_fail_count':sum(r['fast_hard_fail']=='True' for r in out),'ready_parent_count':sum(r['support_v4_capacity_state'].startswith('READY_') for r in parents),'insufficient_parent_count':sum(r['support_v4_capacity_state'].startswith('INSUFFICIENT_') for r in parents),'resource_policy':{'chunk_jobs':16,'workers_per_chunk':2,'maximum_cpu_workers':32,'gpu_count':0},'runtime_manifest_sha256':EXPECTED['runtime_manifest'],'preregistration_sha256':EXPECTED['prereg'],'label_path_access':{'docking':0,'v4_d_geometry':0,'v4_f_labels':0,'model_score':0,'experimental':0},'outputs':{p.name:sha(p) for p in [candidate,parent_path,status_path]},'claim_boundary':CLAIM};audit_path=OUTPUTS/'candidate7087_node1_fastqc_census_v1.audit.json';atomic_json(audit_path,audit,0o444)

def validate_terminal(lineage,specs):
 for c,r in specs:validate_chunk(c,r)
 candidates=read_tsv(OUTPUTS/'candidate7087_node1_fastqc_census_v1.tsv');parents=read_tsv(OUTPUTS/'parent40_node1_fastqc_capacity_v1.tsv');chunks=read_tsv(OUTPUTS/'fast_chunk_status.tsv');audit=json.loads((OUTPUTS/'candidate7087_node1_fastqc_census_v1.audit.json').read_text())
 if len(candidates)!=7087 or len({r['candidate_id'] for r in candidates})!=7087 or len(parents)!=40 or len(chunks)!=16 or any(r['status']!='complete' for r in chunks):raise RuntimeError('terminal_count_closure_failed')
 if audit['status']!='PASS_7087_FAST_QC_CENSUS_AUDIT' or audit['candidate_count']!=7087 or audit['parent_count']!=40:raise RuntimeError('terminal_audit_failed')
 required=['candidate7087_node1_fastqc_census_v1.tsv','parent40_node1_fastqc_capacity_v1.tsv','fast_chunk_status.tsv']
 for n in required:
  if audit['outputs'][n]!=sha(OUTPUTS/n):raise RuntimeError(f'terminal_hash:{n}')
 return {'schema_version':'candidate7087_node1_fastqc_census_receipt_v1','status':'PASS_7087_FAST_QC_CENSUS_READY_FOR_SUPPORT_V4_A_PLANNING','published_at_utc':now(),'candidate_count':7087,'parent_count':40,'fast_hard_pass_count':audit['fast_hard_pass_count'],'fast_hard_fail_count':audit['fast_hard_fail_count'],'ready_parent_count':audit['ready_parent_count'],'insufficient_parent_count':audit['insufficient_parent_count'],'preregistration_sha256':EXPECTED['prereg'],'runtime_manifest_sha256':EXPECTED['runtime_manifest'],'implementation_freeze_sha256':sha(FREEZE),'input_hashes':{'candidate7087.fasta':EXPECTED['fasta'],'candidate7087_lineage.tsv':EXPECTED['lineage']},'output_sha256':{n:sha(OUTPUTS/n) for n in required+['candidate7087_node1_fastqc_census_v1.audit.json']},'receipt_publication_order':'LAST_AFTER_ALL_CLOSURE_GATES','label_path_access':{'docking':0,'v4_d_geometry':0,'v4_f_labels':0,'model_score':0,'experimental':0},'claim_boundary':CLAIM}

def main():
 STATUS.mkdir(parents=True,exist_ok=True);LOGS.mkdir(parents=True,exist_ok=True);atomic_json(STATUS/'census.running.json',{'status':'RUNNING_7087_FAST_QC_CENSUS','pid':os.getpid(),'started_at_utc':now(),'resource_policy':{'chunk_jobs':16,'workers_per_chunk':2,'maximum_cpu_workers':32,'gpu_count':0}})
 try:
  lineage,records=verify_frozen_inputs();specs=write_chunks(records);markers=[]
  with ThreadPoolExecutor(max_workers=CHUNK_JOBS) as ex:
   futures={ex.submit(run_chunk,c,r):c for c,r in specs}
   for f in as_completed(futures):markers.append(f.result())
  merge(lineage,specs,markers);receipt=validate_terminal(lineage,specs);atomic_json(OUTPUTS/'candidate7087_node1_fastqc_census_v1.receipt.json',receipt,0o444);atomic_json(STATUS/'census.complete.json',receipt,0o444);(STATUS/'census.running.json').unlink(missing_ok=True);print(json.dumps(receipt,indent=2,sort_keys=True));return 0
 except BaseException as e:
  failure={'status':'FAIL_FAST_QC_CENSUS_NO_SUPPORT_V4_DENOMINATOR','failed_at_utc':now(),'error':f'{type(e).__name__}:{e}','pid':os.getpid(),'claim_boundary':CLAIM};atomic_json(STATUS/'census.failed.json',failure,0o444);print(json.dumps(failure,indent=2,sort_keys=True),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
