#!/usr/bin/env python3
"""Merge sequence-only binding-model outputs into an auditable prior table.

The resulting consensus is a weak binding prior.  It is not a Kd, an IC50, or
PVRIG-PVRL2 blocking evidence.  Missing model outputs remain missing and never
silently become zero.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Iterable, Sequence


ID_COLUMNS = (
    "candidate_id", "nanobody_id", "nanobody id", "nanobody-id", "id",
    "name", "fasta_id", "molecule_name",
)
SCORE_COLUMNS = (
    "binding_prior", "binding_prior_score", "probability", "prediction",
    "probabilities", "binder_score", "deepnano_score", "binding_score", "score",
)
AFFINITY_COLUMNS = (
    "nanobind_affinity_range", "predicted_kd_intervals", "predicted_kd_interval",
    "affinity_range", "kd_range",
)
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates_fasta", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--deepnano", type=Path)
    parser.add_argument("--nabp-bert", type=Path)
    parser.add_argument("--nanobind-seq", type=Path)
    parser.add_argument("--nanobind-affinity", type=Path)
    parser.add_argument("--deepnano-id-column")
    parser.add_argument("--deepnano-score-column")
    parser.add_argument("--nabp-id-column")
    parser.add_argument("--nabp-score-column")
    parser.add_argument("--nanobind-id-column")
    parser.add_argument("--nanobind-score-column")
    parser.add_argument("--nanobind-affinity-id-column")
    parser.add_argument("--nanobind-affinity-column")
    parser.add_argument(
        "--disagreement-threshold", type=float, default=0.25,
        help="Flag multi-model max-minus-min disagreement at or above this value.",
    )
    args = parser.parse_args(argv)
    if not 0.0 <= args.disagreement_threshold <= 1.0:
        parser.error("--disagreement-threshold must be within [0, 1]")
    return args


def normalize_column(value: str) -> str:
    return re.sub(r"[\s_-]+", "_", value.strip().lower())


def resolve_column(fieldnames: Iterable[str], explicit: str | None, choices: Iterable[str]) -> str:
    fields = list(fieldnames)
    if explicit:
        if explicit not in fields:
            raise ValueError(f"Column {explicit!r} not found; available={fields}")
        return explicit
    by_normalized = {normalize_column(field): field for field in fields}
    for choice in choices:
        found = by_normalized.get(normalize_column(choice))
        if found:
            return found
    raise ValueError(f"No supported column found; choices={list(choices)}, available={fields}")


def read_table(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []
    first = text.splitlines()[0]
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def read_fasta_ids(path: Path) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(">"):
            candidate_id = raw[1:].strip().split()[0]
            if not candidate_id:
                raise ValueError("Empty FASTA identifier")
            if candidate_id in seen:
                raise ValueError(f"Duplicate FASTA identifier: {candidate_id}")
            seen.add(candidate_id)
            ids.append(candidate_id)
    if not ids:
        raise ValueError(f"No FASTA records found in {path}")
    return ids


def parse_probability(value: str) -> float:
    numbers = NUMBER_RE.findall(str(value))
    if not numbers:
        raise ValueError(f"Not a numeric probability: {value!r}")
    # TensorFlow NABP-BERT commonly serializes the two class probabilities;
    # the positive-class probability is the final value.
    score = float(numbers[-1])
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"Probability outside [0, 1]: {value!r}")
    return score


def load_score_map(
    path: Path | None,
    *,
    id_column: str | None,
    score_column: str | None,
) -> dict[str, float]:
    if path is None:
        return {}
    rows = read_table(path)
    if not rows:
        return {}
    id_key = resolve_column(rows[0].keys(), id_column, ID_COLUMNS)
    score_key = resolve_column(rows[0].keys(), score_column, SCORE_COLUMNS)
    output: dict[str, float] = {}
    for row in rows:
        candidate_id = str(row.get(id_key, "")).strip()
        raw_score = str(row.get(score_key, "")).strip()
        if not candidate_id or not raw_score:
            continue
        if candidate_id in output:
            raise ValueError(f"Duplicate candidate_id {candidate_id!r} in {path}")
        output[candidate_id] = parse_probability(raw_score)
    return output


def load_text_map(
    path: Path | None,
    *,
    id_column: str | None,
    value_column: str | None,
) -> dict[str, str]:
    if path is None:
        return {}
    rows = read_table(path)
    if not rows:
        return {}
    id_key = resolve_column(rows[0].keys(), id_column, ID_COLUMNS)
    value_key = resolve_column(rows[0].keys(), value_column, AFFINITY_COLUMNS)
    output: dict[str, str] = {}
    for row in rows:
        candidate_id = str(row.get(id_key, "")).strip()
        value = str(row.get(value_key, "")).strip()
        if not candidate_id or not value:
            continue
        if candidate_id in output:
            raise ValueError(f"Duplicate candidate_id {candidate_id!r} in {path}")
        output[candidate_id] = value
    return output


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.8f}"


def build_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    candidate_ids = read_fasta_ids(args.candidates_fasta)
    deepnano = load_score_map(
        args.deepnano,
        id_column=args.deepnano_id_column,
        score_column=args.deepnano_score_column,
    )
    nabp = load_score_map(
        args.nabp_bert,
        id_column=args.nabp_id_column,
        score_column=args.nabp_score_column,
    )
    nanobind = load_score_map(
        args.nanobind_seq,
        id_column=args.nanobind_id_column,
        score_column=args.nanobind_score_column,
    )
    affinity = load_text_map(
        args.nanobind_affinity,
        id_column=args.nanobind_affinity_id_column,
        value_column=args.nanobind_affinity_column,
    )
    rows: list[dict[str, str]] = []
    for candidate_id in candidate_ids:
        named_scores = [
            ("DeepNano", deepnano.get(candidate_id)),
            ("NABP-BERT", nabp.get(candidate_id)),
            ("NanoBind-seq", nanobind.get(candidate_id)),
        ]
        available = [(name, score) for name, score in named_scores if score is not None]
        values = [score for _, score in available]
        consensus = sum(values) / len(values) if values else None
        disagreement = max(values) - min(values) if len(values) >= 2 else None
        if not available:
            status = "NO_BINDING_MODEL"
        elif len(available) == 1:
            status = "SINGLE_MODEL_ONLY"
        elif disagreement is not None and disagreement >= args.disagreement_threshold:
            status = "MULTI_MODEL_DISAGREEMENT"
        else:
            status = "MULTI_MODEL_CONSENSUS"
        rows.append({
            "candidate_id": candidate_id,
            "deepnano_binding_prior": fmt(deepnano.get(candidate_id)),
            "nabp_binding_prior": fmt(nabp.get(candidate_id)),
            "nanobind_binding_prior": fmt(nanobind.get(candidate_id)),
            "nanobind_affinity_range": affinity.get(candidate_id, ""),
            "binding_model_count": str(len(available)),
            "binding_prior_consensus": fmt(consensus),
            "binding_model_disagreement": fmt(disagreement),
            "binding_prior_status": status,
            "binding_prior_source": ";".join(name for name, _ in available),
        })
    return rows


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    write_tsv(args.output, build_rows(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
