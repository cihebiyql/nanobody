#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_dual_pair_contact_targets_v2 as mod  # noqa: E402


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]], *, compressed: bool = False) -> None:
    opener = gzip.open if compressed else Path.open
    if compressed:
        handle = opener(path, "wt", encoding="utf-8", newline="")
    else:
        handle = opener(path, "w", encoding="utf-8", newline="")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class SyntheticInputs:
    def __init__(self, root: Path) -> None:
        self.root = root
        sequence = "ACDE"
        digest = hashlib.sha256(sequence.encode()).hexdigest()
        self.training = root / "training.tsv"
        training_fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "teacher_source",
        ]
        training_rows = [
            {"candidate_id": candidate, "sequence": sequence, "sequence_sha256": digest, "parent_framework_cluster": parent, "teacher_source": source}
            for candidate, parent, source in (
                ("D_NONZERO", "PD", mod.V4D), ("D_ZERO", "PD", mod.V4D),
                ("H_NONZERO", "PH", mod.V4H), ("H_ZERO", "PH", mod.V4H),
            )
        ]
        write_tsv(self.training, training_fields, training_rows)

        self.target_cache = root / "target_graph_cache_v2.npz"
        np.savez_compressed(
            self.target_cache,
            **{
                "8x6b_uniprot_position": np.asarray([41, 42, 43]),
                "9e6y_uniprot_position": np.asarray([41, 42, 43]),
            },
        )
        self.target_manifest = root / "target_graph_manifest_v2.tsv"
        write_tsv(
            self.target_manifest,
            ["receptor", "sequence", "node_count"],
            [
                {"receptor": "8x6b", "sequence": "FGH", "node_count": 3},
                {"receptor": "9e6y", "sequence": "FGH", "node_count": 3},
            ],
        )
        self.target_receipt = root / "target_graph_receipt_v2.json"
        self.target_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_residue_v2_fixed_target_graphs",
            "status": "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
            "outputs": {
                self.target_cache.name: mod.sha256_file(self.target_cache),
                self.target_manifest.name: mod.sha256_file(self.target_manifest),
            },
            "sealed_boundary": {
                "teacher_source_is_model_feature": False,
                "candidate_docking_pose_files_opened": 0,
            },
        }))

        self.v4d_pair = root / "v4d_pair.tsv.gz"
        v4d_rows = []
        for receptor, seed_values in (("8x6b", [(917, 0.1), (1931, 0.3)]), ("9e6y", [(917, 0.1), (1931, 0.2), (3253, 0.3)])):
            values = np.asarray([value for _, value in seed_values])
            variance = float(values.var(ddof=0))
            v4d_rows.append({
                "schema_version": "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2",
                # Upstream state is candidate-level, so the complete receptor
                # row remains PARTIAL when its peer receptor has only 2/3 seeds.
                "teacher_state": "VALID_DUAL_MULTI_SEED_PARTIAL_TECHNICAL_REPEAT",
                "candidate_id": "D_NONZERO", "sequence_sha256": digest,
                "parent_framework_cluster": "PD", "receptor": receptor,
                "vhh_sequence_index": 1, "vhh_aa": "A",
                "pvrig_uniprot_position": 41, "pvrig_aa": "F",
                "contact_target_mean": format(float(values.mean()), ".12g"),
                "contact_target_variance": format(variance, ".12g"),
                "contact_uncertainty_weight": format(1.0 / (1.0 + 4.0 * variance), ".12g"),
                "supporting_seed_count": len(seed_values),
                "observed_seed_count": len(seed_values), "expected_seed_count": 3,
                "seed_contact_values": ";".join(f"{seed}:{value}" for seed, value in seed_values),
            })
        write_tsv(self.v4d_pair, list(v4d_rows[0]), v4d_rows, compressed=True)
        self.v4d_receipt = root / "v4d_receipt.json"
        self.v4d_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2_receipt",
            "status": "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2",
            "counts": {
                "teacher_candidates": 2, "pair_rows": 2, "zero_imputed_failed_seeds": 0,
                "partial_seed_candidates": 1,
            },
            "outputs": {"pair_sha256": mod.sha256_file(self.v4d_pair)},
            "sealed_boundary": {
                "sealed_pose_files_opened": 0, "sealed_result_files_opened": 0,
                "shared_job_results_tsv_opened": 0, "shared_pose_scores_tsv_opened": 0,
            },
            "source": {"source_mutation_operations": 0},
        }))

        self.v4h_pair = root / "v4h_pair.tsv.gz"
        v4h_rows = [{
            "schema_version": "pvrig_v6_v4h_stage1_contact_teacher_v1",
            "teacher_state": "VALID_DUAL_1_SEED_CONTACT",
            "candidate_id": "H_NONZERO", "sequence_sha256": digest,
            "parent_framework_cluster": "PH", "receptor": receptor, "seed": 917,
            "vhh_sequence_index": 2, "vhh_aa": "C",
            "pvrig_uniprot_position": 42, "pvrig_aa": "G",
            "contact_frequency_pose_weighted": 0.25,
            "supporting_pose_count": 2,
            "selected_pose_count": 4 if receptor == "8x6b" else 8,
        } for receptor in mod.RECEPTORS]
        write_tsv(self.v4h_pair, list(v4h_rows[0]), v4h_rows, compressed=True)
        self.v4h_receipt = root / "v4h_receipt.json"
        self.v4h_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_v4h_stage1_contact_teacher_v1_receipt",
            "status": "COMPLETE_V4H_STAGE1_CONTACT_TEACHER_EXTRACTION",
            "valid_candidate_rows": 2, "technical_incomplete_pose_files_opened": 0,
            "source_mutation_operations": 0, "pair_rows": 2,
            "output_hashes": {self.v4h_pair.name: mod.sha256_file(self.v4h_pair)},
        }))

    def build(self, output: Path) -> dict[str, object]:
        return mod.build_targets(
            training_tsv=self.training,
            v4d_pair_tsv_gz=self.v4d_pair,
            v4d_receipt=self.v4d_receipt,
            v4h_pair_tsv_gz=self.v4h_pair,
            v4h_receipt=self.v4h_receipt,
            target_cache_npz=self.target_cache,
            target_manifest_tsv=self.target_manifest,
            target_receipt=self.target_receipt,
            output_dir=output,
            expected_source_counts={mod.V4D: 2, mod.V4H: 2},
            expected_parent_counts={mod.V4D: 1, mod.V4H: 1},
        )


