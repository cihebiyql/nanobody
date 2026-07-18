#!/usr/bin/env python3
"""Open-only fixed-epoch base trainer for the V2.4 feature-separated stack.

The trainer emits receptor-explicit M2, neural, and contact evidence.  M2 is
fit as an independent Ridge branch and is never passed to the neural forward.
This prototype deliberately performs no same-fold hyperparameter selection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import random
import stat
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch.optim import AdamW


HERE = Path(__file__).resolve()
MODEL_DIR = HERE.parents[1] / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))
from residue_model_v2_4 import (  # noqa: E402
    FeatureSeparatedResidueSurrogate,
    FeatureSeparatedTargetHead,
    M2FreeVHHOnlyHead,
    M2FreeVHHOnlySurrogate,
    RECEPTOR_NAMES,
    ResidueV24Config,
)


SCHEMA_VERSION = "pvrig_v2_4_open_base_split_trainer_v1"
SPLIT_SCHEMA = "pvrig_v2_4_open_base_split_manifest_v1"
LANES = (
    "A_VHH_ONLY",
    "B_TARGET_NO_CONTACT",
    "C_SPLIT_MARGINAL",
    "D_SPLIT_PAIR",
)
CONTACT_TIERS = ("A", "B", "C")
CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking "
    "geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
DEFAULT_TIER_POLICY = {
    "A": {"scalar": 1.0, "marginal": 1.0, "pair": 1.0},
    "B": {"scalar": 1.0, "marginal": 0.5, "pair": 0.25},
    "C": {"scalar": 1.0, "marginal": 0.1, "pair": 0.0},
}
CONTACT_FORMULA_VERSION = "pvrig_v2_4_contact_composite_v1_equal_weight_preregistered"
CONTACT_FORMULA_SHA256 = "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7"
CONTACT_FORMULA_WEIGHTS = {"hotspot_contact_mass": 0.5, "interface_specificity": 0.5}
BUILTIN_TINY_CONTACT_FORMULA = HERE.parents[1] / "contact_contract" / "contact_score_formula_v1.json"


class BaseTrainerError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BaseTrainerError(message)


def require_finite(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_parent_set_sha256(parents: Iterable[str]) -> str:
    payload = "".join(f"{parent}\n" for parent in sorted(set(parents))).encode()
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def reject_sealed_path(path: Path | None) -> None:
    if path is None:
        return
    normalized = str(path).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, f"sealed_path_forbidden:{path}")


def load_contact_formula(path: Path) -> dict[str, Any]:
    reject_sealed_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise BaseTrainerError(f"contact_formula_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"contact_formula_not_regular_or_symlink:{path}")
    observed_sha256 = sha256_file(path)
    require(observed_sha256 == CONTACT_FORMULA_SHA256, f"contact_formula_sha256:{observed_sha256}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaseTrainerError(f"contact_formula_invalid_json:{path}") from exc
    require(isinstance(payload, dict), "contact_formula_not_object")
    require(payload.get("formula_version") == CONTACT_FORMULA_VERSION, "contact_formula_version")
    require(payload.get("receptors") == ["R8", "R9"], "contact_formula_receptors")
    require(
        payload.get("inputs_per_receptor") == ["hotspot_contact_mass", "interface_specificity"],
        "contact_formula_inputs",
    )
    weights = payload.get("weights")
    require(isinstance(weights, dict), "contact_formula_weights_not_object")
    require(set(weights) == set(CONTACT_FORMULA_WEIGHTS), "contact_formula_weight_keys")
    for name, expected in CONTACT_FORMULA_WEIGHTS.items():
        require(float(weights[name]) == expected, f"contact_formula_weight:{name}")
    require(float(payload.get("intercept")) == 0.0, "contact_formula_intercept")
    require(payload.get("clipping") is False, "contact_formula_clipping")
    require(payload.get("label_access") is False, "contact_formula_label_access")
    require(payload.get("outer_result_tuning") is False, "contact_formula_outer_result_tuning")
    return {
        "path": str(path.resolve()),
        "sha256": observed_sha256,
        "formula_version": CONTACT_FORMULA_VERSION,
        "weights": dict(CONTACT_FORMULA_WEIGHTS),
        "raw_bytes": path.read_bytes(),
    }


def resolve_contact_formula(args: argparse.Namespace) -> dict[str, Any]:
    configured = getattr(args, "contact_formula_json", None)
    if configured is None:
        require(bool(getattr(args, "tiny_e2e", False)), "contact_formula_json_required_for_real_mode")
        configured = BUILTIN_TINY_CONTACT_FORMULA
    return load_contact_formula(Path(configured))


@dataclass(frozen=True)
class BaseRow:
    candidate_id: str
    sequence: str
    sequence_sha256: str
    parent: str
    teacher_source: str
    targets: tuple[float, float]
    structure: tuple[float, ...]
    contact_tier: str

    def validate(self) -> None:
        require(self.candidate_id != "" and self.parent != "" and self.teacher_source != "", "row_identity_blank")
        require(hashlib.sha256(self.sequence.encode()).hexdigest() == self.sequence_sha256, f"sequence_hash:{self.candidate_id}")
        require(len(self.targets) == 2 and all(math.isfinite(value) for value in self.targets), f"target_invalid:{self.candidate_id}")
        require(self.structure and all(math.isfinite(value) for value in self.structure), f"structure_invalid:{self.candidate_id}")
        require(self.contact_tier in CONTACT_TIERS, f"contact_tier_invalid:{self.candidate_id}")


@dataclass(frozen=True)
class SplitManifest:
    split_id: str
    outer_fold: int
    train_parents: tuple[str, ...]
    score_parents: tuple[str, ...]
    fixed_epochs: int
    open_only: bool
    v4_f_test32_access_count: int
    train_parent_set_sha256: str
    score_parent_set_sha256: str

    @classmethod
    def from_json(cls, path: Path) -> "SplitManifest":
        reject_sealed_path(path)
        payload = json.loads(path.read_text())
        require(payload.get("schema_version") == SPLIT_SCHEMA, "split_manifest_schema")
        return cls(
            split_id=str(payload["split_id"]),
            outer_fold=int(payload["outer_fold"]),
            train_parents=tuple(str(value) for value in payload["train_parents"]),
            score_parents=tuple(str(value) for value in payload["score_parents"]),
            fixed_epochs=int(payload["fixed_epochs"]),
            open_only=bool(payload["open_only"]),
            v4_f_test32_access_count=int(payload["v4_f_test32_access_count"]),
            train_parent_set_sha256=str(payload["train_parent_set_sha256"]),
            score_parent_set_sha256=str(payload["score_parent_set_sha256"]),
        )

    def validate(self, rows: Sequence[BaseRow], expected_epochs: int) -> tuple[list[int], list[int]]:
        require(self.open_only and self.v4_f_test32_access_count == 0, "split_not_open_only")
        require(self.fixed_epochs == expected_epochs and self.fixed_epochs > 0, "fixed_epoch_contract")
        require(len(self.train_parents) == len(set(self.train_parents)), "train_parent_duplicate")
        require(len(self.score_parents) == len(set(self.score_parents)), "score_parent_duplicate")
        train_set, score_set = set(self.train_parents), set(self.score_parents)
        require(train_set and score_set and train_set.isdisjoint(score_set), "split_parent_overlap")
        require(canonical_parent_set_sha256(train_set) == self.train_parent_set_sha256, "train_parent_hash")
        require(canonical_parent_set_sha256(score_set) == self.score_parent_set_sha256, "score_parent_hash")
        observed = {row.parent for row in rows}
        require(observed == train_set | score_set, "split_parent_exact_closure")
        train = [index for index, row in enumerate(rows) if row.parent in train_set]
        score = [index for index, row in enumerate(rows) if row.parent in score_set]
        require(train and score, "split_empty")
        return train, score


@dataclass(frozen=True)
class RidgeState:
    x_mean: np.ndarray
    x_scale: np.ndarray
    y_mean: np.ndarray
    coefficient: np.ndarray
    alpha: float


def fit_weighted_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> RidgeState:
    require(x.ndim == 2 and y.shape == (len(x), 2), "ridge_shape")
    require(weights.shape == (len(x),) and np.all(weights > 0) and alpha > 0, "ridge_weight_or_alpha")
    normalized = weights / weights.sum()
    x_mean = np.sum(x * normalized[:, None], axis=0)
    x_scale = np.sqrt(np.sum((x - x_mean) ** 2 * normalized[:, None], axis=0))
    x_scale[x_scale < 1e-8] = 1.0
    y_mean = np.sum(y * normalized[:, None], axis=0)
    xs = (x - x_mean) / x_scale
    root = np.sqrt(weights)[:, None]
    gram = (xs * root).T @ (xs * root)
    rhs = (xs * root).T @ ((y - y_mean) * root)
    coefficient = np.linalg.solve(gram + alpha * np.eye(x.shape[1]), rhs)
    require(bool(np.all(np.isfinite(coefficient))), "ridge_nonfinite")
    return RidgeState(x_mean, x_scale, y_mean, coefficient, float(alpha))


def predict_ridge(state: RidgeState, x: np.ndarray) -> np.ndarray:
    result = (x - state.x_mean) / state.x_scale @ state.coefficient + state.y_mean
    require(result.ndim == 2 and result.shape[1] == 2 and bool(np.all(np.isfinite(result))), "ridge_prediction_nonfinite")
    return result


def source_parent_candidate_weights(rows: Sequence[BaseRow], indices: Sequence[int]) -> tuple[np.ndarray, dict[str, Any]]:
    selected = [rows[index] for index in indices]
    sources = sorted({row.teacher_source for row in selected})
    require(len(sources) == 2, f"expected_two_sources:{sources}")
    weights = np.zeros(len(selected), dtype=np.float64)
    audit: dict[str, Any] = {}
    for source in sources:
        parent_map: dict[str, list[int]] = {}
        for local_index, row in enumerate(selected):
            if row.teacher_source == source:
                parent_map.setdefault(row.parent, []).append(local_index)
        require(parent_map, f"source_empty:{source}")
        for parent, members in parent_map.items():
            weights[members] = 0.5 / len(parent_map) / len(members)
        audit[source] = {
            "parents": len(parent_map),
            "candidates": sum(len(value) for value in parent_map.values()),
            "mass": float(weights[[i for value in parent_map.values() for i in value]].sum()),
        }
    require(np.isclose(weights.sum(), 1.0, atol=1e-12), "hierarchical_weight_sum")
    return weights, {
        "contract": "0.5/source -> equal parent -> equal candidate",
        "sources": audit,
        "sum": float(weights.sum()),
    }


class TinyBackbone(nn.Module):
    def __init__(self, vocab_size: int = 32, hidden_size: int = 12) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, hidden_size)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Any:
        del attention_mask
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids))


class V23Runtime:
    """Read-only adapter around the frozen V2.3 loader/graph/contact utilities."""

    def __init__(self, bundle_root: Path) -> None:
        reject_sealed_path(bundle_root)
        v1_src = bundle_root / "residue_v1" / "src"
        v2_src = bundle_root / "residue_v2" / "src"
        require(v1_src.is_dir() and v2_src.is_dir(), "v2_3_bundle_source_missing")
        for path in (v1_src, v2_src):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        self.v1 = importlib.import_module("train_nested_residue_surrogate")
        self.v23 = importlib.import_module("train_nested_residue_surrogate_v2")

    def load_frozen_backbone(self, args: argparse.Namespace) -> tuple[nn.Module, Any, int, str]:
        return self.v23.load_frozen_backbone(args)

    def load_real_panel(self, args: argparse.Namespace) -> tuple[list[BaseRow], Any, Any, Any, Mapping[str, Any] | None]:
        rows_v1, _feature_names, _audit = self.v1.read_training_table(
            args.training_tsv,
            args.contact_tsv_gz,
            structure_prefixes=args.structure_prefix,
            structure_dim=args.structure_dim,
        )
        with args.training_tsv.open(newline="", encoding="utf-8-sig") as handle:
            metadata = {row["candidate_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
        teacher_sources = [metadata[row.candidate_id]["teacher_source"] for row in rows_v1]
        base_rows = []
        for row in rows_v1:
            tier = development_contact_tier(metadata[row.candidate_id])
            base_rows.append(BaseRow(
                row.candidate_id,
                row.sequence,
                row.sequence_sha256,
                row.parent,
                metadata[row.candidate_id]["teacher_source"],
                (float(row.targets[0]), float(row.targets[1])),
                tuple(float(value) for value in row.structure),
                str(tier),
            ))
        contact_uncertainty = self.v23.load_contact_uncertainty(args.contact_tsv_gz, rows_v1)
        graph_store = self.v23.GraphCacheStore(args.graph_cache_dir, rows_v1)
        target_graphs = None
        if args.lane != "A_VHH_ONLY":
            target_graphs = self.v23.load_target_graphs(args.target_graph_pt, graph_store.edge_feature_dim)
        target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES} if target_graphs else {}
        pair_store = self.v23.PairTargetStore(args.pair_contact_tsv_gz, rows_v1, target_nodes) if args.lane == "D_SPLIT_PAIR" else None
        return base_rows, rows_v1, teacher_sources, (contact_uncertainty, graph_store, pair_store), target_graphs


def development_contact_tier(metadata: Mapping[str, str]) -> str:
    """Read the canonical development tier without silently coercing to C."""
    value = ""
    for field in (
        "development_reliability_tier",
        "contact_reliability_tier",
        "contact_tier",
        "docking_evidence_tier",
    ):
        observed = str(metadata.get(field) or "").strip().upper()
        if observed:
            value = observed
            break
    aliases = {
        "A": "A",
        "TIER_A": "A",
        "DUAL_3_SEED": "A",
        "B": "B",
        "TIER_B": "B",
        "DUAL_2_SEED": "B",
        "C": "C",
        "TIER_C": "C",
        "DUAL_1_SEED": "C",
    }
    require(value in aliases, f"development_reliability_tier_missing_or_invalid:{value or 'BLANK'}")
    return aliases[value]


def load_backbone(args: argparse.Namespace, runtime: V23Runtime | Any | None) -> tuple[nn.Module, Any, int, str]:
    if args.backbone_kind == "tiny":
        backbone = TinyBackbone(hidden_size=args.tiny_hidden_size)
        for parameter in backbone.parameters():
            parameter.requires_grad_(False)
        return backbone, None, args.tiny_hidden_size, "tiny_synthetic"
    require(runtime is not None, "v2_3_runtime_required_for_hf")
    reject_sealed_path(args.model_path)
    require(args.model_path is not None and args.model_path.is_dir(), "hf_model_path_missing")
    require(args.model_identity_file is not None and args.model_identity_file.is_file(), "hf_identity_file_missing")
    backbone, tokenizer, hidden, identity = runtime.load_frozen_backbone(args)
    require(not any(parameter.requires_grad for parameter in backbone.parameters()), "hf_backbone_not_frozen")
    return backbone, tokenizer, int(hidden), str(identity)


def build_model(lane: str, backbone: nn.Module, config: ResidueV24Config) -> nn.Module:
    require(lane in LANES, "lane_invalid")
    if lane == "A_VHH_ONLY":
        return M2FreeVHHOnlySurrogate(backbone, M2FreeVHHOnlyHead(config))
    return FeatureSeparatedResidueSurrogate(backbone, FeatureSeparatedTargetHead(config))


def forward_lane(model: nn.Module, lane: str, batch: Mapping[str, Any], target_graphs: Mapping[str, Any] | None) -> dict[str, Tensor]:
    common = {
        "input_ids": batch["input_ids"],
        "attention_mask": batch["attention_mask"],
        "residue_mask": batch["residue_mask"],
        "vhh_aa_index": batch["vhh_aa_index"],
        "vhh_region_index": batch["vhh_region_index"],
        "vhh_confidence": batch["vhh_confidence"],
        "vhh_edge_index": batch["vhh_edge_index"],
        "vhh_edge_features": batch["vhh_edge_features"],
    }
    # Deliberately never forward batch['structure'] or batch['m2_base'].
    if lane == "A_VHH_ONLY":
        return model(**common)
    require(target_graphs is not None, "target_graph_required")
    return model(**common, target_graphs=target_graphs)


def _weighted_mean(values: Tensor, weights: Tensor) -> Tensor:
    require(values.shape == weights.shape, "weighted_mean_shape")
    return (values * weights).sum() / weights.sum().clamp_min(torch.finfo(values.dtype).eps)


def balanced_soft_bce_per_candidate_receptor(
    logits: Tensor,
    targets: Tensor,
    uncertainty_weights: Tensor,
    mask: Tensor,
    *,
    positive_class_fraction: float = 0.5,
    epsilon: float = 1e-8,
) -> tuple[Tensor, Tensor]:
    """V2.3-compatible candidate/receptor positive-negative mass balance."""
    require(logits.shape == targets.shape == uncertainty_weights.shape == mask.shape, "contact_shape")
    require(logits.ndim >= 2, "contact_rank")
    require(0.0 < positive_class_fraction < 1.0 and epsilon > 0.0, "contact_balance_contract")
    require_finite(logits, "contact_logits_nonfinite")
    require_finite(targets, "contact_targets_nonfinite")
    require_finite(uncertainty_weights, "contact_uncertainty_nonfinite")
    require(bool(torch.all((targets >= 0.0) & (targets <= 1.0))), "contact_target_range")
    require(bool(torch.all(uncertainty_weights >= 0.0)), "contact_uncertainty_negative")
    flat_logits = logits.reshape(len(logits), -1)
    flat_targets = targets.to(logits.dtype).reshape(len(logits), -1)
    flat_weights = (uncertainty_weights.to(logits.dtype) * mask.to(logits.dtype)).reshape(len(logits), -1)
    positive_weights = flat_weights * flat_targets
    negative_weights = flat_weights * (1.0 - flat_targets)
    positive_mass = positive_weights.sum(1)
    negative_mass = negative_weights.sum(1)
    has_positive = positive_mass > epsilon
    has_negative = negative_mass > epsilon
    positive_mean = (F.softplus(-flat_logits) * positive_weights).sum(1) / positive_mass.clamp_min(epsilon)
    negative_mean = (F.softplus(flat_logits) * negative_weights).sum(1) / negative_mass.clamp_min(epsilon)
    both = has_positive & has_negative
    result = torch.zeros_like(positive_mean)
    result = torch.where(
        both,
        positive_class_fraction * positive_mean + (1.0 - positive_class_fraction) * negative_mean,
        result,
    )
    result = torch.where(has_positive & ~has_negative, positive_mean, result)
    result = torch.where(has_negative & ~has_positive, negative_mean, result)
    return result, has_positive | has_negative


def _mean_receptor_losses(values: Sequence[Tensor], availability: Sequence[Tensor]) -> tuple[Tensor, Tensor]:
    require(len(values) == len(availability) == 2, "contact_receptor_count")
    stacked_values = torch.stack(tuple(values), dim=1)
    stacked_available = torch.stack(tuple(availability), dim=1)
    weights = stacked_available.to(stacked_values.dtype)
    result = (stacked_values * weights).sum(1) / weights.sum(1).clamp_min(1.0)
    return result, stacked_available.all(1)


def compute_loss(
    output: Mapping[str, Tensor],
    batch: Mapping[str, Any],
    lane: str,
    args: argparse.Namespace,
) -> tuple[Tensor, dict[str, Tensor]]:
    prediction = output["receptor_predictions"]
    target = batch["targets"]
    require_finite(prediction, "receptor_prediction_nonfinite")
    exact_dual = output["exact_min_dual"]
    target_dual = target.min(dim=1).values
    receptor_per = F.smooth_l1_loss(prediction, target, reduction="none", beta=args.huber_delta).mean(1)
    dual_per = F.smooth_l1_loss(exact_dual, target_dual, reduction="none", beta=args.huber_delta)
    hierarchy = batch["hierarchy_weights"].to(prediction.dtype)
    scalar = _weighted_mean(args.receptor_weight * receptor_per + args.dual_weight * dual_per, hierarchy)
    parts: dict[str, Tensor] = {"scalar": scalar}

    contact_terms = []
    if lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}:
        marginal_values, marginal_available = [], []
        for receptor_index in range(2):
            values, available = balanced_soft_bce_per_candidate_receptor(
                output["marginal_contact_logits"][..., receptor_index],
                batch["marginal_targets"][..., receptor_index],
                batch["marginal_uncertainty"][..., receptor_index],
                batch["marginal_mask"][..., receptor_index],
            )
            marginal_values.append(values)
            marginal_available.append(available)
        marginal_per, available = _mean_receptor_losses(marginal_values, marginal_available)
        tier = batch["marginal_tier_weights"].to(prediction.dtype)
        active = hierarchy * tier * available.to(prediction.dtype)
        marginal = _weighted_mean(marginal_per, active) if bool(torch.any(active > 0)) else scalar * 0.0
        parts["marginal"] = marginal
        contact_terms.append(args.marginal_weight * marginal)
    if lane == "D_SPLIT_PAIR":
        receptor_values = []
        receptor_available = []
        for receptor in RECEPTOR_NAMES:
            values, available = balanced_soft_bce_per_candidate_receptor(
                output[f"contact_logits_{receptor}"],
                batch[f"pair_targets_{receptor}"],
                batch[f"pair_uncertainty_{receptor}"],
                batch[f"pair_mask_{receptor}"],
            )
            receptor_values.append(values)
            receptor_available.append(available)
        pair_per, pair_available = _mean_receptor_losses(receptor_values, receptor_available)
        tier = batch["pair_tier_weights"].to(prediction.dtype)
        active = hierarchy * tier * pair_available.to(prediction.dtype)
        pair = _weighted_mean(pair_per, active) if bool(torch.any(active > 0)) else scalar * 0.0
        parts["pair"] = pair
        contact_terms.append(args.pair_weight * pair)
    contact = torch.stack(contact_terms).sum() if contact_terms else scalar * 0.0
    parts["contact"] = contact
    total = scalar + contact
    require_finite(total, "total_loss_nonfinite")
    parts["total"] = total
    return total, parts


def component_gradient_telemetry(parts: Mapping[str, Tensor], parameters: Sequence[Tensor]) -> dict[str, Any]:
    components = {name: parts[name] for name in ("scalar", "contact")}
    gradients: dict[str, tuple[Tensor | None, ...]] = {}
    norms: dict[str, float] = {}
    for name, value in components.items():
        gradients[name] = torch.autograd.grad(value, tuple(parameters), retain_graph=True, allow_unused=True)
        squared = torch.zeros((), dtype=torch.float64, device=value.device)
        for gradient in gradients[name]:
            if gradient is not None:
                require_finite(gradient, f"telemetry_gradient_nonfinite:{name}")
                squared = squared + gradient.detach().double().square().sum()
        norms[name] = float(torch.sqrt(squared).cpu())
    dot = torch.zeros((), dtype=torch.float64, device=parts["scalar"].device)
    for left, right in zip(gradients["scalar"], gradients["contact"]):
        if left is not None and right is not None:
            dot = dot + (left.detach().double() * right.detach().double()).sum()
    denominator = norms["scalar"] * norms["contact"]
    cosine = float(dot.cpu()) / denominator if denominator > 0.0 else None
    require(cosine is None or math.isfinite(cosine), "telemetry_cosine_nonfinite")
    return {"gradient_l2_norm": norms, "scalar_contact_cosine": cosine}


def assert_gradients_finite(parameters: Sequence[Tensor]) -> None:
    for index, parameter in enumerate(parameters):
        if parameter.grad is not None:
            require_finite(parameter.grad, f"gradient_nonfinite:{index}")


def assert_optimizer_finite(optimizer: AdamW, parameters: Sequence[Tensor]) -> None:
    for index, parameter in enumerate(parameters):
        require_finite(parameter, f"parameter_nonfinite:{index}")
    for parameter_index, state in enumerate(optimizer.state.values()):
        for name, value in state.items():
            if isinstance(value, Tensor):
                require_finite(value, f"optimizer_state_nonfinite:{parameter_index}:{name}")


BatchFactory = Callable[[Sequence[int], bool, int], Iterable[Mapping[str, Any]]]


def move_to_device(value: Any, device: torch.device) -> Any:
    if isinstance(value, Tensor):
        return value.to(device)
    if isinstance(value, Mapping):
        return {key: move_to_device(item, device) for key, item in value.items()}
    return value


def train_fixed_epochs(
    model: nn.Module,
    lane: str,
    train_indices: Sequence[int],
    batch_factory: BatchFactory,
    target_graphs: Mapping[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    device = torch.device(args.device)
    require(args.gradient_accumulation >= 1, "gradient_accumulation_invalid")
    model.to(device)
    target_device = move_to_device(target_graphs, device) if target_graphs is not None else None
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = AdamW(parameters, lr=args.learning_rate, weight_decay=args.weight_decay)
    telemetry = None
    step_count = 0
    for epoch in range(args.fixed_epochs):
        model.train()
        model.backbone.eval()  # type: ignore[attr-defined]
        optimizer.zero_grad(set_to_none=True)
        batches = list(batch_factory(train_indices, True, epoch))
        require(bool(batches), "training_batches_empty")
        for batch_index, raw_batch in enumerate(batches):
            batch = move_to_device(raw_batch, device)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.bfloat16,
                enabled=args.precision == "bf16" and device.type == "cuda",
            ):
                output = forward_lane(model, lane, batch, target_device)
                loss, parts = compute_loss(output, batch, lane, args)
            if telemetry is None:
                telemetry = component_gradient_telemetry(parts, parameters)
            (loss / args.gradient_accumulation).backward()
            assert_gradients_finite(parameters)
            should_step = (batch_index + 1) % args.gradient_accumulation == 0 or batch_index + 1 == len(batches)
            if should_step:
                torch.nn.utils.clip_grad_norm_(parameters, args.gradient_clip, error_if_nonfinite=True)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                assert_optimizer_finite(optimizer, parameters)
                step_count += 1
    require(telemetry is not None, "telemetry_missing")
    return {"fixed_epochs": args.fixed_epochs, "optimizer_steps": step_count, "component_gradient": telemetry}


def observe_prestep_contact_gradient_grid(
    model: nn.Module,
    lane: str,
    rows: Sequence[BaseRow],
    manifest: SplitManifest,
    batch_factory: BatchFactory,
    target_graphs: Mapping[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Observe the frozen contact-weight grid before constructing an optimizer."""
    require(lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}, "calibration_lane_must_have_contact_supervision")
    grid = tuple(float(value) for value in args.calibration_grid)
    require(grid and list(grid) == sorted(set(grid)) and all(value > 0 for value in grid), "calibration_grid_invalid")
    lower, upper = (float(value) for value in args.target_gradient_fraction_band)
    require(0 <= lower <= upper <= 1, "calibration_gradient_fraction_band_invalid")
    require(0 < args.pair_to_marginal_ratio <= 1, "calibration_pair_ratio_invalid")
    train_indices, _ = manifest.validate(rows, args.fixed_epochs)
    train_weights, weight_audit = source_parent_candidate_weights(rows, train_indices)
    hierarchy_by_global = {index: float(train_weights[local]) for local, index in enumerate(train_indices)}
    if hasattr(batch_factory, "set_hierarchy_weights"):
        batch_factory.set_hierarchy_weights(hierarchy_by_global)  # type: ignore[attr-defined]

    device = torch.device(args.device)
    model.to(device)
    model.train()
    model.backbone.eval()  # type: ignore[attr-defined]
    target_device = move_to_device(target_graphs, device) if target_graphs is not None else None
    raw_batch = next(iter(batch_factory(train_indices, True, 0)), None)
    require(raw_batch is not None, "calibration_training_batch_missing")
    batch = move_to_device(raw_batch, device)
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    with torch.autocast(
        device_type=device.type,
        dtype=torch.bfloat16,
        enabled=args.precision == "bf16" and device.type == "cuda",
    ):
        output = forward_lane(model, lane, batch, target_device)
        observations = []
        for marginal_weight in grid:
            trial_args = SimpleNamespace(**vars(args))
            trial_args.marginal_weight = marginal_weight
            trial_args.pair_weight = (
                marginal_weight * args.pair_to_marginal_ratio
                if lane == "D_SPLIT_PAIR" else 0.0
            )
            _loss, parts = compute_loss(output, batch, lane, trial_args)
            telemetry = component_gradient_telemetry(parts, parameters)
            scalar_norm = float(telemetry["gradient_l2_norm"]["scalar"])
            contact_norm = float(telemetry["gradient_l2_norm"]["contact"])
            denominator = scalar_norm + contact_norm
            fraction = contact_norm / denominator if denominator > 0 else 0.0
            require(math.isfinite(fraction), "calibration_gradient_fraction_nonfinite")
            observations.append({
                "marginal_weight": marginal_weight,
                "pair_weight": trial_args.pair_weight,
                "scalar_gradient_l2_norm": scalar_norm,
                "contact_gradient_l2_norm": contact_norm,
                "contact_gradient_fraction": fraction,
                "scalar_contact_cosine": telemetry["scalar_contact_cosine"],
            })
    eligible = [item for item in observations if lower <= item["contact_gradient_fraction"] <= upper]
    require(bool(eligible), "calibration_no_grid_value_in_target_band")
    selected = min(eligible, key=lambda item: item["marginal_weight"])
    return {
        "schema_version": "pvrig_v2_4_open_only_prestep_gradient_observation_v1",
        "status": "PASS_OPEN_ONLY_PRESTEP_CONTACT_GRADIENT_LANE_OBSERVATION_V2_4",
        "lane": lane,
        "split": asdict(manifest),
        "open_only": True,
        "optimizer_constructed": False,
        "optimizer_steps_before_observation": 0,
        "outer_metrics_access_count": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "fixed_grid": list(grid),
        "pair_to_marginal_ratio": float(args.pair_to_marginal_ratio),
        "target_gradient_fraction_band": [lower, upper],
        "selection_rule": "smallest_grid_value_in_target_band_before_optimizer_construction",
        "selected_contact_weights": {
            "marginal": selected["marginal_weight"],
            "pair": selected["pair_weight"],
        },
        "observations": observations,
        "source_parent_candidate_weighting": weight_audit,
        "observed_training_batch_candidate_ids": list(raw_batch["candidate_ids"]),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def score_model(
    model: nn.Module,
    lane: str,
    indices: Sequence[int],
    batch_factory: BatchFactory,
    target_graphs: Mapping[str, Any] | None,
    device_name: str,
) -> dict[str, dict[str, float]]:
    device = torch.device(device_name)
    model.eval()
    target_device = move_to_device(target_graphs, device) if target_graphs is not None else None
    records: dict[str, dict[str, float]] = {}
    with torch.no_grad():
        for raw_batch in batch_factory(indices, False, 0):
            batch = move_to_device(raw_batch, device)
            output = forward_lane(model, lane, batch, target_device)
            receptor = output["receptor_predictions"].float().cpu().numpy()
            dual = output["exact_min_dual"].float().cpu().numpy()
            if lane == "A_VHH_ONLY":
                marginal = output["marginal_contact_probabilities"].float()
                denominator = batch["residue_mask"].sum(1, keepdim=True).clamp_min(1).float().cpu()
                contact = (marginal.cpu().sum(1) / denominator).numpy()
            else:
                summary = output["pair_summary"].float().cpu().numpy()
                contact = np.stack(
                    (0.5 * (summary[:, 0] + summary[:, 1]), 0.5 * (summary[:, 6] + summary[:, 7])),
                    axis=1,
                )
            for item, candidate in enumerate(raw_batch["candidate_ids"]):
                require(abs(float(dual[item]) - min(float(receptor[item, 0]), float(receptor[item, 1]))) <= 1e-7, "score_exact_min")
                records[str(candidate)] = {
                    "neural_R8": float(receptor[item, 0]),
                    "neural_R9": float(receptor[item, 1]),
                    "neural_Rdual": float(dual[item]),
                    "contact_score_R8": float(contact[item, 0]),
                    "contact_score_R9": float(contact[item, 1]),
                }
    require(len(records) == len(indices), "score_candidate_closure")
    return records


def run_base_split(
    rows: Sequence[BaseRow],
    manifest: SplitManifest,
    model: nn.Module,
    batch_factory: BatchFactory,
    target_graphs: Mapping[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    require(args.lane in LANES, "lane_invalid")
    formula_receipt = resolve_contact_formula(args)
    for row in rows:
        row.validate()
    require(len({row.candidate_id for row in rows}) == len(rows), "candidate_duplicate")
    train_indices, score_indices = manifest.validate(rows, args.fixed_epochs)
    train_weights, weight_audit = source_parent_candidate_weights(rows, train_indices)
    hierarchy_by_global = {index: float(train_weights[local]) for local, index in enumerate(train_indices)}
    # The batch factory receives the exact frozen weights without exposing M2.
    if hasattr(batch_factory, "set_hierarchy_weights"):
        batch_factory.set_hierarchy_weights(hierarchy_by_global)  # type: ignore[attr-defined]

    x = np.asarray([rows[index].structure for index in train_indices], dtype=np.float64)
    y = np.asarray([rows[index].targets for index in train_indices], dtype=np.float64)
    ridge = fit_weighted_ridge(x, y, train_weights, args.ridge_alpha)
    score_x = np.asarray([rows[index].structure for index in score_indices], dtype=np.float64)
    m2 = predict_ridge(ridge, score_x)

    training = train_fixed_epochs(model, args.lane, train_indices, batch_factory, target_graphs, args)
    neural = score_model(model, args.lane, score_indices, batch_factory, target_graphs, args.device)
    output_dir = args.output_dir
    require(not output_dir.exists(), "output_dir_exists")
    output_dir.mkdir(parents=True)
    formula_artifact_path = output_dir / "contact_score_formula_v1.json"
    atomic_bytes(formula_artifact_path, formula_receipt.pop("raw_bytes"))
    require(sha256_file(formula_artifact_path) == formula_receipt["sha256"], "contact_formula_artifact_hash")
    m2_path = output_dir / "m2_ridge.json"
    atomic_json(m2_path, {
        "schema_version": "pvrig_v2_4_independent_m2_ridge_v1",
        "alpha": ridge.alpha,
        "x_mean": ridge.x_mean.tolist(),
        "x_scale": ridge.x_scale.tolist(),
        "y_mean": ridge.y_mean.tolist(),
        "coefficient": ridge.coefficient.tolist(),
        "direct_targets": ["R_8X6B", "R_9E6Y"],
        "training_parent_set_sha256": manifest.train_parent_set_sha256,
        "neural_input": False,
    })
    checkpoint_path = output_dir / "neural_head.pt"
    head_state = {
        name: parameter.detach().cpu().clone()
        for name, parameter in model.named_parameters()
        if parameter.requires_grad
    }
    require(head_state and all(name.startswith("head.") for name in head_state), "head_checkpoint_contract")
    atomic_torch_save(checkpoint_path, {
        "schema_version": "pvrig_v2_4_open_base_head_checkpoint_v1",
        "lane": args.lane,
        "head_state": head_state,
        "training_parent_set_sha256": manifest.train_parent_set_sha256,
        "claim_boundary": CLAIM_BOUNDARY,
    })
    component_path = output_dir / "component_receipts.json"
    formula_applied = args.lane != "A_VHH_ONLY"
    contact_component_role = (
        "stack_eligible_pvrig_contact_composite"
        if formula_applied else "diagnostic_non_stack_vhh_marginal_mean"
    )
    atomic_json(component_path, {
        "schema_version": "pvrig_v2_4_open_base_component_receipts_v2",
        "lane": args.lane,
        "training_parent_set_sha256": manifest.train_parent_set_sha256,
        "m2_ridge_sha256": sha256_file(m2_path),
        "neural_head_sha256": sha256_file(checkpoint_path),
        "contact_formula_receipt": {
            **formula_receipt,
            "artifact_path": formula_artifact_path.name,
            "artifact_sha256": sha256_file(formula_artifact_path),
            "applied_to_lane": formula_applied,
        },
        "contact_score_component": {
            "role": contact_component_role,
            "stack_eligible": formula_applied,
            "R8": (
                "0.5*(pair_summary[0]_hotspot_contact_mass+pair_summary[1]_interface_specificity)"
                if formula_applied else "mean marginal probability over valid VHH residues; diagnostic only"
            ),
            "R9": (
                "0.5*(pair_summary[6]_hotspot_contact_mass+pair_summary[7]_interface_specificity)"
                if formula_applied else "mean marginal probability over valid VHH residues; diagnostic only"
            ),
        },
        "contact_loss_normalization": "per_candidate_per_receptor_soft_positive_negative_balanced_then_hierarchical_weighted",
        "contact_uncertainty_used": True,
        "contact_tier_policy": DEFAULT_TIER_POLICY,
        "component_gradient": training["component_gradient"],
    })
    base_model_receipt_sha256 = sha256_file(component_path)
    prediction_path = output_dir / "base_score_predictions.tsv"
    fields = [
        "candidate_id", "teacher_source", "parent_framework_cluster", "split_id", "lane",
        "truth_R8", "truth_R9", "truth_Rdual", "M2_R8", "M2_R9", "M2_Rdual",
        "neural_R8", "neural_R9", "neural_Rdual", "contact_score_R8", "contact_score_R9",
        "contact_score_role", "contact_score_formula_sha256",
        "base_training_parent_set_sha256", "base_training_parent_count", "base_model_receipt_sha256",
    ]
    with prediction_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for local, index in enumerate(score_indices):
            row = rows[index]
            values = neural[row.candidate_id]
            writer.writerow({
                "candidate_id": row.candidate_id,
                "teacher_source": row.teacher_source,
                "parent_framework_cluster": row.parent,
                "split_id": manifest.split_id,
                "lane": args.lane,
                "truth_R8": row.targets[0],
                "truth_R9": row.targets[1],
                "truth_Rdual": min(row.targets),
                "M2_R8": m2[local, 0],
                "M2_R9": m2[local, 1],
                "M2_Rdual": min(m2[local]),
                **values,
                "contact_score_role": contact_component_role,
                "contact_score_formula_sha256": formula_receipt["sha256"] if formula_applied else "",
                "base_training_parent_set_sha256": manifest.train_parent_set_sha256,
                "base_training_parent_count": len(manifest.train_parents),
                "base_model_receipt_sha256": base_model_receipt_sha256,
            })
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_OPEN_BASE_SPLIT_COMPLETE",
        "lane": args.lane,
        "split": asdict(manifest),
        "fixed_epoch_selection": "NONE_FIXED_EPOCH_ONLY",
        "neural_feature_firewall": {"M2": False, "126D": False, "structure_features": False},
        "m2_branch": {"independent": True, "ridge_alpha": args.ridge_alpha},
        "source_parent_candidate_weighting": weight_audit,
        "contact_tier_loss_metadata": DEFAULT_TIER_POLICY,
        "loss_weights": {
            "receptor": args.receptor_weight,
            "dual": args.dual_weight,
            "marginal": args.marginal_weight if args.lane in {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"} else 0.0,
            "pair": args.pair_weight if args.lane == "D_SPLIT_PAIR" else 0.0,
        },
        "training": training,
        "gradient_accumulation": args.gradient_accumulation,
        "contact_score_formula_receipt": {
            **formula_receipt,
            "artifact_path": formula_artifact_path.name,
            "artifact_sha256": sha256_file(formula_artifact_path),
            "applied_to_lane": formula_applied,
        },
        "contact_score_formula_receipt_sha256": formula_receipt["sha256"],
        "contact_score_component_role": contact_component_role,
        "contact_score_stack_eligible": formula_applied,
        "artifacts": {
            "predictions": {"path": prediction_path.name, "rows": len(score_indices), "sha256": sha256_file(prediction_path)},
            "m2_ridge": {"path": m2_path.name, "sha256": sha256_file(m2_path)},
            "neural_head": {"path": checkpoint_path.name, "sha256": sha256_file(checkpoint_path)},
            "component_receipts": {"path": component_path.name, "sha256": base_model_receipt_sha256},
            "contact_score_formula": {"path": formula_artifact_path.name, "sha256": sha256_file(formula_artifact_path)},
        },
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(output_dir / "receipt.json", receipt)
    atomic_json(output_dir / "RESULT.json", receipt)
    return receipt


class TinyBatchFactory:
    def __init__(self, rows: Sequence[BaseRow], edge_dim: int, batch_size: int, seed: int) -> None:
        self.rows = rows
        self.edge_dim = edge_dim
        self.batch_size = batch_size
        self.seed = seed
        self.hierarchy: dict[int, float] = {}

    def set_hierarchy_weights(self, weights: Mapping[int, float]) -> None:
        self.hierarchy = dict(weights)

    def _collate(self, indices: Sequence[int]) -> dict[str, Any]:
        sequences = [self.rows[index].sequence for index in indices]
        length = max(len(sequence) for sequence in sequences)
        batch = len(indices)
        input_ids = torch.zeros((batch, length), dtype=torch.long)
        residue_mask = torch.zeros((batch, length), dtype=torch.bool)
        aa = torch.zeros((batch, length), dtype=torch.long)
        region = torch.zeros((batch, length), dtype=torch.long)
        confidence = torch.zeros((batch, length), dtype=torch.float32)
        edges = []
        edge_features = []
        for item, sequence in enumerate(sequences):
            valid = len(sequence)
            ids = torch.tensor([(ord(char) % 20) + 1 for char in sequence], dtype=torch.long)
            input_ids[item, :valid] = ids
            aa[item, :valid] = ids % 21
            residue_mask[item, :valid] = True
            confidence[item, :valid] = 0.85
            boundaries = (valid // 4, valid // 2, 3 * valid // 4)
            region[item, :valid] = torch.tensor([
                1 if pos < boundaries[0] else 2 if pos < boundaries[1] else 3 if pos < boundaries[2] else 0
                for pos in range(valid)
            ])
            for pos in range(valid - 1):
                for source, destination in ((pos, pos + 1), (pos + 1, pos)):
                    edges.append((item * length + source, item * length + destination))
                    feature = torch.zeros(self.edge_dim)
                    feature[0] = 1.0
                    edge_features.append(feature)
        edge_index = torch.tensor(edges, dtype=torch.long).T.contiguous()
        targets = torch.tensor([self.rows[index].targets for index in indices], dtype=torch.float32)
        marginal_targets = torch.zeros((batch, length, 2), dtype=torch.float32)
        for item in range(batch):
            marginal_targets[item, :, 0] = torch.linspace(0.05, 0.7, length)
            marginal_targets[item, :, 1] = torch.linspace(0.7, 0.05, length)
        marginal_mask = residue_mask.unsqueeze(-1).expand_as(marginal_targets)
        output: dict[str, Any] = {
            "candidate_ids": [self.rows[index].candidate_id for index in indices],
            "input_ids": input_ids,
            "attention_mask": residue_mask.long(),
            "residue_mask": residue_mask,
            "vhh_aa_index": aa,
            "vhh_region_index": region,
            "vhh_confidence": confidence,
            "vhh_edge_index": edge_index,
            "vhh_edge_features": torch.stack(edge_features),
            "targets": targets,
            "hierarchy_weights": torch.tensor([self.hierarchy.get(index, 1.0) for index in indices]),
            "marginal_targets": marginal_targets,
            "marginal_mask": marginal_mask,
            "marginal_uncertainty": torch.ones_like(marginal_targets),
            "marginal_tier_weights": torch.tensor([DEFAULT_TIER_POLICY[self.rows[index].contact_tier]["marginal"] for index in indices]),
            "pair_tier_weights": torch.tensor([DEFAULT_TIER_POLICY[self.rows[index].contact_tier]["pair"] for index in indices]),
        }
        for receptor, nodes in (("8x6b", 5), ("9e6y", 6)):
            pair = marginal_targets[:, :, 0 if receptor == "8x6b" else 1].unsqueeze(-1).expand(batch, length, nodes)
            output[f"pair_targets_{receptor}"] = pair
            output[f"pair_mask_{receptor}"] = residue_mask.unsqueeze(-1).expand_as(pair)
            output[f"pair_uncertainty_{receptor}"] = torch.ones_like(pair)
        return output

    def __call__(self, indices: Sequence[int], training: bool, epoch: int) -> Iterable[Mapping[str, Any]]:
        selected = list(indices)
        if training:
            random.Random(self.seed + epoch).shuffle(selected)
        for start in range(0, len(selected), self.batch_size):
            yield self._collate(selected[start:start + self.batch_size])


def tiny_target_graphs(config: ResidueV24Config) -> dict[str, dict[str, Tensor]]:
    result = {}
    for channel, (receptor, nodes) in enumerate((("8x6b", 5), ("9e6y", 6))):
        edges = []
        for index in range(nodes - 1):
            edges.extend(((index, index + 1), (index + 1, index)))
        edge_index = torch.tensor(edges, dtype=torch.long).T.contiguous()
        edge_features = torch.zeros((len(edges), config.edge_feature_dim))
        edge_features[:, 0] = 1.0
        result[receptor] = {
            "node_features": torch.arange(nodes * config.target_node_dim, dtype=torch.float32).reshape(nodes, -1) / 100 + channel,
            "edge_index": edge_index,
            "edge_features": edge_features,
            "interface_mask": torch.tensor([(index % 2) == 0 for index in range(nodes)]),
            "hotspot_mask": torch.tensor([index in {1, 2} for index in range(nodes)]),
        }
    return result


def build_tiny_panel() -> tuple[list[BaseRow], SplitManifest]:
    rows = []
    parents = [f"P{index}" for index in range(8)]
    for parent_index, parent in enumerate(parents):
        source = "V4D_OPEN_MULTI_SEED" if parent_index < 4 else "V4H_OPEN_ADAPTIVE"
        for candidate_index in range(2):
            sequence = "ACDEFG" if candidate_index == 0 else "HIKLMN"
            score = 0.15 + 0.05 * parent_index + 0.01 * candidate_index
            rows.append(BaseRow(
                f"{parent}_C{candidate_index}",
                sequence,
                hashlib.sha256(sequence.encode()).hexdigest(),
                parent,
                source,
                (score, score + 0.03 * ((parent_index % 2) * 2 - 1)),
                (float(parent_index), float(candidate_index), float(parent_index * candidate_index + 1), 1.0),
                CONTACT_TIERS[(parent_index + candidate_index) % 3],
            ))
    train_parents = tuple(parents[:3] + parents[4:7])
    score_parents = (parents[3], parents[7])
    manifest = SplitManifest(
        "tiny_outer_0",
        0,
        train_parents,
        score_parents,
        1,
        True,
        0,
        canonical_parent_set_sha256(train_parents),
        canonical_parent_set_sha256(score_parents),
    )
    return rows, manifest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--lane", choices=LANES, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--split-manifest", type=Path)
    value.add_argument("--v2-3-bundle-root", type=Path)
    value.add_argument("--training-tsv", type=Path)
    value.add_argument("--contact-tsv-gz", type=Path)
    value.add_argument("--graph-cache-dir", type=Path)
    value.add_argument("--target-graph-pt", type=Path)
    value.add_argument("--pair-contact-tsv-gz", type=Path)
    value.add_argument("--contact-formula-json", type=Path)
    value.add_argument("--structure-prefix", action="append", default=[])
    value.add_argument("--structure-dim", type=int, default=126)
    value.add_argument("--backbone-kind", choices=("tiny", "hf"), default="hf")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--trust-remote-code", action="store_true")
    value.add_argument("--tiny-hidden-size", type=int, default=12)
    value.add_argument("--graph-hidden-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.25)
    value.add_argument("--fixed-epochs", type=int, default=8)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--learning-rate", type=float, default=1e-4)
    value.add_argument("--weight-decay", type=float, default=0.02)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--gradient-accumulation", type=int, default=2)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    value.add_argument("--huber-delta", type=float, default=0.03)
    value.add_argument("--receptor-weight", type=float, default=1.0)
    value.add_argument("--dual-weight", type=float, default=0.5)
    value.add_argument("--marginal-weight", type=float, default=0.01)
    value.add_argument("--pair-weight", type=float, default=0.005)
    value.add_argument("--ridge-alpha", type=float, default=10.0)
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--tiny-e2e", action="store_true")
    value.add_argument("--calibration-only", action="store_true")
    value.add_argument("--calibration-grid", type=float, nargs="+", default=[])
    value.add_argument("--pair-to-marginal-ratio", type=float, default=0.5)
    value.add_argument("--target-gradient-fraction-band", type=float, nargs=2, default=(0.05, 0.2))
    return value


def run_tiny(args: argparse.Namespace) -> dict[str, Any]:
    require(args.fixed_epochs == 1, "tiny_fixed_epochs_must_equal_1")
    rows, manifest = build_tiny_panel()
    backbone, _tokenizer, hidden, _identity = load_backbone(args, None)
    config = ResidueV24Config(
        backbone_hidden_size=hidden,
        target_node_dim=7,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
    )
    model = build_model(args.lane, backbone, config)
    batches = TinyBatchFactory(rows, config.edge_feature_dim, args.batch_size, args.seed)
    targets = None if args.lane == "A_VHH_ONLY" else tiny_target_graphs(config)
    return run_base_split(rows, manifest, model, batches, targets, args)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    reject_sealed_path(args.output_dir)
    if args.tiny_e2e:
        require(args.backbone_kind == "tiny", "tiny_e2e_requires_tiny_backbone")
        result = run_tiny(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    # Real execution intentionally reuses the read-only V2.3 data/backbone
    # utilities. Deployment/provenance launchers bind the remaining arguments.
    require(args.v2_3_bundle_root is not None and args.split_manifest is not None, "real_runtime_arguments_missing")
    require(args.contact_formula_json is not None, "contact_formula_json_required_for_real_mode")
    for path in (
        args.training_tsv, args.contact_tsv_gz, args.graph_cache_dir,
        args.target_graph_pt, args.pair_contact_tsv_gz, args.contact_formula_json,
    ):
        reject_sealed_path(path)
    runtime = V23Runtime(args.v2_3_bundle_root)
    rows, rows_v1, teacher_sources, stores, target_graphs = runtime.load_real_panel(args)
    contact_uncertainty, graph_store, pair_store = stores
    backbone, tokenizer, hidden, _identity = load_backbone(args, runtime)
    config = ResidueV24Config(
        backbone_hidden_size=hidden,
        target_node_dim=(next(iter(target_graphs.values()))["node_features"].shape[1] if target_graphs else 1),
        edge_feature_dim=graph_store.edge_feature_dim,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
    )
    model = build_model(args.lane, backbone, config)
    bases = {index: np.zeros(3, dtype=np.float32) for index in range(len(rows))}
    target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES} if target_graphs else {}

    class RealBatchFactory:
        def __init__(self) -> None:
            self.hierarchy: dict[int, float] = {}

        def set_hierarchy_weights(self, weights: Mapping[int, float]) -> None:
            self.hierarchy = dict(weights)

        def __call__(self, indices: Sequence[int], training: bool, epoch: int) -> Iterable[Mapping[str, Any]]:
            selected = list(indices)
            if training:
                random.Random(args.seed + epoch).shuffle(selected)
            collator = runtime.v23.V2Collator(
                rows_v1, tokenizer, bases, teacher_sources, contact_uncertainty,
                graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
            )
            for start in range(0, len(selected), args.batch_size):
                batch_indices = selected[start:start + args.batch_size]
                batch = collator(batch_indices)
                batch["candidate_ids"] = [rows[index].candidate_id for index in batch_indices]
                batch["targets"] = torch.tensor([rows[index].targets for index in batch_indices], dtype=torch.float32)
                batch["hierarchy_weights"] = torch.tensor([self.hierarchy.get(index, 1.0) for index in batch_indices])
                batch["marginal_targets"] = batch.pop("contact_targets")
                batch["marginal_mask"] = batch.pop("contact_mask")
                batch["marginal_uncertainty"] = batch.pop("contact_uncertainty")
                batch["marginal_tier_weights"] = torch.tensor([DEFAULT_TIER_POLICY[rows[index].contact_tier]["marginal"] for index in batch_indices])
                batch["pair_tier_weights"] = torch.tensor([DEFAULT_TIER_POLICY[rows[index].contact_tier]["pair"] for index in batch_indices])
                yield batch

    manifest = SplitManifest.from_json(args.split_manifest)
    batches = RealBatchFactory()
    if args.calibration_only:
        result = observe_prestep_contact_gradient_grid(
            model, args.lane, rows, manifest, batches, target_graphs, args,
        )
        require(not args.output_dir.exists(), "output_dir_exists")
        args.output_dir.mkdir(parents=True)
        atomic_json(args.output_dir / "CALIBRATION_OBSERVATION.json", result)
        atomic_json(args.output_dir / "RESULT.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0
    require(not args.calibration_grid, "calibration_grid_requires_calibration_only")
    result = run_base_split(rows, manifest, model, batches, target_graphs, args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
