from __future__ import annotations

import copy
import csv
import dataclasses
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock
from dataclasses import dataclass

import torch


HERE = pathlib.Path(__file__).resolve()
V26 = HERE.parents[2]
PACKAGE = V26 / "real1507_integration_v1_3_20260719"
ROOT = V26.parent
V25 = ROOT / "v2_5_ortho_contact_pose_stack_v1_20260718"
OPT = V26 / "implementation_v1_20260718" / "trainer"
RANK_V1 = V26 / "rank_calibration_v1_20260718" / "rank_calibration_core_v1.py"
RANK_V11 = V26 / "rank_calibration_v1_1_20260718" / "rank_calibration_core_v1_1.py"
BINDING = ROOT / "v2_6_noise_tolerance_binding_v1_20260718" / "V2_6_DELTA_NOISE_BINDING.json"
TRUST_SET = PACKAGE / "trust_anchor" / "frozen_real1507_trust_anchors_v1_3"
SPLIT_ROOT = ROOT / "v2_4_fs_stack_prototype_v1_20260718" / "split_contract" / "prepared" / "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4"
INNER_MANIFEST = SPLIT_ROOT / "inner_nested_oof_manifest.tsv"
OUTER_MANIFEST = SPLIT_ROOT / "outer_development_manifest.tsv"
TEACHER = ROOT / "v2_4_fs_stack_prototype_v1_20260718" / "data_contract" / "materialized_v1" / "v6_supervised1507_v2_4.tsv"
sys.path[:0] = [
    str(HERE.parent),
    str(V25 / "model"),
    str(V25 / "trainer"),
    str(OPT),
]

