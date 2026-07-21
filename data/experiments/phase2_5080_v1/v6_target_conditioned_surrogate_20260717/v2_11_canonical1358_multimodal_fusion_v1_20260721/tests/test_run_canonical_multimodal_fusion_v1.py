from __future__ import annotations
import csv,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from fixture_utils import fixture,write_tsv,sha
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
MAT=load('v211mat2',ROOT/'src/materialize_canonical_multimodal_v1.py');RUN=load('v211run',ROOT/'src/run_canonical_multimodal_fusion_v1.py')
class Tests(unittest.TestCase):
 def test_end_to_end_and_full_s0_base(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);f=fixture(root);prepared=root/'prepared';a=MAT.parser().parse_args(['--teacher',str(f['teacher']),'--split-manifest',str(f['split']),'--structure-v4d',str(f['s4']),'--structure-v4h',str(f['sh']),'--coarse-pose',str(f['c2']),'--esm2-650m-cache',str(f['cache']),'--output-dir',str(prepared),'--expected-rows','60','--expected-train-rows','48','--expected-development-rows','12']);MAT.materialize(a)
   dev=[r for r in f['rows'] if r['parent_framework_cluster'] in {'P08','P09'}];preds=[]
   for seed in (43,97,193):
    rows=[]
    for i,r in enumerate(dev):
     delta=(seed%7)*1e-5
     rows.append({'candidate_id':r['candidate_id'],'parent_framework_cluster':r['parent_framework_cluster'],'ELASTICNET_ESM2_650M_PCA__R8':str(float(r['R_8X6B'])+delta),'ELASTICNET_ESM2_650M_PCA__R9':str(float(r['R_9E6Y'])-delta)})
    p=root/f'pred{seed}.tsv';write_tsv(p,rows);preds.extend(['--full-stage0-prediction',f'{seed}={p}'])
   table=prepared/'canonical_multimodal_open.tsv';receipt=prepared/'MATERIALIZATION_RECEIPT.json';out=root/'run';argv=['--multimodal-tsv',str(table),'--expected-multimodal-sha256',sha(table),'--materialization-receipt',str(receipt),'--expected-materialization-receipt-sha256',sha(receipt),'--esm2-650m-cache',str(f['cache']),'--output-dir',str(out),'--folds','4','--c2-alphas','0.1,1','--gbdt-min-samples-leaf','8',*preds]
   result=RUN.run(RUN.parser().parse_args(argv));self.assertEqual(result['development_rows'],12)
   metrics=json.loads((out/'METRICS.json').read_text());self.assertFalse(metrics['fusion']['development_used_for_fit_or_selection']);self.assertEqual(metrics['full9849_s0']['status'],'PASS_FULL9849_S0_BASE_ONLY')
   self.assertEqual(set(RUN.MODEL_NAMES)|{'S0_FULL9849_FROZEN_ENSEMBLE_BASE_ONLY'},set(metrics['open_development_metrics']))
   for values in metrics['open_development_metrics'].values():self.assertEqual(values['exact_min_violation_count'],0);self.assertEqual(len(values['early_enrichment']),6)
 def test_convex_weights(self):
  truth=np.asarray([[.5,.4],[.6,.5],[.7,.6]]);m2=truth+.02;s0=truth-.01;c2=truth+.01;model=RUN.fit_convex(truth,{'M2':m2,'S0':s0,'C2':c2},np.ones(3),'M2',.001);self.assertGreaterEqual(model['fallback_weight'],-1e-9);self.assertLessEqual(sum(model['weights']),1+1e-9)
if __name__=='__main__':unittest.main()
