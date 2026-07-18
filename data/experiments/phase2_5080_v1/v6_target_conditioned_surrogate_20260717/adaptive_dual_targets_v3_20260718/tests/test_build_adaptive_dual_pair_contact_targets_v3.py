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
import build_adaptive_dual_pair_contact_targets_v3 as mod  # noqa: E402


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]], compressed: bool = False) -> None:
    handle = gzip.open(path, "wt", encoding="utf-8", newline="") if compressed else path.open("w", encoding="utf-8", newline="")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class Inputs:
    def __init__(self, root: Path) -> None:
        sequence = "ACDE"; digest = hashlib.sha256(sequence.encode()).hexdigest()
        self.training = root / "training.tsv"
        write_tsv(self.training, ["candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "teacher_source"], [
            {"candidate_id": "D", "sequence": sequence, "sequence_sha256": digest, "parent_framework_cluster": "PD", "teacher_source": mod.V4D},
            {"candidate_id": "H", "sequence": sequence, "sequence_sha256": digest, "parent_framework_cluster": "PH", "teacher_source": mod.V4H},
        ])
        self.target_cache = root / "target.npz"
        np.savez_compressed(self.target_cache, **{
            "8x6b_uniprot_position": np.asarray([41, 42]),
            "9e6y_uniprot_position": np.asarray([41, 42]),
        })
        self.target_manifest = root / "target.tsv"
        write_tsv(self.target_manifest, ["receptor", "sequence", "node_count"], [
            {"receptor": "8x6b", "sequence": "FG", "node_count": 2},
            {"receptor": "9e6y", "sequence": "FG", "node_count": 2},
        ])
        self.target_receipt = root / "target.json"
        self.target_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_residue_v2_fixed_target_graphs",
            "status": "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
            "outputs": {self.target_cache.name: mod.sha256_file(self.target_cache), self.target_manifest.name: mod.sha256_file(self.target_manifest)},
            "sealed_boundary": {"teacher_source_is_model_feature": False, "candidate_docking_pose_files_opened": 0},
        }))
        self.v4d_pair = root / "v4d.tsv.gz"
        v4d_rows = []
        for receptor in mod.RECEPTORS:
            values = np.asarray([0.1, 0.3, 0.5]); variance = float(values.var())
            v4d_rows.append({
                "schema_version": "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2", "teacher_state": "VALID_DUAL_MULTI_SEED_CONTACT",
                "candidate_id": "D", "sequence_sha256": digest, "parent_framework_cluster": "PD", "receptor": receptor,
                "vhh_sequence_index": 1, "vhh_aa": "A", "pvrig_uniprot_position": 41, "pvrig_aa": "F",
                "contact_target_mean": values.mean(), "contact_target_variance": variance,
                "contact_uncertainty_weight": 1 / (1 + 4 * variance), "supporting_seed_count": 3,
                "observed_seed_count": 3, "expected_seed_count": 3, "seed_contact_values": "917:0.1;1931:0.3;3253:0.5",
            })
        write_tsv(self.v4d_pair, list(v4d_rows[0]), v4d_rows, True)
        self.v4d_receipt = root / "v4d.json"
        self.v4d_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2_receipt", "status": "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2",
            "counts": {"teacher_candidates": 1, "pair_rows": 2, "zero_imputed_failed_seeds": 0, "partial_seed_candidates": 0},
            "outputs": {"pair_sha256": mod.sha256_file(self.v4d_pair)},
            "sealed_boundary": {"sealed_pose_files_opened": 0, "sealed_result_files_opened": 0, "shared_job_results_tsv_opened": 0, "shared_pose_scores_tsv_opened": 0},
            "source": {"source_mutation_operations": 0},
        }))
        self.v4h_pair = root / "v4h.tsv.gz"
        hrows = []
        for receptor in mod.RECEPTORS:
            values = np.asarray([0.2, 0.6]); variance = float(values.var())
            hrows.append({
                "schema_version": "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2", "teacher_state": "VALID_DUAL_2_SEED_CONTACT",
                "candidate_id": "H", "sequence_sha256": digest, "parent_framework_cluster": "PH", "receptor": receptor,
                "observed_seed_count": 2, "observed_seed_ids": "917;1931", "vhh_sequence_index": 2, "vhh_aa": "C",
                "pvrig_uniprot_position": 42, "pvrig_aa": "G", "contact_target_mean": values.mean(),
                "contact_target_variance": variance, "contact_uncertainty_weight": 1 / (1 + 4 * variance),
                "supporting_seed_count": 2, "seed_contact_values": "917:0.2;1931:0.6",
            })
        write_tsv(self.v4h_pair, list(hrows[0]), hrows, True)
        self.v4h_candidates = root / "v4h_candidates.tsv.gz"
        crows = [{
            "schema_version": "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2", "teacher_state": "VALID_DUAL_2_SEED_CONTACT",
            "candidate_id": "H", "sequence_sha256": digest, "parent_framework_cluster": "PH", "docking_evidence_tier": "B",
            "paired_seed_ids": "917,1931", "paired_seed_count": 2,
        }]
        crows.extend({
            "schema_version": "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2", "teacher_state": "TECHNICAL_INCOMPLETE_NA",
            "candidate_id": f"NA{i:02d}", "sequence_sha256": digest, "parent_framework_cluster": "PNA", "docking_evidence_tier": "TECHNICAL_INCOMPLETE",
            "paired_seed_ids": "", "paired_seed_count": "",
        } for i in range(39))
        write_tsv(self.v4h_candidates, list(crows[0]), crows, True)
        self.v4h_receipt = root / "v4h.json"
        self._write_v4h_receipt()

    def _write_v4h_receipt(self) -> None:
        self.v4h_receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2_receipt", "status": "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION",
            "candidate_rows": 40, "valid_candidate_rows": 1, "technical_incomplete_candidate_rows": 39,
            "pair_rows": 2, "source_mutation_operations": 0,
            "output_hashes": {
                self.v4h_pair.name: mod.sha256_file(self.v4h_pair),
                "v4h_adaptive_residue_pair_contact_teacher.tsv.gz": mod.sha256_file(self.v4h_pair),
                "v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz": "2" * 64,
                self.v4h_candidates.name: mod.sha256_file(self.v4h_candidates),
            },
        }))

    def build(self, output: Path):
        return mod.build_targets(
            training_tsv=self.training, v4d_pair_tsv_gz=self.v4d_pair, v4d_receipt=self.v4d_receipt,
            v4h_pair_tsv_gz=self.v4h_pair, v4h_candidate_tsv_gz=self.v4h_candidates, v4h_receipt=self.v4h_receipt,
            target_cache_npz=self.target_cache, target_manifest_tsv=self.target_manifest, target_receipt=self.target_receipt,
            output_dir=output, expected_source_counts={mod.V4D: 1, mod.V4H: 1}, expected_parent_counts={mod.V4D: 1, mod.V4H: 1},
        )


