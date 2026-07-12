#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("prepare_phase2_v3_g2_cluster_safe_data.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v3_g2_cluster_safe_data", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class PrepareV3G2ClusterSafeDataTest(unittest.TestCase):
    def test_parse_cluster_tsv_requires_complete_unique_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "clusters.tsv"
            path.write_text("a\ta\na\tb\nc\tc\n", encoding="utf-8")
            representatives, clusters = MOD.parse_cluster_tsv(path, {"a", "b", "c"})
            self.assertEqual(representatives["b"], "a")
            self.assertEqual(clusters["a"], clusters["b"])
            self.assertNotEqual(clusters["a"], clusters["c"])
            with self.assertRaises(ValueError):
                MOD.parse_cluster_tsv(path, {"a", "b", "c", "d"})

    def test_external_cluster_marks_all_development_neighbors(self) -> None:
        records = {
            "a": {"sequence": "AAA", "scopes": {"development"}},
            "b": {"sequence": "BBB", "scopes": {"external_hTNFa"}},
            "c": {"sequence": "CCC", "scopes": {"development"}},
        }
        clusters = {"a": "cluster_touching", "b": "cluster_touching", "c": "cluster_safe"}
        self.assertEqual(MOD.external_overlap_clusters(records, clusters), {"cluster_touching"})

    def test_assignment_is_deterministic_and_cluster_safe(self) -> None:
        rows = []
        for cluster_index in range(90):
            cluster_id = f"cluster_{cluster_index:03d}"
            sequence_id = f"sequence_{cluster_index:03d}"
            for target in ("target_a", "target_b"):
                for label in (0, 1):
                    rows.append(
                        {
                            "sample_id": f"{cluster_id}-{target}-{label}",
                            "cluster_id": cluster_id,
                            "sequence_sha256": sequence_id,
                            "dataset_id": "dataset",
                            "target_id": target,
                            "label": label,
                        }
                    )
        frame = pd.DataFrame(rows)
        first = MOD.assign_cluster_splits(frame)
        second = MOD.assign_cluster_splits(frame)
        self.assertEqual(first, second)
        self.assertEqual(set(first.values()), {"train", "dev", "test"})
        assigned = frame.assign(split=frame["cluster_id"].map(first))
        self.assertEqual(MOD.cross_split_overlap(assigned, "cluster_id"), {"train_dev": 0, "train_test": 0, "dev_test": 0})
        counts = assigned.groupby(["split", "target_id", "label"]).size()
        self.assertEqual(len(counts), 3 * 2 * 2)
        ratios = assigned["split"].value_counts(normalize=True).to_dict()
        self.assertLess(max(abs(ratios[key] - value) for key, value in MOD.SPLIT_FRACTIONS.items()), 0.03)


if __name__ == "__main__":
    unittest.main()
