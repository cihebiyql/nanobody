#!/usr/bin/env python3
"""Run the one-shot sealed formal evaluation for a trained V3 run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from phase2_v3_contracts import sha256_file, write_csv_atomic, write_json_atomic
from phase2_v3_metrics import (
    binary_ranking_metrics,
    formal_gate_decision,
    paired_bootstrap_ap_delta,
    paired_permutation_ap_test,
)
from phase2_v3_model import (
    fixed_esm2_cosine,
    frame_pair_indices,
    load_embedding_bank,
    model_from_checkpoint,
    score_model,
)

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_LABELS = EXP_DIR / "prepared" / "phase2_v3_binding" / "binding_formal_labels_sealed_v3.csv"


def verify(path: Path, expected: str, label: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"Frozen {label} SHA256 mismatch: expected {expected}, observed {observed}")


def load_blinded(path: Path) -> pd.DataFrame:
    columns = [
        "sample_id",
        "formal_block",
        "target_id",
        "sequence_sha256",
        "target_sequence_sha256",
        "sealed_status",
    ]
    frame = pd.read_csv(path, usecols=columns)
    if set(frame["sealed_status"].astype(str)) != {"SEALED_LABELS"}:
        raise ValueError("Formal blinded rows must remain sealed")
    if frame["sample_id"].duplicated().any():
        raise ValueError("Formal blinded rows contain duplicate sample IDs")
    return frame


def merge_labels(blinded: pd.DataFrame, labels_path: Path) -> pd.DataFrame:
    labels = pd.read_csv(labels_path, usecols=["sample_id", "formal_block", "label", "sealed_status"])
    if labels["sample_id"].duplicated().any() or set(labels["sealed_status"].astype(str)) != {"SEALED_LABELS"}:
        raise ValueError("Malformed V3 sealed labels")
    if set(blinded["sample_id"].astype(str)) != set(labels["sample_id"].astype(str)):
        raise ValueError("Formal labels do not exactly match blinded sample IDs")
    merged = blinded.merge(labels.drop(columns=["sealed_status"]), on="sample_id", suffixes=("", "_label"), validate="one_to_one")
    if not (merged["formal_block"] == merged["formal_block_label"]).all():
        raise ValueError("Formal block changed during label join")
    merged = merged.drop(columns=["formal_block_label"])
    if not set(merged["label"].astype(int).unique()).issubset({0, 1}):
        raise ValueError("Formal labels are not binary")
    return merged


def load_checkpoint_score(
    result: dict[str, Any],
    bank: Any,
    vhh_index: torch.Tensor,
    target_index: torch.Tensor,
    batch_size: int,
    device: torch.device,
) -> np.ndarray:
    path = Path(result["checkpoint"])
    verify(path, result["checkpoint_sha256"], "checkpoint")
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if checkpoint["embedding_config_sha256"] != bank.config_sha256:
        raise ValueError("Checkpoint and embedding bank configuration hashes differ")
    model = model_from_checkpoint(checkpoint, device)
    return score_model(model, bank, vhh_index, target_index, batch_size, device).numpy()


def learned_ensemble(scores: dict[str, np.ndarray], model_name: str, seeds: list[int]) -> np.ndarray:
    return np.mean([scores[f"{model_name}_seed_{seed}"] for seed in seeds], axis=0)


def block_metrics(frame: pd.DataFrame, scores: dict[str, np.ndarray]) -> dict[str, Any]:
    output = {}
    for block in sorted(frame["formal_block"].astype(str).unique()):
        mask = frame["formal_block"].astype(str).eq(block).to_numpy()
        labels = frame.loc[mask, "label"].astype(int).to_numpy()
        output[block] = {name: binary_ranking_metrics(labels, values[mask]) for name, values in scores.items()}
    return output


def control_pass(
    labels: np.ndarray,
    control: np.ndarray,
    baseline: np.ndarray,
    replicates: int,
    seed: int,
) -> tuple[bool, dict[str, Any]]:
    bootstrap = paired_bootstrap_ap_delta(labels, control, baseline, replicates, seed)
    permutation = paired_permutation_ap_test(labels, control, baseline, replicates, seed)
    passed = (
        bootstrap["observed_delta"] > 0
        and bootstrap["ci95_lower"] > 0
        and permutation["two_sided_p_value"] < 0.05
    )
    return passed, {"passed_improved_prior_gate": passed, "bootstrap": bootstrap, "permutation": permutation}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    primary = summary["formal_metrics"][summary["primary_block"]]
    selected = summary["selected_baseline"]
    decision = summary["formal_decision"]
    lines = [
        "# Phase 2 V3 Formal Evaluation",
        "",
        f"- Decision: **{decision['status']}**",
        f"- Primary block: `{summary['primary_block']}`",
        f"- Development-selected baseline: `{selected}`",
        f"- V3 ensemble AUPRC: `{primary['v3_full']['average_precision']:.6f}`",
        f"- Baseline AUPRC: `{primary[selected]['average_precision']:.6f}`",
        f"- Ensemble delta: `{summary['bootstrap']['observed_delta']:+.6f}`",
        f"- Paired 95% CI: `[{summary['bootstrap']['ci95_lower']:.6f}, {summary['bootstrap']['ci95_upper']:.6f}]`",
        f"- Permutation p: `{summary['permutation']['two_sided_p_value']:.6f}`",
        "",
        "## Gate Checks",
        "",
    ]
    lines.extend(f"- {name}: `{'PASS' if value else 'FAIL'}`" for name, value in decision["checks"].items())
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "This result supports only a generic target-conditioned binary binding prior. It is not PVRIG binding, affinity, competition, or blocker truth.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    run_root = args.run_dir.resolve()
    summary_path = run_root / "train_summary.json"
    marker_path = run_root / "formal_unseal_started.json"
    final_path = run_root / "formal_evaluation" / "formal_evaluation_summary.json"
    if marker_path.exists() or final_path.exists():
        raise RuntimeError("This V3 run already started formal unsealing; use a new version for any rerun")
    train_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cfg = json.loads((run_root / "config_resolved.json").read_text(encoding="utf-8"))
    hashes = train_summary["artifact_hashes"]
    verify(Path(cfg["records_csv"]), hashes["records_csv"], "records_csv")
    verify(Path(cfg["formal_blinded_csv"]), hashes["formal_blinded_csv"], "formal_blinded_csv")
    verify(Path(cfg["embedding_manifest"]), hashes["embedding_manifest"], "embedding_manifest")
    verify(Path(cfg["preregistration_json"]), hashes["preregistration_json"], "preregistration_json")
    verify(Path(cfg["test_spec_json"]), hashes["test_spec_json"], "test_spec_json")
    verify(Path(cfg["source_config_json"]), hashes["source_config_json"], "source_config_json")
    verify(run_root / "preregistered_baseline_selection.json", train_summary["preregistered_baseline_selection_sha256"], "baseline_selection")
    for path, expected in hashes["embedding_shards"].items():
        verify(Path(path), expected, "embedding_shard")

    blinded = load_blinded(Path(cfg["formal_blinded_csv"]))
    bank_cpu = load_embedding_bank(Path(cfg["embedding_manifest"]))
    vhh_index, target_index = frame_pair_indices(blinded, bank_cpu)
    device = torch.device(args.device)
    bank = bank_cpu.to(device)
    train_frame = pd.read_csv(cfg["records_csv"], usecols=["split", "label"])
    prevalence = float(train_frame.loc[train_frame["split"].astype(str).eq("train"), "label"].mean())
    scores: dict[str, np.ndarray] = {
        "prevalence": np.full(len(blinded), prevalence, dtype=np.float32),
        "frozen_esm2_cosine": fixed_esm2_cosine(
            bank, vhh_index.to(device), target_index.to(device)
        ).detach().cpu().numpy(),
    }
    seeds = [int(value) for value in train_summary["seeds"]]
    for model_name, results in train_summary["results"].items():
        for result in results:
            scores[f"{model_name}_seed_{result['seed']}"] = load_checkpoint_score(
                result, bank, vhh_index, target_index, args.batch_size, device
            )
    for model_name in ("vhh_only", "esm2_pair", "v3_full"):
        scores[model_name] = learned_ensemble(scores, model_name, seeds)
    scores["v3_full_label_shuffle"] = scores[f"v3_full_label_shuffle_seed_{seeds[0]}"]
    scores["v3_full_target_shuffle"] = scores[f"v3_full_target_shuffle_seed_{seeds[0]}"]

    formal_dir = run_root / "formal_evaluation"
    formal_dir.mkdir(parents=True, exist_ok=False)
    inference_path = formal_dir / "formal_inference_scores.npz"
    np.savez_compressed(inference_path, **scores)
    inference_record = {
        "formal_inference_completed_before_labels_read": True,
        "formal_blinded_sha256": hashes["formal_blinded_csv"],
        "inference_scores_path": str(inference_path),
        "inference_scores_sha256": sha256_file(inference_path),
        "methods": sorted(scores),
    }
    write_json_atomic(formal_dir / "formal_inference_complete.json", inference_record)
    write_json_atomic(marker_path, {**inference_record, "formal_unseal_status": "STARTED"})

    merged = merge_labels(blinded, args.formal_labels)
    labels_hash = sha256_file(args.formal_labels)
    metrics = block_metrics(merged, scores)
    primary_block = json.loads(Path(cfg["source_config_json"]).read_text(encoding="utf-8"))["primary_formal_block"]
    primary_mask = merged["formal_block"].astype(str).eq(primary_block).to_numpy()
    primary_labels = merged.loc[primary_mask, "label"].astype(int).to_numpy()
    selected = train_summary["preregistered_baseline_selection"]["selected_baseline"]
    baseline = scores[selected][primary_mask]
    full = scores["v3_full"][primary_mask]
    prereg = json.loads(Path(cfg["preregistration_json"]).read_text(encoding="utf-8"))
    replicates = int(prereg["gate"]["bootstrap_replicates"])
    bootstrap = paired_bootstrap_ap_delta(primary_labels, full, baseline, replicates, 20260712)
    permutation = paired_permutation_ap_test(primary_labels, full, baseline, replicates, 20260713)
    seed_deltas = []
    for seed in seeds:
        full_seed = scores[f"v3_full_seed_{seed}"][primary_mask]
        baseline_seed = (
            scores[f"{selected}_seed_{seed}"][primary_mask]
            if f"{selected}_seed_{seed}" in scores
            else baseline
        )
        seed_deltas.append(
            binary_ranking_metrics(primary_labels, full_seed)["average_precision"]
            - binary_ranking_metrics(primary_labels, baseline_seed)["average_precision"]
        )
    null_passed, null_result = control_pass(
        primary_labels, scores["v3_full_label_shuffle"][primary_mask], baseline, replicates, 20260714
    )
    target_shuffle_passed, target_shuffle_result = control_pass(
        primary_labels, scores["v3_full_target_shuffle"][primary_mask], baseline, replicates, 20260715
    )
    decision = formal_gate_decision(seed_deltas, bootstrap, permutation, null_passed, target_shuffle_passed)

    prediction_columns = {
        "sample_id": merged["sample_id"].astype(str).to_numpy(),
        "formal_block": merged["formal_block"].astype(str).to_numpy(),
        "target_id": merged["target_id"].astype(str).to_numpy(),
        "label": merged["label"].astype(int).to_numpy(),
        "v3_full": scores["v3_full"],
        "selected_baseline": scores[selected],
        "vhh_only": scores["vhh_only"],
        "esm2_pair": scores["esm2_pair"],
        "frozen_esm2_cosine": scores["frozen_esm2_cosine"],
        "prevalence": scores["prevalence"],
    }
    prediction_frame = pd.DataFrame(prediction_columns)
    prediction_frame.to_csv(formal_dir / "formal_predictions.csv", index=False)
    summary = {
        "schema_version": "phase2_v3_formal_evaluation_v1",
        "run_dir": str(run_root),
        "formal_unseal_status": "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE",
        "formal_labels_path": str(args.formal_labels),
        "formal_labels_sha256": labels_hash,
        "primary_block": primary_block,
        "selected_baseline": selected,
        "formal_metrics": metrics,
        "seed_primary_ap_deltas": seed_deltas,
        "bootstrap": bootstrap,
        "permutation": permutation,
        "null_control": null_result,
        "target_shuffle_control": target_shuffle_result,
        "formal_decision": decision,
        "deployment_method": "v3_full" if decision["all_checks_pass"] else selected,
        "inference_record": inference_record,
        "formal_predictions_sha256": sha256_file(formal_dir / "formal_predictions.csv"),
        "claim_boundary": "generic_binary_binding_prior_not_pvrig_binding_or_blocking_truth",
    }
    write_json_atomic(final_path, summary)
    write_report(formal_dir / "PHASE2_V3_FORMAL_EVALUATION.md", summary)
    write_json_atomic(
        run_root / "formal_unseal_audit.json",
        {
            "status": "PASS",
            "formal_run_count": 1,
            "inference_completed_before_labels_read": True,
            "formal_labels_used_for_training_or_selection": False,
            "formal_labels_sha256": labels_hash,
            "next_version_required_for_any_change_or_rerun": True,
        },
    )
    print(json.dumps({"decision": decision["status"], "deployment_method": summary["deployment_method"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--formal-labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=8192)
    return parser.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
