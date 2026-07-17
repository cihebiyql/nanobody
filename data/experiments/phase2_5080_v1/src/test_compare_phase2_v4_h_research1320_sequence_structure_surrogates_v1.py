import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("compare_phase2_v4_h_research1320_sequence_structure_surrogates_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_comparison", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ComparisonTests(unittest.TestCase):
    def fixture(self, root: Path):
        sequence = root / "sequence.tsv"
        structure = root / "structure.tsv"
        fields_common = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode", "research_rank", "research_rank_percentile"]
        raw = []
        index = 0
        for parent in ("P1", "P2"):
            for patch in ("A", "B"):
                for mode in ("H3", "H1H3"):
                    for replicate in range(2):
                        raw.append({
                            "candidate_id":f"C{index:02d}", "sequence_sha256":f"{index:064x}",
                            "parent_framework_cluster":parent, "target_patch_id":patch, "design_mode":mode,
                        })
                        index += 1
        sequence_order = list(range(len(raw)))
        structure_order = list(reversed(sequence_order))
        for path, order, prediction_field in (
            (sequence, sequence_order, "predicted_R_dual_min_sequence_only"),
            (structure, structure_order, "predicted_R_dual_min_structure_only"),
        ):
            fields = fields_common[:-2] + [prediction_field, *fields_common[-2:]]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for rank, raw_index in enumerate(order, start=1):
                    row = dict(raw[raw_index])
                    row[prediction_field] = str(float(len(raw) - rank + 1))
                    row["research_rank"] = rank
                    row["research_rank_percentile"] = (len(raw) - rank) / (len(raw) - 1)
                    writer.writerow(row)
        return sequence, structure

    def test_compares_and_builds_balanced_portfolio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence, structure = self.fixture(root)
            result = module.compare(
                sequence, structure, root / "out",
                expected_sequence_sha256=sha(sequence), expected_structure_sha256=sha(structure),
                expected_rows=16, expected_parent_count=2, expected_patch_count=2,
                expected_mode_count=2, expected_rows_per_stratum=2,
                portfolio_per_stratum=2, disagreement_tail_size=2,
            )
            self.assertAlmostEqual(result["prediction_spearman"], -1.0)
            self.assertEqual(result["balanced_portfolio_rows"], 16)
            with (root / "out/v4h_research1320_sequence_structure_balanced132_v1.tsv").open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 16)
            self.assertEqual(len({row["candidate_id"] for row in rows}), 16)
            self.assertEqual(result["V4_H_geometry_labels_accessed"], 0)

    def test_metadata_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence, structure = self.fixture(root)
            value = structure.read_text().replace("\tP1\t", "\tBROKEN\t", 1)
            structure.write_text(value)
            with self.assertRaisesRegex(module.ComparisonError, "ranking_metadata_mismatch"):
                module.compare(
                    sequence, structure, root / "out",
                    expected_sequence_sha256=sha(sequence), expected_structure_sha256=sha(structure),
                    expected_rows=16, expected_parent_count=2, expected_patch_count=2,
                    expected_mode_count=2, expected_rows_per_stratum=2,
                )

    def test_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence, structure = self.fixture(root)
            with self.assertRaisesRegex(module.ComparisonError, "sequence_ranking_hash_mismatch"):
                module.compare(
                    sequence, structure, root / "out",
                    expected_sequence_sha256="0" * 64, expected_structure_sha256=sha(structure),
                    expected_rows=16, expected_parent_count=2, expected_patch_count=2,
                    expected_mode_count=2, expected_rows_per_stratum=2,
                )


if __name__ == "__main__":
    unittest.main()
