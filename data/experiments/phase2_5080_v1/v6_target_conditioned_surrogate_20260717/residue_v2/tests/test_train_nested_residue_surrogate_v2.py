#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch.optim import AdamW


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import train_nested_residue_surrogate_v2 as mod  # noqa: E402
import select_contact_loss_gradient_grid_v2 as selector_v2  # noqa: E402


def args_for(lane: str) -> argparse.Namespace:
    args = mod.parser().parse_args([
        "--training-tsv", "training.tsv",
        "--contact-tsv-gz", "contacts.tsv.gz",
        "--preregistration", "prereg.json",
        "--output-dir", "output",
        "--lane", lane,
        "--outer-fold", "0",
        "--smoke-mode",
        "--backbone-kind", "tiny",
        "--tiny-hidden-size", "16",
        "--structure-dim", "4",
        "--graph-hidden-dim", "32",
        "--max-epochs", "1",
        "--gradient-accumulation", "1",
        "--evaluation-batch-size", "8",
        "--precision", "fp32",
        "--device", "cpu",
    ])
    args.structure_prefix = ["S__"]
    return args


def valid_amendment_payload(args: argparse.Namespace) -> dict[str, object]:
    fractions = (0.10, 0.16, 0.24, 0.35)
    grid_results = []
    for index, ((marginal, pair), fraction) in enumerate(zip(mod.CONTACT_GRADIENT_GRID, fractions, strict=True)):
        grid_results.append({
            "grid_index": index,
            "marginal_contact_weight": marginal,
            "pair_contact_weight": pair,
            "lane_direct_contact_gradient_fractions": {lane: fraction for lane in mod.LANES},
            "all_lanes_in_target_band": mod.CONTACT_GRADIENT_TARGET_MIN <= fraction <= mod.CONTACT_GRADIENT_TARGET_MAX,
            "hard_ceiling_pass": fraction <= mod.CONTACT_GRADIENT_HARD_MAX,
        })
    return {
        **mod.contact_loss_amendment_contract(args),
        "status": mod.CONTACT_LOSS_AMENDMENT_STATUS,
        "calibration": {
            "schema_version": "pvrig_v6_residue_v2_contact_gradient_calibration_v1",
            "status": "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_GRADIENT_CALIBRATION",
            "grid": [
                {"marginal_contact_weight": marginal, "pair_contact_weight": pair}
                for marginal, pair in mod.CONTACT_GRADIENT_GRID
            ],
            "selection_rule": "smallest_grid_entry_with_all_lanes_in_target_band_and_no_lane_above_hard_ceiling",
            "target_fraction_min": mod.CONTACT_GRADIENT_TARGET_MIN,
            "target_fraction_max": mod.CONTACT_GRADIENT_TARGET_MAX,
            "hard_ceiling": mod.CONTACT_GRADIENT_HARD_MAX,
            "selected_grid_index": 0,
            "selected_weights": {
                "marginal_contact_weight": mod.CONTACT_GRADIENT_GRID[0][0],
                "pair_contact_weight": mod.CONTACT_GRADIENT_GRID[0][1],
            },
            "grid_results": grid_results,
            "open_only": True,
            "optimizer_steps_before_observation": 0,
            "gradient_batches_per_lane": 1,
            "v4_f_test32_access_count": 0,
            "input_hashes": {lane: "a" * 64 for lane in mod.LANES},
        },
    }


def valid_amendment_payload_v2_2() -> dict[str, object]:
    raw_by_lane = {
        "A_DOMAIN": {"dual": 1.0, "receptor": 0.0, "marginal": 9.836, "ranking": 0.0, "residual": 0.0},
        "B_VHH3D": {"dual": 1.0, "receptor": 0.0, "marginal": 25.80, "ranking": 0.0, "residual": 0.0},
        "C_PATCH": {"dual": 1.0, "receptor": 0.0, "marginal": 93.35, "ranking": 0.0, "residual": 0.0},
        "D_FULL_PAIR": {"dual": 1.0, "receptor": 0.0, "marginal": 90.6, "ranking": 0.0, "residual": 0.0, "pair": 90.6},
    }
    observations = {
        lane: {
            "unweighted_gradient_l2_norm": raw,
            "candidate_ids_sha256": "a" * 64,
            "teacher_source_counts": {mod.V4D: 2, mod.V4H: 6},
        }
        for lane, raw in raw_by_lane.items()
    }
    amendment, _report = selector_v2.build_calibration(
        observations, {lane: "b" * 64 for lane in mod.LANES},
    )
    return amendment


