import pathlib
import sys
import tempfile
import unittest
from unittest import mock


HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "model"), str(ROOT / "trainer"), str(ROOT / "real1507")]
import residue_model_v2_5_ortho as model_mod
import train_v2_5_ortho_heads as trainer_mod
import run_real1507_split_v1 as mod

from test_residue_model_v2_5_ortho import make_model_and_inputs
from test_train_v2_5_ortho_heads import make_batch


class TestReal1507Runner(unittest.TestCase):
    def test_dynamic_adapter_can_import_real_sibling_module_and_restores_sys_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            sibling_name = "v25_real_sibling_module_for_regression"
            sibling = root / f"{sibling_name}.py"
            adapter = root / "adapter_with_sibling_import.py"
            sibling.write_text("VALUE = 1729\n")
            adapter.write_text(
                f"from {sibling_name} import VALUE\n"
                "ADAPTER_VALUE = VALUE\n"
            )
            digest = mod.sha256_file(adapter)
            before = list(sys.path)
            sys.modules.pop(sibling_name, None)
            try:
                with mock.patch.object(mod, "V24_ADAPTER_SHA256", digest):
                    loaded = mod.load_v24_adapter(adapter, digest)
                self.assertEqual(loaded.ADAPTER_VALUE, 1729)
                self.assertEqual(sys.path, before)
            finally:
                sys.modules.pop(sibling_name, None)

    def test_lane_variants_are_fixed_and_symmetric_between_e_modes(self):
        self.assertEqual(
            set(mod.LANE_SPECS),
            {"B_CLEAN_TARGET_ATTENTION", "E_DECOUPLED_CONTACT_DETACHED", "E_DECOUPLED_CONTACT_SHARED"},
        )
        clean = mod.LANE_SPECS["B_CLEAN_TARGET_ATTENTION"]
        detached = mod.LANE_SPECS["E_DECOUPLED_CONTACT_DETACHED"]
        shared = mod.LANE_SPECS["E_DECOUPLED_CONTACT_SHARED"]
        self.assertEqual((clean.marginal_weight, clean.pair_weight), (0.0, 0.0))
        self.assertEqual((detached.marginal_weight, detached.pair_weight), (1.0, 0.5))
        self.assertEqual((shared.marginal_weight, shared.pair_weight), (1.0, 0.5))
        self.assertEqual(detached.model_lane, shared.model_lane)
        self.assertEqual({detached.contact_encoder_gradient, shared.contact_encoder_gradient}, {"detached", "shared"})
        self.assertEqual(mod.FROZEN_TRAINING["gradient_accumulation"], 2)
        self.assertEqual(mod.FROZEN_TRAINING["precision"], "bf16")

    def test_preoptimizer_gradient_routing_for_all_three_variants(self):
        for variant, gradient_mode in (
            ("B_CLEAN_TARGET_ATTENTION", "detached"),
            ("E_DECOUPLED_CONTACT_DETACHED", "detached"),
            ("E_DECOUPLED_CONTACT_SHARED", "shared"),
        ):
            spec = mod.LANE_SPECS[variant]
            _config, model, inputs = make_model_and_inputs(spec.model_lane, gradient_mode)
            batch = make_batch(inputs, with_contacts=spec.model_lane == model_mod.LANE_E)
            batch["candidate_ids"] = ["A", "B"]
            telemetry = mod.preoptimizer_telemetry(
                model,
                spec.model_lane,
                batch,
                inputs["target_graphs"],
                mod.loss_config(spec),
                device_name="cpu",
                precision="fp32",
            )
            self.assertFalse(telemetry["optimizer_constructed"])
            self.assertEqual(telemetry["optimizer_steps"], 0)
            self.assertEqual(telemetry["prediction_metrics_access_count"], 0)
            self.assertEqual(telemetry["v4_f_test32_access_count"], 0)
            self.assertTrue(all(telemetry["gates"].values()))
            self.assertEqual(telemetry["scalar_gradient_role_l2"]["contact"], 0.0)
            self.assertEqual(telemetry["contact_gradient_role_l2"]["attention_scalar"], 0.0)
            if spec.model_lane == model_mod.LANE_B:
                self.assertEqual(telemetry["contact_gradient_role_l2"]["contact"], 0.0)
            else:
                self.assertGreater(telemetry["contact_gradient_role_l2"]["contact"], 0.0)
                observed_shared = telemetry["contact_gradient_role_l2"]["shared_encoder"] > 0.0
                self.assertEqual(observed_shared, gradient_mode == "shared")

    def test_parser_requires_only_open_real_inputs_and_modes(self):
        parser = mod.parser()
        required = [
            "--mode", "preoptimizer",
            "--lane-variant", "B_CLEAN_TARGET_ATTENTION",
            "--output-dir", "/tmp/out",
            "--v2-4-adapter-path", "/tmp/v24.py",
            "--v2-3-bundle-root", "/tmp/v23",
            "--training-tsv", "/tmp/train.tsv",
            "--contact-tsv-gz", "/tmp/m.tsv.gz",
            "--pair-contact-tsv-gz", "/tmp/p.tsv.gz",
            "--graph-cache-dir", "/tmp/graphs",
            "--target-graph-pt", "/tmp/target.pt",
            "--contact-formula-json", "/tmp/formula.json",
            "--split-manifest", "/tmp/split.json",
            "--model-path", "/tmp/esm",
            "--model-identity-file", "/tmp/esm/model.safetensors",
            "--expected-model-sha256", "0" * 64,
        ]
        args = parser.parse_args(required)
        self.assertEqual(args.expected_rows, 1269)
        self.assertEqual(args.expected_train_rows, 1085)
        with self.assertRaisesRegex(mod.Real1507RunnerError, "sealed_path_forbidden"):
            mod.reject_sealed_path(pathlib.Path("/tmp/V4-F/test32/labels.tsv"))


if __name__ == "__main__":
    unittest.main()
