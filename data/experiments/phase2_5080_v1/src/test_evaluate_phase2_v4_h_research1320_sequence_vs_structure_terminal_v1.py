import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("evaluate_phase2_v4_h_research1320_sequence_vs_structure_terminal_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_terminal_evaluator", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TerminalEvaluatorTests(unittest.TestCase):
    def fixture(self, root: Path, *, terminal: bool = True, bad_incomplete: bool = False):
        count = 24
        rows = []
        for index in range(count):
            rows.append({
                "candidate_id":f"C{index:02d}", "sequence_sha256":f"{index:064x}",
                "parent_framework_cluster":"C0283" if index < 12 else "C9999",
                "target_patch_id":["A","B","C"][index % 3], "design_mode":["H3","H1H3"][index % 2],
            })
        sequence = root / "sequence.tsv"
        structure = root / "structure.tsv"
        for path, field, reverse in (
            (sequence, "predicted_R_dual_min_sequence_only", False),
            (structure, "predicted_R_dual_min_structure_only", True),
        ):
            fields = [*rows[0].keys(), field, "research_rank", "research_rank_percentile"]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                ordered = list(reversed(rows)) if reverse else rows
                for rank, row in enumerate(ordered, start=1):
                    payload = dict(row)
                    payload[field] = str(float(rank if reverse else count - rank + 1) / 100.0 + 0.5)
                    payload["research_rank"] = rank
                    payload["research_rank_percentile"] = (count-rank)/(count-1)
                    writer.writerow(payload)
        teacher = root / "teacher.tsv"
        with teacher.open("w", newline="") as handle:
            fields = ["candidate_id", "teacher_state", "technical_incomplete_reason", "R_dual_min"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, row in enumerate(rows):
                if index == count - 1:
                    writer.writerow({
                        "candidate_id":row["candidate_id"], "teacher_state":"TECHNICAL_INCOMPLETE",
                        "technical_incomplete_reason":"dock_failed", "R_dual_min":"0.1" if bad_incomplete else "",
                    })
                else:
                    writer.writerow({
                        "candidate_id":row["candidate_id"], "teacher_state":"ANALYZABLE",
                        "technical_incomplete_reason":"", "R_dual_min":str(0.5 + index/100.0),
                    })
        balanced = root / "balanced.tsv"
        with balanced.open("w", newline="") as handle:
            fields = ["candidate_id", "portfolio_role"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, row in enumerate(rows[:12]):
                writer.writerow({"candidate_id":row["candidate_id"], "portfolio_role":"CONSENSUS_HIGH" if index < 6 else "STRUCTURE_FAVORED_DISAGREEMENT"})
        prereg = root / "prereg.json"; prereg.write_text("{}\n")
        receipt = root / "terminal.json"
        receipt.write_text(json.dumps({
            "status":"COMPLETE_V4_H_TERMINAL_IMMUTABLE_TEACHER", "campaign_terminal":terminal,
            "teacher_sha256":sha(teacher), "expected_candidate_rows":count,
            "required_receptors":["8X6B","9E6Y"], "partial_teacher_consumption_forbidden":True,
        }) + "\n")
        return teacher, receipt, sequence, structure, balanced, prereg

    def run_evaluation(self, root: Path, **fixture_kwargs):
        teacher, receipt, sequence, structure, balanced, prereg = self.fixture(root, **fixture_kwargs)
        return module.evaluate(
            teacher, receipt, sequence, structure, balanced, prereg, root / "out",
            expected_teacher_sha256=sha(teacher), expected_terminal_receipt_sha256=sha(receipt),
            expected_sequence_sha256=sha(sequence), expected_structure_sha256=sha(structure),
            expected_balanced_sha256=sha(balanced), expected_prereg_sha256=sha(prereg),
            expected_rows=24, bootstrap_replicates=50, bootstrap_seed=7,
        )

    def test_terminal_evaluation_excludes_incomplete_without_imputation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_evaluation(root)
            self.assertEqual(result["analyzable_rows"], 23)
            self.assertEqual(result["technical_incomplete_rows"], 1)
            self.assertFalse(result["formal_pass_claimed"])
            self.assertIn("M1_SEQUENCE_ONLY", result["global_metrics"])
            self.assertIn("M2_STRUCTURE_ONLY", result["global_metrics"])

    def test_rejects_nonterminal_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.EvaluationError, "campaign_not_terminal"):
                self.run_evaluation(Path(directory), terminal=False)

    def test_rejects_numeric_imputation_for_technical_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.EvaluationError, "incomplete_target_must_be_empty"):
                self.run_evaluation(Path(directory), bad_incomplete=True)


if __name__ == "__main__":
    unittest.main()
