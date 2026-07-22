from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]
LOCAL_PREPARED = PKG.parent / "v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared"
REMOTE_PREPARED = Path("/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared")
PREPARED = LOCAL_PREPARED if LOCAL_PREPARED.is_dir() else REMOTE_PREPARED


def load_module():
    path = PKG / "src/materialize_phase_b_seed_contracts_v1.py"
    spec = importlib.util.spec_from_file_location("v213_phase_b_materializer_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


class PhaseBMaterializerTests(unittest.TestCase):
    def test_exact_ten_contracts_change_seed_only_plus_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(json.dumps({
                "status": "PASS_PHASE_A_VARIANT_PROMOTED",
                "selected_variant": "L2",
                "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            }))
            output = root / "nested/contracts"
            receipt = MOD.materialize(
                PKG / "PHASE_B_PROMOTION_CONTRACT_V1.json",
                selection,
                PREPARED,
                output,
            )
            self.assertEqual(receipt["counts"]["contracts"], 10)
            self.assertEqual(len(list(output.glob("seed_*_fold_*_contract.json"))), 10)
            for seed in MOD.SEEDS:
                for fold in MOD.FOLDS:
                    source = json.loads((PREPARED / f"fold_{fold}_contract.json").read_text())
                    actual = json.loads((output / f"seed_{seed}_fold_{fold}_contract.json").read_text())
                    expected = copy.deepcopy(source)
                    expected["task"] = {"fold_id": fold, "seed": seed}
                    provenance = actual.pop("phase_b_provenance")
                    self.assertEqual(actual, expected)
                    self.assertEqual(provenance["selected_variant"], "L2")
                    self.assertTrue(provenance["seed43_reused_not_retrained"])

    def test_nonzero_data_access_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.json"
            selection.write_text(json.dumps({
                "status": "PASS_PHASE_A_VARIANT_PROMOTED",
                "selected_variant": "L1",
                "input_access": {"open_development_rows": 1, "frozen_test_rows": 0},
            }))
            with self.assertRaisesRegex(MOD.MaterializationError, "selection_access"):
                MOD.materialize(PKG / "PHASE_B_PROMOTION_CONTRACT_V1.json", selection, PREPARED, root / "out")


if __name__ == "__main__":
    unittest.main()
