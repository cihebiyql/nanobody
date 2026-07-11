#!/usr/bin/env python3
"""Summarize Phase 2 V2.3 multi-seed metrics and candidate rankings.

This tool keeps the pair-level boundary explicit: V2.3 pair metrics named
``pair_contrastive_proxy_*`` are constructed-contrast metrics, not binding AUROC
or calibrated non-binding labels.
"""
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

SCHEMA_VERSION = "pvrig_vhh_phase2_v2_3_multiseed_summary_v1"
PAIR_PROXY_BOUNDARY = "pair_contrastive_proxy metrics are constructed contrast metrics, not binding AUROC"
NOT_APPLICABLE = "NOT_APPLICABLE"

METRIC_PREFIXES = ("contact_", "paratope_", "epitope_", "ranking_", "pair_contrastive_proxy_")
METRIC_SECTIONS = ("contact_test", "site_test", "ranking_test", "pair_test")
CANDIDATE_ID_COLUMNS = ("candidate_id", "id", "name")
RANK_COLUMNS = ("rank", "candidate_rank", "phase2_v2_3_rank")
LOGIT_COLUMNS = ("phase2_v2_3_pair_ranking_logit", "pair_ranking_logit", "logit")
AI_PRIOR_COLUMNS = (
    "phase2_v2_3_combined_ranking_ai_prior",
    "combined_ranking_ai_prior",
    "phase2_v2_3_sigmoid_pair_ranking_ai_prior",
    "sigmoid_pair_ranking_ai_prior",
    "ai_prior",
)
VERIFIED_LABEL_COLUMNS = ("verified_binary_label", "verified_binding_label", "binding_label_verified")
CALIBRATION_SCORE_COLUMNS = ("calibrated_probability", "predicted_probability", "probability", "score")
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
    return {
        "mean": float(sum(values) / len(values)),
        "std": float(_std(values)),
        "min": float(min(values)),
        "max": float(max(values)),
    }


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


def _infer_seed(metrics: dict[str, Any], metrics_path: Path, config: dict[str, Any] | None) -> str:
    for source in (metrics, config or {}):
        value = _clean(source.get("seed"))
        if value:
            return value
    match = re.search(r"(?:^|[_-])seed(\d+)(?:\D|$)", str(metrics_path.parent))
    if match:
        return match.group(1)
    raise ValueError(f"Cannot infer seed; add seed to metrics/config or run path: {metrics_path}")


def _infer_run_id(metrics: dict[str, Any], metrics_path: Path) -> str:
    return _clean(metrics.get("run_id")) or metrics_path.parent.name or metrics_path.stem


def _infer_schema(metrics: dict[str, Any], config: dict[str, Any] | None) -> str:
    return _clean(metrics.get("schema_version")) or _clean((config or {}).get("schema_version")) or "UNKNOWN"


def _load_config_for(metrics_path: Path) -> dict[str, Any] | None:
    config_path = metrics_path.parent / "config_resolved.json"
    if not config_path.exists():
        return None
    return _read_json(config_path)


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
        raise ValueError(f"Metrics contain no selected V2.3 contact/site/ranking/proxy metrics: {metrics_path}")
    return RunRecord(
        input_path=path,
        metrics_path=metrics_path,
        run_id=_infer_run_id(metrics, metrics_path),
        seed=_infer_seed(metrics, metrics_path, config),
        schema=_infer_schema(metrics, config),
        dataset_sizes=dataset_sizes,
        metrics=selected,
    )


def validate_runs(runs: list[RunRecord]) -> None:
    if not runs:
        raise ValueError("At least one metrics input is required")
    seeds = [run.seed for run in runs]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"Duplicate seed values are not allowed: {seeds}")
    run_ids = [run.run_id for run in runs]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError(f"Duplicate run_id values are not allowed: {run_ids}")
    schemas = {run.schema for run in runs}
    if len(schemas) > 1:
        raise ValueError(f"Schema mismatch across runs: {sorted(schemas)}")
    baseline = runs[0].dataset_sizes
    for run in runs[1:]:
        if run.dataset_sizes != baseline:
            raise ValueError(
                "Dataset size mismatch across strict V2.3 runs: "
                f"{runs[0].run_id}={baseline} vs {run.run_id}={run.dataset_sizes}"
            )


def summarize_metrics(runs: list[RunRecord]) -> dict[str, Any]:
    by_metric: dict[str, list[float]] = {}
    for run in runs:
        for key, value in run.metrics.items():
            by_metric.setdefault(key, []).append(value)
    summary: dict[str, Any] = {}
    for metric in sorted(by_metric):
        values = by_metric[metric]
        summary[metric] = {"n": len(values), **_summary_stats(values)}
    return summary


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


def _candidate_seed(row: pd.Series, supplied_seed: str | None, path: Path) -> str:
    if supplied_seed:
        return supplied_seed
    for col in ("seed", "run_seed"):
        if col in row and _clean(row[col]):
            return _clean(row[col])
    match = re.search(r"(?:^|[_-])seed(\d+)(?:\D|$)", path.name)
    if match:
        return match.group(1)
    raise ValueError(f"Candidate CSV seed is ambiguous; pass seed=path: {path}")