import real1507_role_isolated_trainer_v1_4 as mod
import residue_model_v2_5_ortho as model_mod
import role_isolated_optimization_v1 as opt_mod
import train_v2_5_ortho_heads as v25_mod


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, payload) -> pathlib.Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def make_rank_trust_anchor(policy, rows, train, outer_fold=0, inner_fold=0):
    train_rows = mod.extract_open_train_rows(rows, train)
    labels = policy.make_labels(train_rows)
    return {
        "schema_version": mod.RANK_TRUST_ANCHOR_SCHEMA,
        "status": "FROZEN_EXTERNAL_PRETRAINING_TRUST_ANCHOR",
        "created_before_runtime": True,
        "outer_fold": outer_fold,
        "inner_fold": inner_fold,
        "training_split_sha256": policy.module.compute_training_split_sha256(labels, outer_fold, inner_fold),
        "label_sha256": policy.module.compute_label_sha256(labels),
        "source_teacher_sha256": "a" * 64,
        "source_inner_manifest_sha256": "b" * 64,
        "scalar_train_label_count": len(labels),
        "v4_f_test32_access_count": 0,
    }


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

    def run_lane(
        self,
        lane: str,
        *,
        model=None,
        lambda_contact_shared=1.0,
        marginal_weight=0.2,
        pair_weight=0.1,
    ):
        model = model or make_model(shared=lane == mod.LANE_F)
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
                model_lane=model_mod.LANE_E,
                contact_encoder_gradient="shared" if lane == mod.LANE_F else "detached",
            ),
        )
        labels = self.policy.make_labels(mod.extract_open_train_rows(self.rows, self.train))
        trust_payload = {
            "training_split_sha256": self.policy.module.compute_training_split_sha256(labels, 0, 0),
            "label_sha256": self.policy.module.compute_label_sha256(labels),
            "source_teacher_sha256": mod.BOUND_TEACHER_SHA256,
            "source_inner_manifest_sha256": mod.BOUND_INNER_MANIFEST_SHA256,
            "scalar_train_label_count": len(labels),
            "status": "PASS_TEST_INJECTED_EXTERNAL_TRUST",
        }
        with mock.patch.object(mod, "load_external_rank_trust_anchor", return_value=trust_payload):
            receipt = mod.train_v25_real1507_context_nonlaunching(
                context=context,
                v25_api=v25_mod,
                optimizer_api=opt_mod,
                rank_policy=self.policy,
                delta_noise_binding_path=BINDING,
                scalar_loss_config=v25_mod.OrthoLossConfig(
                    receptor_weight=1.0, dual_weight=0.5, marginal_weight=0.0, pair_weight=0.0,
                ),
                contact_loss_config=v25_mod.OrthoLossConfig(
                    receptor_weight=1.0,
                    dual_weight=0.5,
                    marginal_weight=marginal_weight,
                    pair_weight=pair_weight,
                ),
                role_optimizer_config=opt_mod.RoleOptimizerConfig(
                    learning_rate=1e-3, contact_learning_rate=1e-3, weight_decay=0.0,
                    clip_shared=1.0, clip_scalar=1.0, clip_contact=1.0, kappa=0.25,
                    lambda_contact_shared=lambda_contact_shared,
                ),
                config=mod.V26TrainerConfig(
                    integration_lane=lane, fixed_epochs=1, gradient_accumulation=3,
                    lambda_rank=0.1, precision="fp32", base_seed=43, outer_fold=0, inner_fold=0,
                    expected_main_batches_per_epoch=4,
                    rank_trust_anchor_set_receipt_path="unit_test_injected_receipt.json",
                    rank_trust_anchor_dir="unit_test_injected_anchor_dir",
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
        if before_contact is not None and lane != mod.LANE_B:
            self.assertFalse(torch.equal(before_contact, model.head.contact_interaction.terminal.detach()))
        events = receipt["gradient_step_diagnostics"]
        self.assertEqual([event["accumulated_microbatches"] for event in events], [3, 1])
        self.assertEqual([event["partial_accumulation_window"] for event in events], [False, True])
        self.assertTrue(all(event["scalar"]["rank_pairs"] == 8 for event in events))
        self.assertTrue(all(event["core_gradient_event"]["global_all_parameter_clip_used"] is False for event in events))
        self.assertTrue(all(len(value) == 64 for event in events for value in event["evidence_hashes"].values()))
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
            self.assertTrue(core["post_lambda_contact_gradient_budget_pass"])
            self.assertLessEqual(
                core["post_lambda_contact_capped_gradient_norm"],
                core["post_lambda_contact_budget_norm_limit"] + core["post_lambda_contact_budget_tolerance"],
            )

    def test_shared_gated_marginal_only_cpu_smoke(self):
        receipt, _model = self.run_lane(mod.LANE_F, marginal_weight=1.0, pair_weight=0.0)
        self.assertEqual(receipt["contact_ablation"]["mode"], "MARGINAL_ONLY")
        self.assertEqual(receipt["contact_ablation"]["pair_weight"], 0.0)
        self.assertTrue(all(event["contact"]["contact_loss"] >= 0.0 for event in receipt["gradient_step_diagnostics"]))

    def test_shared_gated_pair_only_cpu_smoke(self):
        receipt, _model = self.run_lane(mod.LANE_F, marginal_weight=0.0, pair_weight=0.5)
        self.assertEqual(receipt["contact_ablation"]["mode"], "PAIR_ONLY")
        self.assertEqual(receipt["contact_ablation"]["marginal_weight"], 0.0)
        self.assertTrue(all(event["contact"]["contact_loss"] >= 0.0 for event in receipt["gradient_step_diagnostics"]))

    def test_lambda_contact_shared_bypass_is_rejected(self):
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "shared_contact_lambda_not_frozen"):
            self.run_lane(mod.LANE_F, lambda_contact_shared=2.0)

    def test_b_and_strict_detached_scalar_trajectories_match_on_real_model(self):
        torch.manual_seed(123)
        b_model = make_model(shared=False)
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
        rows, members = [], []
        ensemble_id = "outer_0_inner_oof_seeds_43_97_193"
        for parent_index in range(5):
            for candidate_index in range(4):
                truth8 = 0.2 + 0.02 * candidate_index + 0.01 * parent_index
                truth9 = 0.3 + 0.015 * candidate_index + 0.01 * parent_index
                candidate_id = f"P{parent_index}_{candidate_index}"
                members.append(mod.OuterTrainCalibrationMember(
                    candidate_id, f"P{parent_index}", 0, parent_index,
                ))
                for seed in mod.FROZEN_ENSEMBLE_SEEDS:
                    rows.append(mod.InnerOofCalibrationInput(
                        candidate_id=candidate_id, parent_cluster_id=f"P{parent_index}",
                        outer_fold=0, inner_fold=parent_index, seed=seed,
                        ensemble_id=ensemble_id, ensemble_member_id=f"inner_{parent_index}_seed_{seed}",
                        split_role="INNER_OOF_SCORE",
                        predicted_r8=(truth8 - 0.02) / 1.1 + seed * 1e-7,
                        predicted_r9=(truth9 + 0.01) / 0.9 - seed * 1e-7,
                        true_r8=truth8, true_r9=truth9,
                    ))
        receipt = mod.fit_fold_local_calibration_from_inner_oof(
            rows, outer_train_members=members, outer_fold=0,
            outer_score_candidate_ids=("OUTER_ONLY",), outer_score_parent_ids=("Q0",), rank_policy=policy,
        )
        self.assertEqual(receipt.seed_prediction_row_count, 60)
        self.assertEqual(receipt.to_payload()["seeds"], [43, 97, 193])
        applied = receipt.apply(torch.tensor([[0.4, 0.6], [0.7, 0.5]]))
        receptor = applied["calibrated_receptor_predictions"]
        self.assertTrue(torch.equal(applied["exact_min_dual"], torch.minimum(receptor[:, 0], receptor[:, 1])))

        with self.assertRaisesRegex(mod.Real1507IntegrationError, "calibration_seed_row_count_mismatch"):
            mod.fit_fold_local_calibration_from_inner_oof(
                rows[:-1], outer_train_members=members, outer_fold=0,
                outer_score_candidate_ids=("OUTER_ONLY",), outer_score_parent_ids=("Q0",), rank_policy=policy,
            )
        duplicated = list(rows[:-1]) + [rows[0]]
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "calibration_seed_member_duplicate"):
            mod.fit_fold_local_calibration_from_inner_oof(
                duplicated, outer_train_members=members, outer_fold=0,
                outer_score_candidate_ids=("OUTER_ONLY",), outer_score_parent_ids=("Q0",), rank_policy=policy,
            )
        wrong_seed = list(rows)
        wrong_seed[0] = dataclasses.replace(wrong_seed[0], seed=11, ensemble_member_id="inner_0_seed_11")
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "calibration_seed_invalid"):
            mod.fit_fold_local_calibration_from_inner_oof(
                wrong_seed, outer_train_members=members, outer_fold=0,
                outer_score_candidate_ids=("OUTER_ONLY",), outer_score_parent_ids=("Q0",), rank_policy=policy,
            )
        outer_parent_members = list(members)
        outer_parent_members[0] = dataclasses.replace(outer_parent_members[0], parent_cluster_id="Q0")
        with self.assertRaisesRegex(mod.Real1507IntegrationError, "outer_test_parent_in_calibration_members"):
            mod.fit_fold_local_calibration_from_inner_oof(
                rows, outer_train_members=outer_parent_members, outer_fold=0,
                outer_score_candidate_ids=("OUTER_ONLY",), outer_score_parent_ids=("Q0",), rank_policy=policy,
            )

    def test_external_rank_trust_anchor_mutation_rejected(self):
        policy = mod.RankPolicyAdapter.load(RANK_V11, sha(RANK_V11))
        receipt = TRUST_SET / "TRUST_ANCHOR_SET_RECEIPT.json"
        anchor = TRUST_SET / "outer_0_inner_0.rank_trust_anchor.json"
        self.assertEqual(sha(receipt), mod.BOUND_RANK_TRUST_ANCHOR_SET_RECEIPT_SHA256)
        payload = json.loads(anchor.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            copied_receipt = root / "TRUST_ANCHOR_SET_RECEIPT.json"
            copied_receipt.write_bytes(receipt.read_bytes())
            for source in TRUST_SET.glob("*.rank_trust_anchor.json"):
                (root / source.name).write_bytes(source.read_bytes())
            config = mod.V26TrainerConfig(
                integration_lane=mod.LANE_B,
                rank_trust_anchor_set_receipt_path=str(copied_receipt),
                rank_trust_anchor_dir=str(root),
            )
            copied = root / anchor.name
            payload["training_split_sha256"] = "0" * 64
            write_json(copied, payload)
            with self.assertRaisesRegex(mod.Real1507IntegrationError, "external_rank_trust_anchor_file_sha256_mismatch"):
                mod.load_external_rank_trust_anchor(config=config, rank_policy=policy, rank_labels=())
            copied.write_bytes(anchor.read_bytes())
            mutated_receipt = json.loads(copied_receipt.read_text())
            mutated_receipt["partition_count"] = 24
            write_json(copied_receipt, mutated_receipt)
            with self.assertRaisesRegex(mod.Real1507IntegrationError, "external_rank_trust_anchor_set_receipt_sha256_mismatch"):
                mod.load_external_rank_trust_anchor(config=config, rank_policy=policy, rank_labels=())

    def test_optimizer_state_hash_is_stable_by_parameter_name_across_process_equivalent_models(self):
        torch.manual_seed(101)
        model_a = make_b_model()
        optimizer_a = torch.optim.AdamW(model_a.parameters(), lr=1e-3)
        sum(parameter.square().sum() for parameter in model_a.parameters()).backward()
        optimizer_a.step()
        model_b = copy.deepcopy(model_a)
        optimizer_b = torch.optim.AdamW(model_b.parameters(), lr=1e-3)
        optimizer_b.load_state_dict(optimizer_a.state_dict())
        self.assertEqual(
            mod._optimizer_state_sha256(model_a, (optimizer_a,)),
            mod._optimizer_state_sha256(model_b, (optimizer_b,)),
        )

    def test_frozen_oof_calibration_requires_checkpoint_bound_prediction_receipts(self):
        policy = mod.RankPolicyAdapter.load(RANK_V11, sha(RANK_V11))
        with INNER_MANIFEST.open() as handle:
            inner_rows = list(csv.DictReader(handle, delimiter="\t"))
        with TEACHER.open() as handle:
            teacher = {row["candidate_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
        outer_fold = 0
        receipts = []
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for inner_fold in mod.FROZEN_INNER_FOLDS:
                score_rows = [
                    row for row in inner_rows
                    if int(row["outer_fold"]) == outer_fold
                    and int(row["inner_fold"]) == inner_fold
                    and row["candidate_role"] == "score"
                ]
                train_rows = [
                    row for row in inner_rows
                    if int(row["outer_fold"]) == outer_fold
                    and int(row["inner_fold"]) == inner_fold
                    and row["candidate_role"] == "train"
                ]
                score_sha = mod._candidate_parent_set_sha256(score_rows)
                train_sha = mod._candidate_parent_set_sha256(train_rows)
                for seed in mod.FROZEN_ENSEMBLE_SEEDS:
                    prefix = f"outer_{outer_fold}_inner_{inner_fold}_seed_{seed}"
                    checkpoint = root / f"{prefix}.pt"
                    checkpoint.write_bytes(f"checkpoint:{prefix}".encode())
                    checkpoint_receipt = write_json(root / f"{prefix}.checkpoint.json", {
                        "schema_version": "pvrig_v2_6_inner_checkpoint_receipt_v1_3",
                        "status": "PASS_INNER_TRAIN_CHECKPOINT_FROZEN",
                        "outer_fold": outer_fold, "inner_fold": inner_fold, "seed": seed,
                        "train_candidate_set_sha256": train_sha, "score_candidate_set_sha256": score_sha,
                        "source_inner_manifest_sha256": mod.BOUND_INNER_MANIFEST_SHA256,
                        "source_outer_manifest_sha256": mod.BOUND_OUTER_MANIFEST_SHA256,
                        "source_teacher_sha256": mod.BOUND_TEACHER_SHA256,
                        "trainer_schema_version": mod.SCHEMA_VERSION,
                        "checkpoint_path": checkpoint.name, "checkpoint_sha256": sha(checkpoint),
                        "v4_f_test32_access_count": 0, "outer_test_truth_access_count": 0,
                    })
                    prediction = root / f"{prefix}.predictions.tsv"
                    with prediction.open("w", newline="") as handle:
                        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=(
                            "candidate_id", "parent_framework_cluster", "predicted_r8", "predicted_r9",
                        ))
                        writer.writeheader()
                        for row in score_rows:
                            truth = teacher[row["candidate_id"]]
                            writer.writerow({
                                "candidate_id": row["candidate_id"],
                                "parent_framework_cluster": row["parent_framework_cluster"],
                                "predicted_r8": float(truth["R_8X6B"]) + seed * 1e-8,
                                "predicted_r9": float(truth["R_9E6Y"]) - seed * 1e-8,
                            })
                    receipt = write_json(root / f"{prefix}.prediction_receipt.json", {
                        "schema_version": mod.OOF_PREDICTION_RECEIPT_SCHEMA,
                        "status": "PASS_CHECKPOINT_BOUND_INNER_OOF_PREDICTIONS",
                        "trainer_schema_version": mod.SCHEMA_VERSION,
                        "source_inner_manifest_sha256": mod.BOUND_INNER_MANIFEST_SHA256,
                        "source_outer_manifest_sha256": mod.BOUND_OUTER_MANIFEST_SHA256,
                        "source_teacher_sha256": mod.BOUND_TEACHER_SHA256,
                        "outer_fold": outer_fold, "inner_fold": inner_fold, "seed": seed,
                        "train_candidate_set_sha256": train_sha, "score_candidate_set_sha256": score_sha,
                        "checkpoint_receipt_path": checkpoint_receipt.name,
                        "checkpoint_receipt_sha256": sha(checkpoint_receipt),
                        "prediction_path": prediction.name, "prediction_sha256": sha(prediction),
                        "prediction_row_count": len(score_rows),
                        "v4_f_test32_access_count": 0, "outer_test_truth_access_count": 0,
                    })
                    receipts.append(receipt)
            result = mod.fit_fold_local_calibration_from_frozen_oof_artifacts(
                inner_manifest_path=INNER_MANIFEST,
                outer_manifest_path=OUTER_MANIFEST,
                teacher_path=TEACHER,
                prediction_receipt_paths=receipts,
                outer_fold=outer_fold,
                rank_policy=policy,
            )
            self.assertEqual(result.outer_train_candidate_count, 1269)
            self.assertEqual(result.seed_prediction_row_count, 1269 * 3)
            mutated = json.loads(receipts[0].read_text())
            mutated["checkpoint_receipt_sha256"] = "0" * 64
            write_json(receipts[0], mutated)
            with self.assertRaisesRegex(mod.Real1507IntegrationError, "oof_checkpoint_receipt_sha256"):
                mod.fit_fold_local_calibration_from_frozen_oof_artifacts(
                    inner_manifest_path=INNER_MANIFEST, outer_manifest_path=OUTER_MANIFEST,
                    teacher_path=TEACHER, prediction_receipt_paths=receipts,
                    outer_fold=outer_fold, rank_policy=policy,
                )

    def test_weighted_window_mean_matches_concatenated_hierarchy_objective(self):
        values = [torch.tensor(2.0, requires_grad=True), torch.tensor(10.0, requires_grad=True)]
        result = mod._weighted_window_mean(values, [3.0, 1.0], "probe")
        self.assertAlmostEqual(float(result.detach()), 4.0, places=7)
        result.backward()
        self.assertAlmostEqual(float(values[0].grad), 0.75, places=7)
        self.assertAlmostEqual(float(values[1].grad), 0.25, places=7)

    def test_uneven_microbatch_scalar_and_contact_match_concatenated_candidates(self):
        loss = v25_mod.OrthoLossConfig(
            receptor_weight=1.0, dual_weight=0.5, marginal_weight=0.2, pair_weight=0.1,
        )

        def batch(count, weights, offset):
            residue = 3
            targets = torch.tensor(
                [[0.2 + 0.03 * (offset + i), 0.4 + 0.02 * (offset + i)] for i in range(count)],
                dtype=torch.float32,
            )
            marginal_targets = torch.full((count, residue, 2), 0.2)
            marginal_targets[:, 0, :] = 0.8
            value = {
                "candidate_ids": [f"C{offset+i}" for i in range(count)],
                "targets": targets,
                "hierarchy_weights": torch.tensor(weights, dtype=torch.float32),
                "marginal_targets": marginal_targets,
                "marginal_mask": torch.ones_like(marginal_targets, dtype=torch.bool),
                "marginal_uncertainty": torch.ones_like(marginal_targets),
                "marginal_tier_weights": torch.tensor([1.0 if i % 2 == 0 else 0.5 for i in range(count)]),
                "pair_tier_weights": torch.tensor([1.0 if i % 2 == 0 else 0.25 for i in range(count)]),
            }
            for receptor, nodes in (("8x6b", 2), ("9e6y", 4)):
                pair = marginal_targets[:, :, 0].unsqueeze(-1).expand(count, residue, nodes).clone()
                value[f"pair_targets_{receptor}"] = pair
                value[f"pair_mask_{receptor}"] = torch.ones_like(pair, dtype=torch.bool)
                value[f"pair_uncertainty_{receptor}"] = torch.ones_like(pair)
            output = {
                "receptor_predictions": targets + torch.tensor([0.04, -0.03]),
                "marginal_contact_logits": torch.linspace(-0.6, 0.8, count * residue * 2).reshape(count, residue, 2),
                "contact_logits_8x6b": torch.linspace(-0.8, 0.7, count * residue * 2).reshape(count, residue, 2),
                "contact_logits_9e6y": torch.linspace(-0.9, 0.9, count * residue * 4).reshape(count, residue, 4),
            }
            return value, output

        b1, o1 = batch(3, [1.0, 7.0, 2.0], 0)
        b2, o2 = batch(1, [5.0], 3)
        _t1, p1 = v25_mod.compute_loss(o1, b1, model_mod.LANE_E, loss)
        _t2, p2 = v25_mod.compute_loss(o2, b2, model_mod.LANE_E, loss)
        combined_batch = {}
        for key in b1:
            combined_batch[key] = b1[key] + b2[key] if isinstance(b1[key], list) else torch.cat((b1[key], b2[key]), dim=0)
        combined_output = {key: torch.cat((o1[key], o2[key]), dim=0) for key in o1}
        _total, expected = v25_mod.compute_loss(combined_output, combined_batch, model_mod.LANE_E, loss)

        scalar = mod._weighted_window_mean(
            [p1["scalar"], p2["scalar"]],
            [mod._raw_hierarchy_mass(b1), mod._raw_hierarchy_mass(b2)],
            "scalar_probe",
        )
        marginal = mod._weighted_window_mean(
            [p1["marginal_contact"], p2["marginal_contact"]],
            [mod._contact_effective_hierarchy_mass(b1, "marginal"), mod._contact_effective_hierarchy_mass(b2, "marginal")],
            "marginal_probe",
        )
        pair = mod._weighted_window_mean(
            [p1["pair_contact"], p2["pair_contact"]],
            [mod._contact_effective_hierarchy_mass(b1, "pair"), mod._contact_effective_hierarchy_mass(b2, "pair")],
            "pair_probe",
        )
        self.assertTrue(torch.allclose(scalar, expected["scalar"], atol=1e-7, rtol=0.0))
        self.assertTrue(torch.allclose(marginal, expected["marginal_contact"], atol=1e-7, rtol=0.0))
        self.assertTrue(torch.allclose(pair, expected["pair_contact"], atol=1e-7, rtol=0.0))
        equal_microbatch_mean = torch.stack((p1["scalar"], p2["scalar"])).mean()
        self.assertGreater(abs(float(equal_microbatch_mean - expected["scalar"])), 1e-6)


class TestFrozenRealTrustAnchors(unittest.TestCase):
    def test_all_25_external_anchors_have_hash_and_source_closure(self):
        receipt = json.loads((TRUST_SET / "TRUST_ANCHOR_SET_RECEIPT.json").read_text())
        self.assertEqual(receipt["status"], "PASS_25_EXTERNAL_PRETRAINING_TRUST_ANCHORS_FROZEN")
        self.assertEqual(receipt["partition_count"], 25)
        self.assertEqual(receipt["v4_f_test32_access_count"], 0)
        self.assertEqual(set(receipt["files"]), {
            f"outer_{outer}_inner_{inner}.rank_trust_anchor.json"
            for outer in range(5) for inner in range(5)
        })
        for name, expected in receipt["files"].items():
            path = TRUST_SET / name
            self.assertTrue(path.is_file() and not path.is_symlink())
            self.assertEqual(sha(path), expected)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["schema_version"], mod.RANK_TRUST_ANCHOR_SCHEMA)
            self.assertEqual(payload["status"], "FROZEN_EXTERNAL_PRETRAINING_TRUST_ANCHOR")
            self.assertTrue(payload["created_before_runtime"])
            self.assertEqual(payload["v4_f_test32_access_count"], 0)


if __name__ == "__main__":
    unittest.main()
