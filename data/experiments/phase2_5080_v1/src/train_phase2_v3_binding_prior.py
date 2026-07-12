#!/usr/bin/env python3
"""Train V3 and matched baselines using open development labels only."""
from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import torch
from torch import nn

from phase2_v3_contracts import sha256_file, write_csv_atomic, write_json_atomic
from phase2_v3_metrics import binary_ranking_metrics, macro_target_average_precision
from phase2_v3_model import (
    BindingPriorModel,
    EmbeddingBank,
    fixed_esm2_cosine,
    frame_pair_indices,
    load_embedding_bank,
    score_model,
    within_target_pairwise_loss,
)

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PREPARED = EXP_DIR / "prepared" / "phase2_v3_binding"
DEFAULT_CONFIG = EXP_DIR / "configs" / "phase2_v3_binding_prior.json"
DEFAULT_PREREG = EXP_DIR / "audits" / "phase2_v3_preregistration.json"
DEFAULT_TEST_SPEC = EXP_DIR / "audits" / "phase2_v3_test_spec.json"
DEFAULT_OUT = EXP_DIR / "runs" / "phase2_v3_binding"


@dataclass
class TrainConfig:
    records_csv: str = str(DEFAULT_PREPARED / "binding_train_dev_v3.csv")
    formal_blinded_csv: str = str(DEFAULT_PREPARED / "binding_formal_blinded_v3.csv")
    embedding_manifest: str = str(DEFAULT_PREPARED / "embeddings" / "embedding_manifest_v3.csv")
    preregistration_json: str = str(DEFAULT_PREREG)
    test_spec_json: str = str(DEFAULT_TEST_SPEC)
    source_config_json: str = str(DEFAULT_CONFIG)
    out_dir: str = str(DEFAULT_OUT)
    seeds: tuple[int, ...] = (43, 53, 67)
    epochs: int = 20
    batch_size: int = 1024
    inference_batch_size: int = 8192
    learning_rate: float = 5e-4
    weight_decay: float = 1e-4
    latent_dim: int = 192
    hidden_dim: int = 256
    dropout: float = 0.1
    pairwise_loss_weight: float = 0.25
    early_stopping_patience: int = 5
    device: str = "cuda"
    variants: tuple[str, ...] = ("vhh_only", "esm2_pair", "v3_full")


def load_source_config(path: Path) -> TrainConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TrainConfig(
        source_config_json=str(path),
        seeds=tuple(int(value) for value in payload["seeds"]),
        epochs=int(payload["epochs"]),
        batch_size=int(payload["batch_size"]),
        learning_rate=float(payload["learning_rate"]),
        weight_decay=float(payload["weight_decay"]),
        latent_dim=int(payload["latent_dim"]),
        hidden_dim=int(payload["hidden_dim"]),
        dropout=float(payload["dropout"]),
        pairwise_loss_weight=float(payload["pairwise_loss_weight"]),
        early_stopping_patience=int(payload["early_stopping_patience"]),
        device=str(payload["device"]),
        variants=tuple(str(value) for value in payload["variants"]),
    )


def read_development(path: Path) -> pd.DataFrame:
    columns = [
        "sample_id",
        "split",
        "target_id",
        "sequence_sha256",
        "target_sequence_sha256",
        "label",
        "sealed_status",
        "ground_truth_kind",
        "allowed_use",
    ]
    frame = pd.read_csv(path, usecols=columns)
    if set(frame["split"].astype(str)) != {"train", "dev"}:
        raise ValueError("V3 training records must contain only train and dev")
    if set(frame["sealed_status"].astype(str)) != {"OPEN_DEVELOPMENT"}:
        raise ValueError("V3 training labels must be open development labels")
    if set(frame["ground_truth_kind"].astype(str)) != {"real_assay_binary_binding"}:
        raise ValueError("V3 training accepts only real binary binding assays")
    if set(frame["allowed_use"].astype(str)) != {"GENERIC_BINDING_PRIOR_ONLY"}:
        raise ValueError("V3 training lane policy mismatch")
    if not set(frame["label"].astype(int).unique()).issubset({0, 1}):
        raise ValueError("V3 training requires binary labels")
    if frame["sample_id"].duplicated().any():
        raise ValueError("V3 training records contain duplicate pairs")
    return frame


