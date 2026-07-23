#!/usr/bin/env python3
"""Truth-free production inference for a clean-attention checkpoint ensemble.

The frozen ESM2 backbone is evaluated once per candidate batch.  Multiple
clean-attention heads then consume the same residue states together with the
label-free VHH monomer graphs and fixed public 8X6B/9E6Y target graphs.

This adapter predicts computational Docking geometry only.  It does not read
teacher values, Docking poses, contact supervision, binding labels, affinity,
or experimental blocking evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig_v2_19_clean_attention_checkpoint_ensemble_inference_v1"
STATUS = "PASS_TRUTH_FREE_CLEAN_ATTENTION_CHECKPOINT_ENSEMBLE_INFERENCE"
LANE = "B_CLEAN_TARGET_ATTENTION"
RECEPTORS = ("8x6b", "9e6y")
OUTPUT_NAME = "clean_attention_checkpoint_ensemble_predictions.tsv"
RECEIPT_NAME = "RUN_RECEIPT.json"
SHA256_NAME = "SHA256SUMS"
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMPACT_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_framework_cluster",
)
ACCEPTED_CHECKPOINT_SCHEMAS = {
    "pvrig_v2_12_clean_attention_inner_oof_fold_runner_v1",
    "pvrig_v2_13_top5_clean_attention_fold_runner_v1",
}
FORBIDDEN_FIELD_TOKENS = {
    "target",
    "truth",
    "teacher",
    "docking",
    "pose",
    "contact",
    "label",
    "affinity",
    "blocking",
    "sample_weight",
    "r_8x6b",
    "r_9e6y",
    "r_dual_min",
}
CLAIM_BOUNDARY = (
    "Sequence plus label-free VHH monomer graph plus fixed public 8X6B/9E6Y "
    "target-graph ensemble approximation of independent dual-receptor computational "
    "Docking geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)


class ProductionInferenceError(RuntimeError):
    """Fail-closed production inference error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProductionInferenceError(message)


def sha256_file(path: Path) -> str:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _import_module(name: str, path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), f"module_path_invalid:{path}")
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, f"module_spec_invalid:{path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _load_base_module(path: Path) -> Any:
    module = _import_module("pvrig_v219_clean_attention_base", path)
    required = {
        "load_contract", "load_frozen_ortho_modules", "load_target_graphs", "load_backbone",
        "GraphCacheStore", "move", "_verify_bound_file",
    }
    require(required <= set(dir(module)), f"base_module_api_missing:{sorted(required-set(dir(module)))}")
    return module


@dataclass(frozen=True)
class ProductionCandidate:
    candidate_id: str
    sequence_sha256: str
    sequence: str
    parent: str


@dataclass(frozen=True)
class LoadedHead:
    index: int
    label: str
    path: Path
    sha256: str
    schema_version: str
    seed: int
    split_id: str
    variant: str
    module: nn.Module


def _field_is_forbidden(field: str) -> bool:
    lowered = field.strip().lower()
    return any(token == lowered or token in lowered for token in FORBIDDEN_FIELD_TOKENS)


def load_compact_manifest(path: Path, expected_rows: int) -> list[ProductionCandidate]:
    require(path.is_file() and not path.is_symlink(), "compact_manifest_invalid")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = tuple(reader.fieldnames or ())
        require(fields == COMPACT_FIELDS, f"compact_manifest_fields_exact_required:{fields}")
        require(not any(_field_is_forbidden(field) for field in fields), "compact_manifest_forbidden_field")
        raw = [dict(row) for row in reader]
    require(len(raw) == expected_rows and expected_rows > 0, f"compact_manifest_row_count:{len(raw)}!={expected_rows}")
    rows: list[ProductionCandidate] = []
    seen: set[str] = set()
    for source in raw:
        candidate_id = source["candidate_id"].strip()
        sequence = source["sequence"].strip().upper()
        sequence_digest = source["sequence_sha256"].strip().lower()
        parent = source["parent_framework_cluster"].strip()
        require(candidate_id and candidate_id not in seen, f"candidate_id_duplicate_or_empty:{candidate_id}")
        require(bool(AA_RE.fullmatch(sequence)), f"sequence_invalid:{candidate_id}")
        require(bool(SHA256_RE.fullmatch(sequence_digest)), f"sequence_sha256_invalid:{candidate_id}")
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == sequence_digest, f"sequence_sha256_mismatch:{candidate_id}")
        require(bool(parent), f"parent_empty:{candidate_id}")
        seen.add(candidate_id)
        rows.append(ProductionCandidate(candidate_id, sequence_digest, sequence, parent))
    return rows


