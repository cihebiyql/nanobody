import argparse
import csv
import dataclasses
import hashlib
import importlib.util
import joblib
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import torch


MODULE = pathlib.Path(__file__).parents[1] / "src" / "train_m4_sklearn_fusion.py"
SPEC = importlib.util.spec_from_file_location("m4_sklearn_train", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def write_tsv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_package(root: pathlib.Path, parents=20, rows_per_parent=3, embedding_dimension=8):
    generator = np.random.default_rng(19)
    feature_names = [f"F{i:03d}" for i in range(126)]
    rows = []
    embeddings = []
    ids = []
    hashes = []
    for parent_index in range(parents):
        parent = f"P{parent_index:03d}"
        fold = parent_index % 5
        parent_effect = generator.normal(0, 0.01)
        for row_index in range(rows_per_parent):
            candidate = f"C{parent_index:03d}_{row_index:02d}"
            unique_index = parent_index * rows_per_parent + row_index
            suffix = "".join("A" if (unique_index >> bit) & 1 else "C" for bit in range(8))
            sequence = "ACDEFGHIKLMNPQRSTVWY" + suffix
            sequence_hash = hashlib.sha256(sequence.encode()).hexdigest()
            embedding = generator.normal(size=embedding_dimension)
            structure = generator.normal(size=126)
            target = np.clip(0.52 + parent_effect + 0.055 * embedding[0] - 0.025 * embedding[1] + 0.005 * structure[0], 0, 1)
            row = {
                "schema_version": "synthetic",
                "candidate_id": candidate,
                "sequence_sha256": sequence_hash,
                "sequence": sequence,
                "parent_framework_cluster": parent,
                "target_patch_id": "A",
                "design_mode": "H3",
                "cdr1": "ACD",
                "cdr2": "EFG",
                "cdr3": "HIK",
                "teacher_source": "SOURCE_A" if parent_index % 2 else "SOURCE_B",
                "teacher_reliability": "SYNTHETIC",
                "sample_weight": "1.0",
                "outer_fold": str(fold),
                "R_8X6B": str(target + 0.01),
                "R_9E6Y": str(target),
                "R_dual_min": str(target),
                "teacher_uncertainty": "0.01",
                "monomer_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                "technical_reasons": "",
                "claim_boundary": mod.CLAIM,
            }
            row.update({name: format(value, ".12g") for name, value in zip(feature_names, structure)})
            rows.append(row)
            embeddings.append(embedding.astype(np.float16))
            ids.append(candidate)
            hashes.append(sequence_hash)
    table = root / "v6_supervised1507.tsv"
    write_tsv(table, rows)
    table_hash = mod.sha256_file(table)
    table_receipt = root / "v6_training_table_receipt.json"
    table_receipt.write_text(json.dumps({
        "status": "PASS_V6_TRAINING_TABLE_MATERIALIZED",
        "output_sha256": {"supervised": table_hash},
    }))
    embedding_root = root / "embeddings"
    shard_dir = embedding_root / "shards"
    shard_dir.mkdir(parents=True)
    shard = shard_dir / "shard_00000.pt"
    torch.save({
        "metadata": {"candidate_ids": ids, "sequence_sha256": hashes},
        "embeddings": torch.as_tensor(np.asarray(embeddings)),
    }, shard)
    receipt = {
        "schema_version": "pvrig_v6_esm_embedding_cache_v1",
        "status": "PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE",
        "input_sha256": table_hash,
        "rows": len(rows),
        "embedding_dimension": embedding_dimension,
        "shards": [{"path": str(shard), "rows": len(rows), "sha256": mod.sha256_file(shard)}],
    }
    (embedding_root / "embedding_cache_receipt.json").write_text(json.dumps(receipt))
    return table, table_receipt, embedding_root


def args_for(table, table_receipt, embeddings, output):
    return argparse.Namespace(
        input=table,
        table_receipt=table_receipt,
        embeddings=embeddings,
        output_dir=output,
        expected_outer_folds=5,
        inner_folds=3,
        subinner_folds=2,
        m2_alpha=10.0,
        pca_dimensions="2,3",
        head_families="ridge",
        ridge_alphas="1,10",
        extra_trees_estimators=20,
        extra_trees_max_features="0.5",
        extra_trees_min_samples_leaf="2",
        hist_learning_rates="0.05",
        hist_max_leaf_nodes="7",
        hist_min_samples_leaf=5,
        hist_l2="1",
        hist_max_iter=20,
        bootstrap_repetitions=50,
        seed=43,
    )


class TestM4SklearnFusion(unittest.TestCase):
    def test_balanced_parent_assignment_never_splits_parent(self):
        parents = ["A", "A", "B", "C", "C", "D"]
        assignment = mod.balanced_parent_assignment(parents, 3, "test")
        for parent in set(parents):
            values = {assignment[index] for index, value in enumerate(parents) if value == parent}
            self.assertEqual(len(values), 1)
        self.assertEqual(set(assignment.tolist()), {0, 1, 2})

    def test_strict_shard_hash_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            table, receipt, embeddings = make_package(root)
            payload = json.loads((embeddings / "embedding_cache_receipt.json").read_text())
            payload["shards"][0]["sha256"] = "0" * 64
            (embeddings / "embedding_cache_receipt.json").write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "embedding_shard_hash"):
                mod.load_validated_arrays(table, receipt, embeddings, 5)

    def test_all_optional_heads_fit_with_sample_weights(self):
        generator = np.random.default_rng(7)
        features = generator.normal(size=(40, 9))
        residual = 0.03 * features[:, 0] - 0.01 * features[:, 1]
        weights = np.linspace(0.65, 1.0, len(features))
        configs = [
            {"family": "ridge", "alpha": 10.0},
            {
                "family": "extra_trees", "n_estimators": 20,
                "max_features": 0.5, "min_samples_leaf": 2,
            },
            {
                "family": "hist_gradient_boosting", "learning_rate": 0.05,
                "max_leaf_nodes": 7, "min_samples_leaf": 5,
                "l2_regularization": 1.0, "max_iter": 20,
            },
        ]
        for index, config in enumerate(configs):
            model = mod.fit_head(config, features, residual, weights, 100 + index)
            self.assertTrue(np.isfinite(model.predict(features)).all())

    def test_outer_test_targets_cannot_change_inner_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            table, receipt, embeddings = make_package(root)
            arrays = mod.load_validated_arrays(table, receipt, embeddings, 5)
            args = args_for(table, receipt, embeddings, root / "unused")
            train = np.flatnonzero(arrays.folds != 0)
            first = mod.select_hyperparameters(0, train, arrays, args)
            changed_target = arrays.target.copy()
            changed_target[arrays.folds == 0] = 0.99
            changed = dataclasses.replace(arrays, target=changed_target)
            second = mod.select_hyperparameters(0, train, changed, args)
            self.assertEqual(first["selected_config"], second["selected_config"])
            self.assertEqual(first["results"], second["results"])

    def test_full_cpu_oof_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            table, receipt, embeddings = make_package(root)
            output = root / "output"
            summary = mod.main(args_for(table, receipt, embeddings, output))
            self.assertEqual(summary["status"], "PASS_V6_M4_OOF_COMPLETE")
            self.assertEqual(summary["rows"], 60)
            self.assertEqual(summary["parent_clusters"], 20)
            self.assertIn("spearman", summary["M2"])
            self.assertIn("parent_centered_spearman", summary["M4"])
            self.assertIn("top20_recall", summary["M4"])
            self.assertTrue((output / "terminal_receipt.json").is_file())
            _, prediction_rows = mod.read_table(output / "oof_predictions.tsv")
            self.assertEqual(len(prediction_rows), 60)
            self.assertEqual(len({row["candidate_id"] for row in prediction_rows}), 60)
            for fold in range(5):
                selection = json.loads((output / f"fold_{fold}" / "inner_selection.json").read_text())
                self.assertEqual(selection["selection_data_boundary"],
                                 "Only explicit outer-train indices are read; outer-test targets and features are not indexed by selection.")
                artifact = joblib.load(output / f"fold_{fold}" / "model.joblib")
                self.assertEqual(artifact["schema_version"], "pvrig_v6_m4_sklearn_model_v1")
                self.assertIn("pca", artifact["fusion_transformer"])


if __name__ == "__main__":
    unittest.main()
