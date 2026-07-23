import importlib.util,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
SPEC=importlib.util.spec_from_file_location("priority",ROOT/"src/run_priority_s0_stage0_top7500_v1.py");M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)
class T(unittest.TestCase):
 def test_combination_and_exact_quota(self):
  rows=[]
  for i in range(10):rows.append({"candidate_id":f"c{i}","sequence":"ACD","sequence_sha256":"x","parent_framework_cluster":f"p{i%2}","cdr3":"D","target_patch_id":"t","design_method":"g","tnp_review_tier":"CLEAR","stage0_prior_rank":str(i+1)})
  s0=np.asarray([[1-i/10,1-i/10-.01] for i in range(10)])
  full,top=M.combine(rows,s0,3);self.assertEqual(len(top),3);self.assertEqual(top[0]["candidate_id"],"c0");self.assertTrue(all(float(r["S0_Rdual_exact_min"])==min(float(r["S0_R8"]),float(r["S0_R9"])) for r in full))
if __name__=="__main__":unittest.main()
