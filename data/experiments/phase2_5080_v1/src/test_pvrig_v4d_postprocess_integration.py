#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
EXP_DIR = SRC_DIR.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MERGE = load_module("candidate_evidence_v2_integration", SRC_DIR / "merge_pvrig_candidate_evidence_v2.py")
RANK = load_module("geometry_shortlist_integration", SRC_DIR / "build_pvrig_geometry_shortlist.py")


class V4DPostprocessIntegrationTests(unittest.TestCase):
    def test_real_v1_schema_flows_through_open_teacher_to_top50(self) -> None:
        split_path = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
        with split_path.open(newline="", encoding="utf-8-sig") as handle:
            split_rows = list(csv.DictReader(handle, delimiter="\t"))
        open_rows = [
            row for row in split_rows
            if row["model_split"] in {"OPEN_TRAIN", "OPEN_DEVELOPMENT"}
        ]
        self.assertEqual(len(open_rows), 258)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher_path = root / "open_teacher.tsv"
            teacher_fields = [
                "candidate_id", "sequence_sha256", "R_8X6B", "R_9E6Y",
                "R_dual_mean", "R_dual_min", "R_dual_gap", "teacher_uncertainty",
                "native_cross_support_agreement_mean", "model_pair_consensus_fraction_mean",
                "successful_seed_count_8X6B", "successful_seed_count_9E6Y",
            ]
            with teacher_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=teacher_fields, delimiter="\t")
                writer.writeheader()
                for index, row in enumerate(open_rows):
                    r8 = 0.2 + index / 1000.0
                    r9 = 0.19 + index / 1000.0
                    writer.writerow({
                        "candidate_id": row["candidate_id"],
                        "sequence_sha256": row["sequence_sha256"],
                        "R_8X6B": f"{r8:.6f}",
                        "R_9E6Y": f"{r9:.6f}",
                        "R_dual_mean": f"{(r8 + r9) / 2:.6f}",
                        "R_dual_min": f"{min(r8, r9):.6f}",
                        "R_dual_gap": f"{abs(r8 - r9):.6f}",
                        "teacher_uncertainty": "0.02",
                        "native_cross_support_agreement_mean": "0.9",
                        "model_pair_consensus_fraction_mean": "0.8",
                        "successful_seed_count_8X6B": "3",
                        "successful_seed_count_9E6Y": "3",
                    })

            master_dir = root / "master_v2"
            merge_args = MERGE.parse_args([
                "--v4d-open-teacher", str(teacher_path),
                "--outdir", str(master_dir),
            ])
            merge_audit = MERGE.run(merge_args)
            self.assertEqual(merge_audit["v4d"]["open_teacher_rows"], 258)
            self.assertEqual(merge_audit["v4d"]["sealed_test_rows"], 32)

            shortlist_dir = root / "shortlist"
            rank_args = RANK.parse_args([
                "--master", str(master_dir / "candidate_evidence_master.tsv"),
                "--outdir", str(shortlist_dir),
            ])
            rank_audit = RANK.run(rank_args)
            self.assertEqual(rank_audit["eligible_open_rows"], 258)
            self.assertEqual(rank_audit["sealed_fullqc_excluded_count"], 32)
            self.assertEqual(rank_audit["shortlist_count"], 50)
            self.assertEqual(rank_audit["pose_review_manifest_rows"], 40)

            test_ids = {
                row["candidate_id"] for row in split_rows
                if row["model_split"] == "PROSPECTIVE_COMPUTATIONAL_TEST"
            }
            with (shortlist_dir / "shortlist50.tsv").open(newline="", encoding="utf-8") as handle:
                shortlist = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(test_ids.isdisjoint(row["candidate_id"] for row in shortlist))


if __name__ == "__main__":
    unittest.main()
