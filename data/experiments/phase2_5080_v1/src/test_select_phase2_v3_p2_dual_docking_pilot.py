#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("select_phase2_v3_p2_dual_docking_pilot.py")
SPEC = importlib.util.spec_from_file_location("select_phase2_v3_p2_dual_docking_pilot", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SelectPhase2V3P2DualDockingPilotTest(unittest.TestCase):
    def calibration_rows(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        manifest: list[dict[str, str]] = []
        summary: list[dict[str, str]] = []
        positive_counts = {"20": 2, "30": 2, "38": 1, "39": 3, "151": 3}
        control_counts = {"20": 9, "30": 8, "38": 4, "39": 8}
        index = 0
        for family, count in positive_counts.items():
            for _ in range(count):
                index += 1
                candidate_id = f"positive_{family}_{index}"
                manifest.append(
                    {
                        "candidate_id": candidate_id,
                        "family": family,
                        "calibration_role": "known_positive_calibration_only",
                        "sequence": "Q" * 100 + f"P{index}",
                        "sequence_sha256": f"positive_sha_{index}",
                        "split": "calibration_only",
                        "parent_framework_cluster": f"positive_family_{family}",
                    }
                )
                summary.append(
                    {
                        "candidate_id": candidate_id,
                        "provisional_stable_geometry_tier": "G2",
                        "teacher_relevance_mean": "3.0",
                    }
                )
        for family, count in control_counts.items():
            for local in range(count):
                index += 1
                candidate_id = f"control_{family}_{local}"
                manifest.append(
                    {
                        "candidate_id": candidate_id,
                        "family": family,
                        "calibration_role": "known_positive_derived_mutant_calibration_only",
                        "sequence": "Q" * 100 + f"C{index}",
                        "sequence_sha256": f"control_sha_{index}",
                        "split": "calibration_only",
                        "parent_framework_cluster": f"positive_family_{family}",
                    }
                )
                summary.append(
                    {
                        "candidate_id": candidate_id,
                        "provisional_stable_geometry_tier": ("G5", "G3", "G2")[local % 3],
                        "teacher_relevance_mean": str(1.0 + local / 10),
                    }
                )
        return manifest, summary

    def teacher_rows(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        manifest: list[dict[str, str]] = []
        summary: list[dict[str, str]] = []
        index = 0
        for tier in ("G1", "G2", "G3", "G5"):
            for local in range(8):
                index += 1
                candidate_id = f"teacher_{tier}_{local}"
                manifest.append(
                    {
                        "candidate_id": candidate_id,
                        "vhh_sequence": "Q" * 100 + f"T{index}",
                        "sequence_sha256": f"teacher_sha_{index}",
                        "parent_framework_cluster": f"parent_{index:02d}",
                        "formal_split": ("train", "dev", "test")[index % 3],
                        "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[index % 3],
                        "design_mode": ("H3", "H1H3")[index % 2],
                    }
                )
                summary.append(
                    {
                        "candidate_id": candidate_id,
                        "provisional_stable_geometry_tier": tier,
                        "teacher_relevance_mean": str(MOD.TIER_ORDER[tier]),
                    }
                )
        return manifest, summary

    def test_frozen_cohorts_and_replicates(self) -> None:
        calibration_manifest, calibration_summary = self.calibration_rows()
        teacher_manifest, teacher_summary = self.teacher_rows()
        positives, controls = MOD.select_calibration(calibration_manifest, calibration_summary)
        teacher = MOD.select_teacher500(teacher_manifest, teacher_summary)
        replicates = MOD.replicate_ids(positives, controls, teacher)
        self.assertEqual(len(positives), 11)
        self.assertEqual(len(controls), 21)
        self.assertEqual(len(teacher), 32)
        self.assertEqual(len({row["parent_framework_cluster"] for row in teacher}), 32)
        self.assertEqual(len(replicates), 16)

    def test_end_to_end_outputs_are_deterministic(self) -> None:
        calibration_manifest, calibration_summary = self.calibration_rows()
        teacher_manifest, teacher_summary = self.teacher_rows()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "calibration_manifest": root / "calibration_manifest.csv",
                "calibration_summary": root / "calibration_summary.csv",
                "teacher500_manifest": root / "teacher_manifest.csv",
                "teacher500_summary": root / "teacher_summary.csv",
                "output": root / "pilot.csv",
                "fasta": root / "pilot.fasta",
                "audit": root / "audit.json",
            }
            write_csv(paths["calibration_manifest"], calibration_manifest)
            write_csv(paths["calibration_summary"], calibration_summary)
            write_csv(paths["teacher500_manifest"], teacher_manifest)
            write_csv(paths["teacher500_summary"], teacher_summary)
            args = argparse.Namespace(**{key: str(value) for key, value in paths.items()})
            first = MOD.build(args)
            first_manifest = paths["output"].read_bytes()
            second = MOD.build(args)
            self.assertEqual(first["candidate_count"], 64)
            self.assertEqual(first["unique_sequence_count"], 64)
            self.assertEqual(first["replicate_seed_candidate_count"], 16)
            self.assertEqual(first_manifest, paths["output"].read_bytes())
            self.assertEqual(first["output_sha256"], second["output_sha256"])


if __name__ == "__main__":
    unittest.main()
