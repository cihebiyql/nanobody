#!/usr/bin/env python3
"""Synthesize the frozen three-seed V3-G2 decision and external comparison.

The primary decision is made on the cluster-safe internal test against the
development-selected mean-pooled baseline.  The hTNFa block was opened by the
earlier V3 run, so it is reported only as an external comparison.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import train_phase2_v2_3 as v23  # noqa: E402
import train_phase2_v3_g2_generic as g2  # noqa: E402
from phase2_v3_contracts import sha256_file, write_json_atomic  # noqa: E402
from phase2_v3_metrics import binary_ranking_metrics, macro_target_average_precision  # noqa: E402
from phase2_v3_model import (  # noqa: E402
    BindingPriorModel,
    frame_pair_indices,
    load_embedding_bank,
    score_model,
)

DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_g2/binding_cluster_safe_v1.csv"
DEFAULT_PREREG = EXP_DIR / "audits/phase2_v3_g2_preregistration.json"
DEFAULT_RUN_ROOT = EXP_DIR / "runs/phase2_v3_g2_generic"
DEFAULT_MEANPOOL_ROOT = EXP_DIR / "runs/phase2_v3_g2_meanpool_baselines"
DEFAULT_SOURCE_CHECKPOINT = EXP_DIR / "checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt"
DEFAULT_SITE = EXP_DIR / "data_splits/zym_site_split_manifest_v2_clustered.csv"
DEFAULT_CONTACT = EXP_DIR / "prepared/structure_contact_maps_v3_clustered.jsonl"
DEFAULT_V23_CACHE = EXP_DIR / "prepared/esm2_8m_v2_3_cache/manifest.csv"
DEFAULT_V23_CDR = EXP_DIR / "data_splits/vhh_cdr_type_masks_v2_3.csv"
DEFAULT_EXTERNAL = EXP_DIR / "prepared/phase2_v3_g2/external_hTNFa_evaluation_v1.csv"
DEFAULT_EXTERNAL_CACHE = EXP_DIR / "prepared/phase2_v3_g2/esm2_8m_external_hTNFa_eval_cache_v1/manifest.csv"
DEFAULT_EXTERNAL_CDR = EXP_DIR / "prepared/phase2_v3_g2/external_hTNFa_vhh_cdr_type_masks_v1.csv"
DEFAULT_MEANPOOL_EMBEDDINGS = EXP_DIR / "prepared/phase2_v3_binding/embeddings/embedding_manifest_v3.csv"
DEFAULT_OUTPUT = EXP_DIR / "runs/phase2_v3_g2_final_evaluation_v1"
SEEDS = (83, 89, 97)
CLAIM_BOUNDARY = "generic_binding_prior_not_pvrig_binding_affinity_docking_or_blocking_truth"
EXTERNAL_BOUNDARY = "external_hTNFa_was_previously_unsealed_and_is_not_a_pristine_formal_test"


def latest_path(root: Path, name: str) -> Path:
    paths = sorted(root.glob(f"*/{name}"), key=lambda path: path.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No {name} under {root}")
    return paths[-1]


def complete_seed_summaries(run_root: Path, seeds: Sequence[int] = SEEDS) -> dict[int, Path]:
    output: dict[int, Path] = {}
    for seed in seeds:
        candidates = []
        for path in run_root.glob(f"*seed{seed}/summary.json"):
            summary = json.loads(path.read_text(encoding="utf-8"))
            if summary.get("status") == "PASS_V3_G2_TRAINING_COMPLETED" and int(summary.get("seed", -1)) == seed:
                candidates.append(path)
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one completed seed {seed} run, found {len(candidates)}")
        output[seed] = candidates[0]
    return output


def metric_bundle(labels: np.ndarray, scores: np.ndarray, targets: Sequence[str]) -> dict[str, Any]:
    metrics = binary_ranking_metrics(labels.astype(np.int64), scores.astype(np.float64))
    macro, per_target = macro_target_average_precision(
        labels.astype(np.int64), scores.astype(np.float64), targets
    )
    metrics.update({"macro_target_auprc": macro, "per_target_auprc": per_target})
    return metrics


def cluster_bootstrap_macro_delta(
    frame: pd.DataFrame,
    candidate_scores: np.ndarray,
    baseline_scores: np.ndarray,
    replicates: int,
    seed: int,
) -> dict[str, float | int]:
    if len(frame) != len(candidate_scores) or len(frame) != len(baseline_scores):
        raise ValueError("Bootstrap frame and score lengths differ")
    if replicates <= 0:
        raise ValueError("Bootstrap replicates must be positive")
    clusters = frame["cluster_id"].astype(str).to_numpy()
    labels = frame["label"].astype(int).to_numpy()
    targets = frame["target_id"].astype(str).to_numpy()
    unique_clusters = sorted(set(clusters))
    groups = [np.flatnonzero(clusters == cluster) for cluster in unique_clusters]
    observed = (
        macro_target_average_precision(labels, candidate_scores, targets.tolist())[0]
        - macro_target_average_precision(labels, baseline_scores, targets.tolist())[0]
    )
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(replicates):
        sampled = rng.integers(0, len(groups), size=len(groups))
        indices = np.concatenate([groups[index] for index in sampled])
        candidate = macro_target_average_precision(
            labels[indices], candidate_scores[indices], targets[indices].tolist()
        )[0]
        baseline = macro_target_average_precision(
            labels[indices], baseline_scores[indices], targets[indices].tolist()
        )[0]
        deltas.append(candidate - baseline)
    values = np.asarray(deltas, dtype=np.float64)
    return {
        "unit": "vhh_mmseqs_cluster",
        "cluster_count": len(unique_clusters),
        "replicates": replicates,
        "seed": seed,
        "observed_delta": float(observed),
        "ci95_lower": float(np.quantile(values, 0.025)),
        "ci95_upper": float(np.quantile(values, 0.975)),
        "bootstrap_probability_delta_le_zero": float(np.mean(values <= 0.0)),
    }


def load_internal_predictions(
    binding_path: Path,
    seed_summaries: Mapping[int, Path],
    baseline_summary_path: Path,
) -> tuple[pd.DataFrame, dict[int, dict[str, Any]], dict[str, Any]]:
    binding = pd.read_csv(binding_path)
    test = binding.loc[
        binding["split"].astype(str).eq("test"),
        ["sample_id", "dataset_id", "target_id", "cluster_id", "label"],
    ].copy()
    if test["sample_id"].duplicated().any():
        raise ValueError("Internal test sample IDs are not unique")
    seed_metadata: dict[int, dict[str, Any]] = {}
    merged = test
    for seed, summary_path in seed_summaries.items():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        prediction_path = summary_path.parent / "test_predictions.csv"
        prediction = pd.read_csv(prediction_path)
        keep = prediction[["sample_id", "label", "score", "cross_family_swap_score", "cross_family_swap_valid"]].copy()
        keep = keep.rename(
            columns={
                "label": f"label_seed_{seed}",
                "score": f"score_seed_{seed}",
                "cross_family_swap_score": f"swap_score_seed_{seed}",
                "cross_family_swap_valid": f"swap_valid_seed_{seed}",
            }
        )
        merged = merged.merge(keep, on="sample_id", how="left", validate="one_to_one")
        if merged[f"score_seed_{seed}"].isna().any():
            raise ValueError(f"Seed {seed} predictions do not cover the internal test")
        if not np.array_equal(merged["label"].astype(int), merged[f"label_seed_{seed}"].astype(int)):
            raise ValueError(f"Seed {seed} labels differ from the frozen binding table")
        seed_metadata[seed] = summary

    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
    baseline_name = str(baseline_summary["strongest_baseline_selected_on_dev"])
    baseline_predictions = pd.read_csv(baseline_summary["test_predictions"])
    baseline_keep = baseline_predictions[["sample_id", baseline_name]].rename(columns={baseline_name: "baseline_score"})
    merged = merged.merge(baseline_keep, on="sample_id", how="left", validate="one_to_one")
    if merged["baseline_score"].isna().any():
        raise ValueError("Mean-pooled baseline predictions do not cover the internal test")
    merged["ensemble_score"] = merged[[f"score_seed_{seed}" for seed in seed_summaries]].mean(axis=1)
    merged["ensemble_swap_score"] = merged[[f"swap_score_seed_{seed}" for seed in seed_summaries]].mean(axis=1)
    return merged, seed_metadata, baseline_summary


def internal_decision(
    predictions: pd.DataFrame,
    seed_metadata: Mapping[int, dict[str, Any]],
    baseline_summary: dict[str, Any],
    bootstrap_replicates: int,
) -> dict[str, Any]:
    labels = predictions["label"].astype(int).to_numpy()
    targets = predictions["target_id"].astype(str).tolist()
    baseline_metrics = metric_bundle(labels, predictions["baseline_score"].to_numpy(), targets)
    ensemble_metrics = metric_bundle(labels, predictions["ensemble_score"].to_numpy(), targets)
    seed_metrics = {
        str(seed): metric_bundle(labels, predictions[f"score_seed_{seed}"].to_numpy(), targets)
        for seed in seed_metadata
    }
    bootstrap = cluster_bootstrap_macro_delta(
        predictions,
        predictions["ensemble_score"].to_numpy(),
        predictions["baseline_score"].to_numpy(),
        bootstrap_replicates,
        20260713,
    )
    valid = predictions[[f"swap_valid_seed_{seed}" for seed in seed_metadata]].all(axis=1).to_numpy(dtype=bool)
    positive = predictions["label"].astype(int).to_numpy() == 1
    target_margin = float(
        np.mean(
            predictions.loc[valid & positive, "ensemble_score"].to_numpy()
            - predictions.loc[valid & positive, "ensemble_swap_score"].to_numpy()
        )
    )
    observed_wins = {
        str(seed): float(summary["test_observed_contrast"]["observed_target_contrast_win_rate"])
        for seed, summary in seed_metadata.items()
    }
    mean_observed_win = float(np.mean(list(observed_wins.values())))
    baseline_macro = float(baseline_metrics["macro_target_auprc"])
    seed_wins = sum(float(metrics["macro_target_auprc"]) > baseline_macro for metrics in seed_metrics.values())
    checks = {
        "ensemble_exceeds_development_selected_baseline": float(ensemble_metrics["macro_target_auprc"]) > baseline_macro,
        "cluster_bootstrap_ci_lower_gt_zero": float(bootstrap["ci95_lower"]) > 0.0,
        "at_least_two_seeds_exceed_baseline": seed_wins >= 2,
        "target_dependence_positive_margin": target_margin > 0.0,
        "observed_target_contrast_win_rate_ge_0_55": mean_observed_win >= 0.55,
    }
    return {
        "baseline_name": baseline_summary["strongest_baseline_selected_on_dev"],
        "baseline_metrics": baseline_metrics,
        "ensemble_metrics": ensemble_metrics,
        "seed_metrics": seed_metrics,
        "seed_count_exceeding_baseline": seed_wins,
        "cluster_bootstrap": bootstrap,
        "target_dependence": {
            "ensemble_positive_true_minus_cross_family_swap": target_margin,
            "per_seed_observed_target_contrast_win_rate": observed_wins,
            "seed_mean_observed_target_contrast_win_rate": mean_observed_win,
        },
        "checks": checks,
    }


def replay_retention(
    seed_summaries: Mapping[int, Path],
    source_checkpoint_path: Path,
    site_path: Path,
    contact_path: Path,
    cache_path: Path,
    cdr_path: Path,
    device: torch.device,
) -> dict[str, Any]:
    source = torch.load(source_checkpoint_path, map_location="cpu", weights_only=False)
    cfg = v23.Config(**source["cfg"])
    cache = v23.ESM2Cache(cache_path, cfg.esm_dim)
    cdrs = v23.CDRMaskStore(cdr_path)
    site = v23.SiteDataset(site_path, "val", cfg, cache, cdrs)
    contact = v23.ContactDataset(contact_path, "val", cfg, cache, cdrs)
    site_loader = DataLoader(site, batch_size=cfg.batch_site, shuffle=False, collate_fn=v23.collate_site)
    contact_loader = DataLoader(contact, batch_size=cfg.batch_contact, shuffle=False, collate_fn=v23.collate_contact)
    source_record = source["history"][int(source["epoch"]) - 1]
    source_metrics = {
        "contact_auprc": float(source_record["val_contact_auprc"]),
        "paratope_auprc": float(source_record["val_paratope_auprc"]),
    }
    per_seed: dict[str, dict[str, float]] = {}
    for seed, summary_path in seed_summaries.items():
        checkpoint = torch.load(summary_path.parent / "checkpoint.pt", map_location="cpu", weights_only=False)
        model = v23.CrossContactNetV23(v23.Config(**checkpoint["backbone_cfg"]))
        model.load_state_dict(checkpoint["model"])
        model.to(device)
        contact_metrics = v23.eval_contact(model, contact_loader, device, cfg)
        site_metrics = v23.eval_site(model, site_loader, device)
        per_seed[str(seed)] = {
            "contact_auprc": float(contact_metrics["contact_auprc"]),
            "paratope_auprc": float(site_metrics["paratope_auprc"]),
        }
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()
    means = {
        name: float(np.mean([metrics[name] for metrics in per_seed.values()]))
        for name in ("contact_auprc", "paratope_auprc")
    }
    ratios = {name: means[name] / source_metrics[name] for name in means}
    checks = {f"{name}_retained_ge_90pct": ratio >= 0.90 for name, ratio in ratios.items()}
    return {
        "source_validation_metrics": source_metrics,
        "per_seed_validation_metrics": per_seed,
        "three_seed_mean": means,
        "retention_ratio": ratios,
        "checks": checks,
    }


class ExternalDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, cfg: v23.Config, cache: g2.CompactESM2Cache, cdrs: v23.CDRMaskStore):
        self.frame = frame.reset_index(drop=True)
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.frame.loc[index]
        vhh_sequence = str(row["vhh_sequence"])
        target_sequence = str(row["target_sequence"])
        vhh = self.cache.get(vhh_sequence, self.cfg.max_vhh_len)
        antigen = self.cache.get(target_sequence, self.cfg.max_antigen_len)
        return {
            "sample_id": str(row["sample_id"]),
            "dataset_id": str(row["dataset_id"]),
            "target_id": str(row["target_id"]),
            "vhh": vhh,
            "cdr": self.cdrs.get(vhh_sequence, self.cfg.max_vhh_len)[: len(vhh)],
            "antigen": antigen,
            "swap_antigen": antigen,
            "swap_valid": False,
            "label": float(row["label"]),
        }


def score_external_residue(
    frame: pd.DataFrame,
    seed_summaries: Mapping[int, Path],
    cache_path: Path,
    cdr_path: Path,
    device: torch.device,
    batch_size: int,
) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    first_checkpoint = torch.load(next(iter(seed_summaries.values())).parent / "checkpoint.pt", map_location="cpu", weights_only=False)
    cfg = v23.Config(**first_checkpoint["backbone_cfg"])
    cache = g2.CompactESM2Cache(cache_path, cfg.esm_dim, max_cached_shards=16)
    cdrs = v23.CDRMaskStore(cdr_path)
    dataset = ExternalDataset(frame, cfg, cache, cdrs)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=g2.binding_collate)
    output: dict[int, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    for seed, summary_path in seed_summaries.items():
        checkpoint_path = summary_path.parent / "checkpoint.pt"
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        model = v23.CrossContactNetV23(v23.Config(**checkpoint["backbone_cfg"]))
        model.load_state_dict(checkpoint["model"])
        model.to(device)
        _, rows = g2.evaluate_binding(model, loader, device, device.type == "cuda", max_batches=0)
        ordered = pd.DataFrame(rows).set_index("sample_id").loc[frame["sample_id"].astype(str)]
        output[seed] = ordered["score"].to_numpy(dtype=np.float64)
        metadata[str(seed)] = {
            "checkpoint": str(checkpoint_path),
            "checkpoint_sha256": sha256_file(checkpoint_path),
        }
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()
    return output, metadata


def score_external_meanpool(
    frame: pd.DataFrame,
    baseline_summary: dict[str, Any],
    embedding_manifest: Path,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    train_summary = json.loads(Path(baseline_summary["train_summary"]).read_text(encoding="utf-8"))
    baseline_name = str(baseline_summary["strongest_baseline_selected_on_dev"])
    if baseline_name not in train_summary["results"]:
        raise ValueError(f"Missing mean-pooled baseline variant {baseline_name}")
    bank_cpu = load_embedding_bank(embedding_manifest)
    vhh_index, target_index = frame_pair_indices(frame, bank_cpu)
    bank = bank_cpu.to(device)
    scores = []
    checkpoints = []
    for result in train_summary["results"][baseline_name]:
        path = Path(result["checkpoint"])
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        model = BindingPriorModel(**checkpoint["model_config"])
        model.load_state_dict(checkpoint["state_dict"])
        model.to(device)
        scores.append(score_model(model, bank, vhh_index, target_index, batch_size, device).numpy())
        checkpoints.append({"seed": int(checkpoint["seed"]), "path": str(path), "sha256": sha256_file(path)})
        del model
    return np.mean(scores, axis=0), {"variant": baseline_name, "checkpoints": checkpoints}


def external_comparison(
    external_path: Path,
    seed_summaries: Mapping[int, Path],
    baseline_summary: dict[str, Any],
    cache_path: Path,
    cdr_path: Path,
    embedding_manifest: Path,
    device: torch.device,
    batch_size: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(external_path)
    residue_scores, residue_meta = score_external_residue(frame, seed_summaries, cache_path, cdr_path, device, batch_size)
    baseline_scores, baseline_meta = score_external_meanpool(frame, baseline_summary, embedding_manifest, device, batch_size * 32)
    predictions = frame[["sample_id", "label", "target_id", "sequence_sha256"]].copy()
    for seed, values in residue_scores.items():
        predictions[f"score_seed_{seed}"] = values
    predictions["ensemble_score"] = np.mean(list(residue_scores.values()), axis=0)
    predictions["baseline_score"] = baseline_scores
    labels = predictions["label"].astype(int).to_numpy()
    targets = predictions["target_id"].astype(str).tolist()
    summary = {
        "claim_boundary": EXTERNAL_BOUNDARY,
        "rows": len(predictions),
        "positive_count": int(labels.sum()),
        "baseline_metrics": metric_bundle(labels, baseline_scores, targets),
        "ensemble_metrics": metric_bundle(labels, predictions["ensemble_score"].to_numpy(), targets),
        "seed_metrics": {
            str(seed): metric_bundle(labels, values, targets) for seed, values in residue_scores.items()
        },
        "residue_checkpoints": residue_meta,
        "meanpool": baseline_meta,
    }
    return predictions, summary


def write_report(path: Path, summary: dict[str, Any]) -> None:
    internal = summary["internal_cluster_safe_test"]
    checks = summary["acceptance_checks"]
    lines = [
        "# Phase 2 V3-G2 三种子最终判定",
        "",
        f"- 结论：**{summary['status']}**",
        f"- 部署方法：`{summary['deployment_method']}`",
        f"- residue ensemble test macro target AUPRC：`{internal['ensemble_metrics']['macro_target_auprc']:.6f}`",
        f"- mean-pooled baseline test macro target AUPRC：`{internal['baseline_metrics']['macro_target_auprc']:.6f}`",
        f"- cluster bootstrap delta 95% CI：`[{internal['cluster_bootstrap']['ci95_lower']:.6f}, {internal['cluster_bootstrap']['ci95_upper']:.6f}]`",
        "",
        "## 验收门",
        "",
    ]
    lines.extend(f"- {name}: `{'PASS' if value else 'FAIL'}`" for name, value in checks.items())
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "V3-G2 只是通用 target-conditioned binding/contact prior，不是 PVRIG 结合、Kd、docking 正确性或阻断真值。",
            "external hTNFa 在旧 V3 中已经解封，本报告只将其作为外部比较，不宣称为新的 untouched formal test。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


@dataclass
class EvaluationConfig:
    binding: Path
    preregistration: Path
    run_root: Path
    baseline_summary: Path
    source_checkpoint: Path
    site: Path
    contact: Path
    v23_cache: Path
    v23_cdr: Path
    external: Path
    external_cache: Path
    external_cdr: Path
    meanpool_embeddings: Path
    output_dir: Path
    device: str
    batch_size: int
    bootstrap_replicates: int
    skip_replay: bool
    skip_external: bool


def evaluate(config: EvaluationConfig) -> dict[str, Any]:
    prereg = json.loads(config.preregistration.read_text(encoding="utf-8"))
    frozen_seeds = tuple(int(value) for value in prereg["seeds"])
    if frozen_seeds != SEEDS:
        raise ValueError(f"Unexpected frozen seeds: {frozen_seeds}")
    seed_summaries = complete_seed_summaries(config.run_root, frozen_seeds)
    predictions, seed_metadata, baseline_summary = load_internal_predictions(
        config.binding, seed_summaries, config.baseline_summary
    )
    internal = internal_decision(predictions, seed_metadata, baseline_summary, config.bootstrap_replicates)
    device = torch.device(config.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    replay = None
    if not config.skip_replay:
        replay = replay_retention(
            seed_summaries,
            config.source_checkpoint,
            config.site,
            config.contact,
            config.v23_cache,
            config.v23_cdr,
            device,
        )

    external_predictions = None
    external = None
    if not config.skip_external:
        external_predictions, external = external_comparison(
            config.external,
            seed_summaries,
            baseline_summary,
            config.external_cache,
            config.external_cdr,
            config.meanpool_embeddings,
            device,
            config.batch_size,
        )

    checks = dict(internal["checks"])
    if replay is None:
        checks["contact_replay_retention"] = False
        checks["paratope_replay_retention"] = False
    else:
        checks["contact_replay_retention"] = replay["checks"]["contact_auprc_retained_ge_90pct"]
        checks["paratope_replay_retention"] = replay["checks"]["paratope_auprc_retained_ge_90pct"]
    primary_candidate = all(internal["checks"].values()) and all(
        replay["checks"].values() if replay is not None else [False]
    )
    # Null models are only worth their GPU cost after the candidate clears all
    # efficacy and replay gates.  They were not needed to reject this version.
    checks["null_controls"] = False
    null_status = "REQUIRED_BEFORE_PROMOTION" if primary_candidate else "NOT_RUN_CANDIDATE_ALREADY_FAILED_PRIMARY_GATES"
    passed = all(checks.values())
    status = "PASS_PROMOTE_V3_G2" if passed else "FAIL_FALLBACK_TO_MEANPOOL_V3_FULL"
    deployment = "v3_g2_residue_ensemble" if passed else str(internal["baseline_name"])

    config.output_dir.mkdir(parents=True, exist_ok=True)
    internal_path = config.output_dir / "internal_cluster_safe_test_predictions.csv"
    predictions.to_csv(internal_path, index=False)
    external_path = None
    if external_predictions is not None:
        external_path = config.output_dir / "external_hTNFa_comparison_predictions.csv"
        external_predictions.to_csv(external_path, index=False)
    summary: dict[str, Any] = {
        "status": status,
        "schema_version": "phase2_v3_g2_final_evaluation_v1",
        "deployment_method": deployment,
        "acceptance_checks": checks,
        "null_control_status": null_status,
        "internal_cluster_safe_test": internal,
        "contact_site_replay": replay,
        "external_hTNFa_comparison": external,
        "seeds": list(frozen_seeds),
        "seed_summaries": {str(seed): str(path) for seed, path in seed_summaries.items()},
        "baseline_summary": str(config.baseline_summary),
        "artifact_sha256": {
            "binding": sha256_file(config.binding),
            "preregistration": sha256_file(config.preregistration),
            "baseline_summary": sha256_file(config.baseline_summary),
            "internal_predictions": sha256_file(internal_path),
            **({"external_predictions": sha256_file(external_path)} if external_path else {}),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json_atomic(config.output_dir / "final_evaluation_summary.json", summary)
    write_report(config.output_dir / "PHASE2_V3_G2_FINAL_EVALUATION_ZH.md", summary)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--baseline-summary", type=Path)
    parser.add_argument("--meanpool-root", type=Path, default=DEFAULT_MEANPOOL_ROOT)
    parser.add_argument("--source-checkpoint", type=Path, default=DEFAULT_SOURCE_CHECKPOINT)
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--contact", type=Path, default=DEFAULT_CONTACT)
    parser.add_argument("--v23-cache", type=Path, default=DEFAULT_V23_CACHE)
    parser.add_argument("--v23-cdr", type=Path, default=DEFAULT_V23_CDR)
    parser.add_argument("--external", type=Path, default=DEFAULT_EXTERNAL)
    parser.add_argument("--external-cache", type=Path, default=DEFAULT_EXTERNAL_CACHE)
    parser.add_argument("--external-cdr", type=Path, default=DEFAULT_EXTERNAL_CDR)
    parser.add_argument("--meanpool-embeddings", type=Path, default=DEFAULT_MEANPOOL_EMBEDDINGS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--skip-external", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    baseline_summary = args.baseline_summary or latest_path(args.meanpool_root, "cluster_safe_test_summary.json")
    summary = evaluate(
        EvaluationConfig(
            binding=args.binding,
            preregistration=args.preregistration,
            run_root=args.run_root,
            baseline_summary=baseline_summary,
            source_checkpoint=args.source_checkpoint,
            site=args.site,
            contact=args.contact,
            v23_cache=args.v23_cache,
            v23_cdr=args.v23_cdr,
            external=args.external,
            external_cache=args.external_cache,
            external_cdr=args.external_cdr,
            meanpool_embeddings=args.meanpool_embeddings,
            output_dir=args.output_dir,
            device=args.device,
            batch_size=args.batch_size,
            bootstrap_replicates=args.bootstrap_replicates,
            skip_replay=args.skip_replay,
            skip_external=args.skip_external,
        )
    )
    print(json.dumps({"status": summary["status"], "deployment_method": summary["deployment_method"]}, indent=2))


if __name__ == "__main__":
    main()
