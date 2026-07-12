#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_pvrig_teacher_v1.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_teacher_v1", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, name: str, residue: str, chain: str, resseq: int, x: float, y: float, z: float) -> str:
    return (
        f"ATOM  {serial:5d} {name:^4s} {residue:>3s} {chain}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {name[0]:>2s}\n"
    )


class TeacherV1Test(unittest.TestCase):
    def test_consensus_relevance(self) -> None:
        self.assertEqual(MOD.consensus_relevance({"consensus_class": "CONSENSUS_BLOCKER_LIKE_A"}), 4)
        self.assertEqual(MOD.consensus_relevance({"consensus_class": "SINGLE_BASELINE_BLOCKER_RECHECK"}), 3)
        self.assertEqual(MOD.consensus_relevance({"consensus_class": "BLOCKER_PLAUSIBLE_B"}), 2)
        self.assertEqual(MOD.consensus_relevance({"consensus_class": "BINDER_LIKE_C", "binder_like_count": "2"}), 1)
        self.assertEqual(MOD.consensus_relevance({"consensus_class": "EVIDENCE_INFERENCE_ONLY_E"}), 0)

    def test_normalized_cluster_entropy(self) -> None:
        self.assertEqual(MOD.normalized_cluster_entropy(["c1", "c1"]), 0.0)
        self.assertAlmostEqual(MOD.normalized_cluster_entropy(["c1", "c2"]), 1.0)

    def test_residue_contact_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pose.pdb"
            path.write_text(
                atom_line(1, "CA", "ALA", "A", 1, 0.0, 0.0, 0.0)
                + atom_line(2, "CB", "ALA", "A", 1, 0.5, 0.0, 0.0)
                + atom_line(3, "CA", "ARG", "B", 10, 4.0, 0.0, 0.0)
                + atom_line(4, "CA", "GLY", "B", 11, 10.0, 0.0, 0.0),
                encoding="utf-8",
            )
            pairs = MOD.residue_contact_pairs(path, "A", "B", 4.5)
            self.assertEqual(pairs, {("A:1:ALA", "B:10:ARG")})

    def test_current_calibration_inventory(self) -> None:
        cases = MOD.discover_cases(MOD.DEFAULT_POSITIVE_ROOT, MOD.DEFAULT_MUTANT_ROOT)
        self.assertEqual(len(cases), 47)
        self.assertEqual(sum(case.calibration_role == "known_positive_calibration_only" for case in cases), 11)
        pose_count = sum(len(MOD.read_csv(case.consensus_csv)) for case in cases)
        self.assertEqual(pose_count, 466)


if __name__ == "__main__":
    unittest.main()
