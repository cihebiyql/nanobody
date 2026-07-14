from __future__ import annotations

import copy
import json
import unittest

from experiments.phase2_5080_v1.src import (
    validate_phase2_v3_p2_v1_3_docking_execution_release as mod,
)


class V13DockingExecutionReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(mod.DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    def test_current_release_passes(self) -> None:
        self.assertEqual(mod.validate_payload(self.payload), [])

    def test_artifact_hash_drift_fails_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["artifacts"][0]["sha256"] = "0" * 64
        self.assertTrue(
            any("artifact_hash_mismatch" in error for error in mod.validate_payload(payload))
        )

    def test_formal_or_training_promotion_fails_closed(self) -> None:
        for field in ("formal_eligible", "training_label_release_eligible", "p2_training_ready"):
            payload = copy.deepcopy(self.payload)
            payload[field] = True
            self.assertIn(f"{field}_mismatch", mod.validate_payload(payload))


if __name__ == "__main__":
    unittest.main()
