#!/usr/bin/env python3
"""Score the frozen 24-candidate PVRIG panel with a formally evaluated V3 run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from phase2_v3_contracts import normalize_antigen_sequence, normalize_vhh_sequence, sha256_file, sha256_text
from phase2_v3_model import (
    fixed_esm2_cosine,
    frame_pair_indices,
    load_embedding_bank,
    model_from_checkpoint,
    score_model,
)

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PANEL = EXP_DIR / "data_splits" / "pvrig_v2_5_prospective_assay_panel.csv"
DEFAULT_CONSTRUCT = EXP_DIR / "assays" / "pvrig_v2_5_prospective_v1" / "construct_manifest.csv"
DEFAULT_OUTPUT = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3.csv"
DEFAULT_HANDOFF = EXP_DIR / "predictions" / "pvrig_candidate_ranking_v3_node1_handoff.csv"


def candidate_lane(role: str) -> str:
    if role == "de_novo_binding_and_competition_screen":
        return "PROSPECTIVE_SCREENING"
    if role == "known_positive_reference":
        return "CALIBRATION_ONLY"
    if role in {"conservative_mutant", "paratope_disruptive_mutant"}:
        return "PAIRED_MUTATION_ANALYSIS"
    if role == "negative_verification_candidate_not_current_negative":
        return "UNVERIFIED_DESIGNED_CONTROL"
    return "UNCLASSIFIED_NOT_RANKED"


def load_panel(panel_path: Path, construct_path: Path) -> pd.DataFrame:
    panel = pd.read_csv(panel_path)
    required = {"panel_order", "candidate_id", "candidate_role", "vhh_sequence", "sequence_sha256", "current_truth_status"}
    if required - set(panel.columns) or len(panel) != 24 or panel["candidate_id"].nunique() != 24:
        raise ValueError("V3 deployment requires the frozen 24-candidate PVRIG panel")
    normalized = []
    for row in panel.to_dict("records"):
        sequence = normalize_vhh_sequence(row["vhh_sequence"]).sequence
        observed = sha256_text(sequence)
        if observed != str(row["sequence_sha256"]):
            raise ValueError(f"Panel sequence hash mismatch for {row['candidate_id']}")
        normalized.append(sequence)
    panel["vhh_sequence"] = normalized

    construct = pd.read_csv(construct_path, usecols=["target_sequence", "target_sequence_sha256"]).drop_duplicates()
    if len(construct) != 1:
        raise ValueError("PVRIG construct manifest must contain one frozen target sequence")
    target = normalize_antigen_sequence(construct.iloc[0]["target_sequence"]).sequence
    target_sha = sha256_text(target)
    if target_sha != str(construct.iloc[0]["target_sequence_sha256"]):
        raise ValueError("PVRIG target sequence hash mismatch")
    panel["target_sequence_sha256"] = target_sha
    panel["target_sequence"] = target
    panel["screening_lane"] = panel["candidate_role"].astype(str).map(candidate_lane)
    return panel


def load_checkpoint_scores(
    run_summary: dict[str, Any],
    model_name: str,
    panel: pd.DataFrame,
    bank: Any,
    vhh_index: torch.Tensor,
    target_index: torch.Tensor,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    seed_scores = {}
    for result in run_summary["results"][model_name]:
        checkpoint_path = Path(result["checkpoint"])
        if sha256_file(checkpoint_path) != result["checkpoint_sha256"]:
            raise ValueError(f"Checkpoint hash mismatch for {checkpoint_path}")
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        model = model_from_checkpoint(checkpoint, device)
        seed_scores[int(result["seed"])] = score_model(
            model, bank, vhh_index, target_index, batch_size, device
        ).numpy()
    return np.mean(list(seed_scores.values()), axis=0), seed_scores


def score(args: argparse.Namespace) -> dict[str, Any]:
    run_root = args.run_dir.resolve()
    run_summary = json.loads((run_root / "train_summary.json").read_text(encoding="utf-8"))
    formal_path = run_root / "formal_evaluation" / "formal_evaluation_summary.json"
    if not formal_path.is_file():
        raise FileNotFoundError("PVRIG scoring requires a completed V3 formal evaluation")
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    cfg = json.loads((run_root / "config_resolved.json").read_text(encoding="utf-8"))
    panel = load_panel(args.panel, args.construct)
    bank_cpu = load_embedding_bank(Path(cfg["embedding_manifest"]))
    vhh_index, target_index = frame_pair_indices(panel, bank_cpu)
    device = torch.device(args.device)
    bank = bank_cpu.to(device)

    method_scores: dict[str, np.ndarray] = {}
    seed_columns: dict[str, np.ndarray] = {}
    for model_name in ("vhh_only", "esm2_pair", "v3_full"):
        ensemble, seeds = load_checkpoint_scores(
            run_summary, model_name, panel, bank, vhh_index, target_index, device, args.batch_size
        )
        method_scores[model_name] = ensemble
        if model_name == "v3_full":
            for seed, values in seeds.items():
                seed_columns[f"v3_full_seed_{seed}"] = values
    method_scores["frozen_esm2_cosine"] = fixed_esm2_cosine(
        bank, vhh_index.to(device), target_index.to(device)
    ).detach().cpu().numpy()
    train_frame = pd.read_csv(cfg["records_csv"], usecols=["split", "label"])
    prevalence = float(train_frame.loc[train_frame["split"].astype(str).eq("train"), "label"].mean())
    method_scores["prevalence"] = np.full(len(panel), prevalence)

    deployment_method = str(formal["deployment_method"])
    if deployment_method not in method_scores:
        raise ValueError(f"Formal deployment method is unavailable for panel scoring: {deployment_method}")
    panel["v3_full_binding_prior"] = method_scores["v3_full"]
    for name, values in seed_columns.items():
        panel[name] = values
    panel["v3_full_seed_std"] = np.std(list(seed_columns.values()), axis=0)
    panel["vhh_only_baseline"] = method_scores["vhh_only"]
    panel["esm2_pair_baseline"] = method_scores["esm2_pair"]
    panel["frozen_esm2_cosine_baseline"] = method_scores["frozen_esm2_cosine"]
    panel["deployment_score"] = method_scores[deployment_method]
    panel["deployment_method"] = deployment_method
    panel["formal_decision"] = formal["formal_decision"]["status"]
    panel["model_run_dir"] = str(run_root)
    panel["model_train_summary_sha256"] = sha256_file(run_root / "train_summary.json")
    panel["formal_summary_sha256"] = sha256_file(formal_path)
    panel["panel_source_sha256"] = sha256_file(args.panel)
    panel["claim_boundary"] = "relative_generic_binding_prior_not_pvrig_binding_affinity_or_blocking_truth"
    panel["screening_rank"] = pd.NA
    eligible = panel["screening_lane"].eq("PROSPECTIVE_SCREENING")
    panel.loc[eligible, "screening_rank"] = (
        panel.loc[eligible, "deployment_score"].rank(method="first", ascending=False).astype(int)
    )
    panel = panel.sort_values("panel_order")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.output, index=False)

    handoff_columns = [
        "candidate_id",
        "vhh_sequence",
        "sequence_sha256",
        "target_sequence_sha256",
        "screening_rank",
        "deployment_score",
        "deployment_method",
        "v3_full_binding_prior",
        "v3_full_seed_std",
        "formal_decision",
        "model_train_summary_sha256",
        "formal_summary_sha256",
        "claim_boundary",
    ]
    handoff = panel.loc[eligible, handoff_columns].sort_values("screening_rank")
    handoff["node1_next_step"] = "STRUCTURE_AND_DUAL_BASELINE_GEOMETRY_VALIDATION"
    handoff["blocking_claim_allowed"] = "false"
    args.handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.to_csv(args.handoff, index=False)
    summary = {
        "schema_version": "phase2_v3_pvrig_panel_scoring_v1",
        "run_dir": str(run_root),
        "formal_decision": formal["formal_decision"]["status"],
        "deployment_method": deployment_method,
        "panel_rows": len(panel),
        "prospective_screening_rows": int(eligible.sum()),
        "calibration_rows": int(panel["screening_lane"].eq("CALIBRATION_ONLY").sum()),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "node1_handoff": str(args.handoff),
        "node1_handoff_sha256": sha256_file(args.handoff),
        "claim_boundary": "score_only_no_pvrig_blocker_truth",
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"deployment_method": deployment_method, "output": str(args.output)}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--construct", type=Path, default=DEFAULT_CONSTRUCT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=1024)
    return parser.parse_args()


if __name__ == "__main__":
    score(parse_args())
