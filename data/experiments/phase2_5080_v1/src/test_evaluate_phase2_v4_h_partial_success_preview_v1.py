import csv,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path

MODULE_PATH=Path(__file__).with_name("evaluate_phase2_v4_h_partial_success_preview_v1.py")
SPEC=importlib.util.spec_from_file_location("v4h_partial_eval",MODULE_PATH);module=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=module;SPEC.loader.exec_module(module)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class PartialEvaluationTests(unittest.TestCase):
    def fixture(self,root,bad_terminal=False,bad_incomplete=False):
        rows=[]
        for i in range(24): rows.append({"candidate_id":f"C{i:02d}","sequence_sha256":f"{i:064x}","parent_framework_cluster":"P1" if i<12 else "P2","target_patch_id":["A","B","C"][i%3],"design_mode":["H3","H1H3"][i%2]})
        teacher=root/"teacher.tsv"
        with teacher.open("w",newline="") as h:
            fields=[*rows[0],"preview_state","R_dual_min","partial_incomplete_reason"];w=csv.DictWriter(h,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader()
            for i,row in enumerate(rows): w.writerow({**row,"preview_state":"PARTIAL_INCOMPLETE" if i==23 else "PARTIAL_ANALYZABLE","R_dual_min":"0.9" if i==23 and bad_incomplete else ("" if i==23 else str(0.5+i/100)),"partial_incomplete_reason":"missing" if i==23 else ""})
        seq=root/"seq.tsv";struct=root/"struct.tsv"
        for path,field,reverse in ((seq,"predicted_R_dual_min_sequence_only",False),(struct,"predicted_R_dual_min_structure_only",True)):
            with path.open("w",newline="") as h:
                fields=[*rows[0],field];w=csv.DictWriter(h,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader()
                for i,row in enumerate(rows): w.writerow({**row,field:str(0.5+(23-i if reverse else i)/100)})
        prereg=root/"prereg.json";prereg.write_text("{}\n")
        metric=Path(__file__).with_name("evaluate_phase2_v4_h_research1320_sequence_vs_structure_terminal_v1.py")
        receipt=root/"snapshot.json";receipt.write_text(json.dumps({"status":"COMPLETE_PARTIAL_DEVELOPMENT_PREVIEW_SNAPSHOT_NOT_TERMINAL","campaign_terminal":bad_terminal,"candidate_rows":24,"outputs":{"partial_teacher":{"sha256":sha(teacher)}},"new_completions_after_snapshot_included":False,"model_or_threshold_changes_permitted_from_preview":False})+"\n")
        return teacher,receipt,seq,struct,prereg,metric
    def run_eval(self,root,**kw):
        t,r,s,u,p,m=self.fixture(root,**kw)
        return module.evaluate(t,r,s,u,p,m,root/"out",expected_teacher_sha256=sha(t),expected_snapshot_receipt_sha256=sha(r),expected_sequence_sha256=sha(s),expected_structure_sha256=sha(u),expected_prereg_sha256=sha(p),expected_terminal_evaluator_sha256=sha(m),expected_rows=24,bootstrap_replicates=50,bootstrap_seed=7)
    def test_partial_preview_evaluates_without_terminal_claim(self):
        with tempfile.TemporaryDirectory() as d:
            result=self.run_eval(Path(d));self.assertEqual(result["analyzable_rows"],23);self.assertFalse(result["campaign_terminal"]);self.assertTrue(result["terminal_evaluation_still_required"])
    def test_rejects_terminal_flag(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(module.PreviewError,"snapshot_must_be_nonterminal"): self.run_eval(Path(d),bad_terminal=True)
    def test_rejects_incomplete_numeric_target(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(module.PreviewError,"incomplete_target_not_empty"): self.run_eval(Path(d),bad_incomplete=True)

if __name__=="__main__": unittest.main()
