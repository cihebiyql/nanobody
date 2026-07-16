#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("freeze_phase2_v4_f_prospective_holdout.py")
SPEC = importlib.util.spec_from_file_location("freeze_phase2_v4_f_prospective_holdout", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sequence(index: int) -> str:
    alphabet = MOD.AA_ORDER if hasattr(MOD, "AA_ORDER") else "ACDEFGHIKLMNPQRSTVWY"
    digits = []
    value = index
    for _ in range(5):
        digits.append(alphabet[value % len(alphabet)])
        value //= len(alphabet)
    tail = "".join(digits)
    return "QVQLVESGGGLVQPGGSLRLSCAAS" + tail + "WGQGTLVTVSS"


class FreezeV4FProspectiveHoldoutTest(unittest.TestCase):
    def fixture(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        import hashlib

        pool = []
        clusters = [f"C{index:04d}" for index in range(6)]
        counter = 0
        for cluster in clusters:
            for patch in MOD.PATCHES:
                for mode in MOD.MODES:
                    for replicate in range(MOD.ROWS_PER_STRATUM + 1):
                        seq = sequence(counter)
                        candidate_id = f"{cluster}_{patch}_{mode}_{replicate}"
                        pool.append(
                            {
                                "candidate_id": candidate_id,
                                "vhh_sequence": seq,
                                "sequence_sha256": hashlib.sha256(seq.encode()).hexdigest(),
                                "parent_id": f"P_{cluster}",
                                "parent_framework_cluster": cluster,
                                "design_method": "fixture",
                                "design_mode": mode,
                                "target_patch_id": patch,
                                "cdr1_after": "CAAS",
                                "cdr2_after": "ACDE",
                                "cdr3_after": "GHIK",
                                "cdr3_length": "4",
                            }
                        )
                        counter += 1
        v4d = [
            {
                "candidate_id": "old_a",
                "sequence_sha256": "a" * 64,
                "parent_framework_cluster": clusters[0],
            },
            {
                "candidate_id": "old_b",
                "sequence_sha256": "b" * 64,
                "parent_framework_cluster": clusters[1],
            },
        ]
        return pool, v4d

    def test_selection_is_balanced_deterministic_and_disjoint(self) -> None:
        pool, v4d = self.fixture()
        selected_clusters = MOD.select_clusters(pool, v4d)
        first = MOD.select_rows(pool, selected_clusters)
        second = MOD.select_rows(list(reversed(pool)), selected_clusters)
        self.assertEqual(first, second)
        checks = MOD.validate_output(first, selected_clusters, v4d)
        self.assertEqual(checks["row_count"], 96)
        self.assertEqual(set(checks["cluster_counts"].values()), {24})
        self.assertEqual(checks["patch_counts"], {"A_CENTER": 32, "B_LOWER": 32, "C_CROSS": 32})
        self.assertEqual(checks["mode_counts"], {"H1H3": 48, "H3": 48})

    def test_insufficient_stratum_fails_closed(self) -> None:
        pool, v4d = self.fixture()
        clusters = MOD.select_clusters(pool, v4d)
        target = (clusters[0], MOD.PATCHES[0], MOD.MODES[0])
        reduced = [
            row
            for row in pool
            if not (
                row["parent_framework_cluster"] == target[0]
                and row["target_patch_id"] == target[1]
                and row["design_mode"] == target[2]
                and row["candidate_id"].endswith(("_1", "_2"))
            )
        ]
        with self.assertRaisesRegex(MOD.HoldoutFreezeError, "insufficient_stratum_rows"):
            MOD.select_rows(reduced, clusters)

    def test_run_writes_hash_bound_manifest(self) -> None:
        pool, v4d = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool_path = root / "pool.csv"
            split_path = root / "split.tsv"
            with pool_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(pool[0]))
                writer.writeheader()
                writer.writerows(pool)
            with split_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(v4d[0]), delimiter="\t")
                writer.writeheader()
                writer.writerows(v4d)
            audit = MOD.run(
                pool_path,
                split_path,
                root / "out",
                enforce_production_hashes=False,
                expected_pool_rows=len(pool),
            )
            manifest = root / "out/prospective_holdout96_manifest.tsv"
            self.assertEqual(
                audit["status"], "TEST_ONLY_PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN"
            )
            self.assertEqual(audit["execution_mode"], "test_only")
            self.assertEqual(audit["output"]["sha256"], MOD.sha256_file(manifest))
            self.assertEqual(audit["checks"]["candidate_overlap_with_v4d"], 0)
            self.assertEqual(audit["checks"]["parent_cluster_overlap_with_v4d"], 0)
            receipt = root / "out/prospective_holdout96_receipt.json"
            self.assertTrue(receipt.is_file())


if __name__ == "__main__":
    unittest.main()
