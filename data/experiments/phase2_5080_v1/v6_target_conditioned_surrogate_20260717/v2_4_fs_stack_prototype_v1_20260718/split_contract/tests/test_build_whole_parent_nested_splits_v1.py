#!/usr/bin/env python3

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "build_whole_parent_nested_splits_v1.py"
SPEC = importlib.util.spec_from_file_location("build_whole_parent_nested_splits_v1", MODULE_PATH)
assert SPEC and SPEC.loader
splitter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = splitter
SPEC.loader.exec_module(splitter)


INPUT_COLUMNS = (
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
)


def make_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for parent_index in range(31):
        parent = f"P{parent_index:02d}"
        outer_fold = str(parent_index % 5)
        source = "V4D" if parent_index < 20 else "V4H"
        for candidate_index in range(1 + (parent_index % 4)):
            rows.append(
                {
                    "candidate_id": f"C{parent_index:02d}_{candidate_index}",
                    "teacher_source": source,
                    "parent_framework_cluster": parent,
                    "outer_fold": outer_fold,
                }
            )
    return rows


def build(rows=None, development_outer_fold=None):
    rows = rows or make_rows()
    return splitter.build_manifests(
        rows,
        input_table_sha256="a" * 64,
        inner_fold_count=5,
        inner_seed=1931,
        development_outer_fold=development_outer_fold,
    )


class NestedSplitContractTests(unittest.TestCase):
    def test_deterministic_outputs_are_identical(self):
        first = build()
        second = build()
        self.assertEqual(first, second)

    def test_outer_whole_parent_non_overlap_and_31_parent_closure(self):
        rows = make_rows()
        outer, _, summary = build(rows)
        by_fold = defaultdict(list)
        for row in outer:
            by_fold[row["outer_fold"]].append(row)
        self.assertEqual(set(by_fold), {"0", "1", "2", "3", "4"})
        for fold_rows in by_fold.values():
            train = {r["parent_framework_cluster"] for r in fold_rows if r["candidate_role"] == "train"}
            score = {r["parent_framework_cluster"] for r in fold_rows if r["candidate_role"] == "score"}
            self.assertFalse(train & score)
            self.assertEqual(len(train | score), 31)
        self.assertEqual(summary["input_parent_count"], 31)

    def test_inner_parent_is_score_exactly_once_per_outer_train(self):
        _, inner, summary = build()
        score_occurrences = Counter()
        for row in inner:
            if row["candidate_role"] == "score":
                score_occurrences[(row["outer_fold"], row["parent_framework_cluster"])] += 1
        candidate_counts = Counter(row["parent_framework_cluster"] for row in make_rows())
        for outer_fold, detail in summary["outer_splits"].items():
            for parent in detail["inner_parent_assignment"]:
                self.assertEqual(
                    score_occurrences[(outer_fold, parent)], candidate_counts[parent]
                )

    def test_every_manifest_row_binds_input_sha_and_parent_set_sha(self):
        outer, inner, _ = build()
        for row in [*outer, *inner]:
            self.assertEqual(row["input_table_sha256"], "a" * 64)
            self.assertEqual(len(row["train_parent_set_sha256"]), 64)
            self.assertEqual(len(row["score_parent_set_sha256"]), 64)

    def test_development_outer_fold_filter(self):
        outer, inner, summary = build(development_outer_fold="3")
        self.assertEqual({row["outer_fold"] for row in outer}, {"3"})
        self.assertEqual({row["outer_fold"] for row in inner}, {"3"})
        self.assertEqual(summary["selected_outer_folds"], ["3"])

    def test_parent_crossing_input_outer_folds_is_rejected(self):
        rows = make_rows()
        rows.append(
            {
                "candidate_id": "CROSS",
                "teacher_source": "V4D",
                "parent_framework_cluster": "P00",
                "outer_fold": "4",
            }
        )
        with self.assertRaisesRegex(splitter.SplitContractError, "parent_in_multiple_outer_folds"):
            splitter.validate_training_rows(rows, INPUT_COLUMNS)

    def test_non_31_parent_input_is_rejected(self):
        rows = [row for row in make_rows() if row["parent_framework_cluster"] != "P30"]
        with self.assertRaisesRegex(splitter.SplitContractError, "parent_closure_not_31"):
            splitter.validate_training_rows(rows, INPUT_COLUMNS)

    def test_v4f_source_is_rejected(self):
        rows = make_rows()
        rows[0]["teacher_source"] = "V4-F"
        with self.assertRaisesRegex(splitter.SplitContractError, "forbidden_v4f_source"):
            splitter.validate_training_rows(rows, INPUT_COLUMNS)

    def test_v4f_input_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pvrig_v4_f.tsv"
            path.write_text("x\n")
            with self.assertRaisesRegex(splitter.SplitContractError, "forbidden_v4f_input_path"):
                splitter.read_training_table(path)

    def test_tampered_outer_parent_role_is_rejected(self):
        rows = make_rows()
        outer, inner, summary = build(rows)
        target_fold = outer[0]["outer_fold"]
        target_parent = outer[0]["parent_framework_cluster"]
        for row in outer:
            if row["outer_fold"] == target_fold and row["parent_framework_cluster"] == target_parent:
                row["candidate_role"] = "score" if row["candidate_role"] == "train" else "train"
                break
        with self.assertRaises(splitter.SplitContractError):
            splitter.validate_generated_manifests(
                rows, outer, inner, summary, input_table_sha256="a" * 64
            )

    def test_cli_materializes_and_receipts_manifests(self):
        rows = make_rows()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.tsv"
            with input_path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=INPUT_COLUMNS, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            output_dir = root / "output"
            receipt = splitter.run(
                splitter.argparse.Namespace(
                    input_tsv=str(input_path),
                    output_dir=str(output_dir),
                    inner_fold_count=5,
                    inner_seed=1931,
                    development_outer_fold=None,
                )
            )
            self.assertEqual(receipt["status"], "PASS_WHOLE_PARENT_31_PARENT_CLOSURE")
            self.assertTrue((output_dir / "outer_development_manifest.tsv").is_file())
            self.assertTrue((output_dir / "inner_nested_oof_manifest.tsv").is_file())
            summary = json.loads((output_dir / "split_summary.json").read_text())
            self.assertEqual(summary["input_parent_count"], 31)


if __name__ == "__main__":
    unittest.main(verbosity=2)
