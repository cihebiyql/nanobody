#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


def load(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREPARE = load("prepare_pvrig_formal_candidate_meanpool_inputs")
SCORE = load("score_pvrig_formal_candidates_meanpool")


class PVRIGFormalCandidateMeanpoolTest(unittest.TestCase):
    def test_prepare_keeps_eligible_and_adds_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence = "QVQL" + "A" * 96
            frame = pd.DataFrame(
                [
                    {"candidate_id": "a", "vhh_sequence": sequence, "sequence_sha256": PREPARE.sha256_text(sequence), "fast_gate_tier": "FORMAL_ELIGIBLE"},
                    {"candidate_id": "b", "vhh_sequence": "C" * 100, "sequence_sha256": PREPARE.sha256_text("C" * 100), "fast_gate_tier": "HARD_FAIL"},
                ]
            )
            frame.to_csv(root / "input.csv", index=False)
            (root / "target.fasta").write_text(">pvrig\nMSTES\n", encoding="utf-8")
            audit = PREPARE.prepare(root / "input.csv", root / "target.fasta", root / "manifest.csv")
            output = pd.read_csv(root / "manifest.csv")
            self.assertEqual(audit["candidate_count"], 1)
            self.assertEqual(set(output["roles"]), {"vhh", "antigen"})

    def test_qc_score_penalizes_reserve_and_review_flags(self) -> None:
        frame = pd.DataFrame(
            {
                "fast_gate_tier": ["FORMAL_ELIGIBLE", "RESERVE_REVIEW"],
                "review_flags": ["", "a;b"],
                "max_positive_cdr_identity": [10.0, 70.0],
            }
        )
        values = SCORE.cheap_qc_score(frame)
        self.assertGreater(values.iloc[0], values.iloc[1])
        self.assertTrue(values.between(0.0, 1.0).all())

    def test_rank_disagreement_is_zero_for_identical_ordering(self) -> None:
        values = np.asarray([0.1, 0.9, 0.5])
        disagreement = SCORE.rank_disagreement({1: values, 2: values + 2.0, 3: values * 3.0})
        np.testing.assert_allclose(disagreement, 0.0)


if __name__ == "__main__":
    unittest.main()
