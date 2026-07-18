from __future__ import annotations
import csv,gzip,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path

MODULE_PATH=Path(__file__).parents[1]/'src/extract_v4h_adaptive_multiseed_contact_teacher_v2.py'
SPEC=importlib.util.spec_from_file_location('adaptive_teacher_v2',MODULE_PATH)
MOD=importlib.util.module_from_spec(SPEC); assert SPEC.loader;sys.modules['adaptive_teacher_v2']=MOD;SPEC.loader.exec_module(MOD)

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seqhash(s): return hashlib.sha256(s.encode('ascii')).hexdigest()
def write_tsv(path,fields,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def read_gz(path):
 with gzip.open(path,'rt',newline='',encoding='utf-8') as f:return list(csv.DictReader(f,delimiter='\t'))
def atom(serial,residue,chain,number,x,y,z):
 return f"ATOM  {serial:5d}  CA  {residue:>3s} {chain}{number:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C\n"

class AdaptiveTeacherTests(unittest.TestCase):
 def build_fixture(self,base):
  root=base/'raw'; root.mkdir(); seq='ACD'; aa3=['ALA','CYS','ASP']
  specs={
   'A3':('DUAL_3_SEED','917,1931,3253','917,1931,3253',''),
   'B2':('DUAL_2_SEED','917,1931,3253','917,1931','9e6y:s3253:SCORING:overlay'),
   'C1':('DUAL_1_SEED','917','917',''),
   'NA':('TECHNICAL_INCOMPLETE','','917','8x6b:s917:FAILED_MAX_ATTEMPTS'),
  }
  candidates=[]; rankings=[]
  for i,(cid,(tier,left,right,reason)) in enumerate(specs.items(),1):
   candidates.append({'candidate_id':cid,'sequence':seq,'sequence_sha256':seqhash(seq),'parent_framework_cluster':f'P{i}'})
   count={'DUAL_3_SEED':'3','DUAL_2_SEED':'2','DUAL_1_SEED':'1','TECHNICAL_INCOMPLETE':'0'}[tier]
   rankings.append({'candidate_id':cid,'sequence_sha256':seqhash(seq),'parent_framework_cluster':f'P{i}',
    'target_patch_id':'A_CENTER','design_mode':'H3','docking_evidence_tier':tier,
    'successful_seed_count_8X6B':str(len(left.split(','))) if left else '0','successful_seed_ids_8X6B':left,
    'successful_seed_count_9E6Y':str(len(right.split(','))) if right else '0','successful_seed_ids_9E6Y':right,
    'median_score_8X6B':'0.6' if tier!='TECHNICAL_INCOMPLETE' else '',
    'median_score_9E6Y':'0.5' if tier!='TECHNICAL_INCOMPLETE' else '',
    'R_dual_min':'0.5' if tier!='TECHNICAL_INCOMPLETE' else '',
    'seed_dispersion_max':'0.1' if tier!='TECHNICAL_INCOMPLETE' else '',
    'confidence_adjusted_score':'0.4' if tier!='TECHNICAL_INCOMPLETE' else '',
    'technical_reasons':reason,'ranking_release':'final','claim_boundary':'computational','rank':str(i) if tier!='TECHNICAL_INCOMPLETE' else ''})
  write_tsv(root/MOD.CANDIDATES_PATH,list(candidates[0]),candidates)
  write_tsv(root/MOD.RANKING_PATH,list(rankings[0]),rankings)
  by_seed={917:list(specs),1931:['A3','B2'],3253:['A3','B2']}
  serial=1
  for seed,cids in by_seed.items():
   jobs=[]
   for cid in cids:
    for receptor in MOD.RECEPTORS:
     jid=f'{cid}_{receptor}_{seed}'; jhash=hashlib.sha256(jid.encode()).hexdigest()
     job={'job_id':jid,'entity_type':'candidate','entity_id':cid,'conformation':receptor,'seed':str(seed),
      'sequence_sha256':seqhash(seq),'cdr1_range':'1','cdr2_range':'2','cdr3_range':'3',
      'vhh_chain':'A','receptor_chain':'T','job_hash':jhash}
     jobs.append(job)
     selected=(cid=='A3') or (cid=='B2' and seed in (917,1931)) or (cid=='C1' and seed==917)
     if not selected:
      # Explicitly unusable bytes prove asymmetric/technical job results are never opened.
      p=root/'results'/jid/'job_result.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('not-json')
      continue
     result_path=root/'results'/jid/'job_result.json';result_path.parent.mkdir(parents=True,exist_ok=True)
     models=[];scores=[]
     for pose_i in range(4):
      pose=root/'runs'/jid/f'cluster_{pose_i+1}_model_1.pdb.gz';pose.parent.mkdir(parents=True,exist_ok=True)
      lines=[]
      for ix,res in enumerate(aa3,1): lines.append(atom(serial,res,'A',ix,10.0*ix,0,0));serial+=1
      lines.append(atom(serial,'SER','T',71,10,0,3));serial+=1
      # residue 3 -> PVRIG 90: seed917 last two poses, 1931 all, 3253 none
      near=(seed==1931) or (seed==917 and pose_i>=2)
      lines.append(atom(serial,'HIS','T',90,30,0,3 if near else 30));serial+=1
      with gzip.open(pose,'wt',encoding='ascii') as f:f.writelines(lines)
      rel=str(pose.relative_to(root));models.append(rel)
      scores.append({'pose':f'/inaccessible/{pose.name}','haddock_io':{'score':-100+pose_i}})
     result_path.write_text(json.dumps({'state':'SUCCESS','job_id':jid,'job_hash':jhash,'entity_id':cid,
      'dock_conformation':receptor,'seed':seed,'selected_models':models,'pose_scores':scores}))
   write_tsv(root/MOD.MANIFEST_PATHS[seed],list(jobs[0]),jobs)
  upstream={'status':'PASS','final_ranking_sha256':digest(root/'release/fake_stage2.tsv') if (root/'release/fake_stage2.tsv').exists() else '0'*64}
  (root/MOD.UPSTREAM_RECEIPT_PATH).write_text(json.dumps(upstream))
  actual={}
  for rel in [MOD.RANKING_PATH,MOD.UPSTREAM_RECEIPT_PATH,MOD.CANDIDATES_PATH,*MOD.MANIFEST_PATHS.values()]:
   actual[rel]={'sha256':digest(root/rel)}
  reconciliation={'schema_version':'test','status':'PASS_RECONCILED_V4H_ADAPTIVE_TERMINAL_CLOSURE',
   'upstream_receipt':{'sha256':digest(root/MOD.UPSTREAM_RECEIPT_PATH)},'actual_files':actual,
   'selected_common_jobs':12,'selected_common_job_identity_mismatches':0}
  recon=base/'reconciliation.json';recon.write_text(json.dumps(reconciliation,sort_keys=True))
  expected_hashes={'raw_candidates':digest(root/MOD.CANDIDATES_PATH),'final_ranking':digest(root/MOD.RANKING_PATH),
   'upstream_receipt':digest(root/MOD.UPSTREAM_RECEIPT_PATH),'reconciliation_receipt':digest(recon)}
  for seed,rel in MOD.MANIFEST_PATHS.items():expected_hashes[f'manifest_seed{seed}']=digest(root/rel)
  contract={'schema_version':f'{MOD.SCHEMA_VERSION}_contract','status':'FROZEN_PRE_EXTRACTION','canonical_raw_root':str(root),
   'implementation':{'adaptive_extractor_sha256':digest(MODULE_PATH),'base_stage1_extractor_sha256':MOD.BASE_EXTRACTOR_SHA256},
   'execution':{'workers':2},
   'contact_definition':{'contact_cutoff_angstrom':4.5,'top_k':8,'minimum_poses':4,'receptors':list(MOD.RECEPTORS),'available_seeds':list(MOD.EXPECTED_SEEDS)},
   'aggregation':{'dual_seed_scope':'intersection_of_ranking_declared_successful_seed_ids','pose_rank_weight':'normalized_1_over_log2_rank_plus_1',
    'seed_weighting':'equal_over_paired_successful_seeds','absent_union_pair':'observed_zero_within_successful_paired_seed',
    'pair_variance':'population','uncertainty_weight':'1/(1+4*variance)','residue_marginal':'pose_weighted_any_pvrig_contact_then_equal_seed_mean'},
   'expected_counts':{'candidates':4,'tier_counts':{'DUAL_3_SEED':1,'DUAL_2_SEED':1,'DUAL_1_SEED':1,'TECHNICAL_INCOMPLETE':1},
    'manifest_rows':{'917':8,'1931':4,'3253':4},'selected_paired_jobs':12,'valid_receptor_seed_asymmetry_candidates':1},
   'expected_sha256':expected_hashes}
  contract_path=base/'contract.json';contract_path.write_text(json.dumps(contract,sort_keys=True))
  return root,contract_path,recon

 def test_end_to_end_aggregates_paired_seeds_and_preserves_na(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);root,contract,recon=self.build_fixture(base)
   before={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
   result=MOD.extract(root,contract,recon,base/'out',workers=2)
   after={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
   self.assertEqual(before,after);self.assertEqual(result['valid_candidate_rows'],3);self.assertEqual(result['selected_paired_job_rows'],12)
   candidates={r['candidate_id']:r for r in read_gz(base/'out'/MOD.CANDIDATE_OUTPUT)}
   self.assertEqual(candidates['A3']['development_reliability_tier'],'A')
   self.assertEqual(candidates['B2']['paired_seed_ids'],'917,1931')
   self.assertEqual(candidates['B2']['receptor_seed_set_asymmetric'],'1')
   self.assertEqual(candidates['NA']['teacher_state'],MOD.INCOMPLETE_STATE)
   for f in ['paired_seed_count',*MOD.RANKING_NUMERIC_FIELDS]:self.assertEqual(candidates['NA'][f],'')
   receptors=[r for r in read_gz(base/'out'/MOD.RECEPTOR_OUTPUT) if r['candidate_id']=='B2']
   left=next(r for r in receptors if r['receptor']=='8x6b')
   self.assertEqual(left['declared_successful_seed_ids'],'917,1931,3253');self.assertEqual(left['excluded_unpaired_seed_ids'],'3253')
   pair=next(r for r in read_gz(base/'out'/MOD.PAIR_OUTPUT) if r['candidate_id']=='B2' and r['receptor']=='8x6b' and r['vhh_sequence_index']=='3' and r['pvrig_uniprot_position']=='90')
   vals=[float(x.split(':')[1]) for x in pair['seed_contact_values'].split(';')]
   self.assertAlmostEqual(float(pair['contact_target_mean']),sum(vals)/2,places=8)
   self.assertGreater(float(pair['contact_target_variance']),0)
   residue=next(r for r in read_gz(base/'out'/MOD.RESIDUE_OUTPUT) if r['candidate_id']=='B2' and r['receptor']=='8x6b' and r['vhh_sequence_index']=='3')
   self.assertEqual(residue['seed_marginal_values'],pair['seed_contact_values'])
   audit=json.loads((base/'out'/MOD.AUDIT_OUTPUT).read_text())
   self.assertEqual(audit['counts']['valid_receptor_seed_asymmetry_candidates'],1)
   self.assertEqual(audit['counts']['excluded_unpaired_or_technical_job_results_opened'],0)

 def test_dry_run_does_not_open_pose_contents_or_create_output(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);root,contract,recon=self.build_fixture(base)
   out=base/'out';r=MOD.extract(root,contract,recon,out,workers=2,dry_run=True)
   self.assertEqual(r['status'],'PASS_ADAPTIVE_READ_ONLY_DRY_RUN');self.assertEqual(r['pose_coordinate_files_opened'],0);self.assertFalse(out.exists())

 def test_contract_changes_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);root,contract,recon=self.build_fixture(base)
   d=json.loads(contract.read_text());d['aggregation']['uncertainty_weight']='1/(1+variance)';contract.write_text(json.dumps(d))
   with self.assertRaisesRegex(MOD.AdaptiveContactError,'uncertainty_changed'):
    MOD.extract(root,contract,recon,base/'out',dry_run=True)

 def test_outputs_are_byte_deterministic(self):
  with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
   a=Path(a);b=Path(b);ra,ca,xa=self.build_fixture(a);rb,cb,xb=self.build_fixture(b)
   MOD.extract(ra,ca,xa,a/'out',workers=2);MOD.extract(rb,cb,xb,b/'out',workers=2)
   for name in [MOD.PAIR_OUTPUT,MOD.RESIDUE_OUTPUT,MOD.RECEPTOR_OUTPUT,MOD.CANDIDATE_OUTPUT,MOD.JOB_OUTPUT]:
    self.assertEqual(digest(a/'out'/name),digest(b/'out'/name),name)

 def test_base_extractor_hash_is_pinned(self):
  module=MOD.load_base_extractor();self.assertEqual(digest(Path(module.__file__)),MOD.BASE_EXTRACTOR_SHA256)

if __name__=='__main__':unittest.main()
