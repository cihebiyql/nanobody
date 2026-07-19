#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_perturbations_v1_1 import (  # noqa: E402
    CausalPerturbationError,
    apply_contact_donor_map,
    audit_contact_donor_power,
    build_matched_prevalence_mask_null_bank,
    contact_payload_distance,
    exact_min_predictions,
    matched_prevalence_mask_position_null,
    omit_contact_meta_evidence,
    permute_target_residue_features,
    swap_hotspot_interface_masks,
    swap_receptor_conformer_payloads,
    within_parent_donor_map,
)


def graph(offset: float, nodes: int = 5) -> dict[str, torch.Tensor]:
    hotspot = torch.tensor([(index % 4) == 0 for index in range(nodes)], dtype=torch.bool)
    interface = torch.tensor([(index % 3) != 2 for index in range(nodes)], dtype=torch.bool)
    return {
        "node_features": torch.arange(nodes * 3, dtype=torch.float32).reshape(nodes, 3) + offset,
        "edge_index": torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long),
        "edge_features": torch.ones(4, 2) * offset,
        "hotspot_mask": hotspot,
        "interface_mask": interface,
    }


class PerturbationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graphs = {"8x6b": graph(0.0), "9e6y": graph(100.0)}

    def test_mask_swap_only_changes_masks_and_does_not_mutate_input(self) -> None:
        original_nodes = self.graphs["8x6b"]["node_features"].clone()
        original_hotspot = self.graphs["8x6b"]["hotspot_mask"].clone()
        swapped = swap_hotspot_interface_masks(self.graphs)
        self.assertTrue(torch.equal(swapped["8x6b"]["hotspot_mask"], self.graphs["8x6b"]["interface_mask"]))
        self.assertTrue(torch.equal(swapped["8x6b"]["interface_mask"], original_hotspot))
        self.assertTrue(torch.equal(swapped["8x6b"]["node_features"], original_nodes))
        self.assertTrue(torch.equal(self.graphs["8x6b"]["hotspot_mask"], original_hotspot))

    def test_matched_mask_position_null_preserves_prevalence_overlap_and_payload(self) -> None:
        first, first_audit = matched_prevalence_mask_position_null(
            self.graphs, replicate=7, master_seed=1931
        )
        second, second_audit = matched_prevalence_mask_position_null(
            self.graphs, replicate=7, master_seed=1931
        )
        self.assertEqual(first_audit, second_audit)
        for receptor in ("8x6b", "9e6y"):
            original = self.graphs[receptor]
            null = first[receptor]
            self.assertEqual(int(original["hotspot_mask"].sum()), int(null["hotspot_mask"].sum()))
            self.assertEqual(int(original["interface_mask"].sum()), int(null["interface_mask"].sum()))
            self.assertEqual(
                int((original["hotspot_mask"] & original["interface_mask"]).sum()),
                int((null["hotspot_mask"] & null["interface_mask"]).sum()),
            )
            self.assertTrue(torch.equal(original["node_features"], null["node_features"]))
            self.assertTrue(torch.equal(original["edge_index"], null["edge_index"]))
            self.assertTrue(
                not torch.equal(original["hotspot_mask"], null["hotspot_mask"])
                or not torch.equal(original["interface_mask"], null["interface_mask"])
            )

    def test_mask_null_bank_is_frozen_256_replicates_and_deterministic(self) -> None:
        graphs = {"8x6b": graph(0.0, nodes=16), "9e6y": graph(100.0, nodes=16)}
        first, first_audits = build_matched_prevalence_mask_null_bank(graphs)
        second, second_audits = build_matched_prevalence_mask_null_bank(graphs)
        self.assertEqual(len(first), 256)
        self.assertEqual(first_audits, second_audits)
        self.assertTrue(torch.equal(first[0]["8x6b"]["hotspot_mask"], second[0]["8x6b"]["hotspot_mask"]))
        with self.assertRaisesRegex(CausalPerturbationError, "replicate_count_frozen"):
            build_matched_prevalence_mask_null_bank(graphs, replicates=32)

    def test_mask_null_fails_when_spatial_relocation_is_impossible(self) -> None:
        graphs = {"8x6b": graph(0.0), "9e6y": graph(100.0)}
        graphs["8x6b"]["hotspot_mask"] = torch.ones(5, dtype=torch.bool)
        graphs["8x6b"]["interface_mask"] = torch.ones(5, dtype=torch.bool)
        with self.assertRaisesRegex(CausalPerturbationError, "relocation_impossible"):
            matched_prevalence_mask_position_null(graphs, replicate=0)

    def test_conformer_swap_retains_keys_but_swaps_full_payload(self) -> None:
        swapped = swap_receptor_conformer_payloads(self.graphs)
        self.assertEqual(set(swapped), {"8x6b", "9e6y"})
        self.assertTrue(torch.equal(swapped["8x6b"]["node_features"], self.graphs["9e6y"]["node_features"]))
        self.assertTrue(torch.equal(swapped["9e6y"]["edge_features"], self.graphs["8x6b"]["edge_features"]))
        swapped["8x6b"]["node_features"][0, 0] = -999
        self.assertNotEqual(float(self.graphs["9e6y"]["node_features"][0, 0]), -999.0)

    def test_target_residue_permutation_is_deterministic_and_position_breaking(self) -> None:
        first, first_audit = permute_target_residue_features(self.graphs, seed=1931)
        second, second_audit = permute_target_residue_features(self.graphs, seed=1931)
        self.assertEqual(first_audit, second_audit)
        for receptor in ("8x6b", "9e6y"):
            self.assertNotEqual(first_audit[receptor], list(range(5)))
            self.assertTrue(torch.equal(first[receptor]["node_features"], second[receptor]["node_features"]))
            self.assertTrue(torch.equal(first[receptor]["edge_index"], self.graphs[receptor]["edge_index"]))
            self.assertTrue(torch.equal(first[receptor]["hotspot_mask"], self.graphs[receptor]["hotspot_mask"]))
            expected_rows = {tuple(row.tolist()) for row in self.graphs[receptor]["node_features"]}
            observed_rows = {tuple(row.tolist()) for row in first[receptor]["node_features"]}
            self.assertEqual(expected_rows, observed_rows)

    def test_donor_map_is_same_parent_deterministic_derangement(self) -> None:
        rows = [
            {"candidate_id": f"a{i}", "parent_framework_cluster": "A"} for i in range(4)
        ] + [
            {"candidate_id": f"b{i}", "parent_framework_cluster": "B"} for i in range(3)
        ]
        first = within_parent_donor_map(rows, partition_id="outer_0_inner_1_train", seed=1931)
        second = within_parent_donor_map(rows, partition_id="outer_0_inner_1_train", seed=1931)
        self.assertEqual(first, second)
        parent = {row["candidate_id"]: row["parent_framework_cluster"] for row in rows}
        self.assertEqual(set(first), set(parent))
        for recipient, donor in first.items():
            self.assertNotEqual(recipient, donor)
            self.assertEqual(parent[recipient], parent[donor])

    def test_donor_singleton_and_sealed_partition_fail_closed(self) -> None:
        rows = [{"candidate_id": "a0", "parent_framework_cluster": "A"}]
        with self.assertRaisesRegex(CausalPerturbationError, "parent_singleton"):
            within_parent_donor_map(rows, partition_id="outer_0_train")
        two = rows + [{"candidate_id": "a1", "parent_framework_cluster": "A"}]
        with self.assertRaisesRegex(CausalPerturbationError, "sealed_token"):
            within_parent_donor_map(two, partition_id="v4_f_test32")

    def test_apply_donor_moves_only_explicit_contact_payload(self) -> None:
        rows = [
            {"candidate_id": "a0", "parent_framework_cluster": "A", "sequence": "AAAA", "truth_R8": 0.1,
             "marginal": torch.tensor([1.0]), "pair_mask": torch.tensor([True]), "tier": "A"},
            {"candidate_id": "a1", "parent_framework_cluster": "A", "sequence": "BBBB", "truth_R8": 0.9,
             "marginal": torch.tensor([0.0]), "pair_mask": torch.tensor([False]), "tier": "C"},
        ]
        donor_map = within_parent_donor_map(rows, partition_id="outer_0_train")
        output = apply_contact_donor_map(
            rows, donor_map, contact_payload_fields=("marginal", "pair_mask", "tier")
        )
        by_id = {row["candidate_id"]: row for row in output}
        self.assertEqual(by_id["a0"]["sequence"], "AAAA")
        self.assertEqual(by_id["a0"]["truth_R8"], 0.1)
        self.assertEqual(by_id["a0"]["tier"], "C")
        self.assertEqual(float(by_id["a0"]["marginal"][0]), 0.0)

    def test_apply_donor_rejects_cross_parent_and_scalar_payload(self) -> None:
        rows = [
            {"candidate_id": "a0", "parent_framework_cluster": "A", "truth_R8": 0.1, "marginal": 1.0},
            {"candidate_id": "b0", "parent_framework_cluster": "B", "truth_R8": 0.9, "marginal": 0.0},
        ]
        with self.assertRaisesRegex(CausalPerturbationError, "donor_apply_cross_parent"):
            apply_contact_donor_map(rows, {"a0": "b0", "b0": "a0"}, contact_payload_fields=("marginal",))
        same_parent = [dict(row, parent_framework_cluster="A") for row in rows]
        with self.assertRaisesRegex(CausalPerturbationError, "forbidden_contact_payload_field"):
            apply_contact_donor_map(
                same_parent, {"a0": "b0", "b0": "a0"}, contact_payload_fields=("truth_R8",)
            )

    @staticmethod
    def power_rows(identical: bool = False) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for parent in ("A", "B"):
            for index in range(4):
                value = 0.0 if identical else index / 3.0
                rows.append({
                    "candidate_id": f"{parent}{index}",
                    "parent_framework_cluster": parent,
                    "marginal_targets": torch.tensor([value, 1.0 - value]),
                    "marginal_mask": torch.tensor([True, index % 2 == 0]),
                    "pair_targets": torch.tensor([[value, 1.0 - value], [1.0 - value, value]]),
                    "pair_mask": torch.tensor([[True, True], [index % 2 == 0, True]]),
                    "uncertainty": torch.tensor([0.1 + value]),
                    "tier": "A" if index < 2 else "B",
                })
        return rows

    def test_contact_payload_distance_and_donor_power_audit_pass(self) -> None:
        rows = self.power_rows()
        donor_map = within_parent_donor_map(rows, partition_id="outer_0_inner_1_train", seed=1931)
        fields = (
            "marginal_targets", "marginal_mask", "pair_targets", "pair_mask", "uncertainty", "tier"
        )
        supervision = ("marginal_targets", "marginal_mask", "pair_targets", "pair_mask")
        distance, per_field = contact_payload_distance(rows[0], rows[1], fields=fields)
        self.assertGreater(distance, 0.0)
        self.assertEqual(set(per_field), set(fields))
        audit = audit_contact_donor_power(
            rows,
            donor_map,
            partition_id="outer_0_inner_1_train",
            contact_payload_fields=fields,
            supervision_fields=supervision,
        )
        self.assertEqual(audit["status"], "PASS_EFFECTIVE_CONTACT_DONOR_NULL")
        self.assertEqual(audit["candidate_count"], 8)
        self.assertEqual(audit["parent_count"], 2)
        self.assertFalse(audit["uses_scalar_truth"])
        self.assertGreaterEqual(audit["supervision_changed_fraction"], 0.8)
        self.assertGreaterEqual(audit["supervision_mapped_to_eligible_median_ratio"], 0.5)

    def test_donor_power_audit_fails_closed_for_identical_supervision(self) -> None:
        rows = self.power_rows(identical=True)
        for row in rows:
            row["marginal_mask"] = torch.ones(2, dtype=torch.bool)
            row["pair_mask"] = torch.ones((2, 2), dtype=torch.bool)
            row["uncertainty"] = torch.tensor([0.1])
            row["tier"] = "A"
        donor_map = within_parent_donor_map(rows, partition_id="outer_0_train", seed=1931)
        with self.assertRaisesRegex(CausalPerturbationError, "donor_null_ineffective"):
            audit_contact_donor_power(
                rows,
                donor_map,
                partition_id="outer_0_train",
                contact_payload_fields=("marginal_targets", "marginal_mask", "pair_targets", "pair_mask"),
                supervision_fields=("marginal_targets", "marginal_mask", "pair_targets", "pair_mask"),
            )

    def test_donor_power_audit_fails_closed_for_shape_or_nonfinite_payload(self) -> None:
        rows = self.power_rows()
        donor_map = within_parent_donor_map(rows, partition_id="outer_0_train", seed=1931)
        rows[1]["pair_targets"] = torch.ones((3, 2))
        with self.assertRaisesRegex(CausalPerturbationError, "payload_shape_mismatch"):
            audit_contact_donor_power(
                rows,
                donor_map,
                partition_id="outer_0_train",
                contact_payload_fields=("pair_targets",),
                supervision_fields=("pair_targets",),
            )
        rows = self.power_rows()
        donor_map = within_parent_donor_map(rows, partition_id="outer_0_train", seed=1931)
        rows[1]["pair_targets"] = torch.tensor([[float("nan"), 0.0], [0.0, 0.0]])
        with self.assertRaisesRegex(CausalPerturbationError, "payload_nonfinite"):
            audit_contact_donor_power(
                rows,
                donor_map,
                partition_id="outer_0_train",
                contact_payload_fields=("pair_targets",),
                supervision_fields=("pair_targets",),
            )

    def test_no_contact_omission_and_exact_min(self) -> None:
        row = {"M2_R8": 0.1, "contact_score_R8": 0.2, "contact_score_R9": 0.3, "E_SHARED_R9": 0.4}
        omitted = omit_contact_meta_evidence(row)
        self.assertEqual(set(omitted), {"M2_R8", "E_SHARED_R9"})
        self.assertEqual(exact_min_predictions([0.4, 0.2], [0.3, 0.5]), [0.3, 0.2])


if __name__ == "__main__":
    unittest.main()
