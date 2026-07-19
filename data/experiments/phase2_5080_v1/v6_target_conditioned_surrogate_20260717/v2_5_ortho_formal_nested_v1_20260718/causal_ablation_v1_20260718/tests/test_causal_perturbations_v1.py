#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_perturbations_v1 import (  # noqa: E402
    CausalPerturbationError,
    apply_contact_donor_map,
    exact_min_predictions,
    omit_contact_meta_evidence,
    permute_target_residue_features,
    swap_hotspot_interface_masks,
    swap_receptor_conformer_payloads,
    within_parent_donor_map,
)


def graph(offset: float, nodes: int = 5) -> dict[str, torch.Tensor]:
    return {
        "node_features": torch.arange(nodes * 3, dtype=torch.float32).reshape(nodes, 3) + offset,
        "edge_index": torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long),
        "edge_features": torch.ones(4, 2) * offset,
        "hotspot_mask": torch.tensor([True, False, True, False, False]),
        "interface_mask": torch.tensor([True, True, True, True, False]),
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

    def test_no_contact_omission_and_exact_min(self) -> None:
        row = {"M2_R8": 0.1, "contact_score_R8": 0.2, "contact_score_R9": 0.3, "E_SHARED_R9": 0.4}
        omitted = omit_contact_meta_evidence(row)
        self.assertEqual(set(omitted), {"M2_R8", "E_SHARED_R9"})
        self.assertEqual(exact_min_predictions([0.4, 0.2], [0.3, 0.5]), [0.3, 0.2])


if __name__ == "__main__":
    unittest.main()
