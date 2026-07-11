#!/usr/bin/env python3
"""Convert model candidate ranks into a bounded cascade front-screen summary."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent

DEFAULT_INPUT = EXP_DIR / "predictions/pvrig_candidate_ranking_ai_prior_v2_4_multiseed_ensemble.csv"
DEFAULT_OUTPUT = EXP_DIR / "predictions/pvrig_model_frontscreen_summary_v1.csv"

ID_COLUMNS = ("candidate_id", "id", "name", "fasta_id", "molecule_name")
SCORE_COLUMNS = (
    "phase2_v2_4_sequence_ensemble_score",
    "phase2_v2_3_combined_ranking_ai_prior",
    "phase2_v2_3_sigmoid_pair_ranking_ai_prior",
    "ai_prior_mean",
    "model_screen_score",
    "score",
)
CLAIM_BOUNDARY = "relative_model_frontscreen_priority_not_binding_or_blocker_probability"


def select_column(frame: pd.DataFrame, requested: str | None, candidates: tuple[str, ...], label: str) -> str:
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"Requested {label} column is missing: {requested}")
        return requested
    for column in candidates:
        if column in frame.columns:
            return column
    raise ValueError(f"Could not identify a {label} column from {candidates}")


def prepare_summary(
    input_path: Path,
    output_path: Path,
    *,
    id_column: str | None = None,
    score_column: str | None = None,
) -> pd.DataFrame:
    frame = pd.read_csv(input_path)
    id_column = select_column(frame, id_column, ID_COLUMNS, "candidate ID")
    score_column = select_column(frame, score_column, SCORE_COLUMNS, "model score")
    candidate_ids = frame[id_column].astype(str).str.strip()
    if candidate_ids.eq("").any() or candidate_ids.duplicated().any():
        raise ValueError("Model front-screen candidate IDs must be non-empty and unique")
    scores = pd.to_numeric(frame[score_column], errors="coerce")
    if scores.isna().any() or not scores.map(math.isfinite).all():
        raise ValueError(f"Model front-screen score column must be finite numeric data: {score_column}")

    ranks = scores.rank(method="min", ascending=False).astype(int)
    denominator = max(len(frame) - 1, 1)
    bounded = (len(frame) - ranks) / denominator
    if len(frame) == 1:
        bounded[:] = 1.0

    output = pd.DataFrame(
        {
            "candidate_id": candidate_ids,
            # The cascade expects this field name, but its semantics remain relative ranking only.
            "binder_score": bounded.astype(float),
            "model_screen_score_raw": scores.astype(float),
            "model_screen_rank": ranks,
            "model_screen_score_column": score_column,
            "model_screen_source_file": input_path.name,
            "score_semantics": "within_input_rank_percentile_higher_is_better",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    ).sort_values(["model_screen_rank", "candidate_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False, lineterminator="\n")
    return output


def map_candidate_ids(
    summary: pd.DataFrame,
    map_path: Path,
    *,
    source_column: str,
    target_column: str,
) -> pd.DataFrame:
    mapping = pd.read_csv(map_path, dtype=str)
    missing = sorted({source_column, target_column} - set(mapping.columns))
    if missing:
        raise ValueError(f"Candidate ID map is missing columns: {missing}")
    mapping = mapping[[source_column, target_column]].copy()
    if mapping[source_column].duplicated().any() or mapping[target_column].duplicated().any():
        raise ValueError("Candidate ID map source and target IDs must both be unique")
    mapped = summary.merge(mapping, left_on="candidate_id", right_on=source_column, how="inner", validate="one_to_one")
    mapped["candidate_id"] = mapped[target_column]
    mapped["blinding_status"] = "BLINDED_ID_ONLY"
    drop_columns = [target_column]
    if source_column != "candidate_id":
        drop_columns.append(source_column)
    return mapped.drop(columns=drop_columns).sort_values(["model_screen_rank", "candidate_id"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--id-column")
    parser.add_argument("--score-column")
    parser.add_argument("--id-map", type=Path)
    parser.add_argument("--map-source-column", default="candidate_id")
    parser.add_argument("--map-target-column", default="assay_sample_id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = prepare_summary(
        args.input,
        args.output,
        id_column=args.id_column,
        score_column=args.score_column,
    )
    if args.id_map:
        output = map_candidate_ids(
            output,
            args.id_map,
            source_column=args.map_source_column,
            target_column=args.map_target_column,
        )
        output.to_csv(args.output, index=False, lineterminator="\n")
    print(
        json.dumps(
            {
                "rows": len(output),
                "output": str(args.output),
                "claim_boundary": CLAIM_BOUNDARY,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
