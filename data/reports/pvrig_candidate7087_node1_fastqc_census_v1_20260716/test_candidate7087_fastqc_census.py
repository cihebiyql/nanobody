#!/usr/bin/env python3
import hashlib,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MAT=ROOT/'materialize_candidate7087_fastqc_input.py'
SPEC=importlib.util.spec_from_file_location('census_materializer',MAT);MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class CensusTests(unittest.TestCase):
 def test_materializer_replay_closes_7087_and_40(self):
  with tempfile.TemporaryDirectory() as td:
   old=sys.argv;sys.argv=[str(MAT),str(Path(td)/'input')]
   try:MOD.main()
   finally:sys.argv=old
   out=Path(td)/'input';audit=json.loads((out/'INPUT_AUDIT.json').read_text())
   self.assertEqual((audit['candidate_count'],audit['parent_count']),(7087,40))
   self.assertEqual(sha(out/'candidate7087.fasta'),'82d89ca0b35f38e87a26b9ccca9ed97ce64255db33250ddb694fe2a072494b88')
   self.assertEqual(sha(out/'candidate7087_lineage.tsv'),'2000415243a044131e1e12704d3a1e0f31b5b84d790d14fdeee4af4db5aea777')
   self.assertEqual(audit['label_path_access'],{'docking':0,'experimental':0,'model_score':0,'v4_d_geometry':0,'v4_f_labels':0})
 def test_worker_is_ssd_only_bounded_and_receipt_last(self):
  text=(ROOT/'run_candidate7087_fastqc_census_node1.py').read_text()
  self.assertNotIn('/data/qlyu',text);self.assertIn('CHUNK_JOBS=16; WORKERS_PER_CHUNK=2',text);self.assertIn("'maximum_cpu_workers':32",text)
  self.assertLess(text.index('merge(lineage,specs,markers)'),text.index("atomic_json(OUTPUTS/'candidate7087_node1_fastqc_census_v1.receipt.json'"))
  self.assertLess(text.index('receipt=validate_terminal'),text.index("atomic_json(OUTPUTS/'candidate7087_node1_fastqc_census_v1.receipt.json'"))
 def test_freeze_and_launcher_bind_prereg_runtime_and_resource_policy(self):
  freeze=json.loads((ROOT/'IMPLEMENTATION_FREEZE.json').read_text())
  self.assertEqual(freeze['preregistration_sha256'],'0112cd909702d85f760ebef92b7bc1ab5db83705c5c8546e45cdfe21b08c175b')
  self.assertEqual(freeze['runtime_manifest_sha256'],'603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d')
  self.assertEqual(freeze['resource_policy']['maximum_cpu_workers'],32)
  launcher=(ROOT/'launch_candidate7087_fastqc_census_node1.sh').read_text();self.assertNotIn('/data/qlyu',launcher)
  self.assertIn(sha(ROOT/'run_candidate7087_fastqc_census_node1.py'),launcher)
if __name__=='__main__':unittest.main()
