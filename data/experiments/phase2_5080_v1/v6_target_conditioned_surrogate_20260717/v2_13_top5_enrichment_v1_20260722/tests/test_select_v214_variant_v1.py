from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]
LOCAL_INPUT = PKG / "inputs/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv"
REMOTE_INPUT = Path("/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/training/oof_seed43_v1/OOF_AGGREGATE/CLEAN_ATTENTION_TRAIN9849_OOF_PREDICTIONS.tsv")
INPUT = LOCAL_INPUT if LOCAL_INPUT.is_file() else REMOTE_INPUT
CONTRACT = PKG / "V2_14_PROMOTION_CONTRACT_V1.json"


def load_module():
    path = PKG / "src/select_v214_variant_v1.py"
    spec = importlib.util.spec_from_file_location("v214_selector_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def write_variant(source: Path, root: Path, variant: str, *, perfect: bool) -> None:
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    output_rows = []
    for row in rows:
        prediction = row["truth_Rdual_exact_min"] if perfect else row["B_CLEAN_TARGET_ATTENTION__Rdual_exact_min"]
        output_rows.append({
            "candidate_id": row["candidate_id"],
            "fold_id": row["fold_id"],
            "truth_Rdual_exact_min": row["truth_Rdual_exact_min"],
            f"B_TOP5_{variant}__Rdual_exact_min": prediction,
        })
    path = root / variant / "OOF_AGGREGATE" / f"V214_{variant}_TRAIN9849_OOF_PREDICTIONS.tsv"
    path.parent.mkdir(parents=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(output_rows)


class V214SelectionTests(unittest.TestCase):
    def test_perfect_tie_prefers_simpler_n1(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for variant in MOD.VARIANTS:
                write_variant(INPUT, root, variant, perfect=True)
            result = MOD.select(CONTRACT, INPUT, root, root / "selection.json")
            self.assertEqual(result["status"], "PASS_V2_14_VARIANT_PROMOTED")
            self.assertEqual(result["selected_variant"], "N1")
            self.assertEqual(result["eligible_variants"], ["N1", "N2", "N3"])

    def test_baseline_clones_fail_frozen_improvement_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for variant in MOD.VARIANTS:
                write_variant(INPUT, root, variant, perfect=False)
            result = MOD.select(CONTRACT, INPUT, root, root / "selection.json")
            self.assertEqual(result["status"], "FAIL_NO_V2_14_LISTWISE_VARIANT_ELIGIBLE")
            self.assertIsNone(result["selected_variant"])


if __name__ == "__main__":
    unittest.main()
