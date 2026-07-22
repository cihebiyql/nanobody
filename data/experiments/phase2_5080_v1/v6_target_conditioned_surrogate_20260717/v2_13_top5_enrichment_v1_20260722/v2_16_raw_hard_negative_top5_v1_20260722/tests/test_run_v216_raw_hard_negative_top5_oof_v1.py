from __future__ import annotations
import importlib.util,sys,unittest
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parents[1];SPEC=importlib.util.spec_from_file_location("v216",HERE/"src/run_v216_raw_hard_negative_top5_oof_v1.py")
if SPEC is None or SPEC.loader is None:raise RuntimeError("import")
MOD=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=MOD;SPEC.loader.exec_module(MOD)

class V216Test(unittest.TestCase):
 def test_strict_oof_shapes(self)->None:
  n=100;parents=np.asarray([f"P{i//10}" for i in range(n)]);folds=np.asarray([(i//10)%5 for i in range(n)]);truth=np.column_stack((np.linspace(.4,.7,n)+.01,np.linspace(.4,.7,n)))
  base=np.column_stack([truth[:,0],truth[:,1],truth[:,1],truth[:,0]-.01,truth[:,1]-.01,truth[:,1]-.01,truth[:,0]+.01,truth[:,1]+.01,truth[:,1]+.01]);l1=np.column_stack((truth[:,0]+.005,truth[:,1]+.005,truth[:,1]+.005))
  data={"candidate_ids":[f"C{i}" for i in range(n)],"parents":parents,"folds":folds,"truth":truth,"base":base,"l1":l1,"raw":np.random.default_rng(1).normal(size=(n,6)),"weights":np.ones(n)}
  c={"data":{"expected_folds":5},"hgb_classifier":{"learning_rate":.1,"max_iter":3,"max_leaf_nodes":5,"min_samples_leaf":3,"l2_regularization":1},"extra_trees":{"n_estimators":5,"max_depth":4,"min_samples_leaf":2,"max_features":.5,"n_jobs":1}}
  scores,models,audit=MOD.run_oof(data,c)
  self.assertEqual(set(scores),set(MOD.METHODS));self.assertTrue(all(np.isfinite(x).all() for x in scores.values()));self.assertEqual(len(models),5);self.assertEqual(len(audit),5)

if __name__=="__main__":unittest.main()
