#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("freeze_phase2_v4_d_fullqc290_split.py")
SPEC = importlib.util.spec_from_file_location("freeze_phase2_v4_d_fullqc290_split", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class FreezeFullQc290SplitTest(unittest.TestCase):
    @classmethod
    def source(cls) -> Path:
        return (
            MODULE_PATH.parents[1]
            / "runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/"
            "teacher500_full_qc_complete290_lineage.csv"
        )

    @classmethod
    def dual128_source(cls) -> Path:
        return MODULE_PATH.parents[1] / "data_splits/pvrig_v4_c/dual128_candidates_source.tsv"

    def test_real_source_freezes_parent_disjoint_split(self) -> None:
        rows = MOD.freeze_rows(MOD.load_csv(self.source()))
        self.assertEqual(MOD.distribution(rows, "model_split"), MOD.EXPECTED_SPLIT_COUNTS)
        clusters = {
            split: {
                row["parent_framework_cluster"]
                for row in rows
                if row["model_split"] == split
            }
            for split in MOD.EXPECTED_SPLIT_COUNTS
        }
        self.assertFalse(clusters["OPEN_TRAIN"] & clusters["OPEN_DEVELOPMENT"])
        self.assertFalse(clusters["OPEN_TRAIN"] & clusters["PROSPECTIVE_COMPUTATIONAL_TEST"])
        self.assertFalse(clusters["OPEN_DEVELOPMENT"] & clusters["PROSPECTIVE_COMPUTATIONAL_TEST"])
        self.assertEqual(clusters["PROSPECTIVE_COMPUTATIONAL_TEST"], MOD.EXPECTED_TEST_CLUSTERS)

    def test_outputs_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            for output in (first, second):
                self.assertEqual(
                    MOD.main(
                        [
                            "--input",
                            str(self.source()),
                            "--dual128-source",
                            str(self.dual128_source()),
                            "--output-dir",
                            str(output),
                        ]
                    ),
                    0,
                )
            self.assertEqual(
                (first / "fullqc290_split_manifest.tsv").read_bytes(),
                (second / "fullqc290_split_manifest.tsv").read_bytes(),
            )
            first_audit = json.loads((first / "fullqc290_split_audit.json").read_text())
            second_audit = json.loads((second / "fullqc290_split_audit.json").read_text())
            for payload in (first_audit, second_audit):
                payload["manifest"]["path"] = "NORMALIZED"
                payload["source"]["path"] = "NORMALIZED"
            self.assertEqual(first_audit, second_audit)

    def test_tampered_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "source.csv"
            shutil.copy2(self.source(), tampered)
            with tampered.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaises(MOD.SplitFreezeError):
                MOD.load_csv(tampered)

    def test_manifest_excludes_docking_targets_and_scores(self) -> None:
        rows = MOD.freeze_rows(MOD.load_csv(self.source()))
        forbidden = {
            "R_8X6B",
            "R_9E6Y",
            "R_dual_min",
            "generic_binding_prior",
            "full_qc_final_score",
            "blocker_class",
        }
        self.assertFalse(forbidden & set(rows[0]))

    def test_dual128_has_no_candidate_or_sequence_overlap(self) -> None:
        rows = MOD.freeze_rows(MOD.load_csv(self.source()))
        dual_ids, dual_hashes = MOD.load_dual128_hashes(self.dual128_source())
        self.assertFalse({row["candidate_id"] for row in rows} & dual_ids)
        self.assertFalse({row["sequence_sha256"] for row in rows} & dual_hashes)


if __name__ == "__main__":
    unittest.main()
