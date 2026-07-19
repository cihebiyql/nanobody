#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("panel", HERE / "materialize_label_free_panel_v1.py")
panel = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(panel)


class PanelTests(unittest.TestCase):
    def write_source(self, root: Path, *, duplicate=False, cross_fold=False) -> Path:
        path = root / "source.tsv"
        fields = panel.FIELDS + ["R_dual_min"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(1507):
                sequence = "A" * 100
                candidate = "c0" if duplicate and index == 1 else f"c{index}"
                parent_index = index % 31
                fold = parent_index % 5
                if cross_fold and index == 31:
                    fold = 1
                writer.writerow({
                    "candidate_id": candidate,
                    "sequence": sequence,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "parent_framework_cluster": f"p{parent_index}",
                    "outer_fold": fold,
                    "R_dual_min": 0.5,
                })
        return path

    def test_materializes_exact_schema_and_drops_teacher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.write_source(root)
            result = panel.materialize(source, root / "out", panel.sha256_file(source))
            self.assertEqual(result["teacher_fields_emitted"], 0)
            with (root / "out/open1507_label_free_replay_panel.tsv").open() as handle:
                self.assertEqual(csv.DictReader(handle, delimiter="\t").fieldnames, panel.FIELDS)

    def test_source_hash_tamper_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.write_source(root)
            with self.assertRaisesRegex(panel.PanelError, "source_sha256"):
                panel.materialize(source, root / "out", "0" * 64)

    def test_duplicate_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.write_source(root, duplicate=True)
            with self.assertRaisesRegex(panel.PanelError, "candidate_duplicate"):
                panel.materialize(source, root / "out", panel.sha256_file(source))

    def test_parent_cross_fold_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = self.write_source(root, cross_fold=True)
            with self.assertRaisesRegex(panel.PanelError, "parent_cross_fold"):
                panel.materialize(source, root / "out", panel.sha256_file(source))


if __name__ == "__main__":
    unittest.main()
