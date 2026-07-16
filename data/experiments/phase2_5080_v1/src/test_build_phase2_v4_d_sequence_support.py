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


MODULE_PATH = Path(__file__).with_name("build_phase2_v4_d_sequence_support.py")
SPEC = importlib.util.spec_from_file_location(
    "build_phase2_v4_d_sequence_support", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def write_table(path: Path, rows: list[dict[str, str]], delimiter: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


class BuildV4DSequenceSupportTest(unittest.TestCase):
    def setUp(self) -> None:
        base = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKL"
        self.references = [
            {
                "candidate_id": "r1",
                "sequence_sha256": sequence_hash(base),
                "sequence": base,
                "parent_framework_cluster": "C1",
                "cdr3": "CARAAA",
            },
            {
                "candidate_id": "r2",
                "sequence_sha256": sequence_hash(base[:-1] + "M"),
                "sequence": base[:-1] + "M",
                "parent_framework_cluster": "C1",
                "cdr3": "CARAAT",
            },
            {
                "candidate_id": "r3",
                "sequence_sha256": sequence_hash(base[:-2] + "MN"),
                "sequence": base[:-2] + "MN",
                "parent_framework_cluster": "C2",
                "cdr3": "CARACA",
            },
            {
                "candidate_id": "r4",
                "sequence_sha256": sequence_hash(base[:-3] + "MNP"),
                "sequence": base[:-3] + "MNP",
                "parent_framework_cluster": "C2",
                "cdr3": "CARACT",
            },
            {
                "candidate_id": "r5",
                "sequence_sha256": sequence_hash(base[:-4] + "MNPQ"),
                "sequence": base[:-4] + "MNPQ",
                "parent_framework_cluster": "C3",
                "cdr3": "CARADA",
            },
            {
                "candidate_id": "r6",
                "sequence_sha256": sequence_hash(base[:-5] + "MNPQR"),
                "sequence": base[:-5] + "MNPQR",
                "parent_framework_cluster": "C3",
                "cdr3": "CARADT",
            },
        ]

    def test_levenshtein_and_normalization(self) -> None:
        self.assertEqual(MOD.levenshtein("CAR", "CAR"), 0)
        self.assertEqual(MOD.levenshtein("CAR", "CAAR"), 1)
        self.assertAlmostEqual(
            MOD.normalized_levenshtein_distance("CAR", "CAAR"), 0.25
        )

    def test_identical_kmer_vectors_have_zero_distance(self) -> None:
        vector = MOD.kmer_vector(self.references[0]["sequence"])
        self.assertAlmostEqual(MOD.clamp_cosine_distance(1.0 - vector @ vector), 0.0)

    def test_lopo_excludes_the_entire_parent_cluster(self) -> None:
        calibration = MOD.lopo_calibration(self.references)
        for row in calibration["row_controls"]:
            self.assertNotEqual(
                row["parent_framework_cluster"],
                row["nearest_lopo_full_parent_cluster"],
            )
            self.assertNotEqual(
                row["parent_framework_cluster"],
                row["nearest_lopo_cdr3_parent_cluster"],
            )
        self.assertGreaterEqual(calibration["joint_pass_fraction"], 0.0)
        self.assertLessEqual(calibration["joint_pass_fraction"], 1.0)

    def test_shuffle_is_composition_preserving_and_deterministic(self) -> None:
        first_rng = MOD.np.random.default_rng(20260715)
        second_rng = MOD.np.random.default_rng(20260715)
        sequence = "AACCDDEEFFGG"
        first = MOD.shuffled_copy(sequence, first_rng)
        second = MOD.shuffled_copy(sequence, second_rng)
        self.assertEqual(first, second)
        self.assertEqual(sorted(first), sorted(sequence))

        calibration = MOD.lopo_calibration(self.references)
        kwargs = {
            "full_threshold": calibration["full_sequence_threshold"],
            "cdr3_threshold": calibration["cdr3_threshold"],
            "replicates": 20,
            "seed": 20260715,
        }
        first_null = MOD.composition_preserving_shuffle_null(
            self.references, calibration["reference_vectors"], **kwargs
        )
        second_null = MOD.composition_preserving_shuffle_null(
            self.references, calibration["reference_vectors"], **kwargs
        )
        self.assertEqual(first_null, second_null)

    def test_score_candidates_emits_three_domain_tiers(self) -> None:
        calibration = MOD.lopo_calibration(self.references)
        candidates = [
            {
                "candidate_id": "in",
                "sequence_sha256": self.references[0]["sequence_sha256"],
                "sequence": self.references[0]["sequence"],
                "parent_framework_cluster": "P1",
                "cdr3": self.references[0]["cdr3"],
            },
            {
                "candidate_id": "near",
                "sequence_sha256": self.references[0]["sequence_sha256"],
                "sequence": self.references[0]["sequence"],
                "parent_framework_cluster": "P2",
                "cdr3": "WWWWWW",
            },
            {
                "candidate_id": "ood",
                "sequence_sha256": sequence_hash("WWWWWWWWWWWWWWWWWWWWWWWWWWWWWW"),
                "sequence": "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
                "parent_framework_cluster": "P3",
                "cdr3": "WWWWWW",
            },
        ]
        scored = MOD.score_candidates(
            self.references,
            candidates,
            reference_vectors=calibration["reference_vectors"],
            full_threshold=calibration["full_sequence_threshold"],
            cdr3_threshold=calibration["cdr3_threshold"],
        )
        self.assertEqual(
            [row["v4d_support_domain"] for row in scored],
            ["IN_DOMAIN", "NEAR_DOMAIN", "OOD"],
        )
        self.assertEqual(scored[0]["nearest_full_reference_candidate_id"], "r1")
        self.assertEqual(scored[0]["nearest_cdr3_reference_candidate_id"], "r1")

    def test_fixture_cli_writes_hashed_audit_with_configurable_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            split_path = directory / "split.tsv"
            pool_path = directory / "pool.csv"
            output_path = directory / "support.csv"
            split_rows = [
                {**row, "model_split": "OPEN_TRAIN"} for row in self.references
            ] + [
                {
                    **self.references[0],
                    "candidate_id": "held_out",
                    "model_split": "PROSPECTIVE_COMPUTATIONAL_TEST",
                }
            ]
            candidate_rows = [
                {
                    "candidate_id": "candidate",
                    "sequence_sha256": self.references[0]["sequence_sha256"],
                    "vhh_sequence": self.references[0]["sequence"],
                    "cdr3_after": self.references[0]["cdr3"],
                    "parent_framework_cluster": "P1",
                }
            ]
            write_table(split_path, split_rows, "\t")
            write_table(pool_path, candidate_rows, ",")

            result = MOD.main(
                [
                    "--split-manifest",
                    str(split_path),
                    "--candidate-pool",
                    str(pool_path),
                    "--out",
                    str(output_path),
                    "--expected-split-sha256",
                    MOD.sha256_file(split_path),
                    "--expected-candidate-pool-sha256",
                    MOD.sha256_file(pool_path),
                    "--expected-split-count",
                    "7",
                    "--expected-reference-count",
                    "6",
                    "--expected-candidate-count",
                    "1",
                    "--minimum-in-support-count",
                    "1",
                    "--minimum-lopo-joint",
                    "0",
                    "--maximum-null-joint",
                    "1",
                    "--null-replicates",
                    "20",
                ]
            )
            self.assertEqual(result, 0)
            audit_path = output_path.with_suffix(".csv.audit.json")
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["reference"]["row_count"], 6)
            self.assertEqual(audit["coverage"]["candidate_count"], 1)
            self.assertEqual(audit["coverage"]["in_support_count"], 1)
            self.assertEqual(audit["controls"]["composition_preserving_shuffle_null"]["seed"], 20260715)
            self.assertEqual(audit["controls"]["composition_preserving_shuffle_null"]["replicates"], 20)
            self.assertEqual(
                audit["outputs"]["sequence_support_csv"]["sha256"],
                MOD.sha256_file(output_path),
            )
            self.assertEqual(len(audit["configuration_sha256"]), 64)
            self.assertEqual(len(audit["audit_payload_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
