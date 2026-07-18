#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from collect_residue_oof_v2 import (  # noqa: E402
    V4D,
    V4H,
    CollectorError,
    collect,
    exact_top_indices,
    sha256_file,
    validate_and_join_rows,
    validate_preregistration,
)


REAL_PREREGISTRATION = ROOT / "PREREGISTRATION_V2.json"
TRAINING_FIELDS = [
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "R_dual_min",
]
PREDICTION_FIELDS = [
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "R_dual_min",
    "m2_prediction",
    "residue_prediction",
    "lane",
    "model_version",
]


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class SyntheticPanel:
    def __init__(self, root: Path, *, model_mode: str = "perfect") -> None:
        self.root = root
        prereg = json.loads(REAL_PREREGISTRATION.read_text())
        self.preregistration = root / "preregistration.json"
        self.preregistration.write_text(json.dumps(prereg, indent=2, sort_keys=True) + "\n")

        training_rows: list[dict[str, str]] = []
        prediction_by_fold: dict[int, list[dict[str, str]]] = {fold: [] for fold in range(5)}
        source_sizes = {V4D: (226, 20), V4H: (1281, 11)}
        for source_index, source in enumerate((V4D, V4H)):
            candidate_count, parent_count = source_sizes[source]
            base_size, remainder = divmod(candidate_count, parent_count)
            source_ordinal = 0
            for parent_index in range(parent_count):
                parent = f"{source}_P{parent_index}"
                fold = parent_index % 5
                members = base_size + int(parent_index < remainder)
                for member in range(members):
                    # Separate source ranges while preserving informative variation
                    # inside every parent cluster.
                    target = 0.05 + source_index * 0.50 + 0.40 * source_ordinal / (candidate_count - 1)
                    baseline = 1.0 - target
                    model = target if model_mode == "perfect" else baseline
                    candidate = f"{source_index}_{parent_index}_{member}"
                    truth = {
                        "candidate_id": candidate,
                        "teacher_source": source,
                        "parent_framework_cluster": parent,
                        "outer_fold": str(fold),
                        "R_dual_min": f"{target:.9f}",
                    }
                    prediction = {
                        **truth,
                        "m2_prediction": f"{baseline:.9f}",
                        "residue_prediction": f"{model:.9f}",
                        "lane": "D_FULL_PAIR",
                        "model_version": "synthetic_test",
                    }
                    training_rows.append(truth)
                    prediction_by_fold[fold].append(prediction)
                    source_ordinal += 1
        self.training_tsv = root / "training.tsv"
        write_tsv(self.training_tsv, TRAINING_FIELDS, training_rows)
        self.prediction_tsvs = []
        for fold in range(5):
            path = root / f"fold_{fold}.tsv"
            write_tsv(path, PREDICTION_FIELDS, prediction_by_fold[fold])
            self.prediction_tsvs.append(path)

    def args(self, output_dir: Path) -> argparse.Namespace:
        return argparse.Namespace(
            training_tsv=self.training_tsv,
            prediction_tsv=self.prediction_tsvs,
            preregistration=self.preregistration,
            output_dir=output_dir,
            bootstrap_repetitions=200,
            bootstrap_seed=20260718,
        )


class FrozenContractTests(unittest.TestCase):
    def test_real_preregistration_exact_gate_contract_validates(self) -> None:
        payload = validate_preregistration(REAL_PREREGISTRATION)
        self.assertEqual(payload["promotion_gates"]["positive_status"], "PROMOTE_RESIDUE_V2_OVER_M2")
        self.assertEqual(payload["promotion_gates"]["negative_status"], "DO_NOT_PROMOTE_RESIDUE_V2")
        self.assertEqual(payload["promotion_gates"]["global_top20_budget"], 302)

    def test_added_or_missing_gate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = json.loads(REAL_PREREGISTRATION.read_text())
            payload["promotion_gates"]["post_hoc_gate"] = True
            path = root / "bad.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(CollectorError, "promotion_gate_key_closure"):
                validate_preregistration(path)

    def test_exact_top_ties_are_resolved_by_candidate_id(self) -> None:
        rows = [
            {"candidate_id": "B", "score": 0.5},
            {"candidate_id": "A", "score": 0.5},
            {"candidate_id": "D", "score": 0.5},
            {"candidate_id": "C", "score": 0.5},
        ]
        selected = exact_top_indices(rows, "score", 2)
        self.assertEqual({rows[index]["candidate_id"] for index in selected}, {"A", "B"})


class CollectorEndToEndTests(unittest.TestCase):
    def test_strong_model_passes_every_frozen_gate_and_writes_auditable_oof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = SyntheticPanel(root, model_mode="perfect")
            output = root / "output"
            report = collect(panel.args(output))
            self.assertEqual(report["status"], "PROMOTE_RESIDUE_V2_OVER_M2")
            self.assertEqual(report["promotion"]["failed_gates"], [])
            self.assertTrue(all(report["promotion"]["gates"].values()))
            for source in (V4D, V4H):
                source_bootstrap = report["promotion"]["source_stratified"][source]["parent_bootstrap"]
                self.assertGreaterEqual(source_bootstrap["positive_fraction"], 0.8)
                self.assertGreaterEqual(source_bootstrap["median_delta_spearman"], 0.0)
            self.assertEqual(report["source_counts"], {V4D: 226, V4H: 1281})
            self.assertEqual(report["candidate_count"], 1507)

            oof = output / "residue_v2_nested_oof_predictions.tsv"
            decision = output / "OOF_PROMOTION_REPORT.json"
            self.assertTrue(oof.is_file())
            self.assertTrue(decision.is_file())
            stored = json.loads(decision.read_text())
            self.assertEqual(stored["outputs"]["oof_predictions_sha256"], sha256_file(oof))
            with oof.open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 1507)
            self.assertEqual(len({row["candidate_id"] for row in rows}), 1507)
            self.assertEqual({row["teacher_source"] for row in rows}, {V4D, V4H})

    def test_any_gate_failure_yields_frozen_do_not_promote_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = SyntheticPanel(root, model_mode="baseline")
            report = collect(panel.args(root / "output"))
            self.assertEqual(report["status"], "DO_NOT_PROMOTE_RESIDUE_V2")
            self.assertGreater(len(report["promotion"]["failed_gates"]), 0)
            self.assertFalse(all(report["promotion"]["gates"].values()))
            self.assertIn("global_spearman_delta_min", report["promotion"]["failed_gates"])
            self.assertIn("v4d_parent_bootstrap_positive_fraction", report["promotion"]["failed_gates"])
            self.assertIn("v4h_parent_bootstrap_positive_fraction", report["promotion"]["failed_gates"])

    def test_duplicate_prediction_candidate_fails_before_any_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = SyntheticPanel(root)
            fields, rows = self._read(panel.prediction_tsvs[0])
            rows.append(copy.deepcopy(rows[0]))
            write_tsv(panel.prediction_tsvs[0], fields, rows)
            prereg = validate_preregistration(panel.preregistration)
            with self.assertRaisesRegex(CollectorError, "prediction_duplicate_candidate"):
                validate_and_join_rows(panel.training_tsv, panel.prediction_tsvs, prereg)

    @staticmethod
    def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            return list(reader.fieldnames or []), list(reader)


if __name__ == "__main__":
    unittest.main()
