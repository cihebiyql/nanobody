#!/usr/bin/env python3
"""Evaluate completed open-development A/B outer-fold predictions.

The report is explicitly non-promotable: it covers only the A/B base lanes and
does not claim completion of adaptive-contact C/D or double cross-fitting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from scipy.optimize import nnls


LANES = ("A_VHH_ONLY", "B_TARGET_NO_CONTACT")
TARGETS = ("R8", "R9", "Rdual")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(truth: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    residual = prediction - truth
    correlation = float(spearmanr(truth, prediction).statistic)
    return {
        "spearman": correlation,
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
    }


def evaluate(root: pathlib.Path) -> dict[str, Any]:
    lane_frames: dict[str, pd.DataFrame] = {}
    artifact_hashes: dict[str, str] = {}
    for lane in LANES:
        frames = []
        for fold in range(5):
            path = root / lane / f"fold_{fold}" / "base_score_predictions.tsv"
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"prediction_missing_or_symlink:{path}")
            frame = pd.read_csv(path, sep="\t")
            if set(frame["lane"]) != {lane} or set(frame["split_id"]) != {f"outer_development_{fold}"}:
                raise RuntimeError(f"prediction_identity:{lane}:{fold}")
            frames.append(frame)
            artifact_hashes[f"{lane}/fold_{fold}"] = sha256(path)
        combined = pd.concat(frames, ignore_index=True)
        if len(combined) != 1507 or combined["candidate_id"].nunique() != 1507:
            raise RuntimeError(f"candidate_closure:{lane}:{len(combined)}")
        if not np.array_equal(
            np.minimum(combined["neural_R8"], combined["neural_R9"]),
            combined["neural_Rdual"],
        ):
            raise RuntimeError(f"neural_exact_min:{lane}")
        if not np.allclose(
            np.minimum(combined["M2_R8"], combined["M2_R9"]),
            combined["M2_Rdual"], atol=0.0, rtol=0.0,
        ):
            raise RuntimeError(f"m2_exact_min:{lane}")
        lane_frames[lane] = combined

    left = lane_frames[LANES[0]].sort_values("candidate_id").reset_index(drop=True)
    right = lane_frames[LANES[1]].sort_values("candidate_id").reset_index(drop=True)
    shared = ["candidate_id", "teacher_source", "parent_framework_cluster"] + [
        f"truth_{target}" for target in TARGETS
    ] + [f"M2_{target}" for target in TARGETS]
    if not left[shared].equals(right[shared]):
        raise RuntimeError("lane_truth_or_m2_mismatch")

    report_lanes = {}
    optimistic_meta = {}
    for lane, frame in lane_frames.items():
        metrics = {
            "M2": {target: metric(frame[f"truth_{target}"].to_numpy(), frame[f"M2_{target}"].to_numpy()) for target in TARGETS},
            "neural": {target: metric(frame[f"truth_{target}"].to_numpy(), frame[f"neural_{target}"].to_numpy()) for target in TARGETS},
        }
        source = {}
        for name, group in frame.groupby("teacher_source"):
            source[str(name)] = {
                "rows": len(group),
                "M2_Rdual": metric(group["truth_Rdual"].to_numpy(), group["M2_Rdual"].to_numpy()),
                "neural_Rdual": metric(group["truth_Rdual"].to_numpy(), group["neural_Rdual"].to_numpy()),
            }
        parent_correlations = []
        for _, group in frame.groupby("parent_framework_cluster"):
            if len(group) >= 3 and group["truth_Rdual"].nunique() > 1 and group["neural_Rdual"].nunique() > 1:
                value = float(spearmanr(group["truth_Rdual"], group["neural_Rdual"]).statistic)
                if math.isfinite(value):
                    parent_correlations.append(value)
        report_lanes[lane] = {
            "rows": len(frame), "parents": frame["parent_framework_cluster"].nunique(),
            "metrics": metrics, "source_strata": source,
            "neural_Rdual_parent_macro_spearman": float(np.mean(parent_correlations)),
            "neural_Rdual_parent_macro_parent_count": len(parent_correlations),
        }
        receptor_predictions = []
        receptor_coefficients = {}
        for receptor in ("R8", "R9"):
            columns = [f"M2_{receptor}", f"neural_{receptor}"]
            if lane == "B_TARGET_NO_CONTACT":
                columns.append(f"contact_score_{receptor}")
            features = frame[columns].to_numpy(dtype=float)
            target = frame[f"truth_{receptor}"].to_numpy(dtype=float)
            mean = features.mean(axis=0)
            scale = features.std(axis=0)
            scale = np.where(scale > 1e-9, scale, 1.0)
            standardized = (features - mean) / scale
            slopes, _ = nnls(standardized, target - target.mean())
            receptor_predictions.append(target.mean() + standardized @ slopes)
            receptor_coefficients[receptor] = dict(zip(columns, (float(value) for value in slopes)))
        optimistic_dual = np.minimum(receptor_predictions[0], receptor_predictions[1])
        optimistic_meta[lane] = {
            "same_rows_used_for_fit_and_evaluation": True,
            "promotion_eligible": False,
            "purpose": "optimistic complementarity ceiling only; strict nested cross-fitting is still required",
            "coefficients_on_standardized_features": receptor_coefficients,
            "Rdual": metric(frame["truth_Rdual"].to_numpy(), optimistic_dual),
        }

    a = report_lanes["A_VHH_ONLY"]["metrics"]["neural"]["Rdual"]
    b = report_lanes["B_TARGET_NO_CONTACT"]["metrics"]["neural"]["Rdual"]
    m2 = report_lanes["A_VHH_ONLY"]["metrics"]["M2"]["Rdual"]
    return {
        "schema_version": "pvrig_v2_4_preliminary_ab_outer_evaluation_v1",
        "status": "PASS_PRELIMINARY_AB_EVALUATED_NOT_FULL_STACK_NOT_PROMOTABLE",
        "rows": 1507, "parents": 31,
        "lanes": report_lanes,
        "comparisons": {
            "B_minus_A_neural_Rdual_spearman": b["spearman"] - a["spearman"],
            "A_minus_M2_Rdual_spearman": a["spearman"] - m2["spearman"],
            "B_minus_M2_Rdual_spearman": b["spearman"] - m2["spearman"],
            "B_minus_A_neural_Rdual_mae": b["mae"] - a["mae"],
        },
        "optimistic_same_row_nonnegative_meta_diagnostic": optimistic_meta,
        "prediction_artifact_sha256": artifact_hashes,
        "promotion_authorized": False,
        "full_stack_complete": False,
        "adaptive_contact_supervision_complete": False,
        "v4_f_access_count": 0,
        "claim_boundary": "Open-development A/B base-lane OOF geometry approximation only; no adaptive contact C/D, no meta stack, not binding or experimental blocking.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.runtime_root)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output), "sha256": sha256(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
