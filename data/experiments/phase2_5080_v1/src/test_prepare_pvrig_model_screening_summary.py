from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_pvrig_model_screening_summary import CLAIM_BOUNDARY, DEFAULT_INPUT, map_candidate_ids, prepare_summary


class PreparePvrigModelScreeningSummaryTests(unittest.TestCase):
    def test_real_v24_ensemble_becomes_bounded_nonprobability_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "summary.csv"
            output = prepare_summary(DEFAULT_INPUT, output_path)
            self.assertEqual(len(output), 50)
            self.assertEqual(output["candidate_id"].nunique(), 50)
            self.assertTrue(output["binder_score"].between(0, 1).all())
            self.assertEqual(output["model_screen_rank"].min(), 1)
            self.assertEqual(set(output["claim_boundary"]), {CLAIM_BOUNDARY})
            self.assertTrue(output["claim_boundary"].str.contains("not_binding_or_blocker_probability").all())
            written = pd.read_csv(output_path)
            self.assertEqual(list(written["candidate_id"]), list(output["candidate_id"]))

    def test_duplicate_candidate_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "scores.csv"
            pd.DataFrame(
                {
                    "candidate_id": ["same", "same"],
                    "model_screen_score": [0.9, 0.8],
                }
            ).to_csv(source, index=False)
            with self.assertRaisesRegex(ValueError, "unique"):
                prepare_summary(source, root / "out.csv")

    def test_non_numeric_scores_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "scores.csv"
            pd.DataFrame(
                {
                    "candidate_id": ["a", "b"],
                    "model_screen_score": ["high", "low"],
                }
            ).to_csv(source, index=False)
            with self.assertRaisesRegex(ValueError, "finite numeric"):
                prepare_summary(source, root / "out.csv")

    def test_blinded_id_map_keeps_only_mapped_ids_without_original_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = prepare_summary(DEFAULT_INPUT, root / "summary.csv")
            selected = summary.head(2)
            mapping = pd.DataFrame(
                {
                    "candidate_id": selected["candidate_id"],
                    "assay_sample_id": ["BLIND-001", "BLIND-002"],
                }
            )
            map_path = root / "map.csv"
            mapping.to_csv(map_path, index=False)
            blinded = map_candidate_ids(
                summary,
                map_path,
                source_column="candidate_id",
                target_column="assay_sample_id",
            )
            self.assertEqual(set(blinded["candidate_id"]), {"BLIND-001", "BLIND-002"})
            self.assertFalse(set(selected["candidate_id"]) & set(blinded["candidate_id"]))
            self.assertEqual(set(blinded["blinding_status"]), {"BLINDED_ID_ONLY"})


if __name__ == "__main__":
    unittest.main()
