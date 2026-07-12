#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_pvrig_teacher_pilot96.py")
SPEC = importlib.util.spec_from_file_location("build_pvrig_teacher_pilot96", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class BuildPilot96TeacherTest(unittest.TestCase):
    def test_current_selection_boundary(self) -> None:
        rows = MOD.read_tsv(MOD.DEFAULT_SELECTION)
        self.assertEqual(len(rows), 96)
        self.assertEqual(len({row["candidate_id"] for row in rows}), 96)
        self.assertEqual({row["parent_framework_cluster"] for row in rows}, {"h-NbBCII10"})
        self.assertEqual(Counter(row["hotspot_set"] for row in rows), Counter({key: 24 for key in "ABCD"}))
        self.assertEqual({row["formal_model_eligible"] for row in rows}, {"false_single_framework_pilot"})
        positives = set(MOD.known_positive_sequences(MOD.base.DEFAULT_POSITIVE_ROOT).values())
        self.assertTrue(positives)
        self.assertFalse({row["sequence"] for row in rows} & positives)

    def test_update_common_preserves_metadata_and_claim_boundary(self) -> None:
        source = {field: f"value_{field}" for field in MOD.METADATA_FIELDS}
        record = MOD.update_common({"candidate_id": "c1"}, source)
        self.assertEqual(record["schema_version"], MOD.SCHEMA_VERSION)
        self.assertEqual(record["claim_boundary"], MOD.CLAIM_BOUNDARY)
        self.assertEqual(record["parent_framework_cluster"], "value_parent_framework_cluster")


if __name__ == "__main__":
    unittest.main()
