from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "materialize_v218_pose_aux_targets_v1.py"
SPEC = importlib.util.spec_from_file_location("v218_materializer", SOURCE)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class PoseAuxMaterializerTests(unittest.TestCase):
    def test_filters_to_strict_train_and_primary_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strict = root / "strict.tsv"
            release = root / "release.tsv"
            pose = root / "pose.tsv"
            jobs = root / "jobs.tsv"
            output = root / "out.tsv"
            write_tsv(strict, [
                {"candidate_id": "A", "parent_framework_cluster": "P1"},
                {"candidate_id": "B", "parent_framework_cluster": "P2"},
            ])
            write_tsv(release, [
                {"candidate_id": "A", "canonical_model_split": "train", "training_label_status": "WEAK_LABEL_AVAILABLE", "successful_dual_seed_count": "2", "seed_dispersion_Rdual": "0.02"},
                {"candidate_id": "B", "canonical_model_split": "development", "training_label_status": "WEAK_LABEL_AVAILABLE", "successful_dual_seed_count": "1", "seed_dispersion_Rdual": ""},
            ])
            pose_rows = []
            for ref in ("8x6b", "9e6y"):
                for rank in (1, 2):
                    pose_rows.append({
                        "candidate_id": "A", "seed": "917", "scoring_reference": ref,
                        "top8_rank": str(rank), "geometry_utility": str(0.4 + rank / 10),
                        "hotspot_overlap": str(10 + rank), "total_occlusion": str(100 + rank),
                        "cdr3_occlusion": str(20 + rank), "cdr3_fraction": "0.2",
                        "geometry_margin": str(rank), "geometry_class": "A" if rank == 1 else "B",
                    })
            pose_rows.append({**pose_rows[0], "seed": "1931", "geometry_utility": "99"})
            write_tsv(pose, pose_rows)
            write_tsv(jobs, [
                {"entity_id": "A", "seed": "917", "conformation": "8x6b", "canonical_state": "SUCCESS", "job_geometry_score": "0.7", "raw_rank_weighted_geometry_score": "0.6", "model_pair_consensus_fraction": "0.8", "model_native_cross_support_agreement_fraction": "0.9", "model_strict_a_fraction": "0.5", "representative_pair_support_ordinal": "3"},
                {"entity_id": "A", "seed": "917", "conformation": "9e6y", "canonical_state": "SUCCESS", "job_geometry_score": "0.6", "raw_rank_weighted_geometry_score": "0.5", "model_pair_consensus_fraction": "0.7", "model_native_cross_support_agreement_fraction": "0.8", "model_strict_a_fraction": "0.4", "representative_pair_support_ordinal": "2"},
            ])
            report = MOD.materialize(strict, release, pose, jobs, output)
            self.assertEqual(report["output_rows"], 1)
            with output.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["candidate_id"], "A")
            self.assertAlmostEqual(float(rows[0]["pose_8x6b_geometry_utility_mean"]), 0.55)
            self.assertEqual(rows[0]["multiseed_uncertainty_available"], "1")
            self.assertEqual(rows[0]["pose_8x6b_A_fraction"], "0.5")

    def test_rejects_duplicate_strict_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "strict.tsv"
            write_tsv(p, [
                {"candidate_id": "A", "parent_framework_cluster": "P1"},
                {"candidate_id": "A", "parent_framework_cluster": "P1"},
            ])
            with self.assertRaises(MOD.MaterializationError):
                MOD.read_unique(p, "candidate_id")


if __name__ == "__main__":
    unittest.main()
