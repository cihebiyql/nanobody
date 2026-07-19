#!/usr/bin/env python3
"""Auditable, label-free multi-model recall selector for a 100K VHH pool.

The selector consumes only explicitly declared prediction, uncertainty,
provenance, diversity and QC columns.  It deliberately has no argument for a
Docking truth table, experimental label, sealed holdout, or prospective test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v2_7_label_free_multimodel_selector_v1"
CONFIG_SCHEMA = "pvrig_v2_7_label_free_selector_config_v1"
CHANNEL_ORDER = (
    "exploitation",
    "single_model_rescue",
    "disagreement",
    "diversity",
    "random_sentinel",
)
TRUTH_FIELD_EXACT = {
    "r8",
    "r9",
    "r_8x6b",
    "r_9e6y",
    "rdual",
    "r_dual",
    "r_dual_min",
    "geometry_tier",
    "consensus_geometry_tier",
    "blocking_label",
    "binding_label",
}
TRUTH_FIELD_TOKENS = (
    "ground_truth",
    "docking_truth",
    "docking_label",
    "haddock_score",
    "experimental_binding",
    "experimental_blocking",
    "prospective_test_label",
    "sealed_label",
)
TRUTH_FIELD_PREFIXES = ("true_", "actual_", "observed_", "measured_", "label_")
PROHIBITED_PATH_TOKENS = (
    "sealed",
    "test32",
    "v4_f",
    "prospective_holdout",
    "docking_truth",
    "teacher_label",
)
TRUE_VALUES = {"1", "true", "t", "yes", "y", "pass", "passed"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "fail", "failed", ""}


class SelectorError(RuntimeError):
    """Fail-closed selector error."""


@dataclass(frozen=True)
class ModelSpec:
    name: str
    score_column: str
    uncertainty_column: str | None
    higher_is_better: bool
    weight: float
    uncertainty_penalty: float


@dataclass
class Candidate:
    row: dict[str, str]
    candidate_id: str
    model_scores: dict[str, float] = field(default_factory=dict)
    model_uncertainties: dict[str, float] = field(default_factory=dict)
    model_utilities: dict[str, float] = field(default_factory=dict)
    uncertainty_utilities: dict[str, float] = field(default_factory=dict)
    adjusted_utilities: dict[str, float] = field(default_factory=dict)
    ensemble_utility: float = float("nan")
    disagreement_utility: float = float("nan")
    mean_uncertainty_utility: float = float("nan")


@dataclass(frozen=True)
class Selection:
    candidate: Candidate
    channel: str
    reason: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(seed: str, *parts: object) -> str:
    payload = "\x1f".join([seed, *(str(part) for part in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_bool(value: str, *, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise SelectorError(f"invalid_boolean:{field_name}:{value!r}")


def parse_finite(value: str, *, field_name: str, allow_empty: bool = False) -> float | None:
    if value.strip() == "" and allow_empty:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise SelectorError(f"invalid_numeric:{field_name}:{value!r}") from exc
    if not math.isfinite(number):
        raise SelectorError(f"nonfinite_numeric:{field_name}:{value!r}")
    return number


def is_truth_field(name: str) -> bool:
    normalized = name.strip().lower()
    return (
        normalized in TRUTH_FIELD_EXACT
        or any(normalized.startswith(prefix) for prefix in TRUTH_FIELD_PREFIXES)
        or any(token in normalized for token in TRUTH_FIELD_TOKENS)
    )


def assert_safe_path(path: Path, *, role: str) -> None:
    lowered_parts = [part.lower() for part in path.resolve().parts]
    for part in lowered_parts:
        if any(token in part for token in PROHIBITED_PATH_TOKENS):
            raise SelectorError(f"prohibited_{role}_path:{path}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectorError(f"invalid_config_json:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise SelectorError("config_must_be_json_object")
    return payload


def require_nonempty_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SelectorError(f"config_missing_string:{key}")
    return value.strip()


def parse_config(payload: Mapping[str, Any]) -> tuple[str, list[ModelSpec], dict[str, Any]]:
    if payload.get("schema_version") != CONFIG_SCHEMA:
        raise SelectorError(f"unsupported_config_schema:{payload.get('schema_version')!r}")
    candidate_id_column = require_nonempty_string(payload, "candidate_id_column")
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or len(raw_models) < 2:
        raise SelectorError("at_least_two_models_required")
    models: list[ModelSpec] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(raw_models):
        if not isinstance(raw, dict):
            raise SelectorError(f"model_spec_not_object:{index}")
        name = require_nonempty_string(raw, "name")
        score = require_nonempty_string(raw, "score_column")
        uncertainty = raw.get("uncertainty_column")
        if uncertainty is not None and (not isinstance(uncertainty, str) or not uncertainty.strip()):
            raise SelectorError(f"invalid_uncertainty_column:{name}")
        if name in seen_names:
            raise SelectorError(f"duplicate_model_name:{name}")
        seen_names.add(name)
        weight = float(raw.get("weight", 1.0))
        penalty = float(raw.get("uncertainty_penalty", 0.0))
        if not math.isfinite(weight) or weight <= 0:
            raise SelectorError(f"invalid_model_weight:{name}")
        if not math.isfinite(penalty) or penalty < 0:
            raise SelectorError(f"invalid_uncertainty_penalty:{name}")
        higher_is_better = raw.get("higher_is_better", True)
        if not isinstance(higher_is_better, bool):
            raise SelectorError(f"higher_is_better_must_be_boolean:{name}")
        models.append(
            ModelSpec(
                name=name,
                score_column=score,
                uncertainty_column=uncertainty.strip() if isinstance(uncertainty, str) else None,
                higher_is_better=higher_is_better,
                weight=weight,
                uncertainty_penalty=penalty,
            )
        )

    selection = payload.get("selection")
    if not isinstance(selection, dict):
        raise SelectorError("selection_config_missing")
    total = selection.get("total")
    quotas = selection.get("quotas")
    if not isinstance(total, int) or total <= 0:
        raise SelectorError("selection_total_must_be_positive_integer")
    if not isinstance(quotas, dict) or set(quotas) != set(CHANNEL_ORDER):
        raise SelectorError(f"selection_quotas_must_have_exact_channels:{CHANNEL_ORDER}")
    if any(not isinstance(quotas[channel], int) or quotas[channel] < 0 for channel in CHANNEL_ORDER):
        raise SelectorError("selection_quotas_must_be_nonnegative_integers")
    if sum(quotas.values()) != total:
        raise SelectorError("selection_quotas_do_not_sum_to_total")
    return candidate_id_column, models, dict(selection)


def referenced_columns(config: Mapping[str, Any], candidate_id_column: str, models: Sequence[ModelSpec]) -> set[str]:
    columns = {candidate_id_column}
    for model in models:
        columns.add(model.score_column)
        if model.uncertainty_column:
            columns.add(model.uncertainty_column)
    metadata = config.get("metadata_columns", {})
    if not isinstance(metadata, dict):
        raise SelectorError("metadata_columns_must_be_object")
    columns.update(str(value) for value in metadata.values())
    qc = config.get("qc", {})
    if not isinstance(qc, dict):
        raise SelectorError("qc_must_be_object")
    for key in ("pass_columns", "fail_columns"):
        values = qc.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise SelectorError(f"qc_{key}_must_be_string_list")
        columns.update(values)
    constraints = qc.get("numeric_constraints", {})
    if not isinstance(constraints, dict):
        raise SelectorError("qc_numeric_constraints_must_be_object")
    columns.update(constraints)
    for key in ("dedup_key_columns", "passthrough_columns"):
        values = config.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise SelectorError(f"{key}_must_be_string_list")
        columns.update(values)
    for key in ("group_caps",):
        values = config["selection"].get(key, {})
        if not isinstance(values, dict):
            raise SelectorError(f"selection_{key}_must_be_object")
        columns.update(values)
    for key in ("diversity_columns", "sentinel_strata_columns"):
        values = config["selection"].get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise SelectorError(f"selection_{key}_must_be_string_list")
        columns.update(values)
    return columns


def read_input(
    path: Path,
    config: Mapping[str, Any],
    candidate_id_column: str,
    models: Sequence[ModelSpec],
) -> tuple[list[Candidate], list[str], dict[str, int]]:
    assert_safe_path(path, role="input")
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        header = list(reader.fieldnames or [])
        if not header or len(header) != len(set(header)):
            raise SelectorError("missing_or_duplicate_input_header")
        forbidden = sorted(field for field in header if is_truth_field(field))
        if forbidden:
            raise SelectorError(f"forbidden_truth_columns:{','.join(forbidden)}")
        required = referenced_columns(config, candidate_id_column, models)
        missing = sorted(required - set(header))
        if missing:
            raise SelectorError(f"missing_input_columns:{','.join(missing)}")
        extras = sorted(set(header) - required)
        if extras and not bool(config.get("allow_extra_columns", False)):
            raise SelectorError(f"undeclared_input_columns:{','.join(extras)}")
        rows = [{key: value if value is not None else "" for key, value in row.items()} for row in reader]

    seen_ids: set[str] = set()
    all_candidates: list[Candidate] = []
    qc_counts: Counter[str] = Counter()
    qc = config.get("qc", {})
    pass_columns = list(qc.get("pass_columns", []))
    fail_columns = list(qc.get("fail_columns", []))
    constraints = dict(qc.get("numeric_constraints", {}))
    strict_nonempty_columns = referenced_columns(config, candidate_id_column, models) - {
        *(model.score_column for model in models),
        *(model.uncertainty_column for model in models if model.uncertainty_column),
        *config.get("passthrough_columns", []),
    }
    min_models = int(config.get("min_models_required", len(models)))
    if min_models < 1 or min_models > len(models):
        raise SelectorError("min_models_required_out_of_range")

    for row_number, row in enumerate(rows, start=2):
        candidate_id = row[candidate_id_column].strip()
        if not candidate_id:
            raise SelectorError(f"empty_candidate_id:row{row_number}")
        if candidate_id in seen_ids:
            raise SelectorError(f"duplicate_candidate_id:{candidate_id}")
        seen_ids.add(candidate_id)
        candidate = Candidate(row=row, candidate_id=candidate_id)
        for column in strict_nonempty_columns:
            if row[column].strip() == "":
                raise SelectorError(f"empty_required_value:{candidate_id}:{column}")
        eligible = True
        for column in pass_columns:
            if not parse_bool(row[column], field_name=column):
                eligible = False
                qc_counts[f"pass_gate_failed:{column}"] += 1
        for column in fail_columns:
            if parse_bool(row[column], field_name=column):
                eligible = False
                qc_counts[f"fail_gate_triggered:{column}"] += 1
        for column, raw_rule in constraints.items():
            if not isinstance(raw_rule, dict):
                raise SelectorError(f"invalid_numeric_constraint:{column}")
            value = parse_finite(row[column], field_name=column, allow_empty=False)
            assert value is not None
            if "min" in raw_rule and value < float(raw_rule["min"]):
                eligible = False
                qc_counts[f"numeric_below_min:{column}"] += 1
            if "max" in raw_rule and value > float(raw_rule["max"]):
                eligible = False
                qc_counts[f"numeric_above_max:{column}"] += 1
        for model in models:
            raw_score = row[model.score_column]
            score = parse_finite(raw_score, field_name=model.score_column, allow_empty=True)
            if score is None:
                continue
            candidate.model_scores[model.name] = score
            if model.uncertainty_column:
                uncertainty = parse_finite(
                    row[model.uncertainty_column],
                    field_name=model.uncertainty_column,
                    allow_empty=True,
                )
                if uncertainty is None:
                    raise SelectorError(f"missing_uncertainty_for_available_score:{candidate_id}:{model.name}")
                if uncertainty < 0:
                    raise SelectorError(f"negative_uncertainty:{candidate_id}:{model.name}")
                candidate.model_uncertainties[model.name] = uncertainty
        if len(candidate.model_scores) < min_models:
            eligible = False
            qc_counts["insufficient_models"] += 1
        if eligible:
            all_candidates.append(candidate)
        else:
            qc_counts["ineligible_rows"] += 1
    qc_counts["input_rows"] = len(rows)
    qc_counts["qc_eligible_rows_before_dedup"] = len(all_candidates)
    return all_candidates, header, dict(qc_counts)


def average_rank_percentiles(values_by_id: Mapping[str, float], *, higher_is_better: bool) -> dict[str, float]:
    if not values_by_id:
        return {}
    ordered = sorted(values_by_id.items(), key=lambda item: (item[1], item[0]))
    output: dict[str, float] = {}
    denominator = max(1, len(ordered) - 1)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_position = (index + end - 1) / 2.0
        percentile = average_position / denominator if len(ordered) > 1 else 1.0
        utility = percentile if higher_is_better else 1.0 - percentile
        for cursor in range(index, end):
            output[ordered[cursor][0]] = utility
        index = end
    return output


def apply_dedup(candidates: Sequence[Candidate], dedup_columns: Sequence[str]) -> tuple[list[Candidate], int]:
    if not dedup_columns:
        return list(candidates), 0
    groups: dict[tuple[str, ...], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        key = tuple(candidate.row[column].strip() for column in dedup_columns)
        if any(not value for value in key):
            raise SelectorError(f"empty_dedup_key:{candidate.candidate_id}")
        groups[key].append(candidate)
    representatives = [min(group, key=lambda c: c.candidate_id) for group in groups.values()]
    return sorted(representatives, key=lambda c: c.candidate_id), len(candidates) - len(representatives)


def score_candidates(candidates: Sequence[Candidate], models: Sequence[ModelSpec]) -> None:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for model in models:
        score_ranks = average_rank_percentiles(
            {candidate.candidate_id: candidate.model_scores[model.name] for candidate in candidates if model.name in candidate.model_scores},
            higher_is_better=model.higher_is_better,
        )
        uncertainty_ranks = average_rank_percentiles(
            {
                candidate.candidate_id: candidate.model_uncertainties[model.name]
                for candidate in candidates
                if model.name in candidate.model_uncertainties
            },
            higher_is_better=True,
        )
        for candidate_id, utility in score_ranks.items():
            candidate = by_id[candidate_id]
            candidate.model_utilities[model.name] = utility
            uncertainty_utility = uncertainty_ranks.get(candidate_id, 0.0)
            candidate.uncertainty_utilities[model.name] = uncertainty_utility
            candidate.adjusted_utilities[model.name] = utility - model.uncertainty_penalty * uncertainty_utility

    weights = {model.name: model.weight for model in models}
    for candidate in candidates:
        available = candidate.adjusted_utilities
        denominator = sum(weights[name] for name in available)
        candidate.ensemble_utility = sum(weights[name] * value for name, value in available.items()) / denominator
        raw_utilities = list(candidate.model_utilities.values())
        candidate.disagreement_utility = max(raw_utilities) - min(raw_utilities) if len(raw_utilities) > 1 else 0.0
        candidate.mean_uncertainty_utility = (
            sum(candidate.uncertainty_utilities.values()) / len(candidate.uncertainty_utilities)
            if candidate.uncertainty_utilities
            else 0.0
        )


class PortfolioSelector:
    def __init__(self, candidates: Sequence[Candidate], models: Sequence[ModelSpec], selection: Mapping[str, Any]):
        self.candidates = list(candidates)
        self.models = list(models)
        self.selection = selection
        self.selected: dict[str, Selection] = {}
        self.ordered: list[Selection] = []
        self.group_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.skipped_selected: Counter[str] = Counter()
        self.skipped_caps: Counter[str] = Counter()
        raw_caps = selection.get("group_caps", {})
        self.group_caps: dict[str, int] = {}
        for column, cap in raw_caps.items():
            if not isinstance(cap, int) or cap <= 0:
                raise SelectorError(f"invalid_group_cap:{column}:{cap!r}")
            self.group_caps[column] = cap
        self.seed = str(selection.get("random_seed", "pvrig-v2.7-label-free-selector-v1"))

    def can_select(self, candidate: Candidate) -> bool:
        return all(self.group_counts[column][candidate.row[column]] < cap for column, cap in self.group_caps.items())

    def take(self, candidate: Candidate, channel: str, reason: str) -> bool:
        if candidate.candidate_id in self.selected:
            self.skipped_selected[channel] += 1
            return False
        if not self.can_select(candidate):
            self.skipped_caps[channel] += 1
            return False
        selection = Selection(candidate=candidate, channel=channel, reason=reason)
        self.selected[candidate.candidate_id] = selection
        self.ordered.append(selection)
        for column in self.group_caps:
            self.group_counts[column][candidate.row[column]] += 1
        return True

    def fill_ranked(self, channel: str, quota: int, ranked: Iterable[tuple[Candidate, str]]) -> None:
        start = len(self.ordered)
        for candidate, reason in ranked:
            self.take(candidate, channel, reason)
            if len(self.ordered) - start == quota:
                return
        if len(self.ordered) - start != quota:
            raise SelectorError(f"quota_unfillable:{channel}:{len(self.ordered)-start}/{quota}")

    def exploitation(self, quota: int) -> None:
        ranked = sorted(self.candidates, key=lambda c: (-c.ensemble_utility, c.candidate_id))
        self.fill_ranked(
            "exploitation",
            quota,
            ((candidate, "exploitation:weighted_rank_ensemble") for candidate in ranked),
        )

    def single_model_rescue(self, quota: int) -> None:
        if quota == 0:
            return
        lists: dict[str, list[Candidate]] = {
            model.name: sorted(
                (candidate for candidate in self.candidates if model.name in candidate.adjusted_utilities),
                key=lambda c, name=model.name: (-c.adjusted_utilities[name], c.candidate_id),
            )
            for model in self.models
        }
        cursors = {model.name: 0 for model in self.models}
        start = len(self.ordered)
        while len(self.ordered) - start < quota:
            progress = False
            for model in self.models:
                name = model.name
                while cursors[name] < len(lists[name]):
                    candidate = lists[name][cursors[name]]
                    cursors[name] += 1
                    if self.take(candidate, "single_model_rescue", f"single_model_rescue:{name}"):
                        progress = True
                        break
                if len(self.ordered) - start == quota:
                    return
            if not progress:
                break
        if len(self.ordered) - start != quota:
            raise SelectorError(f"quota_unfillable:single_model_rescue:{len(self.ordered)-start}/{quota}")

    def disagreement(self, quota: int) -> None:
        best_weight = float(self.selection.get("disagreement_best_model_weight", 0.25))
        ranked = sorted(
            self.candidates,
            key=lambda c: (
                -(c.disagreement_utility + best_weight * max(c.model_utilities.values())),
                -max(c.model_utilities.values()),
                c.candidate_id,
            ),
        )
        self.fill_ranked(
            "disagreement",
            quota,
            ((candidate, "disagreement:model_rank_spread") for candidate in ranked),
        )

    def diversity(self, quota: int) -> None:
        columns = list(self.selection.get("diversity_columns", []))
        if quota and not columns:
            raise SelectorError("diversity_columns_required_for_nonzero_quota")
        groups: dict[tuple[str, ...], list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            key = tuple(candidate.row[column] for column in columns)
            if any(not value for value in key):
                raise SelectorError(f"empty_diversity_key:{candidate.candidate_id}")
            groups[key].append(candidate)
        for key in groups:
            groups[key].sort(key=lambda c: (-c.ensemble_utility, c.candidate_id))
        keys = sorted(groups, key=lambda key: stable_hash(self.seed, "diversity", *key))
        cursors = {key: 0 for key in keys}
        start = len(self.ordered)
        while len(self.ordered) - start < quota:
            progress = False
            for key in keys:
                while cursors[key] < len(groups[key]):
                    candidate = groups[key][cursors[key]]
                    cursors[key] += 1
                    reason = "diversity:" + "|".join(f"{column}={value}" for column, value in zip(columns, key))
                    if self.take(candidate, "diversity", reason):
                        progress = True
                        break
                if len(self.ordered) - start == quota:
                    return
            if not progress:
                break
        if len(self.ordered) - start != quota:
            raise SelectorError(f"quota_unfillable:diversity:{len(self.ordered)-start}/{quota}")

    def random_sentinel(self, quota: int) -> None:
        columns = list(self.selection.get("sentinel_strata_columns", []))
        bins = int(self.selection.get("sentinel_score_bins", 5))
        if bins < 1:
            raise SelectorError("sentinel_score_bins_must_be_positive")
        strata: dict[tuple[str, ...], list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            score_bin = min(bins - 1, max(0, int(candidate.ensemble_utility * bins)))
            key = (*[candidate.row[column] for column in columns], f"score_bin_{score_bin}")
            strata[key].append(candidate)
        for key in strata:
            strata[key].sort(key=lambda c: stable_hash(self.seed, "sentinel", c.candidate_id))
        keys = sorted(strata, key=lambda key: stable_hash(self.seed, "sentinel_stratum", *key))
        cursors = {key: 0 for key in keys}
        start = len(self.ordered)
        while len(self.ordered) - start < quota:
            progress = False
            for key in keys:
                while cursors[key] < len(strata[key]):
                    candidate = strata[key][cursors[key]]
                    cursors[key] += 1
                    reason = "random_sentinel:" + "|".join(key)
                    if self.take(candidate, "random_sentinel", reason):
                        progress = True
                        break
                if len(self.ordered) - start == quota:
                    return
            if not progress:
                break
        if len(self.ordered) - start != quota:
            raise SelectorError(f"quota_unfillable:random_sentinel:{len(self.ordered)-start}/{quota}")

    def run(self) -> list[Selection]:
        quotas = self.selection["quotas"]
        self.exploitation(quotas["exploitation"])
        self.single_model_rescue(quotas["single_model_rescue"])
        self.disagreement(quotas["disagreement"])
        self.diversity(quotas["diversity"])
        self.random_sentinel(quotas["random_sentinel"])
        if len(self.ordered) != self.selection["total"]:
            raise SelectorError(f"selection_total_mismatch:{len(self.ordered)}")
        return self.ordered


def output_fields(header: Sequence[str], candidate_id_column: str) -> list[str]:
    audit_fields = [
        "selection_rank",
        "selection_channel",
        "selection_reason",
        "ensemble_utility",
        "disagreement_utility",
        "mean_uncertainty_utility",
        "best_model",
        "best_model_utility",
        "models_available",
        "selection_hash",
    ]
    return [candidate_id_column, *audit_fields, *(field for field in header if field != candidate_id_column)]


def write_selection(path: Path, selections: Sequence[Selection], header: Sequence[str], candidate_id_column: str, seed: str) -> None:
    fields = output_fields(header, candidate_id_column)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for rank, selection in enumerate(selections, start=1):
            candidate = selection.candidate
            best_model = max(candidate.model_utilities, key=lambda name: (candidate.model_utilities[name], name))
            row = dict(candidate.row)
            row.update(
                {
                    candidate_id_column: candidate.candidate_id,
                    "selection_rank": str(rank),
                    "selection_channel": selection.channel,
                    "selection_reason": selection.reason,
                    "ensemble_utility": f"{candidate.ensemble_utility:.12f}",
                    "disagreement_utility": f"{candidate.disagreement_utility:.12f}",
                    "mean_uncertainty_utility": f"{candidate.mean_uncertainty_utility:.12f}",
                    "best_model": best_model,
                    "best_model_utility": f"{candidate.model_utilities[best_model]:.12f}",
                    "models_available": ",".join(sorted(candidate.model_utilities)),
                    "selection_hash": stable_hash(seed, candidate.candidate_id),
                }
            )
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_publish(
    input_path: Path,
    config_path: Path,
    output_dir: Path,
    config: Mapping[str, Any],
    candidate_id_column: str,
    models: Sequence[ModelSpec],
    selection_config: Mapping[str, Any],
) -> dict[str, Any]:
    if output_dir.exists():
        raise SelectorError(f"output_dir_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp.", dir=output_dir.parent))
    try:
        candidates, header, qc_counts = read_input(input_path, config, candidate_id_column, models)
        dedup_columns = list(config.get("dedup_key_columns", []))
        candidates, dedup_dropped = apply_dedup(candidates, dedup_columns)
        if len(candidates) < selection_config["total"]:
            raise SelectorError(f"insufficient_eligible_rows:{len(candidates)}<{selection_config['total']}")
        score_candidates(candidates, models)
        portfolio = PortfolioSelector(candidates, models, selection_config)
        selections = portfolio.run()
        selection_path = temp_dir / "selection.tsv"
        write_selection(selection_path, selections, header, candidate_id_column, portfolio.seed)
        channel_counts = Counter(selection.channel for selection in selections)
        observed_caps = {
            column: {
                "configured_cap": cap,
                "observed_max": max(portfolio.group_counts[column].values(), default=0),
                "groups_selected": len(portfolio.group_counts[column]),
            }
            for column, cap in portfolio.group_caps.items()
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_LABEL_FREE_SELECTION",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "claim_boundary": (
                "Label-free recall allocation for downstream structure prediction and Docking. "
                "This output is not Docking truth, binding evidence, affinity, experimental blocking, "
                "or a final submission ranking."
            ),
            "input": {
                "path": str(input_path.resolve()),
                "sha256": sha256_file(input_path),
                "bytes": input_path.stat().st_size,
                "header": header,
                "rows": qc_counts["input_rows"],
            },
            "config": {
                "path": str(config_path.resolve()),
                "sha256": sha256_file(config_path),
                "schema_version": config["schema_version"],
            },
            "label_access": {
                "docking_truth_columns_consumed": 0,
                "docking_label_files_opened": 0,
                "sealed_files_opened": 0,
                "prospective_holdout_files_opened": 0,
                "experimental_labels_opened": 0,
            },
            "selection_contract": {
                "total": selection_config["total"],
                "quotas": selection_config["quotas"],
                "channel_order": list(CHANNEL_ORDER),
                "channel_counts": dict(sorted(channel_counts.items())),
                "stable_tie_break": "candidate_id ascending",
                "random_sentinel": "SHA256(random_seed, candidate_id), stratified by configured metadata and ensemble score bin",
                "random_seed": portfolio.seed,
                "group_caps": observed_caps,
                "dedup_key_columns": dedup_columns,
                "duplicate_rows_dropped": dedup_dropped,
                "already_selected_hits_skipped_and_backfilled": dict(portfolio.skipped_selected),
                "group_cap_hits_skipped_and_backfilled": dict(portfolio.skipped_caps),
            },
            "model_contract": {
                "normalization": "tie-aware average rank percentile within current label-free eligible pool",
                "ensemble": "weighted mean of model rank utility minus configured uncertainty-rank penalty",
                "disagreement": "max minus min unpenalized model rank utility",
                "models": [model.__dict__ for model in models],
            },
            "qc_counts": qc_counts,
            "eligible_rows_after_dedup": len(candidates),
            "selected_rows": len(selections),
            "selection_sha256": sha256_file(selection_path),
            "selected_candidate_id_digest": hashlib.sha256(
                "\n".join(selection.candidate.candidate_id for selection in selections).encode("utf-8")
            ).hexdigest(),
        }
        manifest_path = temp_dir / "selection_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checksums = {
            "selection.tsv": sha256_file(selection_path),
            "selection_manifest.json": sha256_file(manifest_path),
        }
        (temp_dir / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="utf-8"
        )
        os.replace(temp_dir, output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Declared label-free CSV/TSV candidate table")
    parser.add_argument("--config", required=True, type=Path, help="Frozen JSON selector configuration")
    parser.add_argument("--output-dir", required=True, type=Path, help="New immutable output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    assert_safe_path(args.config, role="config")
    assert_safe_path(args.output_dir, role="output")
    config = load_json(args.config)
    candidate_id_column, models, selection = parse_config(config)
    manifest = atomic_publish(
        args.input,
        args.config,
        args.output_dir,
        config,
        candidate_id_column,
        models,
        selection,
    )
    print(json.dumps({"status": manifest["status"], "selected_rows": manifest["selected_rows"], "output_dir": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
