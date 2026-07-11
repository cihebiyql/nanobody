#!/usr/bin/env python3
"""Summarize Phase 2 V2.4 three-seed metrics and candidate rankings."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pandas as pd

SCHEMA_VERSION = "pvrig_vhh_phase2_v2_4_multiseed_summary_v1"
EXPECTED_CHECKPOINT_SCHEMA = "phase2_v2_4_listwise_ranking_checkpoint_v1"
PAIR_PROXY_BOUNDARY = "V2.4 complete-group listwise ranking uses constructed contrast candidates; N1/N2/N3 are not verified non-binders"
NOT_APPLICABLE = "NOT_APPLICABLE"
METRIC_PREFIXES = ("contact_", "paratope_", "epitope_", "ranking_", "pair_contrastive_proxy_")
METRIC_SECTIONS = ("contact_test", "site_test", "ranking_test", "pair_test")
CANDIDATE_ID_COLUMNS = ("candidate_id", "id", "name")
RANK_COLUMNS = ("rank", "candidate_rank", "phase2_v2_4_rank")
LOGIT_COLUMNS = ("phase2_v2_4_pair_ranking_logit", "pair_ranking_logit", "logit")
AI_PRIOR_COLUMNS = ("phase2_v2_4_combined_ranking_ai_prior", "combined_ranking_ai_prior", "phase2_v2_4_sigmoid_pair_ranking_ai_prior", "ai_prior")
IDENTITY_COLUMNS = ("candidate_identity_sha256",)
VHH_HASH_COLUMNS = ("vhh_sequence_sha256", "sequence_sha256")
TARGET_HASH_COLUMNS = ("target_sequence_sha256",)


@dataclass(frozen=True)
class RunRecord:
    input_path: Path
    metrics_path: Path
    run_id: str
    seed: str
    schema: str
    dataset_sizes: dict[str, Any]
    metrics: dict[str, float]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _summary_stats(values: list[float]) -> dict[str, float]:
    return {"mean": float(sum(values) / len(values)), "std": float(_std(values)), "min": float(min(values)), "max": float(max(values))}


def _resolve_metrics_path(path: Path) -> Path:
    if path.is_dir():
        metrics = path / "test_metrics.json"
        if not metrics.exists():
            raise FileNotFoundError(f"Run directory is missing test_metrics.json: {path}")
        return metrics
    if not path.exists():
        raise FileNotFoundError(f"Missing metrics input: {path}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"JSON input must contain an object: {path}")
    return raw


def _load_config_for(metrics_path: Path) -> dict[str, Any] | None:
    config_path = metrics_path.parent / "config_resolved.json"
    return _read_json(config_path) if config_path.exists() else None


def _infer_seed(metrics: dict[str, Any], metrics_path: Path, config: dict[str, Any] | None) -> str:
    for source in (metrics, config or {}):
        value = _clean(source.get("seed"))
        if value:
            return value
    match = re.search(r"(?:^|[_-])seed(\d+)(?:\D|$)", str(metrics_path.parent))
    if match:
        return match.group(1)
    raise ValueError(f"Cannot infer seed: {metrics_path}")


def _flatten_selected_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for section in METRIC_SECTIONS:
        payload = metrics.get(section, {})
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if key.startswith(METRIC_PREFIXES):
                numeric = _numeric(value)
                if numeric is not None:
                    out[key] = numeric
    return out


def load_run(path: Path) -> RunRecord:
    metrics_path = _resolve_metrics_path(path)
    metrics = _read_json(metrics_path)
    config = _load_config_for(metrics_path)
    dataset_sizes = metrics.get("dataset_sizes")
    if not isinstance(dataset_sizes, dict) or not dataset_sizes:
        raise ValueError(f"Metrics missing non-empty dataset_sizes: {metrics_path}")
    selected = _flatten_selected_metrics(metrics)
    if not selected:
        raise ValueError(f"Metrics contain no selected V2.4 metrics: {metrics_path}")
    schema = _clean(metrics.get("schema_version")) or _clean((config or {}).get("schema_version")) or EXPECTED_CHECKPOINT_SCHEMA
    if schema != EXPECTED_CHECKPOINT_SCHEMA:
        raise ValueError(f"Incompatible V2.4 metrics schema: expected {EXPECTED_CHECKPOINT_SCHEMA}, observed {schema}")
    return RunRecord(
        input_path=path,
        metrics_path=metrics_path,
        run_id=_clean(metrics.get("run_id")) or metrics_path.parent.name or metrics_path.stem,
        seed=_infer_seed(metrics, metrics_path, config),
        schema=schema,
        dataset_sizes=dataset_sizes,
        metrics=selected,
    )


def validate_runs(runs: list[RunRecord], expected_seeds: int = 3) -> None:
    if len(runs) != expected_seeds:
        raise ValueError(f"Expected exactly {expected_seeds} V2.4 seed runs, observed {len(runs)}")
    seeds = [run.seed for run in runs]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"Duplicate seed values are not allowed: {seeds}")
    baseline = runs[0].dataset_sizes
    for run in runs[1:]:
        if run.dataset_sizes != baseline:
            raise ValueError(f"Dataset size mismatch across V2.4 runs: {runs[0].run_id}={baseline} vs {run.run_id}={run.dataset_sizes}")


def summarize_metrics(runs: list[RunRecord]) -> dict[str, Any]:
    by_metric: dict[str, list[float]] = {}
    for run in runs:
        for key, value in run.metrics.items():
            by_metric.setdefault(key, []).append(value)
    return {metric: {"n": len(values), **_summary_stats(values)} for metric, values in sorted(by_metric.items())}


def _parse_seed_path(value: str) -> tuple[str | None, Path]:
    if "=" in value:
        seed, path = value.split("=", 1)
        return _clean(seed), Path(path)
    return None, Path(value)


def _pick_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    available = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in available:
            return available[candidate.lower()]
    return None


def _candidate_seed(df: pd.DataFrame, supplied_seed: str | None, path: Path) -> str:
    if supplied_seed:
        return supplied_seed
    for col in ("phase2_v2_4_seed", "seed", "run_seed"):
        if col in df.columns:
            values = sorted({_clean(v) for v in df[col].dropna().unique() if _clean(v)})
            if len(values) == 1:
                return values[0]
    match = re.search(r"(?:^|[_-])seed(\d+)(?:\D|$)", path.name)
    if match:
        return match.group(1)
    raise ValueError(f"Candidate CSV seed is ambiguous; pass seed=path: {path}")


def load_candidate_rankings(candidate_csv_args: list[str]) -> tuple[pd.DataFrame, str]:
    rows: list[dict[str, Any]] = []
    prior_columns_seen: list[str] = []
    identity_by_candidate: dict[str, tuple[str, str, str]] = {}
    for arg in candidate_csv_args:
        supplied_seed, path = _parse_seed_path(arg)
        if not path.exists():
            raise FileNotFoundError(f"Missing candidate ranking CSV: {path}")
        df = pd.read_csv(path)
        if "schema_version" in df.columns:
            schemas = {_clean(v) for v in df["schema_version"].dropna().unique() if _clean(v)}
            if schemas and schemas != {"pvrig_vhh_phase2_v2_4_listwise_ranking_ai_prior_v1"}:
                raise ValueError(f"Candidate ranking schema mismatch in {path}: {sorted(schemas)}")
        seed = _candidate_seed(df, supplied_seed, path)
        candidate_col = _pick_column(df.columns, CANDIDATE_ID_COLUMNS)
        rank_col = _pick_column(df.columns, RANK_COLUMNS)
        logit_col = _pick_column(df.columns, LOGIT_COLUMNS)
        prior_col = _pick_column(df.columns, AI_PRIOR_COLUMNS)
        identity_col = _pick_column(df.columns, IDENTITY_COLUMNS)
        vhh_hash_col = _pick_column(df.columns, VHH_HASH_COLUMNS)
        target_hash_col = _pick_column(df.columns, TARGET_HASH_COLUMNS)
        missing = [name for name, col in (("candidate_id", candidate_col), ("rank", rank_col), ("logit", logit_col), ("AI-prior", prior_col), ("candidate_identity_sha256", identity_col), ("vhh_sequence_sha256", vhh_hash_col), ("target_sequence_sha256", target_hash_col)) if col is None]
        if missing:
            raise ValueError(f"Candidate CSV {path} missing required columns: {missing}")
        prior_columns_seen.append(str(prior_col))
        for _, row in df.iterrows():
            candidate_id = _clean(row[candidate_col])
            identity = (_clean(row[identity_col]).lower(), _clean(row[vhh_hash_col]).lower(), _clean(row[target_hash_col]).lower())
            if candidate_id in identity_by_candidate and identity_by_candidate[candidate_id] != identity:
                raise ValueError(f"Candidate identity mismatch across seed CSVs for {candidate_id}")
            identity_by_candidate[candidate_id] = identity
            rank = _numeric(row[rank_col])
            logit = _numeric(row[logit_col])
            prior = _numeric(row[prior_col])
            if rank is None or logit is None or prior is None:
                continue
            rows.append({"seed": seed, "candidate_id": candidate_id, "candidate_identity_sha256": identity[0], "rank": rank, "pair_ranking_logit": logit, "ai_prior": prior})
    return pd.DataFrame(rows), ";".join(sorted(set(prior_columns_seen)))


def summarize_candidates(candidate_csv_args: list[str], expected_seeds: set[str]) -> tuple[list[dict[str, Any]], str]:
    if not candidate_csv_args:
        return [], ""
    df, prior_column = load_candidate_rankings(candidate_csv_args)
    if df.empty:
        return [], prior_column
    csv_seeds = {str(s) for s in df["seed"].unique()}
    if csv_seeds != expected_seeds:
        raise ValueError(f"Candidate CSV seed set mismatch: expected {sorted(expected_seeds)}, observed {sorted(csv_seeds)}")
    expected_count = len(expected_seeds)
    rows: list[dict[str, Any]] = []
    for candidate_id, group in df.groupby("candidate_id", sort=True):
        if int(group["seed"].nunique()) != expected_count:
            raise ValueError(f"Candidate {candidate_id} missing from one or more seed CSVs")
        ranks = [float(v) for v in group["rank"].tolist()]
        logits = [float(v) for v in group["pair_ranking_logit"].tolist()]
        priors = [float(v) for v in group["ai_prior"].tolist()]
        per_seed = {str(row["seed"]): {"rank": float(row["rank"]), "pair_ranking_logit": float(row["pair_ranking_logit"]), "ai_prior": float(row["ai_prior"])} for _, row in group.iterrows()}
        rows.append({
            "candidate_id": candidate_id,
            "candidate_identity_sha256": _clean(group.iloc[0]["candidate_identity_sha256"]),
            "n_seeds": expected_count,
            "seeds": ";".join(sorted(str(s) for s in group["seed"].unique())),
            "rank_mean": sum(ranks) / len(ranks),
            "rank_std": _std(ranks),
            "rank_median": float(median(ranks)),
            "rank_min": min(ranks),
            "rank_max": max(ranks),
            "rank_range": max(ranks) - min(ranks),
            "rank_stability": "stable" if max(ranks) - min(ranks) <= 2 else "variable",
            "pair_ranking_logit_mean": sum(logits) / len(logits),
            "pair_ranking_logit_std": _std(logits),
            "ai_prior_mean": sum(priors) / len(priors),
            "ai_prior_std": _std(priors),
            "per_seed_scores_json": json.dumps(per_seed, ensure_ascii=False, sort_keys=True),
        })
    rows.sort(key=lambda r: (r["rank_mean"], r["rank_std"], -r["ai_prior_mean"], r["candidate_id"]))
    denominator = max(len(rows) - 1, 1)
    for idx, row in enumerate(rows, start=1):
        row["consensus_rank"] = idx
        row["phase2_v2_4_sequence_ensemble_score"] = 1.0 - (idx - 1) / denominator
    return rows, prior_column


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    runs = [load_run(Path(value)) for value in args.inputs]
    validate_runs(runs, args.expected_seeds)
    candidates, prior_column = summarize_candidates(args.candidate_csv, {run.seed for run in runs})
    return {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "input_schema": EXPECTED_CHECKPOINT_SCHEMA,
        "pair_proxy_boundary": PAIR_PROXY_BOUNDARY,
        "n_runs": len(runs),
        "seeds": [run.seed for run in runs],
        "run_ids": [run.run_id for run in runs],
        "dataset_sizes": runs[0].dataset_sizes,
        "metrics": summarize_metrics(runs),
        "calibration": {"status": NOT_APPLICABLE, "reason": "no verified positive-and-negative probability labels; constructed N1/N2/N3 contrasts are ignored"},
        "candidate_summary": candidates,
        "candidate_ai_prior_source_column": prior_column,
    }


def write_json(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 2 V2.4 Three-Seed Summary", "",
        f"- Status: {summary['status']}",
        f"- Runs: {summary['n_runs']}",
        f"- Seeds: {', '.join(summary['seeds'])}",
        f"- Boundary: {summary['pair_proxy_boundary']}",
        f"- Calibration: {summary['calibration']['status']} ({summary['calibration']['reason']})", "",
        "## Metrics", "", "| metric | n | mean | std | min | max |", "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in summary["metrics"].items():
        lines.append(f"| {name} | {stats['n']} | {stats['mean']:.6g} | {stats['std']:.6g} | {stats['min']:.6g} | {stats['max']:.6g} |")
    if summary["candidate_summary"]:
        lines.extend(["", "## Candidate Consensus", "", "| consensus_rank | candidate_id | n_seeds | rank_mean | rank_std | rank_range | stability | ai_prior_mean |", "| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: |"])
        for row in summary["candidate_summary"]:
            lines.append(f"| {row['consensus_rank']} | {row['candidate_id']} | {row['n_seeds']} | {row['rank_mean']:.6g} | {row['rank_std']:.6g} | {row['rank_range']:.6g} | {row['rank_stability']} | {row['ai_prior_mean']:.6g} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_candidate_csv(summary: dict[str, Any], path: Path) -> None:
    rows = summary["candidate_summary"]
    fieldnames = ["consensus_rank", "candidate_id", "candidate_identity_sha256", "n_seeds", "seeds", "rank_mean", "rank_std", "rank_median", "rank_min", "rank_max", "rank_range", "rank_stability", "pair_ranking_logit_mean", "pair_ranking_logit_std", "phase2_v2_4_sequence_ensemble_score", "ai_prior_mean", "ai_prior_std", "per_seed_scores_json"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Exactly three V2.4 run dirs or test_metrics.json files")
    parser.add_argument("--candidate-csv", action="append", default=[], help="Optional seed=CSV V2.4 candidate ranking output; repeat for each seed")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--output-candidates-csv", required=True)
    parser.add_argument("--expected-seeds", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    summary = build_summary(args)
    write_json(summary, Path(args.output_json))
    write_markdown(summary, Path(args.output_md))
    write_candidate_csv(summary, Path(args.output_candidates_csv))
    print(json.dumps({"status": summary["status"], "output_json": args.output_json, "output_md": args.output_md, "output_candidates_csv": args.output_candidates_csv}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
