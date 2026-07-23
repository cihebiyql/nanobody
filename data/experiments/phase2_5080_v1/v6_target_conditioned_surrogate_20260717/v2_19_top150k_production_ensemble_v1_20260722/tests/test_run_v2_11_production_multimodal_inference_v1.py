from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.preprocessing import StandardScaler


SCRIPT = Path(__file__).resolve().parents[1] / "src" / "run_v2_11_production_multimodal_inference_v1.py"
SPEC = importlib.util.spec_from_file_location("production_multimodal", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


SEQUENCES = (
    ("A", "QVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISWNSGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCAKGGWFDYWGQGTLVTVSS", "GFTFSSYA", "ISWNSGST", "AKGGWFDY"),
    ("B", "QVQLVESGGGLVQPGGSLRLSCAASGFTFSNYAMSWVRQAPGKGLEWVSAISWNTGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCAKAGWFDYWGQGTLVTVSS", "GFTFSNYA", "ISWNTGST", "AKAGWFDY"),
    ("C", "QVQLVESGGGLVQPGGSLRLSCAASGFTFSTYAMSWVRQAPGKGLEWVSAISWNVGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCAKSGWFDYWGQGTLVTVSS", "GFTFSTYA", "ISWNVGST", "AKSGWFDY"),
    ("D", "QVQLVESGGGLVQPGGSLRLSCAASGFTFSVYAMSWVRQAPGKGLEWVSAISWNAGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCAKTGWFDYWGQGTLVTVSS", "GFTFSVYA", "ISWNAGST", "AKTGWFDY"),
)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProductionMultimodalInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rng = np.random.default_rng(17)
        self.manifest = self.root / "compact.tsv"
        manifest_rows = []
        for index, (candidate, sequence, cdr1, cdr2, cdr3) in enumerate(SEQUENCES):
            manifest_rows.append({
                "candidate_id": candidate,
                "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "parent_cluster": f"P{index % 2}",
                "cdr1_after": cdr1,
                "cdr2_after": cdr2,
                "cdr3_after": cdr3,
            })
        write_tsv(self.manifest, list(manifest_rows[0]), manifest_rows)

        self.m2_names = [f"M2_{index:03d}" for index in range(126)]
        self.c2_names = [f"C2__feature_{index:02d}" for index in range(32)]
        self.m2 = self.root / "m2.tsv"
        self.c2 = self.root / "c2.tsv"
        m2_values = self.rng.normal(size=(len(SEQUENCES), len(self.m2_names)))
        c2_values = self.rng.normal(size=(len(SEQUENCES), len(self.c2_names)))
        m2_rows, c2_rows = [], []
        for index, (candidate, sequence, *_rest) in enumerate(SEQUENCES):
            sequence_sha256 = hashlib.sha256(sequence.encode()).hexdigest()
            m2_rows.append({
                "candidate_id": candidate,
                "sequence_sha256": sequence_sha256,
                **{name: value for name, value in zip(self.m2_names, m2_values[index])},
            })
            c2_rows.append({
                "candidate_id": candidate,
                "sequence_sha256": sequence_sha256,
                **{name: value for name, value in zip(self.c2_names, c2_values[index])},
            })
        write_tsv(self.m2, list(m2_rows[0]), m2_rows)
        write_tsv(self.c2, list(c2_rows[0]), c2_rows)

        embeddings = self.rng.normal(size=(len(SEQUENCES), 12)).astype(np.float32)
        self.cache = self.root / "cache"
        (self.cache / "shards").mkdir(parents=True)
        shard = self.cache / "shards" / "shard_000.pt"
        torch.save({
            "embeddings": torch.from_numpy(embeddings),
            "metadata": {
                "candidate_ids": [item[0] for item in SEQUENCES],
                "sequence_sha256": [hashlib.sha256(item[1].encode()).hexdigest() for item in SEQUENCES],
            },
        }, shard)
        receipt = {
            "schema_version": MODULE.EMBEDDING_SCHEMA,
            "rows": len(SEQUENCES),
            "shards": [{"path": "shards/shard_000.pt", "sha256": digest(shard), "rows": len(SEQUENCES)}],
        }
        (self.cache / "embedding_cache_receipt.json").write_text(json.dumps(receipt))

        # Train compact but structurally faithful sklearn objects.
        train_n = 16
        x_emb = self.rng.normal(size=(train_n, embeddings.shape[1]))
        x_phys = self.rng.normal(size=(train_n, 124))
        y = self.rng.normal(loc=0.5, scale=0.1, size=(train_n, 2))
        pca = PCA(n_components=4, random_state=1).fit(x_emb)
        joined = np.concatenate((pca.transform(x_emb), x_phys), axis=1)
        s0_scaler = StandardScaler().fit(joined)
        s0_models = [ElasticNet(alpha=0.01, random_state=1).fit(s0_scaler.transform(joined), y[:, target]) for target in range(2)]
        xm2_train = self.rng.normal(size=(train_n, len(self.m2_names)))
        m2_scaler = StandardScaler().fit(xm2_train)
        m2_model = Ridge(alpha=10).fit(m2_scaler.transform(xm2_train), y)
        xc2_train = self.rng.normal(size=(train_n, len(self.c2_names)))
        c2_mean = xc2_train.mean(axis=0)
        c2_scale = xc2_train.std(axis=0)
        retained = np.arange(len(self.c2_names))
        axes = np.eye(len(self.c2_names))[:8]
        c2_reduced = ((xc2_train - c2_mean) / c2_scale) @ axes.T
        c2_scaler = StandardScaler().fit(c2_reduced)
        c2_model = Ridge(alpha=1).fit(c2_scaler.transform(c2_reduced), y)
        meta = self.rng.normal(size=(train_n, 12))
        gbdt = [HistGradientBoostingRegressor(max_iter=4, min_samples_leaf=2, random_state=1).fit(meta, y[:, target]) for target in range(2)]
        self.artifact = self.root / "MODEL_ARTIFACT.pkl"
        artifact = {
            "schema_version": MODULE.MODEL_SCHEMA,
            "claim_boundary": MODULE.MODEL_CLAIM_BOUNDARY,
            "S0": {"pca": pca, "scaler": s0_scaler, "models": s0_models, "seed": 1},
            "M2": {"scaler": m2_scaler, "model": m2_model, "alpha": 10.0},
            "C2": {
                "pca": {"mean": c2_mean, "scale": c2_scale, "retained": retained, "axes": axes},
                "ridge": {"scaler": c2_scaler, "model": c2_model, "alpha": 1.0},
                "alpha": 1.0,
            },
            "fusion_m2c2": {"fallback": "M2", "branches": ("C2",), "weights": np.asarray([0.25])},
            "fusion_all": {"fallback": "M2", "branches": ("S0", "C2"), "weights": np.asarray([0.2, 0.3])},
            "gbdt": gbdt,
            "structure_feature_names": self.m2_names,
            "c2_feature_names": self.c2_names,
        }
        with self.artifact.open("wb") as handle:
            pickle.dump(artifact, handle)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def arguments(self, name: str, with_c2: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            compact_manifest=self.manifest,
            expected_compact_manifest_sha256=digest(self.manifest),
            esm2_pooled_cache=self.cache,
            m2_features=self.m2,
            expected_m2_features_sha256=digest(self.m2),
            c2_features=self.c2 if with_c2 else None,
            expected_c2_features_sha256=digest(self.c2) if with_c2 else None,
            model_artifact=self.artifact,
            expected_model_artifact_sha256=digest(self.artifact),
            expected_rows=len(SEQUENCES),
            output_dir=self.root / name,
        )

    def test_base_s0_m2_inference_and_receipt(self) -> None:
        args = self.arguments("base")
        result = MODULE.run(args)
        self.assertEqual(result["status"], MODULE.STATUS)
        self.assertEqual(result["lanes"], list(MODULE.BASE_LANES))
        receipt = json.loads((args.output_dir / "RUN_RECEIPT.json").read_text())
        self.assertEqual(receipt["counts"]["rows"], len(SEQUENCES))
        self.assertEqual(receipt["invariants"]["teacher_label_values_read"], 0)
        self.assertEqual(receipt["invariants"]["exact_min_violation_count"], 0)
        with (args.output_dir / "PRODUCTION_PREDICTIONS_RANK_READY.tsv").open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), len(SEQUENCES))
        for row in rows:
            for lane in MODULE.BASE_LANES:
                self.assertAlmostEqual(
                    float(row[f"{lane}__Rdual_exact_min"]),
                    min(float(row[f"{lane}__R8"]), float(row[f"{lane}__R9"])),
                    places=9,
                )
                self.assertIn(int(row[f"{lane}__Rdual_rank"]), range(1, len(SEQUENCES) + 1))

    def test_optional_c2_emits_all_frozen_fusion_lanes(self) -> None:
        args = self.arguments("with_c2", with_c2=True)
        result = MODULE.run(args)
        self.assertEqual(result["lanes"], list(MODULE.BASE_LANES + MODULE.C2_LANES))
        receipt = json.loads((args.output_dir / "RUN_RECEIPT.json").read_text())
        self.assertEqual(receipt["inputs"]["c2_features"]["status"], "PASS_OPTIONAL_C2_CLOSURE")
        self.assertEqual(receipt["counts"]["prediction_lanes"], 6)

    def test_truth_field_is_rejected_before_inference(self) -> None:
        with self.manifest.open() as handle:
            fields = next(csv.reader(handle, delimiter="\t"))
        with self.manifest.open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        poisoned = self.root / "truth.tsv"
        for row in rows:
            row["truth_R_dual"] = "0.9"
        write_tsv(poisoned, fields + ["truth_R_dual"], rows)
        args = self.arguments("reject_truth")
        args.compact_manifest = poisoned
        args.expected_compact_manifest_sha256 = digest(poisoned)
        with self.assertRaisesRegex(MODULE.ProductionInferenceError, "forbidden_compact_manifest_field"):
            MODULE.run(args)
        self.assertFalse(args.output_dir.exists())

    def test_feature_candidate_closure_is_fail_closed(self) -> None:
        with self.m2.open() as handle:
            fields = next(csv.reader(handle, delimiter="\t"))
        with self.m2.open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))[:-1]
        short = self.root / "m2_short.tsv"
        write_tsv(short, fields, rows)
        args = self.arguments("reject_short")
        args.m2_features = short
        args.expected_m2_features_sha256 = digest(short)
        with self.assertRaisesRegex(MODULE.ProductionInferenceError, "m2_features_candidate_closure"):
            MODULE.run(args)
        self.assertFalse(args.output_dir.exists())

    def test_artifact_hash_is_verified(self) -> None:
        args = self.arguments("reject_artifact")
        args.expected_model_artifact_sha256 = "0" * 64
        with self.assertRaisesRegex(MODULE.ProductionInferenceError, "model_artifact_sha256_mismatch"):
            MODULE.run(args)
        self.assertFalse(args.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
