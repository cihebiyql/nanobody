#!/usr/bin/env python3
"""Observe V2.4 V2.2 contact gradients on eight frozen training batches.

V2.2 technically supersedes V2.1 because V2.1 observations emitted the base
trainer claim boundary instead of the adaptive-multiseed manifest claim.  No
numeric gate, batch, grid, model, or weight-selection rule changes here.  This
wrapper deliberately imports, but never edits, the immutable V1 base trainer.
It constructs no optimizer and performs no parameter update.  The
same initialized model is evaluated on eight deterministic, hash-bound batches;
each grid value records all eight gradient fractions.  The selected value is
the smallest weight whose median fraction is inside the frozen band and whose
maximum fraction is below the frozen ceiling.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import train_v2_4_base_split as base  # noqa: E402


SCHEMA_VERSION = "pvrig_v2_4_open_only_prestep_multibatch_gradient_observation_v2_2_claim_aligned"
STATUS = "PASS_OPEN_ONLY_PRESTEP_MULTIBATCH_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4_V2_2_CLAIM_ALIGNED"
SUPERSESSION_VERSION = "V2.2_CLAIM_BOUNDARY_ALIGNMENT_ONLY"
CLAIM_BOUNDARY = (
    "Open-only adaptive-multiseed independent 8X6B/9E6Y computational Docking "
    "geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, "
    "or submission evidence."
)
SELECTION_RULE = (
    "smallest_grid_value_with_median_in_band_and_per_batch_max_at_or_below_ceiling_"
    "before_optimizer_construction"
)
DEFAULT_BATCH_COUNT = 8
GRADIENT_GROUPS = (
    "shared_encoder", "pair_factors", "attention_contact_terminals", "scalar_head",
)


class MultiBatchCalibrationError(base.BaseTrainerError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MultiBatchCalibrationError(message)


def canonical_candidate_ids_sha256(candidate_ids: Sequence[str]) -> str:
    require(bool(candidate_ids), "batch_candidate_ids_empty")
    require(len(candidate_ids) == len(set(candidate_ids)), "batch_candidate_ids_duplicate")
    payload = "".join(f"{candidate_id}\n" for candidate_id in candidate_ids).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evenly_spaced_complete_batch_offsets(
    training_candidate_count: int, batch_size: int, batch_count: int = DEFAULT_BATCH_COUNT,
) -> list[int]:
    require(training_candidate_count > 0 and batch_size > 0, "batch_dimensions_invalid")
    require(batch_count >= 2, "batch_count_too_small")
    complete_batches = training_candidate_count // batch_size
    require(complete_batches >= batch_count, "insufficient_complete_training_batches")
    offsets = [
        index * (complete_batches - 1) // (batch_count - 1)
        for index in range(batch_count)
    ]
    require(len(offsets) == batch_count and len(set(offsets)) == batch_count, "batch_offsets_not_unique")
    require(offsets[0] == 0 and offsets[-1] == complete_batches - 1, "batch_offsets_endpoints")
    return offsets


def gradient_parameter_group(name: str) -> str:
    """Assign each trainable parameter to one audit-only architecture group."""
    if name.startswith("head.interaction.vhh_left.") or name.startswith("head.interaction.target_right."):
        return "pair_factors"
    terminal_prefixes = (
        "head.interaction.attention_terminal", "head.interaction.contact_terminal",
        "head.interaction.attention_vhh_bias.", "head.interaction.attention_target_bias.",
        "head.contact_calibration.",
    )
    if name.startswith(terminal_prefixes):
        return "attention_contact_terminals"
    if name.startswith("head.scalar_head."):
        return "scalar_head"
    return "shared_encoder"


def grouped_component_gradient_telemetry(
    parts: Mapping[str, torch.Tensor],
    named_parameters: Sequence[tuple[str, torch.Tensor]],
) -> dict[str, Any]:
    """Compute total and grouped telemetry from the same two autograd calls.

    Grouped values are descriptive only.  Contact-weight selection remains
    exclusively a function of the total median fraction and total maximum cap.
    """
    require(bool(named_parameters), "calibration_trainable_parameters_empty")
    parameters = tuple(parameter for _name, parameter in named_parameters)
    gradients = {
        component: torch.autograd.grad(
            parts[component], parameters, retain_graph=True, allow_unused=True,
        )
        for component in ("scalar", "contact")
    }

    def summarize(indices: Sequence[int]) -> dict[str, Any]:
        norms: dict[str, float] = {}
        for component in ("scalar", "contact"):
            squared = torch.zeros((), dtype=torch.float64, device=parts[component].device)
            for index in indices:
                gradient = gradients[component][index]
                if gradient is not None:
                    base.require_finite(gradient, f"telemetry_gradient_nonfinite:{component}:{index}")
                    squared = squared + gradient.detach().double().square().sum()
            norms[component] = float(torch.sqrt(squared).cpu())
        dot = torch.zeros((), dtype=torch.float64, device=parts["scalar"].device)
        for index in indices:
            left, right = gradients["scalar"][index], gradients["contact"][index]
            if left is not None and right is not None:
                dot = dot + (left.detach().double() * right.detach().double()).sum()
        denominator = norms["scalar"] * norms["contact"]
        cosine = float(dot.cpu()) / denominator if denominator > 0.0 else None
        require(cosine is None or math.isfinite(cosine), "telemetry_cosine_nonfinite")
        return {"gradient_l2_norm": norms, "scalar_contact_cosine": cosine}

    total = summarize(list(range(len(named_parameters))))
    groups = {}
    for group in GRADIENT_GROUPS:
        indices = [
            index for index, (name, _parameter) in enumerate(named_parameters)
            if gradient_parameter_group(name) == group
        ]
        require(bool(indices), f"gradient_parameter_group_empty:{group}")
        groups[group] = {"parameter_tensor_count": len(indices), **summarize(indices)}
    return {**total, "parameter_groups": groups}


def summarize_grid_observations(
    *,
    grid: Sequence[float],
    per_batch_unit_norms: Sequence[Mapping[str, Any]],
    pair_to_marginal_ratio: float,
    median_band: Sequence[float],
    maximum_fraction: float,
    lane: str,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    require(lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}, "calibration_lane_invalid")
    require(
        list(grid) == sorted(set(float(value) for value in grid))
        and all(math.isfinite(float(value)) and float(value) > 0 for value in grid),
        "calibration_grid_invalid",
    )
    require(len(per_batch_unit_norms) == DEFAULT_BATCH_COUNT, "calibration_batch_count")
    require(0 < pair_to_marginal_ratio <= 1, "pair_to_marginal_ratio_invalid")
    require(
        len(median_band) == 2
        and 0 <= float(median_band[0]) <= float(median_band[1]) <= 1,
        "median_band_invalid",
    )
    require(float(median_band[1]) <= maximum_fraction <= 1, "maximum_fraction_invalid")

    observations: list[dict[str, Any]] = []
    for marginal_weight in grid:
        weight = float(marginal_weight)
        batch_records = []
        fractions = []
        for unit in per_batch_unit_norms:
            scalar_norm = float(unit["scalar_gradient_l2_norm"])
            unit_contact_norm = float(unit["unit_contact_gradient_l2_norm"])
            require(
                math.isfinite(scalar_norm) and scalar_norm >= 0
                and math.isfinite(unit_contact_norm) and unit_contact_norm >= 0,
                "gradient_norm_invalid",
            )
            contact_norm = weight * unit_contact_norm
            denominator = scalar_norm + contact_norm
            fraction = contact_norm / denominator if denominator > 0 else 0.0
            require(math.isfinite(fraction), "gradient_fraction_nonfinite")
            fractions.append(fraction)
            batch_records.append({
                "batch_id": str(unit["batch_id"]),
                "batch_offset": int(unit["batch_offset"]),
                "candidate_ids_sha256": str(unit["candidate_ids_sha256"]),
                "contact_gradient_fraction": fraction,
                "scalar_gradient_l2_norm": scalar_norm,
                "contact_gradient_l2_norm": contact_norm,
                "scalar_contact_cosine": unit["scalar_contact_cosine"],
                "gradient_groups": {
                    group: {
                        "parameter_tensor_count": record["parameter_tensor_count"],
                        "scalar_gradient_l2_norm": record["gradient_l2_norm"]["scalar"],
                        "contact_gradient_l2_norm": weight * record["gradient_l2_norm"]["contact"],
                        "scalar_contact_cosine": record["scalar_contact_cosine"],
                    }
                    for group, record in unit["parameter_groups"].items()
                },
            })
        median = float(np.median(np.asarray(fractions, dtype=np.float64)))
        maximum = float(max(fractions))
        eligible = (
            float(median_band[0]) <= median <= float(median_band[1])
            and maximum <= maximum_fraction
        )
        observations.append({
            "marginal_weight": weight,
            "pair_weight": 0.0 if lane == "C_SPLIT_MARGINAL" else weight * pair_to_marginal_ratio,
            "per_batch": batch_records,
            "median_contact_gradient_fraction": median,
            "maximum_contact_gradient_fraction": maximum,
            "eligible": eligible,
        })
    eligible = [record for record in observations if record["eligible"]]
    require(bool(eligible), "calibration_no_grid_value_satisfies_multibatch_rule")
    selected = min(eligible, key=lambda record: float(record["marginal_weight"]))
    return observations, {
        "marginal": float(selected["marginal_weight"]),
        "pair": float(selected["pair_weight"]),
    }


class RealBatchFactory:
    """Minimal read-only copy of the V1 local main-scope batch adapter."""

    def __init__(
        self, *, runtime: Any, rows: Sequence[base.BaseRow], rows_v1: Sequence[Any],
        tokenizer: Any, teacher_sources: Sequence[str], contact_uncertainty: Any,
        graph_store: Any, pair_store: Any, target_nodes: Mapping[str, int],
    ) -> None:
        self.runtime = runtime
        self.rows = rows
        self.rows_v1 = rows_v1
        self.tokenizer = tokenizer
        self.teacher_sources = teacher_sources
        self.contact_uncertainty = contact_uncertainty
        self.graph_store = graph_store
        self.pair_store = pair_store
        self.target_nodes = target_nodes
        self.hierarchy: dict[int, float] = {}
        self.bases = {index: np.zeros(3, dtype=np.float32) for index in range(len(rows))}

    def set_hierarchy_weights(self, weights: Mapping[int, float]) -> None:
        self.hierarchy = dict(weights)

    def collate(self, batch_indices: Sequence[int]) -> dict[str, Any]:
        collator = self.runtime.v23.V2Collator(
            self.rows_v1, self.tokenizer, self.bases, self.teacher_sources,
            self.contact_uncertainty, graph_store=self.graph_store,
            pair_store=self.pair_store, target_nodes=self.target_nodes,
        )
        batch = collator(list(batch_indices))
        batch["candidate_ids"] = [self.rows[index].candidate_id for index in batch_indices]
        batch["targets"] = torch.tensor(
            [self.rows[index].targets for index in batch_indices], dtype=torch.float32,
        )
        batch["hierarchy_weights"] = torch.tensor(
            [self.hierarchy[index] for index in batch_indices], dtype=torch.float32,
        )
        batch["marginal_targets"] = batch.pop("contact_targets")
        batch["marginal_mask"] = batch.pop("contact_mask")
        batch["marginal_uncertainty"] = batch.pop("contact_uncertainty")
        batch["marginal_tier_weights"] = torch.tensor([
            base.DEFAULT_TIER_POLICY[self.rows[index].contact_tier]["marginal"]
            for index in batch_indices
        ])
        batch["pair_tier_weights"] = torch.tensor([
            base.DEFAULT_TIER_POLICY[self.rows[index].contact_tier]["pair"]
            for index in batch_indices
        ])
        return batch


def observe_multibatch(
    *, model: torch.nn.Module, rows: Sequence[base.BaseRow],
    manifest: base.SplitManifest, batch_factory: RealBatchFactory,
    target_graphs: Mapping[str, Any], args: Any,
) -> dict[str, Any]:
    require(args.lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}, "calibration_lane_invalid")
    require(args.calibration_only, "calibration_only_required")
    offsets = [int(value) for value in args.calibration_batch_offsets]
    expected_hashes = list(args.expected_calibration_batch_candidate_sha256)
    require(len(offsets) == DEFAULT_BATCH_COUNT, "calibration_offsets_count")
    require(len(set(offsets)) == DEFAULT_BATCH_COUNT, "calibration_offsets_duplicate")
    require(len(expected_hashes) == DEFAULT_BATCH_COUNT, "calibration_expected_hash_count")

    train_indices, _ = manifest.validate(rows, args.fixed_epochs)
    hierarchy, weight_audit = base.source_parent_candidate_weights(rows, train_indices)
    batch_factory.set_hierarchy_weights({
        index: float(hierarchy[local]) for local, index in enumerate(train_indices)
    })
    ordered = list(train_indices)
    random.Random(args.seed).shuffle(ordered)
    expected_offsets = evenly_spaced_complete_batch_offsets(
        len(ordered), args.batch_size, DEFAULT_BATCH_COUNT,
    )
    require(offsets == expected_offsets, "calibration_offsets_not_frozen_even_spacing")

    device = torch.device(args.device)
    model.to(device)
    model.train()
    model.backbone.eval()  # type: ignore[attr-defined]
    target_device = base.move_to_device(target_graphs, device)
    named_parameters = [
        (name, parameter) for name, parameter in model.named_parameters()
        if parameter.requires_grad
    ]
    require(bool(named_parameters), "calibration_trainable_parameters_empty")

    unit_norms = []
    batch_provenance = []
    seen_candidates: set[str] = set()
    for batch_number, (offset, expected_hash) in enumerate(zip(offsets, expected_hashes)):
        start = offset * args.batch_size
        batch_indices = ordered[start:start + args.batch_size]
        require(len(batch_indices) == args.batch_size, f"calibration_batch_not_complete:{offset}")
        candidate_ids = [rows[index].candidate_id for index in batch_indices]
        digest = canonical_candidate_ids_sha256(candidate_ids)
        require(digest == expected_hash, f"calibration_batch_candidate_sha256:{batch_number}")
        require(seen_candidates.isdisjoint(candidate_ids), f"calibration_candidate_reused:{batch_number}")
        seen_candidates.update(candidate_ids)
        batch_id = f"B{batch_number:02d}_OFFSET_{offset:04d}"
        forward_seed = int(args.seed) + 1_000_003 + offset
        torch.manual_seed(forward_seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(forward_seed)
        batch = base.move_to_device(batch_factory.collate(batch_indices), device)
        with torch.autocast(
            device_type=device.type, dtype=torch.bfloat16,
            enabled=args.precision == "bf16" and device.type == "cuda",
        ):
            output = base.forward_lane(model, args.lane, batch, target_device)
            unit_args = SimpleNamespace(**vars(args))
            unit_args.marginal_weight = 1.0
            unit_args.pair_weight = (
                args.pair_to_marginal_ratio if args.lane == "D_SPLIT_PAIR" else 0.0
            )
            _loss, parts = base.compute_loss(output, batch, args.lane, unit_args)
        telemetry = grouped_component_gradient_telemetry(parts, named_parameters)
        scalar_norm = float(telemetry["gradient_l2_norm"]["scalar"])
        contact_norm = float(telemetry["gradient_l2_norm"]["contact"])
        record = {
            "batch_id": batch_id,
            "batch_offset": offset,
            "candidate_ids_sha256": digest,
            "scalar_gradient_l2_norm": scalar_norm,
            "unit_contact_gradient_l2_norm": contact_norm,
            "scalar_contact_cosine": telemetry["scalar_contact_cosine"],
            "parameter_groups": telemetry["parameter_groups"],
        }
        unit_norms.append(record)
        batch_provenance.append({
            "batch_id": batch_id,
            "batch_offset": offset,
            "forward_seed": forward_seed,
            "candidate_ids": candidate_ids,
            "candidate_ids_sha256": digest,
            "candidate_count": len(candidate_ids),
            "teacher_source_counts": dict(Counter(rows[index].teacher_source for index in batch_indices)),
            "contact_tier_counts": dict(Counter(rows[index].contact_tier for index in batch_indices)),
            "parent_framework_clusters": sorted({rows[index].parent for index in batch_indices}),
        })
        del output, parts, batch

    observations, selected = summarize_grid_observations(
        grid=args.calibration_grid,
        per_batch_unit_norms=unit_norms,
        pair_to_marginal_ratio=args.pair_to_marginal_ratio,
        median_band=args.target_gradient_fraction_band,
        maximum_fraction=args.maximum_per_batch_gradient_fraction,
        lane=args.lane,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "lane": args.lane,
        "split": {
            "split_id": manifest.split_id,
            "outer_fold": manifest.outer_fold,
            "fixed_epochs": manifest.fixed_epochs,
            "open_only": manifest.open_only,
            "v4_f_test32_access_count": manifest.v4_f_test32_access_count,
            "train_parent_set_sha256": manifest.train_parent_set_sha256,
        },
        "open_only": True,
        "optimizer_constructed": False,
        "optimizer_steps_before_observation": 0,
        "outer_metrics_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "fixed_grid": [float(value) for value in args.calibration_grid],
        "pair_to_marginal_ratio": float(args.pair_to_marginal_ratio),
        "target_median_gradient_fraction_band": [
            float(value) for value in args.target_gradient_fraction_band
        ],
        "maximum_per_batch_gradient_fraction": float(args.maximum_per_batch_gradient_fraction),
        "selection_rule": SELECTION_RULE,
        "calibration_batch_count": DEFAULT_BATCH_COUNT,
        "calibration_batch_offsets": offsets,
        "calibration_batch_provenance": batch_provenance,
        "observations": observations,
        "selected_contact_weights": selected,
        "source_parent_candidate_weighting": weight_audit,
        "technical_supersession_version": SUPERSESSION_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def parser() -> Any:
    value = base.parser()
    value.description = __doc__
    value.add_argument("--calibration-batch-offsets", type=int, nargs="+", required=True)
    value.add_argument(
        "--expected-calibration-batch-candidate-sha256", nargs="+", required=True,
    )
    value.add_argument(
        "--maximum-per-batch-gradient-fraction", type=float, required=True,
    )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    base.reject_sealed_path(args.output_dir)
    require(not args.tiny_e2e, "real_multibatch_calibration_only")
    require(args.calibration_only, "calibration_only_required")
    require(args.v2_3_bundle_root is not None and args.split_manifest is not None, "real_runtime_arguments_missing")
    require(args.contact_formula_json is not None, "contact_formula_json_required")
    for path in (
        args.training_tsv, args.contact_tsv_gz, args.graph_cache_dir,
        args.target_graph_pt, args.pair_contact_tsv_gz, args.contact_formula_json,
    ):
        base.reject_sealed_path(path)
    runtime = base.V23Runtime(args.v2_3_bundle_root)
    rows, rows_v1, teacher_sources, stores, target_graphs = runtime.load_real_panel(args)
    require(target_graphs is not None, "target_graphs_required")
    contact_uncertainty, graph_store, pair_store = stores
    backbone, tokenizer, hidden, _identity = base.load_backbone(args, runtime)
    config = base.ResidueV24Config(
        backbone_hidden_size=hidden,
        target_node_dim=next(iter(target_graphs.values()))["node_features"].shape[1],
        edge_feature_dim=graph_store.edge_feature_dim,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
    )
    model = base.build_model(args.lane, backbone, config)
    target_nodes = {
        name: len(target_graphs[name]["node_features"]) for name in base.RECEPTOR_NAMES
    }
    batches = RealBatchFactory(
        runtime=runtime, rows=rows, rows_v1=rows_v1, tokenizer=tokenizer,
        teacher_sources=teacher_sources, contact_uncertainty=contact_uncertainty,
        graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
    )
    manifest = base.SplitManifest.from_json(args.split_manifest)
    result = observe_multibatch(
        model=model, rows=rows, manifest=manifest, batch_factory=batches,
        target_graphs=target_graphs, args=args,
    )
    require(not args.output_dir.exists(), "output_dir_exists")
    args.output_dir.mkdir(parents=True)
    base.atomic_json(args.output_dir / "CALIBRATION_OBSERVATION.json", result)
    base.atomic_json(args.output_dir / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MultiBatchCalibrationError, base.BaseTrainerError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V2_4_MULTIBATCH_CALIBRATION:{error}", file=sys.stderr)
        raise SystemExit(1)