def make_rows() -> list[mod.v1.TrainingRow]:
    rows = []
    for index in range(8):
        sequence = "ACDE"
        source_offset = 0.02 if index >= 2 else 0.0
        first = 0.30 + source_offset + index * 0.005
        second = 0.34 + source_offset + index * 0.004
        rows.append(mod.v1.TrainingRow(
            candidate_id=f"C{index}",
            sequence=sequence,
            sequence_sha256=hashlib.sha256(sequence.encode()).hexdigest(),
            parent=f"P{index // 2}",
            outer_fold=index % 5,
            targets=(first, second, min(first, second)),
            weight=1.0,
            structure=(float(index), 0.5, -0.5, 1.0),
            contact_targets=tuple((0.2 + residue * 0.1, 0.3 + residue * 0.1) for residue in range(4)),
            contact_mask=tuple((True, True) for _ in range(4)),
        ))
    return rows


class FakeGraphStore:
    edge_feature_dim = 26

    def graph(self, candidate_id: str) -> dict[str, np.ndarray]:
        del candidate_id
        edges = np.asarray([[0, 1, 1, 2, 2, 3], [1, 0, 2, 1, 3, 2]], dtype=np.int64)
        features = np.zeros((edges.shape[1], self.edge_feature_dim), dtype=np.float32)
        features[:, 0] = 1.0
        return {
            "aa_index": np.asarray([0, 1, 2, 3]),
            "region_index": np.asarray([0, 1, 2, 3]),
            "confidence": np.asarray([0.8, 0.8, 0.8, 0.8], dtype=np.float32),
            "edge_index": edges,
            "edge_features": features,
        }


def target_graph(nodes: int, node_dim: int = 7, edge_dim: int = 26) -> dict[str, torch.Tensor]:
    edges = []
    for index in range(nodes - 1):
        edges.extend(((index, index + 1), (index + 1, index)))
    return {
        "node_features": torch.arange(nodes * node_dim, dtype=torch.float32).reshape(nodes, node_dim) / 100.0,
        "edge_index": torch.tensor(edges, dtype=torch.long).T.contiguous(),
        "edge_features": torch.zeros((len(edges), edge_dim), dtype=torch.float32),
        "interface_mask": torch.tensor([(index % 2) == 0 for index in range(nodes)]),
        "hotspot_mask": torch.tensor([index in {1, 2} for index in range(nodes)]),
    }


class LaneAndCheckpointTests(unittest.TestCase):
    def test_all_four_lanes_build_with_frozen_backbone_and_head_only_checkpoint(self) -> None:
        architectures = {}
        for lane in mod.LANES:
            args = args_for(lane)
            model, _tokenizer, contract = mod.build_model(
                args,
                edge_feature_dim=26,
                target_node_dim=7,
                device=torch.device("cpu"),
            )
            self.assertFalse(any(parameter.requires_grad for parameter in model.backbone.parameters()))
            checkpoint = mod.head_checkpoint_state(model)
            self.assertTrue(checkpoint)
            self.assertTrue(all(name.startswith("head.") for name in checkpoint))
            self.assertFalse(any(name.startswith("backbone.") for name in checkpoint))
            mod.load_head_checkpoint_state(model, checkpoint)
            self.assertEqual(contract["checkpoint_policy"], "head_only_no_backbone_no_optimizer")
            architectures[lane] = contract["architecture"] if "architecture" in contract else contract["interaction"]
        self.assertEqual(architectures["A_DOMAIN"], "frozen_v1_5_sequence_head")
        self.assertEqual(architectures["B_VHH3D"], "vhh_graph_without_target_conditioning")
        self.assertIn("rank64", architectures["C_PATCH"])
        self.assertIn("rank64", architectures["D_FULL_PAIR"])

    def test_lane_contracts_require_only_the_preregistered_inputs(self) -> None:
        prereg = {
            "training": {},
            "loss": {},
        }
        a = args_for("A_DOMAIN")
        mod.validate_frozen_arguments(a, prereg)
        b = args_for("B_VHH3D")
        with self.assertRaisesRegex(mod.TrainerV2Error, "graph_cache_required"):
            mod.validate_frozen_arguments(b, prereg)
        c = args_for("C_PATCH")
        c.graph_cache_dir = Path("graphs")
        with self.assertRaisesRegex(mod.TrainerV2Error, "target_graph_required"):
            mod.validate_frozen_arguments(c, prereg)
        d = args_for("D_FULL_PAIR")
        d.graph_cache_dir = Path("graphs")
        d.target_graph_pt = Path("target.pt")
        with self.assertRaisesRegex(mod.TrainerV2Error, "pair_targets_required"):
            mod.validate_frozen_arguments(d, prereg)

    def test_teacher_source_is_not_a_forward_feature(self) -> None:
        self.assertNotIn("teacher_source", inspect.signature(mod.VHHGraphOnlyHead.forward).parameters)
        self.assertNotIn("teacher_source", inspect.signature(mod.TargetConditionedResidueV2Head.forward).parameters)
        self.assertNotIn("teacher_source", inspect.signature(mod.DualContactResidualHead.forward).parameters)


class CollatorAndEpochTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = make_rows()
        self.sources = [mod.V4D] * 2 + [mod.V4H] * 6
        self.bases = {index: np.asarray(row.targets, dtype=np.float64) for index, row in enumerate(self.rows)}
        self.uncertainty = {index: np.ones((4, 2), dtype=np.float32) for index in range(8)}

    def test_graph_collator_translates_edges_to_nonpadding_token_positions(self) -> None:
        collator = mod.V2Collator(
            self.rows,
            mod.v1.TinyTokenizer(),
            self.bases,
            self.sources,
            self.uncertainty,
            graph_store=FakeGraphStore(),
            pair_store=None,
            target_nodes={},
        )
        batch = collator(list(range(8)))
        self.assertEqual(Counter(batch["teacher_sources"]), Counter({mod.V4D: 2, mod.V4H: 6}))
        self.assertNotIn("teacher_source", batch)
        flat_mask = batch["residue_mask"].reshape(-1)
        self.assertTrue(torch.all(flat_mask[batch["vhh_edge_index"].reshape(-1)]))
        self.assertEqual(batch["vhh_edge_features"].shape, (48, 26))

    def test_one_domain_balanced_training_epoch_reports_each_source(self) -> None:
        args = args_for("B_VHH3D")
        model, tokenizer, _contract = mod.build_model(
            args,
            edge_feature_dim=26,
            target_node_dim=1,
            device=torch.device("cpu"),
        )
        loader = mod.make_loader(
            self.rows,
            list(range(8)),
            tokenizer,
            self.bases,
            self.sources,
            self.uncertainty,
            args,
            graph_store=FakeGraphStore(),
            pair_store=None,
            target_nodes={},
            training=True,
            seed=917,
        )
        optimizer = AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=1e-4)
        metrics, records = mod.run_epoch(
            model, loader, args.lane, None, args, torch.device("cpu"), optimizer,
        )
        self.assertEqual(len(records), 8)
        self.assertEqual(metrics[mod.V4D]["rows"], 2)
        self.assertEqual(metrics[mod.V4H]["rows"], 6)
        self.assertIn("loss", metrics)
        self.assertEqual(metrics["M2_BASELINE"][mod.V4D]["rows"], 2)
        self.assertEqual(metrics["sampler_audit"]["microbatch_quota"], {mod.V4D: 2, mod.V4H: 6})
        self.assertIn("dual_V4D_OPEN_MULTI_SEED", metrics["loss"])
        self.assertIn("dual_V4H_STAGE1_SEED917", metrics["loss"])
        telemetry = metrics["component_telemetry"]
        self.assertEqual(telemetry["gradient_batches_observed"], 1)
        self.assertAlmostEqual(sum(telemetry["gradient_fraction_mean"].values()), 1.0, places=6)
        self.assertAlmostEqual(sum(telemetry["weighted_contribution_fraction_mean"].values()), 1.0, places=6)
        self.assertEqual(telemetry["contact_loss_normalization"], mod.CONTACT_LOSS_NORMALIZATION)
        observation = telemetry["calibration_observation_first_batch"]
        self.assertEqual(observation["optimizer_steps_before_observation"], 0)
        self.assertEqual(observation["v4_f_test32_access_count"], 0)
        self.assertEqual(observation["gradient_batches_in_observation"], 1)
        self.assertEqual(set(observation["unweighted_gradient_l2_norm"]), set(telemetry["component_weights"]))
        exact_by_id = {row.candidate_id: row.targets[2] for row in self.rows}
        self.assertTrue(all(record["R_dual_min"] == exact_by_id[record["candidate_id"]] for record in records))

    def test_c_lane_integrates_collator_graphs_and_dual_target_graph_model(self) -> None:
        args = args_for("C_PATCH")
        model, tokenizer, _contract = mod.build_model(
            args, edge_feature_dim=26, target_node_dim=7, device=torch.device("cpu"),
        )
        collator = mod.V2Collator(
            self.rows, tokenizer, self.bases, self.sources, self.uncertainty,
            graph_store=FakeGraphStore(), pair_store=None, target_nodes={},
        )
        batch = collator(list(range(8)))
        graphs = {"8x6b": target_graph(5), "9e6y": target_graph(6)}
        model.eval()
        output = mod.forward_model(model, args.lane, batch, graphs)
        self.assertEqual(output["prediction"].shape, (8, 3))
        self.assertEqual(output["pair_logits_8x6b"].shape, (8, 6, 5))
        self.assertEqual(output["pair_logits_9e6y"].shape, (8, 6, 6))

    def test_sparse_pair_contract_expands_absence_to_observed_exact_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pairs.tsv"
            fields = sorted(mod.PAIR_REQUIRED | {"pvrig_node_index"})
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for row in self.rows:
                    for receptor in mod.RECEPTOR_NAMES:
                        writer.writerow({
                            "candidate_id": row.candidate_id,
                            "sequence_sha256": row.sequence_sha256,
                            "parent_framework_cluster": row.parent,
                            "receptor": receptor,
                            "vhh_sequence_index": 1,
                            "pvrig_node_index": 1,
                            "contact_target": 0.75,
                            "contact_uncertainty_weight": 1.0,
                            "target_mask": 1,
                            "pair_table_semantics": "SPARSE_ABSENCE_IS_EXACT_ZERO",
                        })
            store = mod.PairTargetStore(path, self.rows, {"8x6b": 3, "9e6y": 4})
            collator = mod.V2Collator(
                self.rows, mod.v1.TinyTokenizer(), self.bases, self.sources, self.uncertainty,
                graph_store=None, pair_store=store, target_nodes={"8x6b": 3, "9e6y": 4},
            )
            batch = collator(list(range(8)))
            self.assertEqual(int(batch["pair_mask_8x6b"].sum()), 8 * 4 * 3)
            self.assertEqual(int(batch["pair_mask_9e6y"].sum()), 8 * 4 * 4)
            self.assertEqual(int((batch["pair_targets_8x6b"] > 0).sum()), 8)


