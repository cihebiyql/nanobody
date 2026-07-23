#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "collect_v220_contact_shared_oof_v1.py"
SPEC = importlib.util.spec_from_file_location("collect_v220_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
COLLECTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COLLECTOR
SPEC.loader.exec_module(COLLECTOR)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Row:
    candidate_id: str
    sequence_sha256: str
    parent: str
    targets: tuple[float, float]


class Split:
    def __init__(self, train, score, rows, fold):
        self.train_indices = train
        self.development_indices = score
        self.train_parents = sorted({rows[i].parent for i in train})
        self.development_parents = sorted({rows[i].parent for i in score})
        self.split_id = f"fold{fold}"


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.old_counts = (COLLECTOR.EXPECTED_ROWS, COLLECTOR.EXPECTED_PARENTS)
        COLLECTOR.EXPECTED_ROWS = 10
        COLLECTOR.EXPECTED_PARENTS = 10
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = [
            Row(f"C{i:02d}", hashlib.sha256(f"SEQ{i}".encode()).hexdigest(), f"P{i:02d}", (0.4 + i / 100, 0.5 + i / 100))
            for i in range(10)
        ]
        self.teacher = self.root / "teacher.tsv"
        self.teacher.write_text("synthetic\n")
        self.assignment = self.root / "assignment.tsv"
        with self.assignment.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id"), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for i, row in enumerate(self.rows):
                writer.writerow({"candidate_id": row.candidate_id, "sequence_sha256": row.sequence_sha256, "parent_framework_cluster": row.parent, "fold_id": i % 5})
        self.contracts = self.root / "contracts"
        self.contracts.mkdir()
        self.run_root = self.root / "runs"
        self.run_root.mkdir()
        self.runner_path = self.root / "runner.py"
        self.runner_path.write_text("# synthetic\n")

        base = types.SimpleNamespace()
        base.load_rows = lambda path, count: list(self.rows)
        base.load_contract = lambda path: json.loads(path.read_text())
        base._verify_bound_file = lambda bound, label: Path(bound["path"])

        def load_split(path, rows, train_count, score_count):
            fold = int(path.stem.split("_")[-1])
            score = [i for i in range(len(rows)) if i % 5 == fold]
            train = [i for i in range(len(rows)) if i not in score]
            self.assertEqual((len(train), len(score)), (train_count, score_count))
            return Split(train, score, rows, fold)

        base.load_split = load_split
        self.base = base
        self.old_loader = COLLECTOR.load_module
        COLLECTOR.load_module = lambda path, name: self.base

        for fold in range(5):
            split_path = self.root / f"split_{fold}"
            split_path.write_text("x")
            contract = {"task": {"fold_id": fold, "seed": 43}, "expected_counts": {"train": 8, "score": 2}, "split_manifest": {"path": str(split_path)}}
            (self.contracts / f"fold_{fold}_contract.json").write_text(json.dumps(contract))
            fold_dir = self.run_root / f"fold_{fold}"
            fold_dir.mkdir()
            prediction = fold_dir / COLLECTOR.PREDICTION_NAME
            fields = ("candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "arm", "target_R_8X6B", "target_R_9E6Y", "target_R_dual_min", "prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min")
            with prediction.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for i, row in enumerate(self.rows):
                    if i % 5 != fold:
                        continue
                    pred = (row.targets[0] + 0.01, row.targets[1] - 0.01)
                    writer.writerow({"candidate_id": row.candidate_id, "sequence_sha256": row.sequence_sha256, "parent_framework_cluster": row.parent, "fold_id": fold, "seed": 43, "arm": "C1", "target_R_8X6B": row.targets[0], "target_R_9E6Y": row.targets[1], "target_R_dual_min": min(row.targets), "prediction_R_8X6B": pred[0], "prediction_R_9E6Y": pred[1], "prediction_R_dual_min": min(pred)})
            result = {"status": "PASS_V220_C1_CONTACT_SHARED_FOLD", "arm": "C1", "fold_id": fold, "seed": 43, "split": {"whole_parent_overlap": 0}, "neural_input_firewall": {"outer_score_contact_numeric_reads": 0, "contact_labels_forwarded": False}, "exact_min_inference": True, "pairing": {"serialized_initial_state_sha256": "a" * 64}, "outputs": {COLLECTOR.PREDICTION_NAME: sha(prediction)}}
            (fold_dir / COLLECTOR.RESULT_NAME).write_text(json.dumps(result))

    def tearDown(self):
        COLLECTOR.load_module = self.old_loader
        COLLECTOR.EXPECTED_ROWS, COLLECTOR.EXPECTED_PARENTS = self.old_counts
        self.temp.cleanup()

    def collect(self, output_name="out"):
        return COLLECTOR.collect(teacher_path=self.teacher, assignment_path=self.assignment, contracts_dir=self.contracts, run_root=self.run_root, output_dir=self.root / output_name, arm="C1", v213_runner_path=self.runner_path)

    def test_exact_five_fold_collection(self):
        receipt = self.collect()
        self.assertEqual(receipt["status"], "PASS_V220_C1_TRAIN9849_WHOLE_PARENT_OOF")
        output = self.root / "out" / "V220_C1_TRAIN9849_OOF_PREDICTIONS.tsv"
        fields, rows = COLLECTOR.read_tsv(output)
        self.assertEqual(len(rows), 10)
        self.assertIn("V220_C1__Rdual_exact_min", fields)
        self.assertEqual(len({row["candidate_id"] for row in rows}), 10)

    def test_prediction_hash_tamper_fails(self):
        path = self.run_root / "fold_2" / COLLECTOR.PREDICTION_NAME
        path.write_text(path.read_text() + "#tamper\n")
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "prediction_hash:2"):
            self.collect()

    def test_initial_state_mismatch_fails(self):
        path = self.run_root / "fold_4" / COLLECTOR.RESULT_NAME
        result = json.loads(path.read_text())
        result["pairing"]["serialized_initial_state_sha256"] = "b" * 64
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "initial_state_not_byte_identical"):
            self.collect()

    def test_score_candidate_leak_fails(self):
        path = self.run_root / "fold_1" / COLLECTOR.RESULT_NAME
        result = json.loads(path.read_text())
        result["neural_input_firewall"]["outer_score_contact_numeric_reads"] = 1
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(COLLECTOR.CollectionError, "score_contact_access:1"):
            self.collect()


if __name__ == "__main__":
    unittest.main()
