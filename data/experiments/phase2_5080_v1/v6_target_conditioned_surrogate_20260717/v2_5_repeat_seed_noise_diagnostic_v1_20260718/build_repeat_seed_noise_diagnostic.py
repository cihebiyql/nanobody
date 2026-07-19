#!/usr/bin/env python3
"""Candidate-unit repeated-seed noise diagnostics for open V4-D/V4-H Docking."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np


TARGETS = ("R8", "R9", "Rdual")
SEEDS = (917, 1931, 3253)
CLAIM = (
    "Repeated-seed computational dual-receptor docking geometry measurement diagnostic; "
    "not binding, affinity, competition, experimental blocking, Docking Gold, or formal validation."
)


class DiagnosticError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if not rows:
        raise DiagnosticError(f"refusing_empty_output:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def finite(value: Any, label: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise DiagnosticError(f"invalid_float:{label}:{value!r}") from exc
    if not math.isfinite(x):
        raise DiagnosticError(f"nonfinite:{label}:{value!r}")
    return x


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return pearson(average_ranks(x), average_ranks(y))


def bootstrap_spearman_ci(x: np.ndarray, y: np.ndarray, *, reps: int = 1000, seed: int = 20260718) -> tuple[float, float]:
    if len(x) < 4:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(reps):
        idx = rng.integers(0, len(x), len(x))
        value = spearman(x[idx], y[idx])
        if math.isfinite(value):
            values.append(value)
    if not values:
        return float("nan"), float("nan")
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def icc_1_1(matrix: np.ndarray) -> float:
    """One-way random effects single-measure ICC; rows=candidates, columns=seeds."""
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return float("nan")
    n, k = matrix.shape
    row_means = matrix.mean(axis=1)
    grand = matrix.mean()
    ms_between = k * float(np.sum((row_means - grand) ** 2)) / (n - 1)
    ms_within = float(np.sum((matrix - row_means[:, None]) ** 2)) / (n * (k - 1))
    denominator = ms_between + (k - 1) * ms_within
    return (ms_between - ms_within) / denominator if denominator > 0 else float("nan")


def cohort_key(campaign: str, paired_count: int) -> str:
    return f"{campaign}_{paired_count}_SEED"


def build_measurements(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str], dict[int, dict[str, float]]], dict[tuple[str, str], dict[str, str]]]:
    receptor_values: dict[tuple[str, str, int, str], float] = {}
    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        campaign = row["campaign"].upper()
        cid = row["candidate_id"]
        receptor = row["receptor"].lower()
        if receptor not in {"8x6b", "9e6y"}:
            raise DiagnosticError(f"receptor_invalid:{receptor}")
        seed = int(row["seed"])
        key = (campaign, cid, seed, receptor)
        if key in receptor_values:
            raise DiagnosticError(f"duplicate_measurement:{key}")
        receptor_values[key] = finite(row["score"], f"score:{key}")
        meta_key = (campaign, cid)
        current = {k: row[k] for k in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode")}
        if meta_key in metadata and metadata[meta_key] != current:
            raise DiagnosticError(f"metadata_inconsistent:{meta_key}")
        metadata[meta_key] = current

    measurements: dict[tuple[str, str], dict[int, dict[str, float]]] = defaultdict(dict)
    for campaign, cid in metadata:
        seeds = sorted({key[2] for key in receptor_values if key[:2] == (campaign, cid)})
        for seed in seeds:
            key8, key9 = (campaign, cid, seed, "8x6b"), (campaign, cid, seed, "9e6y")
            values: dict[str, float] = {}
            if key8 in receptor_values:
                values["R8"] = receptor_values[key8]
            if key9 in receptor_values:
                values["R9"] = receptor_values[key9]
            if "R8" in values and "R9" in values:
                values["Rdual"] = min(values["R8"], values["R9"])
            if values:
                measurements[(campaign, cid)][seed] = values
        target_counts = {
            target: sum(target in value for value in measurements[(campaign, cid)].values())
            for target in TARGETS
        }
        if min(target_counts.values()) < 2:
            raise DiagnosticError(f"fewer_than_two_paired_seeds:{campaign}:{cid}")
    return dict(measurements), metadata


def validate_references(
    measurements: Mapping[tuple[str, str], Mapping[int, Mapping[str, float]]],
    v4d_reference: Path,
    v4h_reference: Path,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    v4d_rows = [r for r in read_tsv(v4d_reference) if r.get("model_split") == "OPEN_TRAIN"]
    if len(v4d_rows) != 226:
        raise DiagnosticError(f"v4d_reference_open_train_count:{len(v4d_rows)}")
    refs: dict[tuple[str, str], dict[str, float]] = {}
    for r in v4d_rows:
        refs[("V4D", r["candidate_id"])] = {
            "R8": finite(r["R_8X6B"], "v4d_R8"),
            "R9": finite(r["R_9E6Y"], "v4d_R9"),
            "Rdual": finite(r["R_dual_min"], "v4d_Rdual"),
        }
    v4h_rows = read_tsv(v4h_reference)
    repeat_v4h = [r for r in v4h_rows if min(int(r["successful_seed_count_8X6B"]), int(r["successful_seed_count_9E6Y"])) >= 2]
    if len(repeat_v4h) != 364:
        raise DiagnosticError(f"v4h_reference_repeat_count:{len(repeat_v4h)}")
    for r in repeat_v4h:
        refs[("V4H", r["candidate_id"])] = {
            "R8": finite(r["median_score_8X6B"], "v4h_R8"),
            "R9": finite(r["median_score_9E6Y"], "v4h_R9"),
            "Rdual": finite(r["R_dual_min"], "v4h_Rdual"),
        }
    if set(measurements) != set(refs):
        raise DiagnosticError(f"reference_candidate_set_mismatch:{len(measurements)}:{len(refs)}")
    max_abs = {target: 0.0 for target in TARGETS}
    for key, seed_map in measurements.items():
        medians = {
            target: statistics.median(v[target] for v in seed_map.values() if target in v)
            for target in ("R8", "R9")
        }
        # Existing teachers define Rdual as min of receptor medians, not median of seedwise minima.
        medians["Rdual"] = min(medians["R8"], medians["R9"])
        for target in TARGETS:
            delta = abs(medians[target] - refs[key][target])
            max_abs[target] = max(max_abs[target], delta)
            if delta > tolerance:
                raise DiagnosticError(f"terminal_reference_mismatch:{key}:{target}:{delta}")
    return {
        "status": "PASS_PER_SEED_MEDIANS_MATCH_TERMINAL_TEACHERS",
        "candidate_count": len(refs),
        "max_absolute_difference": max_abs,
        "tolerance": tolerance,
    }


def candidate_variance_rows(measurements, metadata) -> list[dict[str, Any]]:
    out = []
    for (campaign, cid), seed_map in sorted(measurements.items()):
        target_seed_ids = {
            target: sorted(seed for seed, value in seed_map.items() if target in value)
            for target in TARGETS
        }
        paired_count = len(target_seed_ids["Rdual"])
        row: dict[str, Any] = {
            "campaign": campaign,
            "candidate_id": cid,
            **metadata[(campaign, cid)],
            "repeat_tier": cohort_key(campaign, paired_count),
            "paired_seed_count": paired_count,
            "paired_seed_ids": ",".join(map(str, target_seed_ids["Rdual"])),
            "R8_seed_count": len(target_seed_ids["R8"]),
            "R8_seed_ids": ",".join(map(str, target_seed_ids["R8"])),
            "R9_seed_count": len(target_seed_ids["R9"]),
            "R9_seed_ids": ",".join(map(str, target_seed_ids["R9"])),
        }
        for target in TARGETS:
            values = [seed_map[s][target] for s in target_seed_ids[target]]
            row[f"{target}_mean"] = f"{statistics.mean(values):.12g}"
            row[f"{target}_median"] = f"{statistics.median(values):.12g}"
            row[f"{target}_sample_variance"] = f"{statistics.variance(values):.12g}"
            row[f"{target}_sd"] = f"{statistics.stdev(values):.12g}"
            row[f"{target}_range"] = f"{max(values)-min(values):.12g}"
        row["claim_boundary"] = CLAIM
        out.append(row)
    return out


def reliability_rows(measurements) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    campaigns = sorted({key[0] for key in measurements})
    for campaign in campaigns:
        campaign_items = {cid: m for (src, cid), m in measurements.items() if src == campaign}
        for target in TARGETS:
            for i, seed_a in enumerate(SEEDS):
                for seed_b in SEEDS[i + 1:]:
                    pairs = [
                        (m[seed_a][target], m[seed_b][target])
                        for m in campaign_items.values()
                        if seed_a in m and seed_b in m and target in m[seed_a] and target in m[seed_b]
                    ]
                    if len(pairs) < 10:
                        continue
                    x, y = np.asarray([p[0] for p in pairs]), np.asarray([p[1] for p in pairs])
                    rho = spearman(x, y)
                    low, high = bootstrap_spearman_ci(x, y, seed=20260718 + seed_a + seed_b)
                    out.append({
                        "campaign": campaign, "cohort": f"PAIR_{seed_a}_{seed_b}", "target": target,
                        "method": "seed_pair_test_retest", "seed_a": seed_a, "seed_b": seed_b,
                        "candidate_count": len(pairs), "spearman": f"{rho:.12g}",
                        "spearman_bootstrap95_low": f"{low:.12g}", "spearman_bootstrap95_high": f"{high:.12g}",
                        "mae": f"{np.mean(np.abs(x-y)):.12g}", "rmse": f"{np.sqrt(np.mean((x-y)**2)):.12g}",
                        "icc_1_1": "", "claim_boundary": CLAIM,
                    })
            for seed_set in ((917, 1931), (917, 1931, 3253)):
                complete = [
                    m for m in campaign_items.values()
                    if all(seed in m and target in m[seed] for seed in seed_set)
                ]
                if len(complete) < 10:
                    continue
                matrix = np.asarray([[m[s][target] for s in seed_set] for m in complete], dtype=float)
                out.append({
                    "campaign": campaign, "cohort": "COMPLETE_" + "_".join(map(str, seed_set)), "target": target,
                    "method": "ICC_1_1", "seed_a": "", "seed_b": "", "candidate_count": len(complete),
                    "spearman": "", "spearman_bootstrap95_low": "", "spearman_bootstrap95_high": "",
                    "mae": "", "rmse": "", "icc_1_1": f"{icc_1_1(matrix):.12g}", "claim_boundary": CLAIM,
                })
    return out


def score_bin_rows(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        groups[(row["campaign"], row["repeat_tier"])].append(row)
    for (campaign, tier), rows in sorted(groups.items()):
        for target in TARGETS:
            score = np.asarray([float(r[f"{target}_mean"]) for r in rows])
            variance = np.asarray([float(r[f"{target}_sample_variance"]) for r in rows])
            order = np.argsort(score, kind="mergesort")
            bins = np.array_split(order, 4)
            for index, idx in enumerate(bins, 1):
                if len(idx) == 0:
                    continue
                out.append({
                    "campaign": campaign, "repeat_tier": tier, "target": target, "score_bin": f"Q{index}",
                    "candidate_count": len(idx), "score_min": f"{score[idx].min():.12g}", "score_max": f"{score[idx].max():.12g}",
                    "mean_within_candidate_variance": f"{variance[idx].mean():.12g}",
                    "median_within_candidate_variance": f"{np.median(variance[idx]):.12g}",
                    "p90_within_candidate_variance": f"{np.quantile(variance[idx], .9):.12g}",
                    "adaptive_selection_caveat": "true" if campaign == "V4H" else "false",
                    "claim_boundary": CLAIM,
                })
    return out


def source_tier_summary(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        groups[(row["campaign"], row["repeat_tier"])].append(row)
    out = []
    for (campaign, tier), rows in sorted(groups.items()):
        for target in TARGETS:
            vars_ = np.asarray([float(r[f"{target}_sample_variance"]) for r in rows])
            sds = np.sqrt(vars_)
            out.append({
                "campaign": campaign, "repeat_tier": tier, "target": target, "candidate_count": len(rows),
                "mean_sample_variance": f"{vars_.mean():.12g}", "median_sample_variance": f"{np.median(vars_):.12g}",
                "p90_sample_variance": f"{np.quantile(vars_, .9):.12g}", "mean_within_candidate_sd": f"{sds.mean():.12g}",
                "adaptive_selection_caveat": "true" if campaign == "V4H" else "false", "claim_boundary": CLAIM,
            })
    return out


def noise_ceiling(measurements) -> dict[str, Any]:
    results = []
    for campaign in sorted({key[0] for key in measurements}):
        for target in TARGETS:
            items = [
                m for (src, _), m in measurements.items()
                if src == campaign and all(seed in m and target in m[seed] for seed in SEEDS)
            ]
            if len(items) < 10:
                continue
            matrix = np.asarray([[m[s][target] for s in SEEDS] for m in items], dtype=float)
            icc = icc_1_1(matrix)
            icc_mean3 = (3 * icc / (1 + 2 * icc)) if math.isfinite(icc) and (1 + 2 * icc) != 0 else float("nan")
            holdout = []
            for col, seed in enumerate(SEEDS):
                other = matrix[:, [i for i in range(3) if i != col]].mean(axis=1)
                truth = matrix[:, col]
                rho = spearman(truth, other)
                low, high = bootstrap_spearman_ci(truth, other, seed=20260718 + seed)
                holdout.append({
                    "heldout_seed": seed, "spearman_heldout_vs_other2_mean": rho,
                    "spearman_bootstrap95_low": low, "spearman_bootstrap95_high": high,
                    "mae": float(np.mean(np.abs(truth-other))), "rmse": float(np.sqrt(np.mean((truth-other)**2))),
                })
            results.append({
                "campaign": campaign, "target": target, "candidate_count": len(items), "seed_ids": list(SEEDS),
                "icc_1_1_single_seed": icc, "icc_reliability_of_mean3": icc_mean3,
                "classical_max_corr_with_single_seed_if_error_model_holds": math.sqrt(max(icc, 0.0)) if math.isfinite(icc) else None,
                "classical_max_corr_with_mean3_if_error_model_holds": math.sqrt(max(icc_mean3, 0.0)) if math.isfinite(icc_mean3) else None,
                "empirical_leave_one_seed_out": holdout,
            })
    return {
        "schema_version": "pvrig_v2_5_repeat_seed_empirical_noise_ceiling_v1",
        "status": "PASS_DESCRIPTIVE_EMPIRICAL_REPEAT_SEED_CEILING",
        "interpretation": "These are replicate-consistency ceilings under the observed sampling scheme, not biological or Docking-Gold ceilings.",
        "results": results, "claim_boundary": CLAIM,
    }


def run(v4d_scores: Path, v4h_scores: Path, v4d_reference: Path, v4h_reference: Path, output_dir: Path) -> dict[str, Any]:
    rows = read_tsv(v4d_scores) + read_tsv(v4h_scores)
    if any(row["campaign"].upper() not in {"V4D", "V4H"} for row in rows):
        raise DiagnosticError("unexpected_campaign")
    measurements, metadata = build_measurements(rows)
    reference_closure = validate_references(measurements, v4d_reference, v4h_reference)
    candidate_rows = candidate_variance_rows(measurements, metadata)
    reliability = reliability_rows(measurements)
    bins = score_bin_rows(candidate_rows)
    source_tiers = source_tier_summary(candidate_rows)
    ceiling = noise_ceiling(measurements)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "candidate_variance": output_dir / "candidate_repeat_seed_variance.tsv",
        "reliability": output_dir / "repeat_seed_reliability.tsv",
        "score_bins": output_dir / "score_bin_variance.tsv",
        "source_tiers": output_dir / "source_tier_variance.tsv",
        "noise_ceiling": output_dir / "EMPIRICAL_NOISE_CEILING.json",
    }
    write_tsv(paths["candidate_variance"], candidate_rows)
    write_tsv(paths["reliability"], reliability)
    write_tsv(paths["score_bins"], bins)
    write_tsv(paths["source_tiers"], source_tiers)
    paths["noise_ceiling"].write_text(json.dumps(ceiling, indent=2, sort_keys=True) + "\n")
    key_findings: dict[str, Any] = {
        "schema_version": "pvrig_v2_5_repeat_seed_noise_key_findings_v1",
        "status": "PASS_DESCRIPTIVE_KEY_FINDINGS",
        "campaigns": {},
        "frozen_interpretive_constraints": [
            "V4-H repeat candidates were adaptively selected after seed917 and are not an unbiased full-range reliability sample.",
            "Repeated seeds are measurement replicates, not independent candidates or training rows.",
            "V4-D OPEN_TRAIN is the more defensible source for a global scalar teacher noise ceiling.",
        ],
        "claim_boundary": CLAIM,
    }
    for campaign in ("V4D", "V4H"):
        pair_rows = [
            row for row in reliability
            if row["campaign"] == campaign and row["target"] == "Rdual" and row["method"] == "seed_pair_test_retest"
        ]
        ceiling_row = next(
            row for row in ceiling["results"] if row["campaign"] == campaign and row["target"] == "Rdual"
        )
        tier_rows = [row for row in source_tiers if row["campaign"] == campaign and row["target"] == "Rdual"]
        bin_rows = [row for row in bins if row["campaign"] == campaign and row["target"] == "Rdual"]
        key_findings["campaigns"][campaign] = {
            "Rdual_seed_pair_spearman": [
                {
                    "cohort": row["cohort"], "candidate_count": int(row["candidate_count"]),
                    "spearman": float(row["spearman"]),
                    "bootstrap95": [float(row["spearman_bootstrap95_low"]), float(row["spearman_bootstrap95_high"])],
                    "mae": float(row["mae"]),
                }
                for row in pair_rows
            ],
            "Rdual_three_seed_icc_1_1": ceiling_row["icc_1_1_single_seed"],
            "Rdual_classical_mean3_reliability": ceiling_row["icc_reliability_of_mean3"],
            "Rdual_classical_max_corr_with_mean3": ceiling_row["classical_max_corr_with_mean3_if_error_model_holds"],
            "Rdual_leave_one_seed_out_spearman": [
                row["spearman_heldout_vs_other2_mean"] for row in ceiling_row["empirical_leave_one_seed_out"]
            ],
            "Rdual_repeat_tier_variance": tier_rows,
            "Rdual_score_bin_variance": bin_rows,
        }
    (output_dir / "KEY_FINDINGS.json").write_text(json.dumps(key_findings, indent=2, sort_keys=True) + "\n")
    tier_counts: dict[str, int] = defaultdict(int)
    for row in candidate_rows:
        tier_counts[row["repeat_tier"]] += 1
    provenance = {
        "schema_version": "pvrig_v2_5_repeat_seed_noise_provenance_v1", "status": "PASS_SOURCE_AND_REFERENCE_CLOSURE",
        "input_sha256": {p.name: sha256_file(p) for p in (v4d_scores, v4h_scores, v4d_reference, v4h_reference)},
        "reference_closure": reference_closure, "v4_f_or_test32_results_accessed": 0,
        "candidate_is_statistical_unit": True, "repeat_seed_rows_treated_as_independent_training_rows": False,
        "claim_boundary": CLAIM,
    }
    (output_dir / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    summary = {
        "schema_version": "pvrig_v2_5_repeat_seed_noise_diagnostic_v1", "status": "PASS_OPEN_DEVELOPMENT_REPEAT_SEED_DIAGNOSTIC",
        "candidate_count": len(candidate_rows), "campaign_candidate_counts": {
            campaign: sum(row["campaign"] == campaign for row in candidate_rows) for campaign in ("V4D", "V4H")
        },
        "repeat_tier_counts": dict(sorted(tier_counts.items())), "scalar_source_row_count": len(rows),
        "reference_closure": reference_closure, "v4_f_or_test32_results_accessed": 0,
        "claim_boundary": CLAIM,
    }
    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--v4d-scores", type=Path, required=True)
    p.add_argument("--v4h-scores", type=Path, required=True)
    p.add_argument("--v4d-reference", type=Path, required=True)
    p.add_argument("--v4h-reference", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.v4d_scores, a.v4h_scores, a.v4d_reference, a.v4h_reference, a.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
