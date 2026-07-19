from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass

import torch


HERE = pathlib.Path(__file__).resolve()
PACKAGE = HERE.parents[1]
V26 = PACKAGE.parent
ROOT = V26.parent
V25 = ROOT / "v2_5_ortho_contact_pose_stack_v1_20260718"
OPT = V26 / "implementation_v1_20260718" / "trainer"
RANK_V1 = V26 / "rank_calibration_v1_20260718" / "rank_calibration_core_v1.py"
RANK_V11 = V26 / "rank_calibration_v1_1_20260718" / "rank_calibration_core_v1_1.py"
BINDING = ROOT / "v2_6_noise_tolerance_binding_v1_20260718" / "V2_6_DELTA_NOISE_BINDING.json"
sys.path[:0] = [
    str(PACKAGE / "trainer"),
    str(V25 / "model"),
    str(V25 / "trainer"),
    str(OPT),
]

import real1507_role_isolated_trainer_v1 as mod
import residue_model_v2_5_ortho as model_mod
import role_isolated_optimization_v1 as opt_mod
import train_v2_5_ortho_heads as v25_mod


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Row:
    candidate_id: str
    parent: str
    teacher_source: str
    contact_tier: str
    targets: tuple[float, float]


@dataclass(frozen=True)
class Manifest:
    split_id: str
    outer_fold: int
    train_parents: tuple[str, ...]
    score_parents: tuple[str, ...]
    open_only: bool = True
    v4_f_test32_access_count: int = 0


def target_graph(nodes: int) -> dict[str, torch.Tensor]:
    edges = []
    for index in range(nodes - 1):
        edges.extend(((index, index + 1), (index + 1, index)))
    return {
        "node_features": torch.randn(nodes, 6),
        "edge_index": torch.tensor(edges, dtype=torch.long).T,
        "edge_features": torch.randn(len(edges), 4),
        "interface_mask": torch.tensor([True] + [False] * (nodes - 1)),
        "hotspot_mask": torch.tensor([True] + [False] * (nodes - 1)),
    }


def make_rows() -> tuple[list[Row], list[int], list[int], Manifest]:
    rows: list[Row] = []
    for parent_index in range(8):
        parent = f"P{parent_index}"
        rows.append(Row(
            f"{parent}_LO", parent, "V4D_OPEN_MULTI_SEED", "A",
            (0.21 + parent_index * 0.005, 0.24 + parent_index * 0.005),
        ))
        rows.append(Row(
            f"{parent}_HI", parent, "V4D_OPEN_MULTI_SEED", "A",
            (0.55 - parent_index * 0.005, 0.58 - parent_index * 0.005),
        ))
    train = list(range(len(rows)))
    rows.extend(
        [
            Row("Q0_ONLY", "Q0", "V4H_OPEN_ADAPTIVE", "C", (0.1, 0.2)),
            Row("Q1_ONLY", "Q1", "V4H_OPEN_ADAPTIVE", "C", (0.2, 0.3)),
        ]
    )
    score = [16, 17]
    manifest = Manifest(
        "synthetic_outer0_inner0",
        0,
        tuple(f"P{index}" for index in range(8)),
        ("Q0", "Q1"),
    )
    return rows, train, score, manifest


