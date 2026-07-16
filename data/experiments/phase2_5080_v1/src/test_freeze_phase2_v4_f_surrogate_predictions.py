#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import freeze_phase2_v4_f_surrogate_predictions as MOD
from test_train_phase2_v4_d_frozen_embedding_surrogate import FrozenEmbeddingFixture


WATCHER = SCRIPT_DIR / "monitor_phase2_v4_f_prediction_freeze.sh"
DOCKING_GATE = SCRIPT_DIR / "run_phase2_v4_f_docking_with_prediction_gate.sh"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_table(path: Path, rows: list[dict[str, object]], delimiter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter=delimiter, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


class V4FPredictionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.embedding_fixture = FrozenEmbeddingFixture(root / "embedding_fixture")
        self.base_out = root / "base_out"
        self.embedding_out = root / "embedding_out"
        self.contact_out = root / "contact_out"
        self.contact_features = root / "contact_features.csv"
        self.contact_audit = root / "contact_features.audit.json"
        self.contact_receipt = root / "contact_features.receipt.json"
        self.contact_schema = root / "frozen_contact_feature_schema_v2.json"
        self.manifest = root / "v4f_manifest.tsv"
        self.manifest_audit = root / "v4f_manifest.audit.json"
        self.manifest_receipt = root / "v4f_manifest.receipt.json"
        self.prediction_out = root / "predictions"
        self._train_base_and_embedding()
        self._make_contact_release_and_artifact()
        self._make_holdout()

    @property
    def fixture(self) -> FrozenEmbeddingFixture:
        return self.embedding_fixture

    def _train_base_and_embedding(self) -> None:
        MOD.base.run_pipeline(
            self.fixture.teacher_path,
            self.fixture.teacher_audit_path,
            self.fixture.split_path,
            self.base_out,
            alphas=(0.1, 1.0),
            ensemble_seeds=(11, 12, 13),
            frozen_feature_width=12,
            enforce_production_split_hash=False,
        )
        MOD.embedding.run_pipeline(
            self.fixture.teacher_path,
            self.fixture.teacher_audit_path,
            self.fixture.split_path,
            self.fixture.embedding_manifest_path,
            self.fixture.embedding_summary_path,
            self.fixture.sequence_manifest_path,
            self.embedding_out,
            release_receipt_path=self.fixture.release_receipt_path,
            alphas=(0.1, 1.0),
            ensemble_seeds=(11, 12, 13),
            enforce_production_hashes=False,
        )

    def _make_contact_release_and_artifact(self) -> None:
        contact_v3 = MOD.contact.contact_v3
        stable_columns = [
            column
            for feature in contact_v3.STABLE_FEATURE_NAMES
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        ]
        rows: list[dict[str, object]] = []
        for index, manifest in enumerate(self.fixture.split_rows):
            row: dict[str, object] = {
                "schema_version": contact_v3.SCHEMA_VERSION,
                "supersedes": ";".join(contact_v3.SUPERSEDED_SCHEMA_VERSIONS),
                "candidate_id": manifest["candidate_id"],
                "sequence_sha256": manifest["sequence_sha256"],
            }
            for feature_index, feature in enumerate(contact_v3.STABLE_FEATURE_NAMES, start=1):
                row[f"{feature}_seed_mean"] = 0.1 + index / 1000 + feature_index / 10000
                row[f"{feature}_seed_std"] = 0.005 + feature_index / 100000
            for feature in contact_v3.DIAGNOSTIC_ONLY_FEATURES:
                row[f"{feature}_seed_mean"] = 100.0
                row[f"{feature}_seed_std"] = 5.0
            rows.append(row)
        write_table(self.contact_features, rows, ",")
        dummy = self.root / "label_free_input.txt"
        dummy.write_text("label-free\n", encoding="utf-8")
        snapshot = contact_v3.snapshot_files({"label_free_input": dummy})
        write_json(
            self.contact_audit,
            {
                "status": "PASS",
                "feature_schema_version": contact_v3.SCHEMA_VERSION,
                "output_sha256": sha(self.contact_features),
                "input_snapshot_unchanged": True,
                "label_free_contract": {
                    "production_hash_locks_enforced": False,
                    "test_only_unfrozen_hash_override": True,
                },
                "feature_policy": {
                    "stable_default_trainer_features": list(contact_v3.STABLE_FEATURE_NAMES),
                    "stable_default_trainer_columns": stable_columns,
                    "default_trainer_must_exclude": list(contact_v3.DIAGNOSTIC_ONLY_FEATURES),
                    "default_trainer_must_exclude_columns": [
                        f"{feature}_seed_mean" for feature in contact_v3.DIAGNOSTIC_ONLY_FEATURES
                    ],
                },
            },
        )
        write_json(
            self.contact_receipt,
            {
                "status": "PASS",
                "schema_version": contact_v3.RECEIPT_SCHEMA_VERSION,
                "feature_schema_version": contact_v3.SCHEMA_VERSION,
                "output": str(self.contact_features.resolve()),
                "output_sha256": sha(self.contact_features),
                "output_row_count": len(rows),
                "audit": str(self.contact_audit.resolve()),
                "audit_sha256": sha(self.contact_audit),
                "input_snapshot": snapshot,
                "input_snapshot_content_closure_sha256": contact_v3.snapshot_content_closure(
                    snapshot
                ),
                "script": str(Path(contact_v3.__file__).resolve()),
                "script_sha256": sha(Path(contact_v3.__file__)),
                "claim_boundary": contact_v3.CLAIM_BOUNDARY,
            },
        )

        selected = tuple(contact_v3.STABLE_FEATURE_NAMES[2:5])
        configuration = {
            "schema_version": MOD.contact.CONTACT_SCHEMA_VERSION,
            "selection_uses_docking_labels": False,
            "production_hash_enforcement": False,
        }
        schema: dict[str, object] = {
            "schema_version": MOD.contact.CONTACT_SCHEMA_VERSION,
            "status": "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA",
            "execution_mode": "test_only",
            "configuration": configuration,
            "configuration_sha256": MOD.contact.sha256_json(configuration),
            "inputs": {
                "feature_release_receipt": {
                    "path": str(self.contact_receipt.resolve()),
                    "sha256": sha(self.contact_receipt),
                }
            },
            "selected_feature_count": len(selected),
            "selected_features": list(selected),
            "diagnostic_only_length_confounded_features": list(
                contact_v3.DIAGNOSTIC_ONLY_FEATURES
            ),
            "required_shortcut_baseline": "cdr_length_only",
            "training_feature_sets": {
                "stable_seed_mean": [f"{feature}_seed_mean" for feature in selected],
                "stable_seed_mean_and_std": [
                    column
                    for feature in selected
                    for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
                ],
            },
            "feature_stability": [
                {
                    "feature": feature,
                    "selected": True,
                    "cross_seed_stable": True,
                    "length_confounded": False,
                }
                for feature in selected
            ],
        }
        schema["payload_sha256"] = MOD.contact.sha256_json(schema)
        write_json(self.contact_schema, schema)
        write_json(
            self.contact_schema.with_suffix(".receipt.json"),
            {
                "schema_version": MOD.contact.CONTACT_SCHEMA_RECEIPT_VERSION,
                "status": "TEST_ONLY_PASS_HASH_CLOSURE",
                "configuration_sha256": schema["configuration_sha256"],
                "feature_release_receipt_sha256": sha(self.contact_receipt),
                "schema_file_sha256": sha(self.contact_schema),
                "schema_payload_sha256": schema["payload_sha256"],
            },
        )

        self.contact_out.mkdir()
        config_path = self.contact_out / "contact_fusion_open_model_config.json"
        artifact_path = self.contact_out / "contact_fusion_open_model_artifact.json"
        predictions_path = self.contact_out / "contact_fusion_open_development_predictions.tsv"
        summary_path = self.contact_out / "contact_fusion_open_development_summary.json"
        write_json(config_path, {"status": "FROZEN_OPEN_CONFIGURATION_BEFORE_PROSPECTIVE_TEST_UNSEAL"})
        stable = tuple(
            column
            for feature in selected
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        )
        spec = MOD.contact.build_feature_spec("stable_contact_mean", stable, 4)
        width = len(spec.feature_names)
        fit = MOD.base.RidgeFit(
            intercept=0.1,
            coefficient=np.linspace(0.01, 0.02, width),
            center=np.zeros(width),
            scale=np.ones(width),
        )
        selected_model = {
            "feature_spec": spec.to_json(),
            "bootstrap_ensemble_fits": [
                {"seed": seed, "fit": fit.to_json()} for seed in (11, 12, 13)
            ],
        }
        models = {name: {} for name in MOD.contact.MODEL_NAMES}
        models["stable_contact_mean"] = selected_model
        write_json(
            artifact_path,
            {
                "schema_version": MOD.contact.SCHEMA_VERSION,
                "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
                "config_sha256": sha(config_path),
                "selected_candidate_model": "stable_contact_mean",
                "models": models,
                "prospective_test_labels_read": False,
            },
        )
        predictions_path.write_text("candidate_id\tmodel_split\nD\tOPEN_DEVELOPMENT\n")
        write_json(
            summary_path,
            {
                "status": "OPEN_DEVELOPMENT_EVALUATED_PROSPECTIVE_TEST_STILL_SEALED",
                "prospective_test": {"labels_read": False, "label_files_opened": 0},
            },
        )
        outputs = [config_path, artifact_path, predictions_path, summary_path]
        write_json(
            self.contact_out / "contact_fusion_frozen_artifact_sha256_receipt.json",
            {
                "status": "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE",
                "prospective_test_labels_read": False,
                "outputs": {str(path.resolve()): sha(path) for path in outputs},
            },
        )

    def _make_holdout(self) -> None:
        source = [
            row
            for row in self.fixture.split_rows
            if row["model_split"] == MOD.base.SEALED_SPLIT
        ][:4]
        rows = []
        for row in source:
            rows.append(
                {
                    **row,
                    "model_split": MOD.MODEL_SPLIT,
                    "selection_stratum": "fixture",
                    "full_qc_and_docking_policy": "fixture",
                    "claim_boundary": "fixture",
                }
            )
        write_table(self.manifest, rows, "\t")
        write_json(
            self.manifest_audit,
            {
                "status": "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN",
                "output": {"sha256": sha(self.manifest)},
                "checks": {"row_count": 4},
                "future_release_policy": {
                    "labels": "do not compute or open before model/config/test predictions are frozen"
                },
            },
        )
        write_json(
            self.manifest_receipt,
            {
                "status": "PASS_COMPLETE_HASH_CLOSURE",
                "manifest_sha256": sha(self.manifest),
                "audit_file_sha256": sha(self.manifest_audit),
            },
        )

    def command(self, command: str = "freeze") -> list[str]:
        common = [
            sys.executable,
            str(SCRIPT_DIR / "freeze_phase2_v4_f_surrogate_predictions.py"),
            command,
            "--manifest",
            str(self.manifest),
            "--manifest-audit",
            str(self.manifest_audit),
            "--manifest-receipt",
            str(self.manifest_receipt),
            "--expected-count",
            "4",
            "--test-only-allow-unfrozen-inputs",
        ]
        if command == "freeze":
            common += [
                "--base-out",
                str(self.base_out),
                "--embedding-out",
                str(self.embedding_out),
                "--contact-out",
                str(self.contact_out),
                "--embedding-manifest",
                str(self.fixture.embedding_manifest_path),
                "--embedding-summary",
                str(self.fixture.embedding_summary_path),
                "--embedding-sequence-manifest",
                str(self.fixture.sequence_manifest_path),
                "--contact-receipt",
                str(self.contact_receipt),
                "--contact-schema",
                str(self.contact_schema),
                "--out-dir",
                str(self.prediction_out),
            ]
        else:
            common += [
                "--receipt",
                str(self.prediction_out / MOD.OUTPUT_FILENAMES[-1]),
            ]
        return common

    def run(self, command: str = "freeze") -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.command(command), text=True, capture_output=True)

    def watcher_env(self) -> dict[str, str]:
        status = self.root / "surrogate_status.json"
        write_json(status, {"status": "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED"})
        return {
            **os.environ,
            "PVRIG_EXP_DIR": str(self.root),
            "PYTHON": sys.executable,
            "V4F_PREDICTION_FREEZER": str(SCRIPT_DIR / "freeze_phase2_v4_f_surrogate_predictions.py"),
            "V4D_SURROGATE_STATUS": str(status),
            "V4F_MANIFEST": str(self.manifest),
            "V4F_MANIFEST_AUDIT": str(self.manifest_audit),
            "V4F_MANIFEST_RECEIPT": str(self.manifest_receipt),
            "V4D_BASE_SURROGATE_OUT": str(self.base_out),
            "V4D_EMBEDDING_SURROGATE_OUT": str(self.embedding_out),
            "V4D_CONTACT_SURROGATE_OUT": str(self.contact_out),
            "V4D_EMBEDDING_MANIFEST": str(self.fixture.embedding_manifest_path),
            "V4D_EMBEDDING_SUMMARY": str(self.fixture.embedding_summary_path),
            "V4D_EMBEDDING_SEQUENCE_MANIFEST": str(self.fixture.sequence_manifest_path),
            "V4D_CONTACT_FEATURE_RECEIPT": str(self.contact_receipt),
            "V4D_CONTACT_SCHEMA": str(self.contact_schema),
            "V4F_PREDICTION_OUT": str(self.prediction_out),
            "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "1",
            "V4F_EXPECTED_COUNT": "4",
            "ONCE": "1",
            "POLL_SECONDS": "1",
        }


