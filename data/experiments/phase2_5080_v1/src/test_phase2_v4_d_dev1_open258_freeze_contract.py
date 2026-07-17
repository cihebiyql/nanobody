#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import stat
import unittest
from datetime import datetime
from pathlib import Path


EXP_DIR = Path(__file__).resolve().parents[1]
FREEZE = EXP_DIR / "audits/phase2_v4_d_dev1_open258_implementation_freeze_candidate.json"
PREREG = EXP_DIR / "audits/phase2_v4_d_dev1_open258_preregistration.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Dev1FreezeContractTest(unittest.TestCase):
    def test_candidate_freeze_is_hash_closed_and_not_launch_authorized(self) -> None:
        payload = json.loads(FREEZE.read_text())
        self.assertEqual(payload["status"], "CANDIDATE_FREEZE_BEFORE_REMOTE_OR_LABEL_ACCESS")
        self.assertFalse(payload["remote_execution_started"])
        self.assertFalse(payload["remote_execution_authorized"])
        self.assertEqual(payload["test32_raw_job_files_opened"], 0)
        self.assertEqual(payload["test32_metric_values_read"], 0)
        self.assertFalse(payload["formal_v4_f_unlock_eligible"])
        frozen = datetime.fromisoformat(payload["frozen_at_utc"]).timestamp()
        self.assertLessEqual(frozen, FREEZE.stat().st_mtime)
        files = payload["files"]
        required = {
            "preregistration", "builder", "v1_formula_helper", "delivery",
            "node23_launcher", "delivery_launcher", "builder_tests",
            "delivery_tests", "freeze_tests", "materializer", "pre_freeze_tests_log",
            "generic_prior_materializer", "generic_prior_tests",
            "generic_prior_extract", "generic_prior_audit",
        }
        self.assertEqual(set(files), required)
        for key, entry in files.items():
            path = EXP_DIR / entry["relative_path"]
            metadata = path.lstat()
            self.assertTrue(stat.S_ISREG(metadata.st_mode), key)
            self.assertEqual(digest(path), entry["sha256"], key)
            self.assertEqual(path.stat().st_size, entry["size"], key)

    def test_prereg_hash_is_bound_consistently_by_builder_and_delivery(self) -> None:
        expected = digest(PREREG)
        self.assertEqual(expected, "ee2c1076b0fd58b5bcb991f7646321c6fd03204746ff926f2d93940fec5ffe55")
        builder = (EXP_DIR / "src/prepare_phase2_v4_d_dev1_open258.py").read_text()
        delivery = (EXP_DIR / "src/deliver_phase2_v4_d_dev1_open258_from_node23.py").read_text()
        self.assertIn(expected, builder)
        self.assertIn(expected, delivery)

    def test_all_release_names_are_independent_from_formal_v4f(self) -> None:
        payload = json.loads(FREEZE.read_text())
        isolation = payload["formal_isolation"]
        self.assertEqual(isolation["dev_delivery_root_suffix"], "pvrig_v4_d_dev1_open258_v1/delivery_dev1")
        self.assertEqual(isolation["dev_future_training_root"], "runs/pvrig_v4_d_dev1_sequence_surrogate_v1")
        self.assertFalse(isolation["formal_completion_or_unlock_receipt_created"])
        for relative in (
            "src/prepare_phase2_v4_d_dev1_open258.py",
            "src/deliver_phase2_v4_d_dev1_open258_from_node23.py",
            "src/run_phase2_v4_d_dev1_open258_node23.sh",
            "src/launch_phase2_v4_d_dev1_delivery_v1.sh",
        ):
            source = (EXP_DIR / relative).read_text()
            self.assertNotIn("status/pvrig_v4_d_surrogate_training_v3", source)
            self.assertNotIn("predictions/pvrig_v4_f_surrogate_predictions_v1", source)
        launcher = (EXP_DIR / "src/run_phase2_v4_d_dev1_open258_node23.sh").read_text()
        prior = payload["runtime_input_candidate"]
        self.assertIn(prior["sha256"], launcher)
        self.assertIn(prior["node23_governance_path"], launcher)

    def test_only_reviewed_label_free_prior_data_is_in_freeze_closure(self) -> None:
        payload = json.loads(FREEZE.read_text())
        forbidden_suffixes = {".tsv", ".csv", ".pdb", ".pt", ".ckpt", ".tar.gz"}
        for key, entry in payload["files"].items():
            path = Path(entry["relative_path"])
            if key == "generic_prior_extract":
                self.assertEqual(path.name, "v4d_dev1_fullqc290_label_free_generic_prior_v1.csv")
            else:
                self.assertNotIn(path.suffix.lower(), forbidden_suffixes)
        prior = payload["runtime_input_candidate"]
        self.assertEqual(prior["status"], "LABEL_FREE_PRIOR_HASH_BOUND_NOT_REMOTE_AUTHORIZED")
        self.assertEqual(prior["row_count"], 290)
        self.assertTrue(prior["candidate_id_sequence_sha256_exact_closure"])
        self.assertEqual(prior["forbidden_docking_geometry_or_label_columns"], [])
        self.assertTrue(prior["numeric_validation"]["all_numeric_values_finite"])
        self.assertTrue(prior["numeric_validation"]["probability_fields_within_closed_unit_interval"])
        self.assertEqual(prior["test32_metric_values_read"], 0)
        self.assertFalse(prior["remote_execution_authorized"])
        self.assertEqual(payload["candidate_label_rows_read"], 0)


if __name__ == "__main__":
    unittest.main()