class ProductionCollator:
    """Positive-allowlist inference collator; identifiers never enter the model."""

    def __init__(self, rows: Sequence[ProductionCandidate], tokenizer: Any, graphs: Any) -> None:
        self.rows = rows
        self.tokenizer = tokenizer
        self.graphs = graphs

    def __call__(self, indices: Sequence[int]) -> dict[str, Tensor]:
        selected = [self.rows[index] for index in indices]
        encoded = self.tokenizer(
            [row.sequence for row in selected],
            padding=True,
            truncation=False,
            return_tensors="pt",
            return_special_tokens_mask=True,
        )
        require("special_tokens_mask" in encoded, "tokenizer_special_tokens_mask_missing")
        residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
        batch_size, width = encoded["input_ids"].shape
        aa = torch.zeros((batch_size, width), dtype=torch.long)
        region = torch.zeros((batch_size, width), dtype=torch.long)
        confidence = torch.zeros((batch_size, width), dtype=torch.float32)
        edge_indices: list[Tensor] = []
        edge_features: list[Tensor] = []
        for item, row in enumerate(selected):
            positions = residue_mask[item].nonzero(as_tuple=False).flatten()
            graph = self.graphs.graph(row.candidate_id)
            require(len(positions) == len(row.sequence) == len(graph["aa_index"]), f"token_graph_alignment:{row.candidate_id}")
            aa[item, positions] = torch.from_numpy(graph["aa_index"]).long()
            region[item, positions] = torch.from_numpy(graph["region_index"]).long()
            confidence[item, positions] = torch.from_numpy(graph["confidence"]).float()
            local = torch.from_numpy(graph["edge_index"]).long()
            edge_indices.append(torch.stack((positions[local[0]], positions[local[1]])) + item * width)
            edge_features.append(torch.from_numpy(graph["edge_features"]).float())
        batch = {
            "input_ids": encoded["input_ids"].long(),
            "attention_mask": encoded["attention_mask"].long(),
            "residue_mask": residue_mask,
            "vhh_aa_index": aa,
            "vhh_region_index": region,
            "vhh_confidence": confidence,
            "vhh_edge_index": torch.cat(edge_indices, dim=1),
            "vhh_edge_features": torch.cat(edge_features, dim=0),
        }
        required = {
            "input_ids", "attention_mask", "residue_mask", "vhh_aa_index", "vhh_region_index",
            "vhh_confidence", "vhh_edge_index", "vhh_edge_features",
        }
        require(set(batch) == required, "production_collator_allowlist_drift")
        require(not any(_field_is_forbidden(field) for field in batch), "production_collator_forbidden_field")
        return batch


def _head_forward_kwargs(batch: Mapping[str, Tensor], states: Tensor, target_graphs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "token_states": states,
        "residue_mask": batch["residue_mask"],
        "vhh_aa_index": batch["vhh_aa_index"],
        "vhh_region_index": batch["vhh_region_index"],
        "vhh_confidence": batch["vhh_confidence"],
        "vhh_edge_index": batch["vhh_edge_index"],
        "vhh_edge_features": batch["vhh_edge_features"],
        "target_graphs": target_graphs,
    }


