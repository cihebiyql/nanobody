#!/usr/bin/env python3

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "fit_shared_nonnegative_stack_v1.py"
SPEC = importlib.util.spec_from_file_location("fit_shared_nonnegative_stack_v1", MODULE_PATH)
assert SPEC and SPEC.loader
stack = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stack
SPEC.loader.exec_module(stack)


def digest(parents: list[str]) -> str:
    return stack.canonical_parent_set_sha256(parents)


def receipt_sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def make_row(
    candidate: str,
    source: str,
    parent: str,
    outer_fold: str,
    features: tuple[float, float, float, float, float, float],
    receipt: str,
    feature_fold: str,
    training_parents: list[str],
    theta: tuple[float, float, float, float, float] = (0.1, 0.2, 0.7, 0.4, 0.25),
) -> dict[str, str]:
    m8, m9, n8, n9, c8, c9 = features
    i8, i9, bm, bn, bc = theta
    return {
        "candidate_id": candidate,
        "teacher_source": source,
        "parent_framework_cluster": parent,
        "outer_fold": outer_fold,
        "R_8X6B": repr(i8 + bm * m8 + bn * n8 + bc * c8),
        "R_9E6Y": repr(i9 + bm * m9 + bn * n9 + bc * c9),
        "M2_R8": repr(m8),
        "M2_R9": repr(m9),
        "neural_R8": repr(n8),
        "neural_R9": repr(n9),
        "contact_score_R8": repr(c8),
        "contact_score_R9": repr(c9),
        "feature_outer_fold": feature_fold,
        "base_training_parent_set_sha256": digest(training_parents),
        "base_model_receipt_sha256": receipt,
    }


def synthetic_bundle():
    theta = (0.1, 0.2, 0.7, 0.4, 0.25)
    receipt_a = receipt_sha("fit-a")
    receipt_b = receipt_sha("fit-b")
    receipt_s = receipt_sha("score")
    fit_rows = [
        make_row("A1", "V4D", "PA", "1", (0.1, 0.8, 0.7, 0.2, 0.3, 0.5), receipt_a, "ia", ["PB", "PD"], theta),
        make_row("A2", "V4D", "PA", "1", (0.9, 0.2, 0.1, 0.6, 0.8, 0.4), receipt_a, "ia", ["PB", "PD"], theta),
        make_row("B1", "V4D", "PB", "2", (0.4, 0.3, 0.9, 0.1, 0.2, 0.7), receipt_b, "ib", ["PA", "PC"], theta),
        make_row("C1", "V4H", "PC", "3", (0.6, 0.4, 0.2, 0.8, 0.9, 0.1), receipt_a, "ia", ["PB", "PD"], theta),
        make_row("C2", "V4H", "PC", "3", (0.2, 0.9, 0.5, 0.3, 0.6, 0.8), receipt_a, "ia", ["PB", "PD"], theta),
        make_row("D1", "V4H", "PD", "4", (0.8, 0.1, 0.4, 0.9, 0.1, 0.6), receipt_b, "ib", ["PA", "PC"], theta),
    ]
    score_rows = [
        make_row("E1", "V4D", "PE", "0", (0.35, 0.75, 0.55, 0.25, 0.45, 0.65), receipt_s, "outer0", ["PA", "PB", "PC", "PD"], theta),
        make_row("F1", "V4H", "PF", "0", (0.75, 0.35, 0.25, 0.55, 0.65, 0.45), receipt_s, "outer0", ["PA", "PB", "PC", "PD"], theta),
    ]
    provenance = {
        "schema_version": stack.PROVENANCE_SCHEMA_VERSION,
        "feature_receipts": {
            receipt_a: {
                "feature_outer_fold": "ia",
                "training_parent_framework_clusters": ["PB", "PD"],
                "training_parent_set_sha256": digest(["PB", "PD"]),
            },
            receipt_b: {
                "feature_outer_fold": "ib",
                "training_parent_framework_clusters": ["PA", "PC"],
                "training_parent_set_sha256": digest(["PA", "PC"]),
            },
            receipt_s: {
                "feature_outer_fold": "outer0",
                "training_parent_framework_clusters": ["PA", "PB", "PC", "PD"],
                "training_parent_set_sha256": digest(["PA", "PB", "PC", "PD"]),
            },
        },
        "stack_outer_folds": {
            "0": {
                "meta_training_parent_framework_clusters": ["PA", "PB", "PC", "PD"],
                "meta_training_parent_set_sha256": digest(["PA", "PB", "PC", "PD"]),
                "score_parent_framework_clusters": ["PE", "PF"],
                "score_parent_set_sha256": digest(["PE", "PF"]),
            }
        },
    }
    return theta, fit_rows, score_rows, provenance


