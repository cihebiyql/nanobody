#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("extract_phase2_v4_d_open258_structure_features_v1.py")
SPEC = importlib.util.spec_from_file_location("structure_features_v1", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_pdb(path: Path, coordinates: np.ndarray, *, omit_residue: int | None = None) -> None:
    lines = []
    serial = 1
    for residue, xyz in enumerate(coordinates, start=1):
        if residue == omit_residue:
            continue
        x, y, z = xyz
        confidence = 0.50 + residue / 1000.0
        lines.append(
            f"ATOM  {serial:5d}  CA  GLY A{residue:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00{confidence:6.2f}           C  \n"
        )
        serial += 1
    lines.append("END\n")
    path.write_text("".join(lines), encoding="ascii")


class StructureFeatureTests(unittest.TestCase):
    def coordinates(self) -> np.ndarray:
        index = np.arange(1, 101, dtype=np.float64)
        return np.column_stack((3.7 * index, 5.0 * np.sin(index / 6.0), 4.0 * np.cos(index / 8.0)))

    def ranges(self) -> dict[str, str]:
        return {"CDR1": "10-14", "CDR2": "35-40", "CDR3": "75-84"}

    def test_emits_frozen_126_feature_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "vhh.pdb"
            write_pdb(path, self.coordinates())
            features = MOD.structure_features(path, "A", self.ranges())
            self.assertEqual(len(features), 126)
            self.assertTrue(all(np.isfinite(list(features.values()))))
            self.assertEqual(features["CDR1__residue_count"], 5.0)
            self.assertEqual(features["CDR2__residue_count"], 6.0)
            self.assertEqual(features["CDR3__residue_count"], 10.0)

    def test_features_are_rigid_transform_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = self.coordinates()
            theta = np.deg2rad(37.0)
            rotation = np.asarray(
                [[np.cos(theta), -np.sin(theta), 0.0], [np.sin(theta), np.cos(theta), 0.0], [0.0, 0.0, 1.0]]
            )
            transformed = original @ rotation.T + np.asarray([100.0, -40.0, 17.0])
            first = root / "first.pdb"
            second = root / "second.pdb"
            write_pdb(first, original)
            write_pdb(second, transformed)
            left = MOD.structure_features(first, "A", self.ranges())
            right = MOD.structure_features(second, "A", self.ranges())
            self.assertEqual(set(left), set(right))
            for name in left:
                # PDB coordinates are rounded to 0.001 A after the transform.
                self.assertAlmostEqual(left[name], right[name], delta=0.001, msg=name)

    def test_missing_cdr_residue_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.pdb"
            write_pdb(path, self.coordinates(), omit_residue=78)
            with self.assertRaisesRegex(MOD.FeatureError, "missing_cdr_residues:CDR3"):
                MOD.structure_features(path, "A", self.ranges())

    def test_wrong_chain_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "vhh.pdb"
            write_pdb(path, self.coordinates())
            with self.assertRaisesRegex(MOD.FeatureError, "unexpected_ca_chain"):
                MOD.structure_features(path, "H", self.ranges())


if __name__ == "__main__":
    unittest.main()
