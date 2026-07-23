from __future__ import annotations

import importlib.util
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_top7500_dual_multiseed_handoff",
    ROOT / "scripts/build_top7500_dual_multiseed_handoff.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RepeatSelectionTests(unittest.TestCase):
    def rows(self, count: int = 80):
        return [
            {
                "candidate_id": f"C{i:04d}",
                "docking_priority_rank": str(i + 1),
                "parent_framework_cluster": f"P{i % 4}",
                "confidence_tier": f"T{i % 2}",
                "docking_wave": f"W{i % 5}",
            }
            for i in range(count)
        ]

    def test_repeat_order_is_deterministic_unique_and_stratified(self):
        rows = self.rows()
        first = MODULE.stratified_repeat_order(rows)
        second = MODULE.stratified_repeat_order(list(reversed(rows)))
        self.assertEqual([r["candidate_id"] for r in first], [r["candidate_id"] for r in second])
        self.assertEqual(len(first), len(rows))
        self.assertEqual(len({r["candidate_id"] for r in first}), len(rows))
        first_twenty_parents = Counter(r["parent_framework_cluster"] for r in first[:20])
        self.assertEqual(set(first_twenty_parents), {"P0", "P1", "P2", "P3"})

    def test_sharding_keeps_both_receptors_together(self):
        jobs = []
        for candidate in ("A", "B", "C", "D"):
            for seed in (917, 1931):
                for receptor in MODULE.RECEPTORS:
                    jobs.append(
                        {
                            "entity_id": candidate,
                            "seed": str(seed),
                            "conformation": receptor,
                            "priority": str(len(jobs) + 1),
                        }
                    )
        shards = MODULE.shard_by_candidate_seed(jobs, 3)
        locations = {}
        for shard_index, shard in enumerate(shards):
            for row in shard:
                locations.setdefault((row["entity_id"], row["seed"]), set()).add(shard_index)
        self.assertTrue(all(len(value) == 1 for value in locations.values()))

    def test_sequence_range_maps_over_pdb_numbering_gaps(self):
        residue_order = [(1, " "), (2, " "), (4, " "), (5, " "), (8, " ")]
        self.assertEqual(
            MODULE.map_sequence_range_to_pdb_residues("2-4", residue_order, "C1"),
            [2, 4, 5],
        )


if __name__ == "__main__":
    unittest.main()