class SharedStackTests(unittest.TestCase):
    def test_recovers_five_shared_nonnegative_parameters(self):
        theta, fit_rows, _, _ = synthetic_bundle()
        model, audit = stack.fit_shared_nonnegative_stack(fit_rows)
        np.testing.assert_allclose(model.as_vector(), theta, rtol=0, atol=2e-12)
        self.assertEqual(model.parameter_count, 5)
        self.assertEqual(audit["parameter_count"], 5)
        self.assertGreaterEqual(model.beta_M2, 0.0)
        self.assertGreaterEqual(model.beta_neural, 0.0)
        self.assertGreaterEqual(model.beta_contact, 0.0)

    def test_hierarchical_weights_are_source_parent_candidate_exact(self):
        _, fit_rows, _, _ = synthetic_bundle()
        weights, audit = stack.compute_source_parent_candidate_weights(fit_rows)
        self.assertAlmostEqual(weights.sum(), 1.0, places=15)
        by_candidate = {row["candidate_id"]: weights[i] for i, row in enumerate(fit_rows)}
        self.assertAlmostEqual(by_candidate["A1"], 0.125)
        self.assertAlmostEqual(by_candidate["A2"], 0.125)
        self.assertAlmostEqual(by_candidate["B1"], 0.25)
        self.assertAlmostEqual(by_candidate["C1"], 0.125)
        self.assertAlmostEqual(by_candidate["C2"], 0.125)
        self.assertAlmostEqual(by_candidate["D1"], 0.25)
        self.assertAlmostEqual(audit["sources"]["V4D"]["mass"], 0.5)
        self.assertAlmostEqual(audit["sources"]["V4H"]["mass"], 0.5)

    def test_rdual_is_bit_exact_numpy_minimum(self):
        _, fit_rows, score_rows, _ = synthetic_bundle()
        model, _ = stack.fit_shared_nonnegative_stack(fit_rows)
        predictions = stack.predict_shared_stack(model, score_rows)
        for prediction in predictions:
            observed = np.float64(prediction["prediction_R_dual_min"])
            expected = np.minimum(
                np.float64(prediction["prediction_R8"]),
                np.float64(prediction["prediction_R9"]),
            )
            self.assertEqual(observed.tobytes(), expected.tobytes())

    def test_fold_provenance_passes_complete_nested_exclusion(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        audit = stack.validate_fold_provenance(fit_rows, score_rows, provenance, "0")
        self.assertEqual(audit["status"], "PASS_NO_PARENT_LEAKAGE")
        self.assertEqual(audit["meta_training_parent_count"], 4)
        self.assertEqual(audit["score_parent_count"], 2)

    def test_fold_provenance_rejects_base_training_parent_leakage(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        broken = copy.deepcopy(provenance)
        receipt = fit_rows[0]["base_model_receipt_sha256"]
        broken["feature_receipts"][receipt]["training_parent_framework_clusters"].append("PA")
        broken["feature_receipts"][receipt]["training_parent_set_sha256"] = digest(["PB", "PD", "PA"])
        for row in fit_rows:
            if row["base_model_receipt_sha256"] == receipt:
                row["base_training_parent_set_sha256"] = digest(["PB", "PD", "PA"])
        with self.assertRaisesRegex(stack.StackValidationError, "base_feature_parent_leakage"):
            stack.validate_fold_provenance(fit_rows, score_rows, broken, "0")

    def test_fold_provenance_rejects_feature_fold_mismatch(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        fit_rows[0]["feature_outer_fold"] = "wrong"
        with self.assertRaisesRegex(stack.StackValidationError, "feature_fold_mismatch"):
            stack.validate_fold_provenance(fit_rows, score_rows, provenance, "0")

    def test_fold_provenance_rejects_row_parent_digest_mismatch(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        fit_rows[0]["base_training_parent_set_sha256"] = "0" * 64
        with self.assertRaisesRegex(stack.StackValidationError, "row_training_parent_digest_mismatch"):
            stack.validate_fold_provenance(fit_rows, score_rows, provenance, "0")

    def test_fold_provenance_rejects_outer_score_feature_parent_leakage(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        receipt = score_rows[0]["base_model_receipt_sha256"]
        broken = copy.deepcopy(provenance)
        parents = ["PA", "PB", "PC", "PD", "PE"]
        broken["feature_receipts"][receipt]["training_parent_framework_clusters"] = parents
        broken["feature_receipts"][receipt]["training_parent_set_sha256"] = digest(parents)
        for row in score_rows:
            row["base_training_parent_set_sha256"] = digest(parents)
        with self.assertRaisesRegex(stack.StackValidationError, "base_feature_parent_leakage"):
            stack.validate_fold_provenance(fit_rows, score_rows, broken, "0")

    def test_fold_provenance_rejects_manifest_digest_mismatch(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        provenance["stack_outer_folds"]["0"]["score_parent_set_sha256"] = "0" * 64
        with self.assertRaisesRegex(stack.StackValidationError, "parent_set_digest_mismatch"):
            stack.validate_fold_provenance(fit_rows, score_rows, provenance, "0")

    def test_fold_provenance_rejects_score_parent_overlap(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        provenance["stack_outer_folds"]["0"]["score_parent_framework_clusters"] = ["PA", "PE", "PF"]
        provenance["stack_outer_folds"]["0"]["score_parent_set_sha256"] = digest(["PA", "PE", "PF"])
        with self.assertRaisesRegex(stack.StackValidationError, "meta_train_score_parent_overlap"):
            stack.validate_fold_provenance(fit_rows, score_rows, provenance, "0")

    def test_legacy_v23_dual_only_oof_fails_closed(self):
        legacy = [{
            "candidate_id": "X",
            "teacher_source": "V4D",
            "parent_framework_cluster": "PX",
            "outer_fold": "0",
            "R_dual_min": "0.5",
            "m2_prediction": "0.4",
            "residue_prediction": "0.45",
        }]
        with self.assertRaisesRegex(stack.StackValidationError, "missing_required_columns"):
            stack.validate_input_rows(legacy)

    def test_negative_slope_is_constrained_to_zero(self):
        _, rows, _, _ = synthetic_bundle()
        for row in rows:
            m8 = float(row["M2_R8"])
            m9 = float(row["M2_R9"])
            row["R_8X6B"] = repr(1.0 - 0.8 * m8 + 0.3 * float(row["neural_R8"]) + 0.2 * float(row["contact_score_R8"]))
            row["R_9E6Y"] = repr(1.2 - 0.8 * m9 + 0.3 * float(row["neural_R9"]) + 0.2 * float(row["contact_score_R9"]))
        model, _ = stack.fit_shared_nonnegative_stack(rows)
        self.assertGreaterEqual(model.beta_M2, 0.0)
        self.assertLess(model.beta_M2, 1e-10)

    def test_cli_writes_model_predictions_and_receipt(self):
        _, fit_rows, score_rows, provenance = synthetic_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit_path = root / "fit.tsv"
            score_path = root / "score.tsv"
            provenance_path = root / "provenance.json"
            for path, rows in ((fit_path, fit_rows), (score_path, score_rows)):
                with path.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
            provenance_path.write_text(json.dumps(provenance, sort_keys=True) + "\n")
            args = stack.argparse.Namespace(
                fit_tsv=str(fit_path),
                score_tsv=str(score_path),
                provenance_json=str(provenance_path),
                outer_fold="0",
                output_dir=str(root / "output"),
            )
            receipt = stack.run(args)
            self.assertEqual(receipt["status"], "PASS_PROTOTYPE_STACK_FIT")
            model_payload = json.loads((root / "output" / "model.json").read_text())
            self.assertEqual(model_payload["parameter_count"], 5)
            with (root / "output" / "outer_test_predictions.tsv").open() as handle:
                predictions = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(predictions), 2)
            for row in predictions:
                dual = np.float64(row["prediction_R_dual_min"])
                expected = np.minimum(np.float64(row["prediction_R8"]), np.float64(row["prediction_R9"]))
                self.assertEqual(dual.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
