#!/usr/bin/env python3
"""Score a VHH-antigen pair with the Phase 1 NumPy baseline."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from train_phase1_sequence_baseline import (  # noqa: E402
    predict_ridge,
    residue_features,
    sigmoid,
    standardize,
    vhh_score_features,
)


def read_fasta(path: Path) -> str:
    parts = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        parts.append(line)
    return "".join(parts)


def load_logistic(path: Path) -> dict[str, np.ndarray | float]:
    data = np.load(path)
    return {"w": data["w"], "b": float(data["b"][0]), "mean": data["mean"], "std": data["std"]}


def load_ridge(path: Path) -> dict[str, np.ndarray | float]:
    data = np.load(path)
    return {
        "w": data["w"],
        "b": float(data["b"][0]),
        "mean": data["mean"],
        "std": data["std"],
        "y_mean": float(data["y_mean"][0]),
        "y_std": float(data["y_std"][0]),
    }


def predict_residue(seq: str, partner: str, model: dict[str, np.ndarray | float]) -> np.ndarray:
    x = residue_features(seq, partner)
    xs = standardize(x, model["mean"], model["std"])  # type: ignore[arg-type]
    return sigmoid(xs @ model["w"] + model["b"])  # type: ignore[operator]


def top_residues(seq: str, probs: np.ndarray, k: int) -> list[dict[str, object]]:
    if len(seq) == 0:
        return []
    order = np.argsort(-probs)[: min(k, len(seq))]
    return [{"position_1based": int(i + 1), "aa": seq[int(i)], "probability": float(probs[int(i)])} for i in order]


def pvrig_overlap(probs: np.ndarray, mask_path: Path, threshold: float) -> dict[str, object]:
    if not mask_path.exists():
        return {"has_mask": False}
    mask = pd.read_csv(mask_path)
    if len(mask) != len(probs):
        return {"has_mask": True, "error": f"mask length {len(mask)} != antigen length {len(probs)}"}
    target = (mask["in_target_epitope"].astype(str) == "yes").to_numpy()
    pred = probs >= threshold
    target_weight = pd.to_numeric(mask.get("target_weight", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    overlap = pred & target
    order = np.argsort(-probs)
    top20 = np.zeros_like(target, dtype=bool)
    top50 = np.zeros_like(target, dtype=bool)
    top20[order[: min(20, len(order))]] = True
    top50[order[: min(50, len(order))]] = True
    return {
        "has_mask": True,
        "threshold": threshold,
        "predicted_epitope_count": int(pred.sum()),
        "target_epitope_count": int(target.sum()),
        "overlap_count": int(overlap.sum()),
        "target_recall": float(overlap.sum() / max(target.sum(), 1)),
        "predicted_precision_on_target": float(overlap.sum() / max(pred.sum(), 1)),
        "target_hits_in_top20": int((top20 & target).sum()),
        "target_recall_top20": float((top20 & target).sum() / max(target.sum(), 1)),
        "target_hits_in_top50": int((top50 & target).sum()),
        "target_recall_top50": float((top50 & target).sum() / max(target.sum(), 1)),
        "weighted_target_probability_sum": float((probs * target_weight).sum()),
        "top_target_positions": [
            {
                "position_1based": int(i + 1),
                "aa": str(mask.loc[i, "aa"]),
                "probability": float(probs[i]),
                "target_weight": float(target_weight[i]),
                "hotspot_ids": str(mask.loc[i, "hotspot_ids"]),
            }
            for i in np.argsort(-(probs * target_weight))[:10]
            if target_weight[i] > 0
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default="models/phase1_sequence_baseline")
    parser.add_argument("--vhh-seq", required=True)
    parser.add_argument("--antigen-seq")
    parser.add_argument("--antigen-fasta")
    parser.add_argument("--cdr1", default="")
    parser.add_argument("--cdr2", default="")
    parser.add_argument("--cdr3", default="")
    parser.add_argument("--pvrig-mask", default="model_data/pvrig_full_sequence_mask_v0.csv")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    antigen = args.antigen_seq or (read_fasta(Path(args.antigen_fasta)) if args.antigen_fasta else "")
    if not antigen:
        raise SystemExit("Provide --antigen-seq or --antigen-fasta")

    para = load_logistic(model_dir / "paratope_logistic_head.npz")
    epi = load_logistic(model_dir / "epitope_logistic_head.npz")
    ridge = load_ridge(model_dir / "vhh_score_ridge_head.npz")

    par_probs = predict_residue(args.vhh_seq, antigen, para)
    epi_probs = predict_residue(antigen, args.vhh_seq, epi)
    x_score = vhh_score_features(args.vhh_seq, args.cdr1, args.cdr2, args.cdr3).reshape(1, -1)
    vhh_score = float(predict_ridge(x_score, ridge["w"], ridge["b"], ridge["mean"], ridge["std"], ridge["y_mean"], ridge["y_std"])[0])  # type: ignore[arg-type]

    result = {
        "vhh_length": len(args.vhh_seq),
        "antigen_length": len(antigen),
        "vhh_score_raw": vhh_score,
        "mean_paratope_probability": float(par_probs.mean()) if len(par_probs) else 0.0,
        "mean_epitope_probability": float(epi_probs.mean()) if len(epi_probs) else 0.0,
        "top_paratope_residues": top_residues(args.vhh_seq, par_probs, args.top_k),
        "top_epitope_residues": top_residues(antigen, epi_probs, args.top_k),
        "pvrig_overlap": pvrig_overlap(epi_probs, Path(args.pvrig_mask), args.threshold),
        "warning": "Phase1 baseline only; not calibrated Kd and not a final PVRIG binder proof.",
    }

    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".json":
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with out.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["section", "position_1based", "aa", "probability", "extra"])
                for row in result["top_paratope_residues"]:
                    writer.writerow(["paratope", row["position_1based"], row["aa"], row["probability"], ""])
                for row in result["top_epitope_residues"]:
                    writer.writerow(["epitope", row["position_1based"], row["aa"], row["probability"], ""])
                for row in result["pvrig_overlap"].get("top_target_positions", []):
                    writer.writerow(["pvrig_target", row["position_1based"], row["aa"], row["probability"], json.dumps(row, ensure_ascii=False)])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
