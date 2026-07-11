#!/usr/bin/env python3
"""Focused validator tests for P3 structure-fusion guardrails."""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_p3_late_fusion import EVIDENCE_BOUNDARY, EXTERNAL_PRIOR_BOUNDARY  # noqa: E402
from validate_p3_structure_fusion import leakage_expected, validate  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    phase2 = root / "phase2.csv"
    external = root / "external.csv"
    pose = root / "pose.csv"
    output = root / "output.csv"
    pose_file = root / "pose_a.pdb"
    pose_file.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n", encoding="utf-8")
    write_csv(
        phase2,
        [
            {"candidate_id": "a", "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE"},
            {"candidate_id": "b", "leakage_label": "NEAR_KNOWN_POSITIVE_LEAKAGE"},
        ],
    )
    write_csv(
        external,
        [
            {"candidate_id": "a", "external_prior_evidence_boundary": EXTERNAL_PRIOR_BOUNDARY},
            {"candidate_id": "b", "external_prior_evidence_boundary": EXTERNAL_PRIOR_BOUNDARY},
        ],
    )
    write_csv(
        pose,
        [
            {
                "candidate_id": "a",
                "pose_id": "pose_a",
                "pose_path": str(pose_file),
                "pose_status": "pose_supplied",
                "qc_status": "pass",
                "pose_interface_contact_count": 5,
            }
        ],
    )
    write_csv(
        output,
        [
            {
                "candidate_id": "a",
                "p3_candidate_rank": 1,
                "p3_fused_ranking_score": 0.75,
                "p3_ai_prior_ranking_score": 0.70,
                "p3_phase2_component_ranking_score": 0.80,
                "p3_external_prior_component_ranking_score": 0.60,
                "p3_pose_geometry_ranking_score": 1.0,
                "p3_pose_available": True,
                "p3_fusion_uses_pose": True,
                "p3_missing_pose_policy": "POSE_AUGMENTED_WHEN_REAL_ROW_PRESENT",
                "p3_leakage_holdout": False,
                "p3_evidence_boundary": EVIDENCE_BOUNDARY,
                "p3_label_policy": "ranking_only_no_calibrated_probability_no_experimental_claim",
            },
            {
                "candidate_id": "b",
                "p3_candidate_rank": "",
                "p3_fused_ranking_score": "",
                "p3_ai_prior_ranking_score": "",
                "p3_phase2_component_ranking_score": "",
                "p3_external_prior_component_ranking_score": "",
                "p3_pose_geometry_ranking_score": "",
                "p3_pose_available": False,
                "p3_fusion_uses_pose": False,
                "p3_missing_pose_policy": "LEAKAGE_HOLDOUT_NOT_RANKED",
                "p3_leakage_holdout": True,
                "p3_evidence_boundary": EVIDENCE_BOUNDARY,
                "p3_label_policy": "ranking_only_no_calibrated_probability_no_experimental_claim",
            },
        ],
    )
    return output, phase2, external, pose


class P3StructureFusionValidatorTests(unittest.TestCase):
    def test_safe_leakage_role_is_not_expected_holdout(self) -> None:
        frame = pd.DataFrame(
            {
                "leakage_label": ["NO_KNOWN_POSITIVE_LEAKAGE"],
                "leakage_role": ["candidate_no_known_positive_leakage"],
            }
        )
        self.assertFalse(bool(leakage_expected(frame).iloc[0]))

    def args_for(self, output: Path, phase2: Path, external: Path, pose: Path) -> Namespace:
        return Namespace(output=output, phase2_predictions=phase2, external_priors=external, pose_manifest=pose, geometry=None, audit_json=None)

    def test_valid_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, phase2, external, pose = write_fixture(Path(tmp))
            result = validate(self.args_for(output, phase2, external, pose))
        self.assertEqual(result["status"], "PASS")

    def test_fails_when_leakage_row_gets_rank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, phase2, external, pose = write_fixture(Path(tmp))
            df = pd.read_csv(output)
            df.loc[df["candidate_id"] == "b", "p3_candidate_rank"] = 2
            df.loc[df["candidate_id"] == "b", "p3_fused_ranking_score"] = 0.99
            df.to_csv(output, index=False)
            result = validate(self.args_for(output, phase2, external, pose))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("leakage_holdouts_not_ranked", result["failed_checks"])

    def test_fails_when_boundary_is_not_ranking_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, phase2, external, pose = write_fixture(Path(tmp))
            df = pd.read_csv(output)
            df.loc[0, "p3_evidence_boundary"] = "experimental_binding_claim"
            df.to_csv(output, index=False)
            result = validate(self.args_for(output, phase2, external, pose))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("evidence_boundary_exact", result["failed_checks"])

    def test_fails_when_explicit_missing_pose_is_marked_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, phase2, external, pose = write_fixture(Path(tmp))
            df = pd.read_csv(output)
            df.loc[df["candidate_id"] == "a", "pose_path"] = ""
            df.loc[df["candidate_id"] == "a", "pose_status"] = "no_pose_supplied"
            df.loc[df["candidate_id"] == "a", "p3_pose_available"] = True
            df.loc[df["candidate_id"] == "a", "p3_fusion_uses_pose"] = True
            df.to_csv(output, index=False)
            pose_df = pd.read_csv(pose)
            pose_df.loc[pose_df["candidate_id"] == "a", "pose_path"] = ""
            pose_df.loc[pose_df["candidate_id"] == "a", "pose_status"] = "no_pose_supplied"
            pose_df.to_csv(pose, index=False)
            result = validate(self.args_for(output, phase2, external, pose))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("missing_or_failed_geometry_is_ai_prior_only", result["failed_checks"])

    def test_fails_when_failed_geometry_is_marked_pose_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, phase2, external, pose = write_fixture(Path(tmp))
            geometry = Path(tmp) / "geometry.csv"
            pose_df = pd.read_csv(pose)
            write_csv(
                geometry,
                [
                    {
                        "candidate_id": "a",
                        "pose_id": "pose_a",
                        "pose_path": pose_df.loc[0, "pose_path"],
                        "pose_status": "pose_supplied",
                        "qc_status": "pass",
                        "geometry_status": "pose_parse_failed",
                    }
                ],
            )
            result = validate(Namespace(output=output, phase2_predictions=phase2, external_priors=external, pose_manifest=pose, geometry=geometry, audit_json=None))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("missing_or_failed_geometry_is_ai_prior_only", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
