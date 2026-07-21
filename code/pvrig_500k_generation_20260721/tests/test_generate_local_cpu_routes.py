from pathlib import Path
import importlib.util
import random
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "generate_local_cpu_routes.py"
SPEC = importlib.util.spec_from_file_location("generate_local_cpu_routes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GenerateLocalCpuRoutesTest(unittest.TestCase):
    def test_conservative_mutation_changes_non_cysteine_sequence(self):
        sequence = "ASSTYYG"
        mutated = MODULE.conservative_mutate(sequence, random.Random(7))
        self.assertNotEqual(mutated, sequence)
        self.assertEqual(len(mutated), len(sequence))
        self.assertNotIn("C", mutated)

    def test_replace_cdr_is_fail_closed(self):
        self.assertEqual(MODULE.replace_cdr("AAABBBCCC", "BBB", "DDD"), "AAADDDCCC")
        with self.assertRaises(ValueError):
            MODULE.replace_cdr("AAABBBCCCBBB", "BBB", "DDD")

    def test_fast_qc_rejects_positive_identity(self):
        cdrs = {"cdr1": "GFTFGTSS", "cdr2": "AAAAAAAA", "cdr3": "AAAAAAAAAAAAAA"}
        positive = {"tab5": {"cdr1": "GFTFGTSS", "cdr2": "ISFDGTEI", "cdr3": "AKGSGNIYYFSGMDV"}}
        sequence = "Q" * 40 + cdrs["cdr1"] + "Q" * 20 + cdrs["cdr2"] + "Q" * 20 + cdrs["cdr3"] + "Q" * 10
        result = MODULE.fast_qc(sequence, cdrs, "A" * len(sequence), positive)
        self.assertEqual(result["fast_qc_status"], "FAIL")
        self.assertIn("positive_any_cdr_identity_ge_80pct", result["fast_qc_reasons"])

    def test_hydrophobic_run(self):
        self.assertEqual(MODULE.longest_hydrophobic_run("AAAKRWWWWWA"), 6)

    def test_recovers_sequence_order_cdr3(self):
        sequence = "A" * 78 + "YYCABCDEFGHIJKLMNOPW" + "A" * 10
        self.assertEqual(MODULE.sequence_order_cdr3(sequence, 16), "ABCDEFGHIJKLMNOP")


if __name__ == "__main__":
    unittest.main()
