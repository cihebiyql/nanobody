from pathlib import Path
import importlib.util
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "prepare_pilot_campaign.py"
SPEC = importlib.util.spec_from_file_location("prepare_pilot_campaign", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def parent(i: int, cdr3_len: int) -> dict[str, str]:
    cdr3 = "Q" * cdr3_len
    return {
        "sequence_id": f"P{i:03d}",
        "sequence_aa": "A" * 78 + "YYC" + cdr3 + "WGQ" + "A" * 20 + chr(65 + i % 20),
        "cluster_id": f"C{i:04d}",
        "cdr1": "ABCDEFGH",
        "cdr2": "IJKLMNOP",
        "cdr3": cdr3,
        "cdr3_len": str(cdr3_len),
    }


class PreparePilotCampaignTest(unittest.TestCase):
    def test_build_tasks_has_exact_route_and_quota_counts(self):
        parents = []
        parents.extend(parent(i, 20) for i in range(89))
        parents.extend(parent(i, 16) for i in range(89, 145))
        parents.extend(parent(i, 14) for i in range(145, 200))
        spec = {
            "raw_generation_policy": {"initial_overgeneration_factor": 1.3},
            "routes": [
                {"route_id": "conservative_cdr_redesign"},
                {"route_id": "natural_cdr_donor"},
                {"route_id": "fixed_pose_mpnn_antifold"},
                {"route_id": "epitope_conditioned_rfantibody"},
                {"route_id": "denovo_disagreement_control"},
            ],
        }
        rows = MODULE.build_tasks(spec, parents, {"C0001"})
        self.assertEqual(len(rows), 32500)
        for route in spec["routes"]:
            subset = [row for row in rows if row["route_id"] == route["route_id"]]
            self.assertEqual(len(subset), 6500)
            self.assertEqual(sum(row["target_patch_assignment"] == "C_CROSS" for row in subset), 2600)
            self.assertEqual(sum(row["design_mode"] == "H1H2H3" for row in subset), 2925)
            self.assertEqual(sum(row["requested_cdr3_length_bin"] == "18_22" for row in subset), 4550)

    def test_cdr3_bins_are_explicit(self):
        self.assertEqual(MODULE.cdr3_bin(20), "18_22")
        self.assertEqual(MODULE.cdr3_bin(16), "16_17")
        self.assertEqual(MODULE.cdr3_bin(14), "10_15")
        self.assertEqual(MODULE.cdr3_bin(9), "other")

    def test_recovers_sequence_order_cdr3(self):
        sequence = "A" * 78 + "YYCABCDEFGHIJKLMNOPW" + "A" * 10
        self.assertEqual(MODULE.sequence_order_cdr3(sequence, 16), "ABCDEFGHIJKLMNOP")


if __name__ == "__main__":
    unittest.main()
