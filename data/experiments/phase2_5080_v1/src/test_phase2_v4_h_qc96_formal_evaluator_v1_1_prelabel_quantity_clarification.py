#!/usr/bin/env python3
"""Regression tests for the label-free V4-H V1.1 quantity clarification."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


SRC_DIR = Path(__file__).resolve().parent
EXP_DIR = SRC_DIR.parent
V1_PREREG = EXP_DIR / "audits/phase2_v4_h_qc96_formal_evaluator_v1_preregistration.json"
V1_PROTOCOL = EXP_DIR / "audits/phase2_v4_h_qc96_formal_evaluator_v1_protocol.md"
V1_1 = EXP_DIR / "audits/phase2_v4_h_qc96_formal_evaluator_v1_1_prelabel_quantity_clarification.json"
EXPECTED_V1_PREREG_SHA256 = "0f0f5b546f71400b50d19e0f3f43cdb7b040c0c2765eef025ae43846df47d8d5"
EXPECTED_V1_PROTOCOL_SHA256 = "144c80dfc9af74bf5fc5b659960dc2a1d36b35433e3e003e665086028d3cc1cd"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class V4HPrelabelQuantityClarificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_json(V1_PREREG)
        cls.v1_1 = load_json(V1_1)
        cls.protocol = V1_PROTOCOL.read_text(encoding="utf-8")

    def test_v1_preregistration_and_protocol_bytes_are_unchanged(self) -> None:
        self.assertEqual(sha256_file(V1_PREREG), EXPECTED_V1_PREREG_SHA256)
        self.assertEqual(sha256_file(V1_PROTOCOL), EXPECTED_V1_PROTOCOL_SHA256)
        bindings = self.v1_1["v1_byte_bindings"]
        self.assertEqual(bindings["preregistration_sha256"], EXPECTED_V1_PREREG_SHA256)
        self.assertEqual(bindings["protocol_sha256"], EXPECTED_V1_PROTOCOL_SHA256)

    def test_original_ambiguous_text_is_preserved_not_silently_rewritten(self) -> None:
        ambiguous = self.v1_1["ambiguous_v1_wording"]
        self.assertEqual(
            self.v1["estimand"]["not_identified_for"][0],
            ambiguous["preregistration_text"],
        )
        self.assertIn(ambiguous["protocol_text"], self.protocol)

    def test_raw_and_selected_quantities_are_distinct_and_arithmetically_closed(self) -> None:
        semantics = self.v1_1["authoritative_quantity_semantics"]
        raw = semantics["raw_generator_record_universe"]
        selected = semantics["h1_selected_pre_qc_candidate_universe"]
        self.assertEqual(raw["count"], 12 * 6 * 36)
        self.assertEqual(raw["count"], 2592)
        self.assertEqual(selected["count"], 12 * 6 * 20)
        self.assertEqual(selected["count"], 1440)
        self.assertIs(raw["may_contain_exact_sequence_duplicates"], True)
        self.assertIs(selected["globally_exact_sequence_unique"], True)
        self.assertIn("sequence-SHA256 exact deduplication", selected["stage"])

    def test_estimand_and_all_scientific_contract_sections_are_unchanged(self) -> None:
        anchors = self.v1_1["unchanged_v1_contract_anchors"]
        sections = {
            "estimand_payload_sha256": "estimand",
            "scientific_evaluation_contract_payload_sha256": "scientific_evaluation_contract",
            "future_panel_contract_payload_sha256": "future_panel_contract",
            "future_prediction_freeze_contract_payload_sha256": "future_prediction_freeze_contract",
            "future_dual_docking_label_contract_payload_sha256": "future_dual_docking_label_contract",
            "one_shot_and_failure_policy_payload_sha256": "one_shot_and_failure_policy",
            "claim_boundary_payload_sha256": "claim_boundary",
        }
        for anchor_name, section_name in sections.items():
            self.assertEqual(anchors[anchor_name], sha256_json(self.v1[section_name]), section_name)
        for flag in (
            "scientific_metrics_or_thresholds_changed",
            "minimum_denominator_policy_changed",
            "estimand_changed",
            "panel_selection_or_replacement_policy_changed",
            "prediction_or_docking_contract_changed",
        ):
            self.assertIs(anchors[flag], False, flag)
        self.assertEqual(
            self.v1_1["authoritative_quantity_semantics"]["formal_estimand_remains"],
            self.v1["estimand"]["name"],
        )

    def test_clarification_remains_fully_label_free_and_creates_no_lock_or_output(self) -> None:
        state = self.v1_1["prelabel_state"]
        for key, value in state.items():
            if key.endswith("_opened") or key.endswith("_accepted"):
                self.assertEqual(value, 0, key)
            else:
                self.assertIs(value, False, key)
        self.assertEqual(
            self.v1_1["status"],
            "PRELABEL_QUANTITY_CLARIFICATION_ONLY_NO_SCIENTIFIC_OR_ESTIMAND_CHANGE",
        )

    def test_supersession_is_text_only(self) -> None:
        scope = self.v1_1["scope"]
        self.assertIn("Only the two ambiguous V1 quantity phrases", scope["supersedes"])
        self.assertIn("scientific metric", scope["does_not_supersede"])
        self.assertIn("2592 raw generator records", scope["future_reporting_requirement"])
        self.assertIn("1440 H1-selected exact-unique pre-QC candidates", scope["future_reporting_requirement"])


if __name__ == "__main__":
    unittest.main()
