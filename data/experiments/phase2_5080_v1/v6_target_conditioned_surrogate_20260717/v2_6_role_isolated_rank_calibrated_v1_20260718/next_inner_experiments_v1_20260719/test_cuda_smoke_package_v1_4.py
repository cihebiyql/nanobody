#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("launch_contact_ablation_cuda_smokes_v1_4.py")
SPEC = importlib.util.spec_from_file_location("smoke_launcher", PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

class SmokePackageTests(unittest.TestCase):
    def test_two_complementary_jobs_only(self):
        self.assertEqual(len(mod.JOBS), 2)
        self.assertEqual({job[0] for job in mod.JOBS}, {"F0_MARGINAL_ONLY_NO_RANK", "F0_PAIR_ONLY_NO_RANK"})
        self.assertEqual({(job[3], job[4]) for job in mod.JOBS}, {(1.0, 0.0), (0.0, 0.5)})
    def test_gpu_mapping_uses_idle_smoke_pair(self):
        self.assertEqual({job[1] for job in mod.JOBS}, {5, 6})
        self.assertEqual({job[2] for job in mod.JOBS}, {"cuda:2", "cuda:3"})
    def test_firewall_fields_complete(self):
        self.assertEqual(set(mod.FIREWALL), {"outer_test_truth_access_count", "outer_metrics_access_count", "v4_f_test32_access_count"})

if __name__ == "__main__":
    unittest.main()
