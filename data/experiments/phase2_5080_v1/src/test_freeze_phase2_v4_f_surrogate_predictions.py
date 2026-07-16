#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

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
        bank = MOD.embedding.load_embedding_bank(
            self.fixture.embedding_manifest_path,
            self.fixture.embedding_summary_path,
            self.fixture.sequence_manifest_path,
            enforce_production_hashes=False,
        )
        stable = tuple(
            column
            for feature in selected
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        )
        selected_name = "embedding_contact_fusion"
        spec = MOD.contact.build_feature_spec(selected_name, stable, bank.esm2.shape[1])
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
        models[selected_name] = selected_model
        stage_inputs = {
            str(path.resolve()): sha(path)
            for path in (
                self.fixture.teacher_path,
                self.fixture.teacher_audit_path,
                self.fixture.split_path,
                self.contact_receipt,
                self.contact_audit,
                self.contact_features,
                self.contact_schema,
                self.contact_schema.with_suffix(".receipt.json"),
                self.fixture.embedding_manifest_path,
                self.fixture.embedding_summary_path,
                self.fixture.sequence_manifest_path,
                Path(MOD.contact.__file__),
                Path(MOD.base.__file__),
                Path(MOD.embedding.__file__),
            )
        }
        stage_inputs.update(
            {
                payload["path"]: payload["sha256"]
                for payload in bank.provenance["shards"].values()
            }
        )
        identity = {
            "embedding_bank_identity_sha256": bank.provenance["identity_sha256"],
            "contact_release_receipt_sha256": sha(self.contact_receipt),
            "contact_schema_sha256": sha(self.contact_schema),
            "stable_contact_columns_sha256": MOD.base.sha256_strings(stable),
        }
        stage_closure = MOD.contact.sha256_json(stage_inputs)
        write_json(
            config_path,
            {
                "status": "FROZEN_OPEN_CONFIGURATION_BEFORE_PROSPECTIVE_TEST_UNSEAL",
                "artifact_identity_contract": identity,
                "stage_input_hashes": stage_inputs,
                "stage_inputs_closure_sha256": stage_closure,
            },
        )
        write_json(
            artifact_path,
            {
                "schema_version": MOD.contact.SCHEMA_VERSION,
                "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
                "config_sha256": sha(config_path),
                "selected_candidate_model": selected_name,
                "models": models,
                "prospective_test_labels_read": False,
                **identity,
                "stage_inputs_closure_sha256": stage_closure,
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
                "inputs": stage_inputs,
                "outputs": {str(path.resolve()): sha(path) for path in outputs},
                "stable_contact_columns": list(stable),
                **identity,
                "stage_inputs_closure_sha256": stage_closure,
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
        audit = {
                "status": "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN",
                "execution_mode": "test_fixture",
                "output": {"sha256": sha(self.manifest)},
                "checks": {"row_count": 4},
                "future_release_policy": {
                    "labels": "do not compute or open before model/config/test predictions are frozen"
                },
            }
        audit["audit_payload_sha256"] = MOD.sha256_json(audit)
        write_json(self.manifest_audit, audit)
        write_json(
            self.manifest_receipt,
            {
                "status": "PASS_COMPLETE_HASH_CLOSURE",
                "execution_mode": "test_fixture",
                "manifest_sha256": sha(self.manifest),
                "audit_file_sha256": sha(self.manifest_audit),
                "audit_payload_sha256": audit["audit_payload_sha256"],
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
        ]
        if command == "freeze":
            common += [
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

    def parsed_args(self, command: str = "freeze") -> Namespace:
        return MOD.build_parser().parse_args(self.command(command)[2:])

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


def refresh_holdout_closure(fixture: V4FPredictionFixture) -> None:
    audit = json.loads(fixture.manifest_audit.read_text())
    audit.pop("audit_payload_sha256", None)
    audit["audit_payload_sha256"] = MOD.sha256_json(audit)
    write_json(fixture.manifest_audit, audit)
    receipt = json.loads(fixture.manifest_receipt.read_text())
    receipt["manifest_sha256"] = sha(fixture.manifest)
    receipt["audit_file_sha256"] = sha(fixture.manifest_audit)
    receipt["audit_payload_sha256"] = audit["audit_payload_sha256"]
    write_json(fixture.manifest_receipt, receipt)


def refresh_prediction_output_closure(fixture: V4FPredictionFixture) -> None:
    prediction = fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]
    audit_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[1]
    receipt_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
    audit = json.loads(audit_path.read_text())
    audit["prediction_sha256"] = sha(prediction)
    write_json(audit_path, audit)
    receipt = json.loads(receipt_path.read_text())
    receipt["outputs"]["predictions"]["sha256"] = sha(prediction)
    receipt["outputs"]["audit"]["sha256"] = sha(audit_path)
    write_json(receipt_path, receipt)


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

    def test_production_gate_rejects_fake_verifier_before_docking_exec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            marker = fixture.root / "fake_verifier_launched_docking"
            env = fixture.watcher_env()
            env.update(
                {
                    "PVRIG_EXP_DIR": str(MOD.PRODUCTION_ROOT),
                    "PYTHON": str(
                        MOD.PRODUCTION_ROOT / ".venv-phase2-5080/bin/python"
                    ),
                    "V4F_PREDICTION_FREEZER": "/bin/true",
                    "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "0",
                }
            )
            result = subprocess.run(
                [
                    str(DOCKING_GATE),
                    "--",
                    sys.executable,
                    "-c",
                    f"open({str(marker)!r},'w').write('x')",
                ],
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(
                "production V4F_PREDICTION_FREEZER override is forbidden",
                result.stderr,
            )
            self.assertFalse(marker.exists())

    def test_output_mutation_at_final_verification_check_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            args = fixture.parsed_args("verify-receipt")
            output_paths = {
                name: fixture.prediction_out / name for name in MOD.OUTPUT_FILENAMES
            }
            original_payloads = {
                name: path.read_bytes() for name, path in output_paths.items()
            }
            original_verify_inputs = MOD.verify_input_hashes
            for name, target in output_paths.items():
                with self.subTest(output=name):
                    for restore_name, restore_path in output_paths.items():
                        restore_path.write_bytes(original_payloads[restore_name])
                    mutated = False

                    def mutate_output_after_input_check(
                        input_hashes: dict[str, str],
                    ) -> None:
                        nonlocal mutated
                        original_verify_inputs(input_hashes)
                        if not mutated:
                            replacement = target.with_suffix(target.suffix + ".replacement")
                            replacement.write_bytes(target.read_bytes() + b"\n")
                            os.replace(replacement, target)
                            mutated = True

                    with patch.object(
                        MOD,
                        "verify_input_hashes",
                        mutate_output_after_input_check,
                    ):
                        with self.assertRaisesRegex(
                            MOD.PredictionFreezeError,
                            "verified_output_changed",
                        ):
                            MOD.verify_receipt(args)
                    self.assertTrue(mutated)

    def test_atomic_source_replacement_after_import_cannot_publish_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = V4FPredictionFixture(root / "fixture")
            isolated_src = root / "isolated/src"
            isolated_src.mkdir(parents=True)
            source_files = {
                Path(MOD.__file__).resolve(),
                *(path.resolve() for path in MOD._EXECUTION_DEPENDENCY_FILES.values()),
            }
            for source in source_files:
                shutil.copy2(source, isolated_src / source.name)
            isolated_freezer = isolated_src / Path(MOD.__file__).name
            module_name = "isolated_v4f_freezer_atomic_replacement_test"
            previous_modules = {
                name: sys.modules.get(name)
                for name in MOD._EXECUTION_DEPENDENCY_FILES
            }
            spec = importlib.util.spec_from_file_location(module_name, isolated_freezer)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            isolated = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = isolated
            try:
                spec.loader.exec_module(isolated)
                args = isolated.build_parser().parse_args(fixture.command()[2:])
                replacement = isolated_freezer.with_suffix(".replacement.py")
                replacement.write_bytes(
                    isolated_freezer.read_bytes()
                    + b"\n# atomic replacement after module import\n"
                )
                os.replace(replacement, isolated_freezer)
                with self.assertRaisesRegex(
                    isolated.PredictionFreezeError,
                    "executed_source_changed",
                ):
                    isolated.run_freeze(args)
                self.assertFalse(
                    (fixture.prediction_out / isolated.OUTPUT_FILENAMES[2]).exists()
                )
            finally:
                sys.modules.pop(module_name, None)
                for name, previous in previous_modules.items():
                    sys.modules.pop(name, None)
                    if previous is not None:
                        sys.modules[name] = previous

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
            refresh_holdout_closure(fixture)
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

    def test_empty_or_incomplete_input_hashes_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            receipt_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
            audit_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[1]
            original_receipt = json.loads(receipt_path.read_text())
            original_audit = json.loads(audit_path.read_text())
            full_inputs = dict(original_receipt["input_hashes"])
            cases = ({}, dict(list(full_inputs.items())[1:]))
            for forged in cases:
                with self.subTest(input_count=len(forged)):
                    audit = dict(original_audit)
                    audit["input_hashes"] = forged
                    audit["input_count"] = len(forged)
                    audit["input_closure_sha256"] = MOD.sha256_json(forged)
                    write_json(audit_path, audit)
                    receipt = dict(original_receipt)
                    receipt["input_hashes"] = forged
                    receipt["input_count"] = len(forged)
                    receipt["input_closure_sha256"] = MOD.sha256_json(forged)
                    receipt["outputs"] = json.loads(json.dumps(original_receipt["outputs"]))
                    receipt["outputs"]["audit"]["sha256"] = sha(audit_path)
                    write_json(receipt_path, receipt)
                    result = fixture.run("verify-receipt")
                    self.assertEqual(result.returncode, 2, result.stdout)

    def test_test_fixture_receipt_is_rejected_by_production_verifier_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            command = fixture.command("verify-receipt")
            command.remove("--test-only-allow-unfrozen-inputs")
            verifier = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(verifier.returncode, 2)
            marker = fixture.root / "forbidden_docking"
            env = fixture.watcher_env()
            env.update(
                {
                    "V4F_TEST_ONLY_ALLOW_UNFROZEN_INPUTS": "0",
                    "V4F_PREDICTION_RECEIPT": str(
                        fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
                    ),
                }
            )
            gate = subprocess.run(
                [
                    str(DOCKING_GATE),
                    "--",
                    sys.executable,
                    "-c",
                    f"open({str(marker)!r},'w').write('x')",
                ],
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(gate.returncode, 2)
            self.assertFalse(marker.exists())

    def test_python_rejects_test_mode_on_any_production_trust_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            args = fixture.parsed_args()
            args.manifest = MOD.PRODUCTION_PATHS["manifest"]
            with self.assertRaisesRegex(
                MOD.PredictionFreezeError,
                "test_only_mode_forbidden_on_production_paths:manifest",
            ):
                MOD.run_freeze(args)

    def test_contact_artifact_identity_mismatches_are_rejected(self) -> None:
        fields = (
            "embedding_bank_identity_sha256",
            "contact_release_receipt_sha256",
            "contact_schema_sha256",
        )
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture = V4FPredictionFixture(Path(temporary))
                artifact_path = (
                    fixture.contact_out / "contact_fusion_open_model_artifact.json"
                )
                artifact = json.loads(artifact_path.read_text())
                artifact[field] = "0" * 64
                write_json(artifact_path, artifact)
                stage_receipt_path = (
                    fixture.contact_out
                    / "contact_fusion_frozen_artifact_sha256_receipt.json"
                )
                stage_receipt = json.loads(stage_receipt_path.read_text())
                stage_receipt["outputs"][str(artifact_path.resolve())] = sha(artifact_path)
                write_json(stage_receipt_path, stage_receipt)
                result = fixture.run()
                self.assertEqual(result.returncode, 2, result.stdout)

    def test_mid_run_replacement_of_consumed_inputs_fails(self) -> None:
        targets = {
            "manifest": lambda fixture: fixture.manifest,
            "artifact": lambda fixture: fixture.base_out / "frozen_open_model_artifact.json",
            "contact_features": lambda fixture: fixture.contact_features,
            "embedding_metadata": lambda fixture: fixture.fixture.embedding_summary_path,
        }
        for label, selector in targets.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = V4FPredictionFixture(Path(temporary))
                target = selector(fixture)
                original_verify = MOD.verify_input_hashes
                changed = False

                def replace_then_verify(input_hashes: dict[str, str]) -> None:
                    nonlocal changed
                    if not changed:
                        target.write_bytes(target.read_bytes() + b"\n")
                        changed = True
                    original_verify(input_hashes)

                with patch.object(MOD, "verify_input_hashes", replace_then_verify):
                    with self.assertRaises(MOD.PredictionFreezeError):
                        MOD.run_freeze(fixture.parsed_args())
                self.assertFalse(
                    (fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]).exists()
                )

    def test_embedding_contact_fusion_replay_uses_frozen_order_and_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            rows, _ = MOD.read_table(
                fixture.prediction_out / MOD.OUTPUT_FILENAMES[0], "\t"
            )
            self.assertEqual(
                {row["contact_selected_model"] for row in rows},
                {"embedding_contact_fusion"},
            )
            context = MOD.prepare_replay(fixture.parsed_args(), waiting=False)
            self.assertEqual(rows, context.prediction_rows)
            self.assertEqual(
                [row["candidate_id"] for row in rows],
                [row["candidate_id"] for row in context.rows],
            )

    def test_every_manifest_identity_field_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            prediction_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]
            original_prediction = prediction_path.read_bytes()
            original_audit = (
                fixture.prediction_out / MOD.OUTPUT_FILENAMES[1]
            ).read_bytes()
            original_receipt = (
                fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
            ).read_bytes()
            for field in MOD.IDENTITY_FIELDS:
                with self.subTest(field=field):
                    prediction_path.write_bytes(original_prediction)
                    (fixture.prediction_out / MOD.OUTPUT_FILENAMES[1]).write_bytes(
                        original_audit
                    )
                    (fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]).write_bytes(
                        original_receipt
                    )
                    rows, _ = MOD.read_table(prediction_path, "\t")
                    rows[0][field] = rows[0][field] + "_tampered"
                    write_table(prediction_path, rows, "\t")
                    refresh_prediction_output_closure(fixture)
                    result = fixture.run("verify-receipt")
                    self.assertEqual(result.returncode, 2, result.stdout)

    def test_invalid_existing_receipt_blocks_watcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            prediction = fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]
            prediction.write_bytes(prediction.read_bytes() + b"\n")
            result = subprocess.run(
                [str(WATCHER)],
                env=fixture.watcher_env(),
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            status = json.loads(
                (
                    fixture.root
                    / "status/pvrig_v4_f_prediction_freeze_v1/status.json"
                ).read_text()
            )
            self.assertEqual(status["status"], "BLOCKED_INVALID_PREDICTION_RECEIPT")

    def test_existing_corrupt_receipt_shapes_are_not_treated_as_absent(self) -> None:
        for shape in ("zero_byte", "non_regular", "unreadable"):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as temporary:
                fixture = V4FPredictionFixture(Path(temporary))
                fixture.prediction_out.mkdir(parents=True)
                receipt = fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
                if shape == "zero_byte":
                    receipt.touch()
                elif shape == "non_regular":
                    receipt.mkdir()
                else:
                    receipt.write_text("{}\n", encoding="utf-8")
                    receipt.chmod(0)
                try:
                    result = subprocess.run(
                        [str(WATCHER)],
                        env=fixture.watcher_env(),
                        text=True,
                        capture_output=True,
                    )
                finally:
                    if receipt.is_file():
                        receipt.chmod(0o600)
                self.assertEqual(result.returncode, 2, result.stderr)
                status = json.loads(
                    (
                        fixture.root
                        / "status/pvrig_v4_f_prediction_freeze_v1/status.json"
                    ).read_text()
                )
                self.assertEqual(
                    status["status"], "BLOCKED_INVALID_PREDICTION_RECEIPT"
                )
                invalid_log = (
                    fixture.root
                    / "status/pvrig_v4_f_prediction_freeze_v1/verification.invalid.json"
                )
                self.assertIn(
                    "existing prediction receipt is corrupt",
                    invalid_log.read_text(encoding="utf-8"),
                )

    def test_interrupted_publication_never_leaves_a_final_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            env = {
                **os.environ,
                "V4F_TEST_ONLY_FAIL_AFTER_PUBLISH_COUNT": "2",
            }
            result = subprocess.run(
                fixture.command(), env=env, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertTrue(
                (fixture.prediction_out / MOD.OUTPUT_FILENAMES[0]).is_file()
            )
            self.assertTrue(
                (fixture.prediction_out / MOD.OUTPUT_FILENAMES[1]).is_file()
            )
            self.assertFalse(
                (fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]).exists()
            )

    def test_primary_evaluation_policy_is_frozen_in_audit_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = V4FPredictionFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            receipt_path = fixture.prediction_out / MOD.OUTPUT_FILENAMES[2]
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(
                receipt["primary_evaluation_policy_sha256"],
                MOD.PRIMARY_EVALUATION_POLICY_SHA256,
            )
            receipt["primary_evaluation_policy"]["primary_model_family"] = "base"
            write_json(receipt_path, receipt)
            self.assertEqual(fixture.run("verify-receipt").returncode, 2)

    def test_real_v4f96_label_free_inputs_preflight(self) -> None:
        registry = MOD.SnapshotRegistry()
        rows, hashes, audit, receipt = MOD.validate_holdout(
            registry,
            MOD.PRODUCTION_PATHS["manifest"],
            MOD.PRODUCTION_PATHS["manifest_audit"],
            MOD.PRODUCTION_PATHS["manifest_receipt"],
            enforce_production_hashes=True,
            expected_count=96,
        )
        self.assertEqual(len(rows), 96)
        self.assertFalse(MOD.FORBIDDEN_MANIFEST_FIELDS & set(rows[0]))
        manifest_snapshot = registry.take(
            MOD.PRODUCTION_PATHS["embedding_manifest"], "embedding_manifest"
        )
        summary_snapshot = registry.take(
            MOD.PRODUCTION_PATHS["embedding_summary"], "embedding_summary"
        )
        sequence_snapshot = registry.take(
            MOD.PRODUCTION_PATHS["embedding_sequence_manifest"],
            "embedding_sequence_manifest",
        )
        bank = MOD.embedding.load_embedding_bank(
            MOD.PRODUCTION_PATHS["embedding_manifest"],
            MOD.PRODUCTION_PATHS["embedding_summary"],
            MOD.PRODUCTION_PATHS["embedding_sequence_manifest"],
            enforce_production_hashes=True,
            embedding_manifest_snapshot=MOD.embedding.FileSnapshot(
                manifest_snapshot.path,
                manifest_snapshot.payload,
                manifest_snapshot.sha256,
            ),
            embedding_summary_snapshot=MOD.embedding.FileSnapshot(
                summary_snapshot.path,
                summary_snapshot.payload,
                summary_snapshot.sha256,
            ),
            sequence_manifest_snapshot=MOD.embedding.FileSnapshot(
                sequence_snapshot.path,
                sequence_snapshot.payload,
                sequence_snapshot.sha256,
            ),
        )
        sequence_hashes = [row["sequence_sha256"] for row in rows]
        self.assertEqual(bank.matrix(sequence_hashes, "esm2_ridge").shape, (96, 320))
        contacts, stable_columns, metadata = MOD.load_contact_replay(
            registry,
            MOD.PRODUCTION_PATHS["contact_receipt"],
            MOD.PRODUCTION_PATHS["contact_schema"],
            {row["candidate_id"] for row in rows},
            enforce_production_hashes=True,
        )
        self.assertEqual(len({row["candidate_id"] for row in rows} & set(contacts)), 96)
        self.assertTrue(
            all(
                contacts[row["candidate_id"]]["sequence_sha256"]
                == row["sequence_sha256"]
                for row in rows
            )
        )
        self.assertTrue(stable_columns)
        self.assertEqual(hashes["manifest"], MOD.EXPECTED_MANIFEST_SHA256)
        self.assertEqual(audit["execution_mode"], "production")
        self.assertEqual(receipt["execution_mode"], "production")
        self.assertEqual(metadata["receipt_sha256"], MOD.EXPECTED_CONTACT_FEATURE_RECEIPT_SHA256)


if __name__ == "__main__":
    unittest.main()
