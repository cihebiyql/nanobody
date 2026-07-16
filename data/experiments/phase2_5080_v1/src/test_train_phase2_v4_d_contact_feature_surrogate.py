#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "train_phase2_v4_d_contact_feature_surrogate.py"
SPEC = importlib.util.spec_from_file_location(
    "train_phase2_v4_d_contact_feature_surrogate", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class ContactFusionSurrogateTest(unittest.TestCase):
    COUNTS = {
        MOD.TRAIN_SPLIT: 12,
        MOD.DEVELOPMENT_SPLIT: 8,
        MOD.SEALED_SPLIT: 4,
    }
    CLUSTERS = {
        MOD.TRAIN_SPLIT: 3,
        MOD.DEVELOPMENT_SPLIT: 2,
        MOD.SEALED_SPLIT: 1,
    }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.split = self.root / "split.tsv"
        self.teacher = self.root / "teacher.tsv"
        self.teacher_audit = self.root / "teacher.tsv.audit.json"
        self.embedding_manifest = self.root / "embeddings/manifest.csv"
        self.embedding_summary = self.root / "embeddings/summary.json"
        self.embedding_sequence_manifest = self.root / "embeddings/sequence_manifest.csv"
        self.contact_features = self.root / "contact_features.csv"
        self.contact_audit = self.root / "contact_features.audit.json"
        self.contact_receipt = self.root / "contact_features.receipt.json"
        self.contact_schema = self.root / "frozen_contact_feature_schema_v2.json"
        self.out_dir = self.root / "out"
        self.manifest_rows, self.teacher_rows = self.make_split_and_teacher()
        write_tsv(self.split, self.manifest_rows)
        write_tsv(self.teacher, self.teacher_rows)
        self.teacher_audit.write_text(
            json.dumps(
                {
                    "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
                    "release": "open_train_and_open_development_only",
                    "inputs": {"split_manifest_sha256": MOD.sha256_file(self.split)},
                    "sealed_data_boundary": {
                        "raw_job_results_opened": 0,
                        "sealed_metrics_used_for_teacher_or_ranking": False,
                    },
                    "output": {"sha256": MOD.sha256_file(self.teacher)},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.make_contact_release()
        self.make_contact_schema()
        self.make_embeddings()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_split_and_teacher(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        alphabet = MOD.base.AA_ORDER
        manifests: list[dict[str, object]] = []
        teachers: list[dict[str, object]] = []
        layout = (
            (MOD.TRAIN_SPLIT, 12, "T", 3),
            (MOD.DEVELOPMENT_SPLIT, 8, "D", 2),
            (MOD.SEALED_SPLIT, 4, "S", 1),
        )
        global_index = 0
        for split, count, prefix, parent_count in layout:
            for local_index in range(count):
                candidate_id = f"candidate-{global_index:02d}"
                sequence = alphabet + alphabet[global_index % len(alphabet)] + alphabet[
                    (global_index // len(alphabet)) % len(alphabet)
                ]
                cdr1 = sequence[:3]
                cdr2 = sequence[3:6]
                cdr3 = sequence[6 : 10 + (global_index % 4)]
                parent = f"{prefix}{local_index % parent_count}"
                digest = MOD.base.sequence_sha256(sequence)
                manifest = {
                    "candidate_id": candidate_id,
                    "model_split": split,
                    "parent_framework_cluster": parent,
                    "sequence_sha256": digest,
                    "sequence": sequence,
                    "design_method": "synthetic",
                    "design_mode": "H3",
                    "target_patch_id": "A_CENTER",
                    "cdr1": cdr1,
                    "cdr2": cdr2,
                    "cdr3": cdr3,
                }
                manifests.append(manifest)
                if split != MOD.SEALED_SPLIT:
                    signal = 0.1 + global_index * 0.035
                    teachers.append(
                        {
                            **manifest,
                            "generic_binding_prior": 0.25 + signal / 4,
                            MOD.PRIMARY_TARGET: signal,
                        }
                    )
                global_index += 1
        return manifests, teachers

    def make_contact_release(self) -> None:
        stable_columns = [
            column
            for feature in MOD.contact_v3.STABLE_FEATURE_NAMES
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        ]
        rows: list[dict[str, object]] = []
        for index, manifest in enumerate(self.manifest_rows):
            signal = 0.1 + index * 0.035
            row: dict[str, object] = {
                "schema_version": MOD.contact_v3.SCHEMA_VERSION,
                "supersedes": ";".join(MOD.contact_v3.SUPERSEDED_SCHEMA_VERSIONS),
                "candidate_id": manifest["candidate_id"],
                "sequence_sha256": manifest["sequence_sha256"],
            }
            for feature_index, feature in enumerate(MOD.contact_v3.STABLE_FEATURE_NAMES, start=1):
                row[f"{feature}_seed_mean"] = signal * (1 + feature_index / 100)
                row[f"{feature}_seed_std"] = 0.005 + (index % 3) * 0.001 + feature_index / 100000
            for feature in MOD.contact_v3.DIAGNOSTIC_ONLY_FEATURES:
                row[f"{feature}_seed_mean"] = signal * 100
                row[f"{feature}_seed_std"] = 5.0
            rows.append(row)
        write_csv(self.contact_features, rows)
        dummy = self.root / "label_free_input.txt"
        dummy.write_text("label-free\n", encoding="utf-8")
        snapshot = MOD.contact_v3.snapshot_files({"label_free_input": dummy})
        audit = {
            "status": "PASS",
            "feature_schema_version": MOD.contact_v3.SCHEMA_VERSION,
            "output_sha256": MOD.sha256_file(self.contact_features),
            "input_snapshot_unchanged": True,
            "label_free_contract": {
                "production_hash_locks_enforced": False,
                "test_only_unfrozen_hash_override": True,
            },
            "feature_policy": {
                "stable_default_trainer_features": list(MOD.contact_v3.STABLE_FEATURE_NAMES),
                "stable_default_trainer_columns": stable_columns,
                "default_trainer_must_exclude": list(MOD.contact_v3.DIAGNOSTIC_ONLY_FEATURES),
                "default_trainer_must_exclude_columns": [
                    f"{feature}_seed_mean"
                    for feature in MOD.contact_v3.DIAGNOSTIC_ONLY_FEATURES
                ],
            },
        }
        self.contact_audit.write_text(json.dumps(audit) + "\n", encoding="utf-8")
        receipt = {
            "status": "PASS",
            "schema_version": MOD.contact_v3.RECEIPT_SCHEMA_VERSION,
            "feature_schema_version": MOD.contact_v3.SCHEMA_VERSION,
            "output": str(self.contact_features.resolve()),
            "output_sha256": MOD.sha256_file(self.contact_features),
            "output_row_count": len(rows),
            "audit": str(self.contact_audit.resolve()),
            "audit_sha256": MOD.sha256_file(self.contact_audit),
            "input_snapshot": snapshot,
            "input_snapshot_content_closure_sha256": MOD.contact_v3.snapshot_content_closure(
                snapshot
            ),
            "script": str(Path(MOD.contact_v3.__file__).resolve()),
            "script_sha256": MOD.sha256_file(Path(MOD.contact_v3.__file__)),
            "claim_boundary": MOD.contact_v3.CLAIM_BOUNDARY,
        }
        self.contact_receipt.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

    def make_contact_schema(self) -> None:
        selected = tuple(MOD.contact_v3.STABLE_FEATURE_NAMES[2:7])
        configuration = {
            "schema_version": MOD.CONTACT_SCHEMA_VERSION,
            "selection_uses_docking_labels": False,
            "production_hash_enforcement": False,
        }
        schema: dict[str, object] = {
            "schema_version": MOD.CONTACT_SCHEMA_VERSION,
            "status": "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA",
            "execution_mode": "test_only",
            "configuration": configuration,
            "configuration_sha256": MOD.sha256_json(configuration),
            "inputs": {
                "feature_release_receipt": {
                    "path": str(self.contact_receipt.resolve()),
                    "sha256": MOD.sha256_file(self.contact_receipt),
                }
            },
            "selected_feature_count": len(selected),
            "selected_features": list(selected),
            "diagnostic_only_length_confounded_features": list(
                MOD.contact_v3.DIAGNOSTIC_ONLY_FEATURES
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
        schema["payload_sha256"] = MOD.sha256_json(schema)
        self.contact_schema.write_text(json.dumps(schema) + "\n", encoding="utf-8")
        schema_receipt = {
            "schema_version": MOD.CONTACT_SCHEMA_RECEIPT_VERSION,
            "status": "TEST_ONLY_PASS_HASH_CLOSURE",
            "configuration_sha256": schema["configuration_sha256"],
            "feature_release_receipt_sha256": MOD.sha256_file(self.contact_receipt),
            "schema_file_sha256": MOD.sha256_file(self.contact_schema),
            "schema_payload_sha256": schema["payload_sha256"],
        }
        self.contact_schema.with_suffix(".receipt.json").write_text(
            json.dumps(schema_receipt) + "\n", encoding="utf-8"
        )

    def make_embeddings(self) -> None:
        self.embedding_manifest.parent.mkdir(parents=True)
        hashes = [str(row["sequence_sha256"]) for row in self.manifest_rows]
        dimension = 6
        matrix = torch.zeros((len(hashes), dimension), dtype=torch.float32)
        for index in range(len(hashes)):
            signal = 0.1 + index * 0.035
            matrix[index] = torch.tensor(
                [signal, signal**2, index / len(hashes), index % 2, index % 3, 1.0]
            )
        config = {
            "backend": "synthetic",
            "esm2_dim": dimension,
            "pooling": "mean",
        }
        config_sha = MOD.frozen_embedding.sha256_json(config)
        shard = self.embedding_manifest.parent / "shard_00000.pt"
        torch.save(
            {
                "schema_version": "synthetic",
                "config_sha256": MOD.frozen_embedding.sha256_json(
                    {"config": config, "sequence_sha256": hashes}
                ),
                "sequence_sha256": hashes,
                "esm2": matrix,
            },
            shard,
        )
        rows = [
            {
                "sequence_sha256": digest,
                "sequence_length": len(str(self.manifest_rows[index]["sequence"])),
                "roles": "vhh",
                "shard_path": "shard_00000.pt",
                "shard_index": index,
                "esm2_dim": dimension,
                "config_sha256": config_sha,
            }
            for index, digest in enumerate(hashes)
        ]
        write_csv(self.embedding_manifest, rows)
        write_csv(
            self.embedding_sequence_manifest,
            [
                {
                    "sequence_sha256": digest,
                    "sequence": self.manifest_rows[index]["sequence"],
                    "sequence_length": len(str(self.manifest_rows[index]["sequence"])),
                    "roles": "vhh",
                }
                for index, digest in enumerate(hashes)
            ],
        )
        self.embedding_summary.write_text(
            json.dumps(
                {
                    "schema_version": "phase2_v3_embedding_summary_v1",
                    "embedding_manifest_sha256": MOD.sha256_file(self.embedding_manifest),
                    "sequence_manifest": str(self.embedding_sequence_manifest.resolve()),
                    "sequence_manifest_sha256": MOD.sha256_file(
                        self.embedding_sequence_manifest
                    ),
                    "sequence_count": len(rows),
                    "config": config,
                    "config_sha256": config_sha,
                    "shard_sha256": {shard.name: MOD.sha256_file(shard)},
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def run_fixture_pipeline(self) -> dict[str, object]:
        return MOD.run_pipeline(
            self.teacher,
            self.teacher_audit,
            self.split,
            self.contact_receipt,
            self.contact_schema,
            self.embedding_manifest,
            self.embedding_summary,
            self.out_dir,
            alphas=(0.1, 1.0),
            ensemble_seeds=(11, 12, 13),
            expected_counts=self.COUNTS,
            expected_cluster_counts=self.CLUSTERS,
            enforce_production_locks=False,
        )

    def test_pipeline_compares_required_models_and_keeps_test_labels_sealed(self) -> None:
        result = self.run_fixture_pipeline()
        self.assertFalse(result["prospective_test_labels_read"])
        self.assertTrue(all((self.out_dir / name).is_file() for name in MOD.OUTPUT_FILENAMES))
        summary = json.loads(
            (self.out_dir / "contact_fusion_open_development_summary.json").read_text()
        )
        config = json.loads((self.out_dir / "contact_fusion_open_model_config.json").read_text())
        artifact = json.loads(
            (self.out_dir / "contact_fusion_open_model_artifact.json").read_text()
        )
        receipt = json.loads(
            (self.out_dir / "contact_fusion_frozen_artifact_sha256_receipt.json").read_text()
        )
        self.assertEqual(set(summary["models"]), set(MOD.MODEL_NAMES))
        self.assertEqual(summary["fit"]["rows"], 12)
        self.assertEqual(summary["selection"]["rows"], 8)
        self.assertFalse(summary["prospective_test"]["labels_read"])
        self.assertEqual(summary["prospective_test"]["label_files_opened"], 0)
        self.assertIn("parent_macro_contract", summary)
        self.assertIn("selected_model_uncertainty_contract", summary)
        self.assertEqual(
            config["contact_feature_policy"]["source"],
            "verified_v3_receipt_plus_frozen_v2_schema_selected_features_only",
        )
        self.assertEqual(
            config["contact_feature_policy"]["diagnostic_or_length_confounded_columns_used"],
            [],
        )
        self.assertEqual(receipt["status"], "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE")
        self.assertFalse(receipt["prospective_test_labels_read"])
        self.assertEqual(receipt["diagnostic_or_docking_alias_columns_used"], [])
        identity_fields = (
            "embedding_bank_identity_sha256",
            "contact_release_receipt_sha256",
            "contact_schema_sha256",
            "stable_contact_columns_sha256",
            "stage_inputs_closure_sha256",
        )
        for field in identity_fields:
            self.assertEqual(artifact[field], receipt[field])
            self.assertEqual(
                artifact[field], summary["artifact_identity_contract"][field]
            )
        self.assertEqual(
            receipt["stage_inputs_closure_sha256"],
            MOD.sha256_json(receipt["inputs"]),
        )
        self.assertEqual(
            receipt["contact_release_receipt_sha256"],
            MOD.sha256_file(self.contact_receipt),
        )
        self.assertEqual(
            receipt["contact_schema_sha256"], MOD.sha256_file(self.contact_schema)
        )
        self.assertEqual(
            receipt["stable_contact_columns_sha256"],
            MOD.base.sha256_strings(receipt["stable_contact_columns"]),
        )
        self.assertIn(str(self.embedding_sequence_manifest.resolve()), receipt["inputs"])
        for path, digest in receipt["outputs"].items():
            self.assertEqual(MOD.sha256_file(Path(path)), digest)
        predictions = MOD.base.read_tsv(
            self.out_dir / "contact_fusion_open_development_predictions.tsv"
        )
        self.assertEqual(len(predictions), 8)
        self.assertTrue(all(row["model_split"] == MOD.DEVELOPMENT_SPLIT for row in predictions))
        for model in MOD.MODEL_NAMES:
            self.assertIn(f"prediction_{model}", predictions[0])
            self.assertIn(f"uncertainty_{model}", predictions[0])

    def test_contact_loader_materializes_only_stable_allowlisted_values(self) -> None:
        open_ids = {str(row["candidate_id"]) for row in self.teacher_rows}
        rows, stable, metadata = MOD.load_verified_contact_release(
            self.contact_receipt,
            self.contact_schema,
            open_ids,
            enforce_production_hash=False,
        )
        self.assertEqual(set(next(iter(rows.values()))), {"candidate_id", "sequence_sha256", *stable})
        self.assertEqual(metadata["diagnostic_columns_used"], [])
        self.assertTrue(all("diagnostic" not in column for column in stable))

    def test_mean_only_artifact_reload_uses_all_frozen_selected_feature_bases(self) -> None:
        self.run_fixture_pipeline()
        artifact = json.loads(
            (self.out_dir / "contact_fusion_open_model_artifact.json").read_text()
        )
        schema = json.loads(self.contact_schema.read_text())
        stable = tuple(schema["training_feature_sets"]["stable_seed_mean_and_std"])
        payload = artifact["models"]["stable_contact_mean"]["feature_spec"]
        spec = MOD.FeatureSpec.from_json(payload, expected_stable_columns=stable)
        expected_means = tuple(schema["training_feature_sets"]["stable_seed_mean"])
        self.assertEqual(spec.contact_columns, expected_means)
        tampered = dict(payload)
        tampered["contact_columns"] = list(expected_means[:-1])
        tampered["feature_names"] = list(expected_means[:-1])
        with self.assertRaisesRegex(
            MOD.ContactFusionError, "serialized_contact_feature_set_mismatch"
        ):
            MOD.FeatureSpec.from_json(tampered, expected_stable_columns=stable)

    def test_diagnostic_and_docking_aliases_are_rejected_from_stable_allowlist(self) -> None:
        with self.assertRaisesRegex(MOD.ContactFusionError, "forbidden_stable_feature_alias"):
            MOD.validate_stable_allowlist(
                [
                    "contact_cdr3_hotspot_mass_length_confounded_diagnostic_seed_mean",
                    "contact_cdr3_hotspot_mass_length_confounded_diagnostic_seed_std",
                ]
            )
        with self.assertRaisesRegex(MOD.ContactFusionError, "forbidden_stable_feature_alias"):
            MOD.validate_stable_allowlist(["R_dual_min_seed_mean", "R_dual_min_seed_std"])

    def test_teacher_with_sealed_candidate_fails_before_contact_or_embedding_training(self) -> None:
        sealed = next(row for row in self.manifest_rows if row["model_split"] == MOD.SEALED_SPLIT)
        tampered = self.teacher_rows + [
            {**sealed, "generic_binding_prior": "not-read", MOD.PRIMARY_TARGET: "not-read"}
        ]
        write_tsv(self.teacher, tampered)
        audit = json.loads(self.teacher_audit.read_text())
        audit["output"]["sha256"] = MOD.sha256_file(self.teacher)
        self.teacher_audit.write_text(json.dumps(audit) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MOD.base.SurrogateError, "open_teacher_row_count_mismatch"):
            self.run_fixture_pipeline()

    def test_contact_release_tamper_is_rejected_by_v3_receipt(self) -> None:
        self.contact_features.write_text(
            self.contact_features.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(MOD.contact_v3.FeatureExtractionError, "output hash"):
            self.run_fixture_pipeline()

    def test_contact_schema_tamper_is_rejected_before_training(self) -> None:
        schema = json.loads(self.contact_schema.read_text())
        schema["selected_features"] = list(reversed(schema["selected_features"]))
        self.contact_schema.write_text(json.dumps(schema) + "\n", encoding="utf-8")
        receipt = json.loads(self.contact_schema.with_suffix(".receipt.json").read_text())
        receipt["schema_file_sha256"] = MOD.sha256_file(self.contact_schema)
        self.contact_schema.with_suffix(".receipt.json").write_text(
            json.dumps(receipt) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(MOD.ContactFusionError, "contact_schema_payload_hash_mismatch"):
            self.run_fixture_pipeline()

    def test_embedding_shard_index_identity_tamper_is_rejected(self) -> None:
        rows, _fields = MOD.read_csv(self.embedding_manifest)
        rows[0]["shard_index"], rows[1]["shard_index"] = rows[1]["shard_index"], rows[0][
            "shard_index"
        ]
        write_csv(self.embedding_manifest, rows)
        summary = json.loads(self.embedding_summary.read_text())
        summary["embedding_manifest_sha256"] = MOD.sha256_file(self.embedding_manifest)
        self.embedding_summary.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MOD.ContactFusionError, "embedding_manifest_shard_index_mismatch"):
            self.run_fixture_pipeline()

    def test_real_production_embedding_release_accepts_per_shard_config_hash(self) -> None:
        rows, _fields = MOD.read_csv(MOD.DEFAULT_EMBEDDING_MANIFEST)
        digest = rows[0]["sequence_sha256"].strip().lower()
        store = MOD.MeanEmbeddingStore(
            MOD.DEFAULT_EMBEDDING_MANIFEST,
            MOD.DEFAULT_EMBEDDING_SUMMARY,
            {digest},
            enforce_production_hash=True,
        )
        vector = store.get(digest)
        self.assertEqual(vector.shape, (store.dimension,))
        self.assertTrue(np.all(np.isfinite(vector)))
        shard_path = store.referenced_shards[0]
        payload = torch.load(shard_path, map_location="cpu", weights_only=True)
        self.assertNotEqual(payload["config_sha256"], store.config_sha256)
        self.assertEqual(
            payload["config_sha256"],
            store._shard_payload_config_sha256[shard_path],
        )
        bank = MOD.frozen_embedding.load_embedding_bank(
            MOD.DEFAULT_EMBEDDING_MANIFEST,
            MOD.DEFAULT_EMBEDDING_SUMMARY,
            store.sequence_manifest_path,
            enforce_production_hashes=True,
        )
        self.assertEqual(
            store.identity_sha256, bank.provenance["identity_sha256"]
        )


if __name__ == "__main__":
    unittest.main()
