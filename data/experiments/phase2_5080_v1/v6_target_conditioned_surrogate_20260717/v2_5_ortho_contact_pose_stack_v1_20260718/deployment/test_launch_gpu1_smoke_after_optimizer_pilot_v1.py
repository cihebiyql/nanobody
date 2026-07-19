import ast
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "launch_gpu1_smoke_after_optimizer_pilot_v1.py"


class AutostartContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text()
        cls.tree = ast.parse(cls.text)

    def test_waits_for_passed_six_variant_open_pilot(self):
        self.assertIn("PASS_INNER_ONLY_OPTIMIZER_PILOT_COMPLETE", self.text)
        self.assertIn('pilot.get("variants") == 6', self.text)
        self.assertIn('pilot.get("sealed_evaluation_access_count") == 0', self.text)

    def test_binds_audited_overlay_and_source_hashes(self):
        for digest in (
            "3ad5ad802b915421ec40d519118233f0a24ddcb6250ffdccd0880e17e19ac114",
            "ebf72b4460756dde25448ba98e5d6683686082edb395f6e214134974efcee221",
            "755b82b220dea0f857257ca773c0557d1c4a1c5c4b57a946f3eb20cdf377d27e",
            "8fb2fda3c9d1ab19b1ed881e9c13fff826efccc6c14238182ce784e205af6849",
            "95788336b963a3eaf953f6c5434e94840cfd18cd5bb2a3d6eabc2e590a68d0a4",
        ):
            self.assertIn(digest, self.text)

    def test_authorizes_only_gpu1_eight_cpu_sequential_smoke(self):
        self.assertIn('"physical_gpu": 1', self.text)
        self.assertIn('"max_cpu_per_process": 8', self.text)
        self.assertIn("I_ACCEPT_V2_5_GPU1_SEQUENTIAL_ONE_EPOCH_REAL_SMOKE", self.text)

    def test_launches_detached_and_persists_receipt(self):
        self.assertIn("start_new_session=True", self.text)
        self.assertIn("LAUNCH_RECEIPT.json", self.text)
        self.assertIn('"v4_f_test32_access_count": 0', self.text)


if __name__ == "__main__":
    unittest.main()
