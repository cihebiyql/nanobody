#!/usr/bin/env python3
"""Batch-score VHH candidates with Phase 1 AI prior plus PVRIG blocker calibration gates.

This script deliberately separates:
1) AI prior: sequence-only paratope/epitope/VHH-score signals.
2) Final calibration: known-positive leakage, optional docking consensus/classes, and PVRIG-specific blocker gates.

If no docking columns are present, the final calibrated label remains NEEDS_DOCKING_CALIBRATION.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from score_phase1_sequence_baseline import (  # noqa: E402
    load_logistic,
    load_ridge,
    predict_residue,
    read_fasta,
    top_residues,
    pvrig_overlap,
)
from train_phase1_sequence_baseline import predict_ridge, vhh_score_features  # noqa: E402

DEFAULT_RULES = {
    "hotspot_min": 14,
    "total_occlusion_min": 500,
    "cdr3_occlusion_min": 100,
    "cdr3_fraction_min": 0.15,
    "binder_total_max": 50,
}


def clean(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v).strip()
    if text.lower() in {"nan", "none", "na", "n/a"}:
        return ""
    return text


def first_present(row: pd.Series, names: list[str]) -> str:
    for name in names:
        if name in row and clean(row.get(name)):
            return clean(row.get(name))
    return ""


def parse_float(v: Any) -> float | None:
    text = clean(v)
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def read_candidates(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".fa", ".fasta", ".faa"}:
        records = []
        cur_id = ""
        parts: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_id:
                    records.append({"candidate_id": cur_id, "vhh_seq": "".join(parts)})
                cur_id = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
        if cur_id:
            records.append({"candidate_id": cur_id, "vhh_seq": "".join(parts)})
        return pd.DataFrame(records)
    return pd.read_csv(path)


def sequence_identity(a: str, b: str) -> tuple[float, str]:
    if not a or not b:
        return 0.0, ""
    if len(a) == len(b):
        matches = sum(x == y for x, y in zip(a, b))
        return matches / max(len(a), 1), str(len(a) - matches)
    return difflib.SequenceMatcher(None, a, b).ratio(), "different_length"


def cdr_identity(query: str, ref: str) -> float:
    if not query or not ref:
        return 0.0
    if len(query) == len(ref):
        return sum(a == b for a, b in zip(query, ref)) / max(len(query), 1)
    return difflib.SequenceMatcher(None, query, ref).ratio()


def load_reference_positives(calibration_path: Path, fasta_path: Path | None = None) -> pd.DataFrame:
    refs = []
    if calibration_path.exists():
        df = pd.read_csv(calibration_path)
        for _, r in df.iterrows():
            refs.append(
                {
                    "reference_id": clean(r.get("molecule_name")) or clean(r.get("calibration_id")),
                    "source": str(calibration_path),
                    "sequence": clean(r.get("sequence")),
                    "cdr1": clean(r.get("cdr1")),
                    "cdr2": clean(r.get("cdr2")),
                    "cdr3": clean(r.get("cdr3")),
                    "family": clean(r.get("family")),
                }
            )
    if fasta_path and fasta_path.exists():
        cur_id = ""
        parts: list[str] = []
        for line in fasta_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_id:
                    refs.append({"reference_id": cur_id, "source": str(fasta_path), "sequence": "".join(parts), "cdr1": "", "cdr2": "", "cdr3": "", "family": ""})
                cur_id = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
        if cur_id:
            refs.append({"reference_id": cur_id, "source": str(fasta_path), "sequence": "".join(parts), "cdr1": "", "cdr2": "", "cdr3": "", "family": ""})
    # Deduplicate exact reference_id+sequence pairs.
    out = pd.DataFrame(refs)
    if out.empty:
        return out
    out = out.drop_duplicates(subset=["reference_id", "sequence"]).reset_index(drop=True)
    return out


def leakage_check(seq: str, cdrs: dict[str, str], refs: pd.DataFrame, full_near: float, cdr_near: float) -> dict[str, Any]:
    best = {
        "nearest_reference_id": "",
        "nearest_reference_family": "",
        "nearest_reference_source": "",
        "identity_fraction": 0.0,
        "same_length_hamming_distance": "",
        "max_cdr_identity": 0.0,
        "max_cdr_name": "",
        "leakage_label": "NO_KNOWN_POSITIVE_LEAKAGE",
        "recommended_action": "allow_to_continue_to_docking_calibration",
    }
    if refs.empty or not seq:
        return best
    for _, r in refs.iterrows():
        ref_seq = clean(r.get("sequence"))
        ident, ham = sequence_identity(seq, ref_seq)
        max_cdr = 0.0
        max_cdr_name = ""
        for cdr in ["cdr1", "cdr2", "cdr3"]:
            ident_cdr = cdr_identity(cdrs.get(cdr, ""), clean(r.get(cdr)))
            if ident_cdr > max_cdr:
                max_cdr = ident_cdr
                max_cdr_name = cdr.upper()
        update = ident > best["identity_fraction"] or (ident == best["identity_fraction"] and max_cdr > best["max_cdr_identity"])
        if update:
            best.update(
                nearest_reference_id=clean(r.get("reference_id")),
                nearest_reference_family=clean(r.get("family")),
                nearest_reference_source=clean(r.get("source")),
                identity_fraction=float(ident),
                same_length_hamming_distance=ham,
                max_cdr_identity=float(max_cdr),
                max_cdr_name=max_cdr_name,
            )
    if best["identity_fraction"] >= 0.999999:
        best["leakage_label"] = "EXACT_KNOWN_POSITIVE"
        best["recommended_action"] = "exclude_from_new_candidate_ranking_keep_as_control"
    elif best["identity_fraction"] >= full_near or best["max_cdr_identity"] >= cdr_near:
        best["leakage_label"] = "NEAR_KNOWN_POSITIVE_OR_CDR_SIMILAR"
        best["recommended_action"] = "exclude_or_hold_for_manual_leakage_review"
    return best


def classify_ai_prior(overlap: dict[str, Any], par_probs: np.ndarray, epi_probs: np.ndarray) -> str:
    top50 = float(overlap.get("target_recall_top50", 0.0) or 0.0)
    top20 = float(overlap.get("target_recall_top20", 0.0) or 0.0)
    par_top = float(np.max(par_probs)) if len(par_probs) else 0.0
    epi_top = float(np.max(epi_probs)) if len(epi_probs) else 0.0
    if top20 >= 0.20 and par_top >= 0.65 and epi_top >= 0.65:
        return "AI_PRIOR_HIGH_NEEDS_DOCKING"
    if top50 >= 0.25 and par_top >= 0.55:
        return "AI_PRIOR_MEDIUM_NEEDS_DOCKING"
    if top50 > 0:
        return "AI_PRIOR_LOW_NEEDS_DOCKING"
    return "AI_PRIOR_NO_TARGET_SIGNAL"


def infer_consensus_from_columns(row: pd.Series) -> tuple[str, str]:
    explicit = first_present(row, ["dual_baseline_consensus_class", "consensus_class", "top_model_consensus_class"])
    if explicit:
        return explicit, "provided_consensus_column"
    c8 = first_present(row, ["haddock_8x6b_class", "top_8x6b_class", "class_8x6b", "8x6b_class"])
    c9 = first_present(row, ["haddock_9e6y_class", "top_9e6y_class", "class_9e6y", "9e6y_class"])
    if c8 or c9:
        if c8 == "BLOCKER_LIKE_A" and c9 == "BLOCKER_LIKE_A":
            return "CONSENSUS_BLOCKER_LIKE_A", "inferred_from_8x6b_9e6y_classes"
        if "BLOCKER_LIKE_A" in {c8, c9} and "BLOCKER_PLAUSIBLE_B" in {c8, c9}:
            return "SINGLE_BASELINE_BLOCKER_RECHECK", "inferred_from_8x6b_9e6y_classes"
        if "BINDER_LIKE_C" in {c8, c9}:
            return "DISCORDANT_OR_BINDER_LIKE_RECHECK", "inferred_from_8x6b_9e6y_classes"
        if "BLOCKER_PLAUSIBLE_B" in {c8, c9}:
            return "BLOCKER_PLAUSIBLE_B", "inferred_from_8x6b_9e6y_classes"
        if "EVIDENCE_INFERENCE_ONLY_E" in {c8, c9}:
            return "EVIDENCE_INFERENCE_ONLY_E", "inferred_from_8x6b_9e6y_classes"
    return "", ""


def classify_numeric_docking(row: pd.Series, rules: dict[str, float]) -> tuple[str, str]:
    hot = parse_float(first_present(row, ["hotspot_overlap_count", "top_8x6b_hotspot", "top_9e6y_hotspot"]))
    total = parse_float(first_present(row, ["total_vhh_pvrl2_residue_pair_occlusion", "total_pvrl2_residue_pair_occlusion", "top_8x6b_total_occlusion", "top_9e6y_total_occlusion"]))
    cdr3 = parse_float(first_present(row, ["cdr3_pvrl2_residue_pair_occlusion", "top_8x6b_cdr3_occlusion", "top_9e6y_cdr3_occlusion"]))
    frac = parse_float(first_present(row, ["cdr3_occlusion_fraction", "top_8x6b_cdr3_fraction", "top_9e6y_cdr3_fraction"]))
    if None in {hot, total, cdr3, frac}:
        return "", ""
    assert hot is not None and total is not None and cdr3 is not None and frac is not None
    if hot >= rules["hotspot_min"] and total >= rules["total_occlusion_min"] and cdr3 >= rules["cdr3_occlusion_min"] and frac >= rules["cdr3_fraction_min"]:
        return "BLOCKER_LIKE_A", "numeric_vhh_docking_gate"
    if hot >= rules["hotspot_min"] and total < rules["binder_total_max"]:
        return "BINDER_LIKE_C", "numeric_hotspot_only_downgrade"
    if hot >= rules["hotspot_min"] and total >= rules["binder_total_max"]:
        return "BLOCKER_PLAUSIBLE_B", "numeric_partial_occlusion_gate"
    return "EVIDENCE_INFERENCE_ONLY_E", "numeric_insufficient_hotspot_or_occlusion"


def final_label(leakage_label: str, ai_prior: str, consensus: str, numeric_class: str) -> tuple[str, str, bool]:
    if leakage_label.startswith("EXACT"):
        return "EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL", "Known positive/control; do not rank as new design.", False
    if leakage_label.startswith("NEAR"):
        return "HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW", "Near known-positive or CDR-similar; exclude unless explicitly a control.", True
    dock_class = consensus or numeric_class
    if dock_class in {"CONSENSUS_BLOCKER_LIKE_A", "BLOCKER_LIKE_A"}:
        return "CALIBRATED_BLOCKER_LIKE_A", "Dual-baseline or numeric calibrated blocker-like support present.", False
    if dock_class == "SINGLE_BASELINE_BLOCKER_RECHECK":
        return "SINGLE_BASELINE_BLOCKER_RECHECK", "One baseline supports A-level geometry; inspect pose/redock before promotion.", True
    if dock_class == "BLOCKER_PLAUSIBLE_B":
        return "BLOCKER_PLAUSIBLE_B_RECHECK", "Plausible but incomplete blocker support; needs second baseline or assay/docking review.", True
    if "BINDER" in dock_class:
        return "REJECT_OR_REDOCK_BINDER_LIKE_C", "Binder-like/non-occluding geometry; not blocker-like without new evidence.", True
    if dock_class == "EVIDENCE_INFERENCE_ONLY_E":
        return "EVIDENCE_ONLY_NOT_PROMOTED", "Insufficient blocker evidence.", True
    if ai_prior.startswith("AI_PRIOR_HIGH"):
        return "AI_PRIOR_HIGH_NEEDS_DOCKING_CALIBRATION", "Good sequence prior but no calibrated docking consensus yet.", True
    if ai_prior.startswith("AI_PRIOR_MEDIUM"):
        return "AI_PRIOR_MEDIUM_NEEDS_DOCKING_CALIBRATION", "Moderate sequence prior; run structure/docking calibration.", True
    return "LOW_PRIORITY_OR_NEEDS_MORE_EVIDENCE", "Weak prior or missing calibrated docking evidence.", True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="CSV/FASTA with candidate_id and vhh_seq/sequence columns")
    parser.add_argument("--out", required=True, help="Output CSV")
    parser.add_argument("--model-dir", default="models/phase1_sequence_baseline")
    parser.add_argument("--antigen-fasta", default="model_data/pvrig_target_sequence_v0.fasta")
    parser.add_argument("--pvrig-mask", default="model_data/pvrig_full_sequence_mask_v0.csv")
    parser.add_argument("--positive-calibration", default="model_data/pvrig_blocker_positive_calibration_v0.csv")
    parser.add_argument("--known-positive-fasta", default="/mnt/d/work/抗体/positives/known_positive_antibodies.fasta")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--full-near-threshold", type=float, default=0.90)
    parser.add_argument("--cdr-near-threshold", type=float, default=0.80)
    args = parser.parse_args()

    candidates = read_candidates(Path(args.candidates))
    antigen = read_fasta(Path(args.antigen_fasta))
    if candidates.empty:
        raise SystemExit("No candidates found")
    if not antigen:
        raise SystemExit("Antigen FASTA is empty or missing")

    model_dir = Path(args.model_dir)
    para = load_logistic(model_dir / "paratope_logistic_head.npz")
    epi = load_logistic(model_dir / "epitope_logistic_head.npz")
    ridge = load_ridge(model_dir / "vhh_score_ridge_head.npz")
    refs = load_reference_positives(Path(args.positive_calibration), Path(args.known_positive_fasta))

    rows = []
    for idx, row in candidates.iterrows():
        cid = first_present(row, ["candidate_id", "id", "name", "molecule_name", "calibration_id"]) or f"candidate_{idx:05d}"
        seq = first_present(row, ["vhh_seq", "sequence", "seq", "aa_sequence"])
        cdrs = {
            "cdr1": first_present(row, ["cdr1", "CDR1"]),
            "cdr2": first_present(row, ["cdr2", "CDR2"]),
            "cdr3": first_present(row, ["cdr3", "CDR3"]),
        }
        if not seq:
            rows.append({"candidate_id": cid, "error": "missing_sequence"})
            continue
        par_probs = predict_residue(seq, antigen, para)
        epi_probs = predict_residue(antigen, seq, epi)
        x_score = vhh_score_features(seq, cdrs["cdr1"], cdrs["cdr2"], cdrs["cdr3"]).reshape(1, -1)
        vhh_score = float(predict_ridge(x_score, ridge["w"], ridge["b"], ridge["mean"], ridge["std"], ridge["y_mean"], ridge["y_std"])[0])  # type: ignore[arg-type]
        overlap = pvrig_overlap(epi_probs, Path(args.pvrig_mask), args.threshold)
        leakage = leakage_check(seq, cdrs, refs, args.full_near_threshold, args.cdr_near_threshold)
        ai_prior = classify_ai_prior(overlap, par_probs, epi_probs)
        consensus, consensus_source = infer_consensus_from_columns(row)
        numeric_class, numeric_source = classify_numeric_docking(row, DEFAULT_RULES)
        label, recommendation, manual = final_label(leakage["leakage_label"], ai_prior, consensus, numeric_class)
        top_para = top_residues(seq, par_probs, args.top_k)
        top_epi = top_residues(antigen, epi_probs, args.top_k)
        rows.append(
            {
                "candidate_id": cid,
                "sequence_length": len(seq),
                "ai_vhh_score_raw": vhh_score,
                "ai_mean_paratope_probability": float(par_probs.mean()) if len(par_probs) else 0.0,
                "ai_max_paratope_probability": float(par_probs.max()) if len(par_probs) else 0.0,
                "ai_mean_pvrig_epitope_probability": float(epi_probs.mean()) if len(epi_probs) else 0.0,
                "ai_max_pvrig_epitope_probability": float(epi_probs.max()) if len(epi_probs) else 0.0,
                "ai_pvrig_predicted_epitope_count_threshold": overlap.get("predicted_epitope_count", ""),
                "ai_pvrig_target_hits_top20": overlap.get("target_hits_in_top20", ""),
                "ai_pvrig_target_recall_top20": overlap.get("target_recall_top20", ""),
                "ai_pvrig_target_hits_top50": overlap.get("target_hits_in_top50", ""),
                "ai_pvrig_target_recall_top50": overlap.get("target_recall_top50", ""),
                "ai_pvrig_weighted_target_probability_sum": overlap.get("weighted_target_probability_sum", ""),
                "ai_prior_label": ai_prior,
                "nearest_reference_id": leakage["nearest_reference_id"],
                "nearest_reference_family": leakage["nearest_reference_family"],
                "known_positive_identity_fraction": leakage["identity_fraction"],
                "same_length_hamming_distance": leakage["same_length_hamming_distance"],
                "max_cdr_identity_to_known_positive": leakage["max_cdr_identity"],
                "max_cdr_identity_name": leakage["max_cdr_name"],
                "leakage_label": leakage["leakage_label"],
                "leakage_recommended_action": leakage["recommended_action"],
                "provided_or_inferred_consensus_class": consensus,
                "consensus_source": consensus_source,
                "numeric_docking_class": numeric_class,
                "numeric_docking_source": numeric_source,
                "final_blocker_like_calibrated_label": label,
                "manual_pose_review_required": "yes" if manual else "no",
                "recommended_next_step": recommendation,
                "top_paratope_residues_json": json.dumps(top_para, ensure_ascii=False),
                "top_pvrig_epitope_residues_json": json.dumps(top_epi, ensure_ascii=False),
                "top_pvrig_target_positions_json": json.dumps(overlap.get("top_target_positions", []), ensure_ascii=False),
                "evidence_boundary": "computational_prior_and_calibration_only_not_experimental_kd_ic50",
            }
        )
    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False, quoting=csv.QUOTE_MINIMAL)
    summary = {
        "candidates": int(len(out)),
        "output": args.out,
        "final_label_counts": out.get("final_blocker_like_calibrated_label", pd.Series(dtype=str)).value_counts().to_dict(),
        "leakage_label_counts": out.get("leakage_label", pd.Series(dtype=str)).value_counts().to_dict(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
