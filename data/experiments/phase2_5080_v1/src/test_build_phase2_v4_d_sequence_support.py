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
        base = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY"
        self.references = []
        for cluster_index in range(5):
            for replicate in range(2):
                suffix = MOD.AA_ORDER[(cluster_index * 2 + replicate) % len(MOD.AA_ORDER)]
                sequence = base[: -(cluster_index + 2)] + suffix * (cluster_index + 2)
                cdr3 = "CAR" + MOD.AA_ORDER[cluster_index] * 2 + MOD.AA_ORDER[replicate + 8]
                self.references.append(
                    {
                        "candidate_id": f"r{cluster_index}_{replicate}",
                        "sequence_sha256": sequence_hash(sequence),
                        "sequence": sequence,
                        "parent_framework_cluster": f"C{cluster_index + 1}",
                        "cdr3": cdr3,
                    }
                )

    def test_levenshtein_and_normalization(self) -> None:
        self.assertEqual(MOD.levenshtein("CAR", "CAR"), 0)
        self.assertEqual(MOD.levenshtein("CAR", "CAAR"), 1)
        self.assertAlmostEqual(MOD.normalized_levenshtein_distance("CAR", "CAAR"), 0.25)

    def test_exact_trimer_vectors_are_collision_free_by_construction(self) -> None:
        first = MOD.kmer_vector("AAAAAA")
        second = MOD.kmer_vector("CCCCCC")
        self.assertEqual(first.shape, (8000,))
        self.assertEqual(MOD.KMER_WIDTH, 20**3)
        self.assertEqual(int((first != 0).sum()), 1)
        self.assertEqual(int((second != 0).sum()), 1)
        self.assertAlmostEqual(float(first @ second), 0.0)
        with self.assertRaisesRegex(MOD.SupportError, "exact_8000"):
            MOD.kmer_vector("AAAAAA", width=256)

    def test_nested_parent_validation_never_calibrates_on_held_out_parent(self) -> None:
        result = MOD.nested_parent_validation(
            self.references, support_quantile=0.95, fold_count=5, seed=17
        )
        self.assertEqual(result["row_count"], len(self.references))
        seen_validation: set[str] = set()
        for fold in result["folds"]:
            calibration = set(fold["calibration_parent_clusters"])
            validation = set(fold["validation_parent_clusters"])
            self.assertFalse(calibration & validation)
            seen_validation.update(validation)
        self.assertEqual(
            seen_validation,
            {row["parent_framework_cluster"] for row in self.references},
        )

    def test_joint_parent_blocks_cross_parent_channel_splicing(self) -> None:
        first = self.references[0]
        donor = self.references[-1]
        mutated = first["sequence"][:-1] + ("A" if first["sequence"][-1] != "A" else "C")
        candidate = {
            "candidate_id": "cross_parent_chimera",
            "sequence_sha256": sequence_hash(mutated),
            "sequence": mutated,
            "parent_framework_cluster": first["parent_framework_cluster"],
            "cdr3": donor["cdr3"],
        }
        vectors = MOD.kmer_matrix(self.references)
        scored = MOD.score_candidates(
            self.references,
            [candidate],
            reference_vectors=vectors,
            full_threshold=0.10,
            cdr3_threshold=0.01,
        )[0]
        self.assertEqual(scored["full_sequence_channel_supported"], "true")
        self.assertEqual(scored["cdr3_channel_supported"], "true")
        self.assertEqual(scored["declared_parent_joint_supported"], "false")
        self.assertEqual(scored["v4d_in_sequence_support"], "false")
        self.assertEqual(scored["v4d_support_domain"], "NEAR_DOMAIN")

    def test_unseen_parent_is_never_promoted_to_in_domain(self) -> None:
        source = self.references[0]
        candidate = {
            "candidate_id": "unseen",
            "sequence_sha256": source["sequence_sha256"],
            "sequence": source["sequence"],
            "parent_framework_cluster": "UNSEEN_PARENT",
            "cdr3": source["cdr3"],
        }
        scored = MOD.score_candidates(
            self.references,
            [candidate],
            reference_vectors=MOD.kmer_matrix(self.references),
            full_threshold=1.0,
            cdr3_threshold=1.0,
        )[0]
        # Exact train sequences remain TRAIN_REFERENCE even when provenance is malformed.
        self.assertEqual(scored["v4d_support_domain"], "TRAIN_REFERENCE")
        mutated = source["sequence"][:-1] + ("A" if source["sequence"][-1] != "A" else "C")
        candidate["candidate_id"] = "unseen_non_reference"
        candidate["sequence"] = mutated
        candidate["sequence_sha256"] = sequence_hash(mutated)
        scored = MOD.score_candidates(
            self.references,
            [candidate],
            reference_vectors=MOD.kmer_matrix(self.references),
            full_threshold=1.0,
            cdr3_threshold=1.0,
        )[0]
        self.assertEqual(scored["v4d_support_domain"], "NEAR_DOMAIN")
        self.assertEqual(scored["v4d_in_sequence_support"], "false")

    def test_shuffle_and_unseen_parent_chimera_nulls_report_each_channel(self) -> None:
        calibration = MOD.calibrate_lopo_thresholds(self.references)
        common = {
            "full_threshold": calibration["full_sequence_threshold"],
            "cdr3_threshold": calibration["cdr3_threshold"],
            "replicates": 20,
            "seed": 20260715,
        }
        shuffle = MOD.composition_preserving_shuffle_null(
            self.references, calibration["reference_vectors"], **common
        )
        chimera = MOD.unseen_parent_chimera_null(
            self.references, calibration["reference_vectors"], **common
        )
        for result in (shuffle, chimera):
            self.assertIn("full_channel_pass_fraction", result)
            self.assertIn("cdr3_channel_pass_fraction", result)
            self.assertIn("joint_parent_pass_fraction", result)
            self.assertIn("joint_reference_pass_fraction", result)

    def fixture_paths(self, directory: Path) -> tuple[Path, Path, Path]:
        split_path = directory / "split.tsv"
        pool_path = directory / "pool.csv"
        output_path = directory / "support.csv"
        split_rows = [
            {**row, "model_split": MOD.REFERENCE_SPLIT} for row in self.references
        ] + [
            {
                **self.references[0],
                "candidate_id": "held_out",
                "model_split": "PROSPECTIVE_COMPUTATIONAL_TEST",
            }
        ]
        candidate_rows = [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "vhh_sequence": row["sequence"],
                "cdr3_after": row["cdr3"],
                "parent_framework_cluster": row["parent_framework_cluster"],
            }
            for row in self.references
        ]
        source = self.references[0]
        mutated = source["sequence"][:-1] + ("A" if source["sequence"][-1] != "A" else "C")
        candidate_rows.append(
            {
                "candidate_id": "deployment_candidate",
                "sequence_sha256": sequence_hash(mutated),
                "vhh_sequence": mutated,
                "cdr3_after": source["cdr3"],
                "parent_framework_cluster": source["parent_framework_cluster"],
            }
        )
        write_table(split_path, split_rows, "\t")
        write_table(pool_path, candidate_rows, ",")
        return split_path, pool_path, output_path

    def test_production_mode_rejects_hash_and_gate_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            split_path, pool_path, output_path = self.fixture_paths(Path(temporary))
            with self.assertRaisesRegex(
                MOD.SupportError, "production_configuration_override_forbidden"
            ):
                MOD.main(
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
                        "--minimum-coverage",
                        "0",
                    ]
                )

    def test_test_only_cli_closes_hashes_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            split_path, pool_path, output_path = self.fixture_paths(directory)
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
                    "11",
                    "--expected-reference-count",
                    "10",
                    "--expected-candidate-count",
                    "11",
                    "--expected-train-reference-overlap",
                    "10",
                    "--outer-folds",
                    "5",
                    "--null-replicates",
                    "20",
                    "--minimum-coverage",
                    "0",
                    "--minimum-in-support-count",
                    "0",
                    "--minimum-nested-full-pass",
                    "0",
                    "--minimum-nested-cdr3-pass",
                    "0",
                    "--minimum-nested-joint-parent-pass",
                    "0",
                    "--maximum-shuffle-full-pass",
                    "1",
                    "--maximum-shuffle-cdr3-pass",
                    "1",
                    "--maximum-shuffle-joint-parent-pass",
                    "1",
                    "--maximum-chimera-joint-parent-pass",
                    "1",
                    "--maximum-chimera-joint-reference-pass",
                    "1",
                    "--test-only-allow-unfrozen-config",
                ]
            )
            self.assertEqual(result, 0)
            audit_path = output_path.with_suffix(".csv.audit.json")
            receipt_path = output_path.with_suffix(".csv.receipt.json")
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertTrue(audit["status"].startswith("TEST_ONLY_PASS"))
            self.assertEqual(audit["coverage"]["train_reference_count_excluded"], 10)
            self.assertEqual(audit["coverage"]["deployment_candidate_count"], 1)
            self.assertEqual(
                MOD.verify_artifact_closure(audit_path, receipt_path)["status"],
                "PASS_COMPLETE_HASH_CLOSURE",
            )
            with output_path.open("a", encoding="utf-8") as handle:
                handle.write("tampered\n")
            with self.assertRaisesRegex(MOD.SupportError, "closure_sha256_mismatch"):
                MOD.verify_artifact_closure(audit_path, receipt_path)


if __name__ == "__main__":
    unittest.main()
