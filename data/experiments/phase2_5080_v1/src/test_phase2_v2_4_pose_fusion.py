#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_4_pose_index import EVIDENCE_BOUNDARY as POSE_BOUNDARY
from build_phase2_v2_4_pose_index import build_pose_index
from fuse_phase2_v2_4_p3 import EVIDENCE_BOUNDARY as FUSION_BOUNDARY
from fuse_phase2_v2_4_p3 import fuse_tables

DOCKING_ROOT = Path("/mnt/d/work/抗体/docking/candidates/v2_4_top2")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Phase2V24PoseFusionTests(unittest.TestCase):
    def test_actual_v2_4_pose_index_verifies_top2_assets_without_binding_claims(self) -> None:
        index = build_pose_index(DOCKING_ROOT)

        self.assertEqual(set(index["candidate_id"]), {"zym_test_9743", "zym_test_108006"})
        self.assertEqual(set(index["pose_index_status"]), {"verified_pose_proxy"})
        self.assertTrue(index["vhh_chain_a_exact_match"].all())
        self.assertTrue(index["pvrig_chain_b_exact_match"].all())
        self.assertGreaterEqual(index["top_pose_pdb_gz_count_verified"].min(), 1)
        self.assertEqual(set(index["evidence_boundary"]), {POSE_BOUNDARY})
        self.assertTrue(index["haddock3_status"].str.startswith("completed").all())
        self.assertTrue(index["nbb2_status"].str.startswith("completed").all())

    def test_missing_geometry_never_boosts_sequence_score(self) -> None:
        sequence = pd.DataFrame(
            [
                {"candidate_id": "with_pose", "phase2_v2_4_sequence_ensemble_score": 0.40},
                {"candidate_id": "missing_pose", "phase2_v2_4_sequence_ensemble_score": 0.80},
            ]
        )
        pose = pd.DataFrame(
            [
                {
                    "candidate_id": "with_pose",
                    "pose_index_status": "verified_pose_proxy",
                    "vhh_chain_a_exact_match": True,
                    "pvrig_chain_b_exact_match": True,
                    "top_pose_pdb_gz_count_verified": 3,
                    "haddock_best_score": -50.0,
                    "haddock_consensus_sum_of_ranks": 2,
                    "monomer_ca_count": 130,
                }
            ]
        )

        fused = fuse_tables(sequence, pose).set_index("candidate_id")

        self.assertEqual(fused.loc["missing_pose", "v2_4_geometry_boost"], 0.0)
        self.assertEqual(fused.loc["missing_pose", "v2_4_p3_fused_proxy_score"], 0.80)
        self.assertEqual(fused.loc["missing_pose", "v2_4_missing_geometry_policy"], "AI_SEQUENCE_ONLY_NO_GEOMETRY_BOOST")
        self.assertEqual(fused.loc["with_pose", "v2_4_p3_fused_proxy_score"], 0.40)
        self.assertGreater(fused.loc["with_pose", "v2_4_pose_supported_fused_proxy_score"], 0.40)
        self.assertEqual(fused.loc["with_pose", "v2_4_global_fusion_policy"], "SEQUENCE_ONLY_GLOBAL_RANK_INCOMPLETE_POSE_COVERAGE")
        self.assertEqual(set(fused["v2_4_p3_evidence_boundary"]), {FUSION_BOUNDARY})

    def test_failed_pose_validation_is_treated_as_missing_geometry(self) -> None:
        sequence = pd.DataFrame([{"candidate_id": "bad_pose", "phase2_v2_4_sequence_ensemble_score": 0.55}])
        pose = pd.DataFrame(
            [
                {
                    "candidate_id": "bad_pose",
                    "pose_index_status": "failed_validation",
                    "vhh_chain_a_exact_match": False,
                    "pvrig_chain_b_exact_match": True,
                    "top_pose_pdb_gz_count_verified": 2,
                    "haddock_best_score": -100.0,
                }
            ]
        )

        fused = fuse_tables(sequence, pose).iloc[0]

        self.assertFalse(bool(fused["v2_4_geometry_available"]))
        self.assertEqual(fused["v2_4_geometry_boost"], 0.0)
        self.assertEqual(fused["v2_4_p3_fused_proxy_score"], 0.55)

    def test_haddock_score_and_consensus_rank_are_lower_is_better(self) -> None:
        sequence = pd.DataFrame(
            [
                {"candidate_id": "better_pose", "phase2_v2_4_sequence_ensemble_score": 0.50},
                {"candidate_id": "worse_pose", "phase2_v2_4_sequence_ensemble_score": 0.50},
            ]
        )
        pose = pd.DataFrame(
            [
                {
                    "candidate_id": "better_pose",
                    "pose_index_status": "verified_pose_proxy",
                    "vhh_chain_a_exact_match": True,
                    "pvrig_chain_b_exact_match": True,
                    "top_pose_pdb_gz_count_verified": 3,
                    "haddock_best_score": -90.0,
                    "haddock_consensus_sum_of_ranks": 1,
                    "monomer_ca_count": 130,
                },
                {
                    "candidate_id": "worse_pose",
                    "pose_index_status": "verified_pose_proxy",
                    "vhh_chain_a_exact_match": True,
                    "pvrig_chain_b_exact_match": True,
                    "top_pose_pdb_gz_count_verified": 3,
                    "haddock_best_score": -10.0,
                    "haddock_consensus_sum_of_ranks": 9,
                    "monomer_ca_count": 130,
                },
            ]
        )

        fused = fuse_tables(sequence, pose).set_index("candidate_id")

        self.assertGreater(fused.loc["better_pose", "v2_4_geometry_proxy_score"], fused.loc["worse_pose", "v2_4_geometry_proxy_score"])
        self.assertGreater(fused.loc["better_pose", "v2_4_p3_fused_proxy_score"], fused.loc["worse_pose", "v2_4_p3_fused_proxy_score"])
        self.assertEqual(set(fused["v2_4_global_fusion_policy"]), {"GLOBAL_POSE_FUSION_APPLIED_SUFFICIENT_COVERAGE"})

    def test_csv_roundtrip_helpers_are_cpu_tempfile_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence_path = root / "sequence.csv"
            write_csv(sequence_path, [{"candidate_id": "c1", "phase2_v2_4_sequence_ensemble_score": 0.2}])
            loaded = pd.read_csv(sequence_path)
            fused = fuse_tables(loaded, pd.DataFrame(columns=["candidate_id"]))
            self.assertEqual(fused.loc[0, "candidate_id"], "c1")
            self.assertEqual(fused.loc[0, "v2_4_p3_fused_proxy_score"], 0.2)


if __name__ == "__main__":
    unittest.main()
