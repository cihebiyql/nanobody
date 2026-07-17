#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SRC=Path(__file__).resolve().parent


def load(name:str):
 spec=importlib.util.spec_from_file_location(name,SRC/name);module=importlib.util.module_from_spec(spec);assert spec.loader;spec.loader.exec_module(module);return module


builder=load("build_phase2_v4_f96_dual_docking_package.py")
node1=load("prepare_phase2_v4_f96_docking_inputs_node1.py")
node23=load("stage_run_phase2_v4_f96_dual_docking_node23.py")


class V4F96DualDockingPackageTests(unittest.TestCase):
 def test_prereg_is_label_blind_and_freezes_zero_branch(self):
  p=json.loads(builder.PREREG.read_text());self.assertEqual(p["status"],"FROZEN_BEFORE_ANY_V4_F96_DOCKING_LABEL_GENERATION");self.assertFalse(p["label_access_at_freeze"]["v4_f96_docking_labels_read"]);self.assertIn("NO_ELIGIBLE_DOCKING",p["eligibility_policy"]["zero_eligible_branch"])

 def test_exact_formal_evaluator_hashes_are_bound(self):
  for key,path in builder.BOUND.items():self.assertEqual(builder.sha(path),builder.EXPECTED[key])

 def test_zero_hardpass_eligibility_keeps_all_96_without_replacement(self):
  manifest=[{"candidate_id":f"C{i:03d}","sequence_sha256":hashlib.sha256(str(i).encode()).hexdigest(),"parent_framework_cluster":f"P{i%4}","model_split":"PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"} for i in range(96)]
  rows=node1.build_eligibility(manifest,[]);self.assertEqual(len(rows),96);self.assertTrue(all(row["full_qc_hard_pass"]=="false" and row["replacement_used"]=="false" for row in rows));self.assertEqual({row["full_qc_status"] for row in rows},{"FAIL_FAST_QC_HARD_GATE"})

 def test_nonzero_future_branch_uses_all_and_only_hardpass(self):
  manifest=[{"candidate_id":"A","sequence_sha256":"a","parent_framework_cluster":"P","model_split":"S"},{"candidate_id":"B","sequence_sha256":"b","parent_framework_cluster":"P","model_split":"S"}]
  full=[{"candidate_id":"A","hard_fail":"false"},{"candidate_id":"B","hard_fail":"true"}]
  rows=node1.build_eligibility(manifest,full);self.assertEqual([row["candidate_id"] for row in rows if row["full_qc_hard_pass"]=="true"],["A"]);self.assertTrue(all(row["replacement_used"]=="false" for row in rows))

 def test_package_builds_and_hash_closes(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw);out=root/"package";freeze=root/"freeze.json";result=builder.build(out,freeze);self.assertEqual(result["status"],"PASS_V4_F96_DUAL_DOCKING_PACKAGE_HASH_CLOSED");self.assertEqual(builder.validate_package(out)["package_receipt_sha256"],result["package_receipt_sha256"])
   f=json.loads((out/"IMPLEMENTATION_FREEZE.json").read_text());self.assertEqual(f["current_expected_hard_pass_count"],0);self.assertFalse(f["zero_eligible_contract"]["label_receipt"])

 def test_node23_waiter_checks_zero_before_prediction_and_v4d(self):
  text=builder.NODE23_TEMPLATE.read_text();zero=text.index("if zero_eligibility");prediction=text.index("prediction_gate 2>/dev/null",zero);v4d=text.index("source_terminal 2>/dev/null",prediction);self.assertLess(zero,prediction);self.assertLess(prediction,v4d);self.assertIn("NO_ELIGIBLE_DOCKING",text);self.assertIn("label_receipt_produced':False",text);self.assertIn("@ZERO_ELIGIBILITY_RECEIPT_SHA@",text)

 def test_zero_branch_never_invokes_node23_runner(self):
  text=builder.NODE23_TEMPLATE.read_text();zero_start=text.index('if [[ "$hard_pass_count" == 0 ]]');zero_end=text.index("\n   fi\n",zero_start);branch=text[zero_start:zero_end];self.assertNotIn('"$RUNNER"',branch);self.assertIn("exit 0",branch)

 def test_no_arbitrary_command_wrapper_or_eval(self):
  for path in (builder.NODE1,builder.NODE23,builder.DELIVER,builder.NODE1_TEMPLATE,builder.NODE23_TEMPLATE):
   text=path.read_text();self.assertNotIn("os.system(",text);self.assertNotIn("shell=True",text);self.assertNotIn('exec "$@"',text);self.assertNotIn("eval ",text)

 def test_label_schema_exactly_matches_formal_evaluator(self):
  expected=["candidate_id","sequence_sha256","parent_framework_cluster","model_split","docking_status","R_dual_min","successful_seed_count_8X6B","successful_seed_ids_8X6B","successful_seed_count_9E6Y","successful_seed_ids_9E6Y","independent_receptor_docking","technical_failure_reason"]
  self.assertEqual(node23.LABEL_FIELDS,expected)

 def test_future_protocol_is_independent_dual_fixed_seed_top8(self):
  self.assertEqual(node23.SEEDS,(917,1931,3253));self.assertEqual(node23.CONFORMATIONS,("8x6b","9e6y"));source=builder.NODE23.read_text();self.assertIn('len(complete)<=8',source);self.assertIn('fewer_than_4_complete_top8_models',source)

 def test_shell_templates_have_only_declared_placeholders(self):
  self.assertEqual(builder.NODE1_TEMPLATE.read_text().count("@NODE1_RUNNER_SHA@"),1);self.assertEqual(builder.NODE23_TEMPLATE.read_text().count("@NODE23_RUNNER_SHA@"),1)
  for path in (builder.NODE1_TEMPLATE,builder.NODE23_TEMPLATE):self.assertEqual(path.read_text().count("@PREREG_SHA@"),1);self.assertEqual(path.read_text().count("@FREEZE_SHA@"),1)
  self.assertEqual(builder.NODE23_TEMPLATE.read_text().count("@ZERO_ELIGIBILITY_RECEIPT_SHA@"),1)


if __name__=="__main__":unittest.main()
