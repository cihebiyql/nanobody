import json,math,subprocess,sys,tempfile,unittest
from pathlib import Path
class T(unittest.TestCase):
 def test_real_result_contract(self):
  d=json.loads((Path(__file__).parent/'SOFTMIN_EXACTMIN_DIAGNOSTIC.json').read_text())
  self.assertEqual(d['input']['rows'],1507);self.assertEqual(d['input']['parents'],31)
  self.assertEqual(d['v4_f_test32_access_count'],0)
  self.assertAlmostEqual(d['parameters']['theoretical_max_bias'],.02*math.log(2),places=12)
  frozen=[x for x in d['within_parent_pair_direction'] if abs(x['minimum_abs_exact_pair_delta']-d['parameters']['delta_noise'])<1e-12][0]
  self.assertEqual(frozen['sign_flip_count'],0)
  self.assertGreater(d['within_parent_pair_direction'][0]['sign_flip_count'],0)
  self.assertEqual(d['decision'],'USE_EXACT_MIN_FOR_RANK_LOSS_KEEP_SOFTMIN_ONLY_AS_SCALAR_AUXILIARY_DIAGNOSTIC')
if __name__=='__main__':unittest.main()
