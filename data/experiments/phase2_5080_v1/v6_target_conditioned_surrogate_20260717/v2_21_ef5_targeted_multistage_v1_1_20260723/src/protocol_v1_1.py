#!/usr/bin/env python3
"""Pure, label-firewalled protocol helpers for V2.21 master-method v1.1.

This module does not train or read project data.  It makes the selection,
metric, root-cause and state-transition contracts executable before the
V2.20 scientific terminal exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import re
import statistics
from typing import Iterable, Mapping, Sequence, TypeVar


ROWS = 9849
POSITIVES = 985
BUDGET = 493
TARGET_HITS = 247


class ProtocolError(RuntimeError):
    """Fail-closed protocol violation."""


Payload = TypeVar("Payload")


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ProtocolError(f"invalid_number:{field}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"invalid_number:{field}") from exc
    if not math.isfinite(result):
        raise ProtocolError(f"non_finite:{field}")
    return result


def _strict_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProtocolError(f"invalid_boolean:{field}")
    return value


def _strict_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise ProtocolError(f"invalid_integer:{field}")
    return value


def _validate_sequence_sha256(values: Sequence[str]) -> None:
    if not values:
        raise ProtocolError("empty_sequence_sha256")
    for value in values:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ProtocolError("invalid_sequence_sha256")


def _validated_indices(
    values: Sequence[int], field: str, *, upper_bound: int | None = None
) -> tuple[int, ...]:
    output = tuple(values)
    if not output:
        raise ProtocolError(f"empty_indices:{field}")
    if any(type(value) is not int for value in output):
        raise ProtocolError(f"invalid_index:{field}")
    if len(output) != len(set(output)):
        raise ProtocolError(f"duplicate_index:{field}")
    if any(value < 0 or (upper_bound is not None and value >= upper_bound) for value in output):
        raise ProtocolError(f"index_out_of_range:{field}")
    return output


def ranked_indices(
    scores: Sequence[float], sequence_sha256: Sequence[str]
) -> list[int]:
    """Descending score with the frozen ascending SHA256 tie break."""
    if len(scores) != len(sequence_sha256) or not scores:
        raise ProtocolError("ranking_length_mismatch_or_empty")
    _validate_sequence_sha256(sequence_sha256)
    if len(set(sequence_sha256)) != len(sequence_sha256):
        raise ProtocolError("duplicate_sequence_sha256")
    clean = [_finite(value, "score") for value in scores]
    return sorted(range(len(clean)), key=lambda i: (-clean[i], sequence_sha256[i]))


def exact_ef5(
    truth: Sequence[float], scores: Sequence[float], sequence_sha256: Sequence[str]
) -> dict[str, float | int]:
    """Frozen train9849 Top10 truth / Top5 budget metric."""
    if len(truth) != ROWS or len(scores) != ROWS or len(sequence_sha256) != ROWS:
        raise ProtocolError("metric_requires_exact_9849_rows")
    truth_rank = ranked_indices(truth, sequence_sha256)
    pred_rank = ranked_indices(scores, sequence_sha256)
    positives = set(truth_rank[:POSITIVES])
    selected = pred_rank[:BUDGET]
    hits = sum(index in positives for index in selected)
    precision = hits / BUDGET
    recall = hits / POSITIVES
    prevalence = POSITIVES / ROWS
    return {
        "rows": ROWS,
        "positives": POSITIVES,
        "selected": BUDGET,
        "hits": hits,
        "precision": precision,
        "recall": recall,
        "ef5": precision / prevalence,
    }


def fit_cdf(fit_values: Sequence[float], query_values: Sequence[float]) -> list[float]:
    """Empirical CDF learned only from fit rows; no query self-ranking."""
    if not fit_values:
        raise ProtocolError("empty_fit_cdf")
    fit = sorted(_finite(value, "fit_cdf") for value in fit_values)
    output: list[float] = []
    for raw in query_values:
        value = _finite(raw, "query_cdf")
        lo, hi = 0, len(fit)
        while lo < hi:
            mid = (lo + hi) // 2
            if fit[mid] <= value:
                lo = mid + 1
            else:
                hi = mid
        output.append(lo / len(fit))
    return output


def union_pool(
    model_scores: Mapping[str, Sequence[float]],
    sequence_sha256: Sequence[str],
    *,
    per_model_fraction: float = 0.05,
) -> list[int]:
    """Frozen L1/B/M2/C2 union, independent of truth labels."""
    required = ("L1", "B", "M2", "C2")
    if tuple(model_scores) != required:
        raise ProtocolError("union_model_order_or_set_mismatch")
    n = len(sequence_sha256)
    if n < 1 or per_model_fraction != 0.05:
        raise ProtocolError("union_requires_frozen_top5_fraction")
    k = math.ceil(n * per_model_fraction)
    selected: set[int] = set()
    for name in required:
        values = model_scores[name]
        if len(values) != n:
            raise ProtocolError(f"union_length_mismatch:{name}")
        selected.update(ranked_indices(values, sequence_sha256)[:k])
    return sorted(selected, key=lambda i: sequence_sha256[i])


REQUIRED_TERMINAL_FIELDS = {
    "scientific_status",
    "technical_closure",
    "all_fold_selected_at_grid_max",
    "max_achieved_shared_gradient_ratio",
    "contact_evaluator_available",
    "contact_vs_position_macro_auprc_ci_lower",
    "target_permutation_relative_contact_drop",
    "shuffle_relative_contact_drop",
    "c1_vs_c0_hits_gain",
    "c1_vs_c0_incremental_gate_pass",
    "fold_stability_pass",
    "source_reliability_stability_pass",
    "minimum_source_stratum_delta_ef5",
    "maximum_source_stratum_delta_ef5",
    "rdual_spearman_delta",
    "rdual_relative_mae_improvement",
}


def dispatch_terminal(terminal: Mapping[str, object]) -> str:
    """Return exactly one activation state; missing evidence fails closed."""
    missing = sorted(REQUIRED_TERMINAL_FIELDS - set(terminal))
    if missing:
        return "STOP_MISSING_TERMINAL_EVIDENCE:" + ",".join(missing)
    for field in (
        "all_fold_selected_at_grid_max",
        "contact_evaluator_available",
        "c1_vs_c0_incremental_gate_pass",
        "fold_stability_pass",
        "source_reliability_stability_pass",
    ):
        _strict_bool(terminal[field], field)
    numeric = {
        field: _finite(terminal[field], field)
        for field in (
            "max_achieved_shared_gradient_ratio",
            "contact_vs_position_macro_auprc_ci_lower",
            "target_permutation_relative_contact_drop",
            "shuffle_relative_contact_drop",
            "minimum_source_stratum_delta_ef5",
            "maximum_source_stratum_delta_ef5",
            "rdual_spearman_delta",
            "rdual_relative_mae_improvement",
        )
    }
    hits_gain = _strict_int(terminal["c1_vs_c0_hits_gain"], "c1_vs_c0_hits_gain")
    if terminal["technical_closure"] != "PASS":
        return "STOP_INVALID_V220_TECHNICAL_CLOSURE"
    status = terminal["scientific_status"]
    if status == "PASS":
        return "PASS_BRANCH_P1_CONTACT_CAUSAL"
    if status != "FAIL":
        return "STOP_INVALID_V220_SCIENTIFIC_STATUS"

    ratio = numeric["max_achieved_shared_gradient_ratio"]
    if terminal["all_fold_selected_at_grid_max"] is True and ratio < 0.005:
        return "F1_UNDERPOWERED_CONTACT_LOSS"

    if terminal["contact_evaluator_available"] is not True:
        return "STOP_MISSING_CONTACT_EVALUATOR_EVIDENCE"
    contact_ci = numeric["contact_vs_position_macro_auprc_ci_lower"]
    target_drop = numeric["target_permutation_relative_contact_drop"]
    shuffle_drop = numeric["shuffle_relative_contact_drop"]
    causal_contact = contact_ci > 0.0 and target_drop >= 0.10 and shuffle_drop >= 0.10
    spearman_delta = numeric["rdual_spearman_delta"]
    mae_gain = numeric["rdual_relative_mae_improvement"]
    scalar_improves = spearman_delta >= 0.02 or mae_gain >= 0.05
    if (
        causal_contact
        and not scalar_improves
        and terminal["c1_vs_c0_incremental_gate_pass"] is not True
    ):
        return "F2_CONTACT_LEARNABLE_SCALAR_PATH_INEFFECTIVE"
    if not causal_contact:
        return "F3_CONTACT_NOT_LEARNABLE_OR_TARGET_BLIND"

    stratum_min = numeric["minimum_source_stratum_delta_ef5"]
    stratum_max = numeric["maximum_source_stratum_delta_ef5"]
    unstable = (
        terminal["fold_stability_pass"] is not True
        or terminal["source_reliability_stability_pass"] is not True
        or stratum_min < -0.25
        or stratum_max - stratum_min > 0.75
    )
    if hits_gain > 0 and unstable:
        return "F4_FOLD_SOURCE_RELIABILITY_INSTABILITY"

    if scalar_improves and (
        terminal["c1_vs_c0_incremental_gate_pass"] is not True
    ):
        return "F5_SCALAR_IMPROVES_TOP5_DOES_NOT"
    return "STOP_NO_PREREGISTERED_ROOT_CAUSE"


@dataclass(frozen=True)
class StageEvidence:
    p1_contact_causal_pass: bool
    p2_multiseed_pass: bool
    p3_complete: bool
    all_outer_fit_union_oracle_ef5: Sequence[float]

    def __post_init__(self) -> None:
        for field in ("p1_contact_causal_pass", "p2_multiseed_pass", "p3_complete"):
            _strict_bool(getattr(self, field), field)
        values = tuple(
            _finite(value, "fit_only_union_oracle")
            for value in self.all_outer_fit_union_oracle_ef5
        )
        object.__setattr__(self, "all_outer_fit_union_oracle_ef5", values)


def next_stage(current: str, evidence: StageEvidence) -> str:
    """Frozen single-transition PASS-path DAG."""
    if current == "P1_CONTACT_CAUSAL":
        return "P2_MULTISEED" if evidence.p1_contact_causal_pass else "P3_BASE_ONLY"
    if current == "P2_MULTISEED":
        return "P3_WITH_MULTISEED" if evidence.p2_multiseed_pass else "P3_WITHOUT_MULTISEED"
    if current in {"P3_BASE_ONLY", "P3_WITH_MULTISEED", "P3_WITHOUT_MULTISEED"}:
        if not evidence.p3_complete:
            return "STOP_P3_INCOMPLETE"
        values = evidence.all_outer_fit_union_oracle_ef5
        if len(values) != 5:
            return "STOP_MISSING_FIVE_OUTER_FIT_ORACLES"
        return "P4_LAMBDARANK" if min(values) >= 5.5 else "STOP_INSUFFICIENT_FIT_ONLY_UNION_SIGNAL"
    if current == "P4_LAMBDARANK":
        return "TERMINAL_DEVELOPMENT_EVALUATION"
    raise ProtocolError(f"unknown_stage:{current}")


def reliability_weights(
    sigma2: Sequence[float], parent_ids: Sequence[str], *, epsilon: float = 1e-6
) -> list[float]:
    """Fit-only capped reliability loss weights, normalized within parent."""
    if len(sigma2) != len(parent_ids) or not sigma2:
        raise ProtocolError("reliability_length_mismatch_or_empty")
    clean = [_finite(value, "sigma2") for value in sigma2]
    if any(value < 0.0 for value in clean) or epsilon != 1e-6:
        raise ProtocolError("invalid_reliability_variance_or_epsilon")
    for parent in parent_ids:
        if not isinstance(parent, str) or not parent:
            raise ProtocolError("invalid_parent_id")
    median = statistics.median(clean)
    raw = [min(2.0, max(0.5, (median + epsilon) / (value + epsilon))) for value in clean]
    by_parent: dict[str, list[int]] = {}
    for index, parent in enumerate(parent_ids):
        by_parent.setdefault(parent, []).append(index)
    output = raw[:]
    for indices in by_parent.values():
        scale = sum(raw[index] for index in indices) / len(indices)
        for index in indices:
            output[index] = raw[index] / scale
    return output


BASE_MODELS = ("L1", "B", "M2", "C2")
ALLOWED_FEATURE_NAMES = frozenset(
    {
        *(f"{model}_{suffix}" for model in BASE_MODELS for suffix in (
            "R8", "R9", "Rdual", "receptor_gap", "fit_cdf_percentile"
        )),
        "rank_mean",
        "rank_std",
        "rank_min",
        "rank_max",
        "model_disagreement",
        *(f"disagreement_{left}_{right}" for offset, left in enumerate(BASE_MODELS) for right in BASE_MODELS[offset + 1:]),
        "seed_std_R8",
        "seed_std_R9",
        "seed_std_Rdual",
        "seed_fit_cdf_percentile_std",
        "predicted_hotspot_mass",
        "predicted_off_interface_mass",
        "predicted_interface_specificity",
        "predicted_CDR1_mass",
        "predicted_CDR2_mass",
        "predicted_CDR3_mass",
        "predicted_contact_entropy",
        "predicted_conformer_gap",
    }
)


def validate_feature_names(names: Iterable[str]) -> None:
    """Reject every inference feature not explicitly frozen in the allowlist."""
    values = tuple(names)
    if not values:
        raise ProtocolError("empty_feature_set")
    if any(not isinstance(name, str) or not name for name in values):
        raise ProtocolError("invalid_feature_name")
    if len(values) != len(set(values)):
        raise ProtocolError("duplicate_feature_name")
    bad = sorted(name for name in values if name not in ALLOWED_FEATURE_NAMES)
    if bad:
        raise ProtocolError("forbidden_or_unknown_features:" + ",".join(bad))


def validate_whole_parent_nested_split(
    parent_ids: Sequence[str],
    outer_fit_indices: Sequence[int],
    outer_test_indices: Sequence[int],
    inner_splits: Sequence[tuple[Sequence[int], Sequence[int]]],
) -> None:
    """Validate exact outer/inner row coverage and whole-parent isolation."""
    if not parent_ids or any(not isinstance(parent, str) or not parent for parent in parent_ids):
        raise ProtocolError("invalid_parent_ids")
    n = len(parent_ids)
    outer_fit = _validated_indices(outer_fit_indices, "outer_fit", upper_bound=n)
    outer_test = _validated_indices(outer_test_indices, "outer_test", upper_bound=n)
    fit_set = set(outer_fit)
    test_set = set(outer_test)
    if fit_set & test_set or fit_set | test_set != set(range(n)):
        raise ProtocolError("outer_row_partition_not_exact")
    fit_parents = {parent_ids[index] for index in fit_set}
    test_parents = {parent_ids[index] for index in test_set}
    if fit_parents & test_parents:
        raise ProtocolError("outer_parent_leakage")
    if len(inner_splits) != 4:
        raise ProtocolError("requires_exact_four_inner_folds")

    validation_row_counts = {index: 0 for index in fit_set}
    validation_parent_counts = {parent: 0 for parent in fit_parents}
    for fold, split in enumerate(inner_splits):
        if not isinstance(split, tuple) or len(split) != 2:
            raise ProtocolError(f"invalid_inner_split:{fold}")
        inner_fit = _validated_indices(split[0], f"inner_{fold}_fit", upper_bound=n)
        inner_validation = _validated_indices(
            split[1], f"inner_{fold}_validation", upper_bound=n
        )
        inner_fit_set = set(inner_fit)
        inner_validation_set = set(inner_validation)
        if (
            inner_fit_set & inner_validation_set
            or inner_fit_set | inner_validation_set != fit_set
        ):
            raise ProtocolError(f"inner_row_partition_not_exact:{fold}")
        inner_fit_parents = {parent_ids[index] for index in inner_fit_set}
        inner_validation_parents = {
            parent_ids[index] for index in inner_validation_set
        }
        if inner_fit_parents & inner_validation_parents:
            raise ProtocolError(f"inner_parent_leakage:{fold}")
        for index in inner_validation_set:
            validation_row_counts[index] += 1
        for parent in inner_validation_parents:
            validation_parent_counts[parent] += 1

    if set(validation_row_counts.values()) != {1}:
        raise ProtocolError("inner_validation_rows_not_exactly_once")
    if set(validation_parent_counts.values()) != {1}:
        raise ProtocolError("inner_validation_parents_not_exactly_once")


@dataclass(frozen=True)
class FitOnlyThreshold:
    cutoff: float
    positive_indices: tuple[int, ...]
    fit_rows: int
    positive_count: int


def _fit_only_records(
    truth_by_index: Mapping[int, float],
    sequence_sha256_by_index: Mapping[int, str],
    fit_indices: Sequence[int],
    outer_test_indices: Sequence[int],
) -> tuple[dict[int, float], dict[int, str], tuple[int, ...]]:
    fit = _validated_indices(fit_indices, "label_fit")
    outer_test = _validated_indices(outer_test_indices, "label_outer_test")
    fit_set = set(fit)
    if fit_set & set(outer_test):
        raise ProtocolError("fit_test_label_scope_overlap")
    if any(type(index) is not int for index in truth_by_index) or any(
        type(index) is not int for index in sequence_sha256_by_index
    ):
        raise ProtocolError("invalid_fit_only_mapping_index")
    if set(truth_by_index) != fit_set or set(sequence_sha256_by_index) != fit_set:
        raise ProtocolError("fit_only_label_firewall_violation")
    truth = {index: _finite(truth_by_index[index], "fit_truth") for index in fit}
    sha = {index: sequence_sha256_by_index[index] for index in fit}
    _validate_sequence_sha256([sha[index] for index in fit])
    if len(set(sha.values())) != len(sha):
        raise ProtocolError("duplicate_sequence_sha256")
    return truth, sha, fit


def fit_only_top10_threshold(
    truth_by_index: Mapping[int, float],
    sequence_sha256_by_index: Mapping[int, str],
    fit_indices: Sequence[int],
    outer_test_indices: Sequence[int],
    *,
    positive_fraction: float = 0.10,
) -> FitOnlyThreshold:
    """Create exact fit-side Top10 relevance without reading test labels."""
    if _finite(positive_fraction, "positive_fraction") != 0.10:
        raise ProtocolError("requires_frozen_top10_fraction")
    truth, sha, fit = _fit_only_records(
        truth_by_index, sequence_sha256_by_index, fit_indices, outer_test_indices
    )
    count = math.ceil(len(fit) * positive_fraction)
    ranked = sorted(fit, key=lambda index: (-truth[index], sha[index]))
    positive = tuple(ranked[:count])
    return FitOnlyThreshold(
        cutoff=truth[positive[-1]],
        positive_indices=positive,
        fit_rows=len(fit),
        positive_count=count,
    )


def fit_only_union_oracle_ef5(
    truth_by_index: Mapping[int, float],
    sequence_sha256_by_index: Mapping[int, str],
    fit_indices: Sequence[int],
    outer_test_indices: Sequence[int],
    union_indices: Sequence[int],
    *,
    budget_fraction: float = 0.05,
) -> dict[str, float | int]:
    """Measure only the fit-side upper bound of a label-free candidate union."""
    if _finite(budget_fraction, "budget_fraction") != 0.05:
        raise ProtocolError("requires_frozen_top5_budget")
    threshold = fit_only_top10_threshold(
        truth_by_index,
        sequence_sha256_by_index,
        fit_indices,
        outer_test_indices,
    )
    fit_set = set(fit_indices)
    union = _validated_indices(union_indices, "fit_union")
    if not set(union) <= fit_set:
        raise ProtocolError("outer_test_or_unknown_row_in_fit_union")
    budget = math.ceil(threshold.fit_rows * budget_fraction)
    if len(union) < budget:
        raise ProtocolError("fit_union_smaller_than_budget")
    available_positives = len(set(union) & set(threshold.positive_indices))
    hits = min(budget, available_positives)
    prevalence = threshold.positive_count / threshold.fit_rows
    precision = hits / budget
    return {
        "fit_rows": threshold.fit_rows,
        "positive_count": threshold.positive_count,
        "budget": budget,
        "union_rows": len(union),
        "available_positive_count": available_positives,
        "oracle_hits": hits,
        "oracle_ef5": precision / prevalence,
    }


def parent_capped_rank_pool(
    scores: Sequence[float],
    sequence_sha256: Sequence[str],
    parent_ids: Sequence[str],
    positive_flags: Sequence[bool],
    *,
    per_parent_cap: int,
    zero_positive_sentinels: int,
) -> list[int]:
    """Build a deterministic fit-side pool with an equal parent cap."""
    n = len(scores)
    if not n or len(sequence_sha256) != n or len(parent_ids) != n or len(positive_flags) != n:
        raise ProtocolError("parent_pool_length_mismatch_or_empty")
    cap = _strict_int(per_parent_cap, "per_parent_cap")
    sentinels = _strict_int(zero_positive_sentinels, "zero_positive_sentinels")
    if cap < 1 or sentinels < 1 or sentinels > cap:
        raise ProtocolError("invalid_parent_cap_or_sentinel_count")
    _validate_sequence_sha256(sequence_sha256)
    if len(set(sequence_sha256)) != n:
        raise ProtocolError("duplicate_sequence_sha256")
    clean_scores = [_finite(value, "parent_pool_score") for value in scores]
    for parent in parent_ids:
        if not isinstance(parent, str) or not parent:
            raise ProtocolError("invalid_parent_id")
    for flag in positive_flags:
        _strict_bool(flag, "positive_flag")

    by_parent: dict[str, list[int]] = {}
    for index, parent in enumerate(parent_ids):
        by_parent.setdefault(parent, []).append(index)
    output: list[int] = []
    for parent in sorted(by_parent):
        rows = by_parent[parent]
        positives = sorted(
            (index for index in rows if positive_flags[index]),
            key=lambda index: (-clean_scores[index], sequence_sha256[index]),
        )
        negatives = sorted(
            (index for index in rows if not positive_flags[index]),
            key=lambda index: (-clean_scores[index], sequence_sha256[index]),
        )
        if positives:
            output.extend((positives + negatives)[:cap])
        else:
            output.extend(negatives[:sentinels])
    return output


def degree_preserving_contact_shuffle(
    matrix: Sequence[Sequence[int]], *, seed: int, swaps: int
) -> tuple[tuple[int, ...], ...]:
    """Shuffle binary contacts through sparse edge swaps preserving both margins."""
    if type(seed) is not int:
        raise ProtocolError("invalid_contact_shuffle_seed")
    requested_swaps = _strict_int(swaps, "contact_shuffle_swaps")
    if requested_swaps < 1:
        raise ProtocolError("invalid_contact_shuffle_swaps")
    if len(matrix) < 2 or any(len(row) < 2 for row in matrix):
        raise ProtocolError("contact_matrix_too_small")
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ProtocolError("ragged_contact_matrix")
    if any(type(value) is not int or value not in (0, 1) for row in matrix for value in row):
        raise ProtocolError("contact_matrix_requires_binary_integers")

    original = tuple(tuple(row) for row in matrix)
    shuffled = [list(row) for row in original]
    rng = random.Random(seed)
    def find_switch() -> tuple[int, int, int, int] | None:
        edges = [
            (row, column)
            for row, values in enumerate(shuffled)
            for column, value in enumerate(values)
            if value == 1
        ]

        def valid(first: tuple[int, int], second: tuple[int, int]) -> bool:
            row_a, column_a = first
            row_b, column_b = second
            return (
                row_a != row_b
                and column_a != column_b
                and shuffled[row_a][column_b] == 0
                and shuffled[row_b][column_a] == 0
            )

        if len(edges) < 2:
            return None
        attempts = max(100, min(10_000, len(edges) * 4))
        for _ in range(attempts):
            first_index, second_index = rng.sample(range(len(edges)), 2)
            first, second = edges[first_index], edges[second_index]
            if valid(first, second):
                return first[0], second[0], first[1], second[1]
        for first_index, first in enumerate(edges[:-1]):
            for second in edges[first_index + 1 :]:
                if valid(first, second):
                    return first[0], second[0], first[1], second[1]
        return None

    def apply_switch(switch: tuple[int, int, int, int]) -> None:
        row_a, row_b, column_a, column_b = switch
        shuffled[row_a][column_a] = 0
        shuffled[row_b][column_b] = 0
        shuffled[row_a][column_b] = 1
        shuffled[row_b][column_a] = 1

    for _ in range(requested_swaps):
        switch = find_switch()
        if switch is None:
            raise ProtocolError("contact_shuffle_not_possible")
        apply_switch(switch)

    output = tuple(tuple(row) for row in shuffled)
    if output == original:
        repair = find_switch()
        if repair is None:
            raise ProtocolError("contact_shuffle_returned_identity")
        apply_switch(repair)
        output = tuple(tuple(row) for row in shuffled)
    original_rows = tuple(sum(row) for row in original)
    output_rows = tuple(sum(row) for row in output)
    original_columns = tuple(sum(row[column] for row in original) for column in range(width))
    output_columns = tuple(sum(row[column] for row in output) for column in range(width))
    if original_rows != output_rows or original_columns != output_columns:
        raise ProtocolError("contact_shuffle_margin_violation")
    if sum(original_rows) != sum(output_rows):
        raise ProtocolError("contact_shuffle_density_violation")
    return output


def apply_target_residue_permutation(
    payload_by_residue: Mapping[str, Payload],
    destination_to_source: Mapping[str, str],
) -> dict[str, Payload]:
    """Apply a closed, non-identity target-residue payload permutation."""
    keys = tuple(payload_by_residue)
    if len(keys) < 2 or any(not isinstance(key, str) or not key for key in keys):
        raise ProtocolError("invalid_target_residue_keys")
    if any(
        not isinstance(destination, str)
        or not destination
        or not isinstance(source, str)
        or not source
        for destination, source in destination_to_source.items()
    ):
        raise ProtocolError("invalid_target_permutation_keys")
    universe = set(keys)
    if set(destination_to_source) != universe or set(destination_to_source.values()) != universe:
        raise ProtocolError("target_permutation_not_closed_bijection")
    if all(destination_to_source[key] == key for key in keys):
        raise ProtocolError("target_permutation_is_identity")
    return {
        destination: payload_by_residue[destination_to_source[destination]]
        for destination in keys
    }


def swap_dual_conformer_payloads(
    payload_by_conformer: Mapping[str, Payload],
) -> dict[str, Payload]:
    """Swap the complete 8X6B/9E6Y payloads with an exact closed mapping."""
    required = {"8X6B", "9E6Y"}
    if set(payload_by_conformer) != required:
        raise ProtocolError("dual_conformer_mapping_not_closed")
    return {
        "8X6B": payload_by_conformer["9E6Y"],
        "9E6Y": payload_by_conformer["8X6B"],
    }


FORBIDDEN_PROSPECTIVE_PATH_MARKERS = frozenset(
    {"prospective", "sealed", "unsealed", "v4f", "top7500", "opendevelopment"}
)


def validate_nonprospective_paths(paths: Iterable[str]) -> None:
    """Lexically reject prospective/open-development artifacts before access."""
    values = tuple(paths)
    if not values:
        raise ProtocolError("empty_training_path_set")
    for raw in values:
        if not isinstance(raw, str) or not raw or any(character in raw for character in "\x00\r\n"):
            raise ProtocolError("invalid_training_path")
        normalized = raw.replace("\\", "/")
        segments = [segment for segment in normalized.split("/") if segment]
        if not segments or ".." in segments or "://" in normalized:
            raise ProtocolError("unsafe_training_path")
        compact_segments = {
            re.sub(r"[^a-z0-9]", "", segment.casefold()) for segment in segments
        }
        tokens = {
            token
            for segment in segments
            for token in re.findall(r"[a-z0-9]+", segment.casefold())
        }
        markers = (compact_segments | tokens) & FORBIDDEN_PROSPECTIVE_PATH_MARKERS
        if markers or any("prospective" in segment or "sealed" in segment for segment in compact_segments):
            raise ProtocolError(
                "prospective_or_open_development_path_forbidden:" + normalized
            )


def validate_training_input_firewall(
    paths: Iterable[str], feature_names: Iterable[str]
) -> None:
    """Enforce both path- and feature-level prospective/label firewalls."""
    validate_nonprospective_paths(paths)
    validate_feature_names(feature_names)
