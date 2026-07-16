#!/usr/bin/env python3
from __future__ import annotations

import csv
import dataclasses
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


MODULE_PATH = Path(__file__).with_name(
    "train_phase2_v4_d_frozen_embedding_surrogate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "train_phase2_v4_d_frozen_embedding_surrogate", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)
BASE = MOD.base


def write_table(
    path: Path, rows: list[dict[str, object]], delimiter: str = ","
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def encode_index(index: int, width: int = 5) -> str:
    values = []
    for _ in range(width):
        values.append(BASE.AA_ORDER[index % len(BASE.AA_ORDER)])
        index //= len(BASE.AA_ORDER)
    return "".join(values)


class FrozenEmbeddingFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.split_path = root / "split.tsv"
        self.teacher_path = root / "teacher.tsv"
        self.teacher_audit_path = root / "teacher.tsv.audit.json"
        self.release_receipt_path = root / "open_teacher_release_receipt.json"
        self.sequence_manifest_path = root / "sequence_manifest.csv"
        self.embedding_manifest_path = root / "embedding_manifest.csv"
        self.embedding_summary_path = root / "embedding_summary.json"
        self.out_dir = root / "out"
        self.split_rows: list[dict[str, object]] = []
        self.teacher_rows: list[dict[str, object]] = []
        self.embedding_by_hash: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._build_rows()
        self._write_embedding_cache()
        self._write_teacher_audit()
        self._write_release_receipt()

    def _build_rows(self) -> None:
        layout = (
            (BASE.TRAIN_SPLIT, 20, 226, "T"),
            (BASE.DEVELOPMENT_SPLIT, 3, 32, "D"),
            (BASE.SEALED_SPLIT, 3, 32, "S"),
        )
        global_index = 0
        for split, cluster_count, row_count, prefix in layout:
            counts = [row_count // cluster_count] * cluster_count
            for index in range(row_count % cluster_count):
                counts[index] += 1
            for cluster_index, count in enumerate(counts):
                cluster = f"{prefix}{cluster_index:02d}"
                for replicate in range(count):
                    token = encode_index(global_index)
                    cdr1 = "GFTF" + token[:3] + "Y"
                    cdr2 = "IS" + token[1:4] + "GGT"
                    cdr3 = "CAR" + token + "W"
                    sequence = (
                        "QVQLVESGGGLVQPGGSLRLSCAAS"
                        + cdr1
                        + "MGWYRQAPGKERELVA"
                        + cdr2
                        + "AYKDSVKGRFTISRDFSRSTMYLQMNSLKPEDTAIYYC"
                        + cdr3
                        + "GQGTQVTVSS"
                    )
                    sequence_hash = BASE.sequence_sha256(sequence)
                    signal = global_index / 289.0
                    esm2 = np.asarray(
                        [signal, signal**2, math_sin(signal), 1.0 - signal],
                        dtype=np.float32,
                    )
                    vhhbert = np.asarray(
                        [signal, 2.0 * signal, signal**2, 1.0 - signal, math_cos(signal), 0.5],
                        dtype=np.float32,
                    )
                    physchem = np.asarray(
                        [len(cdr3) / 20.0, signal, 1.0 - signal], dtype=np.float32
                    )
                    self.embedding_by_hash[sequence_hash] = (esm2, vhhbert, physchem)
                    target = 0.15 + 0.65 * signal + 0.05 * signal**2
                    row = {
                        "candidate_id": f"{split}_{cluster}_{replicate:03d}",
                        "sequence_sha256": sequence_hash,
                        "sequence": sequence,
                        "parent_id": f"PARENT_{cluster}",
                        "parent_framework_cluster": cluster,
                        "original_formal_split": "train",
                        "model_split": split,
                        "design_method": "RFantibody_RFdiffusion_ProteinMPNN",
                        "design_mode": "H3" if global_index % 2 else "H1H3",
                        "target_patch_id": ("A_CENTER", "B_LOWER", "C_BRIDGE")[
                            global_index % 3
                        ],
                        "cdr1": cdr1,
                        "cdr2": cdr2,
                        "cdr3": cdr3,
                        "cdr3_length": len(cdr3),
                        "new_dual_docking_label_policy": "SYNTHETIC_TEST_ONLY",
                        "claim_boundary": "synthetic_test_only",
                    }
                    self.split_rows.append(row)
                    if split != BASE.SEALED_SPLIT:
                        self.teacher_rows.append(
                            {
                                **row,
                                "generic_binding_prior": f"{signal:.9f}",
                                BASE.PRIMARY_TARGET: f"{target:.9f}",
                            }
                        )
                    global_index += 1
        write_table(self.split_path, self.split_rows, "\t")
        write_table(self.teacher_path, self.teacher_rows, "\t")

    def _write_embedding_cache(self) -> None:
        antigen = "ACDEFGHIKLMNPQRSTVWY"
        antigen_hash = BASE.sequence_sha256(antigen)
        self.embedding_by_hash[antigen_hash] = (
            np.zeros(4, dtype=np.float32),
            np.zeros(6, dtype=np.float32),
            np.zeros(3, dtype=np.float32),
        )
        sequence_by_hash = {
            str(row["sequence_sha256"]): (str(row["sequence"]), "vhh")
            for row in self.split_rows
        }
        sequence_by_hash[antigen_hash] = (antigen, "antigen")
        sequence_rows = [
            {
                "sequence_sha256": sequence_hash,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "roles": role,
            }
            for sequence_hash, (sequence, role) in sorted(sequence_by_hash.items())
        ]
        write_table(self.sequence_manifest_path, sequence_rows)

        config = {
            "backend": "hash",
            "vhhbert_model_path": "synthetic",
            "esm2_model_path": "synthetic",
            "vhhbert_model_sha256": "synthetic",
            "esm2_model_sha256": "synthetic",
            "vhhbert_dim": 6,
            "esm2_dim": 4,
            "physchem_dim": 3,
            "max_esm_residues": 1000,
            "chunk_overlap": 0,
            "pooling": "residue_mean_excluding_special_tokens",
        }
        config_sha = MOD.sha256_json(config)
        shard_dir = self.root / "shards"
        shard_dir.mkdir()
        manifest_rows: list[dict[str, object]] = []
        shard_hashes: dict[str, str] = {}
        for shard_number, start in enumerate(range(0, len(sequence_rows), 160)):
            rows = sequence_rows[start : start + 160]
            hashes = [str(row["sequence_sha256"]) for row in rows]
            shard_path = shard_dir / f"shard_{shard_number:05d}.pt"
            roles = [str(row["roles"]) for row in rows]
            payload = {
                "schema_version": "phase2_v3_embedding_shard_v1",
                "config_sha256": MOD.sha256_json(
                    {"config": config, "sequence_sha256": hashes}
                ),
                "sequence_sha256": hashes,
                "esm2": torch.tensor(
                    np.stack([self.embedding_by_hash[value][0] for value in hashes])
                ),
                "vhhbert": torch.tensor(
                    np.stack([self.embedding_by_hash[value][1] for value in hashes])
                ),
                "physchem": torch.tensor(
                    np.stack([self.embedding_by_hash[value][2] for value in hashes])
                ),
                "vhhbert_available": torch.tensor(
                    [role == "vhh" for role in roles], dtype=torch.bool
                ),
            }
            torch.save(payload, shard_path)
            shard_hashes[shard_path.name] = BASE.sha256_file(shard_path)
            for offset, row in enumerate(rows):
                manifest_rows.append(
                    {
                        "sequence_sha256": row["sequence_sha256"],
                        "sequence_length": row["sequence_length"],
                        "roles": row["roles"],
                        "shard_path": str(shard_path.resolve()),
                        "shard_index": offset,
                        "esm2_dim": 4,
                        "vhhbert_dim": 6,
                        "physchem_dim": 3,
                        "config_sha256": config_sha,
                    }
                )
        write_table(self.embedding_manifest_path, manifest_rows)
        summary = {
            "schema_version": "phase2_v3_embedding_summary_v1",
            "sequence_manifest": str(self.sequence_manifest_path.resolve()),
            "sequence_manifest_sha256": BASE.sha256_file(self.sequence_manifest_path),
            "embedding_manifest": str(self.embedding_manifest_path.resolve()),
            "embedding_manifest_sha256": BASE.sha256_file(self.embedding_manifest_path),
            "config": config,
            "config_sha256": config_sha,
            "sequence_count": len(sequence_rows),
            "vhh_sequence_count": 290,
            "antigen_sequence_count": 1,
            "shard_count": len(shard_hashes),
            "shard_sha256": shard_hashes,
        }
        self.embedding_summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _write_teacher_audit(self) -> None:
        audit = {
            "schema_version": "phase2_v4_d_open_continuous_teacher_v1",
            "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
            "release": "open_train_and_open_development_only",
            "row_count": 258,
            "inputs": {"split_manifest_sha256": BASE.sha256_file(self.split_path)},
            "sealed_data_boundary": {
                "raw_job_results_opened": 0,
                "sealed_metrics_used_for_teacher_or_ranking": False,
            },
            "output": {"sha256": BASE.sha256_file(self.teacher_path)},
        }
        audit["inputs"]["raw_aggregate_closure"] = {
            "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
            "job_count": 1548,
            "pose_row_count": 12384,
            "closure_sha256": "a" * 64,
        }
        self.teacher_audit_path.write_text(json.dumps(audit), encoding="utf-8")

    def _write_release_receipt(self) -> None:
        audit = json.loads(self.teacher_audit_path.read_text())
        receipt = {
            "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
            "row_count": 258,
            "teacher_sha256": BASE.sha256_file(self.teacher_path),
            "teacher_audit_sha256": BASE.sha256_file(self.teacher_audit_path),
            "sealed_test_raw_job_results_opened": 0,
            "sealed_metrics_used_for_teacher_or_ranking": False,
            "raw_aggregate_closure_sha256": audit["inputs"]["raw_aggregate_closure"][
                "closure_sha256"
            ],
        }
        self.release_receipt_path.write_text(json.dumps(receipt), encoding="utf-8")


def math_sin(value: float) -> float:
    return float(np.sin(value * np.pi))


def math_cos(value: float) -> float:
    return float(np.cos(value * np.pi))


class TrainFrozenEmbeddingSurrogateTest(unittest.TestCase):
    def test_file_snapshot_binds_the_bytes_used_after_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.csv"
            path.write_text("candidate_id\na\n", encoding="utf-8")
            snapshot = MOD.snapshot_file(path)
            path.write_text("candidate_id\nb\n", encoding="utf-8")
            self.assertEqual(MOD.read_csv_snapshot(snapshot)[0]["candidate_id"], "a")
            self.assertNotEqual(snapshot.sha256, BASE.sha256_file(path))

    def test_dual_ridge_matches_primal_ridge_for_p_greater_than_n(self) -> None:
        rng = np.random.default_rng(20260716)
        x = rng.normal(size=(8, 13))
        y = rng.normal(size=8)
        alpha = 0.7
        dual = MOD.fit_dual_ridge(x, y, alpha)
        primal = BASE.fit_ridge(x, y, alpha)
        np.testing.assert_allclose(
            BASE.predict_ridge(x, dual), BASE.predict_ridge(x, primal), atol=1e-10
        )
        self.assertEqual(len(dual.coefficient), 13)

    def test_cdr_length_shortcut_contains_no_sequence_identity(self) -> None:
        rows = [
            {
                "sequence": "A" * 100,
                "cdr1": "A" * 8,
                "cdr2": "C" * 7,
                "cdr3": "D" * 13,
            },
            {
                "sequence": "W" * 100,
                "cdr1": "W" * 8,
                "cdr2": "Y" * 7,
                "cdr3": "F" * 13,
            },
        ]
        matrix = MOD.cdr_length_matrix(rows)
        np.testing.assert_array_equal(matrix[0], matrix[1])
        self.assertEqual(matrix.shape[1], 5)

    def test_embedding_loader_closes_sequence_config_and_shard_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            bank = MOD.load_embedding_bank(
                fixture.embedding_manifest_path,
                fixture.embedding_summary_path,
                fixture.sequence_manifest_path,
                enforce_production_hashes=False,
            )
            self.assertEqual(len(bank.sequence_sha256), 291)
            self.assertEqual(bank.esm2.shape, (291, 4))
            self.assertEqual(bank.vhhbert.shape, (291, 6))
            self.assertEqual(bank.physchem.shape, (291, 3))
            self.assertEqual(len(bank.provenance["shards"]), 2)

            manifest_rows = MOD.read_csv(fixture.embedding_manifest_path)
            for row in manifest_rows:
                row["shard_path"] = str(Path("/relocated/source") / Path(row["shard_path"]).name)
            write_table(fixture.embedding_manifest_path, manifest_rows)
            summary = json.loads(fixture.embedding_summary_path.read_text())
            summary["embedding_manifest_sha256"] = BASE.sha256_file(
                fixture.embedding_manifest_path
            )
            fixture.embedding_summary_path.write_text(json.dumps(summary), encoding="utf-8")
            relocated_bank = MOD.load_embedding_bank(
                fixture.embedding_manifest_path,
                fixture.embedding_summary_path,
                fixture.sequence_manifest_path,
                enforce_production_hashes=False,
            )
            self.assertEqual(relocated_bank.vhhbert.shape, (291, 6))

            first_shard = next(iter(Path(temporary, "shards").glob("*.pt")))
            with first_shard.open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "embedding_shard_sha256_mismatch"
            ):
                MOD.load_embedding_bank(
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    enforce_production_hashes=False,
                )

    def test_embedding_loader_rejects_sequence_and_config_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            rows = MOD.read_csv(fixture.sequence_manifest_path)
            rows[0]["sequence"] = "A" * len(rows[0]["sequence"])
            write_table(fixture.sequence_manifest_path, rows)
            summary = json.loads(fixture.embedding_summary_path.read_text())
            summary["sequence_manifest_sha256"] = BASE.sha256_file(
                fixture.sequence_manifest_path
            )
            fixture.embedding_summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "embedding_sequence_sha256_mismatch"
            ):
                MOD.load_embedding_bank(
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    enforce_production_hashes=False,
                )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            summary = json.loads(fixture.embedding_summary_path.read_text())
            summary["config"]["esm2_dim"] = 5
            fixture.embedding_summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "embedding_summary_config_hash_mismatch"
            ):
                MOD.load_embedding_bank(
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    enforce_production_hashes=False,
                )

    def test_pipeline_freezes_replayable_unlabeled_test_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            result = MOD.run_pipeline(
                fixture.teacher_path,
                fixture.teacher_audit_path,
                fixture.split_path,
                fixture.embedding_manifest_path,
                fixture.embedding_summary_path,
                fixture.sequence_manifest_path,
                fixture.out_dir,
                release_receipt_path=fixture.release_receipt_path,
                alphas=(0.1, 1.0),
                ensemble_seeds=(11, 12, 13),
                enforce_production_hashes=False,
            )
            self.assertFalse(result["prospective_test_labels_read"])
            summary = json.loads(Path(result["summary"]).read_text())
            self.assertEqual(
                summary["serialized_artifact_roundtrip"]["status"],
                "PASS_FROZEN_EMBEDDING_ARTIFACT_ROUNDTRIP",
            )
            self.assertEqual(set(summary["embedding_models"]), set(MOD.EMBEDDING_MODELS))
            self.assertEqual(
                set(summary["shortcut_baselines"]),
                set(BASE.REQUIRED_BASELINES + MOD.LOCAL_SHORTCUT_MODELS),
            )
            length_baseline = summary["shortcut_baselines"]["cdr_length_only"]
            self.assertFalse(length_baseline["sequence_identity_features_used"])
            self.assertEqual(
                length_baseline["feature_names"],
                [
                    "sequence_length",
                    "cdr1_length",
                    "cdr2_length",
                    "cdr3_length",
                    "total_cdr_length",
                ],
            )
            self.assertIn("absolute_spearman", summary["open_performance_gates"]["gates"])
            self.assertIn(
                "parent_macro_spearman", summary["open_performance_gates"]["gates"]
            )
            for model in summary["embedding_models"].values():
                self.assertFalse(model["fixed_seed_metric_range"]["is_confidence_interval"])

            test_rows = BASE.read_tsv(Path(result["prospective_test_predictions"]))
            self.assertEqual(len(test_rows), 32)
            self.assertTrue(
                all(row["model_split"] == BASE.SEALED_SPLIT for row in test_rows)
            )
            forbidden = {
                field
                for field in test_rows[0]
                if "target" in field.lower() or "label" in field.lower()
            }
            self.assertFalse(forbidden)
            receipt = json.loads(Path(result["receipt"]).read_text())
            self.assertEqual(
                receipt["status"], "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE"
            )
            for path, digest in receipt["outputs"].items():
                self.assertEqual(BASE.sha256_file(Path(path)), digest)
            self.assertEqual(len(receipt["inputs"]), 11)

            artifact_path = fixture.out_dir / MOD.OUTPUT_FILENAMES[1]
            config_path = fixture.out_dir / MOD.OUTPUT_FILENAMES[0]
            artifact = MOD.load_model_artifact(
                artifact_path, expected_config_sha256=BASE.sha256_file(config_path)
            )
            bank = MOD.load_embedding_bank(
                fixture.embedding_manifest_path,
                fixture.embedding_summary_path,
                fixture.sequence_manifest_path,
                enforce_production_hashes=False,
            )
            hashes = [row["sequence_sha256"] for row in test_rows]
            prediction, uncertainty = MOD.predict_artifact_model(
                artifact, summary["selected_model"], bank, hashes
            )
            np.testing.assert_array_equal(
                np.round(prediction, 9),
                np.asarray([float(row["selected_prediction"]) for row in test_rows]),
            )
            np.testing.assert_array_equal(
                np.round(uncertainty, 9),
                np.asarray([float(row["selected_uncertainty"]) for row in test_rows]),
            )
            wrong_bank_binding = json.loads(json.dumps(artifact))
            wrong_bank_binding["embedding_config_sha256"] = "0" * 64
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "artifact_embedding_config_hash_mismatch"
            ):
                MOD.predict_artifact_model(
                    wrong_bank_binding, summary["selected_model"], bank, hashes
                )
            different_identity_bank = dataclasses.replace(
                bank,
                provenance={**bank.provenance, "identity_sha256": "0" * 64},
            )
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "artifact_embedding_bank_identity_mismatch"
            ):
                MOD.predict_artifact_model(
                    artifact,
                    summary["selected_model"],
                    different_identity_bank,
                    hashes,
                )
            invalid_boundary = json.loads(artifact_path.read_text())
            invalid_boundary["prospective_test_labels_read"] = True
            invalid_artifact_path = Path(temporary) / "invalid_artifact.json"
            invalid_artifact_path.write_text(json.dumps(invalid_boundary), encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError,
                "frozen_embedding_artifact_test_label_boundary_invalid",
            ):
                MOD.load_model_artifact(invalid_artifact_path)

            Path(result["receipt"]).write_text('{"status":"STALE"}\n')
            MOD.run_pipeline(
                fixture.teacher_path,
                fixture.teacher_audit_path,
                fixture.split_path,
                fixture.embedding_manifest_path,
                fixture.embedding_summary_path,
                fixture.sequence_manifest_path,
                fixture.out_dir,
                release_receipt_path=fixture.release_receipt_path,
                alphas=(0.1, 1.0),
                ensemble_seeds=(11, 12, 13),
                enforce_production_hashes=False,
            )
            replacement = json.loads(
                (fixture.out_dir / MOD.OUTPUT_FILENAMES[-1]).read_text()
            )
            self.assertTrue(
                replacement["publication"][
                    "stale_receipt_removed_before_replacement"
                ]
            )

    def test_release_receipt_is_required_and_raw_closure_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError, "open_teacher_release_receipt_required"
            ):
                MOD.run_pipeline(
                    fixture.teacher_path,
                    fixture.teacher_audit_path,
                    fixture.split_path,
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    fixture.out_dir,
                    alphas=(0.1,),
                    ensemble_seeds=(11, 12, 13),
                    enforce_production_hashes=False,
                )

            receipt = json.loads(fixture.release_receipt_path.read_text())
            receipt["raw_aggregate_closure_sha256"] = "b" * 64
            fixture.release_receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(
                MOD.FrozenEmbeddingError,
                "open_teacher_release_receipt_raw_closure_mismatch",
            ):
                MOD.run_pipeline(
                    fixture.teacher_path,
                    fixture.teacher_audit_path,
                    fixture.split_path,
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    fixture.out_dir,
                    release_receipt_path=fixture.release_receipt_path,
                    alphas=(0.1,),
                    ensemble_seeds=(11, 12, 13),
                    enforce_production_hashes=False,
                )

    def test_teacher_cannot_contain_prospective_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FrozenEmbeddingFixture(Path(temporary))
            teachers = BASE.read_tsv(fixture.teacher_path)
            sealed = next(
                row
                for row in fixture.split_rows
                if row["model_split"] == BASE.SEALED_SPLIT
            )
            teachers[0] = {
                **sealed,
                "generic_binding_prior": "0.1",
                BASE.PRIMARY_TARGET: "999.0",
            }
            write_table(fixture.teacher_path, teachers, "\t")
            fixture._write_teacher_audit()
            with self.assertRaisesRegex(
                BASE.SurrogateError, "teacher_contains_non_open_candidate"
            ):
                MOD.run_pipeline(
                    fixture.teacher_path,
                    fixture.teacher_audit_path,
                    fixture.split_path,
                    fixture.embedding_manifest_path,
                    fixture.embedding_summary_path,
                    fixture.sequence_manifest_path,
                    fixture.out_dir,
                    test_only_allow_missing_release_receipt=True,
                    alphas=(0.1,),
                    ensemble_seeds=(11, 12, 13),
                    enforce_production_hashes=False,
                )


if __name__ == "__main__":
    unittest.main()