class ContactLossAmendmentTests(unittest.TestCase):
    @staticmethod
    def balanced(logits, targets, weights=None, mask=None):
        logits = torch.tensor([logits], dtype=torch.float64, requires_grad=True)
        targets = torch.tensor([targets], dtype=torch.float64)
        weights = torch.ones_like(targets) if weights is None else torch.tensor([weights], dtype=torch.float64)
        mask = torch.ones_like(targets, dtype=torch.bool) if mask is None else torch.tensor([mask], dtype=torch.bool)
        return mod.balanced_soft_bce_per_candidate_receptor(
            logits, targets, weights, mask,
            positive_class_fraction=0.5,
            epsilon=1e-8,
        )

    def test_no_positive_uses_full_negative_loss_and_exact_zero_is_negative(self) -> None:
        value, available, audit = self.balanced([-1.0, 1.0], [0.0, 0.0])
        expected = torch.nn.functional.softplus(torch.tensor([-1.0, 1.0], dtype=torch.float64)).mean()
        self.assertTrue(bool(available[0]))
        self.assertAlmostEqual(float(value[0]), float(expected), places=12)
        self.assertEqual(float(audit["negative_only_candidates"]), 1.0)
        self.assertEqual(float(audit["positive_mass"]), 0.0)

    def test_no_negative_uses_full_positive_loss(self) -> None:
        value, available, audit = self.balanced([-1.0, 1.0], [1.0, 1.0])
        expected = torch.nn.functional.softplus(-torch.tensor([-1.0, 1.0], dtype=torch.float64)).mean()
        self.assertTrue(bool(available[0]))
        self.assertAlmostEqual(float(value[0]), float(expected), places=12)
        self.assertEqual(float(audit["positive_only_candidates"]), 1.0)
        self.assertEqual(float(audit["negative_mass"]), 0.0)

    def test_soft_target_contributes_positive_mass_and_negative_mass(self) -> None:
        value, available, audit = self.balanced([2.0], [0.25])
        positive = torch.nn.functional.softplus(torch.tensor(-2.0, dtype=torch.float64))
        negative = torch.nn.functional.softplus(torch.tensor(2.0, dtype=torch.float64))
        self.assertTrue(bool(available[0]))
        self.assertAlmostEqual(float(value[0]), float(0.5 * positive + 0.5 * negative), places=12)
        self.assertAlmostEqual(float(audit["positive_mass"]), 0.25, places=12)
        self.assertAlmostEqual(float(audit["negative_mass"]), 0.75, places=12)

    def test_masked_values_are_excluded_and_all_masked_is_unavailable(self) -> None:
        value, available, audit = self.balanced([0.0, 1000.0], [0.5, 0.0], mask=[True, False])
        self.assertTrue(bool(available[0]))
        self.assertAlmostEqual(float(value[0]), math.log(2.0), places=12)
        self.assertEqual(float(audit["both_class_candidates"]), 1.0)
        missing, missing_available, missing_audit = self.balanced([0.0], [0.5], mask=[False])
        self.assertFalse(bool(missing_available[0]))
        self.assertEqual(float(missing[0]), 0.0)
        self.assertEqual(float(missing_audit["unavailable_candidates"]), 1.0)

    def test_many_exact_zeros_do_not_overwhelm_one_soft_positive(self) -> None:
        few, _, _ = self.balanced([1.0] + [-2.0] * 3, [1.0] + [0.0] * 3)
        many, _, _ = self.balanced([1.0] + [-2.0] * 300, [1.0] + [0.0] * 300)
        self.assertAlmostEqual(float(few[0].detach()), float(many[0].detach()), places=12)

    def test_contact_candidate_losses_are_equal_source_balanced(self) -> None:
        loss_v4d = 1.0
        loss_v4h = 3.0
        logit_v4d = math.log(math.expm1(loss_v4d))
        logit_v4h = math.log(math.expm1(loss_v4h))
        logits = torch.tensor([[logit_v4d]] * 2 + [[logit_v4h]] * 6, dtype=torch.float64)
        targets = torch.zeros_like(logits)
        values, available, _ = mod.balanced_soft_bce_per_candidate_receptor(
            logits, targets, torch.ones_like(targets), torch.ones_like(targets, dtype=torch.bool),
            positive_class_fraction=0.5, epsilon=1e-8,
        )
        combined, means = mod.source_balanced_component(
            values, [mod.V4D] * 2 + [mod.V4H] * 6, available_mask=available,
        )
        self.assertAlmostEqual(float(means[mod.V4D]), loss_v4d, places=12)
        self.assertAlmostEqual(float(means[mod.V4H]), loss_v4h, places=12)
        self.assertAlmostEqual(float(combined), 2.0, places=12)

    def test_amendment_parameters_are_exposed_and_formal_run_requires_independent_amendment(self) -> None:
        args = args_for("A_DOMAIN")
        contract = mod.contact_loss_amendment_contract(args)
        self.assertEqual(contract["positive_class_fraction"], 0.5)
        self.assertEqual(contract["gradient_telemetry_batches_per_epoch"], 1)
        prereg = json.loads((ROOT / "PREREGISTRATION_V2.json").read_text())
        args.smoke_mode = False
        with self.assertRaisesRegex(mod.TrainerV2Error, "formal_contact_loss_amendment_required"):
            mod.validate_frozen_arguments(args, prereg)
        with tempfile.TemporaryDirectory() as temporary:
            args.max_epochs = prereg["training"]["maximum_epochs"]
            args.gradient_accumulation = prereg["training"]["gradient_accumulation"]
            args.structure_dim = 126
            args.graph_hidden_dim = 128
            args.backbone_kind = "hf"
            args.precision = prereg["training"]["precision"]
            args.contact_receipt = Path("receipt.json")
            args.contact_loss_amendment = Path(temporary) / "CONTACT_LOSS_AMENDMENT.json"
            args.marginal_contact_weight, args.pair_contact_weight = mod.CONTACT_GRADIENT_GRID[0]
            legacy = valid_amendment_payload(args)
            args.contact_loss_amendment.write_text(json.dumps(legacy))
            self.assertEqual(mod.validate_contact_loss_amendment(args.contact_loss_amendment, args), legacy)
            with self.assertRaisesRegex(mod.TrainerV2Error, "amendment_v2_2_(field_closure|schema)"):
                mod.validate_frozen_arguments(args, prereg)
            payload = valid_amendment_payload_v2_2()
            selected = payload["lane_weights"][args.lane]  # type: ignore[index]
            args.marginal_contact_weight = selected["marginal_contact_weight"]  # type: ignore[index]
            args.pair_contact_weight = selected["pair_contact_weight"]  # type: ignore[index]
            args.contact_loss_amendment.write_text(json.dumps(payload))
            loaded = mod.validate_frozen_arguments(args, prereg)
            self.assertEqual(loaded, payload)
            args.contact_positive_class_fraction = 0.6
            with self.assertRaisesRegex(mod.TrainerV2Error, "amendment_v2_2_mismatch:positive_class_fraction"):
                mod.validate_frozen_arguments(args, prereg)

    def test_v2_2_formal_validation_uses_current_lane_weight(self) -> None:
        prereg = json.loads((ROOT / "PREREGISTRATION_V2.json").read_text())
        payload = valid_amendment_payload_v2_2()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "amendment.json"
            path.write_text(json.dumps(payload))
            for lane in mod.LANES:
                args = args_for(lane)
                args.smoke_mode = False
                args.max_epochs = prereg["training"]["maximum_epochs"]
                args.gradient_accumulation = prereg["training"]["gradient_accumulation"]
                args.structure_dim = 126
                args.graph_hidden_dim = 128
                args.backbone_kind = "hf"
                args.precision = prereg["training"]["precision"]
                args.contact_receipt = Path("receipt.json")
                args.contact_loss_amendment = path
                selected = payload["lane_weights"][lane]  # type: ignore[index]
                args.marginal_contact_weight = selected["marginal_contact_weight"]  # type: ignore[index]
                args.pair_contact_weight = selected["pair_contact_weight"]  # type: ignore[index]
                if lane in mod.GRAPH_LANES:
                    args.graph_cache_dir = Path("graphs")
                if lane in mod.TARGET_LANES:
                    args.target_graph_pt = Path("target.pt")
                    args.target_graph_receipt = Path("target.receipt.json")
                if lane in mod.PAIR_LANES:
                    args.pair_contact_tsv_gz = Path("pairs.tsv.gz")
                mod.validate_frozen_arguments(args, prereg)
                args.marginal_contact_weight *= 2.0
                with self.assertRaisesRegex(mod.TrainerV2Error, "current_lane_marginal"):
                    mod.validate_frozen_arguments(args, prereg)

    def test_amendment_rejects_tampered_calibration_and_weight(self) -> None:
        args = args_for("A_DOMAIN")
        args.marginal_contact_weight, args.pair_contact_weight = mod.CONTACT_GRADIENT_GRID[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "amendment.json"
            payload = valid_amendment_payload(args)
            payload["calibration"]["selected_grid_index"] = 1  # type: ignore[index]
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.TrainerV2Error, "not_smallest_passing_grid"):
                mod.validate_contact_loss_amendment(path, args)
            payload = valid_amendment_payload(args)
            payload["normalization"] = "tampered"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.TrainerV2Error, "mismatch:normalization"):
                mod.validate_contact_loss_amendment(path, args)

    def test_terminal_telemetry_summarizes_training_segments(self) -> None:
        telemetry = {
            "gradient_fraction_mean": {"dual": 0.75, "marginal": 0.25},
            "weighted_gradient_l2_norm_mean": {"dual": 3.0, "marginal": 1.0},
            "unweighted_gradient_l2_norm_mean": {"dual": 3.0, "marginal": 10000.0},
            "weighted_contribution_fraction_mean": {"dual": 0.9, "marginal": 0.1},
        }
        inner = [{"inner_fold": 2, "history": [{"epoch": 0, "train": {"component_telemetry": telemetry}}]}]
        final = {"training_history": [{"epoch": 0, "train": {"component_telemetry": telemetry}}]}
        summary = mod.summarize_component_telemetry(inner, final)
        self.assertEqual(summary["training_segment_count"], 2)
        self.assertEqual(summary["gradient_fraction_mean"], telemetry["gradient_fraction_mean"])
        self.assertEqual({row["stage"] for row in summary["segments"]}, {"inner_selection", "final_refit"})


