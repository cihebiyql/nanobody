#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "audit_phase2_v3_p2_v1_1_hetatm_contamination.py"
)
SPEC = importlib.util.spec_from_file_location("p2_v1_1_hetatm_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def pdb_line(
    record: str,
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    residue: int,
    x: float,
    y: float = 0.0,
    z: float = 0.0,
    element: str = "C",
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:^4} {resname:>3} {chain}{residue:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {element:>2}  "
    )


class HetatmContactAuditTests(unittest.TestCase):
    def test_inclusive_and_protein_only_residue_pairs_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pose = Path(tmp) / "pose.pdb"
            reference = Path(tmp) / "reference.pdb"
            pose.write_text(
                "\n".join(
                    [
                        pdb_line("ATOM", 1, "CA", "ALA", "A", 100, 0.0),
                        pdb_line("ATOM", 2, "CA", "ALA", "A", 10, 10.0),
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            reference.write_text(
                "\n".join(
                    [
                        # Both boundary contacts at exactly 4.5 A must count.
                        pdb_line("ATOM", 1, "CA", "ALA", "D", 1, 4.5),
                        pdb_line("ATOM", 2, "CA", "GLY", "D", 2, 14.5),
                        pdb_line("HETATM", 3, "O", "HOH", "D", 201, 3.0, element="O"),
                        pdb_line("HETATM", 4, "C1", "EDO", "D", 202, -3.0),
                        # A second atom in the same EDO must not add a residue pair.
                        pdb_line("HETATM", 5, "C2", "EDO", "D", 202, -3.5),
                        pdb_line("ATOM", 6, "CA", "SER", "D", 3, 30.0),
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            vhh_atoms = list(MOD.iter_heavy_atoms(pose, "A"))
            reference_atoms = list(MOD.iter_heavy_atoms(reference, "D"))
            result = MOD.contact_pair_summaries(
                vhh_atoms, reference_atoms, 4.5, MOD.parse_range("98-116")
            )

            self.assertEqual(result["inclusive"]["total_residue_pair_occlusion"], 4)
            self.assertEqual(result["inclusive"]["cdr3_residue_pair_occlusion"], 3)
            self.assertTrue(math.isclose(result["inclusive"]["cdr3_fraction"], 0.75))
            self.assertEqual(result["protein_only"]["total_residue_pair_occlusion"], 2)
            self.assertEqual(result["protein_only"]["cdr3_residue_pair_occlusion"], 1)
            self.assertTrue(math.isclose(result["protein_only"]["cdr3_fraction"], 0.5))

            inventory = MOD.reference_inventory(reference_atoms)
            self.assertEqual(inventory["protein_atom_count"], 3)
            self.assertEqual(inventory["protein_residue_count"], 3)
            self.assertEqual(inventory["hetatm_atom_count"], 3)
            self.assertEqual(inventory["hetatm_residue_count"], 2)
            self.assertEqual(inventory["hoh_atom_count"], 1)
            self.assertEqual(inventory["edo_atom_count"], 2)
            self.assertEqual(inventory["edo_residue_count"], 1)

    def test_zero_protein_only_denominator_has_null_factor(self) -> None:
        self.assertIsNone(MOD.safe_factor(3.0, 0.0))
        self.assertEqual(MOD.csv_number(MOD.safe_factor(3.0, 0.0)), "")

    def test_output_paths_must_stay_outside_read_only_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            root.mkdir()
            outside = Path(tmp) / "audit.csv"
            MOD.ensure_output_paths_outside_input_root(root, [outside])
            with self.assertRaisesRegex(ValueError, "outside the read-only input root"):
                MOD.ensure_output_paths_outside_input_root(root, [root / "audit.csv"])
            with self.assertRaisesRegex(ValueError, "must be distinct"):
                MOD.ensure_output_paths_outside_input_root(root, [outside, outside])
            protected = Path(tmp) / "rules.json"
            with self.assertRaisesRegex(ValueError, "collides with a protected input"):
                MOD.ensure_output_paths_outside_input_root(
                    root, [protected], [protected]
                )

    def test_marker_artifact_path_and_hash_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            artifact = run_dir / "reports/ranks.csv"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("model,rank\npose,1\n", encoding="utf-8")
            marker = {
                "artifacts": {
                    "ranks": {
                        "relpath": "reports/ranks.csv",
                        "sha256": MOD.sha256_file(artifact),
                    }
                }
            }
            MOD.validate_marker_artifact(marker, "ranks", artifact, run_dir)
            artifact.write_text("model,rank\npose,2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                MOD.validate_marker_artifact(marker, "ranks", artifact, run_dir)


class SensitivityClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = {
            "hotspot_min": 14.0,
            "total_min": 500.0,
            "cdr3_min": 100.0,
            "cdr3_fraction_min": 0.15,
            "binder_total_max": 50.0,
            "b_total_min": 500.0,
            "b_cdr3_min": 50.0,
            "b_fallback_total_min": 300.0,
            "b_fallback_hotspot_min": 10.0,
            "b_fallback_cdr3_min": 50.0,
        }

    def classify(self, hotspot: float, total: float, cdr3: float, fraction: float) -> str:
        return MOD.classify_sensitivity(hotspot, total, cdr3, fraction, self.rules)

    def test_exact_current_rule_boundaries(self) -> None:
        self.assertEqual(self.classify(14, 500, 100, 0.15), "BLOCKER_LIKE_A")
        self.assertEqual(self.classify(14, 49, 0, 0), "BINDER_LIKE_C")
        self.assertEqual(self.classify(13, 500, 50, 0), "BLOCKER_PLAUSIBLE_B")
        self.assertEqual(self.classify(10, 300, 50, 0), "BLOCKER_PLAUSIBLE_B")
        self.assertEqual(self.classify(10, 299, 50, 0), "EVIDENCE_INFERENCE_ONLY_E")

    def test_sensitivity_can_transition_a_to_b_and_b_to_e(self) -> None:
        self.assertEqual(self.classify(14, 500, 100, 0.15), "BLOCKER_LIKE_A")
        self.assertEqual(self.classify(14, 499, 99, 0.20), "BLOCKER_PLAUSIBLE_B")
        self.assertEqual(self.classify(14, 500, 50, 0.10), "BLOCKER_PLAUSIBLE_B")
        self.assertEqual(self.classify(14, 299, 49, 0.10), "EVIDENCE_INFERENCE_ONLY_E")

    def test_b_total_threshold_tracks_the_loaded_a_total_rule(self) -> None:
        payload = {
            "classifier": {
                "BLOCKER_LIKE_A": {
                    "required_for_vhh_docking": {
                        "hotspot_overlap_count": ">= 14",
                        "total_vhh_pvrl2_residue_pair_occlusion": ">= 600",
                        "cdr3_pvrl2_residue_pair_occlusion": ">= 100",
                        "cdr3_occlusion_fraction": ">= 0.15",
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = MOD.load_rules(path)
        self.assertEqual(loaded["total_min"], 600.0)
        self.assertEqual(loaded["b_total_min"], 600.0)

    def test_claim_boundary_forbids_overclaiming(self) -> None:
        self.assertIn("Read-only V1.1 contamination and sensitivity audit", MOD.CLAIM_BOUNDARY)
        self.assertIn("not a V1.2 calibrated label", MOD.CLAIM_BOUNDARY)
        self.assertIn("experimental binding truth", MOD.CLAIM_BOUNDARY)
        self.assertIn("blocking truth", MOD.CLAIM_BOUNDARY)
        forbidden_fields = {
            "corrected_class",
            "validated_v1_2_class",
            "protein_only_gold_class",
        }
        self.assertTrue(forbidden_fields.isdisjoint(MOD.CSV_FIELDS))
        self.assertIn("protein_only_sensitivity_class", MOD.CSV_FIELDS)


if __name__ == "__main__":
    unittest.main()
