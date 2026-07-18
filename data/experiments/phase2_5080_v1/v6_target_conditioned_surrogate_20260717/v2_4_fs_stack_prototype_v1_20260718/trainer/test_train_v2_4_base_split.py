import argparse
import csv
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import torch


HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train_v2_4_base_split as mod


def tiny_args(output_dir: pathlib.Path, lane: str) -> argparse.Namespace:
    return argparse.Namespace(
        lane=lane,
        output_dir=output_dir,
        split_manifest=None,
        v2_3_bundle_root=None,
        training_tsv=None,
        contact_tsv_gz=None,
        graph_cache_dir=None,
        target_graph_pt=None,
        pair_contact_tsv_gz=None,
        contact_formula_json=None,
        structure_prefix=[],
        structure_dim=126,
        backbone_kind="tiny",
        model_path=None,
        model_identity_file=None,
        expected_model_sha256=None,
        trust_remote_code=False,
        tiny_hidden_size=12,
        graph_hidden_dim=32,
        dropout=0.0,
        fixed_epochs=1,
        batch_size=4,
        learning_rate=1e-3,
        weight_decay=0.0,
        gradient_clip=1.0,
        gradient_accumulation=2,
        precision="fp32",
        device="cpu",
        huber_delta=0.03,
        receptor_weight=1.0,
        dual_weight=0.5,
        marginal_weight=0.01,
        pair_weight=0.005,
        ridge_alpha=10.0,
        seed=43,
        tiny_e2e=True,
    )