class LossAndSplitTests(unittest.TestCase):
    def make_loss_batch(self) -> tuple[dict[str, object], dict[str, torch.Tensor]]:
        batch: dict[str, object] = {
            "teacher_sources": [mod.V4D] * 2 + [mod.V4H] * 6,
            "weights": torch.ones(8),
            "targets": torch.tensor([[0.4, 0.5, 0.4]] * 8),
            "parents": ["P0", "P0", "P1", "P1", "P2", "P2", "P3", "P3"],
            "contact_targets": torch.ones((8, 4, 2)),
            "contact_uncertainty": torch.ones((8, 4, 2)),
            "contact_mask": torch.ones((8, 4, 2), dtype=torch.bool),
        }
        output = {
            "prediction": torch.full((8, 3), 0.45, requires_grad=True),
            "residual": torch.full((8, 3), 0.01, requires_grad=True),
            "marginal_contact_logits": torch.zeros((8, 4, 2), requires_grad=True),
            "pair_logits_8x6b": torch.zeros((8, 4, 3), requires_grad=True),
            "pair_logits_9e6y": torch.zeros((8, 4, 3), requires_grad=True),
        }
        for receptor in mod.RECEPTOR_NAMES:
            batch[f"pair_targets_{receptor}"] = torch.ones((8, 4, 3))
            batch[f"pair_uncertainty_{receptor}"] = torch.ones((8, 4, 3))
            batch[f"pair_mask_{receptor}"] = torch.ones((8, 4, 3), dtype=torch.bool)
        return batch, output

    def test_pair_bce_is_disabled_in_c_and_enabled_only_in_d(self) -> None:
        batch, output = self.make_loss_batch()
        c_args = args_for("C_PATCH")
        c_loss, c_parts = mod.compute_v2_loss(output, batch, c_args)
        self.assertNotIn("pair", c_parts)
        d_args = args_for("D_FULL_PAIR")
        d_loss, d_parts = mod.compute_v2_loss(output, batch, d_args)
        self.assertIn("pair", d_parts)
        self.assertGreater(float(d_loss.detach()), float(c_loss.detach()))
        d_loss.backward()
        self.assertIsNotNone(output["pair_logits_8x6b"].grad)

    def test_outer_fold_and_crossfit_are_whole_parent_and_v1_5_compatible(self) -> None:
        rows = []
        for parent_index in range(15):
            for member in range(2):
                target = 0.2 + parent_index * 0.01 + member * 0.002
                rows.append(mod.v1.TrainingRow(
                    candidate_id=f"P{parent_index}_{member}", sequence="ACDE",
                    sequence_sha256=hashlib.sha256(b"ACDE").hexdigest(),
                    parent=f"P{parent_index}", outer_fold=parent_index % 5,
                    targets=(target, target + 0.02, target), weight=1.0,
                    structure=(float(parent_index), float(member)),
                    contact_targets=((0.0, 0.0),) * 4, contact_mask=((True, True),) * 4,
                ))
        mod.validate_outer_fold_closure(rows)
        arrays = mod.v1.arrays_from_rows(rows)
        selected = [index for index, row in enumerate(rows) if row.outer_fold != 0]
        prediction, counts = mod.v15.crossfit_m2(selected, arrays, 0, 10.0)
        self.assertEqual(prediction.shape, (len(selected), 3))
        self.assertTrue(np.all(np.isfinite(prediction)))
        self.assertGreaterEqual(len(counts), 2)
        for parent in {rows[index].parent for index in selected}:
            expected = mod.v15.parent_inner_fold(parent, 0)
            self.assertIn(expected, counts)


