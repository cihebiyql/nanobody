import csv
import tempfile
import unittest
from pathlib import Path

import analyze_pvrig_v4e_design_axis_enrichment as analysis


def write_teacher(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def make_rows() -> list[dict[str, str]]:
    rows = []
    index = 0
    for split, count, parent_prefix, parent_count in (
        ("OPEN_TRAIN", 226, "TRAIN", 20),
        ("OPEN_DEVELOPMENT", 32, "DEV", 3),
    ):
        for offset in range(count):
            rows.append(
                {
                    "candidate_id": f"C{index:03d}",
                    "sequence_sha256": f"h{index:03d}",
                    "model_split": split,
                    "parent_id": f"{parent_prefix}_{offset % parent_count}",
                    "target_patch_id": ["A_CENTER", "B_LOWER", "C_CROSS"][offset % 3],
                    "design_mode": ["H1H3", "H3"][offset % 2],
                    "R_dual_min": f"{0.40 + 0.001 * index:.6f}",
                }
            )
            index += 1
    return rows


class V4EDesignAxisEnrichmentTests(unittest.TestCase):
    def test_expected_contract_is_exploratory_and_never_authorizes_generation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            teacher = Path(tempdir) / "teacher.tsv"
            write_teacher(teacher, make_rows())
            payload = analysis.analyze(teacher)
        self.assertEqual(payload["status"], "PASS_EXPLORATORY_ANALYSIS_NO_GENERATION_RELEASE")
        self.assertFalse(payload["generation_authorized"])
        self.assertEqual(payload["distribution_shift"]["development_parent_count"], 3)
        self.assertTrue(all(not row["independent_parent_gate_pass"] for row in payload["results"]))

    def test_parent_overlap_is_rejected(self):
        rows = make_rows()
        rows[-1]["parent_id"] = rows[0]["parent_id"]
        with tempfile.TemporaryDirectory() as tempdir:
            teacher = Path(tempdir) / "teacher.tsv"
            write_teacher(teacher, rows)
            with self.assertRaisesRegex(analysis.AnalysisError, "train_development_parent_overlap"):
                analysis.analyze(teacher)

    def test_unexpected_axis_level_is_rejected(self):
        rows = make_rows()
        rows[0]["target_patch_id"] = "P4"
        with tempfile.TemporaryDirectory() as tempdir:
            teacher = Path(tempdir) / "teacher.tsv"
            write_teacher(teacher, rows)
            with self.assertRaisesRegex(analysis.AnalysisError, "axis_levels_mismatch"):
                analysis.analyze(teacher)


if __name__ == "__main__":
    unittest.main()
