#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "audit_real1507_rank_eligibility_v1_1", ROOT / "audit_real1507_rank_eligibility_v1_1.py"
)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)

V6_ROOT = ROOT.parent.parent
TEACHER = (
    V6_ROOT / "v2_4_fs_stack_prototype_v1_20260718" / "data_contract" / "materialized_v1"
    / "v6_supervised1507_v2_4.tsv"
)
INNER = (
    V6_ROOT / "v2_4_fs_stack_prototype_v1_20260718" / "split_contract" / "prepared"
    / "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4"
    / "inner_nested_oof_manifest.tsv"
)
BINDING = V6_ROOT / "v2_6_noise_tolerance_binding_v1_20260718" / "V2_6_DELTA_NOISE_BINDING.json"


def teacher_rows():
    with TEACHER.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Real1507AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = audit.build_audit(TEACHER, INNER)

    def test_real_counts_pair_policy_and_inner_feasibility(self):
        payload = self.payload
        self.assertEqual(payload["status"], "PASS_REAL1507_EXACT_MIN_V4D_ONLY_RANK_POLICY_FEASIBLE")
        self.assertEqual(payload["teacher"]["candidate_count"], 1507)
        self.assertEqual(payload["teacher"]["parent_count"], 31)
        self.assertEqual(payload["teacher"]["rank_eligible_candidate_count"], 226)
        self.assertEqual(payload["teacher"]["rank_ineligible_candidate_count"], 1281)
        seed_strata = {
            (row["teacher_source"], row["successful_seed_count_8X6B"], row["successful_seed_count_9E6Y"]):
            row["candidate_count"]
            for row in payload["teacher"]["source_successful_seed_count_strata"]
        }
        self.assertEqual(seed_strata[("V4D_OPEN_MULTI_SEED", 3, 3)], 225)
        self.assertEqual(seed_strata[("V4D_OPEN_MULTI_SEED", 2, 3)], 1)
        pair = payload["global_rank_pair_audit"]
        self.assertEqual(pair["rank_parent_count"], 20)
        self.assertEqual(pair["same_parent_unordered_pair_count"], 1230)
        self.assertEqual(pair["eligible_pair_count"], 824)
        self.assertEqual(pair["below_noise_discard_count"], 406)
        inner = payload["inner_train_partition_audit"]
        self.assertEqual(inner["partition_count"], 25)
        self.assertEqual(inner["minimum_rank_eligible_parent_count"], 10)
        self.assertGreaterEqual(inner["minimum_rank_eligible_pair_count"], 1)
        self.assertEqual(payload["v4_f_or_test32_results_accessed"], 0)

    def test_softmin_diagnostic_proves_nonidentity(self):
        diagnostic = self.payload["softmin_exact_min_diagnostic"]
        bias = diagnostic["normalized_softmin_minus_exact_min"]
        self.assertGreater(bias["mean"], 0.0)
        self.assertLessEqual(bias["maximum"], audit.core.SOFTMIN_TAU * __import__("math").log(2.0) + 1e-12)
        thresholds = {row["threshold"]: row for row in diagnostic["within_parent_sign_flip_by_exact_delta_threshold"]}
        self.assertGreater(thresholds[0.0]["flip_count"], 0)
        self.assertEqual(thresholds[audit.core.FROZEN_DELTA_NOISE]["flip_count"], 0)

    def test_source_tier_and_exact_min_mutations_fail_closed(self):
        rows = teacher_rows()
        wrong_tier = copy.deepcopy(rows)
        v4d_index = next(i for i, row in enumerate(wrong_tier) if row["teacher_source"] == "V4D_OPEN_MULTI_SEED")
        wrong_tier[v4d_index]["development_reliability_tier"] = "B"
        with self.assertRaisesRegex(audit.AuditError, "v4d_source_tier_provenance_invalid"):
            audit.validate_teacher_rows(wrong_tier)
        wrong_dual = copy.deepcopy(rows)
        wrong_dual[0]["R_dual_min"] = str(float(wrong_dual[0]["R_dual_min"]) + 0.001)
        with self.assertRaisesRegex(audit.AuditError, "teacher_exact_min_mismatch"):
            audit.validate_teacher_rows(wrong_dual)

    def test_input_hash_mutation_fails_before_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "teacher.tsv"
            bad.write_bytes(TEACHER.read_bytes() + b"\n")
            with self.assertRaisesRegex(audit.AuditError, "input_sha256_mismatch"):
                audit.build_audit(bad, INNER)

    def test_real_inner_train_partition_builds_v4d_only_exact_cache(self):
        rows = teacher_rows()
        row_index = {row["candidate_id"]: row for row in rows}
        with INNER.open("r", encoding="utf-8", newline="") as handle:
            manifest = list(csv.DictReader(handle, delimiter="\t"))
        train_ids = {
            row["candidate_id"] for row in manifest
            if row["outer_fold"] == "0" and row["inner_fold"] == "0" and row["candidate_role"] == "train"
        }
        labels = [audit._candidate_label(row_index[candidate_id]) for candidate_id in sorted(train_ids)]
        core = audit.core
        cache = core.build_parent_pair_epoch_cache(
            labels,
            base_seed=1931,
            outer_fold=0,
            inner_fold=0,
            epoch=0,
            scalar_optimizer_steps=2,
            binding_receipt=core.verify_frozen_delta_noise_binding(BINDING),
            expected_training_split_sha256=core.compute_training_split_sha256(labels, 0, 0),
            expected_label_sha256=core.compute_label_sha256(labels),
        )
        self.assertEqual(cache.rank_eligible_candidate_count, 155)
        self.assertEqual(cache.rank_ineligible_candidate_count, 930)
        self.assertEqual(len(cache.records), 16)
        self.assertTrue(all(record.teacher_source == "V4D_OPEN_MULTI_SEED" for record in cache.records))
        self.assertTrue(all(record.rank_eligibility_policy_id == core.RANK_ELIGIBILITY_POLICY_ID for record in cache.records))


if __name__ == "__main__":
    unittest.main(verbosity=2)
