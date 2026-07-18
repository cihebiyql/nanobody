import importlib.util
import pathlib
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "train_nested_residue_surrogate_v1_2.py"
spec = importlib.util.spec_from_file_location("residue_v1_2_trainer", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestCompleteResumeBinding(unittest.TestCase):
    def make_args(self):
        return types.SimpleNamespace(
            ridge_alpha=10.0,
            backbone_kind="hf",
            backbone_mode="lora",
            model_path=pathlib.Path("/models/esm2"),
            model_identity_file=pathlib.Path("/models/esm2/model.safetensors"),
            expected_model_sha256="model-sha",
            lora_r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            lora_target_modules="query,key,value",
            gradient_checkpointing=True,
            structure_dim=126,
            structure_prefix=list(mod.STRUCTURE_PREFIXES),
            fusion_dim=128,
            dropout=0.10,
            residual_scale=0.12,
            end_to_end_contact_pooling=False,
            dual_weight=1.0,
            receptor_weight=0.35,
            contact_weight=0.25,
            ranking_weight=0.10,
            residual_weight=0.05,
            huber_delta=0.03,
            ranking_minimum_delta=0.005,
            ranking_temperature=0.02,
            max_epochs=12,
            batch_size=8,
            per_parent_batch=2,
            gradient_accumulation=2,
            head_learning_rate=2e-4,
            lora_learning_rate=2e-5,
            weight_decay=0.01,
            warmup_steps=10,
            gradient_clip=1.0,
            precision="bf16",
            seed=43,
            safe_stop_free_gb=150.0,
            checkpoint_min_free_gb=180.0,
            trust_remote_code=False,
            tiny_hidden_size=16,
        )

    def test_every_result_affecting_category_changes_binding_and_rejects_resume(self):
        args = self.make_args()
        external = {
            "training_sha256": "training",
            "contact_sha256": "contact",
            "contact_receipt_sha256": "receipt",
            "contact_validation_sha256": "validation",
            "implementation_freeze_sha256": "implementation",
        }
        baseline = mod.result_affecting_binding(args, [f"F{i}" for i in range(126)], external, outer_fold=2)
        baseline_hash = mod.binding_hash(baseline)
        mutations = {
            "ridge_alpha": 11.0,
            "backbone_kind": "tiny",
            "backbone_mode": "frozen",
            "model_path": pathlib.Path("/models/other"),
            "model_identity_file": pathlib.Path("/models/other/model.safetensors"),
            "expected_model_sha256": "different-model",
            "lora_r": 4,
            "lora_alpha": 32,
            "lora_dropout": 0.1,
            "lora_target_modules": "q_proj,v_proj",
            "gradient_checkpointing": False,
            "structure_dim": 125,
            "structure_prefix": ["DIFFERENT__"],
            "fusion_dim": 64,
            "dropout": 0.2,
            "residual_scale": 0.2,
            "end_to_end_contact_pooling": True,
            "dual_weight": 0.9,
            "receptor_weight": 0.2,
            "contact_weight": 0.3,
            "ranking_weight": 0.2,
            "residual_weight": 0.1,
            "huber_delta": 0.04,
            "ranking_minimum_delta": 0.01,
            "ranking_temperature": 0.04,
            "max_epochs": 13,
            "batch_size": 10,
            "per_parent_batch": 1,
            "gradient_accumulation": 4,
            "head_learning_rate": 1e-4,
            "lora_learning_rate": 1e-5,
            "weight_decay": 0.02,
            "warmup_steps": 20,
            "gradient_clip": 0.5,
            "precision": "fp32",
            "seed": 44,
            "safe_stop_free_gb": 151.0,
            "checkpoint_min_free_gb": 181.0,
            "trust_remote_code": True,
            "tiny_hidden_size": 32,
        }
        for field, changed_value in mutations.items():
            with self.subTest(field=field):
                changed = self.make_args()
                setattr(changed, field, changed_value)
                changed_binding = mod.result_affecting_binding(changed, [f"F{i}" for i in range(126)], external, outer_fold=2)
                changed_hash = mod.binding_hash(changed_binding)
                self.assertNotEqual(changed_hash, baseline_hash)
                with self.assertRaisesRegex(Exception, "resume_binding_hash_mismatch"):
                    mod.assert_resume_binding(baseline_hash, changed_hash)

    def test_feature_order_external_hash_and_outer_fold_are_bound(self):
        args = self.make_args()
        external = {"training_sha256": "a"}
        baseline = mod.binding_hash(mod.result_affecting_binding(args, ["A", "B"], external, 0))
        variants = [
            mod.result_affecting_binding(args, ["B", "A"], external, 0),
            mod.result_affecting_binding(args, ["A", "B"], {"training_sha256": "b"}, 0),
            mod.result_affecting_binding(args, ["A", "B"], external, 1),
        ]
        self.assertTrue(all(mod.binding_hash(value) != baseline for value in variants))

    def test_actual_resume_rejects_changed_config_before_model_construction(self):
        helper_module_path = ROOT / "tests" / "test_train_nested_residue_surrogate_v1_1.py"
        helper_spec = importlib.util.spec_from_file_location("v1_1_test_fixture", helper_module_path)
        helper_module = importlib.util.module_from_spec(helper_spec)
        assert helper_spec.loader
        helper_spec.loader.exec_module(helper_module)
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, contact, receipt = helper_module.TestV11EndToEndResume().write_fixture(root)
            argv = [
                "--training-tsv", str(training), "--contact-tsv-gz", str(contact),
                "--contact-receipt", str(receipt), "--output-dir", str(root / "run"),
                "--smoke-mode", "--structure-prefix", "feature_", "--structure-dim", "4",
                "--outer-fold", "0", "--ridge-alpha", "1", "--backbone-kind", "tiny",
                "--backbone-mode", "frozen", "--tiny-hidden-size", "8", "--fusion-dim", "8",
                "--max-epochs", "1", "--batch-size", "4", "--per-parent-batch", "2",
                "--gradient-accumulation", "2", "--precision", "fp32", "--device", "cpu",
                "--safe-stop-free-gb", "0", "--checkpoint-min-free-gb", "0",
            ]
            args = mod.parser().parse_args(argv)
            self.assertEqual(mod.train(args)["status"], "PASS_OUTER_FOLD_COMPLETE")
            args.resume = True
            args.ridge_alpha = 2.0
            original_build_model = mod.build_model
            mod.build_model = lambda *_args, **_kwargs: self.fail("model construction occurred before resume binding rejection")
            try:
                with self.assertRaisesRegex(Exception, "resume_binding_hash_mismatch"):
                    mod.train(args)
            finally:
                mod.build_model = original_build_model


if __name__ == "__main__":
    unittest.main()
