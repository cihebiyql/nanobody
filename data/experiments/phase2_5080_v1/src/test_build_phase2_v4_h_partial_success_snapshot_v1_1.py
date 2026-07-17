import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v4_h_partial_success_snapshot_v1_1.py")
SPEC = importlib.util.spec_from_file_location("v4h_partial_snapshot_v1_1", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class PartialSnapshotTests(unittest.TestCase):
    def fixture(self, root: Path, *, mutate_result: bool = False):
        (root/"inputs").mkdir(); (root/"manifests").mkdir(); (root/"status/jobs").mkdir(parents=True); (root/"results").mkdir()
        candidates=[
            {"candidate_id":"C1","sequence_sha256":"1"*64,"parent_framework_cluster":"P1","target_patch_id":"A","design_mode":"H3"},
            {"candidate_id":"C2","sequence_sha256":"2"*64,"parent_framework_cluster":"P2","target_patch_id":"B","design_mode":"H1H3"},
        ]
        with (root/"inputs/candidates_290.tsv").open("w",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(candidates[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(candidates)
        jobs=[]
        for candidate in candidates:
            for conf in ("8x6b","9e6y"):
                jobs.append({"job_id":f"{candidate['candidate_id']}_{conf}","entity_type":"candidate","entity_id":candidate["candidate_id"],"conformation":conf,"seed":917})
        with (root/"manifests/docking_jobs.tsv").open("w",newline="") as h:
            w=csv.DictWriter(h,fieldnames=list(jobs[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(jobs)
        for job in jobs[:3]:
            (root/f"status/jobs/{job['job_id']}.json").write_text(json.dumps({"status":"SUCCESS"}))
            d=root/f"results/{job['job_id']}";d.mkdir();(d/"job_result.json").write_text(json.dumps({"state":"SUCCESS","score":0.5 if job['conformation']=="8x6b" else 0.6}))
        adaptive=root/"adaptive.py";adaptive.write_text("# synthetic\n")
        scorer=root/"scorer.py";scorer.write_text("# synthetic\n")
        return adaptive,scorer

    def test_captures_only_success_set_and_requires_dual_for_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adaptive,scorer=self.fixture(root)
            result=module.build_snapshot(root,adaptive,scorer,root/"out",score_result=lambda payload,_conf:payload["score"])
            self.assertEqual(result["successful_jobs_captured"],3)
            self.assertEqual(result["preview_state_counts"],{"PARTIAL_ANALYZABLE":1,"PARTIAL_INCOMPLETE":1})
            self.assertFalse(result["campaign_terminal"])
            with (root/"out/partial_candidate_teacher_snapshot_v1_1.tsv").open(newline="") as h: rows=list(csv.DictReader(h,delimiter="\t"))
            self.assertEqual(rows[0]["R_dual_min"],"0.5")
            self.assertEqual(rows[1]["R_dual_min"],"")
            self.assertEqual(result["score_valid_jobs"],3)
            self.assertEqual(result["score_invalid_jobs"],0)

    def test_scoring_invalid_is_explicit_and_not_numeric(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adaptive,scorer=self.fixture(root)
            def score(payload,_conf):
                if payload["score"]==0.6:
                    raise ValueError("frozen_gate_failed")
                return payload["score"]
            result=module.build_snapshot(root,adaptive,scorer,root/"out",score_result=score)
            self.assertEqual(result["score_valid_jobs"],2)
            self.assertEqual(result["score_invalid_jobs"],1)
            with (root/"out/successful_jobs_snapshot_v1_1.tsv").open(newline="") as handle:
                rows=list(csv.DictReader(handle,delimiter="\t"))
            invalid=[row for row in rows if row["snapshot_job_state"]=="SCORING_INVALID"]
            self.assertEqual(len(invalid),1)
            self.assertEqual(invalid[0]["partial_score"],"")

    def test_existing_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adaptive,scorer=self.fixture(root);(root/"out").mkdir()
            with self.assertRaisesRegex(module.SnapshotError,"output_exists"):
                module.build_snapshot(root,adaptive,scorer,root/"out",score_result=lambda payload,_conf:payload["score"])

    def test_no_success_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adaptive,scorer=self.fixture(root)
            for path in (root/"status/jobs").glob("*.json"): path.unlink()
            with self.assertRaisesRegex(module.SnapshotError,"no_successful_jobs_at_snapshot"):
                module.build_snapshot(root,adaptive,scorer,root/"out",score_result=lambda payload,_conf:payload["score"])


if __name__ == "__main__":
    unittest.main()
