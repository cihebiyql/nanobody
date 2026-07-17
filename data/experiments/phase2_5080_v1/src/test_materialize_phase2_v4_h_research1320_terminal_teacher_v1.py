import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_h_research1320_terminal_teacher_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_terminal_teacher", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TerminalTeacherTests(unittest.TestCase):
    def fixture(self, root: Path, *, nonterminal: bool = False, inconsistent_target: bool = False):
        candidates = root / "candidates.tsv"
        fields = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"]
        rows = [
            {"candidate_id":"C1", "sequence_sha256":"1"*64, "parent_framework_cluster":"P1", "target_patch_id":"A", "design_mode":"H3"},
            {"candidate_id":"C2", "sequence_sha256":"2"*64, "parent_framework_cluster":"P2", "target_patch_id":"B", "design_mode":"H1H3"},
        ]
        with candidates.open("w", newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=fields,delimiter="\t",lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
        ranking = root / "ranking.tsv"
        ranking_fields = [*fields, "docking_evidence_tier", "successful_seed_count_8X6B", "successful_seed_count_9E6Y", "median_score_8X6B", "median_score_9E6Y", "R_dual_min", "technical_reasons"]
        with ranking.open("w", newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=ranking_fields,delimiter="\t",lineterminator="\n"); writer.writeheader()
            writer.writerow({**rows[0], "docking_evidence_tier":"DUAL_2_SEED", "successful_seed_count_8X6B":2, "successful_seed_count_9E6Y":2, "median_score_8X6B":"0.6", "median_score_9E6Y":"0.5", "R_dual_min":"0.4" if inconsistent_target else "0.5", "technical_reasons":""})
            writer.writerow({**rows[1], "docking_evidence_tier":"TECHNICAL_INCOMPLETE", "successful_seed_count_8X6B":1, "successful_seed_count_9E6Y":0, "median_score_8X6B":"0.55", "median_score_9E6Y":"", "R_dual_min":"", "technical_reasons":"9e6y:s917:FAILED_MAX_ATTEMPTS"})
        receipt = root / "adaptive.json"
        terminal_counts = {"SUCCESS":1, **({"RUNNING":1} if nonterminal else {"FAILED_MAX_ATTEMPTS":1})}
        block={"job_count":2,"terminal_counts":terminal_counts}
        receipt.write_text(json.dumps({
            "status":"PASS_ADAPTIVE_DUAL_DOCKING_TERMINAL_WITH_EXPLICIT_TECHNICAL_STATES",
            "candidate_count":2, "final_ranking_sha256":sha(ranking),
            "terminals":{name:block for name in ("smoke","stage1","stage2","stage3")},
        })+"\n")
        return candidates, ranking, receipt

    def run_materialize(self, root: Path, **kwargs):
        candidates, ranking, receipt = self.fixture(root, **kwargs)
        return module.materialize(
            ranking, receipt, candidates, root/"teacher.tsv", root/"terminal_receipt.json",
            expected_final_ranking_sha256=sha(ranking), expected_adaptive_receipt_sha256=sha(receipt),
            expected_candidate_sha256=sha(candidates), expected_rows=2,
        )

    def test_materializes_analyzable_and_explicit_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); result=self.run_materialize(root)
            self.assertEqual(result["state_counts"], {"ANALYZABLE":1,"TECHNICAL_INCOMPLETE":1})
            self.assertFalse(result["numeric_imputation_performed"])
            with (root/"teacher.tsv").open(newline="") as handle: rows=list(csv.DictReader(handle,delimiter="\t"))
            self.assertEqual(rows[1]["R_dual_min"], "")

    def test_rejects_nonterminal_receipt_block(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.TeacherError, "nonterminal_state_in_receipt"):
                self.run_materialize(Path(directory), nonterminal=True)

    def test_rejects_inconsistent_R_dual_min(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.TeacherError, "R_dual_min_consistency_failed"):
                self.run_materialize(Path(directory), inconsistent_target=True)


if __name__ == "__main__":
    unittest.main()