def hash_embedding_shards(manifest_path: Path) -> dict[str, str]:
    manifest = pd.read_csv(manifest_path, usecols=["shard_path"])
    return {path: sha256_file(Path(path)) for path in manifest["shard_path"].astype(str).drop_duplicates()}


def resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was preregistered but is not available")
    return torch.device(requested)


def train_one(
    cfg: TrainConfig,
    variant: str,
    seed: int,
    control_kind: str,
    frame: pd.DataFrame,
    bank: EmbeddingBank,
    vhh_index: torch.Tensor,
    target_index: torch.Tensor,
    run_root: Path,
    artifact_hashes: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = resolve_device(cfg.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.set_float32_matmul_precision("high")
        torch.cuda.reset_peak_memory_stats(device)

    model = BindingPriorModel(
        variant=variant,
        esm2_dim=bank.esm2_dim,
        vhhbert_dim=bank.vhhbert_dim,
        physchem_dim=bank.physchem_dim,
        latent_dim=cfg.latent_dim,
        hidden_dim=cfg.hidden_dim,
        dropout=cfg.dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    labels = torch.tensor(frame["label"].astype(float).to_numpy(), dtype=torch.float32)
    target_codes = torch.tensor(pd.factorize(frame["target_id"].astype(str), sort=True)[0], dtype=torch.long)
    train_rows = torch.tensor(np.flatnonzero(frame["split"].astype(str).to_numpy() == "train"), dtype=torch.long)
    dev_rows = torch.tensor(np.flatnonzero(frame["split"].astype(str).to_numpy() == "dev"), dtype=torch.long)
    train_labels = labels[train_rows].clone()
    train_targets = target_index[train_rows].clone()
    generator = torch.Generator().manual_seed(seed + 10_000)
    if control_kind == "label_shuffle":
        train_labels = train_labels[torch.randperm(len(train_labels), generator=generator)]
    elif control_kind == "target_shuffle":
        train_targets = train_targets[torch.randperm(len(train_targets), generator=generator)]
    elif control_kind != "none":
        raise ValueError(f"Unsupported control kind: {control_kind}")

    positive = float(train_labels.sum())
    negative = float(len(train_labels) - positive)
    pos_weight = torch.tensor(negative / max(positive, 1.0), device=device)
    history = []
    best_metric = -1.0
    best_epoch = 0
    best_state = None
    stale = 0
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        order = torch.randperm(len(train_rows), generator=generator)
        losses = []
        for start in range(0, len(order), cfg.batch_size):
            local = order[start : start + cfg.batch_size]
            rows = train_rows[local]
            batch_vhh = vhh_index[rows].to(device)
            batch_target = train_targets[local].to(device)
            batch_labels = train_labels[local].to(device)
            batch_codes = target_codes[rows].to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(bank, batch_vhh, batch_target)
            bce = nn.functional.binary_cross_entropy_with_logits(logits, batch_labels, pos_weight=pos_weight)
            pair = within_target_pairwise_loss(logits, batch_labels, batch_codes)
            loss = bce + cfg.pairwise_loss_weight * pair
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite V3 loss for {variant}/{control_kind}/seed={seed}")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))

        dev_scores = score_model(
            model,
            bank,
            vhh_index[dev_rows],
            target_index[dev_rows],
            cfg.inference_batch_size,
            device,
        ).numpy()
        dev_labels = labels[dev_rows].numpy().astype(int)
        dev_targets = frame.iloc[dev_rows.numpy()]["target_id"].astype(str).tolist()
        dev_macro, _ = macro_target_average_precision(dev_labels, dev_scores, dev_targets)
        history.append({"epoch": epoch, "train_loss": statistics.mean(losses), "dev_macro_target_ap": dev_macro})
        if dev_macro > best_metric + 1e-12:
            best_metric = dev_macro
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= cfg.early_stopping_patience:
                break

    if best_state is None:
        raise RuntimeError("No V3 development-selected checkpoint was produced")
    model.load_state_dict(best_state)
    dev_scores = score_model(
        model,
        bank,
        vhh_index[dev_rows],
        target_index[dev_rows],
        cfg.inference_batch_size,
        device,
    ).numpy()
    dev_labels = labels[dev_rows].numpy().astype(int)
    dev_targets = frame.iloc[dev_rows.numpy()]["target_id"].astype(str).tolist()
    macro_ap, target_ap = macro_target_average_precision(dev_labels, dev_scores, dev_targets)
    metrics = binary_ranking_metrics(dev_labels, dev_scores)
    metrics.update({"macro_target_average_precision": macro_ap, "target_average_precision": target_ap})

    name = variant if control_kind == "none" else f"v3_full_{control_kind}"
    output_dir = run_root / name / f"seed_{seed}"
    output_dir.mkdir(parents=True, exist_ok=False)
    checkpoint = {
        "schema_version": "phase2_v3_binding_checkpoint_v1",
        "model_name": name,
        "variant": variant,
        "control_kind": control_kind,
        "seed": seed,
        "best_epoch": best_epoch,
        "best_dev_macro_target_ap": best_metric,
        "model_config": model.model_config,
        "state_dict": best_state,
        "embedding_config_sha256": bank.config_sha256,
        "artifact_hashes": artifact_hashes,
    }
    checkpoint_path = output_dir / "checkpoint.pt"
    torch.save(checkpoint, checkpoint_path)
    np.save(output_dir / "dev_scores.npy", dev_scores)
    telemetry = {
        "device": str(device),
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "cuda_peak_allocated_mib": (
            float(torch.cuda.max_memory_allocated(device)) / 1024.0 / 1024.0 if device.type == "cuda" else None
        ),
        "elapsed_seconds": time.perf_counter() - started,
    }
    result = {
        "model_name": name,
        "variant": variant,
        "control_kind": control_kind,
        "seed": seed,
        "best_epoch": best_epoch,
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "dev_scores_npy": str(output_dir / "dev_scores.npy"),
        "dev_scores_sha256": sha256_file(output_dir / "dev_scores.npy"),
        "dev_metrics": metrics,
        "history": history,
        "telemetry": telemetry,
    }
    write_json_atomic(output_dir / "metrics.json", result)
    return result


def ensemble_dev_scores(results: Sequence[dict[str, Any]]) -> np.ndarray:
    return np.mean([np.load(result["dev_scores_npy"]) for result in results], axis=0)


def train(cfg: TrainConfig) -> dict[str, Any]:
    prereg = json.loads(Path(cfg.preregistration_json).read_text(encoding="utf-8"))
    preregistered_seeds = tuple(int(value) for value in prereg["seeds"])
    if not cfg.seeds or not set(cfg.seeds).issubset(preregistered_seeds):
        raise ValueError("Resolved seeds are not a non-empty preregistered subset")
    frame = read_development(Path(cfg.records_csv))
    bank_cpu = load_embedding_bank(Path(cfg.embedding_manifest))
    vhh_index, target_index = frame_pair_indices(frame, bank_cpu)
    device = resolve_device(cfg.device)
    bank = bank_cpu.to(device)

    timestamp = datetime.now(timezone.utc).strftime("phase2_v3_binding_%Y%m%dT%H%M%S_%fZ")
    run_root = Path(cfg.out_dir) / timestamp
    run_root.mkdir(parents=True, exist_ok=False)
    write_json_atomic(run_root / "config_resolved.json", asdict(cfg))
    artifact_hashes = {
        "records_csv": sha256_file(Path(cfg.records_csv)),
        "formal_blinded_csv": sha256_file(Path(cfg.formal_blinded_csv)),
        "embedding_manifest": sha256_file(Path(cfg.embedding_manifest)),
        "embedding_shards": hash_embedding_shards(Path(cfg.embedding_manifest)),
        "preregistration_json": sha256_file(Path(cfg.preregistration_json)),
        "test_spec_json": sha256_file(Path(cfg.test_spec_json)),
        "source_config_json": sha256_file(Path(cfg.source_config_json)),
        "config_resolved_json": sha256_file(run_root / "config_resolved.json"),
    }
    write_json_atomic(run_root / "frozen_artifacts.json", artifact_hashes)

    results: dict[str, list[dict[str, Any]]] = {}
    for variant in cfg.variants:
        results[variant] = [
            train_one(cfg, variant, seed, "none", frame, bank, vhh_index, target_index, run_root, artifact_hashes)
            for seed in cfg.seeds
        ]
    results["v3_full_label_shuffle"] = [
        train_one(cfg, "v3_full", cfg.seeds[0], "label_shuffle", frame, bank, vhh_index, target_index, run_root, artifact_hashes)
    ]
    results["v3_full_target_shuffle"] = [
        train_one(cfg, "v3_full", cfg.seeds[0], "target_shuffle", frame, bank, vhh_index, target_index, run_root, artifact_hashes)
    ]

    dev_mask = frame["split"].astype(str).eq("dev").to_numpy()
    dev_rows = torch.tensor(np.flatnonzero(dev_mask), dtype=torch.long)
    dev_labels = frame.loc[dev_mask, "label"].astype(int).to_numpy()
    dev_targets = frame.loc[dev_mask, "target_id"].astype(str).tolist()
    prevalence = float(frame.loc[frame["split"].astype(str).eq("train"), "label"].mean())
    fixed_scores = {
        "prevalence": np.full(dev_mask.sum(), prevalence, dtype=np.float64),
        "frozen_esm2_cosine": fixed_esm2_cosine(
            bank, vhh_index[dev_rows].to(device), target_index[dev_rows].to(device)
        ).detach().cpu().numpy(),
    }
    ensemble_scores = {name: ensemble_dev_scores(items) for name, items in results.items()}
    dev_metrics: dict[str, Any] = {}
    for name, scores in {**fixed_scores, **ensemble_scores}.items():
        metrics = binary_ranking_metrics(dev_labels, scores)
        macro_ap, target_ap = macro_target_average_precision(dev_labels, scores, dev_targets)
        metrics.update({"macro_target_average_precision": macro_ap, "target_average_precision": target_ap})
        dev_metrics[name] = metrics

    baseline_order = [str(value) for value in prereg["eligible_baselines"]]
    strongest = max(
        baseline_order,
        key=lambda name: (float(dev_metrics[name]["macro_target_average_precision"]), -baseline_order.index(name)),
    )
    selection = {
        "schema_version": "phase2_v3_development_baseline_selection_v1",
        "selected_baseline": strongest,
        "selection_metric": "macro_target_average_precision",
        "selection_scope": "DEVELOPMENT_ONLY_BEFORE_FORMAL_UNSEAL",
        "candidate_metrics": {name: dev_metrics[name]["macro_target_average_precision"] for name in baseline_order},
        "formal_metrics_consulted": False,
    }
    write_json_atomic(run_root / "preregistered_baseline_selection.json", selection)
    selection_hash = sha256_file(run_root / "preregistered_baseline_selection.json")

    prediction_rows = []
    dev_frame = frame.loc[dev_mask, ["sample_id", "target_id", "label"]].reset_index(drop=True)
    for index, row in dev_frame.iterrows():
        output = row.to_dict()
        for name, scores in {**fixed_scores, **ensemble_scores}.items():
            output[name] = float(scores[index])
        prediction_rows.append(output)
    write_csv_atomic(run_root / "dev_predictions.csv", prediction_rows, list(prediction_rows[0]))

    summary = {
        "schema_version": "phase2_v3_binding_train_summary_v1",
        "run_dir": str(run_root),
        "seeds": list(cfg.seeds),
        "results": results,
        "development_metrics": dev_metrics,
        "preregistered_baseline_selection": selection,
        "preregistered_baseline_selection_sha256": selection_hash,
        "artifact_hashes": artifact_hashes,
        "embedding_config_sha256": bank.config_sha256,
        "formal_unseal_status": "SEALED_LABELS_NOT_READ",
        "claim_boundary": "generic_binary_binding_prior_not_pvrig_blocking_truth",
    }
    write_json_atomic(run_root / "train_summary.json", summary)
    print(json.dumps({"run_dir": str(run_root), "selected_baseline": strongest}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--records-csv", default="")
    parser.add_argument("--formal-blinded-csv", default="")
    parser.add_argument("--embedding-manifest", default="")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> TrainConfig:
    cfg = load_source_config(args.config)
    if args.records_csv:
        cfg.records_csv = args.records_csv
    if args.formal_blinded_csv:
        cfg.formal_blinded_csv = args.formal_blinded_csv
    if args.embedding_manifest:
        cfg.embedding_manifest = args.embedding_manifest
    if args.out_dir:
        cfg.out_dir = args.out_dir
    if args.device:
        cfg.device = args.device
    if args.smoke:
        cfg.epochs = 2
        cfg.early_stopping_patience = 1
        cfg.seeds = (43,)
        cfg.variants = ("vhh_only", "esm2_pair", "v3_full")
    return cfg


def main() -> None:
    train(config_from_args(parse_args()))


if __name__ == "__main__":
    main()
