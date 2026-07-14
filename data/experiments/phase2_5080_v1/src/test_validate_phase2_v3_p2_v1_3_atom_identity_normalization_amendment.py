from __future__ import annotations

import copy
import json
import unittest

from experiments.phase2_5080_v1.src import (
    validate_phase2_v3_p2_v1_3_atom_identity_normalization_amendment as mod,
)


class AtomIdentityNormalizationAmendmentValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(mod.DEFAULT_AMENDMENT.read_text(encoding="utf-8"))

    def test_current_frozen_amendment_passes(self) -> None:
        self.assertEqual(mod.sha256_file(mod.DEFAULT_AMENDMENT), mod.FROZEN_AMENDMENT_SHA256)
        self.assertEqual(mod.validate_payload(self.payload), [])

    def test_rule_expansion_fails_closed(self) -> None:
        mutations = (
            ("allowed_atom_name", "O"),
            ("symmetric_difference_maximum_atom_identities", 2),
            ("non_terminal_oxt_allowed", True),
            ("all_other_atom_or_residue_differences", "ignore"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                payload["normalization_rule"][field] = value
                self.assertTrue(
                    any(field in error for error in mod.validate_payload(payload))
                )

    def test_receptor_normalization_and_side_effects_fail_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["receptor_rule"]["atom_identity_normalization"] = "terminal_oxt"
        payload["side_effect_contract"]["coordinate_bytes_modified"] = True
        errors = mod.validate_payload(payload)
        self.assertIn("receptor_rule_atom_identity_normalization_mismatch", errors)
        self.assertIn("side_effect_coordinate_bytes_modified_mismatch", errors)

    def test_formal_training_or_artifact_drift_fails_closed(self) -> None:
        for field in (
            "formal_eligible", "training_label_release_eligible",
            "docking_gold_release_eligible", "p2_training_ready",
        ):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                payload["eligibility"][field] = True
                self.assertIn(f"eligibility_{field}_mismatch", mod.validate_payload(payload))
        payload = copy.deepcopy(self.payload)
        payload["artifacts"][0]["sha256"] = "0" * 64
        self.assertTrue(
            any("artifact_hash_mismatch" in error for error in mod.validate_payload(payload))
        )


if __name__ == "__main__":
    unittest.main()
