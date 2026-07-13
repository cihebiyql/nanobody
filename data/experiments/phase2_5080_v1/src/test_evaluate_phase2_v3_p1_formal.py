#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evaluate_phase2_v3_p1_formal as formal


class V3P1FormalEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.teacher_path = self.root / "teacher.csv"
        self.teacher_open_path = self.root / "teacher_open.csv"
        self.teacher_sealed_path = self.root / "teacher_test_sealed.csv"
        self.baseline_path = self.root / "baselines.csv"
        self.control_path = self.root / "controls.csv"
        self.replay_path = self.root / "generic_replay_retention.json"
        self.artifact_manifest_path = self.root / "formal_artifact_manifest.json"
        self.seed_paths: dict[int, Path] = {}
        rows: list[dict[str, object]] = []
        index = 0
        for split, cluster_count in (("dev", 3), ("test", 10)):
            for cluster in range(cluster_count):
                for position, tier in enumerate(("G1" if cluster % 2 == 0 else "G2", "G3", "G4", "G5")):
                    relevance = formal.TIER_TO_RELEVANCE[tier]
                    row: dict[str, object] = {
                        "candidate_id": f"{split}_p{cluster:02d}_{position}",
                        "formal_split": split,
                        "parent_framework_cluster": f"{split}_parent_{cluster:02d}",
                        "provisional_stable_geometry_tier": tier,
                    }
                    row["sequence_sha256"] = hashlib.sha256(
                        str(row["candidate_id"]).encode("utf-8")
                    ).hexdigest()
                    for field_index, field in enumerate(formal.GEOMETRY_FIELDS):
                        row[field] = relevance * (field_index + 1) + position * 0.01
                    rows.append(row)
                    index += 1
        teacher = pd.DataFrame(rows)
        teacher.to_csv(self.teacher_path, index=False)
        teacher.loc[teacher["formal_split"].eq("dev")].to_csv(
            self.teacher_open_path, index=False
        )
        sealed = teacher.loc[teacher["formal_split"].eq("test")].copy()
        sealed["sealed_status"] = "SEALED_FORMAL_TEST_LABEL"
        sealed.to_csv(self.teacher_sealed_path, index=False)

        baselines = teacher[
            ["candidate_id", "sequence_sha256", "formal_split", "parent_framework_cluster"]
        ].copy()
        positions = baselines["candidate_id"].str.rsplit("_", n=1).str[-1].astype(int)
        baselines["baseline_mid"] = positions.map({0: 3.0, 1: 4.0, 2: 2.0, 3: 1.0})
        tiers = teacher["provisional_stable_geometry_tier"].map(formal.TIER_TO_RELEVANCE)
        baselines["baseline_bad"] = -tiers.astype(float)
        baselines.to_csv(self.baseline_path, index=False)

        test = teacher.loc[teacher["formal_split"].eq("test")].copy()
        relevance = test["provisional_stable_geometry_tier"].map(formal.TIER_TO_RELEVANCE)
        for seed_index, seed in enumerate(formal.EXPECTED_SEEDS):
            prediction = test[
                ["candidate_id", "sequence_sha256", "formal_split", "parent_framework_cluster"]
            ].copy()
            prediction["predicted_relevance"] = relevance.astype(float) + seed_index * 0.001
            for field in formal.GEOMETRY_FIELDS:
                prediction[f"predicted_{field}"] = test[field].astype(float) + seed_index * 0.01
            path = self.root / f"seed_{seed}.csv"
            prediction.to_csv(path, index=False)
            self.seed_paths[seed] = path

        controls: list[dict[str, object]] = []
        for control_type in formal.REQUIRED_CONTROL_TYPES:
            for seed_index, seed in enumerate(formal.EXPECTED_SEEDS):
                for _, row in test.iterrows():
                    true_relevance = formal.TIER_TO_RELEVANCE[
                        str(row["provisional_stable_geometry_tier"])
                    ]
                    controls.append(
                        {
                            "candidate_id": row["candidate_id"],
                            "sequence_sha256": row["sequence_sha256"],
                            "formal_split": "test",
                            "parent_framework_cluster": row["parent_framework_cluster"],
                            "seed": seed,
                            "control_type": control_type,
                            "predicted_relevance": -float(true_relevance) + seed_index * 0.001,
                        }
                    )
        pd.DataFrame(controls).to_csv(self.control_path, index=False)
        self.replay_path.write_text(
            json.dumps(
                {
                    "schema_version": "phase2_v3_p1_generic_replay_retention_v1",
                    "per_seed": {
                        str(seed): {
                            "contact_auprc_retention_fraction": 0.95,
                            "paratope_auprc_retention_fraction": 0.96,
                        }
                        for seed in formal.EXPECTED_SEEDS
                    },
                }
            ),
            encoding="utf-8",
        )
        def record(path: Path) -> dict[str, str]:
            return {"path": str(path), "sha256": formal.sha256_file(path)}
        checkpoints = {}
        label_checkpoints = {}
        for seed in formal.EXPECTED_SEEDS:
            checkpoint = self.root / f"checkpoint_{seed}.pt"
            checkpoint.write_text(f"checkpoint-{seed}\n")
            label_checkpoint = self.root / f"label_checkpoint_{seed}.pt"
            label_checkpoint.write_text(f"label-checkpoint-{seed}\n")
            checkpoints[str(seed)] = record(checkpoint)
            label_checkpoints[str(seed)] = record(label_checkpoint)
        self.artifact_manifest_path.write_text(json.dumps({
            "status": "PASS_V3_P1_FORMAL_ARTIFACT_BUNDLE_READY",
            "seed_predictions": {str(seed): record(path) for seed, path in self.seed_paths.items()},
            "checkpoints": checkpoints,
            "label_shuffle_checkpoints": label_checkpoints,
            "bound_files": {"teacher_open": record(self.teacher_open_path), "teacher_sealed": record(self.teacher_sealed_path)},
            "bundle_outputs": {
                "baseline_predictions": record(self.baseline_path),
                "control_predictions": record(self.control_path),
                "generic_replay_retention": record(self.replay_path),
            },
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_formal_evaluation_passes_consistent_synthetic_signal(self) -> None:
        output = self.root / "evaluation"
        result = formal.evaluate_formal(
            self.teacher_open_path,
            self.teacher_sealed_path,
            self.seed_paths,
            self.baseline_path,
            self.control_path,
            self.replay_path,
            self.artifact_manifest_path,
            output,
            bootstrap_replicates=300,
            permutation_replicates=1023,
        )
        self.assertEqual(result["status"], "PASS_V3_P1_FORMAL_SURROGATE_GATE")
        self.assertTrue(result["all_checks_pass"])
        self.assertEqual(
            result["strongest_baseline_selection"]["selected_baseline"], "baseline_mid"
        )
        self.assertEqual(result["expected_seeds"], [83, 89, 97])
        self.assertEqual(result["formal_test_rows"], 40)
        self.assertAlmostEqual(
            result["ensemble_metrics"]["g1_g2_recall_at_20_percent"], 0.8
        )
        self.assertAlmostEqual(result["ensemble_metrics"]["g1_g2_ef_at_10_percent"], 4.0)
        self.assertGreater(result["parent_cluster_bootstrap"]["ci95_lower"], 0.0)
        self.assertLess(
            result["paired_parent_cluster_permutation"]["two_sided_p_value"], 0.05
        )
        self.assertTrue(
            all(
                value["rejected_as_null_or_target_independent"]
                for value in result["control_results"].values()
            )
        )
        self.assertTrue((output / "formal_evaluation.json").is_file())
        self.assertTrue((output / "formal_test_predictions_with_teacher_labels.csv").is_file())

    def test_artifact_manifest_hash_mismatch_fails_closed(self) -> None:
        prediction = pd.read_csv(self.seed_paths[83])
        prediction.loc[0, "predicted_relevance"] += 0.5
        prediction.to_csv(self.seed_paths[83], index=False)
        with self.assertRaisesRegex(ValueError, "artifact bundle mismatch"):
            formal.validate_artifact_bundle(
                self.artifact_manifest_path, self.seed_paths, self.baseline_path,
                self.control_path, self.replay_path,
            )

    def test_open_and_sealed_teacher_join_occurs_in_evaluator(self) -> None:
        teacher = pd.read_csv(self.teacher_path)
        loaded = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        self.assertEqual(len(loaded), len(teacher))
        self.assertEqual(set(loaded["formal_split"]), {"dev", "test"})

    def test_sealed_status_is_mandatory_and_exact(self) -> None:
        sealed = pd.read_csv(self.teacher_sealed_path)
        sealed.drop(columns="sealed_status").to_csv(self.teacher_sealed_path, index=False)
        with self.assertRaisesRegex(ValueError, "lack required sealed_status"):
            formal.load_teacher_parts(self.teacher_open_path, self.teacher_sealed_path)

        sealed.loc[0, "sealed_status"] = "OPEN_OR_MIXED"
        sealed.to_csv(self.teacher_sealed_path, index=False)
        with self.assertRaisesRegex(ValueError, "required sealed status"):
            formal.load_teacher_parts(self.teacher_open_path, self.teacher_sealed_path)

    def test_combined_teacher_cli_bypass_is_disabled(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                formal.parse_args(["--teacher", str(self.teacher_path)])

    def test_open_teacher_cannot_contain_test_labels(self) -> None:
        pd.read_csv(self.teacher_path).to_csv(self.teacher_open_path, index=False)
        with self.assertRaisesRegex(ValueError, "only train/dev"):
            formal.load_teacher_parts(self.teacher_open_path, self.teacher_sealed_path)

    def test_exact_three_seed_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly"):
            formal.parse_seed_paths([f"83={self.seed_paths[83]}", f"89={self.seed_paths[89]}"])
        teacher = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        with self.assertRaisesRegex(ValueError, "exactly"):
            formal.merge_three_seed_predictions(
                teacher, {83: self.seed_paths[83], 89: self.seed_paths[89]}
            )

    def test_prediction_labels_are_rejected_before_join(self) -> None:
        contaminated = pd.read_csv(self.seed_paths[83])
        contaminated["true_relevance"] = 4
        contaminated.to_csv(self.seed_paths[83], index=False)
        teacher = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        with self.assertRaisesRegex(ValueError, "pre-evaluator label"):
            formal.merge_three_seed_predictions(teacher, self.seed_paths)

    def test_sequence_hash_mismatch_is_rejected(self) -> None:
        prediction = pd.read_csv(self.seed_paths[83])
        prediction.loc[0, "sequence_sha256"] = "0" * 64
        prediction.to_csv(self.seed_paths[83], index=False)
        teacher = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        with self.assertRaisesRegex(ValueError, "sequence_sha256"):
            formal.merge_three_seed_predictions(teacher, self.seed_paths)

    def test_baseline_is_selected_on_dev_only(self) -> None:
        teacher = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        selected, _, audit = formal.select_strongest_baseline(teacher, self.baseline_path)
        self.assertEqual(selected, "baseline_mid")
        self.assertEqual(audit["selection_split"], "dev")
        self.assertNotIn("test_metrics", audit)

    def test_missing_control_or_candidate_fails_closed(self) -> None:
        controls = pd.read_csv(self.control_path)
        controls = controls.loc[~controls["control_type"].eq("vhh_only")]
        controls.to_csv(self.control_path, index=False)
        teacher = formal.load_teacher_parts(
            self.teacher_open_path, self.teacher_sealed_path
        )
        with self.assertRaisesRegex(ValueError, "Controls must be exactly"):
            formal.load_controls(
                self.control_path, teacher.loc[teacher["formal_split"].eq("test")]
            )


if __name__ == "__main__":
    unittest.main()
