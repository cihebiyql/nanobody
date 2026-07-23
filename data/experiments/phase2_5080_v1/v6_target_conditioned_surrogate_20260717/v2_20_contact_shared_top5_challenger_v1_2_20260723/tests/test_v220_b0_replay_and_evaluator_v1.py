#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


PACKAGE = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = PACKAGE / "src" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPLAY = load_module("v220_replay_under_test", "replay_v213_b0_oof_v1.py")
EVALUATE = load_module("v220_evaluate_under_test", "evaluate_v220_oof_v1.py")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def tsv_bytes(fields, rows) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


class ReplayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.teacher = root / "train_only_teacher.tsv"
        self.aggregate = root / "TOP5_L1_TRAIN9849_OOF_PREDICTIONS.tsv"
        self.metrics = root / "OOF_METRICS.json"
        self.receipt = root / "OOF_RECEIPT.json"
        self.prereg = root / "PREREGISTRATION.json"
        self.folds: dict[int, Path] = {}
        teacher_rows = []
        fold_tables = {}
        fold_hashes = {}
        for fold in range(5):
            fold_rows = []
            for item in range(4):
                candidate = f"candidate_{fold}_{item}"
                r8 = 0.45 + fold * 0.01 + item * 0.001 + 0.000000013
                r9 = r8 + (0.02 if item % 2 == 0 else -0.015)
                pred8 = 0.40 + fold * 0.02 + item * 0.005
                pred9 = pred8 - 0.01 + item * 0.001
                teacher_rows.append({
                    "candidate_id": candidate,
                    "sequence_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                    "parent_framework_cluster": f"parent_{fold}",
                    "R_8X6B": format(r8, ".12g"),
                    "R_9E6Y": format(r9, ".12g"),
                    "R_dual_min": format(min(r8, r9), ".12g"),
                })
                f32r8, f32r9 = float(np.float32(r8)), float(np.float32(r9))
                fold_rows.append({
                    "candidate_id": candidate,
                    "parent_framework_cluster": f"parent_{fold}",
                    "target_R_8X6B": format(f32r8, ".12g"),
                    "target_R_9E6Y": format(f32r9, ".12g"),
                    "target_R_dual_min": format(min(f32r8, f32r9), ".12g"),
                    "prediction_R_8X6B": format(pred8, ".12g"),
                    "prediction_R_9E6Y": format(pred9, ".12g"),
                    "prediction_R_dual_min": format(min(pred8, pred9), ".12g"),
                    "exact_min_abs_error": "0",
                    "sequence_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                    "fold_id": str(fold),
                    "seed": "43",
                    "variant": "L1",
                })
            fold_fields = (
                "candidate_id", "parent_framework_cluster", "target_R_8X6B", "target_R_9E6Y", "target_R_dual_min",
                "prediction_R_8X6B", "prediction_R_9E6Y", "prediction_R_dual_min", "exact_min_abs_error",
                "sequence_sha256", "fold_id", "seed", "variant",
            )
            raw = tsv_bytes(fold_fields, fold_rows)
            path = root / f"fold_{fold}_predictions.tsv"
            path.write_bytes(raw)
            self.folds[fold] = path
            fold_tables[fold] = (list(fold_fields), fold_rows)
            fold_hashes[str(fold)] = sha(raw)

        teacher_fields = (
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "R_8X6B", "R_9E6Y", "R_dual_min",
        )
        teacher_raw = tsv_bytes(teacher_fields, sorted(teacher_rows, key=lambda row: row["candidate_id"]))
        self.teacher.write_bytes(teacher_raw)
        aggregate_raw, _, _ = REPLAY.reconstruct_aggregate_bytes(
            fold_tables, teacher_fields, teacher_rows, expected_seed=43,
        )
        self.aggregate.write_bytes(aggregate_raw)
        metrics_raw = (json.dumps({"synthetic": True}, indent=2, sort_keys=True) + "\n").encode()
        self.metrics.write_bytes(metrics_raw)
        receipt_payload = {
            "counts": {"folds": 5, "parents": 5, "rows": 20, "seed": 43},
            "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            "inputs": {
                "teacher_sha256": sha(teacher_raw),
                "folds": {fold: {"predictions": digest} for fold, digest in fold_hashes.items()},
            },
            "outputs": {self.aggregate.name: sha(aggregate_raw), self.metrics.name: sha(metrics_raw)},
        }
        receipt_raw = (json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n").encode()
        self.receipt.write_bytes(receipt_raw)
        prereg = {
            "strict_oof": {
                "rows": 20,
                "parents": 5,
                "folds": 5,
                "seed_phase_1": 43,
                "fold_bindings": [
                    {"fold": fold, "score_rows": 4, "prediction_sha256": fold_hashes[str(fold)]}
                    for fold in range(5)
                ],
            },
            "B0_replay_gate": {
                "aggregate_prediction_path": self.aggregate.name,
                "aggregate_prediction_sha256": sha(aggregate_raw),
                "metrics_sha256": sha(metrics_raw),
                "receipt_sha256": sha(receipt_raw),
                "row_by_row_exact_fields": list(REPLAY.PREREG_EXACT_FIELDS),
                "numeric_comparison": "exact serialized decimal string equality, not tolerance equality",
                "required_before_C0_or_C1_training": True,
            },
        }
        self.prereg.write_text(json.dumps(prereg, indent=2, sort_keys=True) + "\n")

    def run(self):
        return REPLAY.replay_b0(
            preregistration_path=self.prereg,
            fold_prediction_paths=self.folds,
            train_teacher_path=self.teacher,
            frozen_aggregate_path=self.aggregate,
            frozen_metrics_path=self.metrics,
            frozen_receipt_path=self.receipt,
        )


class B0ReplayTests(unittest.TestCase):
    def test_byte_exact_replay_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReplayFixture(Path(directory))
            result = fixture.run()
            self.assertEqual(result["status"], REPLAY.STATUS)
            self.assertTrue(result["closure"]["byte_exact"])
            self.assertEqual(result["counts"], {"rows": 20, "parents": 5, "folds": 5, "seed": 43})

    def test_fold_hash_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReplayFixture(Path(directory))
            fixture.folds[2].write_bytes(fixture.folds[2].read_bytes() + b"\n")
            with self.assertRaisesRegex(REPLAY.ReplayError, "fold_prereg_hash_mismatch:2"):
                fixture.run()

    def test_frozen_aggregate_serialization_mutation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReplayFixture(Path(directory))
            fixture.aggregate.write_bytes(fixture.aggregate.read_bytes().replace(b"0.4", b"0.40", 1))
            with self.assertRaisesRegex(REPLAY.ReplayError, "aggregate_prereg_hash_mismatch"):
                fixture.run()

    def test_forbidden_frozen_test_path_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReplayFixture(Path(directory))
            forbidden = Path(directory) / "frozen_test"
            forbidden.mkdir()
            forbidden_aggregate = forbidden / fixture.aggregate.name
            forbidden_aggregate.write_bytes(fixture.aggregate.read_bytes())
            with self.assertRaisesRegex(REPLAY.ReplayError, "forbidden_path:frozen_b0_aggregate:frozen_test"):
                REPLAY.replay_b0(
                    preregistration_path=fixture.prereg,
                    fold_prediction_paths=fixture.folds,
                    train_teacher_path=fixture.teacher,
                    frozen_aggregate_path=forbidden_aggregate,
                    frozen_metrics_path=fixture.metrics,
                    frozen_receipt_path=fixture.receipt,
                )


def make_rows(count: int, prediction_transform=lambda value: value, parents: int = 4):
    rows = []
    for index in range(count):
        truth = float(count - index) / count
        prediction = float(prediction_transform(truth))
        rows.append(EVALUATE.OOFRow(
            candidate_id=f"candidate_{index:03d}",
            parent_id=f"parent_{index % parents:02d}",
            true_r8=truth + 0.05,
            true_r9=truth,
            true_rdual=truth,
            pred_r8=prediction + 0.05,
            pred_r9=prediction,
            pred_rdual=prediction,
        ))
    return rows


class EvaluatorTests(unittest.TestCase):
    def test_ceil_rounding_perfect_top5_enrichment(self):
        metrics = EVALUATE.evaluate_rows(make_rows(21))
        self.assertEqual(metrics["positives_true_top10"], 3)
        self.assertEqual(metrics["selected_at_budget5"], 2)
        self.assertEqual(metrics["hits_at_budget5"], 2)
        self.assertEqual(metrics["EF_true_top10_at_budget5"], 7.0)
        self.assertEqual(metrics["precision_at_budget5"], 1.0)
        self.assertAlmostEqual(metrics["recall_at_budget5"], 2 / 3)
        self.assertEqual(metrics["Rdual_Spearman"], 1.0)
        self.assertEqual(metrics["Rdual_MAE"], 0.0)

    def test_candidate_id_breaks_prediction_tie(self):
        rows = make_rows(10, prediction_transform=lambda _: 0.0, parents=2)
        rows[0] = EVALUATE.OOFRow(**{**rows[0].__dict__, "pred_r8": 1.05, "pred_r9": 1.0, "pred_rdual": 1.0})
        rows[1] = EVALUATE.OOFRow(**{**rows[1].__dict__, "pred_r8": 1.05, "pred_r9": 1.0, "pred_rdual": 1.0})
        metrics = EVALUATE.evaluate_rows(rows)
        self.assertEqual(metrics["selected_at_budget5"], 1)
        self.assertEqual(metrics["hits_at_budget5"], 1)
        self.assertEqual(metrics["EF_true_top10_at_budget5"], 10.0)

    def test_paired_parent_bootstrap_is_deterministic_and_positive(self):
        c1 = make_rows(40, parents=4)
        c0 = make_rows(40, prediction_transform=lambda truth: 1.0 - truth, parents=4)
        first = EVALUATE.paired_parent_bootstrap(
            {"C1": c1, "C0": c0}, paired_deltas=[("C1", "C0")], replicates=250, seed=20260723, expected_parents=4,
        )
        second = EVALUATE.paired_parent_bootstrap(
            {"C1": c1, "C0": c0}, paired_deltas=[("C1", "C0")], replicates=250, seed=20260723, expected_parents=4,
        )
        self.assertEqual(first, second)
        lower, upper = first["paired_deltas"]["C1_minus_C0"]["paired_percentile_95_ci"]
        self.assertGreater(lower, 0.0)
        self.assertGreaterEqual(upper, lower)

    def test_identical_model_paired_delta_is_exact_zero(self):
        rows = make_rows(32, parents=4)
        result = EVALUATE.paired_parent_bootstrap(
            {"C1": rows, "B0": list(rows)}, paired_deltas=[("C1", "B0")], replicates=80, seed=17,
        )
        delta = result["paired_deltas"]["C1_minus_B0"]
        self.assertEqual(delta["point_delta"], 0.0)
        self.assertEqual(delta["paired_percentile_95_ci"], [0.0, 0.0])

    def test_paired_bootstrap_rejects_truth_or_parent_misalignment(self):
        c1 = make_rows(20, parents=4)
        c0 = list(make_rows(20, parents=4))
        changed = c0[3]
        c0[3] = EVALUATE.OOFRow(**{**changed.__dict__, "parent_id": "wrong_parent"})
        with self.assertRaisesRegex(EVALUATE.EvaluationError, "paired_truth_or_parent_mismatch"):
            EVALUATE.paired_parent_bootstrap(
                {"C1": c1, "C0": c0}, paired_deltas=[("C1", "C0")], replicates=5, seed=1,
            )


if __name__ == "__main__":
    unittest.main()
