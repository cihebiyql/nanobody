#!/usr/bin/env python3
"""Frozen dual-source batching and loss utilities for residue V2.

``teacher_source`` is accepted only as sampler/loss audit metadata.  Callers
must never concatenate it to model features.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from torch import Tensor


V4D = "V4D_OPEN_MULTI_SEED"
V4H = "V4H_STAGE1_SEED917"
SOURCES = (V4D, V4H)
MICROBATCH_QUOTA = {V4D: 2, V4H: 6}


class DomainBalanceError(RuntimeError):
    """Raised when frozen domain balancing cannot be satisfied exactly."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DomainBalanceError(message)


def _hash_order(values: Sequence[int], candidate_ids: Sequence[str], token: str) -> list[int]:
    return sorted(
        values,
        key=lambda index: (
            hashlib.sha256(f"{token}|{candidate_ids[index]}".encode()).hexdigest(),
            candidate_ids[index],
            index,
        ),
    )


def _cycle(values: Sequence[int], count: int) -> list[int]:
    require(bool(values), "cannot_cycle_empty_source")
    return [values[index % len(values)] for index in range(count)]


class DeterministicDomainBatchSampler:
    """Create exact 2 V4D + 6 V4H microbatches.

    The epoch length is the smallest number of complete microbatches that
    covers every candidate from both sources.  The smaller V4D domain is
    therefore deterministically repeated; no row is silently dropped.
    """

    def __init__(
        self,
        teacher_sources: Sequence[str],
        candidate_ids: Sequence[str],
        *,
        seed: int,
        epoch: int = 0,
        expected_source_counts: Mapping[str, int] | None = None,
    ) -> None:
        require(len(teacher_sources) == len(candidate_ids) > 0, "sampler_row_mismatch")
        require(len(set(candidate_ids)) == len(candidate_ids), "sampler_duplicate_candidate_id")
        require(set(teacher_sources) == set(SOURCES), f"sampler_source_closure:{sorted(set(teacher_sources))}")
        counts = Counter(teacher_sources)
        if expected_source_counts is not None:
            require(dict(counts) == {source: int(expected_source_counts[source]) for source in SOURCES}, "sampler_source_count_mismatch")
        for source in SOURCES:
            require(counts[source] >= MICROBATCH_QUOTA[source], f"sampler_source_too_small:{source}")
        self.teacher_sources = list(teacher_sources)
        self.candidate_ids = list(candidate_ids)
        self.seed = int(seed)
        self.epoch = int(epoch)
        self.source_counts = dict(counts)
        self._batches = self._build()

    def _build(self) -> list[list[int]]:
        batches = max(
            math.ceil(self.source_counts[source] / MICROBATCH_QUOTA[source])
            for source in SOURCES
        )
        pools: dict[str, list[int]] = {}
        for source in SOURCES:
            indices = [index for index, value in enumerate(self.teacher_sources) if value == source]
            ordered = _hash_order(indices, self.candidate_ids, f"PVRIG_RESIDUE_V2|seed={self.seed}|epoch={self.epoch}|{source}")
            pools[source] = _cycle(ordered, batches * MICROBATCH_QUOTA[source])
        output: list[list[int]] = []
        for batch_index in range(batches):
            batch: list[int] = []
            for source in SOURCES:
                quota = MICROBATCH_QUOTA[source]
                batch.extend(pools[source][batch_index * quota : (batch_index + 1) * quota])
            batch = _hash_order(
                batch,
                self.candidate_ids,
                f"PVRIG_RESIDUE_V2_BATCH|seed={self.seed}|epoch={self.epoch}|batch={batch_index}",
            )
            observed = Counter(self.teacher_sources[index] for index in batch)
            require(dict(observed) == MICROBATCH_QUOTA, f"microbatch_quota_violation:{batch_index}:{dict(observed)}")
            require(len(batch) == sum(MICROBATCH_QUOTA.values()), f"microbatch_size_violation:{batch_index}")
            require(len(set(batch)) == len(batch), f"microbatch_duplicate_candidate:{batch_index}")
            output.append(batch)
        used = Counter(index for batch in output for index in batch)
        require(set(used) == set(range(len(self.teacher_sources))), "sampler_candidate_coverage_failure")
        return output

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)
        self._batches = self._build()

    def __iter__(self) -> Iterator[list[int]]:
        return iter([list(batch) for batch in self._batches])

    def __len__(self) -> int:
        return len(self._batches)

    def audit_manifest(self) -> dict[str, Any]:
        draws = Counter(index for batch in self._batches for index in batch)
        per_source_draws = {
            source: sum(count for index, count in draws.items() if self.teacher_sources[index] == source)
            for source in SOURCES
        }
        return {
            "schema_version": "pvrig_residue_v2_domain_batch_manifest",
            "seed": self.seed,
            "epoch": self.epoch,
            "microbatch_quota": dict(MICROBATCH_QUOTA),
            "batch_count": len(self),
            "candidate_counts": dict(self.source_counts),
            "draw_counts": per_source_draws,
            "candidate_draws": [
                {
                    "candidate_id": self.candidate_ids[index],
                    "teacher_source": self.teacher_sources[index],
                    "draw_count": draws[index],
                }
                for index in sorted(draws, key=lambda value: self.candidate_ids[value])
            ],
        }


