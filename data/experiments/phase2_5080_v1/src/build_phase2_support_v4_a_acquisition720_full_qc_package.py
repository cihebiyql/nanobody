#!/usr/bin/env python3
"""Build/freeze the Support V4-A 720 label-free Node1 Full-QC package."""
from __future__ import annotations
import argparse,csv,hashlib,json,os,shutil,tempfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

PHASE2=Path(__file__).resolve().parents[1]
SRC=Path(__file__).resolve().parent
DEFAULT_INPUT=PHASE2/'prepared/pvrig_support_v4_a_acquisition720_v1'
DEFAULT_MANIFEST=DEFAULT_INPUT/'support_v4_a_future_teacher_acquisition_pool_v1.tsv'
DEFAULT_AUDIT=DEFAULT_INPUT/'support_v4_a_acquisition_readiness_audit_v1.json'
DEFAULT_RECEIPT=DEFAULT_INPUT/'support_v4_a_acquisition_readiness_receipt_v1.json'
DEFAULT_PREREG=PHASE2/'audits/phase2_support_v4_a_acquisition720_full_qc_v1_preregistration.json'
DEFAULT_RUNNER=SRC/'run_phase2_support_v4_a_acquisition720_full_qc_node1.py'
DEFAULT_TEST=SRC/'test_build_phase2_support_v4_a_acquisition720_full_qc_package.py'
DEFAULT_LAUNCHER_TEMPLATE=SRC/'templates/pvrig_support_v4_a_acquisition720_full_qc_launcher.sh.in'
DEFAULT_OUTPUT=PHASE2/'prepared/pvrig_support_v4_a_acquisition720_full_qc_v1'
DEFAULT_FREEZE=PHASE2/'audits/phase2_support_v4_a_acquisition720_full_qc_v1_implementation_freeze.json'
EXPECTED={'manifest':'73454cbf8194d3faa5cad354a5b2f31f433e317d5222a6cd59906775fb56bfca','audit':'19f7465978601b346b98b7cf9fe0385cf5b139db0e1bf1ae09a3dbae5b214f1e','receipt':'440e675b1a6e39771a830d282e7e575dfe7ce24f7cb91c2966f71f577c655181','prereg':'1d84c5fafc1d1ce3cdd605b6cae697ded207b1806327c28b2d028bce4543658a','screen':'051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a','runtime_manifest':'603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d','python':'33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095'}
FIELDS=['candidate_id','sequence','sequence_sha256','parent_id','parent_framework_cluster','parent_role','target_patch_id','design_mode','cdr3','cdr3_length','max_positive_cdr_identity','fast_qc_state','selection_hash','acquisition_role','selection_rank_within_parent','cdr3_min_normalized_edit_distance_to_previous','claim_boundary']
STANDARD=set('ACDEFGHIKLMNPQRSTVWY')
REMOTE_ROOT='/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717'
CLAIM='This run measures sequence and developability Full-QC only. It is not Docking, docking geometry, PVRIG binding, affinity, competition, experimental blocking, blocker probability, or a biological teacher label.'

