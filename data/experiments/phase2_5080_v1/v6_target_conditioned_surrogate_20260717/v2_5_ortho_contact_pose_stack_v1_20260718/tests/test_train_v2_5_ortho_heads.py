import pathlib
import sys
import unittest

import torch


HERE = pathlib.Path(__file__).resolve()
MODEL_DIR = HERE.parents[1] / "model"
TRAINER_DIR = HERE.parents[1] / "trainer"
sys.path[:0] = [str(MODEL_DIR), str(TRAINER_DIR)]
import residue_model_v2_5_ortho as model_mod
import train_v2_5_ortho_heads as mod

from test_residue_model_v2_5_ortho import make_model_and_inputs


def make_batch(inputs, with_contacts: bool = True):
    batch = {key: value for key, value in inputs.items() if key != "target_graphs"}
    count, length = batch["residue_mask"].shape
    batch["targets"] = torch.tensor([[0.42, 0.37], [0.31, 0.39]], dtype=torch.float32)
    batch["hierarchy_weights"] = torch.tensor([0.6, 0.4])
    if with_contacts:
        marginal = torch.zeros((count, length, 2), dtype=torch.float32)
        marginal[:, :, 0] = torch.linspace(0.05, 0.8, length)
        marginal[:, :, 1] = torch.linspace(0.8, 0.05, length)
        batch["marginal_targets"] = marginal
        batch["marginal_mask"] = batch["residue_mask"].unsqueeze(-1).expand_as(marginal)
        batch["marginal_uncertainty"] = torch.ones_like(marginal)
        batch["marginal_tier_weights"] = torch.tensor([1.0, 0.5])
        for receptor, nodes, channel in (("8x6b", 5, 0), ("9e6y", 6, 1)):
            pair = marginal[:, :, channel].unsqueeze(-1).expand(count, length, nodes)
            batch[f"pair_targets_{receptor}"] = pair
            batch[f"pair_mask_{receptor}"] = batch["residue_mask"].unsqueeze(-1).expand_as(pair)
            batch[f"pair_uncertainty_{receptor}"] = torch.ones_like(pair)
        batch["pair_tier_weights"] = torch.tensor([1.0, 0.25])
    return batch


