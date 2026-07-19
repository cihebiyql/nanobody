#!/usr/bin/env python3
"""Independent compact audit of the frozen V2.4 strict terminal package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np


MODELS = {
    "M2_FROZEN_ALPHA10": "M2_FROZEN_ALPHA10_OOF.tsv",
    "B_TARGET_NO_CONTACT": "B_TARGET_NO_CONTACT_STRICT_OOF.tsv",
    "C_SPLIT_MARGINAL": "C_SPLIT_MARGINAL_STRICT_OOF.tsv",
    "D_SPLIT_PAIR": "D_SPLIT_PAIR_STRICT_OOF.tsv",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def rankdata(values: list[float]) -> np.ndarray:
    data = np.asarray(values, dtype=np.float64)
    order = np.argsort(data, kind="mergesort")
    ranks = np.empty(len(data), dtype=np.float64)
    start = 0
    while start < len(data):
        end = start + 1
        while end < len(data) and data[order[end]] == data[order[start]]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + end - 1) + 1.0
        start = end
    return ranks


def metrics(data: list[dict[str, str]]) -> dict[str, float]:
    truth = np.asarray([float(row["R_dual_min"]) for row in data])
    prediction = np.asarray([float(row["prediction_R_dual_min"]) for row in data])
    left, right = rankdata(truth.tolist()), rankdata(prediction.tolist())
    correlation = 0.0 if np.std(left) == 0 or np.std(right) == 0 else float(np.corrcoef(left, right)[0, 1])
    error = prediction - truth
    return {
        "spearman": correlation,
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = args.result_dir.resolve()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    expected_checksums = {}
    for line in (result / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        expected_checksums[name] = digest
    for name, digest in expected_checksums.items():
        require((result / name).is_file() and sha256(result / name) == digest, f"checksum:{name}")
    metric_payload = json.loads((result / "STRICT_OOF_METRICS.json").read_text(encoding="utf-8"))
    decision = json.loads((result / "PROMOTION_DECISION.json").read_text(encoding="utf-8"))
    receipt = json.loads((result / "EVALUATION_RECEIPT.json").read_text(encoding="utf-8"))
    all_rows = {model: rows(result / filename) for model, filename in MODELS.items()}
    reference = None
    recomputed = {}
    for model, data in all_rows.items():
        require(len(data) == 1507, f"row_count:{model}")
        require(len({row["candidate_id"] for row in data}) == 1507, f"candidate_count:{model}")
        require(len({row["parent_framework_cluster"] for row in data}) == 31, f"parent_count:{model}")
        require(Counter(row["teacher_source"] for row in data) == Counter(contract["expected_sources"]), f"sources:{model}")
        require({int(row["outer_fold"]) for row in data} == set(range(5)), f"folds:{model}")
        truth = {
            row["candidate_id"]: (
                row["teacher_source"], row["parent_framework_cluster"], row["outer_fold"],
                row["R_8X6B"], row["R_9E6Y"], row["R_dual_min"],
            ) for row in data
        }
        if reference is None:
            reference = truth
        else:
            require(truth == reference, f"truth_mismatch:{model}")
        for row in data:
            require(math.isclose(float(row["R_dual_min"]), min(float(row["R_8X6B"]), float(row["R_9E6Y"])), abs_tol=1e-12), f"truth_min:{model}")
            require(math.isclose(float(row["prediction_R_dual_min"]), min(float(row["prediction_R8"]), float(row["prediction_R9"])), abs_tol=1e-12), f"prediction_min:{model}")
        recomputed[model] = metrics(data)
        reported = metric_payload["models"][model]["targets"]["R_dual_min"]
        require(all(abs(recomputed[model][key] - reported[key]) <= 1e-12 for key in reported), f"metric_mismatch:{model}")
    require(receipt["completed_job_count"] == 195, "completed_jobs")
    require(receipt["strict_meta_validation_reports_passed"] == 15, "meta_validations")
    require(receipt["v4_f_or_test32_access_count"] == 0, "sealed_access")
    require(receipt["exact_min_violations"] == 0, "exact_min_violations")
    require(decision["formal_primary_lane"] == "D_SPLIT_PAIR", "primary_lane")
    expected_status = (
        "PASS_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK"
        if all(decision["formal_primary_lane_gates"].values())
        else "DO_NOT_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK"
    )
    require(decision["status"] == receipt["status"] == expected_status, "status_mismatch")
    payload = {
        "schema_version": "pvrig_v2_4_strict_terminal_independent_audit_v1",
        "status": "PASS_INDEPENDENT_STRICT_TERMINAL_AUDIT",
        "promotion_status": expected_status,
        "rows_per_model": 1507,
        "models": list(MODELS),
        "parents": 31,
        "outer_folds": 5,
        "completed_jobs": 195,
        "meta_validations": 15,
        "exact_min_violations": 0,
        "v4_f_or_test32_access_count": 0,
        "recomputed_Rdual_metrics": recomputed,
        "result_checksums_verified": len(expected_checksums),
        "result_sha256s": {name: sha256(result / name) for name in sorted(expected_checksums)},
        "contract_sha256": sha256(args.contract.resolve()),
        "claim_boundary": contract["claim_boundary"],
    }
    require(not args.output.exists(), "audit_output_preexists")
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
