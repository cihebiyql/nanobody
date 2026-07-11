#!/usr/bin/env python3
from __future__ import annotations

import math
import unittest

import pandas as pd

from summarize_phase2_v2_5_formal import (
    fast_mean_seed_delta_statistic,
    sha256_text,
    stable_sample_id,
    validate_label_binding_frames,
    validate_required_prediction_scores,
)


class Phase2V25FormalSummaryTests(unittest.TestCase):
    def fixture(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        vhh = "AAAA"
        target = "TTTT"
        vhh_sha = sha256_text(vhh)
        target_sha = sha256_text(target)
        sample_id = stable_sample_id(vhh_sha, target_sha)
        blinded = pd.DataFrame(
            [
                {
                    "sample_id": sample_id,
                    "sequence_sha256": vhh_sha,
                    "target_sequence_sha256": target_sha,
                    "vhh_sequence": vhh,
                    "target_sequence": target,
                    "split_group_id": "cc1",
                    "ranking_group_id": "exact_target_" + target_sha,
                    "sealed_status": "SEALED_LABELS",
                }
            ]
        )
        labels = pd.DataFrame(
            [
                {
                    "sample_id": sample_id,
                    "label_value": 1e-9,
                    "affinity_kd_m": 1e-9,
                    "affinity_score": 9.0,
                    "label_unit": "M",
                    "label_direction": "lower_is_better",
                    "sealed_status": "SEALED_LABELS",
                }
            ]
        )
        rebuilt = pd.DataFrame(
            [
                {
                    "sample_id": sample_id,
                    "sequence_sha256": vhh_sha,
                    "target_sequence_sha256": target_sha,
                    "vhh_sequence": vhh,
                    "target_sequence": target,
                    "label_value": 1e-9,
                    "affinity_kd_m": 1e-9,
                    "affinity_score": 9.0,
                }
            ]
        )
        p1 = pd.DataFrame([{"sequence_sha256": vhh_sha, "target_sequence_sha256": target_sha, "split_group_id": "cc1"}])
        return blinded, labels, rebuilt, p1

    def test_label_binding_accepts_deterministic_source_match(self) -> None:
        result = validate_label_binding_frames(*self.fixture())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["sample_id_sequence_target_binding_pass"])
        self.assertTrue(result["source_label_regeneration_pass"])

    def test_label_binding_rejects_same_id_with_wrong_label(self) -> None:
        blinded, labels, rebuilt, p1 = self.fixture()
        labels.loc[0, "label_value"] = 2e-9
        result = validate_label_binding_frames(blinded, labels, rebuilt, p1)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("raw_source_label_mismatch", result["failures"])

    def test_fast_multi_seed_statistic_uses_group_macro_delta(self) -> None:
        frame = pd.DataFrame(
            [
                {"group_id": "g1", "label_value": 1.0, "label_direction": "higher_is_better", "base": 0.0, "s43": 1.0, "s53": 1.0, "s67": 1.0},
                {"group_id": "g1", "label_value": 0.0, "label_direction": "higher_is_better", "base": 1.0, "s43": 0.0, "s53": 0.0, "s67": 0.0},
                {"group_id": "g2", "label_value": 1.0, "label_direction": "higher_is_better", "base": 1.0, "s43": 1.0, "s53": 1.0, "s67": 1.0},
                {"group_id": "g2", "label_value": 0.0, "label_direction": "higher_is_better", "base": 0.0, "s43": 0.0, "s53": 0.0, "s67": 0.0},
            ]
        )
        # g1 delta is +1 and g2 delta is 0, so the group-macro delta is 0.5.
        observed = fast_mean_seed_delta_statistic(frame, ["s43", "s53", "s67"], "base")
        self.assertTrue(math.isclose(float(observed), 0.5))

    def test_required_prediction_coverage_rejects_missing_duplicate_and_nonfinite_scores(self) -> None:
        rows = [
            {"sample_id": sample_id, "method": method, "formal_eligible": "true", "ranking_score": score}
            for sample_id, score in (("a", 0.1), ("b", 0.2))
            for method in ("shallow_head", "baseline")
        ]
        complete = pd.DataFrame(rows)
        validate_required_prediction_scores(complete, {"a", "b"}, {"shallow_head", "baseline"}, 43)

        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            validate_required_prediction_scores(
                complete[~((complete["sample_id"] == "b") & (complete["method"] == "shallow_head"))],
                {"a", "b"},
                {"shallow_head", "baseline"},
                43,
            )
        with self.assertRaisesRegex(ValueError, "duplicate required predictions"):
            validate_required_prediction_scores(pd.concat([complete, complete.iloc[[0]]]), {"a", "b"}, {"shallow_head", "baseline"}, 43)
        bad_score = complete.copy()
        bad_score.loc[(bad_score["sample_id"] == "a") & (bad_score["method"] == "baseline"), "ranking_score"] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            validate_required_prediction_scores(bad_score, {"a", "b"}, {"shallow_head", "baseline"}, 43)


if __name__ == "__main__":
    unittest.main()