class V4FPredictionFreezeTests(unittest.TestCase):
    def test_freeze_verify_idempotence_and_docking_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            marker = fixture.root / "docking_started"
            gate_env = {
                **fixture.watcher_env(),
                "V4F_PREDICTION_RECEIPT": str(fixture.prediction_out / MOD.OUTPUT_FILENAMES[-1]),
            }
            blocked = subprocess.run(
                [str(DOCKING_GATE), "--", sys.executable, "-c", f"open({str(marker)!r},'w').write('x')"],
                env=gate_env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(blocked.returncode, 4)
            self.assertFalse(marker.exists())

            result = fixture.run()
            self.assertEqual(result.returncode, 0, result.stderr)
            prediction_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]
            rows = MOD.read_table(prediction_path, "\t")[0]
            self.assertEqual(len(rows), 4)
            self.assertFalse(MOD.FORBIDDEN_OUTPUT_FIELDS & set(rows[0]))
            first_hash = sha(prediction_path)
            self.assertEqual(fixture.run().returncode, 0)
            self.assertEqual(sha(prediction_path), first_hash)
            self.assertEqual(fixture.run("verify-receipt").returncode, 0)

            allowed = subprocess.run(
                [str(DOCKING_GATE), "--", sys.executable, "-c", f"open({str(marker)!r},'w').write('x')"],
                env=gate_env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertTrue(marker.exists())

    def test_tampered_prediction_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            prediction = fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]
            prediction.write_text(prediction.read_text() + "\n")
            result = fixture.run("verify-receipt")
            self.assertEqual(result.returncode, 2)

    def test_label_column_in_holdout_is_rejected_before_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            rows, _ = MOD.read_table(fixture.manifest, "\t")
            for row in rows:
                row["R_dual_min"] = "999"
            write_table(fixture.manifest, rows, "\t")
            audit = json.loads(fixture.manifest_audit.read_text())
            audit["output"]["sha256"] = sha(fixture.manifest)
            write_json(fixture.manifest_audit, audit)
            receipt = json.loads(fixture.manifest_receipt.read_text())
            receipt["manifest_sha256"] = sha(fixture.manifest)
            receipt["audit_file_sha256"] = sha(fixture.manifest_audit)
            write_json(fixture.manifest_receipt, receipt)
            result = fixture.run()
            self.assertEqual(result.returncode, 2)
            self.assertFalse(fixture.prediction_out.exists())

    def test_missing_contact_artifact_waits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            (fixture.contact_out / "contact_fusion_frozen_artifact_sha256_receipt.json").unlink()
            result = fixture.run()
            self.assertEqual(result.returncode, 4)
            self.assertIn("WAITING_V4_D_SURROGATES", result.stdout)

    def test_watcher_freezes_only_after_complete_surrogate_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            env = fixture.watcher_env()
            status_path = Path(env["V4D_SURROGATE_STATUS"])
            write_json(status_path, {"status": "WAITING_OPEN_TEACHER"})
            waiting = subprocess.run([str(WATCHER)], env=env, text=True, capture_output=True)
            self.assertEqual(waiting.returncode, 4, waiting.stderr)
            self.assertFalse(fixture.prediction_out.exists())
            write_json(status_path, {"status": "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED"})
            complete = subprocess.run([str(WATCHER)], env=env, text=True, capture_output=True)
            self.assertEqual(complete.returncode, 0, complete.stderr)
            watcher_status = fixture.root / "status/pvrig_v4_f_prediction_freeze_v1/status.json"
            self.assertEqual(
                json.loads(watcher_status.read_text())["status"],
                "COMPLETE_V4_F_96_PREDICTIONS_FROZEN",
            )


if __name__ == "__main__":
    unittest.main()
