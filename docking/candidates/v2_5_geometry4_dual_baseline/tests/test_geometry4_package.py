#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
MANIFEST = ROOT / "manifests/geometry4_candidates.tsv"
POSTPROCESS = ROOT / "scripts/run_dual_baseline_postprocess.py"
EXPECTED = {
    "PV25-EF3F71502C71": "zym_test_359954",
    "PV25-8E96BF37FD37": "zym_test_3633872",
    "PV25-0B63D218E0F3": "zym_test_8787",
    "PV25-25F7D6778F87": "zym_test_108006",
}

spec = importlib.util.spec_from_file_location("geometry4_postprocess", POSTPROCESS)
postprocess = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(postprocess)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Geometry4PackageTests(unittest.TestCase):
    def test_manifest_matches_frozen_blinding_key(self) -> None:
        rows = read_tsv(MANIFEST)
        self.assertEqual({row["candidate_id"]: row["source_candidate_id"] for row in rows}, EXPECTED)
        self.assertEqual(len({row["vhh_seq_sha256"] for row in rows}), 4)

        key_path = REPO / "data/experiments/phase2_5080_v1/assays/pvrig_v2_5_prospective_v1/blinding_key.csv"
        with key_path.open(newline="", encoding="utf-8") as handle:
            key = {row["assay_sample_id"]: row for row in csv.DictReader(handle)}
        for row in rows:
            frozen = key[row["candidate_id"]]
            self.assertEqual(frozen["candidate_id"], row["source_candidate_id"])
            self.assertEqual(frozen["sequence_sha256"], row["vhh_seq_sha256"])
            self.assertEqual(hashlib.sha256(frozen["vhh_sequence"].encode()).hexdigest(), row["vhh_seq_sha256"])

    def test_only_pending_candidates_are_in_launcher(self) -> None:
        script = (ROOT / "scripts/run_pending_haddock3_node1.sh").read_text()
        self.assertIn("MAX_LOAD1=${GEOMETRY4_MAX_LOAD1:-64}", script)
        self.assertIn("value > 64", script)
        self.assertIn("LOAD_GATE_REFUSE", script)
        self.assertIn("REFUSE_INCOMPLETE_EXISTING_RUN", script)
        self.assertIn("REFUSE_CANDIDATE_LOCK_BUSY", script)
        self.assertIn(".geometry4_haddock.lock", script)
        self.assertNotIn("rm -rf", script)
        for candidate in ("zym_test_359954", "zym_test_3633872", "zym_test_8787"):
            self.assertIn(candidate, script)
        self.assertNotIn("CANDIDATES=(zym_test_108006", script)

    def test_guarded_waiter_is_bounded_idempotent_and_fail_closed(self) -> None:
        runner = (ROOT / "scripts/node1_guarded_haddock3_waiter.sh").read_text()
        deployer = (ROOT / "scripts/deploy_guarded_haddock3_waiter_node1.sh").read_text()
        self.assertIn("flock -n 9", runner)
        self.assertIn("MAX_WAIT_SECONDS=${GEOMETRY4_MAX_WAIT_SECONDS:-86400}", runner)
        self.assertIn('float(sys.argv[1]) < float(sys.argv[2])', runner)
        self.assertLess(
            runner.index("elapsed >= MAX_WAIT_SECONDS"),
            runner.index('float(sys.argv[1]) < float(sys.argv[2])'),
        )
        self.assertIn("REFUSE_INCOMPLETE_EXISTING_RUN", runner)
        self.assertIn("REFUSE_RUN_DIR_APPEARED_AFTER_GATE", runner)
        self.assertNotIn("rm -rf", runner)
        for candidate in ("zym_test_359954", "zym_test_3633872", "zym_test_8787"):
            self.assertIn(candidate, runner)
        self.assertNotIn("zym_test_108006", runner)
        self.assertIn('tmux -L "$socket" has-session', deployer)
        self.assertIn("TMUX_SOCKET=pvrig_v25_geometry4", deployer)
        self.assertIn("runner hash mismatch", deployer)
        self.assertIn("--status", deployer)
        self.assertNotIn("rm -rf", deployer)

    def test_reference_baselines_and_hotspot_map_exist(self) -> None:
        for relative in (
            "data/structures/8X6B.pdb",
            "data/structures/9E6Y.pdb",
            "data/structures/PVRIG_hotspot_set_v1.csv",
        ):
            self.assertTrue((REPO / relative).is_file(), relative)

    def test_completed_candidate_has_dual_baseline_consensus(self) -> None:
        row = next(item for item in read_tsv(MANIFEST) if item["source_candidate_id"] == "zym_test_108006")
        consensus = Path(row["workdir"]) / "reports" / row["consensus_filename"]
        self.assertTrue(consensus.is_file())
        with consensus.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        top = min(rows, key=lambda item: float(item["best_haddock_rank"]))
        self.assertEqual(top["best_haddock_rank"], "1")
        self.assertEqual(top["consensus_class"], "CONSENSUS_BLOCKER_LIKE_A")
        self.assertEqual(top["baseline_classes"], "8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_LIKE_A")

    def test_finalize_filter_requires_complete_two_baseline_run(self) -> None:
        fields = [
            "candidate_id",
            "import_status",
            "run_status",
            "baseline_count",
            "blocker_class",
            "hotspot_overlap_count",
            "total_vhh_pvrl2_residue_pair_occlusion",
            "cdr3_pvrl2_residue_pair_occlusion",
            "cdr3_occlusion_fraction",
        ]
        complete = {
            "candidate_id": "complete",
            "import_status": "IMPORTED",
            "run_status": "RUN",
            "baseline_count": "2",
            "blocker_class": "CONSENSUS_BLOCKER_LIKE_A",
            "hotspot_overlap_count": "15",
            "total_vhh_pvrl2_residue_pair_occlusion": "610",
            "cdr3_pvrl2_residue_pair_occlusion": "106",
            "cdr3_occlusion_fraction": "0.17",
        }
        rows = [
            complete,
            {**complete, "candidate_id": "not_run", "run_status": "NOT_RUN"},
            {**complete, "candidate_id": "one_baseline", "baseline_count": "1"},
            {**complete, "candidate_id": "bad_class", "blocker_class": "INCOMPLETE"},
            {**complete, "candidate_id": "missing_metric", "cdr3_occlusion_fraction": ""},
        ]
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / "audit.csv"
            finalize = Path(td) / "finalize.csv"
            with audit.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(postprocess.write_finalize_csv(audit, finalize), 1)
            with finalize.open(newline="", encoding="utf-8") as handle:
                self.assertEqual([row["candidate_id"] for row in csv.DictReader(handle)], ["complete"])


if __name__ == "__main__":
    unittest.main()