class DualPairBuilderTests(unittest.TestCase):
    def test_builds_canonical_sparse_pairs_and_explicit_zero_group_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = SyntheticInputs(root)
            receipt = inputs.build(root / "output")
            self.assertEqual(receipt["status"], mod.STATUS)
            self.assertEqual(receipt["counts"]["pair_rows"], 4)
            self.assertEqual(receipt["counts"]["candidate_receptor_groups"], 8)
            self.assertEqual(receipt["counts"]["zero_nonzero_pair_groups"], 4)
            self.assertEqual(receipt["counts"]["technical_failed_seed_zero_imputations"], 0)
            self.assertEqual(receipt["counts"]["unresolved_target_pair_rows_dropped"], 0)
            self.assertEqual(receipt["target_mapping_audit"]["target_node_counts"], {"8x6b": 3, "9e6y": 3})
            self.assertEqual(receipt["target_mapping_audit"]["unresolved_target_position_policy"], "FAIL_CLOSED_NO_DROP")
            self.assertEqual(receipt["implementation"]["sha256"], mod.sha256_file(Path(mod.__file__)))

            with gzip.open(root / "output" / mod.OUTPUT_NAME, "rt", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual({row["pair_table_semantics"] for row in rows}, {mod.PAIR_SEMANTICS})
            partial = next(row for row in rows if row["candidate_id"] == "D_NONZERO" and row["receptor"] == "8x6b")
            self.assertEqual(partial["observed_seed_count"], "2")
            self.assertEqual(partial["expected_seed_count"], "3")
            self.assertAlmostEqual(float(partial["contact_target"]), 0.2)
            self.assertAlmostEqual(float(partial["contact_variance"]), 0.01)
            self.assertEqual(partial["pvrig_node_index"], "1")

            with (root / "output" / mod.GROUP_AUDIT_NAME).open(newline="") as handle:
                groups = list(csv.DictReader(handle, delimiter="\t"))
            zero = next(row for row in groups if row["candidate_id"] == "D_ZERO" and row["receptor"] == "8x6b")
            self.assertEqual(zero["nonzero_pair_rows"], "0")
            self.assertEqual(zero["observed_seed_count_min"], "")
            self.assertEqual(zero["observed_seed_count_audit_state"], "UNAVAILABLE_ZERO_NONZERO_PAIR_GROUP_NO_SEED_IMPUTATION")

    def test_output_is_deterministic_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = SyntheticInputs(root)
            first = inputs.build(root / "first")
            second = inputs.build(root / "second")
            self.assertEqual(first["outputs"], second["outputs"])
            for name, digest in first["outputs"].items():
                self.assertEqual(digest, mod.sha256_file(root / "first" / name))
            sums = (root / "first" / mod.SHA256SUMS_NAME).read_text()
            self.assertIn(mod.OUTPUT_NAME, sums)
            self.assertIn(mod.RECEIPT_NAME, sums)

    def test_invalid_sequence_position_or_target_aa_fails_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = SyntheticInputs(root)
            with gzip.open(inputs.v4h_pair, "rt", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                fields, rows = list(reader.fieldnames or []), list(reader)
            rows[0]["pvrig_aa"] = "Y"
            write_tsv(inputs.v4h_pair, fields, rows, compressed=True)
            receipt = json.loads(inputs.v4h_receipt.read_text())
            receipt["output_hashes"][inputs.v4h_pair.name] = mod.sha256_file(inputs.v4h_pair)
            inputs.v4h_receipt.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(mod.PairTargetError, "pair_pvrig_aa"):
                inputs.build(root / "output")
            self.assertFalse((root / "output").exists())

    def test_sealed_or_failed_seed_imputation_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = SyntheticInputs(root)
            receipt = json.loads(inputs.v4d_receipt.read_text())
            receipt["counts"]["zero_imputed_failed_seeds"] = 1
            inputs.v4d_receipt.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(mod.PairTargetError, "failed_seed_zero_imputation"):
                inputs.build(root / "output")


if __name__ == "__main__":
    unittest.main()
