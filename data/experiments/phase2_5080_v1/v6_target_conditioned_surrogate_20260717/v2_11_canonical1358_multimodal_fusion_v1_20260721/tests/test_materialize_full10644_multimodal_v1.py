#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/materialize_full10644_multimodal_v1.py"
SPEC = importlib.util.spec_from_file_location("full10644_multimodal", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parent_hash(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode("utf-8")).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.teacher = root / "teacher.tsv"
        self.split = root / "split.json"
        self.m2 = root / "canonical10644_m2_126d_features_v1.tsv"
        self.m2_receipt = root / "canonical10644_m2_126d_features_v1.receipt.json"
        self.coarse = root / "canonical10644_coarse_pose_features_36d_v1.tsv"
        self.coarse_receipt = root / "canonical10644_coarse_pose_features_36d_v1.receipt.json"
        self.cache = root / "cache650"
        self.cache_shard = self.cache / "shards/shard_00000.pt"
        self.cache_receipt = self.cache / "embedding_cache_receipt.json"
        self.output = root / "output"
        self.train_parents = ["P001", "P002"]
        self.development_parents = ["P003", "P004"]
        self.frozen_parents = ["P999"]
        self._write()

    def _write(self) -> None:
        teacher_rows: list[dict[str, str]] = []
        m2_rows: list[dict[str, str]] = []
        coarse_rows: list[dict[str, str]] = []
        m2_names = [f"M2_REGION__feature_{index:03d}" for index in range(126)]
        parents = self.train_parents + self.development_parents
        for index, parent in enumerate(parents):
            candidate = f"CAND_{index:03d}"
            sequence = "QVQLVESGGGLVQSGGSLRLSCAAS" + "ACDEFGHIKLMNPQRSTVWY"[index] + "WGQGTQVTVSS"
            sequence_sha256 = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
            r8 = 0.51 + index * 0.01
            r9 = 0.56 - index * 0.005
            teacher_rows.append({
                "candidate_id": candidate,
                "sequence_sha256": sequence_sha256,
                "sequence": sequence,
                "parent_framework_cluster": parent,
                "cdr1": "CAAS",
                "cdr2": "EFGH",
                "cdr3": "KLMNPQ",
                "sample_weight": "1",
                "R_8X6B": f"{r8:.9f}",
                "R_9E6Y": f"{r9:.9f}",
                "R_dual_min": f"{min(r8, r9):.9f}",
                "teacher_source": "V4D_OPEN_MULTI_SEED",
                "teacher_reliability": "MULTI_SEED",
            })
            monomer_sha256 = hashlib.sha256(f"monomer:{candidate}".encode()).hexdigest()
            m2_row = {
                "schema_version": MODULE.M2_SCHEMA,
                "candidate_id": candidate,
                "sequence_sha256": sequence_sha256,
                "parent_framework_cluster": parent,
                "model_split": "train" if parent in self.train_parents else "development",
                "asset_lane": "fixture",
                "monomer_sha256": monomer_sha256,
            }
            m2_row.update({name: f"{index + feature / 1000:.9f}" for feature, name in enumerate(m2_names)})
            m2_row["claim_boundary"] = "fixture"
            m2_rows.append(m2_row)
            coarse_row = {
                "candidate_id": candidate,
                "monomer_sha256": monomer_sha256,
                "feature_schema": MODULE.C2_FEATURE_SCHEMA,
            }
            coarse_row.update({
                name: f"{index + feature / 100:.9f}"
                for feature, name in enumerate(MODULE.C2_FEATURE_FIELDS)
            })
            coarse_rows.append(coarse_row)
        write_tsv(self.teacher, teacher_rows)
        self.write_split()
        write_tsv(self.m2, m2_rows)
        m2_receipt = {
            "schema_version": MODULE.M2_SCHEMA,
            "status": MODULE.M2_STATUS,
            "counts": {
                "rows": 4,
                "features": 126,
                "splits": {"development": 2, "train": 2},
            },
            "output": {"path": self.m2.name, "sha256": sha256_file(self.m2)},
            "invariants": {
                "legacy_m2_126d_schema": True,
                "monomer_sha256_recomputed": True,
                "all_numeric_values_finite": True,
                "geometry_label_values_read": 0,
                "candidate_docking_pose_files_opened": 0,
            },
            "feature_names": m2_names,
        }
        self.m2_receipt.write_text(json.dumps(m2_receipt), encoding="utf-8")
        write_tsv(self.coarse, coarse_rows)
        self.write_coarse_receipt()
        self.cache_shard.parent.mkdir(parents=True)
        torch.save({
            "metadata": {
                "candidate_ids": [row["candidate_id"] for row in teacher_rows] + ["CACHE_EXTRA"],
                "sequence_sha256": [row["sequence_sha256"] for row in teacher_rows] + ["f" * 64],
            },
            "embeddings": torch.tensor(np.arange(40).reshape(5, 8), dtype=torch.float32),
        }, self.cache_shard)
        self.write_cache_receipt()

    def write_split(self) -> None:
        payload = {
            "schema_version": "pvrig_v2_9_whole_parent_split_v1",
            "open_only": True,
            "training_tsv_sha256": sha256_file(self.teacher),
            "expected_total_rows": 4,
            "expected_train_rows": 2,
            "expected_score_rows": 2,
            "frozen_test_access_count": 0,
            "sealed_truth_access_count": 0,
            "train_parents": self.train_parents,
            "score_parents": self.development_parents,
            "frozen_test_parents": self.frozen_parents,
            "train_parent_set_sha256": parent_hash(self.train_parents),
            "score_parent_set_sha256": parent_hash(self.development_parents),
            "frozen_test_parent_set_sha256": parent_hash(self.frozen_parents),
        }
        self.split.write_text(json.dumps(payload), encoding="utf-8")

    def write_coarse_receipt(self) -> None:
        payload = {
            "schema_version": MODULE.C2_SCHEMA,
            "status": MODULE.C2_STATUS,
            "counts": {
                "candidates": 4,
                "features": 36,
                "splits": {"development": 2, "train": 2},
            },
            "output": {"path": str(self.coarse), "sha256": sha256_file(self.coarse)},
            "invariants": {
                "candidate_set_exact": True,
                "frozen_structure_manifest_order_preserved": True,
                "all_features_finite": True,
                "monomer_sha256_join_exact": True,
                "all_shard_and_target_hashes_verified": True,
                "candidate_docking_pose_files_opened": 0,
                "teacher_label_files_opened": 0,
            },
        }
        self.coarse_receipt.write_text(json.dumps(payload), encoding="utf-8")

    def write_cache_receipt(self) -> None:
        self.cache_receipt.write_text(json.dumps({
            "schema_version": MODULE.EMBEDDING_SCHEMA,
            "status": "PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE",
            "rows": 5,
            "embedding_dimension": 8,
            "shards": [{
                "path": str(self.cache_shard), "rows": 5,
                "sha256": sha256_file(self.cache_shard),
            }],
        }), encoding="utf-8")

    def args(self):
        return MODULE.parser().parse_args([
            "--teacher", str(self.teacher),
            "--split-manifest", str(self.split),
            "--m2-features", str(self.m2),
            "--m2-receipt", str(self.m2_receipt),
            "--coarse-pose", str(self.coarse),
            "--coarse-pose-receipt", str(self.coarse_receipt),
            "--esm2-650m-cache", str(self.cache),
            "--output-dir", str(self.output),
            "--expected-teacher-sha256", sha256_file(self.teacher),
            "--expected-split-sha256", sha256_file(self.split),
            "--expected-m2-features-sha256", sha256_file(self.m2),
            "--expected-m2-receipt-sha256", sha256_file(self.m2_receipt),
            "--expected-coarse-pose-sha256", sha256_file(self.coarse),
            "--expected-coarse-pose-receipt-sha256", sha256_file(self.coarse_receipt),
            "--expected-esm2-cache-receipt-sha256", sha256_file(self.cache_receipt),
            "--expected-rows", "4",
            "--expected-train-rows", "2",
            "--expected-development-rows", "2",
        ])


class Full10644MultimodalMaterializerTests(unittest.TestCase):
    def test_defaults_are_full10644_contract(self):
        defaults = MODULE.parser().parse_args([
            "--teacher", "a", "--split-manifest", "b", "--m2-features", "c",
            "--m2-receipt", "d", "--coarse-pose", "e", "--coarse-pose-receipt", "f",
            "--esm2-650m-cache", "g", "--output-dir", "h",
            "--expected-teacher-sha256", "0" * 64, "--expected-split-sha256", "0" * 64,
            "--expected-m2-features-sha256", "0" * 64, "--expected-m2-receipt-sha256", "0" * 64,
            "--expected-coarse-pose-sha256", "0" * 64,
            "--expected-coarse-pose-receipt-sha256", "0" * 64,
            "--expected-esm2-cache-receipt-sha256", "0" * 64,
        ])
        self.assertEqual((defaults.expected_rows, defaults.expected_train_rows,
                          defaults.expected_development_rows), (10644, 9849, 795))

    def test_materializes_exact_multimodal_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = MODULE.materialize(fixture.args())
            self.assertEqual((result["rows"], result["train_rows"], result["development_rows"]), (4, 2, 2))
            output = fixture.output / "canonical10644_multimodal_open_v1.tsv"
            rows = load_tsv(output)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(rows[0]), len(MODULE.TEACHER_FIELDS) + 3 + 126 + 36)
            self.assertTrue(all(
                abs(float(row["R_dual_min"]) - min(float(row["R_8X6B"]), float(row["R_9E6Y"]))) < 2e-8
                for row in rows
            ))
            receipt = json.loads(
                (fixture.output / "canonical10644_multimodal_materialization_v1.receipt.json").read_text()
            )
            self.assertEqual(receipt["counts"]["splits"], {"development": 2, "train": 2})
            self.assertEqual(receipt["features"]["m2_feature_count"], 126)
            self.assertEqual(receipt["features"]["coarse_feature_count"], 36)
            self.assertEqual(receipt["features"]["coarse_model_feature_count"], 32)
            self.assertEqual(receipt["invariants"]["frozen_test_access_count"], 0)
            self.assertEqual(receipt["invariants"]["sealed_truth_access_count"], 0)
            self.assertEqual(receipt["embedding_cache"]["matched_rows"], 4)

    def test_parent_hash_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            split = json.loads(fixture.split.read_text())
            split["train_parent_set_sha256"] = "0" * 64
            fixture.split.write_text(json.dumps(split), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.MaterializationError, "train_parent_hash"):
                MODULE.materialize(fixture.args())
            self.assertFalse(fixture.output.exists())

    def test_coarse_candidate_substitution_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            rows = load_tsv(fixture.coarse)
            rows[0]["candidate_id"] = "ALIEN"
            write_tsv(fixture.coarse, rows)
            fixture.write_coarse_receipt()
            with self.assertRaisesRegex(MODULE.MaterializationError, "coarse_candidate_set_not_exact"):
                MODULE.materialize(fixture.args())
            self.assertFalse(fixture.output.exists())

    def test_embedding_sequence_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            payload = torch.load(fixture.cache_shard, map_location="cpu", weights_only=False)
            payload["metadata"]["sequence_sha256"][0] = "0" * 64
            torch.save(payload, fixture.cache_shard)
            fixture.write_cache_receipt()
            with self.assertRaisesRegex(MODULE.MaterializationError, "embedding_sequence_mismatch:CAND_000"):
                MODULE.materialize(fixture.args())
            self.assertFalse(fixture.output.exists())

    def test_exact_min_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            rows = load_tsv(fixture.teacher)
            rows[0]["R_dual_min"] = "0.999"
            write_tsv(fixture.teacher, rows)
            fixture.write_split()
            with self.assertRaisesRegex(MODULE.MaterializationError, "exact_min:CAND_000"):
                MODULE.materialize(fixture.args())
            self.assertFalse(fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
