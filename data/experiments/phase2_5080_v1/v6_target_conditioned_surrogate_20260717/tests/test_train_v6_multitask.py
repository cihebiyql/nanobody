#!/usr/bin/env python3

from __future__ import annotations

import json
import csv
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import tiny_gpu_smoke as smoke  # noqa: E402
import train_v6_multitask as trainer  # noqa: E402


class V6TrainingTests(unittest.TestCase):
    def test_cpu_smoke_writes_best_last_metrics_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = smoke.run(root, "cpu", epochs=2)
            self.assertEqual(result["status"], "COMPLETE")
            run = root / "run"
            self.assertTrue((run / "best.pt").is_file())
            self.assertTrue((run / "last.pt").is_file())
            metrics = [json.loads(line) for line in (run / "metrics.jsonl").read_text().splitlines()]
            self.assertEqual(len(metrics), 2)
            self.assertIn("parent_centered_spearman", metrics[-1]["validation"])
            contract = json.loads((run / "contract.json").read_text())
            self.assertEqual(contract["row_count"], 24)
            self.assertEqual(len(contract["feature_names"]), 126)

    def test_resume_continues_from_last_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "synthetic.tsv"
            smoke.write_synthetic_table(table)
            output = root / "run"
            first = trainer.parser().parse_args([
                "--train-tsv", str(table), "--output-dir", str(output),
                "--backbone-kind", "tiny", "--device", "cpu", "--epochs", "1",
                "--batch-size", "4", "--fold-count", "3", "--warmup-steps", "0",
                "--fusion-dim", "16", "--early-stopping-patience", "5",
            ])
            trainer.train(first)
            second = trainer.parser().parse_args([
                "--train-tsv", str(table), "--output-dir", str(output),
                "--backbone-kind", "tiny", "--device", "cpu", "--epochs", "2",
                "--batch-size", "4", "--fold-count", "3", "--warmup-steps", "0",
                "--fusion-dim", "16", "--early-stopping-patience", "5",
                "--resume", str(output / "last.pt"),
            ])
            trainer.train(second)
            records = (output / "metrics.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(line)["epoch"] for line in records], [0, 1])

    def test_separate_structure_table_uses_reliability_weight_and_frozen_fold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            combined = root / "combined.tsv"
            smoke.write_synthetic_table(combined)
            with combined.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            feature_names = [name for name in rows[0] if name.startswith("structure_")]
            teacher = root / "teacher.tsv"
            teacher_fields = [name for name in rows[0] if name not in feature_names and name != "sample_weight"] + ["reliability_weight", "fold_id"]
            parent_fold = {f"P{index}": index % 3 for index in range(6)}
            with teacher.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, teacher_fields, delimiter="\t")
                writer.writeheader()
                for row in rows:
                    payload = {name: row[name] for name in teacher_fields if name in row}
                    payload["reliability_weight"] = "0.65"
                    payload["fold_id"] = str(parent_fold[row["parent_framework_cluster"]])
                    writer.writerow(payload)
            structure = root / "structure.tsv"
            with structure.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, ["candidate_id", *feature_names], delimiter="\t")
                writer.writeheader()
                for row in rows:
                    writer.writerow({name: row[name] for name in ["candidate_id", *feature_names]})
            loaded, names = trainer.load_rows(
                teacher, structure_prefix="structure_", structure_dim=126, structure_tsv=[structure],
            )
            self.assertEqual(len(names), 126)
            self.assertTrue(all(row.sample_weight == 0.65 for row in loaded))
            folds = trainer.frozen_parent_folds(loaded, 3)
            self.assertIsNotNone(folds)
            self.assertEqual(sorted(index for fold in folds or [] for index in fold), list(range(24)))


if __name__ == "__main__":
    unittest.main()
