import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("summarize_pvrig_teacher500_docking_status.py")
SPEC = importlib.util.spec_from_file_location("teacher_status", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class TeacherStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for shard, candidate in ((0, "A"), (1, "B")):
            shard_root = self.root / f"shard_{shard}"
            manifest = shard_root / "manifests/selected_candidates_manifest.tsv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_id"], delimiter="\t")
                writer.writeheader()
                writer.writerow({"candidate_id": candidate})
            (shard_root / "logs").mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_models(self, shard: int, candidate: str, count: int) -> None:
        selected = self.root / f"shard_{shard}" / "haddock3" / candidate / f"run_{candidate}_pvrig_hotspot" / "6_seletopclusts"
        selected.mkdir(parents=True)
        for index in range(count):
            (selected / f"cluster_1_model_{index + 1}.pdb").write_text("MODEL\n", encoding="utf-8")

    def test_latest_exit_overrides_historical_failure(self) -> None:
        log1 = self.root / "shard_0/logs/run_node1_v2_5_pose_batch.20260713_010000.log"
        log1.write_text("HADDOCK_START A now\nHADDOCK_EXIT A rc=1 now\n", encoding="utf-8")
        log2 = self.root / "shard_0/logs/run_node1_v2_5_pose_batch.20260713_020000.log"
        log2.write_text("HADDOCK_START A now\nHADDOCK_EXIT A rc=0 now\n", encoding="utf-8")
        other = self.root / "shard_1/logs/run_node1_v2_5_pose_batch.20260713_020000.log"
        other.write_text("HADDOCK_START B now\n", encoding="utf-8")
        self.add_models(0, "A", 4)

        status = MOD.summarize(self.root, expected_candidates=2, min_models=4)

        self.assertEqual(status["unique_started"], 2)
        self.assertEqual(status["latest_success"], 1)
        self.assertEqual(status["latest_failed"], 0)
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["model_ready"], 1)
        self.assertEqual(status["top_models"], 4)

    def test_archived_partial_run_is_not_counted(self) -> None:
        archived = self.root / "shard_0/haddock3/A/run_A_pvrig_hotspot.failed_rc1_20260713/6_seletopclusts"
        archived.mkdir(parents=True)
        for index in range(8):
            (archived / f"cluster_1_model_{index + 1}.pdb").write_text("MODEL\n", encoding="utf-8")

        status = MOD.summarize(self.root, expected_candidates=2, min_models=4)

        self.assertEqual(status["model_ready"], 0)
        self.assertEqual(status["top_models"], 0)

    def test_retry_start_invalidates_historical_success_until_new_exit(self) -> None:
        log1 = self.root / "shard_0/logs/run_node1_v2_5_pose_batch.20260713_010000.log"
        log1.write_text("HADDOCK_START A now\nHADDOCK_EXIT A rc=0 now\n", encoding="utf-8")
        log2 = self.root / "shard_0/logs/run_node1_v2_5_pose_batch.20260713_020000.log"
        log2.write_text("HADDOCK_START A retry\n", encoding="utf-8")

        status = MOD.summarize(self.root, expected_candidates=2, min_models=4)

        self.assertEqual(status["latest_success"], 0)
        self.assertEqual(status["latest_failed"], 0)
        self.assertEqual(status["pending"], 2)


if __name__ == "__main__":
    unittest.main()
