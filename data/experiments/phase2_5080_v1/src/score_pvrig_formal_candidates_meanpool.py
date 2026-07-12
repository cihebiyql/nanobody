#!/usr/bin/env python3
"""Score formal PVRIG designs with the frozen mean-pooled V3-G baseline."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from phase2_v3_contracts import sha256_file, sha256_text  # noqa: E402
from phase2_v3_model import (  # noqa: E402
    BindingPriorModel,
    frame_pair_indices,
    load_embedding_bank,
    score_model,
)

DEFAULT_INPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/fast_gate_all_v1.csv"
DEFAULT_EMBEDDINGS = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/meanpool_embeddings/embedding_manifest_v3.csv"
DEFAULT_MEANPOOL_ROOT = EXP_DIR / "runs/phase2_v3_g2_meanpool_baselines"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv"
ELIGIBLE_TIERS = {"FORMAL_ELIGIBLE", "RESERVE_REVIEW"}
CLAIM_BOUNDARY = "relative_generic_binding_prior_for_teacher_sampling_not_pvrig_binding_or_blocking_truth"


def latest_train_summary(root: Path) -> Path:
    paths = sorted(root.glob("*/train_summary.json"), key=lambda path: path.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No mean-pooled train summary under {root}")
    return paths[-1]


def read_fasta(path: Path) -> str:
    return "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )


def review_count(value: object) -> int:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return 0
    return len([item for item in text.split(";") if item])


def cheap_qc_score(frame: pd.DataFrame) -> pd.Series:
    tier_penalty = frame["fast_gate_tier"].astype(str).map({"FORMAL_ELIGIBLE": 0.0, "RESERVE_REVIEW": 0.10}).fillna(1.0)
    flags = frame.get("review_flags", pd.Series("", index=frame.index)).map(review_count).clip(upper=4)
    identity = pd.to_numeric(frame.get("max_positive_cdr_identity", 0.0), errors="coerce").fillna(0.0).clip(0.0, 80.0)
    score = 1.0 - tier_penalty - 0.04 * flags - 0.15 * identity / 80.0
    return score.clip(0.0, 1.0)


def rank_disagreement(seed_scores: dict[int, np.ndarray]) -> np.ndarray:
    percentiles = []
    count = len(next(iter(seed_scores.values())))
    denominator = max(count - 1, 1)
    for values in seed_scores.values():
        ranks = pd.Series(values).rank(method="average", ascending=False).to_numpy()
        percentiles.append((count - ranks) / denominator)
    return np.std(np.stack(percentiles), axis=0)


def score(
    input_path: Path,
    embedding_manifest: Path,
    train_summary_path: Path,
    target_path: Path,
    output_path: Path,
    device_name: str,
    batch_size: int,
) -> dict[str, Any]:
    frame = pd.read_csv(input_path)
    required = {"candidate_id", "vhh_sequence", "sequence_sha256", "fast_gate_tier"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Fast-gate input is missing {sorted(missing)}")
    frame = frame[frame["fast_gate_tier"].astype(str).isin(ELIGIBLE_TIERS)].copy().reset_index(drop=True)
    if frame.empty or frame["sequence_sha256"].duplicated().any():
        raise ValueError("Scoring requires non-empty exact-deduplicated eligible candidates")
    if not frame["vhh_sequence"].astype(str).map(sha256_text).equals(frame["sequence_sha256"].astype(str)):
        raise ValueError("Candidate sequence hashes differ from vhh_sequence")
    target = read_fasta(target_path)
    target_hash = sha256_text(target)
    pairs = frame.copy()
    pairs["target_sequence_sha256"] = target_hash
    pairs["target_sequence"] = target

    train_summary = json.loads(train_summary_path.read_text(encoding="utf-8"))
    variant = "v3_full"
    if variant not in train_summary["results"]:
        raise ValueError("Mean-pooled train summary has no v3_full result")
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    bank_cpu = load_embedding_bank(embedding_manifest)
    vhh_index, target_index = frame_pair_indices(pairs, bank_cpu)
    bank = bank_cpu.to(device)
    seed_scores: dict[int, np.ndarray] = {}
    checkpoint_rows = []
    for result in train_summary["results"][variant]:
        checkpoint_path = Path(result["checkpoint"])
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if checkpoint["embedding_config_sha256"] != bank.config_sha256:
            raise ValueError("Candidate embedding config differs from frozen mean-pooled checkpoint")
        model = BindingPriorModel(**checkpoint["model_config"])
        model.load_state_dict(checkpoint["state_dict"])
        model.to(device)
        seed = int(checkpoint["seed"])
        seed_scores[seed] = score_model(model, bank, vhh_index, target_index, batch_size, device).numpy()
        checkpoint_rows.append({"seed": seed, "path": str(checkpoint_path), "sha256": sha256_file(checkpoint_path)})
        del model
    if len(seed_scores) < 3:
        raise ValueError(f"Expected at least three frozen v3_full seeds, found {len(seed_scores)}")
    matrix = np.stack([seed_scores[seed] for seed in sorted(seed_scores)])
    frame["generic_binding_prior"] = matrix.mean(axis=0)
    frame["model_uncertainty"] = matrix.std(axis=0)
    frame["model_disagreement"] = rank_disagreement(seed_scores)
    frame["cheap_qc_score"] = cheap_qc_score(frame)
    frame["generic_binding_prior_percentile"] = frame["generic_binding_prior"].rank(pct=True, method="average")
    frame["generic_binding_model"] = "meanpool_v3_full_cluster_safe_baseline"
    frame["generic_binding_train_summary"] = str(train_summary_path)
    frame["generic_binding_train_summary_sha256"] = sha256_file(train_summary_path)
    frame["target_sequence_sha256"] = target_hash
    frame["model_claim_boundary"] = CLAIM_BOUNDARY
    for seed in sorted(seed_scores):
        frame[f"generic_binding_prior_seed_{seed}"] = seed_scores[seed]
    if not all(math.isfinite(value) for value in frame["generic_binding_prior"]):
        raise ValueError("Non-finite generic binding prior")
    frame = frame.sort_values(["generic_binding_prior", "cheap_qc_score", "candidate_id"], ascending=[False, False, True])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    audit = {
        "status": "PASS_PVRIG_FORMAL_CANDIDATES_SCORED",
        "schema_version": "pvrig_formal_candidate_meanpool_scoring_v1",
        "rows": len(frame),
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "embedding_manifest": str(embedding_manifest),
        "embedding_manifest_sha256": sha256_file(embedding_manifest),
        "train_summary": str(train_summary_path),
        "train_summary_sha256": sha256_file(train_summary_path),
        "target_sequence_sha256": target_hash,
        "checkpoints": checkpoint_rows,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    output_path.with_name("scored_candidates_audit_v1.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--embedding-manifest", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--train-summary", type=Path)
    parser.add_argument("--meanpool-root", type=Path, default=DEFAULT_MEANPOOL_ROOT)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=8192)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    train_summary = args.train_summary or latest_train_summary(args.meanpool_root)
    audit = score(
        args.input,
        args.embedding_manifest,
        train_summary,
        args.target_fasta,
        args.output,
        args.device,
        args.batch_size,
    )
    print(json.dumps({"status": audit["status"], "rows": audit["rows"], "output": audit["output"]}, indent=2))


if __name__ == "__main__":
    main()
