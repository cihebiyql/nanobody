import csv,hashlib,importlib.util,json,tempfile,unittest
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def mod(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
run=mod('formalrun',ROOT/'src/run_formal_split_v1.py'); met=mod('formalmetrics',ROOT/'src/formal_metrics_v1.py'); sched=mod('formalsched',ROOT/'src/run_formal_job_graph_v1.py')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
class T(unittest.TestCase):
 def test_freeze_contract(self):
  f=json.loads((ROOT/'FORMAL_TRAINING_FREEZE_V1.json').read_text());self.assertEqual(f['job_counts']['TOTAL'],301);self.assertEqual(f['outer_ensemble_seeds'],[43,97,193]);self.assertFalse(f['launch_authorized']);self.assertEqual(f['metrics_access']['v4_f_test32_access_count'],0)
 def test_package_graph(self):
  p=ROOT/'prepared/nonlaunching_package_v1_3';m=json.loads((p/'PACKAGE_MANIFEST.json').read_text());g=json.loads((p/'node1_bundle/plan/job_graph.json').read_text());self.assertEqual(sha(p/'node1_bundle/plan/job_graph.json'),m['job_graph_sha256']);self.assertEqual(Counter(x['kind'] for x in g['jobs']),Counter({'GPU_INNER':225,'GPU_OUTER_REFIT':45,'CPU_SELECT':15,'CPU_OUTER_ENSEMBLE_EVAL':15,'CPU_FINAL_COLLECT':1}));self.assertEqual({x['physical_gpu'] for x in g['jobs'] if 'physical_gpu'in x},{1,2,4,5})
 def test_no_forbidden_inputs_or_sealed(self):
  g=json.loads((ROOT/'prepared/nonlaunching_package_v1_3/node1_bundle/plan/job_graph.json').read_text())
  for j in g['jobs']:
   t=' '.join(j['command']).lower();self.assertNotIn('v4_f',t);self.assertNotIn('test32',t);self.assertNotIn('--structure-dim',t);self.assertNotIn('--ridge-alpha',t)
 def test_variant_split_only_changes_epoch_plus_provenance(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);src=td/'s.json';base={'schema_version':'pvrig_v2_4_open_base_split_manifest_v1','fixed_epochs':8,'open_only':True,'v4_f_test32_access_count':0};src.write_text(json.dumps(base));p=run.materialize_split(src,td/'o','H2');x=json.loads(p.read_text());self.assertEqual(x['fixed_epochs'],16);self.assertEqual(x['formal_hparam_id'],'H2');self.assertEqual({k:v for k,v in x.items() if k in base and k!='fixed_epochs'},{k:v for k,v in base.items() if k!='fixed_epochs'})
 def _training_job(self,d,h,fold,pred_offset):
  d.mkdir();truth=d/f't{fold}.tsv'; fields=['candidate_id','R_8X6B','R_9E6Y','R_dual_min','parent_framework_cluster']
  with truth.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields,delimiter='\t');w.writeheader();w.writerow({'candidate_id':f'c{fold}','R_8X6B':.3+fold*.01,'R_9E6Y':.4+fold*.01,'R_dual_min':.3+fold*.01,'parent_framework_cluster':f'p{fold}'})
  p=d/'score_predictions_no_metrics.tsv';fields=['candidate_id','neural_R8','neural_R9','neural_Rdual','contact_score_R8','contact_score_R9']
  with p.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields,delimiter='\t');w.writeheader();r8=.3+fold*.01+pred_offset;r9=.4+fold*.01+pred_offset;w.writerow({'candidate_id':f'c{fold}','neural_R8':r8,'neural_R9':r9,'neural_Rdual':min(r8,r9),'contact_score_R8':'','contact_score_R9':''})
  r={'status':'PASS_FORMAL_INNER_TRAINING','phase':'inner','lane':{'variant':'B_CLEAN_TARGET_ATTENTION'},'outer_fold':0,'inner_fold':fold,'formal_seed':43,'formal_hparam_id':h,'input_receipt':{'files':{'training_tsv':{'path':str(truth)}}},'artifacts':{'predictions_no_metrics':{'sha256':sha(p)}}};(d/'RESULT.json').write_text(json.dumps(r));return d
 def test_inner_selection_uses_inner_only(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);ds=[]
   for h,off in [('H0',.05),('H1',0),('H2',-.03)]:
    for i in range(5):ds.append(self._training_job(td/f'{h}{i}',h,i,off))
   out=td/'out';a=type('A',(),{'output_dir':out,'input_dir':ds,'lane':'B_CLEAN_TARGET_ATTENTION','outer_fold':0,'job_id':'select'})();met.select(a);r=json.loads((out/'RESULT.json').read_text());self.assertEqual(r['selected_hparam_id'],'H1');self.assertEqual(r['prediction_metrics_scope'],'inner_only')
 def test_valid_result_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'r.json';job={'expected_result':str(p),'job_id':'j'};p.write_text(json.dumps({'status':'PASS_X','job_id':'j','v4_f_test32_access_count':0}));self.assertTrue(sched.valid_result(job));p.write_text(json.dumps({'status':'PASS_X','job_id':'wrong','v4_f_test32_access_count':0}));self.assertFalse(sched.valid_result(job))
if __name__=='__main__':unittest.main()
