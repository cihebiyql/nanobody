#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_pvrig_formal_teacher500_package.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_formal_teacher500_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildPVRIGFormalTeacher500PackageTest(unittest.TestCase):
    def test_manifest_mapping_preserves_frozen_cdr_coordinates(self) -> None:
        sequence = "A" * 10 + "CDE" + "F" * 8 + "GHI" + "K" * 10 + "LMNP" + "Q" * 8
        row = {
            "selection_rank": "1", "candidate_id": "c1", "vhh_sequence": sequence,
            "sequence_sha256": "sha", "cdr1_after": "CDE", "cdr2_after": "GHI", "cdr3_after": "LMNP",
            "cdr1_start_1based": "11", "cdr1_end_1based": "13",
            "cdr2_start_1based": "22", "cdr2_end_1based": "24",
            "cdr3_start_1based": "35", "cdr3_end_1based": "38",
            "target_patch_id": "A", "hotspots_uniprot": "R95", "parent_id": "p1",
            "parent_framework_cluster": "pc1", "backbone_index": "2", "mpnn_index": "1",
            "design_mode": "H3", "design_method": "RFantibody", "teacher_selection_layer": "diversity",
            "formal_split": "test", "fast_gate_tier": "FORMAL_ELIGIBLE", "generic_binding_prior": "0.4",
            "model_uncertainty": "0.1", "cheap_qc_score": "0.9", "source_pdb": "/tmp/c1.pdb",
        }
        mapped = MOD.manifest_row(row)
        self.assertEqual(mapped["cdr3_start_1based"], "35")
        self.assertEqual(mapped["teacher_split"], "test")
        self.assertEqual(mapped["hotspot_set"], "A")

    def test_controller_uses_seven_distinct_gpu_shards(self) -> None:
        source = MOD.controller_script()
        self.assertIn("seq 0 6", source)
        self.assertIn("gpu=$((shard + 1))", source)
        self.assertIn("run_shards 0 monomer", source)
        self.assertIn("run_shards 1 docking", source)

    def test_bad_cdr_coordinates_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MOD.verified_range("AAAA", "AC", "3", "4")


if __name__ == "__main__":
    unittest.main()
