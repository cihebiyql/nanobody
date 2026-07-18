#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_v2_4_supervised1507.py")
SPEC = importlib.util.spec_from_file_location("v2_4_builder", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def seq_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class BuildV24Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        base = {
            "schema_version": "old",
            "sequence": "ACDE",
            "sequence_sha256": seq_hash("ACDE"),
            "target_patch_id": "A",
            "design_mode": "H3",
            "cdr1": "A",
            "cdr2": "C",
            "cdr3": "DE",
            "sample_weight": "1.0",
            "R_8X6B": "0.1",
            "R_9E6Y": "0.2",
            "R_dual_min": "0.1",
            "teacher_uncertainty": "0.01",
            "monomer_sha256": "m",
            "technical_reasons": "",
            "claim_boundary": "old",
            "feature": "7",
        }
        self.old = []
        for cid, source, parent, fold in [
            ("d1", "V4D_OPEN_MULTI_SEED", "P0", "0"),
            ("d2", "V4D_OPEN_MULTI_SEED", "P1", "1"),
            ("h1", "V4H_STAGE1_SEED917", "P2", "2"),
            ("h2", "V4H_STAGE1_SEED917", "P3", "3"),
            ("h3", "V4H_STAGE1_SEED917", "P4", "4"),
        ]:
            row = dict(base, candidate_id=cid, teacher_source=source, teacher_reliability="MULTI_SEED" if cid.startswith("d") else "SINGLE_SEED", parent_framework_cluster=parent, outer_fold=fold)
            self.old.append(row)
        self.adaptive = []
        for cid, tier, count, scores in [
            ("h1", "DUAL_3_SEED", 3, ("0.8", "0.7")),
            ("h2", "DUAL_2_SEED", 2, ("0.6", "0.65")),
            ("h3", "DUAL_1_SEED", 1, ("0.4", "0.3")),
        ]:
            old = next(row for row in self.old if row["candidate_id"] == cid)
            ids = "917,1931,3253" if count == 3 else ("917,1931" if count == 2 else "917")
            self.adaptive.append({
                "candidate_id": cid, "sequence_sha256": old["sequence_sha256"], "parent_framework_cluster": old["parent_framework_cluster"],
                "target_patch_id": "A", "design_mode": "H3", "docking_evidence_tier": tier,
                "successful_seed_count_8X6B": str(count), "successful_seed_ids_8X6B": ids,
                "successful_seed_count_9E6Y": str(count), "successful_seed_ids_9E6Y": ids,
                "median_score_8X6B": scores[0], "median_score_9E6Y": scores[1], "R_dual_min": str(min(map(float, scores))),
                "seed_dispersion_max": "0.02", "confidence_adjusted_score": "0", "technical_reasons": "", "ranking_release": "adaptive", "claim_boundary": "x", "rank": "1",
            })
        # Decimal serialization in production is exact; normalize fixture values likewise.
        self.adaptive[0]["R_dual_min"] = "0.7"
        self.adaptive[1]["R_dual_min"] = "0.6"
        self.adaptive[2]["R_dual_min"] = "0.3"
        incomplete = dict(self.adaptive[0], candidate_id="bad", docking_evidence_tier="TECHNICAL_INCOMPLETE", technical_reasons="failed")
        self.adaptive.append(incomplete)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def contract(self) -> dict:
        return {
            "claim_boundary": "computational only",
            "inputs": {"adaptive_receipt": {"required_status": "AR"}, "adaptive_package_receipt": {"required_status": "APR"}, "v4d_audit": {"required_status": "VA"}},
            "expected": {
                "rows": 5,
                "teacher_source_counts": {"V4D_OPEN_MULTI_SEED": 2, "V4H_ADAPTIVE_SEED_RANKING": 3},
                "parent_cluster_count": 5, "v4d_parent_cluster_count": 2, "v4h_parent_cluster_count": 3,
                "v4h_adaptive_tier_counts": {"DUAL_3_SEED": 1, "DUAL_2_SEED": 1, "DUAL_1_SEED": 1, "TECHNICAL_INCOMPLETE": 1},
                "development_reliability_tier_counts": {"A": 3, "B": 1, "C": 1}, "outer_fold_count": 5,
                "expected_seed_ids": [917, 1931, 3253],
            },
            "source_labels": {"v4d_old": "V4D_OPEN_MULTI_SEED", "v4h_old": "V4H_STAGE1_SEED917", "v4h_new": "V4H_ADAPTIVE_SEED_RANKING"},
            "development_reliability": {"tier_mapping": {"V4D_MULTI_SEED": "A", "DUAL_3_SEED": "A", "DUAL_2_SEED": "B", "DUAL_1_SEED": "C"}, "fixed_weights": {"A": "1.0", "B": "0.8", "C": "0.65"}},
        }

    def build(self, adaptive=None, old=None):
        old = self.old if old is None else old
        adaptive = self.adaptive if adaptive is None else adaptive
        fields = list(old[0])
        return MOD.build_rows(
            self.contract(), fields, old, adaptive,
            {"status": "AR"}, {"status": "APR"},
            {"expected_partial_candidate": {"candidate_id": "d1", "observed_seeds_8x6b": [917, 1931], "observed_seeds_9e6y": [917, 1931, 3253]}},
            {"status": "VA", "counts": {"teacher_candidates": 2}, "sealed_boundary": {"sealed_pose_files_opened": 0, "sealed_result_files_opened": 0}},
        )

    def test_success_updates_v4h_and_preserves_v4d(self):
        fields, rows, stats = self.build()
        by_id = {row["candidate_id"]: row for row in rows}
        self.assertEqual(by_id["h1"]["R_dual_min"], "0.7")
        self.assertEqual(by_id["h2"]["development_reliability_weight"], "0.8")
        self.assertEqual(by_id["h3"]["development_reliability_tier"], "C")
        self.assertEqual(by_id["d1"]["successful_seed_count_8X6B"], "2")
        self.assertEqual(by_id["d1"]["R_dual_min"], "0.1")
        self.assertIn("docking_evidence_tier", fields)
        self.assertEqual(stats["development_reliability_tier_counts"], {"A": 3, "B": 1, "C": 1})

    def test_exact_min_violation_fails_closed(self):
        adaptive = [dict(row) for row in self.adaptive]
        adaptive[0]["R_dual_min"] = "0.8"
        with self.assertRaisesRegex(MOD.ContractError, "exact-min"):
            self.build(adaptive=adaptive)

    def test_candidate_closure_violation_fails_closed(self):
        adaptive = [dict(row) for row in self.adaptive]
        adaptive[0]["candidate_id"] = "unknown"
        with self.assertRaisesRegex(MOD.ContractError, "closure"):
            self.build(adaptive=adaptive)

    def test_seed_count_violation_fails_closed(self):
        adaptive = [dict(row) for row in self.adaptive]
        adaptive[1]["successful_seed_count_8X6B"] = "3"
        with self.assertRaisesRegex(MOD.ContractError, "seed count"):
            self.build(adaptive=adaptive)

    def test_parent_split_violation_fails_closed(self):
        old = [dict(row) for row in self.old]
        old[1]["parent_framework_cluster"] = "P0"
        with self.assertRaises(MOD.ContractError):
            self.build(old=old)

    def test_input_hash_mismatch_fails_closed(self):
        path = self.root / "input.tsv"
        path.write_text("payload\n", encoding="utf-8")
        contract = {"inputs": {"only": {"sha256": "0" * 64}}}
        with self.assertRaisesRegex(MOD.ContractError, "input hash mismatch"):
            MOD.verify_hashes(contract, {"only": path})

    def test_sequence_hash_violation_fails_closed(self):
        old = [dict(row) for row in self.old]
        old[0]["sequence_sha256"] = "0" * 64
        with self.assertRaisesRegex(MOD.ContractError, "sequence hash"):
            self.build(old=old)


if __name__ == "__main__":
    unittest.main()
