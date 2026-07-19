#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys
import unittest

import torch
from torch import nn
from torch.nn import functional as F
from torch.optim import AdamW


HERE = pathlib.Path(__file__).resolve()
TRAINER_DIR = HERE.parents[1] / "trainer"
V25_MODEL_DIR = HERE.parents[3] / "v2_5_ortho_contact_pose_stack_v1_20260718" / "model"
V25_TRAINER_DIR = HERE.parents[3] / "v2_5_ortho_contact_pose_stack_v1_20260718" / "trainer"
sys.path[:0] = [str(TRAINER_DIR), str(V25_MODEL_DIR), str(V25_TRAINER_DIR)]
import role_isolated_optimization_v1 as mod  # noqa: E402
import residue_model_v2_5_ortho as v25_model  # noqa: E402
import train_v2_5_ortho_heads as v25_trainer  # noqa: E402


class ToyRoleModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.shared_encoder = nn.Sequential(
            nn.Linear(5, 7),
            nn.GELU(),
            nn.Dropout(0.35),
        )
        self.attention_scalar = nn.Sequential(
            nn.Linear(7, 6),
            nn.GELU(),
            nn.Dropout(0.25),
            nn.Linear(6, 2),
        )
        self.contact_only = nn.Sequential(
            nn.Linear(7, 5),
            nn.GELU(),
            nn.Linear(5, 3),
        )

    def scalar_forward(self, values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        shared = self.shared_encoder(values)
        return self.attention_scalar(shared), shared

    def contact_forward(
        self,
        shared: torch.Tensor,
        *,
        dropout: float,
    ) -> torch.Tensor:
        return self.contact_only(F.dropout(shared, p=dropout, training=True))


def role_mapping(model: ToyRoleModel):
    result = {role: [] for role in mod.ROLES}
    for name, parameter in model.named_parameters():
        if name.startswith("shared_encoder."):
            result[mod.ROLE_SHARED].append((name, parameter))
        elif name.startswith("attention_scalar."):
            result[mod.ROLE_SCALAR].append((name, parameter))
        elif name.startswith("contact_only."):
            result[mod.ROLE_CONTACT].append((name, parameter))
        else:
            raise AssertionError(name)
    return result


def scalar_closure(model, values, targets, *, detach_payload):
    def closure():
        prediction, shared = model.scalar_forward(values)
        loss = F.smooth_l1_loss(prediction, targets, beta=0.03)
        payload = shared.detach() if detach_payload else shared
        return mod.ScalarStepOutput(loss=loss, contact_payload=payload)

    return closure


def contact_closure(model, targets, *, dropout, multiplier=1.0):
    def closure(shared):
        prediction = model.contact_forward(shared, dropout=dropout)
        return multiplier * F.binary_cross_entropy_with_logits(prediction, targets)

    return closure


def clone_main_rng_state():
    return torch.random.get_rng_state().clone()


class TestRoleIsolatedOptimization(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        generator = torch.Generator().manual_seed(7719)
        self.values = torch.randn(9, 5, generator=generator)
        self.scalar_targets = torch.randn(9, 2, generator=generator) * 0.05 + 0.4
        self.contact_targets = torch.randint(0, 2, (9, 3), generator=generator).float()
        self.config = mod.RoleOptimizerConfig(
            learning_rate=7e-4,
            contact_learning_rate=9e-4,
            weight_decay=0.01,
            clip_shared=1.0,
            clip_scalar=1.0,
            clip_contact=1.0,
            kappa=0.25,
        )

    def make_aligned_models(self, count):
        torch.manual_seed(991)
        reference = ToyRoleModel()
        models = [reference]
        for _ in range(count - 1):
            model = ToyRoleModel()
            model.load_state_dict(copy.deepcopy(reference.state_dict()))
            models.append(model)
        return models

    def test_parameter_roles_and_two_optimizer_ownership_are_exhaustive(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        scalar_optimizer, contact_optimizer, audit = mod.build_role_optimizers(
            model, roles, self.config,
        )
        self.assertTrue(
            audit["parameter_roles"]["all_trainable_parameters_owned_exactly_once"]
        )
        self.assertEqual(audit["optimizer_ownership"]["overlap_count"], 0)
        scalar_ids = set(mod.optimizer_parameter_ids(scalar_optimizer))
        contact_ids = set(mod.optimizer_parameter_ids(contact_optimizer))
        self.assertFalse(scalar_ids & contact_ids)
        self.assertEqual(
            scalar_ids,
            {
                id(parameter)
                for role in (mod.ROLE_SHARED, mod.ROLE_SCALAR)
                for _name, parameter in roles[role]
            },
        )

    def test_real_v25_orthogonal_head_maps_exhaustively_into_v26_roles(self):
        config = v25_model.ResidueV25OrthoConfig.for_lane(
            v25_model.LANE_E,
            backbone_hidden_size=12,
            target_node_dim=9,
            edge_feature_dim=4,
            graph_hidden_dim=16,
            interaction_rank=64,
            dropout=0.25,
            contact_encoder_gradient="shared",
        )
        model = v25_trainer.build_model(
            v25_model.LANE_E,
            v25_trainer.TinyBackbone(hidden_size=12),
            config,
        )
        roles = mod.role_mapping_from_v25_orthogonal_model(model)
        audit = mod.validate_parameter_roles(model, roles)
        self.assertTrue(audit["all_trainable_parameters_owned_exactly_once"])
        self.assertGreater(audit["role_tensor_counts"][mod.ROLE_SHARED], 0)
        self.assertGreater(audit["role_tensor_counts"][mod.ROLE_SCALAR], 0)
        self.assertGreater(audit["role_tensor_counts"][mod.ROLE_CONTACT], 0)
        _scalar, _contact, optimizer_audit = mod.build_role_optimizers(
            model, roles, self.config,
        )
        self.assertEqual(optimizer_audit["optimizer_ownership"]["overlap_count"], 0)

    def test_real_v25_clean_b_lane_uses_scalar_reference_optimizer_without_contact(self):
        config = v25_model.ResidueV25OrthoConfig.for_lane(
            v25_model.LANE_B,
            backbone_hidden_size=12,
            target_node_dim=9,
            edge_feature_dim=4,
            graph_hidden_dim=16,
            interaction_rank=64,
            dropout=0.25,
            contact_encoder_gradient="detached",
        )
        model = v25_trainer.build_model(
            v25_model.LANE_B,
            v25_trainer.TinyBackbone(hidden_size=12),
            config,
        )
        roles = mod.role_mapping_from_v25_orthogonal_model(model)
        self.assertFalse(roles[mod.ROLE_CONTACT])
        optimizer, audit = mod.build_scalar_reference_optimizer(model, roles, self.config)
        self.assertEqual(len(optimizer.param_groups), 2)
        self.assertFalse(
            audit["optimizer_ownership"]["contact_parameter_owned_by_scalar_optimizer"]
        )

    def test_mutation_overlapping_role_ownership_is_rejected(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        name, parameter = roles[mod.ROLE_SHARED][0]
        mutated = {role: list(values) for role, values in roles.items()}
        mutated[mod.ROLE_CONTACT].append((name, parameter))
        with self.assertRaisesRegex(mod.RoleIsolationError, "parameter_name_duplicate|parameter_role_overlap"):
            mod.validate_parameter_roles(model, mutated)

    def test_mutation_overlapping_optimizer_ownership_is_rejected(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        scalar_optimizer, contact_optimizer, _audit = mod.build_role_optimizers(
            model, roles, self.config,
        )
        mutated_contact = AdamW(
            [
                parameter
                for role in (mod.ROLE_CONTACT, mod.ROLE_SHARED)
                for _name, parameter in roles[role]
            ],
            lr=1e-4,
        )
        with self.assertRaisesRegex(mod.RoleIsolationError, "optimizer_parameter_overlap"):
            mod.validate_optimizer_ownership(roles, scalar_optimizer, mutated_contact)
        # Preserve a real optimizer reference so the intended one is not
        # optimized away by a future test simplification.
        self.assertTrue(contact_optimizer.param_groups)

    def test_mutation_global_clip_event_is_rejected(self):
        with self.assertRaisesRegex(mod.RoleIsolationError, "global_all_parameter_clip_forbidden"):
            mod.validate_clip_events(
                [{"role": "GLOBAL_ALL", "max_norm": 1.0}],
                (mod.ROLE_SHARED, mod.ROLE_SCALAR),
            )

    def test_contact_seed_is_content_addressed_and_context_restores_rng(self):
        first = mod.ContactRngKey(43, 1, 2, 3, 4, 5)
        second = mod.ContactRngKey(43, 1, 2, 3, 4, 6)
        self.assertEqual(mod.derive_contact_seed(first), mod.derive_contact_seed(first))
        self.assertNotEqual(mod.derive_contact_seed(first), mod.derive_contact_seed(second))
        torch.manual_seed(10)
        before = mod.rng_state_sha256("cpu")
        with mod.isolated_contact_rng(first, "cpu"):
            _ = torch.rand(200)
        after = mod.rng_state_sha256("cpu")
        self.assertEqual(before, after)

    def test_mutation_contact_rng_outside_fork_is_detected(self):
        torch.manual_seed(66)
        before = mod.rng_state_sha256("cpu")
        _ = F.dropout(torch.ones(100), p=0.5, training=True)
        after = mod.rng_state_sha256("cpu")
        self.assertNotEqual(before, after)
        with self.assertRaisesRegex(mod.RoleIsolationError, "contact_rng_state_leak"):
            mod.require(after == before, "contact_rng_state_leak")

    def test_twenty_step_b_e_trajectory_equivalence_with_adversarial_contact_rng(self):
        baseline, detached, adversarial = self.make_aligned_models(3)
        models = (baseline, detached, adversarial)
        role_maps = [role_mapping(model) for model in models]
        optimizers = [mod.build_role_optimizers(model, roles, self.config)[:2] for model, roles in zip(models, role_maps)]
        initial_contact = [mod.parameter_state_sha256(roles[mod.ROLE_CONTACT]) for roles in role_maps]

        torch.manual_seed(12001)
        initial_rng = clone_main_rng_state()
        rng_states = [initial_rng.clone(), initial_rng.clone(), initial_rng.clone()]
        trajectory = []
        for step in range(20):
            step_hashes = []
            step_rng_hashes = []
            for index, (model, roles, (scalar_optimizer, contact_optimizer)) in enumerate(
                zip(models, role_maps, optimizers)
            ):
                torch.random.set_rng_state(rng_states[index])
                scalar = scalar_closure(
                    model, self.values, self.scalar_targets, detach_payload=True,
                )
                if index == 0:
                    receipt = mod.scalar_only_step(
                        role_mapping=roles,
                        scalar_optimizer=scalar_optimizer,
                        contact_optimizer=contact_optimizer,
                        scalar_closure=scalar,
                        config=self.config,
                    )
                    self.assertEqual(receipt["mode"], "B_SCALAR_ATTENTION_ONLY")
                else:
                    dropout = 0.5 if index == 1 else 0.2
                    multiplier = 1.0 if index == 1 else 10.0
                    receipt = mod.strict_detached_step(
                        role_mapping=roles,
                        scalar_optimizer=scalar_optimizer,
                        contact_optimizer=contact_optimizer,
                        scalar_closure=scalar,
                        contact_closure=contact_closure(
                            model,
                            self.contact_targets,
                            dropout=dropout,
                            multiplier=multiplier,
                        ),
                        rng_key=mod.ContactRngKey(97, 0, 1, 2, step, 0),
                        device="cpu",
                        config=self.config,
                    )
                    self.assertTrue(receipt["main_rng_restored"])
                    self.assertGreater(receipt["contact_pre_clip_gradient_norm"], 0.0)
                rng_states[index] = clone_main_rng_state()
                step_hashes.append(mod.scalar_trajectory_sha256(roles))
                step_rng_hashes.append(mod.rng_state_sha256("cpu"))

            self.assertEqual(step_hashes[0], step_hashes[1])
            self.assertEqual(step_hashes[0], step_hashes[2])
            self.assertEqual(step_rng_hashes[0], step_rng_hashes[1])
            self.assertEqual(step_rng_hashes[0], step_rng_hashes[2])
            self.assertLessEqual(
                mod.maximum_parameter_delta(
                    role_maps[0], role_maps[1], (mod.ROLE_SHARED, mod.ROLE_SCALAR),
                ),
                1e-7,
            )
            self.assertLessEqual(
                mod.maximum_parameter_delta(
                    role_maps[0], role_maps[2], (mod.ROLE_SHARED, mod.ROLE_SCALAR),
                ),
                1e-7,
            )
            trajectory.append(
                {
                    "step": step,
                    "scalar_sha256": step_hashes[0],
                    "main_rng_sha256": step_rng_hashes[0],
                }
            )

        self.assertEqual(len(trajectory), 20)
        self.assertNotEqual(
            initial_contact[1], mod.parameter_state_sha256(role_maps[1][mod.ROLE_CONTACT])
        )
        self.assertNotEqual(
            initial_contact[2], mod.parameter_state_sha256(role_maps[2][mod.ROLE_CONTACT])
        )
        # Different dropout/loss scale is allowed to change contact-only state.
        self.assertNotEqual(
            mod.parameter_state_sha256(role_maps[1][mod.ROLE_CONTACT]),
            mod.parameter_state_sha256(role_maps[2][mod.ROLE_CONTACT]),
        )

    def test_strict_detached_rejects_contact_gradient_into_shared(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        scalar_optimizer, contact_optimizer, _audit = mod.build_role_optimizers(
            model, roles, self.config,
        )
        with self.assertRaisesRegex(
            mod.RoleIsolationError,
            "strict_detached_contact_payload_requires_grad|strict_detached_contact_gradient_reaches_scalar_path",
        ):
            mod.strict_detached_step(
                role_mapping=roles,
                scalar_optimizer=scalar_optimizer,
                contact_optimizer=contact_optimizer,
                scalar_closure=scalar_closure(
                    model, self.values, self.scalar_targets, detach_payload=False,
                ),
                contact_closure=contact_closure(
                    model, self.contact_targets, dropout=0.5,
                ),
                rng_key=mod.ContactRngKey(11, 0, 0, 0, 0),
                device="cpu",
                config=self.config,
            )

    def test_shared_gated_contact_gradient_respects_kappa_budget(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        scalar_optimizer, contact_optimizer, _audit = mod.build_role_optimizers(
            model, roles, self.config,
        )
        before_shared = mod.parameter_state_sha256(roles[mod.ROLE_SHARED])
        before_contact = mod.parameter_state_sha256(roles[mod.ROLE_CONTACT])
        receipt = mod.shared_gated_contact_step(
            role_mapping=roles,
            scalar_optimizer=scalar_optimizer,
            contact_optimizer=contact_optimizer,
            scalar_closure=scalar_closure(
                model, self.values, self.scalar_targets, detach_payload=False,
            ),
            contact_closure=contact_closure(
                model, self.contact_targets, dropout=0.5, multiplier=100.0,
            ),
            rng_key=mod.ContactRngKey(193, 2, 3, 4, 5),
            device="cpu",
            config=self.config,
        )
        self.assertEqual(receipt["mode"], "F_SHARED_GATED_CONTACT_TRANSFER")
        self.assertTrue(receipt["main_rng_restored"])
        self.assertGreater(receipt["scalar_shared_gradient_norm"], 0.0)
        self.assertGreater(receipt["contact_shared_gradient_norm"], 0.0)
        self.assertLessEqual(receipt["contact_cap_multiplier"], 1.0)
        self.assertLessEqual(
            receipt["contact_capped_gradient_norm"],
            receipt["contact_budget_norm_limit"] + 1e-10,
        )
        self.assertEqual(
            [event["role"] for event in receipt["clip_events"]], list(mod.ROLES)
        )
        self.assertFalse(receipt["global_all_parameter_clip_used"])
        self.assertNotEqual(before_shared, mod.parameter_state_sha256(roles[mod.ROLE_SHARED]))
        self.assertNotEqual(before_contact, mod.parameter_state_sha256(roles[mod.ROLE_CONTACT]))

    def test_shared_gated_rejects_contact_path_into_scalar_terminal(self):
        model = self.make_aligned_models(1)[0]
        roles = role_mapping(model)
        scalar_optimizer, contact_optimizer, _audit = mod.build_role_optimizers(
            model, roles, self.config,
        )

        def bad_contact(shared):
            contact = model.contact_forward(shared, dropout=0.2).mean()
            scalar = model.attention_scalar(shared).mean()
            return contact + scalar

        with self.assertRaisesRegex(
            mod.RoleIsolationError, "contact_loss_reaches_attention_scalar_parameters",
        ):
            mod.shared_gated_contact_step(
                role_mapping=roles,
                scalar_optimizer=scalar_optimizer,
                contact_optimizer=contact_optimizer,
                scalar_closure=scalar_closure(
                    model, self.values, self.scalar_targets, detach_payload=False,
                ),
                contact_closure=bad_contact,
                rng_key=mod.ContactRngKey(5, 0, 0, 0, 0),
                device="cpu",
                config=self.config,
            )

    def test_implementation_contract_freezes_scope_and_budget(self):
        contract = mod.implementation_contract()
        self.assertEqual(contract["shared_gated"]["kappa"], 0.25)
        self.assertFalse(contract["global_all_parameter_clip_allowed"])
        self.assertFalse(contract["outer_metrics_accessed"])
        self.assertFalse(contract["v4_f_test32_accessed"])
        self.assertEqual(
            contract["optimizer_owners"][mod.OWNER_CONTACT], [mod.ROLE_CONTACT]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
