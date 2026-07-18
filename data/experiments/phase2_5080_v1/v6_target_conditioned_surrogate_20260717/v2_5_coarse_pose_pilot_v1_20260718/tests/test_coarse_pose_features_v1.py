#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path

import numpy as np


MODULE = Path(__file__).resolve().parents[1] / "src" / "coarse_pose_features_v1.py"
SPEC = importlib.util.spec_from_file_location("coarse_pose_features_v1", MODULE)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    c, s, q = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([
        [c + x*x*q, x*y*q-z*s, x*z*q+y*s],
        [y*x*q+z*s, c+y*y*q, y*z*q-x*s],
        [z*x*q-y*s, z*y*q+x*s, c+z*z*q],
    ])


class CoarsePoseFeaturesTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(17)
        sequence = "ACDEFGHIKLMNPQRSTVWY"
        coords = np.cumsum(rng.normal(size=(len(sequence), 3)), axis=0)
        coords[:, 2] += np.linspace(-7, 7, len(sequence))
        charges = np.asarray([mod.CHARGE.get(aa, 0.0) for aa in sequence])
        self.vhh = mod.ResidueCloud(sequence, np.arange(1, len(sequence)+1), coords, charges)
        target_sequence = "ACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY"
        target_coords = np.cumsum(rng.normal(size=(len(target_sequence), 3)), axis=0)
        target_coords[:, 0] += np.linspace(-6, 6, len(target_sequence))
        target_charges = np.asarray([mod.CHARGE.get(aa, 0.0) for aa in target_sequence])
        self.target = mod.ResidueCloud(
            target_sequence, np.arange(1, len(target_sequence)+1), target_coords, target_charges
        )
        self.interface = np.zeros(len(target_sequence), dtype=bool)
        self.interface[8:22] = True
        self.hotspot = np.zeros(len(target_sequence), dtype=bool)
        self.hotspot[12:18] = True

    def test_pose_grid_has_fixed_300_poses(self):
        poses = mod.pose_grid()
        self.assertEqual(len(poses), 300)
        self.assertEqual([pose.pose_id for pose in poses], list(range(300)))

    def test_feature_vector_is_36d_and_finite(self):
        vhh = mod.canonicalize_vhh(self.vhh, "CDE", "HIK", "PQR")
        target = mod.canonicalize_target(self.target, self.interface, self.hotspot)
        features, _ = mod.feature_vector(vhh, {"8x6b": target, "9e6y": target})
        self.assertEqual(len(features), 36)
        self.assertTrue(np.isfinite(np.asarray(list(features.values()))).all())

    def test_independent_rigid_rotations_do_not_change_features(self):
        base_vhh = mod.canonicalize_vhh(self.vhh, "CDE", "HIK", "PQR")
        base_target = mod.canonicalize_target(self.target, self.interface, self.hotspot)
        base, _ = mod.feature_vector(base_vhh, {"8x6b": base_target, "9e6y": base_target})

        rv = rotation([1, 2, 3], 0.73)
        rt = rotation([-2, 1, 0.5], -0.91)
        moved_vhh = mod.ResidueCloud(
            self.vhh.sequence,
            self.vhh.residue_numbers,
            self.vhh.ca @ rv.T + np.array([4.1, -2.0, 8.2]),
            self.vhh.charges,
        )
        moved_target = mod.ResidueCloud(
            self.target.sequence,
            self.target.residue_numbers,
            self.target.ca @ rt.T + np.array([-5.3, 7.0, 1.2]),
            self.target.charges,
        )
        vhh2 = mod.canonicalize_vhh(moved_vhh, "CDE", "HIK", "PQR")
        target2 = mod.canonicalize_target(moved_target, self.interface, self.hotspot)
        transformed, _ = mod.feature_vector(vhh2, {"8x6b": target2, "9e6y": target2})
        error = max(abs(base[key] - transformed[key]) for key in base)
        self.assertLess(error, 1e-10)

    def test_one_based_ranges_match_sequence_annotations(self):
        annotated = mod.canonicalize_vhh(self.vhh, "CDE", "HIK", "PQR")
        ranged = mod.canonicalize_vhh_from_manifest(
            self.vhh,
            {"cdr1_range": "2-4", "cdr2_range": "7-9", "cdr3_range": "13-15"},
        )
        self.assertTrue(np.allclose(annotated.coords, ranged.coords, atol=1e-12))
        self.assertTrue(np.array_equal(annotated.cdr_indices, ranged.cdr_indices))


if __name__ == "__main__":
    unittest.main()
