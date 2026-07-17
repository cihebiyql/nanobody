#!/usr/bin/env python3
import csv,importlib.util,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);assert spec and spec.loader;m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
HERE=Path(__file__).resolve().parent
B=load('support_v4a_720_builder',HERE/'build_phase2_support_v4_a_acquisition720_full_qc_package.py')
R=load('support_v4a_720_runner',HERE/'run_phase2_support_v4_a_acquisition720_full_qc_node1.py')

class Tests(unittest.TestCase):
 def build(self,root):
  out=root/'package';freeze=root/'freeze.json';result=B.build_package(out,freeze);self.assertEqual(result['status'],'PASS');return out
 def test_frozen_input_exact_counts_and_no_label_columns(self):
  rows,_=B.validate_sources();self.assertEqual(len(rows),720);self.assertEqual(len({r['parent_framework_cluster'] for r in rows}),20)
  self.assertEqual({r['parent_role'] for r in rows},{'OPEN_TRAIN'})
  for f in B.FIELDS:self.assertFalse(any(t in f.lower() for t in R.FORBIDDEN_FIELD_TOKENS),f)
 def test_role_patch_and_unique_cdr3_closure(self):
  rows,_=B.validate_sources();from collections import Counter
  self.assertEqual(Counter(r['acquisition_role'] for r in rows),Counter({'FUTURE_NODE1_TEACHER_ACQUISITION':480,'LABEL_FREE_AUDIT':240}))
  self.assertEqual(Counter(r['target_patch_id'] for r in rows),Counter({'A_CENTER':240,'B_LOWER':240,'C_CROSS':240}))
  self.assertEqual(len({r['cdr3'] for r in rows}),720)
 def test_build_validate_and_receipt_last(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t));result=B.validate_package(out);self.assertEqual(result['candidate_count'],720)
   receipt=out/'PACKAGE_RECEIPT.json';self.assertGreaterEqual(receipt.stat().st_mtime_ns,max(p.stat().st_mtime_ns for p in out.rglob('*') if p.is_file() and p!=receipt))
 def test_runner_fixture_preflight_closes_without_runtime(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t));result=R.preflight(out,verify_runtime=False);self.assertEqual(result['status'],'PASS_ZERO_WORK_PREFLIGHT');self.assertEqual(result['candidate_count'],720)
 def test_mutated_manifest_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t));p=out/'inputs'/B.DEFAULT_MANIFEST.name;p.write_text(p.read_text().replace('C0009','C9999',1))
   with self.assertRaises(RuntimeError):R.validate_input_contract(out)
 def test_extra_docking_field_rejected_by_exact_schema(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t));p=out/'inputs'/B.DEFAULT_MANIFEST.name
   lines=p.read_text().splitlines();lines[0]+='\tdocking_score';lines[1]+='\t9.9';p.write_text('\n'.join(lines)+'\n')
   with self.assertRaises(RuntimeError):R.validate_input_contract(out)
 def test_tampered_package_payload_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t));p=out/'inputs/support_v4_a_acquisition720.fasta';p.write_text(p.read_text()+'\n')
   with self.assertRaises(RuntimeError):B.validate_package(out)
 def test_generated_launcher_and_runner_smoke(self):
  with tempfile.TemporaryDirectory() as t:
   out=self.build(Path(t))
   a=subprocess.run([str(out/'launch_full_qc_node1.sh'),'--smoke-test'],text=True,capture_output=True,check=False);self.assertEqual(a.returncode,0,a.stderr);self.assertEqual(json.loads(a.stdout)['maximum_cpu'],32)
   b=subprocess.run([sys.executable,str(out/B.DEFAULT_RUNNER.name),'--smoke-test'],text=True,capture_output=True,check=False);self.assertEqual(b.returncode,0,b.stderr);self.assertEqual(json.loads(b.stdout)['gpu'],0)
 def test_screen_command_frozen_resources_and_no_tnp(self):
  c=R.screen_command('full');s=' '.join(c);self.assertIn('--full-qc-limit 0',s);self.assertIn('--full-chunk-jobs 16',s);self.assertIn('--workers 2',s);self.assertNotIn('--full-run-tnp',s);self.assertNotIn('/data/qlyu/',s)

if __name__=='__main__':unittest.main()
