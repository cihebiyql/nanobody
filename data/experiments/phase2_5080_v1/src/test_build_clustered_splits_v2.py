#!/usr/bin/env python3
"""Regression tests for global task-balanced clustered splits."""
from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_clustered_splits_v2 import assign_connected_splits


ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def sequence(offset: int, length: int) -> str:
    return "".join(ALPHABET[(offset + index * 7) % len(ALPHABET)] for index in range(length))


class GlobalClusteredSplitTests(unittest.TestCase):
    def test_shared_sequences_stay_together_across_tasks(self) -> None:
        rows = []
        for task_offset, task in enumerate(("site", "contact")):
            for index in range(10):
                offset = index + task_offset * 10
                rows.append(
                    {
                        "dataset_role": task,
                        "structure_group": f"{task}:{index}",
                        "vhh_seq": sequence(offset, 80),
                        "antigen_seq": sequence(offset + 40, 120),
                    }
                )
        rows[10]["vhh_seq"] = rows[0]["vhh_seq"]
        rows[10]["antigen_seq"] = rows[0]["antigen_seq"]

        splits, _, vhh_map, _, antigen_map, stats = assign_connected_splits(
            rows,
            vhh_threshold=0.99,
            antigen_threshold=0.99,
            cdr3_proxy_threshold=0.99,
            seed=73,
            structure_key="structure_group",
            balance_key="dataset_role",
        )

        self.assertEqual(splits[0], splits[10])
        self.assertEqual(vhh_map[rows[0]["vhh_seq"]], vhh_map[rows[10]["vhh_seq"]])
        self.assertEqual(antigen_map[rows[0]["antigen_seq"]], antigen_map[rows[10]["antigen_seq"]])
        for task in ("site", "contact"):
            counts = Counter(split for row, split in zip(rows, splits) if row["dataset_role"] == task)
            self.assertGreaterEqual(counts["train"], 6)
            self.assertGreaterEqual(counts["val"], 1)
            self.assertGreaterEqual(counts["test"], 1)
        self.assertEqual(stats["balance_key"], "dataset_role")


if __name__ == "__main__":
    unittest.main()