class TestV24BaseTrainer(unittest.TestCase):
    def test_all_four_lanes_complete_tiny_e2e_with_receptor_explicit_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for lane in mod.LANES:
                output = root / lane
                receipt = mod.run_tiny(tiny_args(output, lane))
                self.assertEqual(receipt["status"], "PASS_OPEN_BASE_SPLIT_COMPLETE")
                self.assertEqual(receipt["lane"], lane)
                self.assertEqual(receipt["fixed_epoch_selection"], "NONE_FIXED_EPOCH_ONLY")
                self.assertEqual(receipt["neural_feature_firewall"], {"M2": False, "126D": False, "structure_features": False})
                self.assertTrue(receipt["m2_branch"]["independent"])
                self.assertEqual(receipt["v4_f_test32_access_count"], 0)
                telemetry = receipt["training"]["component_gradient"]
                self.assertEqual(set(telemetry["gradient_l2_norm"]), {"scalar", "contact"})
                self.assertGreater(telemetry["gradient_l2_norm"]["scalar"], 0.0)
                if lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}:
                    self.assertGreater(telemetry["gradient_l2_norm"]["contact"], 0.0)
                    self.assertIsNotNone(telemetry["scalar_contact_cosine"])
                else:
                    self.assertEqual(telemetry["gradient_l2_norm"]["contact"], 0.0)
                    self.assertIsNone(telemetry["scalar_contact_cosine"])

                with (output / "base_score_predictions.tsv").open(newline="") as handle:
                    rows = list(csv.DictReader(handle, delimiter="\t"))
                self.assertEqual(len(rows), 4)
                for row in rows:
                    self.assertAlmostEqual(float(row["truth_Rdual"]), min(float(row["truth_R8"]), float(row["truth_R9"])), places=8)
                    self.assertAlmostEqual(float(row["M2_Rdual"]), min(float(row["M2_R8"]), float(row["M2_R9"])), places=8)
                    self.assertAlmostEqual(float(row["neural_Rdual"]), min(float(row["neural_R8"]), float(row["neural_R9"])), places=7)
                    self.assertEqual(row["base_training_parent_set_sha256"], receipt["split"]["train_parent_set_sha256"])
                    for field in ("contact_score_R8", "contact_score_R9"):
                        self.assertTrue(np.isfinite(float(row[field])))
                    self.assertEqual(row["base_model_receipt_sha256"], receipt["artifacts"]["component_receipts"]["sha256"])
                    expected_role = (
                        "diagnostic_non_stack_vhh_marginal_mean"
                        if lane == "A_VHH_ONLY" else "stack_eligible_pvrig_contact_composite"
                    )
                    self.assertEqual(row["contact_score_role"], expected_role)
                    self.assertEqual(
                        row["contact_score_formula_sha256"],
                        "" if lane == "A_VHH_ONLY" else mod.CONTACT_FORMULA_SHA256,
                    )
                for artifact in ("m2_ridge.json", "neural_head.pt", "component_receipts.json", "contact_score_formula_v1.json", "RESULT.json", "receipt.json"):
                    self.assertTrue((output / artifact).is_file())
                component = json.loads((output / "component_receipts.json").read_text())
                self.assertTrue(component["contact_uncertainty_used"])
                self.assertEqual(component["contact_formula_receipt"]["sha256"], mod.CONTACT_FORMULA_SHA256)
                self.assertEqual(component["contact_formula_receipt"]["formula_version"], mod.CONTACT_FORMULA_VERSION)
                self.assertEqual(component["contact_formula_receipt"]["weights"], mod.CONTACT_FORMULA_WEIGHTS)
                self.assertEqual(receipt["contact_score_formula_receipt_sha256"], mod.CONTACT_FORMULA_SHA256)
                self.assertEqual(receipt["artifacts"]["contact_score_formula"]["sha256"], mod.CONTACT_FORMULA_SHA256)
                self.assertEqual(component["contact_score_component"]["stack_eligible"], lane != "A_VHH_ONLY")
                if lane == "A_VHH_ONLY":
                    self.assertEqual(receipt["contact_score_component_role"], "diagnostic_non_stack_vhh_marginal_mean")
                    self.assertFalse(receipt["contact_score_stack_eligible"])
                    self.assertFalse(component["contact_formula_receipt"]["applied_to_lane"])
                else:
                    self.assertIn("0.5*", component["contact_score_component"]["R8"])
                    self.assertTrue(receipt["contact_score_stack_eligible"])
                    self.assertTrue(component["contact_formula_receipt"]["applied_to_lane"])

    def test_prestep_contact_calibration_observes_grid_without_optimizer(self):
        rows, manifest = mod.build_tiny_panel()
        args = tiny_args(pathlib.Path("unused"), "C_SPLIT_MARGINAL")
        args.calibration_grid = [0.0001, 0.001]
        args.pair_to_marginal_ratio = 0.5
        args.target_gradient_fraction_band = [0.0, 1.0]
        backbone, _tokenizer, hidden, _identity = mod.load_backbone(args, None)
        config = mod.ResidueV24Config(
            backbone_hidden_size=hidden, target_node_dim=7,
            graph_hidden_dim=args.graph_hidden_dim, dropout=args.dropout,
        )
        model = mod.build_model(args.lane, backbone, config)
        result = mod.observe_prestep_contact_gradient_grid(
            model, args.lane, rows, manifest,
            mod.TinyBatchFactory(rows, config.edge_feature_dim, args.batch_size, args.seed),
            mod.tiny_target_graphs(config), args,
        )
        self.assertFalse(result["optimizer_constructed"])
        self.assertEqual(result["optimizer_steps_before_observation"], 0)
        self.assertEqual(result["selected_contact_weights"]["marginal"], 0.0001)
        self.assertEqual(len(result["observations"]), 2)

    def test_split_manifest_overlap_hash_and_fixed_epoch_fail_closed(self):
        rows, manifest = mod.build_tiny_panel()
        overlap = mod.SplitManifest(
            manifest.split_id,
            manifest.outer_fold,
            manifest.train_parents,
            (manifest.train_parents[0],),
            manifest.fixed_epochs,
            True,
            0,
            manifest.train_parent_set_sha256,
            mod.canonical_parent_set_sha256((manifest.train_parents[0],)),
        )
        with self.assertRaisesRegex(mod.BaseTrainerError, "split_parent_overlap"):
            overlap.validate(rows, 1)
        bad_hash = mod.SplitManifest(
            manifest.split_id,
            manifest.outer_fold,
            manifest.train_parents,
            manifest.score_parents,
            manifest.fixed_epochs,
            True,
            0,
            "0" * 64,
            manifest.score_parent_set_sha256,
        )
        with self.assertRaisesRegex(mod.BaseTrainerError, "train_parent_hash"):
            bad_hash.validate(rows, 1)
        with self.assertRaisesRegex(mod.BaseTrainerError, "fixed_epoch_contract"):
            manifest.validate(rows, 2)

    def test_source_parent_candidate_weights_have_half_mass_per_source(self):
        rows, manifest = mod.build_tiny_panel()
        train, _score = manifest.validate(rows, 1)
        weights, audit = mod.source_parent_candidate_weights(rows, train)
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=12)
        self.assertEqual(len(audit["sources"]), 2)
        for source in audit["sources"].values():
            self.assertAlmostEqual(source["mass"], 0.5, places=12)

    def test_contact_bce_balances_positive_and_negative_mass_per_candidate(self):
        logits = torch.zeros((1, 101))
        targets = torch.zeros_like(logits)
        targets[:, 0] = 1.0
        uncertainty = torch.ones_like(logits)
        mask = torch.ones_like(logits, dtype=torch.bool)
        value, available = mod.balanced_soft_bce_per_candidate_receptor(
            logits, targets, uncertainty, mask,
        )
        self.assertTrue(bool(available.item()))
        self.assertAlmostEqual(float(value.item()), float(torch.log(torch.tensor(2.0))), places=6)

    def test_neural_forward_ignores_m2_and_structure_keys_in_batch(self):
        rows, _manifest = mod.build_tiny_panel()
        args = tiny_args(pathlib.Path("unused"), "B_TARGET_NO_CONTACT")
        backbone, _tokenizer, hidden, _identity = mod.load_backbone(args, None)
        config = mod.ResidueV24Config(
            backbone_hidden_size=hidden,
            target_node_dim=7,
            graph_hidden_dim=32,
            dropout=0.0,
        )
        model = mod.build_model(args.lane, backbone, config)
        factory = mod.TinyBatchFactory(rows, config.edge_feature_dim, 4, 43)
        batch = next(iter(factory([0, 1, 2, 3], False, 0)))
        targets = mod.tiny_target_graphs(config)
        first = mod.forward_lane(model, args.lane, batch, targets)["prediction"]
        altered = dict(batch)
        altered["m2_base"] = torch.full((4, 3), float("nan"))
        altered["structure"] = torch.full((4, 126), float("nan"))
        second = mod.forward_lane(model, args.lane, altered, targets)["prediction"]
        self.assertTrue(torch.equal(first, second))

    def test_real_hf_adapter_path_delegates_to_v23_frozen_loader(self):
        class FakeRuntime:
            def __init__(self):
                self.calls = 0

            def load_frozen_backbone(self, args):
                self.calls += 1
                backbone = mod.TinyBackbone(hidden_size=14)
                for parameter in backbone.parameters():
                    parameter.requires_grad_(False)
                return backbone, object(), 14, "frozen-hf-identity"

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            model_path = root / "esm2_local"
            model_path.mkdir()
            identity = root / "model_identity.json"
            identity.write_text("{}\n")
            args = tiny_args(root / "unused", "A_VHH_ONLY")
            args.backbone_kind = "hf"
            args.model_path = model_path
            args.model_identity_file = identity
            runtime = FakeRuntime()
            backbone, tokenizer, hidden, observed_identity = mod.load_backbone(args, runtime)
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(hidden, 14)
            self.assertEqual(observed_identity, "frozen-hf-identity")
            self.assertIsNotNone(tokenizer)
            self.assertFalse(any(parameter.requires_grad for parameter in backbone.parameters()))

    def test_canonical_development_reliability_tier_is_used_and_missing_fails(self):
        self.assertEqual(mod.development_contact_tier({"development_reliability_tier": "A"}), "A")
        self.assertEqual(mod.development_contact_tier({"development_reliability_tier": "TIER_B"}), "B")
        self.assertEqual(mod.development_contact_tier({"development_reliability_tier": "DUAL_1_SEED"}), "C")
        # The canonical field has precedence over legacy aliases.
        self.assertEqual(
            mod.development_contact_tier({
                "development_reliability_tier": "A",
                "contact_reliability_tier": "C",
            }),
            "A",
        )
        with self.assertRaisesRegex(mod.BaseTrainerError, "development_reliability_tier_missing_or_invalid"):
            mod.development_contact_tier({})

    def test_nonfinite_parameter_and_sealed_paths_fail_closed(self):
        parameter = torch.nn.Parameter(torch.tensor([1.0]))
        optimizer = torch.optim.AdamW([parameter], lr=1e-3)
        parameter.data.fill_(float("nan"))
        with self.assertRaisesRegex(mod.BaseTrainerError, "parameter_nonfinite"):
            mod.assert_optimizer_finite(optimizer, [parameter])
        with self.assertRaisesRegex(mod.BaseTrainerError, "sealed_path_forbidden"):
            mod.reject_sealed_path(pathlib.Path("/tmp/V4-F/test32/labels.tsv"))

    def test_real_mode_requires_formula_and_formula_bytes_are_frozen(self):
        args = tiny_args(pathlib.Path("unused"), "D_SPLIT_PAIR")
        args.tiny_e2e = False
        with self.assertRaisesRegex(mod.BaseTrainerError, "contact_formula_json_required_for_real_mode"):
            mod.resolve_contact_formula(args)
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "formula.json"
            payload = json.loads(mod.BUILTIN_TINY_CONTACT_FORMULA.read_text())
            payload["weights"]["hotspot_contact_mass"] = 0.49
            path.write_text(json.dumps(payload))
            args.contact_formula_json = path
            with self.assertRaisesRegex(mod.BaseTrainerError, "contact_formula_sha256"):
                mod.resolve_contact_formula(args)

    def test_real_formula_argument_parses_and_canonical_formula_validates(self):
        args = mod.parser().parse_args([
            "--lane", "D_SPLIT_PAIR",
            "--output-dir", "/tmp/v2_4_formula_arg_test",
            "--contact-formula-json", str(mod.BUILTIN_TINY_CONTACT_FORMULA),
        ])
        self.assertEqual(args.contact_formula_json, mod.BUILTIN_TINY_CONTACT_FORMULA)
        receipt = mod.resolve_contact_formula(args)
        self.assertEqual(receipt["sha256"], mod.CONTACT_FORMULA_SHA256)
        self.assertEqual(receipt["formula_version"], mod.CONTACT_FORMULA_VERSION)


if __name__ == "__main__":
    unittest.main()
