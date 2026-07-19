import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json"
SPEC = importlib.util.spec_from_file_location("v25_cross_lane_validator", ROOT / "validate_cross_lane_contract_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CrossLaneContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT.read_text())

    def validate(self, contract=None, hashes=False):
        return MODULE.validate(contract or self.contract, ROOT, verify_upstream_hashes=hashes)

    def test_frozen_contract_and_upstream_hashes_pass(self):
        result = self.validate(hashes=True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["primary_lane"], "E_DECOUPLED_CONTACT_SHARED")
        self.assertEqual(result["upstream_hashes_checked"], 5)
        self.assertEqual(result["v4_f_test32_access_count"], 0)

    def test_posthoc_primary_lane_switch_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["lane_roles"]["formal_primary_base_lane"] = "B_CLEAN_TARGET_ATTENTION"
        with self.assertRaisesRegex(MODULE.ContractError, "primary_lane_changed"):
            self.validate(changed)

    def test_posthoc_selection_flag_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["preobservation_assertions"]["posthoc_lane_selection_allowed"] = True
        with self.assertRaisesRegex(MODULE.ContractError, "posthoc_lane_selection_enabled"):
            self.validate(changed)

    def test_sealed_access_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["preobservation_assertions"]["v4_f_test32_access_count"] = 1
        with self.assertRaisesRegex(MODULE.ContractError, "sealed_access_nonzero"):
            self.validate(changed)

    def test_missing_persisted_contact_field_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["primary_stack"]["raw_required_fields"].remove("contact_score_R9")
        with self.assertRaisesRegex(MODULE.ContractError, "required_raw_fields_changed"):
            self.validate(changed)

    def test_unpersisted_contact_dimension_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["primary_stack"]["contact_feature_policy"]["full_14d_contact_summary_allowed"] = True
        with self.assertRaisesRegex(MODULE.ContractError, "unpersisted_contact_enabled"):
            self.validate(changed)

    def test_free_rdual_fails(self):
        changed = copy.deepcopy(self.contract)
        changed["prediction_contract"]["independent_Rdual_output_allowed"] = True
        with self.assertRaisesRegex(MODULE.ContractError, "free_rdual_enabled"):
            self.validate(changed)

    def test_contact_minus_m2_guard_fails_closed(self):
        changed = copy.deepcopy(self.contract)
        changed["primary_stack"]["formula"]["forbidden_formula"] = ""
        with self.assertRaisesRegex(MODULE.ContractError, "contact_minus_m2_guard_missing"):
            self.validate(changed)

    def test_exact_m2_fallback_is_required(self):
        changed = copy.deepcopy(self.contract)
        changed["primary_stack"]["exact_m2_fallback"]["candidate_parameters"]["beta_C"] = 0.01
        with self.assertRaisesRegex(MODULE.ContractError, "m2_fallback_not_exact"):
            self.validate(changed)

    def test_source_gate_is_required(self):
        changed = copy.deepcopy(self.contract)
        changed["promotion_gate"]["each_source_Rdual_mae_nonregression_vs_M2"] = False
        with self.assertRaisesRegex(MODULE.ContractError, "source_mae_gate_removed"):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
