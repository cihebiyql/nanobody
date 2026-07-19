import ast,hashlib,importlib.util,json,pathlib,unittest
HERE=pathlib.Path(__file__).resolve(); ROOT=HERE.parents[1]; DRIVER=ROOT/'src/run_node1_cuda_smoke_v1_3_1.py'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
class TestDriver(unittest.TestCase):
 def test_contract_and_no_sealed_inputs(self):
  spec=importlib.util.spec_from_file_location('driver',DRIVER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  self.assertEqual((m.PHYSICAL_GPU,m.LOGICAL_GPU,m.STEPS,m.ACCUMULATION),(1,0,20,2))
  self.assertNotIn('v4_f',str(m.DATA_ROOT).lower());self.assertNotIn('test32',str(m.DATA_ROOT).lower())
  self.assertEqual(m.INTEGRATION_TRAINER_SHA,sha(ROOT/'vendor/integration/real1507_role_isolated_trainer_v1_3.py'))
  self.assertEqual(m.TRUST_RECEIPT_SHA,sha(ROOT/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json'))
  self.assertEqual(str(m.V25_SRC),'/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_2_20260718/src')
  self.assertEqual(str(m.DATA_ROOT),'/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718')
  self.assertEqual(str(m.V23),'/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718')
  self.assertEqual(str(m.TARGET),'/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt')
 def test_driver_has_real_lane_and_step_evidence(self):
  text=DRIVER.read_text();tree=ast.parse(text)
  self.assertIn('train_open_partition_fixed_epochs',text)
  self.assertIn('per_step_evidence_hashes',text)
  self.assertNotIn("(modules[2].LANE_B,'B_CLEAN_TARGET_ATTENTION')",text)
  self.assertIn("(modules[2].LANE_B,'E_DECOUPLED_CONTACT_DETACHED')",text)
  self.assertIn('torch.use_deterministic_algorithms(True)',text)
  self.assertIn("CUBLAS_WORKSPACE_CONFIG')==':4096:8'",text)
  self.assertIn("'E_DECOUPLED_CONTACT_DETACHED'",text)
  self.assertIn("'E_DECOUPLED_CONTACT_SHARED'",text)
 def test_anchor_set_is_exact_25(self):
  r=json.loads((ROOT/'vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json').read_text())
  self.assertEqual(r['partition_count'],25);self.assertEqual(len(r['files']),25);self.assertEqual(r['v4_f_test32_access_count'],0)
  for n,h in r['files'].items(): self.assertEqual(sha(ROOT/'vendor/trust_anchors'/n),h)
if __name__=='__main__':unittest.main()