def assert_teacher_source_not_model_feature(feature_names: Sequence[str]) -> None:
    lowered = {str(name).strip().lower() for name in feature_names}
    forbidden = {"teacher_source", "teacher_source_id", "source_id", "campaign_id"}
    observed = sorted(lowered & forbidden)
    require(not observed, f"teacher_source_model_feature_forbidden:{observed}")


def source_balanced_component(
    per_candidate_loss: Tensor,
    teacher_sources: Sequence[str],
    *,
    sample_weights: Tensor | None = None,
    available_mask: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    """Normalize one loss component within source, then return 0.5/0.5.

    ``per_candidate_loss`` must already be reduced over tokens/pairs.  This
    prevents long proteins or dense contact tables from changing source weight.
    """

    require(per_candidate_loss.ndim == 1, "component_loss_must_be_per_candidate")
    require(len(per_candidate_loss) == len(teacher_sources), "component_source_row_mismatch")
    device = per_candidate_loss.device
    dtype = per_candidate_loss.dtype
    if sample_weights is None:
        sample_weights = torch.ones(len(per_candidate_loss), device=device, dtype=dtype)
    require(sample_weights.shape == per_candidate_loss.shape, "component_weight_shape")
    require(bool(torch.all(torch.isfinite(sample_weights))) and bool(torch.all(sample_weights > 0)), "component_weight_invalid")
    if available_mask is None:
        available_mask = torch.ones(len(per_candidate_loss), device=device, dtype=torch.bool)
    require(available_mask.shape == per_candidate_loss.shape, "component_mask_shape")
    require(bool(torch.all(torch.isfinite(per_candidate_loss))), "component_loss_nonfinite")
    means: dict[str, Tensor] = {}
    for source in SOURCES:
        source_mask = torch.tensor([value == source for value in teacher_sources], device=device, dtype=torch.bool)
        selected = source_mask & available_mask.to(device=device, dtype=torch.bool)
        require(bool(torch.any(selected)), f"component_source_unavailable:{source}")
        weights = sample_weights[selected]
        means[source] = (per_candidate_loss[selected] * weights).sum() / weights.sum().clamp_min(torch.finfo(dtype).eps)
    return 0.5 * means[V4D] + 0.5 * means[V4H], means


def contact_uncertainty_weight(variance: np.ndarray | Tensor) -> np.ndarray | Tensor:
    """Frozen V2 weight ``1/(1+4*population_variance)``."""

    if isinstance(variance, Tensor):
        require(bool(torch.all(torch.isfinite(variance))), "contact_variance_nonfinite")
        require(bool(torch.all((variance >= -1e-8) & (variance <= 0.25 + 1e-8))), "contact_variance_range")
        return 1.0 / (1.0 + 4.0 * variance.clamp(0.0, 0.25))
    values = np.asarray(variance, dtype=np.float64)
    require(bool(np.all(np.isfinite(values))), "contact_variance_nonfinite")
    require(bool(np.all((values >= -1e-8) & (values <= 0.25 + 1e-8))), "contact_variance_range")
    return 1.0 / (1.0 + 4.0 * np.clip(values, 0.0, 0.25))


@dataclass(frozen=True)
class SeedContactAggregate:
    mean: np.ndarray
    population_variance: np.ndarray
    uncertainty_weight: np.ndarray
    observed_seeds: tuple[int, ...]
    missing_seeds: tuple[int, ...]


def aggregate_observed_seed_contacts(
    contacts_by_seed: Mapping[int, np.ndarray],
    *,
    expected_seeds: Sequence[int] = (917, 1931, 3253),
    minimum_observed_seeds: int = 2,
) -> SeedContactAggregate:
    expected = tuple(int(value) for value in expected_seeds)
    observed = tuple(sorted(int(value) for value in contacts_by_seed))
    require(len(observed) >= minimum_observed_seeds, f"contact_observed_seed_count:{len(observed)}")
    require(set(observed) <= set(expected), f"contact_unexpected_seed:{observed}")
    arrays = [np.asarray(contacts_by_seed[seed], dtype=np.float64) for seed in observed]
    require(bool(arrays) and all(array.shape == arrays[0].shape for array in arrays), "contact_seed_shape_mismatch")
    stacked = np.stack(arrays)
    require(bool(np.all(np.isfinite(stacked))), "contact_seed_nonfinite")
    require(bool(np.all((stacked >= 0.0) & (stacked <= 1.0))), "contact_seed_value_range")
    mean = stacked.mean(axis=0)
    variance = stacked.var(axis=0, ddof=0)
    return SeedContactAggregate(
        mean=mean,
        population_variance=variance,
        uncertainty_weight=np.asarray(contact_uncertainty_weight(variance)),
        observed_seeds=observed,
        missing_seeds=tuple(seed for seed in expected if seed not in observed),
    )

