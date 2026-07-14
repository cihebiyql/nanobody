from __future__ import annotations

import copy
import json
import unittest

from experiments.phase2_5080_v1.src import (
    validate_phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v2 as mod,
)


class AtomHetatmIdentityAmendmentV2ValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(mod.DEFAULT_AMENDMENT.read_text(encoding="utf-8"))
        audit_item = next(
            item
            for item in cls.payload["artifacts"]
            if item["role"] == mod.HETATM_AUDIT_ROLE
        )
        cls.audit = json.loads(
            mod.resolve_artifact(audit_item["path"]).read_text(encoding="utf-8")
        )

    def test_current_frozen_amendment_v2_passes(self) -> None:
        self.assertEqual(
            mod.sha256_file(mod.DEFAULT_AMENDMENT), mod.FROZEN_AMENDMENT_SHA256
        )
        self.assertEqual(mod.validate_payload(self.payload), [])

    def test_v1_supersession_and_atom_rules_are_immutable(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["supersedes"]["sha256"] = "0" * 64
        payload["normalization_rule"]["allowed_atom_name"] = "O"
        payload["receptor_rule"]["atom_identity_normalization"] = "terminal_oxt"
        errors = mod.validate_payload(payload)
        self.assertIn("supersedes_sha256_mismatch", errors)
        self.assertIn("normalization_rule_not_identical_to_v1", errors)
        self.assertIn("receptor_rule_not_identical_to_v1", errors)
        self.assertIn("supersedes_artifact_binding_mismatch", errors)

    def test_heavy_hetatm_rule_expansion_fails_closed(self) -> None:
        mutations = (
            ("applicable_chains", ["A"]),
            ("record_scope", "ATOM_and_HETATM"),
            ("identity_normalization", "terminal_oxt"),
            ("terminal_oxt_normalization_applies", True),
            ("reference_heavy_hetatm_identity_count_must_equal", 1),
            ("pose_heavy_hetatm_identity_count_must_equal", 1),
            ("raw_reference_pose_identity_must_match", False),
            ("any_heavy_hetatm_identity", "allow"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                payload["heavy_hetatm_rule"][field] = value
                self.assertIn(
                    f"heavy_hetatm_rule_{field}_mismatch",
                    mod.validate_payload(payload),
                )

    def test_nonzero_audit_hetatm_evidence_fails_closed(self) -> None:
        audit = copy.deepcopy(self.audit)
        audit["summary"]["chains"]["A"]["heavy_hetatm"][
            "pose_identity_count_total"
        ] = 1
        audit["summary"]["chains_by_receptor"]["8X6B"]["A"][
            "heavy_hetatm_pose_identity_count_total"
        ] = 1
        errors = mod.validate_audit_payload(audit)
        self.assertIn(
            "audit_chain_A_heavy_hetatm_pose_identity_count_total_mismatch",
            errors,
        )
        self.assertIn(
            "audit_receptor_8X6B_chain_A_heavy_hetatm_pose_identity_count_total_mismatch",
            errors,
        )

    def test_oxt_normalization_cannot_expand_to_hetatm(self) -> None:
        audit = copy.deepcopy(self.audit)
        audit["proposed_rule"]["oxt_normalization_record_scope"] = "ATOM_and_HETATM"
        audit["proposed_rule"]["heavy_hetatm_policy"] = "raw_exact_nonzero_allowed"
        errors = mod.validate_audit_payload(audit)
        self.assertIn("audit_oxt_record_scope_mismatch", errors)
        self.assertIn("audit_heavy_hetatm_policy_mismatch", errors)

    def test_side_effect_eligibility_and_artifact_drift_fail_closed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["side_effect_contract"]["coordinate_bytes_modified"] = True
        payload["eligibility"]["training_label_release_eligible"] = True
        payload["artifacts"][1]["sha256"] = "0" * 64
        errors = mod.validate_payload(payload)
        self.assertIn("side_effect_coordinate_bytes_modified_mismatch", errors)
        self.assertIn("eligibility_training_label_release_eligible_mismatch", errors)
        self.assertTrue(any(error.startswith("artifact_hash_mismatch:") for error in errors))

    def test_unsafe_artifact_paths_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsafe amendment artifact path"):
            mod.resolve_artifact("../escape.json")
        with self.assertRaisesRegex(ValueError, "Unsafe amendment artifact path"):
            mod.resolve_artifact("/tmp/escape.json")


if __name__ == "__main__":
    unittest.main()
