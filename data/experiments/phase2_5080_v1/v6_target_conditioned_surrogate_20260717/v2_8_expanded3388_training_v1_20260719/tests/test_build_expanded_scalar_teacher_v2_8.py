from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "build_expanded_scalar_teacher_v2_8.py"
SPEC = importlib.util.spec_from_file_location("builder", MODULE_PATH)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def read_tsv(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class BuildExpandedScalarTeacherTests(unittest.TestCase):
    def materialize(self, output_dir: Path):
        args = BUILDER.parse_args([])
        args.output_dir = output_dir
        return BUILDER.build(args)

    def test_production_materialization_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            receipt = self.materialize(tmp_path)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["counts"]["expanded_scalar_rows"], 3388)
            self.assertEqual(receipt["counts"]["v4i_scalar_valid_rows"], 1881)
            self.assertEqual(receipt["counts"]["v4i_technical_incomplete_rows"], 81)
            self.assertEqual(receipt["counts"]["stage2_ablation_scalar_rows"], 2007)
            self.assertEqual(receipt["counts"]["expanded_multi_seed_rows"], 1066)
            self.assertEqual(receipt["counts"]["expanded_single_seed_rows"], 2322)
            self.assertEqual(receipt["counts"]["receptor_specific_scalar_targets"], 6776)

            expanded = read_tsv(tmp_path / "v6_scalar_teacher3388_v2_8.tsv")
            self.assertEqual(len(expanded), 3388)
            self.assertEqual(len({row["candidate_id"] for row in expanded}), 3388)
            self.assertEqual(len({row["sequence_sha256"] for row in expanded}), 3388)
            self.assertTrue(all(abs(float(row["R_dual_min"]) - min(float(row["R_8X6B"]), float(row["R_9E6Y"]))) <= 1e-8 for row in expanded))

            v4i = [row for row in expanded if row["source_campaign"] == "V4I"]
            self.assertEqual(len(v4i), 1881)
            self.assertEqual(sum(row["stage2_repeat_selected"] == "1" for row in v4i), 500)
            self.assertEqual(sum(row["teacher_reliability"] == "DUAL_2_SEED" for row in v4i), 476)
            self.assertEqual(sum(row["teacher_reliability"] == "DUAL_1_SEED" for row in v4i), 1405)
            self.assertTrue(all(row["contact_teacher_state"] == "CONTACT_TEACHER_NOT_EXTRACTED" for row in v4i))
            self.assertTrue(all(int(row["paired_successful_seed_count"]) >= 1 for row in expanded))
            self.assertEqual(sum(int(row["paired_successful_seed_count"]) >= 2 for row in expanded), 1066)

            stage2_ablation = read_tsv(tmp_path / "v6_scalar_teacher2007_stage2_ablation_v2_8.tsv")
            self.assertEqual(len(stage2_ablation), 2007)
            self.assertEqual(sum(row["source_campaign"] == "V4I" for row in stage2_ablation), 500)
            self.assertTrue(all(row["source_campaign"] != "V4I" or row["stage2_repeat_selected"] == "1" for row in stage2_ablation))

            receipt_disk = json.loads((tmp_path / "MATERIALIZATION_RECEIPT.json").read_text())
            self.assertEqual(receipt_disk, receipt)

    def test_stage2_rows_replace_instead_of_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            self.materialize(tmp_path)
            v4i = read_tsv(tmp_path / "v4i_scalar_teacher1881_v2_8.tsv")
            selected = [row for row in v4i if row["stage2_repeat_selected"] == "1"]
            self.assertEqual(len(selected), 500)
            self.assertTrue(all(row["label_update_provenance"] == "stage2_seed917_1931_selected500_ranking.tsv" for row in selected))
            self.assertEqual(len({row["candidate_id"] for row in selected}), 500)

    def test_parent_fold_is_bound_to_existing_parent_split(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            self.materialize(tmp_path)
            rows = read_tsv(tmp_path / "v6_scalar_teacher3388_v2_8.tsv")
            folds = {}
            for row in rows:
                parent = row["parent_framework_cluster"]
                folds.setdefault(parent, set()).add(row["outer_fold"])
            self.assertEqual(len(folds), 31)
            self.assertTrue(all(len(values) == 1 for values in folds.values()))


if __name__ == "__main__":
    unittest.main()
