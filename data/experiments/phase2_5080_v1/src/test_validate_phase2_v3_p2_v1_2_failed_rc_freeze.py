from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.phase2_5080_v1.src.validate_phase2_v3_p2_v1_2_failed_rc_freeze import (
    canonical_sha256,
    json_pointer,
    validate_payload,
)


class FailedRcFreezeValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary_directory.name)
        artifact_path = self.repo_root / "artifact.txt"
        artifact_path.write_text("frozen\n", encoding="utf-8")
        artifact = {
            "bytes": artifact_path.stat().st_size,
            "frozen": True,
            "path": "artifact.txt",
            "reuse_class": "PROVENANCE_ONLY",
            "role": "synthetic_test_artifact",
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        }
        artifacts = [artifact]
        self.payload = {
            "schema_version": "phase2_v3_p2_v1_2_failed_rc_freeze_manifest_v1",
            "status": "FROZEN_FAILED_RC_V1_2",
            "validation_outcome": "FAIL_DOCKING_GOLD_NOT_VALIDATED",
            "training_state": "P2_TRAINING_BLOCKED",
            "release_eligibility": {
                "threshold_freeze_eligible": False,
                "pose_rule_threshold_freeze_eligible": False,
                "single_8x6b_dock_run_method_freeze_eligible": False,
                "dual_receptor_r_gold_freeze_eligible": False,
                "training_label_release_eligible": False,
                "formal_eligible": False,
                "p2_training_ready": False,
                "continuous_input_provenance_reuse_only": True,
            },
            "failed_acceptance_gate": {
                "name": "bootstrap",
                "minimum_modal_probability": 0.70,
                "required_anchor_count": 9,
                "observed_anchor_count": 7,
                "total_anchor_count": 11,
            },
            "reuse_policy": {
                "mode": "CONTINUOUS_INPUT_AND_PROVENANCE_ONLY",
                "prohibited_uses": [
                    "CURRENT_ABC_E_OR_G1_G5_AS_GOLD_LABELS",
                    "CURRENT_R_CALIBRATION_RUN_8X6B_DOCK_AS_GOLD",
                    "P2_MODEL_TRAINING_OR_LABEL_RELEASE",
                    "SMOKE8_OR_FAILED52_SCORING_WITH_V1_2_RULES",
                    "DUAL_RECEPTOR_R_GOLD_CLAIM",
                    "FORMAL_HOLDOUT_OR_EXPERIMENTAL_TRUTH_CLAIM",
                    "RETROACTIVE_V1_2_GATE_OR_THRESHOLD_CHANGE",
                ],
            },
            "artifact_count": 1,
            "artifacts": artifacts,
            "artifact_inventory_sha256": canonical_sha256(artifacts),
            "hash_listing_contracts": [],
            "exact_directory_contracts": [],
            "semantic_assertion_count": 0,
            "semantic_assertions": [],
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_json_pointer(self) -> None:
        document = {"a/b": {"~key": ["zero", "one"]}}
        self.assertEqual(json_pointer(document, "/a~1b/~0key/1"), "one")

    def test_valid_payload_passes(self) -> None:
        result = validate_payload(self.payload, self.repo_root)
        self.assertTrue(result["valid"], result["errors"])

    def test_artifact_hash_drift_fails_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        (self.repo_root / "artifact.txt").write_text("drifted\n", encoding="utf-8")
        result = validate_payload(payload, self.repo_root)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("artifact SHA256 mismatch" in error for error in result["errors"]),
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
