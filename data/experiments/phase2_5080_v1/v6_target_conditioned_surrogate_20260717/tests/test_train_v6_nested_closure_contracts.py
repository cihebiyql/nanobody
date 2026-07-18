import hashlib
import importlib.util
import pathlib
import types
import unittest
from collections import Counter

import numpy as np
import torch


MODULE = pathlib.Path(__file__).parents[1] / "src" / "train_v6_fusion_surrogate.py"
spec = importlib.util.spec_from_file_location("v6_train_nested_contracts", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestNestedFoldContracts(unittest.TestCase):
    def test_parent_inner_fold_is_deterministic_and_outer_specific(self):
        parent = "PARENT_B"
        inner_folds = 3
        observed = [mod.parent_inner_fold(parent, outer, inner_folds) for outer in range(5)]
        expected = [
            int(
                hashlib.sha256(
                    f"PVRIG_V6_INNER|outer={outer}|{parent}".encode()
                ).hexdigest(),
                16,
            )
            % inner_folds
            for outer in range(5)
        ]

        self.assertEqual(observed, expected)
        self.assertEqual(
            observed,
            [mod.parent_inner_fold(parent, outer, inner_folds) for outer in range(5)],
        )
        self.assertGreater(len(set(observed)), 1, "outer fold must participate in the hash")

    def test_crossfit_baseline_does_not_use_held_inner_fold_labels(self):
        outer_fold = 2
        inner_folds = 3
        parents = [f"PARENT_{letter}" for letter in "ABCDEFGHIJKL" for _ in range(2)]
        rows = len(parents)
        structure = np.column_stack(
            (
                np.linspace(-2.0, 2.0, rows),
                np.sin(np.linspace(0.0, 3.0, rows)),
                np.cos(np.linspace(0.0, 4.0, rows)),
            )
        )
        targets = np.column_stack(
            (
                0.45 + 0.03 * structure[:, 0],
                0.53 - 0.02 * structure[:, 1],
                0.49 + 0.01 * structure[:, 2],
            )
        )
        arrays = {
            "parents": parents,
            "structure": structure,
            "targets": targets.copy(),
            "weights": np.ones(rows),
        }
        indices = np.arange(rows)
        original, counts = mod.crossfit_baselines(indices, arrays, outer_fold, inner_folds)
        self.assertGreaterEqual(len(counts), 2)

        assignments = np.asarray(
            [mod.parent_inner_fold(parent, outer_fold, inner_folds) for parent in parents]
        )
        held_inner_fold = sorted(counts)[0]
        held = assignments == held_inner_fold
        perturbed = dict(arrays)
        perturbed["targets"] = arrays["targets"].copy()
        perturbed["targets"][held] += np.asarray([50.0, -75.0, 125.0])
        changed, changed_counts = mod.crossfit_baselines(
            indices, perturbed, outer_fold, inner_folds
        )

        self.assertEqual(counts, changed_counts)
        np.testing.assert_array_equal(original[held], changed[held])
        self.assertFalse(
            np.array_equal(original[~held], changed[~held]),
            "the perturbation should remain visible only to models allowed to train on it",
        )


class TestEmbeddingTableClosureContracts(unittest.TestCase):
    @staticmethod
    def make_fixture():
        feature_names = [f"structure_feature_{index:03d}" for index in range(126)]
        fields = sorted(mod.METADATA) + feature_names
        rows = []
        embedding_map = {}
        embedding_hashes = {}
        for index in range(20):
            candidate = f"CANDIDATE_{index:03d}"
            sequence = f"SEQUENCE_{index:03d}"
            sequence_hash = hashlib.sha256(sequence.encode()).hexdigest()
            fold = index % 5
            row = {name: "" for name in fields}
            row.update(
                {
                    "candidate_id": candidate,
                    "sequence": sequence,
                    "sequence_sha256": sequence_hash,
                    "parent_framework_cluster": f"PARENT_F{fold}_{index // 5}",
                    "outer_fold": str(fold),
                }
            )
            rows.append(row)
            embedding_map[candidate] = torch.zeros(8)
            embedding_hashes[candidate] = sequence_hash
        args = types.SimpleNamespace(max_rows=None, smoke_mode=False)
        return fields, rows, embedding_map, embedding_hashes, args, feature_names

    def test_exact_embedding_table_closure_passes(self):
        fields, rows, embedding_map, embedding_hashes, args, feature_names = self.make_fixture()
        selected, observed_features = mod.validate_rows(
            fields, rows, embedding_map, embedding_hashes, args
        )
        self.assertEqual(selected, rows)
        self.assertEqual(observed_features, feature_names)

    def test_missing_or_extra_embedding_is_rejected(self):
        fields, rows, embedding_map, embedding_hashes, args, _ = self.make_fixture()
        missing_map = dict(embedding_map)
        missing_hashes = dict(embedding_hashes)
        missing_map.pop(rows[0]["candidate_id"])
        missing_hashes.pop(rows[0]["candidate_id"])
        with self.assertRaisesRegex(ValueError, "embedding_candidate_closure"):
            mod.validate_rows(fields, rows, missing_map, missing_hashes, args)

        extra_map = dict(embedding_map)
        extra_hashes = dict(embedding_hashes)
        extra_map["UNDECLARED_CANDIDATE"] = torch.zeros(8)
        extra_hashes["UNDECLARED_CANDIDATE"] = hashlib.sha256(b"extra").hexdigest()
        with self.assertRaisesRegex(ValueError, "embedding_candidate_closure"):
            mod.validate_rows(fields, rows, extra_map, extra_hashes, args)

    def test_embedding_sequence_hash_must_close_to_table_sequence(self):
        fields, rows, embedding_map, embedding_hashes, args, _ = self.make_fixture()
        candidate = rows[7]["candidate_id"]
        embedding_hashes = dict(embedding_hashes)
        embedding_hashes[candidate] = hashlib.sha256(b"different sequence").hexdigest()
        with self.assertRaisesRegex(ValueError, f"sequence_hash_closure:{candidate}"):
            mod.validate_rows(fields, rows, embedding_map, embedding_hashes, args)


class TestParentAwareBatchSamplerContracts(unittest.TestCase):
    def test_batches_are_deterministic_paired_bounded_and_exhaustive(self):
        parents = [parent for parent in ("P0", "P1", "P2", "P3") for _ in range(4)]
        sampler_a = mod.ParentAwareBatchSampler(
            parents, batch_size=4, per_parent=2, seed=1931
        )
        sampler_b = mod.ParentAwareBatchSampler(
            parents, batch_size=4, per_parent=2, seed=1931
        )
        batches_a = list(sampler_a)
        batches_b = list(sampler_b)

        self.assertEqual(batches_a, batches_b)
        self.assertEqual(len(batches_a), len(sampler_a))
        self.assertEqual(sorted(index for batch in batches_a for index in batch), list(range(16)))
        for batch in batches_a:
            self.assertLessEqual(len(batch), 4)
            counts = Counter(parents[index] for index in batch)
            self.assertTrue(counts)
            self.assertTrue(all(count % 2 == 0 for count in counts.values()))
            self.assertTrue(any(count >= 2 for count in counts.values()))


if __name__ == "__main__":
    unittest.main()
