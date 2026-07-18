import argparse
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "collect_residue_oof_v1_4.py"
GOVERNANCE = ROOT.parent / "PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json"
FREEZE = ROOT / "IMPLEMENTATION_FREEZE_V1_4.json"
spec = importlib.util.spec_from_file_location("residue_oof_v1_4", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestFrozenBootstrapMatrix(unittest.TestCase):
    def test_real_v14_freeze_closes_for_collector(self):
        hashes = mod.validate_implementation_freeze(FREEZE, ROOT, GOVERNANCE)
        self.assertEqual(hashes["src/collect_residue_oof_v1_4.py"], mod.sha256_file(MODULE))

    def test_parser_defaults_are_exactly_frozen(self):
        parsed = mod.parser().parse_args([
            "--training-tsv", "training.tsv",
            "--outer-run-dir", "fold0",
            "--output-dir", "output",
            "--implementation-freeze", "freeze.json",
            "--governance-amendment", "amendment.json",
        ])
        self.assertEqual(parsed.bootstrap_replicates, 1000)
        self.assertEqual(parsed.bootstrap_seed, 20260718)

    def test_exact_matrix_passes_and_nonfrozen_values_fail_closed(self):
        mod.validate_bootstrap_matrix(1000, 20260718)
        for repetitions, seed, expected in (
            (999, 20260718, "bootstrap_repetitions_not_frozen"),
            (2000, 20260718, "bootstrap_repetitions_not_frozen"),
            (1000, 20260719, "bootstrap_seed_not_frozen"),
        ):
            with self.subTest(repetitions=repetitions, seed=seed):
                with self.assertRaisesRegex(Exception, expected):
                    mod.validate_bootstrap_matrix(repetitions, seed)

    def test_collect_rejects_invalid_matrix_before_any_input_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base = dict(
                training_tsv=root / "missing.tsv",
                outer_run_dir=[root / f"fold{index}" for index in range(5)],
                output_dir=root / "output",
                implementation_freeze=root / "missing-freeze.json",
                governance_amendment=root / "missing-amendment.json",
                bootstrap_seed=20260718,
            )
            for repetitions in (999, 2000):
                with self.subTest(repetitions=repetitions):
                    args = argparse.Namespace(**base, bootstrap_replicates=repetitions)
                    with self.assertRaisesRegex(Exception, "bootstrap_repetitions_not_frozen"):
                        mod.collect(args)

    def test_matrix_binding_is_canonical_and_report_ready(self):
        expected = {
            "bootstrap_repetitions": 1000,
            "bootstrap_seed": 20260718,
            "governance_amendment_sha256": mod.GOVERNANCE_SHA256,
            "promotion_gate": mod.EXACT_PROMOTION_GATE,
            "schema_version": "pvrig_v6_residue_v1_4_collector_matrix",
        }
        self.assertEqual(mod.COLLECTOR_MATRIX, expected)
        canonical = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(mod.COLLECTOR_MATRIX_SHA256, hashlib.sha256(canonical).hexdigest())
        binding = mod.collector_matrix_binding()
        self.assertEqual(binding["collector_matrix"], expected)
        self.assertEqual(binding["collector_matrix_sha256"], mod.COLLECTOR_MATRIX_SHA256)
        self.assertIsNot(binding["collector_matrix"], mod.COLLECTOR_MATRIX)
        mod.validate_collector_matrix_binding(binding)
        for field, value, expected_error in (
            ("bootstrap_repetitions", 999, "freeze_collector_matrix_mismatch"),
            ("bootstrap_seed", 20260719, "freeze_collector_matrix_mismatch"),
        ):
            with self.subTest(field=field):
                tampered = mod.collector_matrix_binding()
                tampered["collector_matrix"][field] = value
                with self.assertRaisesRegex(Exception, expected_error):
                    mod.validate_collector_matrix_binding(tampered)
        tampered_hash = mod.collector_matrix_binding()
        tampered_hash["collector_matrix_sha256"] = "0" * 64
        with self.assertRaisesRegex(Exception, "freeze_collector_matrix_sha256_mismatch"):
            mod.validate_collector_matrix_binding(tampered_hash)


if __name__ == "__main__":
    unittest.main()
