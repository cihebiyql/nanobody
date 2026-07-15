#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_phase2_v4_c_teacher.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v4_c_teacher", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def pose(model: str, reference: str, score: float, multiplier: float = 1.0) -> dict[str, str]:
    return {
        "model": model,
        "scoring_reference": reference,
        "haddock_score": str(score),
        "air_energy": "1.0",
        "hotspot_overlap": str(12 * multiplier),
        "anchor_overlap": str(7 * multiplier),
        "holdout_overlap": str(5 * multiplier),
        "total_occlusion": str(400 * multiplier),
        "cdr3_occlusion": str(80 * multiplier),
        "cdr3_fraction": str(0.12 * multiplier),
        "vhh_pvrig_clash_residue_pairs": "0",
        "vhh_pvrl2_clash_residue_pairs": "10",
        "overlay_rmsd_a": "0.2",
    }


class PrepareV4CTeacherTest(unittest.TestCase):
    def test_pose_utility_is_continuous_and_bounded(self) -> None:
        low = MOD.native_pose_utility(pose("m1", "8x6b", -10.0, 0.5))
        high = MOD.native_pose_utility(pose("m1", "8x6b", -10.0, 1.5))
        self.assertGreater(high, low)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_pose_utility_penalizes_pvrig_clash_and_rejects_bad_overlay(self) -> None:
        clean = pose("m1", "8x6b", -10.0, 1.0)
        clashing = dict(clean, vhh_pvrig_clash_residue_pairs="20")
        self.assertLess(MOD.native_pose_utility(clashing), MOD.native_pose_utility(clean))
        with self.assertRaises(MOD.TeacherBuildError):
            MOD.native_pose_utility(dict(clean, overlay_rmsd_a="1.01"))

    def test_candidate_uses_median_seed_and_dual_min(self) -> None:
        split = {
            "candidate_id": "c1",
            "sequence_sha256": "sha",
            "sequence": "Q" * 110,
            "cdr1": "AAA",
            "cdr2": "BBB",
            "cdr3": "CCC",
            "phase": "P1",
            "scaffold_id": "s1",
            "h3_regime": "L",
            "near_cdr3_family_id": "f1",
            "selection_bucket": "b1",
            "model_split": "OPEN_DEVELOPMENT",
        }
        summaries = []
        for conf, values in (("8x6b", (0.2, 0.4, 0.6)), ("9e6y", (0.1, 0.3, 0.5))):
            for index, value in enumerate(values):
                summaries.append(
                    {
                        "dock_conformation": conf,
                        "job_utility": value,
                        "native_cross_support_agreement": 0.8,
                        "model_pair_consensus_fraction": 0.75,
                        "model_strict_a_fraction": 0.5,
                        "model_count_reliability": 1.0,
                        "agreement_reliability": 0.9,
                        "hotspot_overlap": 12.0,
                        "anchor_overlap": 7.0,
                        "holdout_overlap": 5.0,
                        "total_occlusion": 400.0,
                        "cdr3_occlusion": 80.0,
                        "cdr3_fraction": 0.12,
                        "vhh_pvrig_clash_residue_pairs": 0.0,
                        "vhh_pvrl2_clash_residue_pairs": 10.0,
                        "overlay_rmsd_a": 0.2,
                    }
                )
        row = MOD.build_candidate_teacher(split, summaries)
        self.assertAlmostEqual(row["R_8X6B"], 0.4)
        self.assertAlmostEqual(row["R_9E6Y"], 0.3)
        self.assertAlmostEqual(row["R_dual_min"], 0.3)
        self.assertAlmostEqual(row["R_dual_gap"], 0.1)

    def test_job_summary_requires_complete_model_pairs(self) -> None:
        rows = []
        for index in range(4):
            for reference in MOD.CONFORMATIONS:
                rows.append(pose(f"m{index}", reference, -100 + index))
        result = {
            "seed": "917",
            "model_native_cross_support_agreement_fraction": "0.8",
            "model_pair_consensus_fraction": "0.75",
            "model_strict_a_fraction": "0.5",
        }
        summary = MOD.job_summary("j1", "8x6b", rows, result)
        self.assertEqual(summary["complete_model_count"], 4)
        self.assertGreater(summary["job_utility"], 0.0)

    def test_open_selection_never_returns_challenge_rows(self) -> None:
        rows = [
            {"candidate_id": f"o{index}", "model_split": "OPEN_DEVELOPMENT"}
            for index in range(96)
        ] + [
            {"candidate_id": f"t{index}", "model_split": "RETROSPECTIVE_GROUPED_CHALLENGE"}
            for index in range(32)
        ]
        selected = MOD.select_open_split(rows)
        self.assertEqual(len(selected), 96)
        self.assertTrue(all(row["candidate_id"].startswith("o") for row in selected))

    def test_spoofed_evaluator_is_rejected(self) -> None:
        with self.assertRaises(MOD.TeacherBuildError):
            MOD.validate_evaluator(
                {
                    "status": "PASS",
                    "evidence_mode": "production_pose_backed",
                    "unlockable": False,
                    "job_count": 1050,
                    "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
                    "protocol_lock_sha256": MOD.EXPECTED_PROTOCOL_LOCK_SHA256,
                    "gates": {"all_jobs_terminal": {"status": "PASS"}},
                },
                job_results_sha256="forged",
                pose_scores_sha256="forged",
            )


if __name__ == "__main__":
    unittest.main()