def _load_heads(
    checkpoint_paths: Sequence[Path],
    model_module: Any,
    *,
    expected_backbone_identity: str,
    backbone_hidden_size: int,
    edge_feature_dim: int,
    target_node_dim: int,
    tiny_e2e: bool,
) -> tuple[list[LoadedHead], Mapping[str, Any]]:
    require(bool(checkpoint_paths), "checkpoint_list_empty")
    require(len(checkpoint_paths) == len(set(checkpoint_paths)), "checkpoint_path_duplicate")
    loaded: list[LoadedHead] = []
    reference_config: Mapping[str, Any] | None = None
    seen_hashes: set[str] = set()
    for index, path in enumerate(checkpoint_paths):
        digest = sha256_file(path)
        require(digest not in seen_hashes, f"checkpoint_content_duplicate:{path}")
        seen_hashes.add(digest)
        payload = torch.load(path, map_location="cpu", weights_only=True)
        require(isinstance(payload, Mapping), f"checkpoint_payload_invalid:{path}")
        schema = str(payload.get("schema_version", ""))
        require(schema in ACCEPTED_CHECKPOINT_SCHEMAS, f"checkpoint_schema_invalid:{schema}")
        require(payload.get("lane") == LANE, f"checkpoint_lane_invalid:{path}")
        identity = str(payload.get("backbone_identity_sha256", ""))
        if tiny_e2e:
            require(identity == "tiny_synthetic", f"tiny_checkpoint_identity_invalid:{identity}")
        else:
            require(bool(SHA256_RE.fullmatch(identity)), f"checkpoint_backbone_identity_invalid:{path}")
            require(identity == expected_backbone_identity, f"checkpoint_backbone_identity_mismatch:{path}")
        config_dict = payload.get("head_config")
        state = payload.get("head_state_dict")
        require(isinstance(config_dict, Mapping), f"checkpoint_head_config_invalid:{path}")
        require(isinstance(state, Mapping) and state, f"checkpoint_head_state_invalid:{path}")
        config_dict = dict(config_dict)
        require(int(config_dict.get("backbone_hidden_size", -1)) == backbone_hidden_size, f"checkpoint_backbone_dim:{path}")
        require(int(config_dict.get("edge_feature_dim", -1)) == edge_feature_dim, f"checkpoint_edge_dim:{path}")
        require(int(config_dict.get("target_node_dim", -1)) == target_node_dim, f"checkpoint_target_dim:{path}")
        require(config_dict.get("enable_contact_evidence") is False, f"checkpoint_contact_lane_enabled:{path}")
        if reference_config is None:
            reference_config = config_dict
        require(config_dict == reference_config, f"checkpoint_head_config_mismatch:{path}")
        config = model_module.ResidueV25OrthoConfig(**config_dict)
        config.validate()
        head = model_module.OrthogonalTargetHead(config)
        head.load_state_dict(dict(state), strict=True)
        head.eval()
        require(not any(parameter.requires_grad is False for parameter in head.parameters()), "unexpected_frozen_head_parameter")
        seed = int(payload.get("seed", -1))
        split_id = str(payload.get("split_id", ""))
        require(seed >= 0 and split_id, f"checkpoint_metadata_invalid:{path}")
        variant = str(payload.get("variant", "BASE"))
        loaded.append(LoadedHead(index, f"checkpoint_{index:03d}", path, digest, schema, seed, split_id, variant, head))
    assert reference_config is not None
    return loaded, reference_config


def _iter_batches(count: int, batch_size: int) -> Iterable[list[int]]:
    for start in range(0, count, batch_size):
        yield list(range(start, min(count, start + batch_size)))


def _ordinal_ranks(candidate_ids: Sequence[str], score: np.ndarray) -> np.ndarray:
    require(len(candidate_ids) == len(score), "rank_length_mismatch")
    order = sorted(range(len(score)), key=lambda index: (-float(score[index]), candidate_ids[index]))
    ranks = np.empty(len(order), dtype=np.int64)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    return ranks


def _format_float(value: float) -> str:
    require(math.isfinite(value), "output_nonfinite")
    return f"{value:.12g}"


