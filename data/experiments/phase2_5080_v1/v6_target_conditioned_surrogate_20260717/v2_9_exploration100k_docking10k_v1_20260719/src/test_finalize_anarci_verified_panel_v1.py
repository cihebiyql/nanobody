from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("finalize_anarci_verified_panel_v1.py")
SPEC = importlib.util.spec_from_file_location("finalize_panel", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FinalizePanelTests(unittest.TestCase):
    def write_inputs(self, root: Path, pass_second: bool = True) -> tuple[Path, Path]:
        sequences = ["QVQLVESGGGLVQAGGSLRLSCAASGFTFSSYAMGWFRQAPGKEREFVAAISWNSGSTYYADSVKGRFTISRDNAKNTVYLQMNSLKPEDTAVYYCAAGGGYWGQGTQVTVSS",
                     "QVQLVESGGGLVQAGGSLRLSCAASGFTFSSYAMGWFRQAPGKEREFVAAISWNSGSTYYADSVKGRFTISRDNAKNTVYLQMNSLKPEDTAVYYCAAGGSYWGQGTQVTVSS"]
        panel = pd.DataFrame({
            "candidate_id": ["A", "B"],
            "sequence": sequences,
            "sequence_sha256": [hashlib.sha256(x.encode()).hexdigest() for x in sequences],
            "parent_framework_cluster": ["P1", "P2"],
        })
        ledger = pd.DataFrame({
            "candidate_id": ["A", "B"],
            "anarci_imgt_pass": ["true", "true" if pass_second else "false"],
            "anarci_chain_type": ["H", "H"], "anarci_hmm_species": ["alpaca", "alpaca"],
            "anarci_e_value": ["0", "0"], "anarci_score": ["100", "100"],
            "anarci_position1_present": ["true", "true"], "anarci_position128_present": ["true", "true"],
            "anarci_cdr1": ["GFTFSSYA", "GFTFSSYA"], "anarci_cdr2": ["ISWNSGST", "ISWNSGST"],
            "anarci_cdr3": ["AAGGGY", "AAGGSY"], "anarci_failure_reason": ["", ""],
        })
        panel_path, ledger_path = root / "panel.tsv", root / "ledger.tsv"
        panel.to_csv(panel_path, sep="\t", index=False); ledger.to_csv(ledger_path, sep="\t", index=False)
        return panel_path, ledger_path

    def test_success_emits_hash_bound_structure_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); panel, ledger = self.write_inputs(root)
            receipt = MODULE.run(panel, ledger, root / "out", 2)
            self.assertEqual(receipt["status"], "PASS_STRUCTURE_INPUT_FREEZE")
            manifest = pd.read_csv(root / "out/structure_candidates10000.tsv", sep="\t")
            self.assertEqual(set(manifest.research_pool_state), {"RESEARCH_READY"})

    def test_fail_closed_on_selected_anarci_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); panel, ledger = self.write_inputs(root, pass_second=False)
            with self.assertRaisesRegex(RuntimeError, "selected_anarci_failure"):
                MODULE.run(panel, ledger, root / "out", 2)


if __name__ == "__main__":
    unittest.main()