class TestOrthoTrainer(unittest.TestCase):
    def test_positive_allowlist_ignores_ids_m2_structure_and_pose(self):
        config, _unused, inputs = make_model_and_inputs(model_mod.LANE_B)
        model = mod.build_model(model_mod.LANE_B, mod.TinyBackbone(hidden_size=12), config)
        batch = make_batch(inputs, with_contacts=False)
        first = mod.forward_lane(model, model_mod.LANE_B, batch, inputs["target_graphs"])["prediction"]
        altered = dict(batch)
        altered.update(
            {
                "m2_base": torch.full((2, 3), float("nan")),
                "structure": torch.full((2, 126), float("nan")),
                "candidate_ids": ["TRAP_A", "TRAP_B"],
                "parent_framework_cluster": ["P1", "P2"],
                "campaign_id": "TRAP",
                "docking_pose_features": torch.full((2, 99), float("nan")),
                "teacher_source": ["TRAP", "TRAP"],
            }
        )
        second = mod.forward_lane(model, model_mod.LANE_B, altered, inputs["target_graphs"])["prediction"]
        self.assertTrue(torch.equal(first, second))
        kwargs = mod.neural_forward_kwargs(altered, inputs["target_graphs"])
        self.assertEqual(set(kwargs), set(mod.NEURAL_REQUIRED_BATCH_FIELDS) | {"target_graphs"})
        self.assertFalse(set(kwargs) & set(mod.FORBIDDEN_NEURAL_INPUT_FIELDS))

    def test_clean_attention_loss_rejects_contact_weights(self):
        _config, model, inputs = make_model_and_inputs(model_mod.LANE_B)
        batch = make_batch(inputs, with_contacts=False)
        output = mod.forward_lane(model, model_mod.LANE_B, batch, inputs["target_graphs"])
        with self.assertRaisesRegex(mod.OrthoTrainerError, "clean_attention_lane_contact_loss_forbidden"):
            mod.compute_loss(
                output,
                batch,
                model_mod.LANE_B,
                mod.OrthoLossConfig(marginal_weight=0.1),
            )

    def test_e_loss_routes_scalar_and_contact_without_nonfinite_values(self):
        _config, model, inputs = make_model_and_inputs(model_mod.LANE_E, "detached")
        batch = make_batch(inputs)
        output = mod.forward_lane(model, model_mod.LANE_E, batch, inputs["target_graphs"])
        total, parts = mod.compute_loss(
            output,
            batch,
            model_mod.LANE_E,
            mod.OrthoLossConfig(marginal_weight=0.2, pair_weight=0.1),
        )
        self.assertTrue(torch.isfinite(total))
        self.assertEqual(
            set(parts),
            {"receptor", "softmin_dual", "scalar", "marginal_contact", "pair_contact", "contact", "total"},
        )
        self.assertGreater(float(parts["scalar"].detach()), 0.0)
        self.assertGreater(float(parts["contact"].detach()), 0.0)
        total.backward()
        self.assertIsNotNone(model.head.scalar_head[-1].weight.grad)
        self.assertIsNotNone(model.head.contact_interaction.terminal.grad)
        self.assertIsNone(model.backbone.embedding.weight.grad)

    def test_optimizer_roles_have_no_overlap_and_contact_is_optional(self):
        config_b, _unused, _inputs = make_model_and_inputs(model_mod.LANE_B)
        model_b = mod.build_model(model_mod.LANE_B, mod.TinyBackbone(hidden_size=12), config_b)
        optimizer_b, audit_b = mod.build_optimizer(model_b, mod.OptimizerConfig())
        self.assertEqual(len(optimizer_b.param_groups), 2)
        self.assertEqual(audit_b["contact"]["parameter_tensors"], 0)

        config_e, _unused, _inputs = make_model_and_inputs(model_mod.LANE_E)
        model_e = mod.build_model(model_mod.LANE_E, mod.TinyBackbone(hidden_size=12), config_e)
        optimizer_e, audit_e = mod.build_optimizer(
            model_e,
            mod.OptimizerConfig(contact_learning_rate_multiplier=0.5),
        )
        self.assertEqual(len(optimizer_e.param_groups), 3)
        self.assertGreater(audit_e["contact"]["parameter_tensors"], 0)
        self.assertAlmostEqual(
            optimizer_e.param_groups[2]["lr"], optimizer_e.param_groups[0]["lr"] * 0.5,
        )
        parameters = [parameter for group in optimizer_e.param_groups for parameter in group["params"]]
        self.assertEqual(len(parameters), len({id(parameter) for parameter in parameters}))

    def test_trainer_contract_records_exact_min_firewall_and_gradient_mode(self):
        config, _unused, _inputs = make_model_and_inputs(model_mod.LANE_E, "detached")
        model = mod.build_model(model_mod.LANE_E, mod.TinyBackbone(hidden_size=12), config)
        loss = mod.OrthoLossConfig(marginal_weight=0.2, pair_weight=0.1)
        contract = mod.trainer_contract(model_mod.LANE_E, model, loss)
        self.assertFalse(contract["scalar_contact_feedback"])
        self.assertEqual(contract["contact_encoder_gradient"], "detached")
        self.assertEqual(contract["derived_target"], "exact_min(R_8X6B,R_9E6Y)")
        self.assertTrue(set(mod.FORBIDDEN_NEURAL_INPUT_FIELDS) <= set(contract["forbidden_neural_inputs"]))
        self.assertEqual(contract["parameter_role_counts"]["contact"], len(list(model.head.contact_interaction.parameters())) + 1)

    def test_balanced_soft_bce_handles_one_positive_against_many_negatives(self):
        logits = torch.zeros((1, 101))
        targets = torch.zeros_like(logits)
        targets[:, 0] = 1.0
        value, available = mod.balanced_soft_bce_per_candidate(
            logits, targets, torch.ones_like(logits), torch.ones_like(logits, dtype=torch.bool),
        )
        self.assertTrue(bool(available.item()))
        self.assertAlmostEqual(float(value.item()), float(torch.log(torch.tensor(2.0))), places=6)

    def test_fixed_epoch_loop_trains_e_without_reading_forbidden_extras(self):
        config, _unused, inputs = make_model_and_inputs(model_mod.LANE_E, "detached")
        model = mod.build_model(model_mod.LANE_E, mod.TinyBackbone(hidden_size=12), config)
        batch = make_batch(inputs)
        batch.update(
            {
                "candidate_ids": ["TRAP_A", "TRAP_B"],
                "m2_base": torch.full((2, 3), float("nan")),
                "structure_features": torch.full((2, 126), float("nan")),
                "docking_pose_features": torch.full((2, 20), float("nan")),
            }
        )
        before_scalar = model.head.scalar_head[-1].weight.detach().clone()
        before_contact = model.head.contact_interaction.terminal.detach().clone()
        receipt = mod.train_fixed_epochs(
            model,
            model_mod.LANE_E,
            lambda epoch: [batch],
            inputs["target_graphs"],
            mod.OrthoLossConfig(marginal_weight=0.2, pair_weight=0.1),
            mod.OptimizerConfig(learning_rate=1e-3, weight_decay=0.0),
            fixed_epochs=2,
            device_name="cpu",
            precision="fp32",
        )
        self.assertEqual(receipt["selection"], "NONE_FIXED_EPOCH_ONLY")
        self.assertEqual(receipt["optimizer_steps"], 2)
        self.assertEqual(len(receipt["epoch_history"]), 2)
        self.assertFalse(torch.equal(before_scalar, model.head.scalar_head[-1].weight.detach()))
        self.assertFalse(torch.equal(before_contact, model.head.contact_interaction.terminal.detach()))
        self.assertTrue(
            set(mod.FORBIDDEN_NEURAL_INPUT_FIELDS)
            <= set(receipt["neural_input_firewall"]["forbidden"])
        )


if __name__ == "__main__":
    unittest.main()
