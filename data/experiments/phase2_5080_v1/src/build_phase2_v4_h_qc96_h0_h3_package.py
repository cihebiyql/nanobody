#!/usr/bin/env python3
"""Build and freeze the label-free V4-H-QC96 H0-H4 Node1 package."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,shutil,subprocess
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Mapping,Sequence

SCRIPT_DIR=Path(__file__).resolve().parent; EXP_DIR=SCRIPT_DIR.parent; WORKSPACE=EXP_DIR.parents[2]
TOP200=WORKSPACE/'scaffolds/top_200_vhh_scaffolds_for_design.csv'
V4D=EXP_DIR/'data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv'; V4F=EXP_DIR/'data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv'
V4G=EXP_DIR/'data_splits/pvrig_v4_g/unseen96_acquisition_manifest.tsv'; RESERVE2=EXP_DIR/'data_splits/pvrig_v4_g/untouched_reserve2_parents.tsv'
CALIBRATION=EXP_DIR/'data_splits/pvrig_v4_g/known_calibration_sequence_exclusions_v1.tsv'; ANARCI=EXP_DIR/'data_splits/pvrig_v4_h/parent12_anarci_imgt_v1_H.csv'
LEGACY7087_FASTA=EXP_DIR.parents[1]/'reports/pvrig_candidate7087_node1_fastqc_census_v1_20260716/deployment_inputs/candidate7087.fasta'
RF1000_FASTA=EXP_DIR/'prepared/pvrig_rfantibody_v1/pvrig_rfantibody_1000_fr4_complete.fasta'; TARGET=WORKSPACE/'node1/rfantibody_pvrig_1000/inputs/pvrig_8x6b_chainT.pdb'
PARENT_QUEUE=EXP_DIR/'data_splits/pvrig_v4_h/parent12_queue_v1.tsv'; PREREG=EXP_DIR/'audits/phase2_v4_h_qc96_h0_h3_v1_preregistration.json'
FREEZE=EXP_DIR/'audits/phase2_v4_h_qc96_h0_h3_v1_implementation_freeze.json'; DEFAULT_OUTDIR=EXP_DIR/'prepared/pvrig_v4_h_qc96_h0_h3_v1'
REMOTE_ROOT=Path('/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717')
SELECTION_SEED='phase2_v4_h_qc_qualified_prospective_holdout_20260717'; H1_SELECTION_SEED='phase2_v4_h_h1_exact_unique_selection_v1_20260717'; H4_SELECTION_SEED='phase2_v4_h_h4_fullqc_hash_selection_v1_20260717'
EXACT_QUEUE=('C0162','C0371','C0283','C0148','C0078','C0145','C0086','C0417','C0176','C0348','C0409','C0360')
STANDARD_AA=set('ACDEFGHIKLMNPQRSTVWY'); MODES=('H3','H1H3')
PATCHES={'A_CENTER':{'hotspots_pdb':'T57,T101,T106','hotspots_uniprot':'R95,F139,W144'},'B_LOWER':{'hotspots_pdb':'T97,T101,T105,T106','hotspots_uniprot':'K135,F139,S143,W144'},'C_CROSS':{'hotspots_pdb':'T33,T36,T105,T106','hotspots_uniprot':'S71,T74,S143,W144'}}
CLAIM='V4-H-QC96 is a label-free QC-qualified prospective computational holdout protocol; not Docking geometry, binding, affinity, competition, experimental blocking, or Docking Gold.'

def now(): return datetime.now(timezone.utc).isoformat()
def sha256(p):
 d=hashlib.sha256()
 with Path(p).open('rb') as h:
  for b in iter(lambda:h.read(1024*1024),b''): d.update(b)
 return d.hexdigest()
def shat(s): return hashlib.sha256(s.encode()).hexdigest()
def read(path,delimiter='\t'):
 with Path(path).open(newline='',encoding='utf-8-sig') as h:return list(csv.DictReader(h,delimiter=delimiter))
def write_tsv(path,rows):
 if not rows: raise ValueError(f'empty_rows:{path}')
 Path(path).parent.mkdir(parents=True,exist_ok=True)
 with Path(path).open('w',newline='',encoding='utf-8') as h:
  w=csv.DictWriter(h,fieldnames=list(rows[0]),delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def fasta(path):
 out=[];cid=None;parts=[]
 for line in Path(path).read_text().splitlines():
  if line.startswith('>'):
   if cid is not None:out.append((cid,''.join(parts)))
   cid=line[1:].split()[0];parts=[]
  else:parts.append(line.strip())
 if cid is not None:out.append((cid,''.join(parts)))
 return out
def numpos(field):
 m=re.match(r'^(\d+)',field);return int(m.group(1)) if m else None

def parse_anarci():
 rows=read(ANARCI,',');out={}
 if len(rows)!=12:raise RuntimeError(f'anarci_parent_count:{len(rows)}')
 for row in rows:
  cluster=row['Id'].split('|')[0];res=[];raw=0
  for field,value in row.items():
   pos=numpos(field)
   if pos is None or not value or value=='-':continue
   raw+=1;res.append((raw,field,value))
  seq=''.join(v for _,_,v in res);loops={}
  for name,lo,hi in [('h1',27,38),('h2',56,65),('h3',105,117)]:
   xs=[x for x in res if lo<=numpos(x[1])<=hi]
   if not xs:raise RuntimeError(f'anarci_loop_empty:{cluster}:{name}')
   loops[name]=(xs[0][0],xs[-1][0],''.join(x[2] for x in xs))
  out[cluster]={'sequence':seq,'loops':loops,'score':row['score'],'evalue':row['e-value']}
 if set(out)!=set(EXACT_QUEUE):raise RuntimeError('anarci_cluster_set')
 return out

def derive_queue():
 used_clusters=set();used_parents=set();used_sequences=set();used_hashes=set()
 for rows in map(read,[V4D,V4F,V4G,RESERVE2]):
  for row in rows:
   if row.get('parent_framework_cluster'):used_clusters.add(row['parent_framework_cluster'])
   used_parents.update(x for x in row.get('parent_ids',row.get('parent_id','')).split(';') if x)
   if row.get('sequence'):used_sequences.add(row['sequence'])
   if row.get('sequence_sha256'):used_hashes.add(row['sequence_sha256'])
 if len(used_clusters)!=40:raise RuntimeError(f'used_clusters:{len(used_clusters)}')
 cal=read(CALIBRATION);calseq={r['sequence'] for r in cal};calhash={r['sequence_sha256'] for r in cal};eligible=[]
 for row in read(TOP200,','):
  seq=row['sequence_aa'].strip().upper();digest=shat(seq)
  if row['cluster_id'] in used_clusters or row['sequence_id'] in used_parents or seq in used_sequences or digest in used_hashes or seq in calseq or digest in calhash:continue
  gates=[row['keep_or_drop']=='keep',row['numbering_status']=='anarci_success',row['is_vhh']=='yes',row['framework_health_status']=='pass_framework_health',row['developability_status']=='pass_developability',row['target_related_similarity_status']=='pass_positive_leakage_gate',not(set(seq)-STANDARD_AA),110<=len(seq)<=135,seq.endswith('WGQGTQVTVSS'),seq.count('C')==2,not row['ptm_risk_flags'].strip(),row['free_cys_risk']=='low']
  if all(gates):
   row=dict(row);row['selection_hash']=shat(f"{SELECTION_SEED}|{row['cluster_id']}");eligible.append(row)
 eligible.sort(key=lambda r:(-float(r['score_v1_1']),r['selection_hash'],r['cluster_id']))
 if len(eligible)!=67 or tuple(r['cluster_id'] for r in eligible[:12])!=EXACT_QUEUE:raise RuntimeError(f'eligible_queue:{len(eligible)}:{tuple(r["cluster_id"] for r in eligible[:12])}')
 numbered=parse_anarci();out=[];mismatch=Counter()
 for rank,source in enumerate(eligible[:12],1):
  cluster=source['cluster_id'];seq=source['sequence_aa'].strip().upper();n=numbered[cluster]
  if n['sequence']!=seq:raise RuntimeError(f'anarci_sequence:{cluster}')
  h1,h2,h3=n['loops']['h1'],n['loops']['h2'],n['loops']['h3']
  mismatch['source_cdr1_mismatch']+=source['cdr1']!=h1[2];mismatch['source_cdr2_mismatch']+=source['cdr2']!=h2[2];mismatch['source_cdr3_mismatch']+=source['cdr3']!=h3[2]
  out.append({'schema_version':'phase2_v4_h_parent12_queue_v1','queue_rank':rank,'parent_framework_cluster':cluster,'parent_id':source['sequence_id'],'source_accession':source['source_accession'],'sequence':seq,'sequence_sha256':shat(seq),'sequence_length':len(seq),'h1_start_1based':h1[0],'h1_end_1based':h1[1],'cdr1':h1[2],'h2_start_1based':h2[0],'h2_end_1based':h2[1],'cdr2':h2[2],'h3_start_1based':h3[0],'h3_end_1based':h3[1],'cdr3':h3[2],'cdr3_length':len(h3[2]),'fr4_tail':'WGQGTQVTVSS','score_v1_1':source['score_v1_1'],'max_cdr_identity_to_HR151_Tab5':source['max_cdr_identity_to_HR151_Tab5'],'selection_hash':source['selection_hash'],'numbering_source':'frozen_ANARCI_IMGT_raw_sequence_mapping','claim_boundary':CLAIM})
 return out,{'eligible_parent_count':len(eligible),'used_parent_cluster_count':len(used_clusters),'source_vs_anarci_cdr_mismatch_counts':dict(mismatch)}

def h3range(n):
 lo=min(20,max(5,n-2));return lo,min(20,max(lo,n+2))
def build_tasks(parents):
 tasks=[]
 for p in parents:
  lo,hi=h3range(int(p['cdr3_length']));h3=str(lo) if lo==hi else f'{lo}-{hi}';h1=int(p['h1_end_1based'])-int(p['h1_start_1based'])+1
  for patch,pc in PATCHES.items():
   for mode in MODES:
    tasks.append({'task_id':f"V4H__{p['parent_id']}__{patch}__{mode}",'parent_id':p['parent_id'],'parent_framework_cluster':p['parent_framework_cluster'],'parent_queue_rank':p['queue_rank'],'patch_id':patch,**pc,'design_mode':mode,'design_loops':f'H3:{h3}' if mode=='H3' else f'H1:{h1},H3:{h3}','mpnn_loops':'H3' if mode=='H3' else 'H1,H3','target_backbones':12,'sequences_per_backbone':3,'expected_raw_records':36,'selected_exact_unique_target':20,'diffuser_t':50,'rfdiffusion_deterministic':'true','rfdiffusion_design_indices':'0-11','mpnn_temperature':'0.2','augment_eps':'0','omit_aas':'CX','proteinmpnn_deterministic_contract':'bound_script_-deterministic_hardcodes_seed42','claim_boundary':CLAIM})
 if len(tasks)!=72 or sum(r['expected_raw_records'] for r in tasks)!=2592:raise RuntimeError('task_shape')
 return tasks

def exclusions():
 vals={}
 for role,path in [('LEGACY7087',LEGACY7087_FASTA),('RFANTIBODY1000',RF1000_FASTA)]:
  for _,seq in fasta(path):vals.setdefault(shat(seq),set()).add(role)
 for row in read(CALIBRATION):vals.setdefault(row['sequence_sha256'],set()).add('CALIBRATION_POSITIVE_EXCLUSION')
 return [{'sequence_sha256':d,'exclusion_sources':';'.join(sorted(src)),'claim_boundary':'hash-only exact-sequence exclusion; no labels or scores'} for d,src in sorted(vals.items())]

def package_config():
 return {'schema_version':'phase2_v4_h_qc96_generation_config_v1','remote_root':str(REMOTE_ROOT),'tools':{
'rfdiffusion':{'path':'/data/qlyu/software/RFantibody/bin/rfdiffusion','sha256':'f60ed188789e0a343d2bd7f7dbbaadb23807b30dfb513b5a2c305e2166f5a7d7'},'rfantibody_env':{'path':'/data/qlyu/software/RFantibody/bin/rfantibody-env','sha256':'e83f2ae1e4fb0a6755d1c19ba926cd8ae7b267a419a4107bea4e32563703cc97'},'proteinmpnn_script':{'path':'/data/qlyu/software/RFantibody/scripts/proteinmpnn_interface_design.py','sha256':'b4aefc06ad9b6aab1a54eda691e55bb99e30a33e6d6b9489c17187a266e230b3'},'proteinmpnn_weight':{'path':'/data/qlyu/software/RFantibody/weights/ProteinMPNN_v48_noise_0.2.pt','sha256':'c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd'},'rfdiffusion_weight':{'path':'/data/qlyu/software/RFantibody/weights/RFdiffusion_Ab.pt','sha256':'736c18ae8e867ed505d19853fa5380514ff439675d002ff3a73c7287acf07e3c'},'rfdiffusion_inference_source':{'path':'/data/qlyu/software/RFantibody/scripts/rfdiffusion_inference.py','sha256':'fe66312248ba280e6bb05fa66677a6eb96dd8206679ce7d0d9ad5760a9495aca'},'nanobodybuilder2':{'path':'/data1/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2','sha256':'00e0a9211449f6d1da299308c553b3bc3facb261707316fcb688a6cfe5ae6e69'},'python':{'path':'/data1/qlyu/anaconda3/envs/boltz/bin/python3.11','sha256':'33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095'}},
'generation':{'h1_selection_seed':H1_SELECTION_SEED,'raw_records':2592,'selected_records':1440},'resource_policy':{'gpu_ids':[0,1,2,3],'cpu_sets':['0-7','8-15','16-23','24-31'],'minimum_node_cpu_count':32,'minimum_free_disk_bytes':100*1024**3},'command_timeouts_seconds':{'nanobodybuilder2':3600,'helper':600,'rfdiffusion':21600,'proteinmpnn':7200},
'qc':{'runtime_root':'/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure','runtime_manifest':{'path':'/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure/RUNTIME_MANIFEST.json','sha256':'603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d'},'screen':{'path':'/data1/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py','sha256':'051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a'},'python':{'path':'/data1/qlyu/anaconda3/envs/boltz/bin/python3.11','sha256':'33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095'},'h4_selection_seed':H4_SELECTION_SEED},
'forbidden_environment_tokens':['r_dual_min','test32','model_predictions','/pvrig_v4_d_dual','/pvrig_v4_f96_dual'],'label_path_access':{'docking':0,'v4_d_test32':0,'v4_f_labels':0,'model_scores_or_predictions':0,'experimental':0},'claim_boundary':CLAIM}

def prereg(parents,audit,tasks,excluded):
 inputs={p.name:{'path':str(p.relative_to(WORKSPACE)),'sha256':sha256(p)} for p in [TOP200,V4D,V4F,V4G,RESERVE2,CALIBRATION,ANARCI,LEGACY7087_FASTA,RF1000_FASTA,TARGET]}
 return {'schema_version':'phase2_v4_h_qc96_h0_h3_preregistration_v1','status':'FROZEN_BEFORE_ANY_REAL_GENERATION','frozen_at_utc':now(),'objective':'Generate a new-parent, label-free, QC-qualified prospective V4-H-QC96 panel before any model prediction or Docking label access.','version_boundary':{'independent_version':'V4-H-QC96','does_not_modify':['V4-D','V4-F','V4-G'],'v4_f_terminal_evidence_preserved':True},'frozen_inputs':inputs,
'parent_contract':{'eligible_parent_count':audit['eligible_parent_count'],'exact_queue_clusters':list(EXACT_QUEUE),'queue_rows':12,'selection_seed':SELECTION_SEED,'selection_order':'score_v1_1_desc_then_SHA256(seed|cluster)_asc_then_cluster; all eligible score tied 0.990','cdr_contract':'H1/H2/H3 raw spans and bytes reconstructed only from frozen ANARCI IMGT; Top-200 CDR strings forbidden','source_vs_anarci_cdr_mismatch_counts':audit['source_vs_anarci_cdr_mismatch_counts']},
'generation_contract':{'generator':'existing Node1 RFantibody RFdiffusion + ProteinMPNN only','parent_count':12,'patches':PATCHES,'modes':list(MODES),'task_count':72,'backbones_per_task':12,'sequences_per_backbone':3,'raw_records':2592,'feasibility_wording_correction':'1,440 is selected exact-unique H1 panel; raw denominator is 2,592','selected_exact_unique_per_stratum':20,'selected_exact_unique_total':1440,'cross_stratum_dedup_priority':'parent_queue_rank_then_A/B/C_then_H3/H1H3','h1_selection_seed':H1_SELECTION_SEED,'framework_fr4_bytes_protected':True,'cdr2_frozen':True,'minimum_designed_region_edits':1,'exact_exclusion_sources':['legacy7087 hash-only FASTA','RFantibody1000 FASTA','calibration exact registry','12 parent sequences'],'exclusion_hash_count_without_parents':len(excluded),'retry':'maximum two same-config pipeline invocations; failed task recomputes full 12x3 new attempt; only complete hash-closed task reusable'},
'qc_contract':{'H2':'all1440 blocker_calibrated large-scale-fast','H3':'all Fast-pass; frozen full_merged hard_fail=false; no cap/no replacement','sapiens_policy':'descriptive/review-only, not H4 hard gate','tnp_policy':'DEFERRED_THREE_STATE_NA_NO_IMPUTATION; numeric/flags blank','maximum_cpu_workers':24,'gpu_count':0},
'h4_contract':{'ready_parent':'Full-QC hard-pass>=24 and each six strata>=4','parent_selection':'first four ready by queue','candidate_selection':'first four by frozen hash per stratum','h4_selection_seed':H4_SELECTION_SEED,'output_shape':'4x6x4=96','failure':'fewer than four => FAIL no replacement/threshold change','canonical_future_delivery':['experiments/phase2_5080_v1/data_splits/pvrig_v4_h/qc96_manifest_v1.tsv','experiments/phase2_5080_v1/data_splits/pvrig_v4_h/qc96_audit_v1.json','experiments/phase2_5080_v1/data_splits/pvrig_v4_h/qc96_receipt_v1.json']},
'resource_contract':{'node':'node1','gpu_ids':[0,1,2,3],'cpu_sets':['0-7','8-15','16-23','24-31'],'maximum_gpus':4,'maximum_cpu_workers':32,'storage':str(REMOTE_ROOT)},'label_path_access':package_config()['label_path_access'],'claim_boundary':CLAIM}

def supervisor():
 return f'''#!/usr/bin/env bash
set -Eeuo pipefail
ROOT={REMOTE_ROOT}
cd "$ROOT"; mkdir -p status logs
exec 9>"$ROOT/status/pipeline.global.lock"; flock -n 9 || {{ echo pipeline_already_active >&2; exit 75; }}
python=/data1/qlyu/anaconda3/envs/boltz/bin/python3.11
"$python" scripts/run_phase2_v4_h_qc96_generation_node1.py --preflight >logs/h0_zero_work_preflight.log 2>&1
status=1
for attempt in 1 2; do
 echo "H1_ATTEMPT=$attempt $(date -Is)" | tee -a logs/pipeline.log
 if "$python" scripts/run_phase2_v4_h_qc96_generation_node1.py >>logs/h1_generation.log 2>&1; then status=0; break; fi
done
if [[ $status -ne 0 ]]; then echo "H1_FAILED_AFTER_FROZEN_RETRY $(date -Is)" | tee -a logs/pipeline.log; exit 1; fi
"$python" scripts/run_phase2_v4_h_qc96_qc_node1.py >>logs/h2_h4_qc.log 2>&1
echo "V4_H_H0_H4_PIPELINE_TERMINAL $(date -Is)" | tee -a logs/pipeline.log
'''
def monitor():
 return '''#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
while [[ ! -f "$ROOT/status/generation.complete.json" && ! -f "$ROOT/status/generation.failed.json" ]]; do
 { date -Is; uptime; nvidia-smi --id=0,1,2,3 --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits; } >>"$ROOT/logs/resource_monitor.log" 2>&1 || true
 sleep 60
done
'''

def build(outdir,force):
 parents,audit=derive_queue();tasks=build_tasks(parents);excluded=exclusions()
 if outdir.exists():
  if not force:raise FileExistsError(outdir)
  shutil.rmtree(outdir)
 for n in ['config','inputs','manifests','scripts','status','logs']:(outdir/n).mkdir(parents=True,exist_ok=True)
 write_tsv(PARENT_QUEUE,parents);write_tsv(outdir/'manifests/parent12_queue.tsv',parents);write_tsv(outdir/'manifests/generation_tasks.tsv',tasks);write_tsv(outdir/'manifests/excluded_candidate_sequence_sha256.tsv',excluded)
 shutil.copy2(ANARCI,outdir/'manifests/parent12_anarci_imgt_v1_H.csv');shutil.copy2(TARGET,outdir/'inputs/pvrig_8x6b_chainT.pdb')
 cfg=package_config();(outdir/'config/generation_config.json').write_text(json.dumps(cfg,indent=2,sort_keys=True)+'\n')
 pre=prereg(parents,audit,tasks,excluded);PREREG.parent.mkdir(parents=True,exist_ok=True);PREREG.write_text(json.dumps(pre,indent=2,sort_keys=True)+'\n');shutil.copy2(PREREG,outdir/'PREREGISTRATION.json')
 for n in ['run_phase2_v4_h_qc96_generation_node1.py','run_phase2_v4_h_qc96_qc_node1.py','make_rfantibody_hlt_framework.py']:shutil.copy2(SCRIPT_DIR/n,outdir/'scripts'/n)
 template=WORKSPACE/'docking/candidates/v2_5_pose_batch/scripts'
 for n in ['normalize_pdb_chain.py','validate_pdb_sequence.py','pdb_geometry_qc.py']:shutil.copy2(template/n,outdir/'scripts'/n)
 (outdir/'scripts/run_h0_h4_pipeline.sh').write_text(supervisor());(outdir/'scripts/monitor_resources.sh').write_text(monitor())
 for p in (outdir/'scripts').iterdir():p.chmod(0o755)
 subprocess.run(['bash','-n',str(outdir/'scripts/run_h0_h4_pipeline.sh')],check=True);subprocess.run(['bash','-n',str(outdir/'scripts/monitor_resources.sh')],check=True)
 result={'status':'PASS_H0_STATIC_PACKAGE_BUILT_NOT_FROZEN','parent_count':12,'task_count':72,'raw_records':2592,'selected_target':1440,'excluded_exact_sequence_hash_count':len(excluded),'remote_root':str(REMOTE_ROOT),'label_path_access':cfg['label_path_access'],'claim_boundary':CLAIM}
 (outdir/'H0_BUILD_AUDIT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');return result

def freeze(outdir,test_log):
 text=test_log.read_text(errors='replace');m=re.search(r'Ran\s+(\d+)\s+tests?',text)
 if not m or int(m.group(1))<12 or not re.search(r'^OK$',text,re.M):raise RuntimeError('test_log_not_12_OK')
 if (outdir/'IMPLEMENTATION_FREEZE.json').exists():raise FileExistsError('freeze_exists')
 shutil.copy2(test_log,outdir/'TEST_RESULTS.log');files=[p for p in sorted(outdir.rglob('*')) if p.is_file()]
 if any(p.is_symlink() for p in files):raise RuntimeError('static_symlink')
 value={'schema_version':'phase2_v4_h_qc96_h0_h3_implementation_freeze_v1','status':'FROZEN_BEFORE_ANY_REAL_GENERATION','frozen_at_utc':now(),'preregistration_sha256':sha256(PREREG),'parent_queue_sha256':sha256(PARENT_QUEUE),'test_log_sha256':sha256(test_log),'test_count':int(m.group(1)),'source_hashes':{n:sha256(SCRIPT_DIR/n) for n in ['build_phase2_v4_h_qc96_h0_h3_package.py','run_phase2_v4_h_qc96_generation_node1.py','run_phase2_v4_h_qc96_qc_node1.py','test_phase2_v4_h_qc96_h0_h3_package.py']},'package_hashes':{str(p.relative_to(outdir)):sha256(p) for p in files},'remote_root':str(REMOTE_ROOT),'resource_policy':package_config()['resource_policy'],'command_timeouts_seconds':package_config()['command_timeouts_seconds'],'label_path_access':package_config()['label_path_access'],'claim_boundary':CLAIM}
 FREEZE.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');shutil.copy2(FREEZE,outdir/'IMPLEMENTATION_FREEZE.json');return value

def main():
 p=argparse.ArgumentParser();p.add_argument('--outdir',type=Path,default=DEFAULT_OUTDIR);p.add_argument('--force',action='store_true');p.add_argument('--freeze',action='store_true');p.add_argument('--test-log',type=Path);a=p.parse_args()
 value=freeze(a.outdir,a.test_log) if a.freeze else build(a.outdir,a.force);print(json.dumps(value,indent=2,sort_keys=True))
if __name__=='__main__':main()
