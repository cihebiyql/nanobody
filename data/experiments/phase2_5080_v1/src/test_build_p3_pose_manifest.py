#!/usr/bin/env python3
"""Regression tests for optional Phase 3 pose manifest construction."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_p3_pose_manifest import build_manifest, stable_pose_id


class P3PoseManifestTests(unittest.TestCase):
    def test_zero_poses_writes_explicit_auditable_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.csv"
            index = root / "index.csv"
            cdr = root / "cdr.csv"
            out = root / "manifest.csv"
            seq = "AAACDR3BBB"
            candidates.write_text("candidate_id,leakage_label,score\nzym_test_7,NO_KNOWN_POSITIVE_LEAKAGE,0.9\n", encoding="utf-8")
            index.write_text(
                "sample_id,vhh_seq,cdr3_seq\nzympara_test_000007," + seq + ",CDR3\n",
                encoding="utf-8",
            )
            cdr.write_text("vhh_seq,cdr3_seq\n" + seq + ",CDR3\n", encoding="utf-8")

            summary = build_manifest(candidates, out, cdr_manifest=cdr, index_csv=index, root=root)
            self.assertEqual(summary["candidates"], 1)
            self.assertEqual(summary["pose_rows"], 0)
            self.assertEqual(summary["missing_pose_rows"], 1)
            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["candidate_id"], "zym_test_7")
            self.assertEqual(row["pose_status"], "no_pose_supplied")
            self.assertEqual(row["qc_status"], "not_applicable_no_pose")
            self.assertEqual(row["pose_path"], "")
            self.assertEqual(row["vhh_seq"], seq)
            self.assertEqual(row["cdr3_seq"], "CDR3")
            self.assertEqual(row["leakage_role"], "candidate_no_known_positive_leakage")
            self.assertEqual(row["pose_id"], stable_pose_id("zym_test_7", row["target_baseline"], "", "none_supplied"))

    def test_pose_index_preserves_pose_metadata_and_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.csv"
            index = root / "index.csv"
            cdr = root / "cdr.csv"
            pose = root / "pose.pdb"
            pose_index = root / "pose_index.csv"
            out = root / "manifest.csv"
            candidates.write_text("candidate_id,leakage_label\ncandA,CALIBRATION_CONTROL\n", encoding="utf-8")
            index.write_text("sample_id,vhh_seq,cdr3_seq\n", encoding="utf-8")
            cdr.write_text("vhh_seq,cdr3_seq\n", encoding="utf-8")
            pose.write_text("", encoding="utf-8")
            pose_index.write_text(
                "candidate_id,pose_path,vhh_chain,target_chain,pose_source,qc_status,qc_notes,calibration_role,leakage_role\n"
                "candA,pose.pdb,H,P,synthetic_fixture,pass,unit ok,calibration_positive,leakage_control\n",
                encoding="utf-8",
            )

            build_manifest(candidates, out, pose_index_csv=pose_index, cdr_manifest=cdr, index_csv=index, root=root)
            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["pose_path"], str(pose.resolve()))
            self.assertEqual(row["pose_relpath"], "pose.pdb")
            self.assertEqual(row["vhh_chain"], "H")
            self.assertEqual(row["target_chain"], "P")
            self.assertEqual(row["pose_source"], "synthetic_fixture")
            self.assertEqual(row["qc_status"], "pass")
            self.assertEqual(row["calibration_role"], "calibration_positive")
            self.assertEqual(row["leakage_role"], "leakage_control")
            self.assertEqual(row["pose_id"], stable_pose_id("candA", row["target_baseline"], str(pose.resolve()), "synthetic_fixture"))


if __name__ == "__main__":
    unittest.main()
