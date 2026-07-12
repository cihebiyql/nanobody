#!/usr/bin/env python3
"""Regression tests for the V3-G2 final synthesis helpers."""
from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).with_name("evaluate_phase2_v3_g2_final.py")
SPEC = importlib.util.spec_from_file_location("evaluate_phase2_v3_g2_final", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class EvaluateV3G2FinalTest(unittest.TestCase):
    def test_cluster_bootstrap_detects_consistent_improvement(self) -> None:
        frame = pd.DataFrame(
            {
                "cluster_id": [f"c{i // 2}" for i in range(40)],
                "target_id": ["a" if i < 20 else "b" for i in range(40)],
                "label": [i % 2 for i in range(40)],
            }
        )
        labels = frame["label"].to_numpy()
        candidate = np.where(labels == 1, 0.9, 0.1)
        baseline = np.linspace(0.0, 1.0, len(frame))
        result = MOD.cluster_bootstrap_macro_delta(frame, candidate, baseline, 100, 7)
        self.assertGreater(result["observed_delta"], 0.0)
        self.assertGreater(result["ci95_lower"], 0.0)
        self.assertEqual(result["cluster_count"], 20)

    def test_completed_seed_discovery_rejects_duplicate_complete_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("one_seed83", "two_seed83"):
                run = root / name
                run.mkdir()
                (run / "summary.json").write_text(
                    json.dumps({"status": "PASS_V3_G2_TRAINING_COMPLETED", "seed": 83})
                )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                MOD.complete_seed_summaries(root, (83,))

    def test_internal_decision_requires_seed_consistency_and_bootstrap(self) -> None:
        rows = []
        for target in ("a", "b"):
            for cluster in range(12):
                label = cluster % 2
                rows.append(
                    {
                        "sample_id": f"{target}_{cluster}",
                        "target_id": target,
                        "cluster_id": f"{target}_c{cluster}",
                        "label": label,
                        "baseline_score": 0.5,
                        "ensemble_score": 0.9 if label else 0.1,
                        "ensemble_swap_score": 0.2,
                        "score_seed_83": 0.9 if label else 0.1,
                        "score_seed_89": 0.88 if label else 0.12,
                        "score_seed_97": 0.87 if label else 0.13,
                        "swap_valid_seed_83": True,
                        "swap_valid_seed_89": True,
                        "swap_valid_seed_97": True,
                    }
                )
        frame = pd.DataFrame(rows)
        metadata = {
            seed: {"test_observed_contrast": {"observed_target_contrast_win_rate": 0.75}}
            for seed in (83, 89, 97)
        }
        baseline = {"strongest_baseline_selected_on_dev": "v3_full"}
        result = MOD.internal_decision(frame, metadata, baseline, bootstrap_replicates=100)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["seed_count_exceeding_baseline"], 3)


if __name__ == "__main__":
    unittest.main()