def _write_prediction_table(
    path: Path,
    rows: Sequence[ProductionCandidate],
    heads: Sequence[LoadedHead],
    predictions: np.ndarray,
    uncertainty_penalty: float,
) -> dict[str, Any]:
    require(predictions.shape == (len(heads), len(rows), 2), "prediction_tensor_shape_invalid")
    individual_dual = np.minimum(predictions[:, :, 0], predictions[:, :, 1])
    mean_r = predictions.mean(axis=0)
    std_r = predictions.std(axis=0, ddof=0)
    mean_dual = individual_dual.mean(axis=0)
    std_dual = individual_dual.std(axis=0, ddof=0)
    exact_min_of_means = np.minimum(mean_r[:, 0], mean_r[:, 1])
    conservative = mean_dual - uncertainty_penalty * std_dual
    ids = [row.candidate_id for row in rows]
    mean_rank = _ordinal_ranks(ids, mean_dual)
    conservative_rank = _ordinal_ranks(ids, conservative)
    individual_ranks = np.stack([_ordinal_ranks(ids, individual_dual[index]) for index in range(len(heads))])
    rank_std = individual_ranks.std(axis=0, ddof=0)

    fieldnames = list(COMPACT_FIELDS)
    for head in heads:
        fieldnames.extend((
            f"{head.label}_R_8X6B",
            f"{head.label}_R_9E6Y",
            f"{head.label}_R_dual_min",
        ))
    fieldnames.extend((
        "ensemble_R_8X6B_mean",
        "ensemble_R_8X6B_std",
        "ensemble_R_9E6Y_mean",
        "ensemble_R_9E6Y_std",
        "ensemble_R_dual_mean",
        "ensemble_R_dual_std",
        "ensemble_exact_min_of_receptor_means",
        "ensemble_receptor_gap_abs",
        "ensemble_checkpoint_rank_std",
        "ensemble_conservative_R_dual_score",
        "ensemble_R_dual_mean_rank",
        "ensemble_conservative_rank",
        "ensemble_conservative_top_fraction",
        "ensemble_checkpoint_count",
        "claim_boundary",
    ))
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    denominator = max(1, len(rows) - 1)
    for item, row in enumerate(rows):
        record: dict[str, str] = {
            "candidate_id": row.candidate_id,
            "sequence_sha256": row.sequence_sha256,
            "sequence": row.sequence,
            "parent_framework_cluster": row.parent,
        }
        for model_index, head in enumerate(heads):
            r8 = float(predictions[model_index, item, 0])
            r9 = float(predictions[model_index, item, 1])
            record[f"{head.label}_R_8X6B"] = _format_float(r8)
            record[f"{head.label}_R_9E6Y"] = _format_float(r9)
            record[f"{head.label}_R_dual_min"] = _format_float(min(r8, r9))
        record.update({
            "ensemble_R_8X6B_mean": _format_float(float(mean_r[item, 0])),
            "ensemble_R_8X6B_std": _format_float(float(std_r[item, 0])),
            "ensemble_R_9E6Y_mean": _format_float(float(mean_r[item, 1])),
            "ensemble_R_9E6Y_std": _format_float(float(std_r[item, 1])),
            "ensemble_R_dual_mean": _format_float(float(mean_dual[item])),
            "ensemble_R_dual_std": _format_float(float(std_dual[item])),
            "ensemble_exact_min_of_receptor_means": _format_float(float(exact_min_of_means[item])),
            "ensemble_receptor_gap_abs": _format_float(float(abs(mean_r[item, 0] - mean_r[item, 1]))),
            "ensemble_checkpoint_rank_std": _format_float(float(rank_std[item])),
            "ensemble_conservative_R_dual_score": _format_float(float(conservative[item])),
            "ensemble_R_dual_mean_rank": str(int(mean_rank[item])),
            "ensemble_conservative_rank": str(int(conservative_rank[item])),
            "ensemble_conservative_top_fraction": _format_float(float((conservative_rank[item] - 1) / denominator)),
            "ensemble_checkpoint_count": str(len(heads)),
            "claim_boundary": CLAIM_BOUNDARY,
        })
        writer.writerow(record)
    _atomic_text(path, buffer.getvalue())
    return {
        "rows": len(rows),
        "checkpoints": len(heads),
        "uncertainty_penalty": uncertainty_penalty,
        "mean_dual_min": float(mean_dual.min()),
        "mean_dual_max": float(mean_dual.max()),
        "mean_dual_std_mean": float(std_dual.mean()),
        "conservative_score_min": float(conservative.min()),
        "conservative_score_max": float(conservative.max()),
    }


