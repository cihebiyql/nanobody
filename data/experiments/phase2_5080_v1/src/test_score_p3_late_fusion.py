#!/usr/bin/env python3
"""Synthetic tests for deterministic P3 late fusion."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_p3_late_fusion import EVIDENCE_BOUNDARY, EXTERNAL_PRIOR_BOUNDARY, FusionInputs, fuse_candidates, leakage_reason, sequence_sha256  # noqa: E402
from validate_p3_structure_fusion import validate  # noqa: E402
from argparse import Namespace


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def base_phase2_rows() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "cand_pose",
            "phase2_v2_pair_binding_probability": 0.90,
            "phase2_v2_pvrig_target_epitope_mass": 8.0,
            "phase2_v2_cdr3_hotspot_contact_mean": 0.70,
            "phase1_mvp_rank_score": 0.80,
            "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
            "phase2_v2_combined_rank_score": 0.91,
        },
        {
            "candidate_id": "cand_no_pose",
            "phase2_v2_pair_binding_probability": 0.40,
            "phase2_v2_pvrig_target_epitope_mass": 5.0,
            "phase2_v2_cdr3_hotspot_contact_mean": 0.20,
            "phase1_mvp_rank_score": 0.50,
            "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
            "phase2_v2_combined_rank_score": 0.55,
        },
        {
            "candidate_id": "cand_leakage_field",
            "phase2_v2_pair_binding_probability": 0.99,
            "phase2_v2_pvrig_target_epitope_mass": 9.0,
            "phase2_v2_cdr3_hotspot_contact_mean": 0.90,
            "phase1_mvp_rank_score": 0.95,
            "leakage_label": "NEAR_KNOWN_POSITIVE_LEAKAGE",
            "phase2_v2_combined_rank_score": 0.99,
        },
        {
            "candidate_id": "cand_exact_sha",
            "phase2_v2_pair_binding_probability": 0.10,
            "phase2_v2_pvrig_target_epitope_mass": 1.0,
            "phase2_v2_cdr3_hotspot_contact_mean": 0.10,
            "phase1_mvp_rank_score": 0.10,
            "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
            "phase2_v2_combined_rank_score": 0.10,
        },
    ]


def external_rows(control_sequence: str) -> list[dict[str, object]]:
    rows = []
    values = {
        "cand_pose": (0.9, 0.7, 0.8, 0.20, 0.30, 0.10, 0.20, "POSESEQ"),
        "cand_no_pose": (0.3, 0.2, 0.5, 0.05, 0.10, 0.02, 0.04, "NOPSEQ"),
        "cand_leakage_field": (1.0, 1.0, 1.0, 0.50, 0.50, 0.50, 0.50, "LEAKSEQ"),
        "cand_exact_sha": (0.1, 0.1, 0.1, 0.01, 0.01, 0.01, 0.01, control_sequence),
    }
    for candidate_id, vals in values.items():
        nanoseq, nanopro, deepseq, nminus, nweighted, dminus, dweighted, seq = vals
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_sequence_sha256": sequence_sha256(seq),
                "nanobind_seq_raw_score": nanoseq,
                "nanobind_pro_raw_score": nanopro,
                "deepnano_seq_raw_score": deepseq,
                "nanobind_site_target_minus_background": nminus,
                "nanobind_site_target_weighted_mean": nweighted,
                "deepnano_site_target_minus_background": dminus,
                "deepnano_site_target_weighted_mean": dweighted,
                "external_prior_evidence_boundary": EXTERNAL_PRIOR_BOUNDARY,
            }
        )
    return rows


class P3LateFusionTests(unittest.TestCase):
    def test_explicit_no_known_positive_leakage_role_is_safe(self) -> None:
        row = pd.Series(
            {
                "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
                "leakage_role": "candidate_no_known_positive_leakage",
                "geometry_leakage_role": "candidate_no_known_positive_leakage",
            }
        )
        self.assertEqual(leakage_reason(row, []), "")

    def make_inputs(self, root: Path) -> tuple[FusionInputs, Path, Path, Path, Path]:
        phase2 = root / "phase2.csv"
        external = root / "external.csv"
        pose = root / "pose.csv"
        leakage = root / "leakage.csv"
        output = root / "out.csv"
        audit = root / "audit.json"
        pose_file = root / "cand_pose.pdb"
        pose_file.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n", encoding="utf-8")
        control_sequence = "CONTROLKNOWNPOSITIVE"
        write_csv(phase2, base_phase2_rows())
        write_csv(external, external_rows(control_sequence))
        write_csv(
            pose,
            [
                {
                    "candidate_id": "cand_pose",
                    "pose_id": "pose_001",
                    "pose_path": str(pose_file),
                    "pose_status": "pose_supplied",
                    "qc_status": "pass",
                    "pose_interface_contact_count": 25,
                    "pose_interface_confidence": 0.8,
                    "pose_geometry_quality": 0.7,
                    "pose_buried_sasa": 120.0,
                    "pose_clash_count": 1,
                }
            ],
        )
        write_csv(
            leakage,
            [
                {
                    "sample_id": "known_1",
                    "split": "pvrig_external",
                    "role": "known_positive_calibration_only",
                    "sequence": control_sequence,
                    "label_hint": "positive_control",
                    "leakage_policy": "exclude_from_training_and_new_candidate_ranking",
                }
            ],
        )
        return FusionInputs(phase2, external, output, audit, pose_manifest=pose, leakage_manifest=leakage), phase2, external, pose, output

    def test_fusion_keeps_missing_pose_ai_only_and_holds_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, phase2, external, pose, output = self.make_inputs(root)
            audit = fuse_candidates(inputs)
            self.assertEqual(audit["status"], "PASS")
            df = pd.read_csv(output)
            by_id = df.set_index("candidate_id")

            self.assertEqual(by_id.loc["cand_no_pose", "p3_missing_pose_policy"], "AI_PRIOR_ONLY")
            self.assertFalse(bool(by_id.loc["cand_no_pose", "p3_fusion_uses_pose"]))
            self.assertTrue(pd.isna(by_id.loc["cand_no_pose", "p3_pose_geometry_ranking_score"]))
            self.assertAlmostEqual(by_id.loc["cand_no_pose", "p3_fused_ranking_score"], by_id.loc["cand_no_pose", "p3_ai_prior_ranking_score"])
            self.assertEqual(by_id.loc["cand_pose", "p3_missing_pose_policy"], "POSE_AUGMENTED_WHEN_REAL_ROW_PRESENT")
            self.assertTrue(bool(by_id.loc["cand_pose", "p3_fusion_uses_pose"]))
            self.assertEqual(by_id.loc["cand_pose", "p3_evidence_boundary"], EVIDENCE_BOUNDARY)
            self.assertTrue(bool(by_id.loc["cand_leakage_field", "p3_leakage_holdout"]))
            self.assertTrue(bool(by_id.loc["cand_exact_sha", "p3_leakage_holdout"]))
            self.assertTrue(pd.isna(by_id.loc["cand_leakage_field", "p3_fused_ranking_score"]))
            self.assertNotIn("probability", " ".join(col for col in df.columns if col.startswith("p3_")))

            validation = validate(Namespace(output=output, phase2_predictions=phase2, external_priors=external, pose_manifest=pose, geometry=None, audit_json=None))
            self.assertEqual(validation["status"], "PASS")

    def test_normalization_is_candidate_pool_only_not_heldout_influenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, _, _, _, output = self.make_inputs(root)
            fuse_candidates(inputs)
            baseline = pd.read_csv(output).set_index("candidate_id")
            baseline_score = baseline.loc["cand_no_pose", "p3_ai_prior_ranking_score"]

            phase2_rows = base_phase2_rows()
            for row in phase2_rows:
                if row["candidate_id"] == "cand_leakage_field":
                    row["phase2_v2_combined_rank_score"] = 1000.0
                    row["phase2_v2_pair_binding_probability"] = 1000.0
            write_csv(root / "phase2.csv", phase2_rows)
            fuse_candidates(inputs)
            changed = pd.read_csv(output).set_index("candidate_id")
            self.assertAlmostEqual(baseline_score, changed.loc["cand_no_pose", "p3_ai_prior_ranking_score"])

    def test_validator_catches_fabricated_missing_pose_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, phase2, external, pose, output = self.make_inputs(root)
            fuse_candidates(inputs)
            rows = pd.read_csv(output)
            rows.loc[rows["candidate_id"] == "cand_no_pose", "p3_pose_geometry_ranking_score"] = 0.5
            rows.to_csv(output, index=False)
            validation = validate(Namespace(output=output, phase2_predictions=phase2, external_priors=external, pose_manifest=pose, geometry=None, audit_json=None))
            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("missing_pose_has_no_fabricated_pose_score", validation["failed_checks"])

    def test_rejects_external_prior_boundary_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, _, external, _, _ = self.make_inputs(root)
            rows = pd.read_csv(external)
            rows.loc[0, "external_prior_evidence_boundary"] = "pretend_blocker_score"
            rows.to_csv(external, index=False)
            with self.assertRaises(ValueError):
                fuse_candidates(inputs)

    def test_explicit_missing_and_failed_geometry_are_ai_prior_only_but_ok_pose_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, phase2, external, pose, output = self.make_inputs(root)
            ok_pose = root / "ok_pose.pdb"
            failed_pose = root / "failed_pose.pdb"
            ok_pose.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n", encoding="utf-8")
            failed_pose.write_text("not a pdb\n", encoding="utf-8")
            phase2_rows = base_phase2_rows()
            phase2_rows.append(
                {
                    "candidate_id": "cand_failed_geometry",
                    "phase2_v2_pair_binding_probability": 0.60,
                    "phase2_v2_pvrig_target_epitope_mass": 6.0,
                    "phase2_v2_cdr3_hotspot_contact_mean": 0.40,
                    "phase1_mvp_rank_score": 0.60,
                    "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
                    "phase2_v2_combined_rank_score": 0.60,
                }
            )
            write_csv(phase2, phase2_rows)
            external_with_failed = external_rows("CONTROLKNOWNPOSITIVE")
            external_with_failed.append(
                {
                    "candidate_id": "cand_failed_geometry",
                    "candidate_sequence_sha256": sequence_sha256("FAILSEQ"),
                    "nanobind_seq_raw_score": 0.4,
                    "nanobind_pro_raw_score": 0.4,
                    "deepnano_seq_raw_score": 0.4,
                    "nanobind_site_target_minus_background": 0.04,
                    "nanobind_site_target_weighted_mean": 0.04,
                    "deepnano_site_target_minus_background": 0.04,
                    "deepnano_site_target_weighted_mean": 0.04,
                    "external_prior_evidence_boundary": EXTERNAL_PRIOR_BOUNDARY,
                }
            )
            write_csv(external, external_with_failed)
            write_csv(
                pose,
                [
                    {"candidate_id": "cand_pose", "pose_id": "pose_ok", "pose_path": str(ok_pose), "pose_status": "pose_supplied", "qc_status": "pass"},
                    {"candidate_id": "cand_no_pose", "pose_id": "pose_missing", "pose_path": "", "pose_status": "no_pose_supplied", "qc_status": "not_applicable_no_pose"},
                    {"candidate_id": "cand_failed_geometry", "pose_id": "pose_failed", "pose_path": str(failed_pose), "pose_status": "pose_supplied", "qc_status": "pass"},
                ],
            )
            geometry = root / "geometry.csv"
            write_csv(
                geometry,
                [
                    {
                        "candidate_id": "cand_pose",
                        "pose_id": "pose_ok",
                        "pose_path": str(ok_pose),
                        "pose_status": "pose_supplied",
                        "qc_status": "pass",
                        "geometry_status": "ok",
                        "heavy_atom_interface_contacts_le_4p5A": 10,
                        "heavy_atom_clashes_lt_2p0A": 0,
                        "minimum_heavy_atom_distance_A": 3.0,
                        "hotspot_contact_count": 2,
                        "cdr3_contacts": 1,
                    },
                    {
                        "candidate_id": "cand_no_pose",
                        "pose_id": "pose_missing",
                        "pose_path": "",
                        "pose_status": "no_pose_supplied",
                        "qc_status": "not_applicable_no_pose",
                        "geometry_status": "no_pose",
                        "heavy_atom_interface_contacts_le_4p5A": "",
                        "heavy_atom_clashes_lt_2p0A": "",
                        "minimum_heavy_atom_distance_A": "",
                        "hotspot_contact_count": "",
                        "cdr3_contacts": "",
                    },
                    {
                        "candidate_id": "cand_failed_geometry",
                        "pose_id": "pose_failed",
                        "pose_path": str(failed_pose),
                        "pose_status": "pose_supplied",
                        "qc_status": "pass",
                        "geometry_status": "pose_parse_failed",
                        "heavy_atom_interface_contacts_le_4p5A": "",
                        "heavy_atom_clashes_lt_2p0A": "",
                        "minimum_heavy_atom_distance_A": "",
                        "hotspot_contact_count": "",
                        "cdr3_contacts": "",
                    },
                ],
            )
            fuse_candidates(FusionInputs(phase2, external, output, inputs.audit_json, pose_manifest=pose, geometry=geometry, leakage_manifest=inputs.leakage_manifest))
            by_id = pd.read_csv(output).set_index("candidate_id")

            self.assertTrue(bool(by_id.loc["cand_pose", "p3_pose_available"]))
            self.assertTrue(bool(by_id.loc["cand_pose", "p3_fusion_uses_pose"]))
            for candidate_id in ("cand_no_pose", "cand_failed_geometry"):
                self.assertFalse(bool(by_id.loc[candidate_id, "p3_pose_available"]))
                self.assertFalse(bool(by_id.loc[candidate_id, "p3_fusion_uses_pose"]))
                self.assertEqual(by_id.loc[candidate_id, "p3_missing_pose_policy"], "AI_PRIOR_ONLY")
                self.assertTrue(pd.isna(by_id.loc[candidate_id, "p3_pose_geometry_ranking_score"]))
                self.assertAlmostEqual(by_id.loc[candidate_id, "p3_fused_ranking_score"], by_id.loc[candidate_id, "p3_ai_prior_ranking_score"])

            validation = validate(Namespace(output=output, phase2_predictions=phase2, external_priors=external, pose_manifest=pose, geometry=geometry, audit_json=None))
            self.assertEqual(validation["status"], "PASS")

    def test_v2_3_only_phase2_columns_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, phase2, _, _, output = self.make_inputs(root)
            rows = []
            for i, row in enumerate(base_phase2_rows()):
                rows.append(
                    {
                        "candidate_id": row["candidate_id"],
                        "phase2_v2_3_combined_ranking_ai_prior": 0.9 - i * 0.2,
                        "phase2_v2_3_pair_ranking_logit": 2.0 - i,
                        "phase2_v2_3_pair_ranking_logit_norm": 0.9 - i * 0.2,
                        "phase2_v2_3_sigmoid_pair_ranking_ai_prior_norm": 0.8 - i * 0.1,
                        "phase2_v2_3_contact_top20_mean_ai_prior_norm": 0.7 - i * 0.1,
                        "phase2_v2_3_cdr3_contact_top20_mean_ai_prior_norm": 0.6 - i * 0.1,
                        "phase2_v2_3_cdr3_contact_mean_ai_prior": 0.5 - i * 0.1,
                        "leakage_label": row["leakage_label"],
                    }
                )
            write_csv(phase2, rows)

            audit = fuse_candidates(inputs)
            by_id = pd.read_csv(output).set_index("candidate_id")

            self.assertEqual(audit["status"], "PASS")
            self.assertIn("phase2_v2_3_combined_ranking_ai_prior", json.loads(by_id.iloc[0]["p3_weight_spec_json"])["phase2_feature_weights"])
            self.assertTrue(pd.to_numeric(by_id["p3_phase2_component_ranking_score"], errors="coerce").notna().any())


if __name__ == "__main__":
    unittest.main()