class BatchFactory:
    def __init__(self, rows: list[Row], targets: dict[str, dict[str, torch.Tensor]], batch_size: int = 4):
        self.rows = rows
        self.targets = targets
        self.batch_size = batch_size

    def __call__(self, indices, training: bool, epoch: int):
        del training, epoch
        selected = list(indices)
        for start in range(0, len(selected), self.batch_size):
            yield self.make_batch(selected[start:start + self.batch_size])

    def make_batch(self, indices):
        count, length = len(indices), 4
        input_ids = torch.tensor(
            [[(index + offset) % 20 + 1 for offset in range(length)] for index in indices],
            dtype=torch.long,
        )
        edge_pairs = []
        for local in range(count):
            base = local * length
            for position in range(length - 1):
                edge_pairs.extend(((base + position, base + position + 1), (base + position + 1, base + position)))
        residue_mask = torch.ones((count, length), dtype=torch.bool)
        batch = {
            "input_ids": input_ids,
            "attention_mask": torch.ones_like(input_ids),
            "residue_mask": residue_mask,
            "vhh_aa_index": input_ids.clamp_max(20),
            "vhh_region_index": torch.tensor([[0, 1, 2, 3]] * count, dtype=torch.long),
            "vhh_confidence": torch.ones((count, length, 1)),
            "vhh_edge_index": torch.tensor(edge_pairs, dtype=torch.long).T,
            "vhh_edge_features": torch.randn(len(edge_pairs), 4),
            "candidate_ids": [self.rows[index].candidate_id for index in indices],
            "targets": torch.tensor([self.rows[index].targets for index in indices], dtype=torch.float32),
            "hierarchy_weights": torch.ones(count),
            # Firewall traps: they may be present in the batch but never in
            # neural_forward_kwargs.
            "m2_base": torch.full((count, 3), float("nan")),
            "structure_features": torch.full((count, 126), float("nan")),
            "docking_pose_features": torch.full((count, 5), float("nan")),
        }
        marginal = torch.full((count, length, 2), 0.2)
        marginal[:, 0, :] = 0.8
        batch.update({
            "marginal_targets": marginal,
            "marginal_mask": residue_mask.unsqueeze(-1).expand_as(marginal),
            "marginal_uncertainty": torch.ones_like(marginal),
            "marginal_tier_weights": torch.tensor([
                mod.CONTACT_TIER_POLICY[self.rows[index].contact_tier]["marginal"] for index in indices
            ]),
            "pair_tier_weights": torch.tensor([
                mod.CONTACT_TIER_POLICY[self.rows[index].contact_tier]["pair"] for index in indices
            ]),
        })
        for receptor in ("8x6b", "9e6y"):
            nodes = len(self.targets[receptor]["node_features"])
            pair = marginal[:, :, 0].unsqueeze(-1).expand(count, length, nodes).clone()
            pair[:, 0, 0] = 0.9
            batch[f"pair_targets_{receptor}"] = pair
            batch[f"pair_mask_{receptor}"] = residue_mask.unsqueeze(-1).expand_as(pair)
            batch[f"pair_uncertainty_{receptor}"] = torch.ones_like(pair)
        return batch


def make_model(shared: bool):
    config = model_mod.ResidueV25OrthoConfig(
        backbone_hidden_size=12,
        target_node_dim=6,
        edge_feature_dim=4,
        graph_hidden_dim=16,
        dropout=0.0,
        enable_contact_evidence=True,
        contact_encoder_gradient="shared" if shared else "detached",
    )
    return v25_mod.build_model(model_mod.LANE_E, v25_mod.TinyBackbone(hidden_size=12), config)


def make_b_model():
    config = model_mod.ResidueV25OrthoConfig(
        backbone_hidden_size=12,
        target_node_dim=6,
        edge_feature_dim=4,
        graph_hidden_dim=16,
        dropout=0.0,
        enable_contact_evidence=False,
        contact_encoder_gradient="detached",
    )
    return v25_mod.build_model(model_mod.LANE_B, v25_mod.TinyBackbone(hidden_size=12), config)


