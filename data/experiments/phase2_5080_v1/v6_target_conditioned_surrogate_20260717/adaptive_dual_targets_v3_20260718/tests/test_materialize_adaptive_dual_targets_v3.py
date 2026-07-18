#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tests"))
import materialize_adaptive_dual_targets_v3 as mod  # noqa: E402
from test_build_adaptive_dual_contact_targets_v3 import MarginalInputs  # noqa: E402


class Tests(unittest.TestCase):
    def test_materializes_two_tables_receipts_and_prefreeze_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inputs = MarginalInputs(root)
            source = json.loads(inputs.v4h_receipt.read_text())
            source.update({
                "selected_paired_job_rows": 2, "residue_rows": 8,
                "contract_sha256": "a" * 64, "reconciliation_receipt_sha256": "b" * 64,
                "implementation_sha256": "c" * 64,
            })
            inputs.v4h_receipt.write_text(json.dumps(source))
            counts = {
                "training_candidates": 2, "v4d_candidates": 1,
                "v4h_valid_candidates": 1, "v4h_technical_incomplete_excluded": 39,
                "v4h_source_candidates": 40, "v4h_selected_paired_jobs": 2,
            }
            with mock.patch.object(mod, "TRAINING_TSV_SHA256", mod.sha256_file(inputs.training)), \
                 mock.patch.object(mod, "EXPECTED_COUNTS", counts), \
                 mock.patch.object(mod, "EXPECTED_PARENT_COUNTS", {mod.pair.V4D: 1, mod.pair.V4H: 1}):
                receipt = mod.materialize(
                    training_tsv=inputs.training, v4d_pair_tsv=inputs.v4d_pair,
                    v4d_marginal_tsv=inputs.v4d_marginal, v4d_receipt=inputs.v4d_receipt,
                    v4h_pair_tsv=inputs.v4h_pair, v4h_residue_tsv=inputs.v4h_residue,
                    v4h_candidate_tsv=inputs.v4h_candidates, v4h_receipt=inputs.v4h_receipt,
                    target_cache_npz=inputs.target_cache, target_manifest_tsv=inputs.target_manifest,
                    target_receipt=inputs.target_receipt, output_root=root / "out",
                )
            self.assertEqual(receipt["status"], "PASS_V2_4_ADAPTIVE_DUAL_SOURCE_TABLES_AND_CONTRACT_MATERIALIZED")
            contract = json.loads((root / "out" / mod.CONTRACT_NAME).read_text())
            self.assertEqual(contract["schema_version"], mod.CONTRACT_SCHEMA)
            self.assertEqual(contract["expected_counts"], counts)
            self.assertEqual(set(contract["artifacts"]), {
                "v4h_adaptive_source_receipt", "v4d_source_receipt",
                "adaptive_marginal_tsv_gz", "adaptive_marginal_receipt",
                "adaptive_pair_tsv_gz", "adaptive_pair_receipt",
            })
            marginal_receipt = json.loads((root / "out" / "marginal" / mod.marginal.RECEIPT_NAME).read_text())
            pair_receipt = json.loads((root / "out" / "pair" / mod.pair.RECEIPT_NAME).read_text())
            self.assertEqual(marginal_receipt["schema_version"], mod.marginal.RECEIPT_SCHEMA)
            self.assertEqual(pair_receipt["schema_version"], mod.pair.RECEIPT_SCHEMA)
            self.assertEqual(marginal_receipt["legacy_stage1_rows"], 0)
            self.assertEqual(pair_receipt["legacy_stage1_rows"], 0)


if __name__ == "__main__":
    unittest.main()