def load_candidate_rankings(candidate_csv_args: list[str]) -> tuple[pd.DataFrame, str, str]:
    rows: list[dict[str, Any]] = []
    prior_columns_seen: list[str] = []
    schemas_seen: list[str] = []
    for arg in candidate_csv_args:
        supplied_seed, path = _parse_seed_path(arg)
        if not path.exists():
            raise FileNotFoundError(f"Missing candidate ranking CSV: {path}")
        df = pd.read_csv(path)
        if "schema_version" in df.columns:
            schemas_seen.extend(_clean(value) for value in df["schema_version"].dropna().unique() if _clean(value))
        candidate_col = _pick_column(df.columns, CANDIDATE_ID_COLUMNS)
        rank_col = _pick_column(df.columns, RANK_COLUMNS)
        logit_col = _pick_column(df.columns, LOGIT_COLUMNS)
        prior_col = _pick_column(df.columns, AI_PRIOR_COLUMNS)
        missing = [name for name, col in (("candidate_id", candidate_col), ("rank", rank_col), ("logit", logit_col), ("AI-prior", prior_col)) if col is None]
        if missing:
            raise ValueError(f"Candidate CSV {path} missing required columns: {missing}")
        prior_columns_seen.append(str(prior_col))
        for _, row in df.iterrows():
            seed = _candidate_seed(row, supplied_seed, path)
            rank = _numeric(row[rank_col])
            logit = _numeric(row[logit_col])
            prior = _numeric(row[prior_col])
            if rank is None or logit is None or prior is None:
                continue
            rows.append(
                {
                    "seed": seed,
                    "candidate_id": _clean(row[candidate_col]),
                    "rank": rank,
                    "pair_ranking_logit": logit,
                    "ai_prior": prior,
                }
            )
    candidate_schemas = sorted(set(schemas_seen))
    if len(candidate_schemas) > 1:
        raise ValueError(f"Candidate ranking schema mismatch across CSV inputs: {candidate_schemas}")
    return pd.DataFrame(rows), ";".join(sorted(set(prior_columns_seen))), (candidate_schemas[0] if candidate_schemas else "")


def summarize_candidates(candidate_csv_args: list[str], expected_seeds: set[str]) -> tuple[list[dict[str, Any]], str, str]:
    if not candidate_csv_args:
        return [], "", ""
    df, prior_column, candidate_schema = load_candidate_rankings(candidate_csv_args)
    if df.empty:
        return [], prior_column, candidate_schema
    csv_seeds = {str(s) for s in df["seed"].unique()}
    extra = csv_seeds - expected_seeds
    if extra:
        raise ValueError(f"Candidate CSV seed(s) not present in metrics inputs: {sorted(extra)}")
    missing = expected_seeds - csv_seeds
    if missing:
        raise ValueError(f"Candidate CSV missing seed(s) present in metrics inputs: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for candidate_id, group in df.groupby("candidate_id", sort=True):
        ranks = [float(v) for v in group["rank"].tolist()]
        logits = [float(v) for v in group["pair_ranking_logit"].tolist()]
        priors = [float(v) for v in group["ai_prior"].tolist()]
        rows.append(
            {
                "candidate_id": candidate_id,
                "n_seeds": int(group["seed"].nunique()),
                "seeds": ";".join(sorted(str(s) for s in group["seed"].unique())),
                "rank_mean": sum(ranks) / len(ranks),
                "rank_std": _std(ranks),
                "rank_median": float(median(ranks)),
                "rank_min": min(ranks),
                "rank_max": max(ranks),
                "pair_ranking_logit_mean": sum(logits) / len(logits),
                "pair_ranking_logit_std": _std(logits),
                "ai_prior_mean": sum(priors) / len(priors),
                "ai_prior_std": _std(priors),
            }
        )
    rows.sort(key=lambda r: (r["rank_mean"], -r["ai_prior_mean"], r["candidate_id"]))
    for idx, row in enumerate(rows, start=1):
        row["consensus_rank"] = idx
    return rows, prior_column, candidate_schema


def _looks_unverified(columns: Iterable[str], row: pd.Series) -> bool:
    lower_cols = {c.lower(): c for c in columns}
    for col in ("label_source", "label_state", "source", "metric_boundary"):
        actual = lower_cols.get(col)
        if actual and re.search(r"constructed|contrastive|proxy|unverified", _clean(row[actual]), re.I):
            return True
    return False


def _load_calibration_rows(args: list[str]) -> list[tuple[float, float]]:
    valid: list[tuple[float, float]] = []
    for arg in args:
        _, path = _parse_seed_path(arg)
        if not path.exists():
            raise FileNotFoundError(f"Missing calibration CSV: {path}")
        df = pd.read_csv(path)
        label_col = _pick_column(df.columns, VERIFIED_LABEL_COLUMNS)
        score_col = _pick_column(df.columns, CALIBRATION_SCORE_COLUMNS)
        if label_col is None or score_col is None:
            continue
        for _, row in df.iterrows():
            if _looks_unverified(df.columns, row):
                continue
            y = _numeric(row[label_col])
            p = _numeric(row[score_col])
            if y not in (0.0, 1.0) or p is None:
                continue
            valid.append((float(y), min(max(float(p), 0.0), 1.0)))
    return valid


def summarize_calibration(calibration_csv_args: list[str]) -> dict[str, Any]:
    if not calibration_csv_args:
        return {"status": NOT_APPLICABLE, "reason": "no explicit verified binary calibration labels were provided"}
    rows = _load_calibration_rows(calibration_csv_args)
    labels = {y for y, _ in rows}
    if labels != {0.0, 1.0}:
        return {
            "status": NOT_APPLICABLE,
            "reason": "explicit verified binary labels with both positive and negative classes are required; constructed contrasts are ignored",
            "valid_verified_rows": len(rows),
            "classes_present": sorted(labels),
        }
    y = [v[0] for v in rows]
    p = [v[1] for v in rows]
    brier = sum((pi - yi) ** 2 for yi, pi in zip(y, p)) / len(rows)
    return {"status": "PASS", "n": len(rows), "brier": brier, "ece": expected_calibration_error(y, p)}


def expected_calibration_error(labels: list[float], scores: list[float], bins: int = 10) -> float:
    total = len(labels)
    ece = 0.0
    for idx in range(bins):
        lo = idx / bins
        hi = (idx + 1) / bins
        members = [i for i, score in enumerate(scores) if (lo <= score < hi) or (idx == bins - 1 and score == 1.0)]
        if not members:
            continue
        acc = sum(labels[i] for i in members) / len(members)
        conf = sum(scores[i] for i in members) / len(members)
        ece += (len(members) / total) * abs(acc - conf)
    return ece


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    runs = [load_run(Path(value)) for value in args.inputs]
    validate_runs(runs)
    candidates, prior_column, candidate_schema = summarize_candidates(args.candidate_csv, {run.seed for run in runs})
    summary = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "input_schema": runs[0].schema,
        "pair_proxy_boundary": PAIR_PROXY_BOUNDARY,
        "n_runs": len(runs),
        "seeds": [run.seed for run in runs],
        "run_ids": [run.run_id for run in runs],
        "dataset_sizes": runs[0].dataset_sizes,
        "metrics": summarize_metrics(runs),
        "calibration": summarize_calibration(args.calibration_csv),
        "candidate_summary": candidates,
        "candidate_ai_prior_source_column": prior_column,
        "candidate_ranking_schema": candidate_schema,
    }
    return summary


