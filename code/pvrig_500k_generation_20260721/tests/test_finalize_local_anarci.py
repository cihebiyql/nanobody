from pathlib import Path
import importlib.util
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "finalize_local_anarci.py"
SPEC = importlib.util.spec_from_file_location("finalize_local_anarci", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FinalizeLocalAnarciTest(unittest.TestCase):
    def test_region_uses_imgt_order_even_when_header_is_scrambled(self):
        row = {"117": "Y", "112": "Y", "112A": "Q", "111A": "L", "105": "A", "112B": "P", "111": "G"}
        self.assertEqual(MODULE.numbered_region(row, 105, 117), "AGLPQYY")

    def test_cdr2_midpoint_insertions_follow_sequence_order(self):
        row = {
            "56": "I",
            "57": "T",
            "58": "S",
            "59": "L",
            "60": "V",
            "60A": "S",
            "61A": "G",
            "61": "V",
            "62": "M",
            "63": "F",
            "64": "Y",
            "65": "K",
        }
        self.assertEqual(MODULE.numbered_region(row, 56, 65), "ITSLVSGVMFYK")

    def test_evaluate_accepts_complete_matching_regions(self):
        row = {str(i): "A" for i in range(1, 129)}
        row.update({"chain_type": "H", "hmm_species": "alpaca", "score": "200", "23": "C", "104": "C"})
        candidate = {
            "cdr1_after": MODULE.numbered_region(row, 27, 38),
            "cdr2_after": MODULE.numbered_region(row, 56, 65),
            "cdr3_after": MODULE.numbered_region(row, 105, 117),
        }
        result = MODULE.evaluate(candidate, row)
        self.assertEqual(result["anarci_qc_status"], "PASS")

    def test_freeze_effective_tops_up_each_route_without_duplicates(self):
        routes = ("conservative_cdr_redesign", "natural_cdr_donor")
        primary = []
        supplemental = []
        for route in routes:
            primary.extend(
                {
                    "route_id": route,
                    "anarci_qc_status": "PASS",
                    "candidate_id": f"{route}-p-{i}",
                    "sequence": f"{route}-p-seq-{i}",
                    "cdr3_after": f"P{i}{route}",
                }
                for i in range(2)
            )
            supplemental.extend(
                {
                    "route_id": route,
                    "anarci_qc_status": "PASS",
                    "candidate_id": f"{route}-s-{i}",
                    "sequence": f"{route}-s-seq-{i}",
                    "cdr3_after": f"S{i}{route}",
                }
                for i in range(2)
            )
        frozen = MODULE.freeze_effective(primary, supplemental, quota=3)
        self.assertEqual(len(frozen), 6)
        self.assertEqual({row["candidate_id"] for row in frozen}, {
            "conservative_cdr_redesign-p-0", "conservative_cdr_redesign-p-1",
            "conservative_cdr_redesign-s-0", "natural_cdr_donor-p-0",
            "natural_cdr_donor-p-1", "natural_cdr_donor-s-0",
        })


if __name__ == "__main__":
    unittest.main()
