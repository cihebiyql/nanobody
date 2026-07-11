#!/usr/bin/env python3
"""Tests for the portable V2.3 multi-seed candidate ensemble."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_3_candidate_ensemble import build_ensemble  # noqa: E402


class CandidateEnsembleTests(unittest.TestCase):
    def _write(self, path: Path, seed: int, rows: list[tuple[str, int, float]]) -> None:
        pd.DataFrame(
            [
                {
                    "candidate_id": candidate_id,
                    "rank": rank,
                    "schema_version": "member_v1",
                    "phase2_v2_3_seed": seed,
                    "phase2_v2_3_pair_ranking_logit": score,
                    "phase2_v2_3_sigmoid_pair_ranking_ai_prior": score / 10.0,
                    "phase2_v2_3_contact_top20_mean_ai_prior": score / 20.0,
                    "phase2_v2_3_cdr3_contact_top20_mean_ai_prior": score / 30.0,
                    "phase2_v2_3_cdr3_contact_mean_ai_prior": score / 40.0,
                    "phase2_v2_3_combined_ranking_ai_prior": score / 10.0,
                    "phase2_v2_3_boundary_note": "ranking AI prior only; sigmoid proxy is not calibrated blocker probability",
                    "phase2_v2_combined_rank_score": 0.5,
                    "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
                }
                for candidate_id, rank, score in rows
            ]
        ).to_csv(path, index=False)

    def test_builds_mean_features_and_consensus_rank(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "seed43.csv"
            second = root / "seed53.csv"
            self._write(first, 43, [("a", 1, 4.0), ("b", 2, 2.0)])
            self._write(second, 53, [("a", 2, 2.0), ("b", 1, 5.0)])
            out = build_ensemble([first, second])
            self.assertEqual(set(out["candidate_id"]), {"a", "b"})
            self.assertTrue((out["phase2_v2_3_seed_count"] == 2).all())
            row_a = out.set_index("candidate_id").loc["a"]
            self.assertAlmostEqual(float(row_a["phase2_v2_3_pair_ranking_logit"]), 3.0)
            self.assertAlmostEqual(float(row_a["phase2_v2_3_rank_mean"]), 1.5)
            self.assertIn("phase2_v2_3_pair_ranking_logit_seed_std", out.columns)

    def test_rejects_candidate_set_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "seed43.csv"
            second = root / "seed53.csv"
            self._write(first, 43, [("a", 1, 4.0)])
            self._write(second, 53, [("b", 1, 5.0)])
            with self.assertRaisesRegex(ValueError, "Candidate set mismatch"):
                build_ensemble([first, second])


if __name__ == "__main__":
    unittest.main()