def write_json(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 2 V2.3 Multi-Seed Summary",
        "",
        f"- Status: {summary['status']}",
        f"- Runs: {summary['n_runs']}",
        f"- Seeds: {', '.join(summary['seeds'])}",
        f"- Boundary: {summary['pair_proxy_boundary']}",
        f"- Calibration: {summary['calibration']['status']} ({summary['calibration'].get('reason', 'verified labels present')})",
        "",
        "## Metrics",
        "",
        "| metric | n | mean | std | min | max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, stats in summary["metrics"].items():
        lines.append(f"| {name} | {stats['n']} | {stats['mean']:.6g} | {stats['std']:.6g} | {stats['min']:.6g} | {stats['max']:.6g} |")
    if summary["candidate_summary"]:
        lines.extend(["", "## Candidate Consensus", "", "| consensus_rank | candidate_id | n_seeds | rank_mean | rank_std | rank_median | ai_prior_mean |", "| ---: | --- | ---: | ---: | ---: | ---: | ---: |"])
        for row in summary["candidate_summary"]:
            lines.append(
                f"| {row['consensus_rank']} | {row['candidate_id']} | {row['n_seeds']} | {row['rank_mean']:.6g} | {row['rank_std']:.6g} | {row['rank_median']:.6g} | {row['ai_prior_mean']:.6g} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_candidate_csv(summary: dict[str, Any], path: Path) -> None:
    rows = summary["candidate_summary"]
    fieldnames = [
        "consensus_rank",
        "candidate_id",
        "n_seeds",
        "seeds",
        "rank_mean",
        "rank_std",
        "rank_median",
        "rank_min",
        "rank_max",
        "pair_ranking_logit_mean",
        "pair_ranking_logit_std",
        "ai_prior_mean",
        "ai_prior_std",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="V2.3 run directories or test_metrics.json files")
    parser.add_argument("--candidate-csv", action="append", default=[], help="Optional seed=CSV V2.3 candidate ranking output; may be repeated")
    parser.add_argument("--calibration-csv", action="append", default=[], help="Optional seed=CSV with explicit verified binary labels and probabilities; may be repeated")
    parser.add_argument("--output-json", required=True, help="Summary JSON output path")
    parser.add_argument("--output-md", required=True, help="Markdown report output path")
    parser.add_argument("--output-candidates-csv", required=True, help="Candidate consensus CSV output path")
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