def infer(args: argparse.Namespace) -> dict[str, Any]:
    require(args.expected_rows > 0 and args.batch_size > 0, "count_argument_invalid")
    require(math.isfinite(args.uncertainty_penalty) and args.uncertainty_penalty >= 0.0, "uncertainty_penalty_invalid")
    require(args.precision == "fp32" or args.device.startswith("cuda"), "bf16_requires_cuda")
    require(not args.output_dir.exists(), "output_dir_exists")
    require(args.base_module.is_file() and not args.base_module.is_symlink(), "base_module_invalid")
    base = _load_base_module(args.base_module)
    contract = base.load_contract(args.reference_contract)
    model_module, _trainer_module = base.load_frozen_ortho_modules(contract)
    rows = load_compact_manifest(args.manifest, args.expected_rows)
    graph_store = base.GraphCacheStore(args.graph_cache_dir, rows, require_full_receipt=False)
    target_receipt_path = base._verify_bound_file(contract["fixed_target_graph"]["receipt"], "target_graph_receipt")
    target_path = base._verify_bound_file(contract["fixed_target_graph"]["torch_artifact"], "target_graph_pt")
    target_graphs = base.load_target_graphs(target_path, graph_store.edge_feature_dim, target_receipt_path)
    target_node_dim = int(next(iter(target_graphs.values()))["node_features"].shape[1])
    backbone, tokenizer, backbone_hidden_size, backbone_identity = base.load_backbone(args)
    heads, head_config = _load_heads(
        args.checkpoint,
        model_module,
        expected_backbone_identity=backbone_identity,
        backbone_hidden_size=backbone_hidden_size,
        edge_feature_dim=graph_store.edge_feature_dim,
        target_node_dim=target_node_dim,
        tiny_e2e=args.tiny_e2e,
    )
    require(all(not parameter.requires_grad for parameter in backbone.parameters()), "backbone_not_frozen")
    collator = ProductionCollator(rows, tokenizer, graph_store)
    probe = collator(range(min(2, len(rows))))
    require(set(probe) == {
        "input_ids", "attention_mask", "residue_mask", "vhh_aa_index", "vhh_region_index",
        "vhh_confidence", "vhh_edge_index", "vhh_edge_features",
    }, "probe_allowlist_drift")

    args.output_dir.mkdir(parents=True)
    _atomic_json(args.output_dir / "RUNNING.json", {
        "schema_version": SCHEMA_VERSION,
        "status": "RUNNING_TRUTH_FREE_CLEAN_ATTENTION_CHECKPOINT_ENSEMBLE_INFERENCE",
        "rows": len(rows),
        "checkpoints": len(heads),
        "claim_boundary": CLAIM_BOUNDARY,
    })
    device = torch.device(args.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_unavailable")
    backbone.to(device).eval()
    for head in heads:
        head.module.to(device).eval()
    target_device = base.move(target_graphs, device)
    predictions = np.empty((len(heads), len(rows), 2), dtype=np.float32)
    backbone_forward_batches = 0
    head_forward_batches = 0
    exact_min_max_abs_error = 0.0
    with torch.no_grad():
        for batch_indices in _iter_batches(len(rows), args.batch_size):
            raw = collator(batch_indices)
            batch = base.move(raw, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=args.precision == "bf16"):
                states = model_module.backbone_states(backbone, batch["input_ids"], batch["attention_mask"])
                backbone_forward_batches += 1
                for model_index, head in enumerate(heads):
                    output = head.module(**_head_forward_kwargs(batch, states, target_device))
                    receptor = output["receptor_predictions"].float().cpu().numpy()
                    exact = output["exact_min_dual"].float().cpu().numpy()
                    recomputed = np.minimum(receptor[:, 0], receptor[:, 1])
                    error = float(np.max(np.abs(exact - recomputed)))
                    require(error <= 1e-7, f"checkpoint_exact_min_mismatch:{head.label}:{error}")
                    exact_min_max_abs_error = max(exact_min_max_abs_error, error)
                    predictions[model_index, batch_indices, :] = receptor
                    head_forward_batches += 1

    output_path = args.output_dir / OUTPUT_NAME
    summary = _write_prediction_table(output_path, rows, heads, predictions, args.uncertainty_penalty)
    checkpoints = [{
        "index": head.index,
        "label": head.label,
        "path": str(head.path),
        "sha256": head.sha256,
        "schema_version": head.schema_version,
        "seed": head.seed,
        "split_id": head.split_id,
        "variant": head.variant,
    } for head in heads]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": summary,
        "inference": {
            "device": str(device),
            "precision": args.precision,
            "batch_size": args.batch_size,
            "backbone_forward_batches": backbone_forward_batches,
            "head_forward_batches": head_forward_batches,
            "shared_backbone_once_per_batch": head_forward_batches == backbone_forward_batches * len(heads),
            "exact_min_inference": True,
            "exact_min_max_abs_error": exact_min_max_abs_error,
            "head_config": dict(head_config),
        },
        "input_firewall": {
            "manifest_exact_fields": list(COMPACT_FIELDS),
            "teacher_fields_read": 0,
            "truth_fields_read": 0,
            "docking_pose_files_opened": 0,
            "contact_supervision_fields_read": 0,
            "candidate_id_model_input_count": 0,
            "parent_id_model_input_count": 0,
        },
        "input_bindings": {
            "manifest": {"path": str(args.manifest), "sha256": sha256_file(args.manifest)},
            "reference_contract": {"path": str(args.reference_contract), "sha256": sha256_file(args.reference_contract)},
            "base_module": {"path": str(args.base_module), "sha256": sha256_file(args.base_module)},
            "target_graph_receipt": {"path": str(target_receipt_path), "sha256": sha256_file(target_receipt_path)},
            "target_graph": {"path": str(target_path), "sha256": sha256_file(target_path)},
            "graph_bundle": graph_store.input_hashes,
            "backbone_identity": backbone_identity,
            "checkpoints": checkpoints,
        },
        "outputs": {OUTPUT_NAME: sha256_file(output_path)},
    }
    receipt_path = args.output_dir / RECEIPT_NAME
    _atomic_json(receipt_path, receipt)
    _atomic_text(
        args.output_dir / SHA256_NAME,
        f"{sha256_file(output_path)}  {OUTPUT_NAME}\n{sha256_file(receipt_path)}  {RECEIPT_NAME}\n",
    )
    (args.output_dir / "RUNNING.json").unlink()
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--manifest", type=Path, required=True)
    value.add_argument("--expected-rows", type=int, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--reference-contract", type=Path, required=True)
    value.add_argument("--base-module", type=Path, required=True)
    value.add_argument("--checkpoint", type=Path, action="append", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--device", default="cuda:0")
    value.add_argument("--batch-size", type=int, default=16)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--uncertainty-penalty", type=float, default=1.0)
    value.add_argument("--backbone-kind", choices=("hf", "tiny"), default="hf")
    value.add_argument("--backbone-dtype", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--tiny-hidden-size", type=int, default=16)
    value.add_argument("--tiny-e2e", action="store_true")
    return value


def validate_args(args: argparse.Namespace) -> None:
    if args.backbone_kind == "hf":
        require(not args.tiny_e2e, "hf_tiny_e2e_invalid")
        require(
            args.model_path is not None and args.model_identity_file is not None and args.expected_model_sha256,
            "hf_model_binding_required",
        )
    else:
        require(args.tiny_e2e, "tiny_backbone_test_only")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    validate_args(args)
    result = infer(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
