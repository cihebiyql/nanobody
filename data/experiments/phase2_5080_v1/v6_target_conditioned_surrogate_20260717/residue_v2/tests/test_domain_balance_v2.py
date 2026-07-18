#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import torch


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from domain_balance_v2 import (  # noqa: E402
    MICROBATCH_QUOTA,
    V4D,
    V4H,
    DeterministicDomainBatchSampler,
    DomainBalanceError,
    aggregate_observed_seed_contacts,
    assert_teacher_source_not_model_feature,
    contact_uncertainty_weight,
    source_balanced_component,
)


class DomainBatchSamplerTests(unittest.TestCase):
    @staticmethod
    def panel(v4d: int, v4h: int) -> tuple[list[str], list[str]]:
        sources = [V4D] * v4d + [V4H] * v4h
        candidates = [f"D_{index:04d}" for index in range(v4d)] + [
            f"H_{index:04d}" for index in range(v4h)
        ]
        return sources, candidates

    def test_exact_quota_determinism_and_complete_coverage(self) -> None:
        sources, candidates = self.panel(10, 60)
        first = DeterministicDomainBatchSampler(sources, candidates, seed=917)
        second = DeterministicDomainBatchSampler(sources, candidates, seed=917)
        self.assertEqual(list(first), list(second))
        self.assertEqual(len(first), 10)

        observed_indices: list[int] = []
        for batch in first:
            self.assertEqual(len(batch), 8)
            self.assertEqual(len(set(batch)), 8)
            counts = Counter(sources[index] for index in batch)
            self.assertEqual(dict(counts), MICROBATCH_QUOTA)
            observed_indices.extend(batch)
        self.assertEqual(set(observed_indices), set(range(70)))

        audit = first.audit_manifest()
        self.assertEqual(audit["draw_counts"], {V4D: 20, V4H: 60})
        d_draws = [row["draw_count"] for row in audit["candidate_draws"] if row["teacher_source"] == V4D]
        h_draws = [row["draw_count"] for row in audit["candidate_draws"] if row["teacher_source"] == V4H]
        self.assertEqual(set(d_draws), {2})
        self.assertEqual(set(h_draws), {1})

    def test_epoch_is_deterministic_but_changes_order(self) -> None:
        sources, candidates = self.panel(12, 36)
        sampler = DeterministicDomainBatchSampler(sources, candidates, seed=1931)
        epoch_zero = list(sampler)
        sampler.set_epoch(1)
        epoch_one = list(sampler)
        self.assertNotEqual(epoch_zero, epoch_one)
        sampler.set_epoch(1)
        self.assertEqual(epoch_one, list(sampler))

    def test_fail_closed_for_source_and_identity_contracts(self) -> None:
        with self.assertRaisesRegex(DomainBalanceError, "sampler_source_closure"):
            DeterministicDomainBatchSampler([V4D] * 2 + ["OTHER"] * 6, [str(i) for i in range(8)], seed=1)
        with self.assertRaisesRegex(DomainBalanceError, "sampler_duplicate_candidate_id"):
            DeterministicDomainBatchSampler([V4D] * 2 + [V4H] * 6, ["same"] * 8, seed=1)
        sources, candidates = self.panel(2, 6)
        with self.assertRaisesRegex(DomainBalanceError, "sampler_source_count_mismatch"):
            DeterministicDomainBatchSampler(
                sources,
                candidates,
                seed=1,
                expected_source_counts={V4D: 3, V4H: 5},
            )


class SourceBalancedLossTests(unittest.TestCase):
    def test_each_component_is_normalized_within_source_then_half_half(self) -> None:
        losses = torch.tensor([1.0, 3.0] + [10.0] * 6, requires_grad=True)
        combined, means = source_balanced_component(losses, [V4D] * 2 + [V4H] * 6)
        self.assertAlmostEqual(float(means[V4D].detach()), 2.0)
        self.assertAlmostEqual(float(means[V4H].detach()), 10.0)
        self.assertAlmostEqual(float(combined.detach()), 6.0)
        combined.backward()
        np.testing.assert_allclose(losses.grad[:2].numpy(), np.full(2, 0.25))
        np.testing.assert_allclose(losses.grad[2:].numpy(), np.full(6, 1.0 / 12.0))

    def test_weights_are_source_local_and_missing_source_fails(self) -> None:
        losses = torch.tensor([0.0, 4.0] + [2.0] * 6)
        weights = torch.tensor([3.0, 1.0] + [1.0] * 6)
        combined, means = source_balanced_component(
            losses,
            [V4D] * 2 + [V4H] * 6,
            sample_weights=weights,
        )
        self.assertAlmostEqual(float(means[V4D]), 1.0)
        self.assertAlmostEqual(float(means[V4H]), 2.0)
        self.assertAlmostEqual(float(combined), 1.5)
        with self.assertRaisesRegex(DomainBalanceError, "component_source_unavailable"):
            source_balanced_component(
                losses,
                [V4D] * 2 + [V4H] * 6,
                available_mask=torch.tensor([True, True] + [False] * 6),
            )

    def test_teacher_source_cannot_become_model_feature(self) -> None:
        assert_teacher_source_not_model_feature(["esm2", "cdr_mask", "m2_prediction"])
        for forbidden in ("teacher_source", "source_id", "campaign_id"):
            with self.assertRaisesRegex(DomainBalanceError, "teacher_source_model_feature_forbidden"):
                assert_teacher_source_not_model_feature(["esm2", forbidden])


class ContactUncertaintyTests(unittest.TestCase):
    def test_frozen_uncertainty_formula_numpy_and_torch(self) -> None:
        variance = np.asarray([0.0, 0.125, 0.25])
        np.testing.assert_allclose(contact_uncertainty_weight(variance), [1.0, 2.0 / 3.0, 0.5])
        tensor = torch.tensor([0.0, 0.125, 0.25])
        torch.testing.assert_close(contact_uncertainty_weight(tensor), torch.tensor([1.0, 2.0 / 3.0, 0.5]))

    def test_seed_aggregation_preserves_partial_seed_audit(self) -> None:
        aggregate = aggregate_observed_seed_contacts(
            {
                917: np.asarray([[0.0, 1.0], [0.5, 0.5]]),
                3253: np.asarray([[1.0, 0.0], [0.5, 1.0]]),
            }
        )
        np.testing.assert_allclose(aggregate.mean, [[0.5, 0.5], [0.5, 0.75]])
        np.testing.assert_allclose(aggregate.population_variance, [[0.25, 0.25], [0.0, 0.0625]])
        np.testing.assert_allclose(aggregate.uncertainty_weight, [[0.5, 0.5], [1.0, 0.8]])
        self.assertEqual(aggregate.observed_seeds, (917, 3253))
        self.assertEqual(aggregate.missing_seeds, (1931,))

    def test_contact_aggregation_fails_below_two_observed_seeds(self) -> None:
        with self.assertRaisesRegex(DomainBalanceError, "contact_observed_seed_count:1"):
            aggregate_observed_seed_contacts({917: np.zeros((2, 2))})
        with self.assertRaisesRegex(DomainBalanceError, "contact_seed_shape_mismatch"):
            aggregate_observed_seed_contacts({917: np.zeros((2, 2)), 1931: np.zeros((3, 2))})


if __name__ == "__main__":
    unittest.main()
