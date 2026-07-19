#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("noise", ROOT / "build_repeat_seed_noise_diagnostic.py")
assert spec and spec.loader
noise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noise)
extract_spec = importlib.util.spec_from_file_location("extract", ROOT / "extract_open_repeat_seed_scores.py")
assert extract_spec and extract_spec.loader
extract = importlib.util.module_from_spec(extract_spec)
extract_spec.loader.exec_module(extract)


class NoiseTests(unittest.TestCase):
    def test_spearman_and_tie_ranks(self):
        x = np.asarray([1.0, 2.0, 2.0, 4.0])
        self.assertTrue(np.allclose(noise.average_ranks(x), [1.0, 2.5, 2.5, 4.0]))
        self.assertAlmostEqual(noise.spearman(x, x), 1.0)
        self.assertAlmostEqual(noise.spearman(x, -x), -1.0)

    def test_icc_perfect_and_noisy(self):
        perfect = np.asarray([[1, 1, 1], [2, 2, 2], [3, 3, 3]], dtype=float)
        self.assertAlmostEqual(noise.icc_1_1(perfect), 1.0)
        noisy = np.asarray([[1, 3], [2, 0], [3, 2]], dtype=float)
        self.assertLess(noise.icc_1_1(noisy), 1.0)

    def test_build_measurements_uses_candidate_as_unit_and_exact_min(self):
        rows = []
        for seed, r8, r9 in ((917, .7, .5), (1931, .4, .8)):
            for receptor, score in (("8x6b", r8), ("9e6y", r9)):
                rows.append({
                    "campaign": "V4H", "candidate_id": "C1", "receptor": receptor, "seed": str(seed), "score": str(score),
                    "sequence_sha256": "a" * 64, "parent_framework_cluster": "P1", "target_patch_id": "A", "design_mode": "H3",
                })
        measurements, _ = noise.build_measurements(rows)
        self.assertEqual(len(measurements), 1)
        self.assertAlmostEqual(measurements[("V4H", "C1")][917]["Rdual"], .5)
        self.assertAlmostEqual(measurements[("V4H", "C1")][1931]["Rdual"], .4)

    def test_rejects_unpaired_candidate(self):
        rows = [{
            "campaign": "V4H", "candidate_id": "C1", "receptor": "8x6b", "seed": "917", "score": ".5",
            "sequence_sha256": "a" * 64, "parent_framework_cluster": "P1", "target_patch_id": "A", "design_mode": "H3",
        }]
        with self.assertRaisesRegex(noise.DiagnosticError, "fewer_than_two_paired_seeds"):
            noise.build_measurements(rows)

    def test_bootstrap_ci_is_finite(self):
        x = np.arange(20, dtype=float)
        low, high = noise.bootstrap_spearman_ci(x, x + np.sin(x), reps=50)
        self.assertTrue(math.isfinite(low) and math.isfinite(high))
        self.assertLessEqual(low, high)

    def test_v4d_pose_utility_and_overlay_gate(self):
        row = {
            "overlay_rmsd_a": .5, "hotspot_overlap": 14, "holdout_overlap": 7,
            "total_occlusion": 500, "cdr3_occlusion": 100, "cdr3_fraction": .15,
            "vhh_pvrig_clash_residue_pairs": 0,
        }
        value = extract.v4d_pose_utility(row)
        self.assertGreater(value, 0)
        self.assertLessEqual(value, 1)
        row["overlay_rmsd_a"] = 1.01
        with self.assertRaisesRegex(extract.ExtractionError, "native_overlay_rmsd"):
            extract.v4d_pose_utility(row)


if __name__ == "__main__":
    unittest.main()
