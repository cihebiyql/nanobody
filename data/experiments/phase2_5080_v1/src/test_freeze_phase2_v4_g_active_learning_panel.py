#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("freeze_phase2_v4_g_active_learning_panel.py")
SPEC = importlib.util.spec_from_file_location(
    "freeze_phase2_v4_g_active_learning_panel", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def aa_token(index: int, length: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    value = index + 1
    output = []
    for _ in range(length):
        output.append(alphabet[value % len(alphabet)])
        value = value // len(alphabet) + 1
    return "".join(output)


def write_table(path: Path, rows: list[dict[str, str]], delimiter: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


class FreezeV4GActiveLearningPanelTest(unittest.TestCase):
    def fixture(
        self,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        clusters = [f"C{index:04d}" for index in range(13)]
        pool: list[dict[str, str]] = []
        counter = 0
        for cluster in clusters:
            for patch in MOD.PATCHES:
                for mode in MOD.MODES:
                    for replicate in range(3):
                        cdr1 = aa_token(counter * 3, 7)
                        cdr2 = aa_token(counter * 3 + 1, 7)
                        cdr3 = aa_token(counter * 3 + 2, 12)
                        sequence = (
                            "QVQLVESGGGLVQPGGSLRLSCAAS"
                            + cdr1
                            + "WFRQAPGKEREFVA"
                            + cdr2
                            + "RFTISRDNAKNTVYLQMNSLKPEDTAVYYC"
                            + cdr3
                            + "WGQGTQVTVSS"
                        )
                        candidate_id = f"{cluster}_{patch}_{mode}_{replicate}"
                        pool.append(
                            {
                                "candidate_id": candidate_id,
                                "vhh_sequence": sequence,
                                "sequence_sha256": hashlib.sha256(
                                    sequence.encode("ascii")
                                ).hexdigest(),
                                "parent_id": f"P_{cluster}",
                                "parent_framework_cluster": cluster,
                                "design_method": "synthetic",
                                "design_mode": mode,
                                "target_patch_id": patch,
                                "cdr1_after": cdr1,
                                "cdr2_after": cdr2,
                                "cdr3_after": cdr3,
                                "cdr3_length": str(len(cdr3)),
                                "fast_gate_tier": "FORMAL_ELIGIBLE",
                                "hard_fail": "False",
                            }
                        )
                        counter += 1

        by_cluster: dict[str, list[dict[str, str]]] = {}
        for cluster in clusters:
            by_cluster[cluster] = [
                row for row in pool if row["parent_framework_cluster"] == cluster
            ]

        def reference(source: dict[str, str], model_split: str) -> dict[str, str]:
            return {
                "candidate_id": source["candidate_id"],
                "sequence_sha256": source["sequence_sha256"],
                "sequence": source["vhh_sequence"],
                "parent_id": source["parent_id"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "design_method": source["design_method"],
                "design_mode": source["design_mode"],
                "target_patch_id": source["target_patch_id"],
                "cdr1": source["cdr1_after"],
                "cdr2": source["cdr2_after"],
                "cdr3": source["cdr3_after"],
                "cdr3_length": source["cdr3_length"],
                "model_split": model_split,
            }

        v4d = [
            reference(by_cluster[clusters[0]][0], "OPEN_TRAIN"),
            reference(by_cluster[clusters[1]][0], "OPEN_TRAIN"),
        ]
        v4f = [reference(by_cluster[clusters[2]][0], "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT")]
        return pool, v4d, v4f

    def write_fixture(
        self, root: Path
    ) -> tuple[Path, Path, Path, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        pool, v4d, v4f = self.fixture()
        pool_path = root / "pool.csv"
        v4d_path = root / "v4d.tsv"
        v4f_path = root / "v4f.tsv"
        write_table(pool_path, pool, ",")
        write_table(v4d_path, v4d, "\t")
        write_table(v4f_path, v4f, "\t")
        return pool_path, v4d_path, v4f_path, pool, v4d, v4f

    def run_fixture(self, root: Path, **overrides):
        pool_path, v4d_path, v4f_path, pool, v4d, v4f = self.write_fixture(root)
        result = MOD.run(
            pool_path,
            v4d_path,
            v4f_path,
            root / "out",
            enforce_production_hashes=False,
            expected_pool_rows=len(pool),
            expected_v4d_rows=len(v4d),
            expected_v4f_rows=len(v4f),
            expected_pool_parent_clusters=13,
            expected_remaining_parent_clusters=10,
            expected_open_train_parent_clusters=2,
            **overrides,
        )
        return result, pool_path, v4d_path, v4f_path

    def test_selection_is_deterministic_balanced_and_reference_disjoint(self) -> None:
        pool, v4d, v4f = self.fixture()
        pool_by_id = {row["candidate_id"]: row for row in pool}
        canonical_pool = MOD.validate_pool(
            pool,
            list(pool[0]),
            expected_rows=len(pool),
            expected_parent_clusters=13,
        )
        canonical_by_id = {row["candidate_id"]: row for row in canonical_pool}
        canonical_v4d = MOD.validate_reference(
            v4d,
            list(v4d[0]),
            canonical_by_id,
            label="v4d_split",
            expected_rows=2,
        )
        canonical_v4f = MOD.validate_reference(
            v4f,
            list(v4f[0]),
            canonical_by_id,
            label="v4f_holdout",
            expected_rows=1,
        )
        acquisition, reserve, ranking = MOD.choose_parent_roles(
            canonical_pool,
            canonical_v4d,
            canonical_v4f,
            expected_remaining_parent_clusters=10,
        )
        eligible = MOD.filter_reference_disjoint(
            canonical_pool, [*canonical_v4d, *canonical_v4f]
        )
        first = MOD.select_unseen96(eligible, acquisition)
        second = MOD.select_unseen96(list(reversed(eligible)), acquisition)
        self.assertEqual(first, second)
        checks = MOD.validate_selected_panel(
            first, acquisition, reserve, canonical_v4d, canonical_v4f
        )
        self.assertEqual(checks["row_count"], 96)
        self.assertEqual(set(checks["parent_counts"].values()), {12})
        self.assertTrue(
            all(
                count == 0
                for group in checks["reference_overlap_counts"].values()
                for count in group.values()
            )
        )
        self.assertEqual(len(MOD.build_reserve_rows(eligible, reserve, ranking)), 2)
        self.assertEqual(len(pool_by_id), len(pool))

    def test_pipeline_preregisters_seen200_and_publishes_receipt_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destinations: list[str] = []
            original_replace = os.replace

            def record_replace(source, destination):
                destinations.append(Path(destination).name)
                return original_replace(source, destination)

            with mock.patch.object(MOD.os, "replace", side_effect=record_replace):
                audit, *_ = self.run_fixture(root)
            output = root / "out"
            self.assertEqual(
                audit["status"],
                "TEST_ONLY_PASS_LABEL_FREE_UNSEEN96_AND_RESERVE2_FROZEN",
            )
            self.assertEqual(destinations[-1], MOD.OUTPUT_FILENAMES[-1])
            prereg = json.loads(
                (output / "phase2_v4_g_active_learning_preregistration.json").read_text()
            )
            self.assertEqual(prereg["future_seen200"]["rows"], 200)
            self.assertEqual(
                prereg["future_seen200"]["model_open_gate_pass_quota_per_parent"],
                {"top": 4, "uncertainty": 3, "disagreement": 2, "control": 1},
            )
            self.assertEqual(
                prereg["future_seen200"]["model_open_gate_fail_quota_per_parent"]
                ["label_free_diverse_replacing_top"],
                4,
            )
            receipt = json.loads(
                (output / "v4_g_active_learning_freeze_receipt.json").read_text()
            )
            for name, digest in receipt["outputs"].items():
                self.assertEqual(MOD.sha256_file(output / name), digest)

    def test_reference_overlap_can_make_a_stratum_fail_closed(self) -> None:
        pool, v4d, v4f = self.fixture()
        canonical_pool = MOD.validate_pool(
            pool,
            list(pool[0]),
            expected_rows=len(pool),
            expected_parent_clusters=13,
        )
        by_id = {row["candidate_id"]: row for row in canonical_pool}
        cv4d = MOD.validate_reference(v4d, list(v4d[0]), by_id, label="v4d_split", expected_rows=2)
        cv4f = MOD.validate_reference(v4f, list(v4f[0]), by_id, label="v4f_holdout", expected_rows=1)
        acquisition, _reserve, _ranking = MOD.choose_parent_roles(
            canonical_pool, cv4d, cv4f, expected_remaining_parent_clusters=10
        )
        target = (acquisition[0], MOD.PATCHES[0], MOD.MODES[0])
        reference_cdr = cv4d[0]["cdr1"]
        for row in canonical_pool:
            if (
                row["parent_framework_cluster"],
                row["target_patch_id"],
                row["design_mode"],
            ) == target:
                row["cdr1"] = reference_cdr
        eligible = MOD.filter_reference_disjoint(canonical_pool, [*cv4d, *cv4f])
        with self.assertRaisesRegex(MOD.ActiveLearningFreezeError, "insufficient_unseen_stratum"):
            MOD.select_unseen96(eligible, acquisition)

    def test_immutable_snapshots_bind_consumed_bytes_after_path_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool_path, v4d_path, v4f_path, pool, v4d, v4f = self.write_fixture(root)
            expected = {
                "candidate_pool": MOD.sha256_file(pool_path),
                "v4d_split": MOD.sha256_file(v4d_path),
                "v4f_holdout": MOD.sha256_file(v4f_path),
            }
            original = MOD.select_unseen96

            def mutate_paths(eligible, parents):
                result = original(eligible, parents)
                pool_path.write_text("candidate_id\ntampered\n")
                v4d_path.write_text("candidate_id\ntampered\n")
                v4f_path.write_text("candidate_id\ntampered\n")
                return result

            with mock.patch.object(MOD, "select_unseen96", side_effect=mutate_paths):
                audit = MOD.run(
                    pool_path,
                    v4d_path,
                    v4f_path,
                    root / "out",
                    enforce_production_hashes=False,
                    expected_pool_rows=len(pool),
                    expected_v4d_rows=len(v4d),
                    expected_v4f_rows=len(v4f),
                    expected_pool_parent_clusters=13,
                    expected_remaining_parent_clusters=10,
                    expected_open_train_parent_clusters=2,
                )
            self.assertEqual(
                {name: value["sha256"] for name, value in audit["inputs"].items()},
                expected,
            )

    def test_forbidden_label_field_and_production_hash_tamper_are_rejected(self) -> None:
        pool, _v4d, _v4f = self.fixture()
        pool[0]["R_dual_min"] = "0.9"
        with self.assertRaisesRegex(
            MOD.ActiveLearningFreezeError, "forbidden_label_fields"
        ):
            MOD.validate_pool(
                pool,
                list(pool[0]),
                expected_rows=len(pool),
                expected_parent_clusters=13,
            )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool_path, v4d_path, v4f_path, *_ = self.write_fixture(root)
            with self.assertRaisesRegex(
                MOD.ActiveLearningFreezeError, "candidate_pool_sha256_mismatch"
            ):
                MOD.run(pool_path, v4d_path, v4f_path, root / "out")

    def test_real_production_inputs_replay_and_match_frozen_outputs_when_present(self) -> None:
        experiment = MODULE_PATH.parents[1]
        pool = (
            experiment
            / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/fast_gate_formal_eligible_v1.csv"
        )
        v4d = experiment / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
        v4f = experiment / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv"
        if not all(path.is_file() for path in (pool, v4d, v4f)):
            self.skipTest("production inputs are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pvrig_v4_g"
            audit = MOD.run(pool, v4d, v4f, output)
            self.assertEqual(audit["checks"]["row_count"], 96)
            self.assertEqual(len(audit["parent_selection"]["reserve_parents"]), 2)
            frozen = experiment / "data_splits/pvrig_v4_g"
            if frozen.is_dir():
                for name in MOD.OUTPUT_FILENAMES:
                    self.assertEqual((output / name).read_bytes(), (frozen / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