class Tests(unittest.TestCase):
    def test_adaptive_values_and_candidate_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = Inputs(root); receipt = inputs.build(root / "out")
            self.assertEqual(receipt["status"], mod.STATUS)
            self.assertEqual(receipt["counts"]["pair_rows"], 4)
            self.assertEqual(receipt["counts"]["zero_nonzero_pair_groups"], 0)
            self.assertEqual(receipt["counts"]["v4h_technical_na_candidates"], 39)
            with gzip.open(root / "out" / mod.OUTPUT_NAME, "rt") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            row = next(item for item in rows if item["candidate_id"] == "H")
            self.assertAlmostEqual(float(row["contact_target"]), 0.4)
            self.assertAlmostEqual(float(row["contact_variance"]), 0.04)
            self.assertEqual(row["observed_seed_count"], "2")
            self.assertEqual(row["expected_seed_count"], "2")

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = Inputs(root)
            first = inputs.build(root / "one"); second = inputs.build(root / "two")
            self.assertEqual(first["outputs"], second["outputs"])

    def test_wrong_target_aa_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = Inputs(root)
            with gzip.open(inputs.v4h_pair, "rt") as handle:
                reader = csv.DictReader(handle, delimiter="\t"); fields = list(reader.fieldnames or []); rows = list(reader)
            rows[0]["pvrig_aa"] = "Y"; write_tsv(inputs.v4h_pair, fields, rows, True); inputs._write_v4h_receipt()
            with self.assertRaisesRegex(mod.PairTargetError, "pair_pvrig_aa"):
                inputs.build(root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
