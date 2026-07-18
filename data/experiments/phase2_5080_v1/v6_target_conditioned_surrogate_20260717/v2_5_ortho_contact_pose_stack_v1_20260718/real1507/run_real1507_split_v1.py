#!/usr/bin/env python3
"""Real-1507 whole-parent split adapter for V2.5 orthogonal heads.

The runner reuses the frozen V2.4/V2.3 readers, ESM2-650M loader, monomer
graph cache and adaptive contact target stores.  It never forwards M2, 126D
aggregate structure features, identifiers, or candidate Docking poses into the
neural model.  Technical smoke modes expose no prediction metric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
for directory in (ROOT / "model", ROOT / "trainer"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from residue_model_v2_5_ortho import (  # noqa: E402
    CLAIM_BOUNDARY,
    LANE_B,
    LANE_E,
    RECEPTOR_NAMES,
    ResidueV25OrthoConfig,
    model_contract,
)
from train_v2_5_ortho_heads import (  # noqa: E402
    FORBIDDEN_NEURAL_INPUT_FIELDS,
    OrthoLossConfig,
    OptimizerConfig,
    build_model,
    compute_loss,
    forward_lane,
    move_to_device,
    named_parameter_roles,
    train_fixed_epochs,
    trainer_contract,
)


SCHEMA_VERSION = "pvrig_v2_5_ortho_real1507_split_runner_v1"
V24_ADAPTER_SHA256 = "59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f"
CONTACT_FORMULA_SHA256 = "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7"
STRUCTURE_PREFIXES = (
    "ALL__", "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
    "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__", "CDR3_FRAMEWORK__", "CDR3__",
    "CDR_ALL__", "FRAMEWORK__",
)


class Real1507RunnerError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Real1507RunnerError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_sealed_path(path: Path | None) -> None:
    if path is None:
        return
    normalized = str(path).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, f"sealed_path_forbidden:{path}")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


@dataclass(frozen=True)
class LaneSpec:
    variant: str
    model_lane: str
    contact_encoder_gradient: str
    adapter_lane: str
    marginal_weight: float
    pair_weight: float
    physical_gpu: int


LANE_SPECS = {
    "B_CLEAN_TARGET_ATTENTION": LaneSpec(
        "B_CLEAN_TARGET_ATTENTION", LANE_B, "detached", "B_TARGET_NO_CONTACT", 0.0, 0.0, 2,
    ),
    "E_DECOUPLED_CONTACT_DETACHED": LaneSpec(
        "E_DECOUPLED_CONTACT_DETACHED", LANE_E, "detached", "D_SPLIT_PAIR", 1.0, 0.5, 4,
    ),
    "E_DECOUPLED_CONTACT_SHARED": LaneSpec(
        "E_DECOUPLED_CONTACT_SHARED", LANE_E, "shared", "D_SPLIT_PAIR", 1.0, 0.5, 5,
    ),
}


FROZEN_TRAINING = {
    "graph_hidden_dim": 128,
    "dropout": 0.25,
    "batch_size": 8,
    "learning_rate": 1e-4,
    "weight_decay": 0.02,
    "contact_learning_rate_multiplier": 1.0,
    "gradient_clip": 1.0,
    "gradient_accumulation": 2,
    "precision": "bf16",
    "huber_beta": 0.03,
    "softmin_tau": 0.02,
    "receptor_weight": 1.0,
    "dual_weight": 0.5,
    "seed": 43,
}


def load_v24_adapter(path: Path, expected_sha256: str) -> Any:
    reject_sealed_path(path)
    require(path.is_file() and not path.is_symlink(), f"v2_4_adapter_missing_or_symlink:{path}")
    observed = sha256_file(path)
    require(observed == expected_sha256 == V24_ADAPTER_SHA256, f"v2_4_adapter_sha256:{observed}")
    name = f"pvrig_v24_adapter_{observed[:12]}"
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, "v2_4_adapter_import_spec")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _real_adapter_args(args: argparse.Namespace, spec: LaneSpec) -> argparse.Namespace:
    return argparse.Namespace(
        lane=spec.adapter_lane,
        training_tsv=args.training_tsv,
        contact_tsv_gz=args.contact_tsv_gz,
        graph_cache_dir=args.graph_cache_dir,
        target_graph_pt=args.target_graph_pt,
        pair_contact_tsv_gz=args.pair_contact_tsv_gz,
        structure_prefix=list(STRUCTURE_PREFIXES),
        structure_dim=126,
        backbone_kind="hf",
        model_path=args.model_path,
        model_identity_file=args.model_identity_file,
        expected_model_sha256=args.expected_model_sha256,
        trust_remote_code=False,
        tiny_hidden_size=12,
    )


class RealBatchFactory:
    def __init__(
        self,
        *,
        runtime: Any,
        rows: Sequence[Any],
        rows_v1: Sequence[Any],
        tokenizer: Any,
        teacher_sources: Sequence[str],
        contact_uncertainty: Any,
        graph_store: Any,
        pair_store: Any,
        target_nodes: Mapping[str, int],
        tier_policy: Mapping[str, Mapping[str, float]],
        batch_size: int,
        seed: int,
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
        self.tier_policy = tier_policy
        self.batch_size = batch_size
        self.seed = seed
        self.hierarchy: dict[int, float] = {}
        self.bases = {index: np.zeros(3, dtype=np.float32) for index in range(len(rows))}

    def set_hierarchy_weights(self, weights: Mapping[int, float]) -> None:
        self.hierarchy = dict(weights)

    def __call__(self, indices: Sequence[int], training: bool, epoch: int) -> Iterable[Mapping[str, Any]]:
        selected = list(indices)
        if training:
            random.Random(self.seed + epoch).shuffle(selected)
        collator = self.runtime.v23.V2Collator(
            self.rows_v1,
            self.tokenizer,
            self.bases,
            self.teacher_sources,
            self.contact_uncertainty,
            graph_store=self.graph_store,
            pair_store=self.pair_store,
            target_nodes=self.target_nodes,
        )
        for start in range(0, len(selected), self.batch_size):
            batch_indices = selected[start:start + self.batch_size]
            batch = collator(batch_indices)
            batch["candidate_ids"] = [self.rows[index].candidate_id for index in batch_indices]
            batch["targets"] = torch.tensor(
                [self.rows[index].targets for index in batch_indices], dtype=torch.float32,
            )
            batch["hierarchy_weights"] = torch.tensor(
                [self.hierarchy.get(index, 1.0) for index in batch_indices], dtype=torch.float32,
            )
            batch["marginal_targets"] = batch.pop("contact_targets")
            batch["marginal_mask"] = batch.pop("contact_mask")
            batch["marginal_uncertainty"] = batch.pop("contact_uncertainty")
            batch["marginal_tier_weights"] = torch.tensor(
                [self.tier_policy[self.rows[index].contact_tier]["marginal"] for index in batch_indices],
                dtype=torch.float32,
            )
            batch["pair_tier_weights"] = torch.tensor(
                [self.tier_policy[self.rows[index].contact_tier]["pair"] for index in batch_indices],
                dtype=torch.float32,
            )
            yield batch


@dataclass
class RealContext:
    adapter: Any
    runtime: Any
    rows: Sequence[Any]
    manifest: Any
    train_indices: list[int]
    score_indices: list[int]
    model: nn.Module
    batches: RealBatchFactory
    target_graphs: Mapping[str, Mapping[str, Tensor]]
    model_identity: str
    lane_spec: LaneSpec


def load_real_context(args: argparse.Namespace) -> RealContext:
    spec = LANE_SPECS[args.lane_variant]
    for path in (
        args.output_dir, args.v2_4_adapter_path, args.v2_3_bundle_root, args.training_tsv,
        args.contact_tsv_gz, args.graph_cache_dir, args.target_graph_pt,
        args.pair_contact_tsv_gz, args.contact_formula_json, args.model_path,
        args.model_identity_file, args.split_manifest,
    ):
        reject_sealed_path(path)
    adapter = load_v24_adapter(args.v2_4_adapter_path, args.expected_v2_4_adapter_sha256)
    adapter_args = _real_adapter_args(args, spec)
    runtime = adapter.V23Runtime(args.v2_3_bundle_root)
    rows, rows_v1, teacher_sources, stores, target_graphs = runtime.load_real_panel(adapter_args)
    contact_uncertainty, graph_store, pair_store = stores
    require(target_graphs is not None, "target_graphs_missing")
    require((pair_store is not None) == (spec.model_lane == LANE_E), "pair_store_lane_mismatch")
    backbone, tokenizer, hidden, identity = adapter.load_backbone(adapter_args, runtime)
    config = ResidueV25OrthoConfig(
        backbone_hidden_size=int(hidden),
        target_node_dim=int(next(iter(target_graphs.values()))["node_features"].shape[1]),
        edge_feature_dim=int(graph_store.edge_feature_dim),
        graph_hidden_dim=int(FROZEN_TRAINING["graph_hidden_dim"]),
        dropout=float(FROZEN_TRAINING["dropout"]),
        enable_contact_evidence=spec.model_lane == LANE_E,
        contact_encoder_gradient=spec.contact_encoder_gradient,
    )
    model = build_model(spec.model_lane, backbone, config)
    manifest = adapter.SplitManifest.from_json(args.split_manifest)
    # Source manifest keeps the production 8-epoch contract.  Technical smoke
    # may run one epoch but cannot rewrite that manifest.
    train_indices, score_indices = manifest.validate(rows, manifest.fixed_epochs)
    observed_parents = {row.parent for row in rows}
    require(len(rows) == args.expected_rows, f"row_count:{len(rows)}")
    require(len(observed_parents) == args.expected_parents, f"parent_count:{len(observed_parents)}")
    require(len(train_indices) == args.expected_train_rows, f"train_row_count:{len(train_indices)}")
    require(len(score_indices) == args.expected_score_rows, f"score_row_count:{len(score_indices)}")
    train_weights, _audit = adapter.source_parent_candidate_weights(rows, train_indices)
    hierarchy = {index: float(train_weights[local]) for local, index in enumerate(train_indices)}
    target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES}
    batches = RealBatchFactory(
        runtime=runtime,
        rows=rows,
        rows_v1=rows_v1,
        tokenizer=tokenizer,
        teacher_sources=teacher_sources,
        contact_uncertainty=contact_uncertainty,
        graph_store=graph_store,
        pair_store=pair_store,
        target_nodes=target_nodes,
        tier_policy=adapter.DEFAULT_TIER_POLICY,
        batch_size=int(FROZEN_TRAINING["batch_size"]),
        seed=int(FROZEN_TRAINING["seed"]),
    )
    batches.set_hierarchy_weights(hierarchy)
    return RealContext(
        adapter, runtime, rows, manifest, train_indices, score_indices,
        model, batches, target_graphs, str(identity), spec,
    )


def loss_config(spec: LaneSpec) -> OrthoLossConfig:
    return OrthoLossConfig(
        receptor_weight=float(FROZEN_TRAINING["receptor_weight"]),
        dual_weight=float(FROZEN_TRAINING["dual_weight"]),
        marginal_weight=spec.marginal_weight,
        pair_weight=spec.pair_weight,
        huber_beta=float(FROZEN_TRAINING["huber_beta"]),
        softmin_tau=float(FROZEN_TRAINING["softmin_tau"]),
    )


def optimizer_config() -> OptimizerConfig:
    return OptimizerConfig(
        learning_rate=float(FROZEN_TRAINING["learning_rate"]),
        weight_decay=float(FROZEN_TRAINING["weight_decay"]),
        contact_learning_rate_multiplier=float(FROZEN_TRAINING["contact_learning_rate_multiplier"]),
    )


def _gradient_role_norms(
    loss: Tensor,
    roles: Mapping[str, Sequence[tuple[str, nn.Parameter]]],
    *,
    retain_graph: bool,
) -> dict[str, float]:
    parameters = [parameter for values in roles.values() for _name, parameter in values]
    if not loss.requires_grad or float(loss.detach()) == 0.0:
        return {name: 0.0 for name in roles}
    gradients = torch.autograd.grad(loss, parameters, retain_graph=retain_graph, allow_unused=True)
    by_parameter = {id(parameter): gradient for parameter, gradient in zip(parameters, gradients)}
    result = {}
    for role, values in roles.items():
        squared = 0.0
        for _name, parameter in values:
            gradient = by_parameter[id(parameter)]
            if gradient is not None:
                require(bool(torch.isfinite(gradient).all()), f"preoptimizer_gradient_nonfinite:{role}")
                squared += float(gradient.float().square().sum().detach().cpu())
        result[role] = math.sqrt(squared)
    return result


def preoptimizer_telemetry(
    model: nn.Module,
    model_lane: str,
    batch: Mapping[str, Any],
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    loss: OrthoLossConfig,
    *,
    device_name: str,
    precision: str,
) -> dict[str, Any]:
    device = torch.device(device_name)
    model.to(device)
    model.train()
    model.backbone.eval()
    batch_device = move_to_device(batch, device)
    target_device = move_to_device(target_graphs, device)
    with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
        output = forward_lane(model, model_lane, batch_device, target_device)
        total, parts = compute_loss(output, batch_device, model_lane, loss)
    roles = named_parameter_roles(model)
    scalar_norms = _gradient_role_norms(parts["scalar"], roles, retain_graph=True)
    contact_norms = _gradient_role_norms(parts["contact"], roles, retain_graph=False)
    scalar_contact_leakage = scalar_norms["contact"]
    contact_attention_leakage = contact_norms["attention_scalar"]
    require(scalar_contact_leakage == 0.0, "scalar_gradient_leaks_to_contact")
    require(contact_attention_leakage == 0.0, "contact_gradient_leaks_to_attention_scalar")
    if model_lane == LANE_E:
        require(contact_norms["contact"] > 0.0, "contact_branch_gradient_missing")
        expected_shared = model.head.config.contact_encoder_gradient == "shared"
        require((contact_norms["shared_encoder"] > 0.0) == expected_shared, "contact_encoder_gradient_mode_mismatch")
    else:
        require(not roles["contact"] and contact_norms["contact"] == 0.0, "clean_lane_contact_role_present")
    return {
        "schema_version": "pvrig_v2_5_ortho_real_preoptimizer_telemetry_v1",
        "optimizer_constructed": False,
        "optimizer_steps": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "batch_candidates": len(batch["candidate_ids"]),
        "loss_values": {name: float(value.detach().float().cpu()) for name, value in parts.items()},
        "scalar_gradient_role_l2": scalar_norms,
        "contact_gradient_role_l2": contact_norms,
        "gates": {
            "scalar_to_contact_zero": scalar_contact_leakage == 0.0,
            "contact_to_attention_scalar_zero": contact_attention_leakage == 0.0,
            "contact_encoder_gradient_matches_mode": True,
        },
        "output_shapes": {name: list(value.shape) for name, value in output.items()},
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _input_receipt(args: argparse.Namespace, context: RealContext) -> dict[str, Any]:
    files = {
        "training_tsv": args.training_tsv,
        "marginal_contact": args.contact_tsv_gz,
        "pair_contact": args.pair_contact_tsv_gz,
        "split_manifest": args.split_manifest,
        "target_graph": args.target_graph_pt,
        "contact_formula": args.contact_formula_json,
        "v2_4_adapter": args.v2_4_adapter_path,
        "model_identity_file": args.model_identity_file,
    }
    receipt = {
        name: {"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for name, path in files.items()
    }
    require(receipt["v2_4_adapter"]["sha256"] == V24_ADAPTER_SHA256, "adapter_receipt_hash")
    require(receipt["contact_formula"]["sha256"] == CONTACT_FORMULA_SHA256, "contact_formula_hash")
    graph_files = {}
    for name in ("graph_manifest_v2.tsv", "graph_cache_receipt_v2.json", "graph_cache_v2.npz"):
        path = args.graph_cache_dir / name
        require(path.is_file() and not path.is_symlink(), f"graph_input_missing:{name}")
        graph_files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    return {
        "files": receipt,
        "graph_cache": {"path": str(args.graph_cache_dir.resolve()), "files": graph_files},
        "rows": len(context.rows),
        "parents": len({row.parent for row in context.rows}),
        "train_rows": len(context.train_indices),
        "score_rows": len(context.score_indices),
        "model_identity": context.model_identity,
    }


def run_preoptimizer(args: argparse.Namespace, context: RealContext) -> dict[str, Any]:
    require(not args.output_dir.exists(), "output_dir_exists")
    raw_batch = next(iter(context.batches(context.train_indices, True, 0)), None)
    require(raw_batch is not None, "preoptimizer_batch_missing")
    telemetry = preoptimizer_telemetry(
        context.model,
        context.lane_spec.model_lane,
        raw_batch,
        context.target_graphs,
        loss_config(context.lane_spec),
        device_name=args.device,
        precision=FROZEN_TRAINING["precision"],
    )
    args.output_dir.mkdir(parents=True)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_REAL1507_OUTER0_INNER0_PREOPTIMIZER",
        "mode": "preoptimizer",
        "lane": asdict(context.lane_spec),
        "source_split": asdict(context.manifest),
        "input_receipt": _input_receipt(args, context),
        "model_contract": model_contract(context.model.head.config, context.lane_spec.model_lane),
        "trainer_contract": trainer_contract(
            context.lane_spec.model_lane, context.model, loss_config(context.lane_spec),
        ),
        "telemetry": telemetry,
        "training_hyperparameters": dict(FROZEN_TRAINING),
        "optimizer_constructed": False,
        "optimizer_steps": 0,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "PREOPTIMIZER_RECEIPT.json", receipt)
    atomic_json(args.output_dir / "RESULT.json", receipt)
    return receipt


def _score_without_metrics(
    context: RealContext,
    *,
    device_name: str,
) -> list[dict[str, Any]]:
    device = torch.device(device_name)
    context.model.eval()
    targets = move_to_device(context.target_graphs, device)
    records = []
    with torch.no_grad():
        for raw_batch in context.batches(context.score_indices, False, 0):
            batch = move_to_device(raw_batch, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=FROZEN_TRAINING["precision"] == "bf16"):
                output = forward_lane(context.model, context.lane_spec.model_lane, batch, targets)
            receptor = output["receptor_predictions"].float().cpu()
            dual = output["exact_min_dual"].float().cpu()
            contact = output.get("contact_composite")
            if contact is not None:
                contact = contact.float().cpu()
            for item, candidate_id in enumerate(raw_batch["candidate_ids"]):
                require(abs(float(dual[item]) - min(float(receptor[item, 0]), float(receptor[item, 1]))) <= 1e-7, "score_exact_min")
                records.append(
                    {
                        "candidate_id": candidate_id,
                        "neural_R8": float(receptor[item, 0]),
                        "neural_R9": float(receptor[item, 1]),
                        "neural_Rdual": float(dual[item]),
                        "contact_score_R8": "" if contact is None else float(contact[item, 0]),
                        "contact_score_R9": "" if contact is None else float(contact[item, 1]),
                    }
                )
    require(len(records) == len(context.score_indices), "score_row_closure")
    return records


def run_training(args: argparse.Namespace, context: RealContext) -> dict[str, Any]:
    require(not args.output_dir.exists(), "output_dir_exists")
    if args.mode == "train-smoke":
        fixed_epochs = 1
        status = "PASS_REAL1507_OUTER0_INNER0_ONE_EPOCH_TECHNICAL_SMOKE"
    else:
        fixed_epochs = int(context.manifest.fixed_epochs)
        status = "PASS_REAL1507_WHOLE_PARENT_SPLIT_TRAINING"
    training = train_fixed_epochs(
        context.model,
        context.lane_spec.model_lane,
        lambda epoch: context.batches(context.train_indices, True, epoch),
        context.target_graphs,
        loss_config(context.lane_spec),
        optimizer_config(),
        fixed_epochs=fixed_epochs,
        device_name=args.device,
        precision=str(FROZEN_TRAINING["precision"]),
        gradient_clip=float(FROZEN_TRAINING["gradient_clip"]),
        gradient_accumulation=int(FROZEN_TRAINING["gradient_accumulation"]),
    )
    records = _score_without_metrics(context, device_name=args.device)
    args.output_dir.mkdir(parents=True)
    prediction_path = args.output_dir / "score_predictions_no_metrics.tsv"
    with prediction_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    checkpoint_path = args.output_dir / "neural_head.pt"
    head_state = {
        name: parameter.detach().cpu().clone()
        for name, parameter in context.model.named_parameters()
        if parameter.requires_grad
    }
    require(head_state and all(name.startswith("head.") for name in head_state), "checkpoint_head_only")
    atomic_torch_save(
        checkpoint_path,
        {
            "schema_version": "pvrig_v2_5_ortho_real_head_checkpoint_v1",
            "lane": context.lane_spec.variant,
            "source_split_id": context.manifest.split_id,
            "head_state": head_state,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "mode": args.mode,
        "lane": asdict(context.lane_spec),
        "source_split": asdict(context.manifest),
        "technical_smoke_epoch_override": args.mode == "train-smoke",
        "source_manifest_fixed_epochs_unchanged": int(context.manifest.fixed_epochs),
        "input_receipt": _input_receipt(args, context),
        "model_contract": model_contract(context.model.head.config, context.lane_spec.model_lane),
        "trainer_contract": trainer_contract(
            context.lane_spec.model_lane, context.model, loss_config(context.lane_spec),
        ),
        "training": training,
        "artifacts": {
            "predictions_no_metrics": {
                "path": prediction_path.name,
                "rows": len(records),
                "sha256": sha256_file(prediction_path),
            },
            "neural_head": {"path": checkpoint_path.name, "sha256": sha256_file(checkpoint_path)},
        },
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "TRAINING_RECEIPT.json", receipt)
    atomic_json(args.output_dir / "RESULT.json", receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--mode", choices=("preoptimizer", "train-smoke", "train"), required=True)
    value.add_argument("--lane-variant", choices=tuple(LANE_SPECS), required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--v2-4-adapter-path", type=Path, required=True)
    value.add_argument("--expected-v2-4-adapter-sha256", default=V24_ADAPTER_SHA256)
    value.add_argument("--v2-3-bundle-root", type=Path, required=True)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--contact-tsv-gz", type=Path, required=True)
    value.add_argument("--pair-contact-tsv-gz", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--target-graph-pt", type=Path, required=True)
    value.add_argument("--contact-formula-json", type=Path, required=True)
    value.add_argument("--split-manifest", type=Path, required=True)
    value.add_argument("--model-path", type=Path, required=True)
    value.add_argument("--model-identity-file", type=Path, required=True)
    value.add_argument("--expected-model-sha256", required=True)
    value.add_argument("--device", default="cuda")
    value.add_argument("--expected-rows", type=int, default=1269)
    value.add_argument("--expected-parents", type=int, default=28)
    value.add_argument("--expected-train-rows", type=int, default=1085)
    value.add_argument("--expected-score-rows", type=int, default=184)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    random.seed(int(FROZEN_TRAINING["seed"]))
    np.random.seed(int(FROZEN_TRAINING["seed"]))
    torch.manual_seed(int(FROZEN_TRAINING["seed"]))
    context = load_real_context(args)
    if args.mode == "preoptimizer":
        receipt = run_preoptimizer(args, context)
    else:
        receipt = run_training(args, context)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