class TargetGraphLoadingTests(unittest.TestCase):
    def test_target_graph_loader_accepts_tensor_only_payload_and_rejects_source_key(self) -> None:
        graphs = {"8x6b": target_graph(5), "9e6y": target_graph(6)}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "target.pt"
            torch.save({"target_graphs": graphs}, good)
            loaded = mod.load_target_graphs(good, 26)
            self.assertEqual(set(loaded), set(mod.RECEPTOR_NAMES))
            bad = root / "bad.pt"
            torch.save({"target_graphs": {**graphs, "teacher_source": torch.tensor(1)}}, bad)
            with self.assertRaisesRegex(mod.TrainerV2Error, "receptor_closure|teacher_source"):
                mod.load_target_graphs(bad, 26)

    def test_contact_receipt_binds_the_exact_contact_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contact = root / "contacts.tsv.gz"
            contact.write_bytes(b"frozen-contact-table")
            receipt = root / "RUN_RECEIPT.json"
            receipt.write_text(json.dumps({
                "schema_version": "pvrig_v6_residue_dual_source_contact_targets_v2_receipt",
                "status": "PASS_DUAL_SOURCE_CONTACT_TARGETS_V2",
                "teacher_source_is_model_feature": False,
                "output": {"path": contact.name, "sha256": mod.sha256_file(contact)},
            }))
            loaded = mod.validate_contact_receipt(receipt, contact)
            self.assertEqual(loaded["status"], "PASS_DUAL_SOURCE_CONTACT_TARGETS_V2")
            contact.write_bytes(b"mutated")
            with self.assertRaisesRegex(mod.TrainerV2Error, "output_hash"):
                mod.validate_contact_receipt(receipt, contact)

    def test_target_graph_receipt_binds_public_graph_delivery_and_sealed_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target_graphs_v2.pt"
            target.write_bytes(b"fixed-public-target-graphs")
            receipt = root / "target_graph_cache_receipt_v2.json"
            receipt.write_text(json.dumps({
                "schema_version": "pvrig_v6_residue_v2_fixed_target_graphs",
                "status": "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
                "sealed_boundary": {
                    "teacher_source_is_model_feature": False,
                    "candidate_docking_pose_files_opened": 0,
                },
                "outputs": {target.name: mod.sha256_file(target)},
            }))
            loaded = mod.validate_target_graph_receipt(receipt, target)
            self.assertEqual(loaded["status"], "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED")

    def test_target_graph_receipt_accepts_native_esm2_augmentation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target_graphs_esm2_650m_v2.pt"
            target.write_bytes(b"fixed-public-target-graphs-plus-frozen-esm2")
            receipt = root / "target_graphs_esm2_650m_v2.receipt.json"
            receipt.write_text(json.dumps({
                "schema_version": "pvrig_v6_target_graphs_esm2_650m_v2",
                "status": "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED",
                "sealed_boundary": {
                    "teacher_source_is_model_feature": False,
                    "candidate_docking_pose_files_opened": 0,
                    "base_target_cache_mutated": False,
                },
                "inference": {
                    "network_access": "disabled",
                    "base_feature_dim": 30,
                    "plm_feature_dim": 1280,
                    "augmented_feature_dim": 1310,
                },
                "model_identity": {"model_identity_sha256": "a" * 64},
                "output": {
                    "relative_path": f"by_sha256/{mod.sha256_file(target)}/{target.name}",
                    "sha256": mod.sha256_file(target),
                },
            }))
            loaded = mod.validate_target_graph_receipt(receipt, target)
            self.assertEqual(loaded["status"], "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED")

            payload = json.loads(receipt.read_text())
            payload["inference"]["network_access"] = "enabled"
            receipt.write_text(json.dumps(payload))
            with self.assertRaisesRegex(mod.TrainerV2Error, "augmentation_contract"):
                mod.validate_target_graph_receipt(receipt, target)


if __name__ == "__main__":
    unittest.main()