class TestRankPolicyAdapter(unittest.TestCase):
    def test_current_v1_policy_loads_by_hash_and_uses_legacy_builder(self):
        policy = mod.RankPolicyAdapter.load(RANK_V1, sha(RANK_V1))
        self.assertEqual(policy.prediction_builder_name, "build_softmin_dual_prediction_batch")
        self.assertEqual(policy.verify_binding(BINDING)["v4_f_or_test32_results_accessed"], 0)

    def test_v11_exact_builder_wins_over_deprecated_soft_builder(self):
        source = RANK_V1.read_text()
        source += "\n\ndef build_exact_min_dual_prediction_batch(candidate_ids, receptor_predictions):\n"
        source += "    return build_softmin_dual_prediction_batch(candidate_ids, receptor_predictions)\n"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "rank_v1_1.py"
            path.write_text(source)
            policy = mod.RankPolicyAdapter.load(path, sha(path))
        self.assertEqual(policy.prediction_builder_name, "build_exact_min_dual_prediction_batch")
        self.assertEqual(policy.prediction_semantics, "EXACT_MIN_FROM_DIRECT_R8_R9")

    def test_hash_mutation_fails_closed(self):
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "module_sha256_mismatch"):
            mod.RankPolicyAdapter.load(RANK_V1, "0" * 64)

    def test_formal_dependency_gate_rejects_legacy_v1_rank_policy(self):
        policy = mod.RankPolicyAdapter.load(RANK_V1, sha(RANK_V1))
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "formal_rank_policy_not_frozen_v1_1"):
            mod.validate_bound_training_dependencies(
                v25_mod, opt_mod, make_b_model(), policy, BINDING
            )

    def test_frozen_v11_loads_exact_min_and_strict_v4d_provenance(self):
        policy = mod.RankPolicyAdapter.load(RANK_V11, sha(RANK_V11))
        self.assertEqual(policy.prediction_builder_name, "build_exact_min_dual_prediction_batch")
        self.assertEqual(policy.prediction_semantics, "EXACT_MIN_FROM_DIRECT_R8_R9")
        v4d = mod.OpenTrainRow("A", "P", "V4D_OPEN_MULTI_SEED", "A", 0.2, 0.5)
        v4h = mod.OpenTrainRow("B", "Q", "V4H_OPEN_ADAPTIVE", "A", 0.2, 0.5)
        self.assertTrue(policy.admits(v4d))
        self.assertFalse(policy.admits(v4h))
        label = policy.make_label(v4d)
        self.assertEqual(label.ranking_release, "v4d_open_multi_seed_frozen_v1_1")
        self.assertEqual(label.teacher_reliability, "MULTI_SEED")
        labels = policy.make_labels((v4d, v4h))
        self.assertEqual(len(labels), 2)
        self.assertEqual(sum(value.rank_eligible for value in labels), 1)
        self.assertEqual(labels[1].ranking_release, "final_adaptive_seed")


class TestPartitionAndTierFirewalls(unittest.TestCase):
    def setUp(self):
        self.rows, self.train, self.score, self.manifest = make_rows()

    def test_whole_parent_exact_closure(self):
        audit = mod.validate_whole_parent_partition(self.rows, self.train, self.score, self.manifest)
        self.assertEqual((audit.row_count, audit.parent_count), (18, 10))
        self.assertEqual((audit.train_rows, audit.score_rows), (16, 2))

    def test_parent_leakage_mutation_rejected(self):
        rows = list(self.rows)
        rows[16] = Row("Q0_ONLY", "P0", "V4H_OPEN_ADAPTIVE", "C", (0.1, 0.2))
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "whole_parent_split_leakage"):
            mod.validate_whole_parent_partition(rows, self.train, self.score, self.manifest)

    def test_partition_row_omission_rejected(self):
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "partition_row_closure_failed"):
            mod.validate_whole_parent_partition(self.rows, self.train[:-1], self.score, self.manifest)

    def test_score_truth_is_not_read_by_partition_audit(self):
        class ScoreRow:
            candidate_id = "QX"
            parent = "QX"
            teacher_source = "V4H_OPEN_ADAPTIVE"
            contact_tier = "C"

            @property
            def targets(self):
                raise AssertionError("score truth touched")

        rows = list(self.rows[:16]) + [ScoreRow()]
        manifest = Manifest("x", 0, self.manifest.train_parents, ("QX",))
        audit = mod.validate_whole_parent_partition(rows, range(16), [16], manifest)
        self.assertEqual(audit.score_rows, 1)

    def test_tier_weight_mutation_rejected(self):
        targets = {"8x6b": target_graph(3), "9e6y": target_graph(4)}
        batch = BatchFactory(self.rows, targets).make_batch([0, 1, 2, 3])
        tiers = {row.candidate_id: row.contact_tier for row in self.rows}
        batch["pair_tier_weights"][0] = 0.25
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "pair_tier_policy_mismatch"):
            mod.validate_contact_tier_batch(batch, tiers)


class TestCpuIntegrationSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.train, cls.score, cls.manifest = make_rows()
        torch.manual_seed(7)
        cls.targets = {"8x6b": target_graph(3), "9e6y": target_graph(4)}
        cls.factory = BatchFactory(cls.rows, cls.targets, batch_size=4)
        cls.policy = mod.RankPolicyAdapter.load(RANK_V11, sha(RANK_V11))

    def run_lane(self, lane: str, *, model=None):
        model = model or (make_b_model() if lane == mod.LANE_B else make_model(shared=lane == mod.LANE_F))
        before_scalar = model.head.scalar_head[-1].weight.detach().clone()
        before_contact = (
            None if model.head.contact_interaction is None
            else model.head.contact_interaction.terminal.detach().clone()
        )
        context = types.SimpleNamespace(
            model=model,
            rows=self.rows,
            manifest=self.manifest,
            train_indices=self.train,
            score_indices=self.score,
            batches=self.factory,
            target_graphs=self.targets,
            lane_spec=types.SimpleNamespace(
                model_lane=model_mod.LANE_B if lane == mod.LANE_B else model_mod.LANE_E,
                contact_encoder_gradient="shared" if lane == mod.LANE_F else "detached",
            ),
        )
        receipt = mod.train_v25_real1507_context_nonlaunching(
            context=context,
            v25_api=v25_mod,
            optimizer_api=opt_mod,
            rank_policy=self.policy,
            delta_noise_binding_path=BINDING,
            scalar_loss_config=v25_mod.OrthoLossConfig(
                receptor_weight=1.0,
                dual_weight=0.5,
                marginal_weight=0.0,
                pair_weight=0.0,
            ),
            contact_loss_config=v25_mod.OrthoLossConfig(
                receptor_weight=1.0,
                dual_weight=0.5,
                marginal_weight=0.2,
                pair_weight=0.1,
            ),
            role_optimizer_config=opt_mod.RoleOptimizerConfig(
                learning_rate=1e-3,
                contact_learning_rate=1e-3,
                weight_decay=0.0,
                clip_shared=1.0,
                clip_scalar=1.0,
                clip_contact=1.0,
                kappa=0.25,
            ),
            config=mod.V26TrainerConfig(
                integration_lane=lane,
                fixed_epochs=1,
                gradient_accumulation=3,
                lambda_rank=0.1,
                precision="fp32",
                base_seed=43,
                outer_fold=0,
                inner_fold=0,
                expected_main_batches_per_epoch=4,
            ),
            device_name="cpu",
        )
        self.assertEqual(receipt["optimizer_steps"], 2)
        self.assertEqual(receipt["score_truth_rows_accessed"], 0)
        self.assertEqual(receipt["outer_metrics_access_count"], 0)
        self.assertEqual(receipt["v4_f_test32_access_count"], 0)
        self.assertEqual(receipt["exact_min_probe_error"], 0.0)
        self.assertFalse(receipt["independent_Rdual_output_trained"])
        self.assertEqual(receipt["real1507_context_adapter"]["batch_size"], 4)
        self.assertFalse(torch.equal(before_scalar, model.head.scalar_head[-1].weight.detach()))
        if before_contact is not None:
            self.assertFalse(torch.equal(before_contact, model.head.contact_interaction.terminal.detach()))
        events = receipt["gradient_step_diagnostics"]
        self.assertEqual([event["accumulated_microbatches"] for event in events], [3, 1])
        self.assertEqual([event["partial_accumulation_window"] for event in events], [False, True])
        self.assertTrue(all(event["scalar"]["rank_pairs"] == 8 for event in events))
        self.assertTrue(all(event["core_gradient_event"]["global_all_parameter_clip_used"] is False for event in events))
        return receipt, model

    def test_strict_detached_cpu_smoke(self):
        receipt, _model = self.run_lane(mod.LANE_E)
        for event in receipt["gradient_step_diagnostics"]:
            core = event["core_gradient_event"]
            self.assertTrue(core["main_rng_restored"])
            self.assertEqual(core["mode"], mod.LANE_E)
            self.assertIn("scalar_clip_events", core)
            self.assertIn("contact_clip_events", core)

    def test_shared_gated_cpu_smoke(self):
        receipt, _model = self.run_lane(mod.LANE_F)
        for event in receipt["gradient_step_diagnostics"]:
            core = event["core_gradient_event"]
            self.assertEqual(core["mode"], mod.LANE_F)
            self.assertLessEqual(
                core["contact_capped_gradient_norm"],
                core["contact_budget_norm_limit"] + 1e-8,
            )
            self.assertEqual(core["kappa"], 0.25)

    def test_b_and_strict_detached_scalar_trajectories_match_on_real_model(self):
        torch.manual_seed(123)
        b_model = make_b_model()
        torch.manual_seed(123)
        e_model = make_model(shared=False)
        b_receipt, b_model = self.run_lane(mod.LANE_B, model=b_model)
        e_receipt, e_model = self.run_lane(mod.LANE_E, model=e_model)
        self.assertEqual(b_receipt["optimizer_steps"], e_receipt["optimizer_steps"])
        b_values = {
            name: value.detach()
            for name, value in b_model.named_parameters()
            if value.requires_grad and not name.startswith("head.contact_")
        }
        e_values = {
            name: value.detach()
            for name, value in e_model.named_parameters()
            if value.requires_grad and not name.startswith("head.contact_")
        }
        self.assertEqual(set(b_values), set(e_values))
        maximum = max(float((b_values[name] - e_values[name]).abs().max()) for name in b_values)
        self.assertLessEqual(maximum, 1e-7)

    def test_scalar_loss_contact_parameter_mutation_rejected(self):
        model = make_model(shared=False)
        role_mapping = opt_mod.role_mapping_from_v25_orthogonal_model(model)
        scalar_optimizer, contact_optimizer, _audit = opt_mod.build_role_optimizers(
            model, role_mapping, opt_mod.RoleOptimizerConfig(weight_decay=0.0)
        )

        def bad_scalar():
            return opt_mod.ScalarStepOutput(
                loss=model.head.contact_interaction.terminal.square().mean(),
                contact_payload={"x": torch.tensor(1.0)},
            )

        with self.assertRaisesRegex(opt_mod.RoleIsolationError, "scalar_loss_reaches_contact_parameters"):
            opt_mod.strict_detached_step(
                role_mapping=role_mapping,
                scalar_optimizer=scalar_optimizer,
                contact_optimizer=contact_optimizer,
                scalar_closure=bad_scalar,
                contact_closure=lambda payload: model.head.contact_interaction.terminal.square().mean(),
                rng_key=opt_mod.ContactRngKey(1, 0, 0, 0, 0),
                device="cpu",
                config=opt_mod.RoleOptimizerConfig(weight_decay=0.0),
            )