def now():return datetime.now(timezone.utc).isoformat()
def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def jbytes(x:Any):return (json.dumps(x,indent=2,sort_keys=True)+'\n').encode()
def atomic(path:Path,raw:bytes,mode=0o644):
 path.parent.mkdir(parents=True,exist_ok=True);fd,n=tempfile.mkstemp(prefix=f'.{path.name}.tmp.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as h:h.write(raw);h.flush();os.fsync(h.fileno())
  os.chmod(n,mode);os.replace(n,path)
 finally:
  if Path(n).exists():Path(n).unlink()
def read(path:Path):
 with path.open(newline='',encoding='utf-8-sig') as h:
  r=csv.DictReader(h,delimiter='\t');return list(r.fieldnames or []),list(r)

def validate_sources(manifest=DEFAULT_MANIFEST,audit=DEFAULT_AUDIT,receipt=DEFAULT_RECEIPT,prereg=DEFAULT_PREREG):
 observed={'manifest':sha(manifest),'audit':sha(audit),'receipt':sha(receipt),'prereg':sha(prereg)}
 for k,v in observed.items():
  if v!=EXPECTED[k]:raise RuntimeError(f'frozen_source_hash_mismatch:{k}:{v}')
 fields,rows=read(manifest)
 if fields!=FIELDS:raise RuntimeError(f'exact_schema_mismatch:{fields}')
 if len(rows)!=720:raise RuntimeError('expected_720')
 if len({r['parent_framework_cluster'] for r in rows})!=20 or set(Counter(r['parent_framework_cluster'] for r in rows).values())!={36}:raise RuntimeError('parent_20x36')
 if Counter(r['acquisition_role'] for r in rows)!=Counter({'FUTURE_NODE1_TEACHER_ACQUISITION':480,'LABEL_FREE_AUDIT':240}):raise RuntimeError('role_480_240')
 if Counter(r['target_patch_id'] for r in rows)!=Counter({'A_CENTER':240,'B_LOWER':240,'C_CROSS':240}):raise RuntimeError('patch_3x240')
 if {r['parent_role'] for r in rows}!={'OPEN_TRAIN'} or {r['fast_qc_state'] for r in rows}!={'HARD_PASS'}:raise RuntimeError('role_fast_state')
 for k in ['candidate_id','sequence','sequence_sha256','cdr3']:
  if len({r[k] for r in rows})!=720:raise RuntimeError(f'unique_{k}')
 for r in rows:
  if set(r['sequence'])-STANDARD or hashlib.sha256(r['sequence'].encode()).hexdigest()!=r['sequence_sha256']:raise RuntimeError(f'sequence:{r["candidate_id"]}')
  if len(r['cdr3'])!=int(r['cdr3_length']):raise RuntimeError(f'cdr3:{r["candidate_id"]}')
 a=json.loads(audit.read_text());q=json.loads(receipt.read_text());p=json.loads(prereg.read_text())
 if a['selected_rows']!=720 or a['acquisition_rows']!=480 or a['audit_rows']!=240 or any(int(x)!=0 for x in a['label_path_access'].values()):raise RuntimeError('audit_closure')
 if q['output_sha256'][manifest.name]!=EXPECTED['manifest'] or q['status']!='FROZEN_FUTURE_NODE1_TEACHER_ACQUISITION_CAPACITY_ONLY':raise RuntimeError('receipt_closure')
 if p['status']!='FROZEN_BEFORE_SUPPORT_V4_A_720_FULL_QC_EXECUTION' or any(int(x)!=0 for x in p['label_path_access'].values()):raise RuntimeError('prereg_closure')
 return rows,observed

def build_package(output=DEFAULT_OUTPUT,freeze_out=DEFAULT_FREEZE,manifest=DEFAULT_MANIFEST,audit=DEFAULT_AUDIT,receipt=DEFAULT_RECEIPT,prereg=DEFAULT_PREREG,runner=DEFAULT_RUNNER,test=DEFAULT_TEST,launcher_template=DEFAULT_LAUNCHER_TEMPLATE):
 rows,sources=validate_sources(manifest,audit,receipt,prereg)
 if output.exists():shutil.rmtree(output)
 (output/'inputs').mkdir(parents=True)
 for src in [manifest,audit,receipt]:shutil.copyfile(src,output/'inputs'/src.name)
 shutil.copyfile(prereg,output/prereg.name);shutil.copyfile(runner,output/runner.name)
 (output/runner.name).chmod(0o755)
 fasta=''.join(f'>{r["candidate_id"]}\n{r["sequence"]}\n' for r in rows).encode();atomic(output/'inputs/support_v4_a_acquisition720.fasta',fasta)
 runner_sha=sha(output/runner.name)
 launcher=launcher_template.read_text().replace('@RUNNER_SHA@',runner_sha).encode();atomic(output/'launch_full_qc_node1.sh',launcher,0o755)
 impl={
  'schema_version':'phase2_support_v4_a_acquisition720_full_qc_v1_implementation_freeze',
  'status':'FROZEN_BEFORE_REMOTE_FULL_QC_EXECUTION','frozen_at_utc':now(),
  'input_hashes':{manifest.name:EXPECTED['manifest'],audit.name:EXPECTED['audit'],receipt.name:EXPECTED['receipt'],'support_v4_a_acquisition720.fasta':sha(output/'inputs/support_v4_a_acquisition720.fasta')},
  'implementation_hashes':{Path(__file__).name:sha(Path(__file__).resolve()),runner.name:runner_sha,test.name:sha(test),launcher_template.name:sha(launcher_template),'launch_full_qc_node1.sh':sha(output/'launch_full_qc_node1.sh')},
  'preregistration_sha256':EXPECTED['prereg'],'remote_bindings':{'remote_root':REMOTE_ROOT,'screen_source_sha256':EXPECTED['screen'],'runtime_manifest_sha256':EXPECTED['runtime_manifest'],'python_sha256':EXPECTED['python']},
  'resource_policy':{'chunk_jobs':16,'full_chunk_jobs':16,'workers_per_chunk':2,'maximum_requested_cpu_workers':32,'gpu_requested':0},
  'execution_policy':'prepare -> fast -> all fast survivors Full-QC; no replacement; TNP deferred','label_path_access':{'model':0,'docking':0,'geometry':0,'experimental':0},'claim_boundary':CLAIM,
 }
 atomic(freeze_out,jbytes(impl),0o444);shutil.copyfile(freeze_out,output/'IMPLEMENTATION_FREEZE.json');(output/'IMPLEMENTATION_FREEZE.json').chmod(0o444)
 rels=[f'inputs/{manifest.name}',f'inputs/{audit.name}',f'inputs/{receipt.name}','inputs/support_v4_a_acquisition720.fasta',prereg.name,runner.name,'launch_full_qc_node1.sh','IMPLEMENTATION_FREEZE.json']
 package={'schema_version':'phase2_support_v4_a_acquisition720_full_qc_v1_package_receipt','status':'PASS_PACKAGE_HASH_CLOSED_BEFORE_REMOTE_EXECUTION','published_at_utc':now(),'candidate_count':720,'outputs':{rel:sha(output/rel) for rel in rels},'source_hashes':sources,'label_or_model_fields_accepted':0,'remote_execution_started':False,'receipt_publication_order':'LAST_AFTER_PACKAGE_AND_FREEZE_HASH_CLOSURE','claim_boundary':CLAIM}
 atomic(output/'PACKAGE_RECEIPT.json',jbytes(package),0o444)
 return validate_package(output)

def validate_package(output=DEFAULT_OUTPUT):
 receipt=json.loads((output/'PACKAGE_RECEIPT.json').read_text())
 if receipt['status']!='PASS_PACKAGE_HASH_CLOSED_BEFORE_REMOTE_EXECUTION' or receipt['candidate_count']!=720 or receipt['label_or_model_fields_accepted']!=0:raise RuntimeError('package_receipt')
 expected=set(receipt['outputs'])|{'PACKAGE_RECEIPT.json'};actual={str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()}
 if actual!=expected:raise RuntimeError(f'package_file_closure:{sorted(actual^expected)}')
 for rel,d in receipt['outputs'].items():
  p=output/rel
  if p.is_symlink() or sha(p)!=d:raise RuntimeError(f'package_hash:{rel}')
 fields,rows=read(output/'inputs'/DEFAULT_MANIFEST.name)
 fasta=[line for line in (output/'inputs/support_v4_a_acquisition720.fasta').read_text().splitlines() if line.startswith('>')]
 if fields!=FIELDS or len(rows)!=len(fasta)!=720:raise RuntimeError('package_rows')
 if (output/'PACKAGE_RECEIPT.json').stat().st_mode&0o222:raise RuntimeError('receipt_writable')
 return {'status':'PASS','candidate_count':720,'package_receipt_sha256':sha(output/'PACKAGE_RECEIPT.json'),'implementation_freeze_sha256':sha(output/'IMPLEMENTATION_FREEZE.json'),'runner_sha256':sha(output/DEFAULT_RUNNER.name),'launcher_sha256':sha(output/'launch_full_qc_node1.sh')}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);ap.add_argument('--freeze-out',type=Path,default=DEFAULT_FREEZE);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
 result=validate_package(a.output) if a.verify_only else build_package(a.output,a.freeze_out);print(json.dumps(result,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