class TestContract(unittest.TestCase):
    def test_contract_is_explicitly_nonlaunching(self):
        contract = mod.integration_contract()
        self.assertEqual(contract["status"], "NONLAUNCHING_INTEGRATION_SURFACE")
        self.assertIn("score-partition truth", contract["forbidden"])
        self.assertFalse(contract["global_all_parameter_clip_allowed"])
        self.assertEqual(contract["derived_inference_target"], "exact_min(R_8X6B,R_9E6Y)")

    def test_fold_local_calibration_uses_inner_oof_and_exact_min(self):
        policy = mod.RankPolicyAdapter.load(RANK_V11, sha(RANK_V11))
        rows = []
        for parent_index in range(4):
            for candidate_index in range(4):
                truth8 = 0.2 + 0.02 * candidate_index + 0.01 * parent_index
                truth9 = 0.3 + 0.015 * candidate_index + 0.01 * parent_index
                rows.append(mod.InnerOofCalibrationInput(
                    candidate_id=f"P{parent_index}_{candidate_index}",
                    parent_cluster_id=f"P{parent_index}",
                    predicted_r8=(truth8 - 0.02) / 1.1,
                    predicted_r9=(truth9 + 0.01) / 0.9,
                    true_r8=truth8,
                    true_r9=truth9,
                ))
        calibration = mod.fit_fold_local_calibration_from_inner_oof(
            rows,
            outer_fold=0,
            outer_score_candidate_ids=("OUTER_ONLY",),
            rank_policy=policy,
        )
        applied = calibration.apply(torch.tensor([[0.4, 0.6], [0.7, 0.5]]))
        receptor = applied["calibrated_receptor_predictions"]
        self.assertTrue(torch.equal(applied["exact_min_dual"], torch.minimum(receptor[:, 0], receptor[:, 1])))
        mutated = list(rows)
        mutated[0] = mod.InnerOofCalibrationInput(
            "OUTER_ONLY", "P0", 0.2, 0.3, 0.2, 0.3,
        )
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "outer_score_candidate_in_inner_oof_calibration"):
            mod.fit_fold_local_calibration_from_inner_oof(
                mutated,
                outer_fold=0,
                outer_score_candidate_ids=("OUTER_ONLY",),
                rank_policy=policy,
            )


if __name__ == "__main__":
    unittest.main()
