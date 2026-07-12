#!/usr/bin/env python3
"""Select a parent-balanced 500-candidate prospective PVRIG teacher panel."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_INPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv"
DEFAULT_OUTPUT = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500"
SEED = "pvrig_teacher500_v1_seed107"
PARENT_CAP = 13
STRATUM_CAP = 4
SPLIT_QUOTAS = {"train": 350, "dev": 75, "test": 75}
LAYER_SPLIT_QUOTAS = {
    "high_prior": {"train": 98, "dev": 21, "test": 21},
    "boundary": {"train": 70, "dev": 15, "test": 15},
    "low_prior_qc_pass": {"train": 42, "dev": 9, "test": 9},
    "diversity": {"train": 84, "dev": 18, "test": 18},
    "uncertainty_disagreement": {"train": 56, "dev": 12, "test": 12},
}
CLAIM_BOUNDARY = "prospective_teacher_sampling_not_binding_docking_or_blocking_truth"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}\t{value}".encode()).hexdigest()


def cdr3_kmers(sequence: str, k: int = 3) -> set[str]:
    sequence = str(sequence)
    return {sequence[index : index + k] for index in range(max(0, len(sequence) - k + 1))}


def jaccard_distance(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 - (len(left & right) / len(union) if union else 1.0)


def prepare_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "candidate_id", "sequence_sha256", "parent_id", "formal_split",
        "target_patch_id", "design_mode", "cdr3_after", "fast_gate_tier",
        "generic_binding_prior", "model_uncertainty",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Teacher input is missing {sorted(missing)}")
    frame = frame[frame["fast_gate_tier"].astype(str).isin({"FORMAL_ELIGIBLE", "RESERVE_REVIEW"})].copy()
    if frame["sequence_sha256"].duplicated().any():
        raise ValueError("Teacher input must be exact-sequence deduplicated")
    if set(frame["formal_split"].astype(str)) != set(SPLIT_QUOTAS):
        raise ValueError("Teacher input must cover train/dev/test parent splits")
    frame["generic_binding_prior"] = pd.to_numeric(frame["generic_binding_prior"], errors="raise")
    frame["model_uncertainty"] = pd.to_numeric(frame["model_uncertainty"], errors="raise")
    if "model_disagreement" not in frame:
        frame["model_disagreement"] = frame["model_uncertainty"]
    if "cheap_qc_score" not in frame:
        frame["cheap_qc_score"] = 1.0
    frame["model_disagreement"] = pd.to_numeric(frame["model_disagreement"], errors="raise")
    frame["cheap_qc_score"] = pd.to_numeric(frame["cheap_qc_score"], errors="raise")
    frame["_stable"] = frame["candidate_id"].astype(str).map(stable_key)
    frame["_stratum"] = frame["parent_id"].astype(str) + "|" + frame["target_patch_id"].astype(str) + "|" + frame["design_mode"].astype(str)
    frame["_cdr3_kmers"] = frame["cdr3_after"].astype(str).map(cdr3_kmers)
    frame["_diversity_min_distance"] = 1.0
    frame["_prior_percentile"] = frame.groupby("formal_split")["generic_binding_prior"].rank(pct=True, method="average")
    return frame.reset_index(drop=True)


def select_panel(frame: pd.DataFrame) -> pd.DataFrame:
    indices = list(frame.index)
    parent_by_index = frame["parent_id"].astype(str).to_dict()
    split_by_index = frame["formal_split"].astype(str).to_dict()
    stratum_by_index = frame["_stratum"].astype(str).to_dict()
    stable_by_index = frame["_stable"].astype(str).to_dict()
    kmers_by_index = frame["_cdr3_kmers"].to_dict()
    diversity_min_distance = {index: 1.0 for index in indices}
    static_scores = {
        "high_prior": {
            index: (-float(frame.at[index, "generic_binding_prior"]), -float(frame.at[index, "cheap_qc_score"]))
            for index in indices
        },
        "boundary": {
            index: (abs(float(frame.at[index, "_prior_percentile"]) - 0.5), -float(frame.at[index, "cheap_qc_score"]))
            for index in indices
        },
        "low_prior_qc_pass": {
            index: (float(frame.at[index, "generic_binding_prior"]), -float(frame.at[index, "cheap_qc_score"]))
            for index in indices
        },
        "uncertainty_disagreement": {
            index: (
                -max(float(frame.at[index, "model_uncertainty"]), float(frame.at[index, "model_disagreement"])),
                -float(frame.at[index, "cheap_qc_score"]),
            )
            for index in indices
        },
    }
    selected_indices: list[int] = []
    selected_set: set[int] = set()
    parent_counts: Counter[str] = Counter()
    stratum_counts: Counter[str] = Counter()
    layer_by_index: dict[int, str] = {}
    layer_rank_by_index: dict[int, int] = {}

    def eligible(index: int, split: str) -> bool:
        if index in selected_set:
            return False
        return (
            split_by_index[index] == split
            and parent_counts[parent_by_index[index]] < PARENT_CAP
            and stratum_counts[stratum_by_index[index]] < STRATUM_CAP
        )

    def choose_layer(
        layer: str,
        split: str,
        quota: int,
        score: Callable[[int], tuple[Any, ...]],
    ) -> None:
        for layer_rank in range(1, quota + 1):
            candidates = [index for index in indices if eligible(index, split)]
            if not candidates:
                raise ValueError(f"Cannot fill {layer}/{split}; selected {layer_rank - 1} of {quota}")
            index = min(
                candidates,
                key=lambda candidate: (
                    parent_counts[parent_by_index[candidate]],
                    stratum_counts[stratum_by_index[candidate]],
                    *score(candidate),
                    stable_by_index[candidate],
                ),
            )
            selected_indices.append(index)
            selected_set.add(index)
            layer_by_index[index] = layer
            layer_rank_by_index[index] = layer_rank
            parent_counts[parent_by_index[index]] += 1
            stratum_counts[stratum_by_index[index]] += 1
            selected_kmers = kmers_by_index[index]
            for candidate in indices:
                if candidate in selected_set:
                    continue
                diversity_min_distance[candidate] = min(
                    diversity_min_distance[candidate],
                    jaccard_distance(kmers_by_index[candidate], selected_kmers),
                )

    scorers: dict[str, Callable[[int], tuple[Any, ...]]] = {
        **{layer: (lambda index, layer=layer: static_scores[layer][index]) for layer in static_scores},
        "diversity": lambda index: (
            -diversity_min_distance[index],
            -float(frame.at[index, "cheap_qc_score"]),
        ),
    }
    for layer in ("high_prior", "boundary", "low_prior_qc_pass", "uncertainty_disagreement", "diversity"):
        for split, quota in LAYER_SPLIT_QUOTAS[layer].items():
            choose_layer(layer, split, quota, scorers[layer])

    output = frame.loc[selected_indices].copy()
    output["teacher_selection_layer"] = [layer_by_index[index] for index in selected_indices]
    output["layer_rank"] = [layer_rank_by_index[index] for index in selected_indices]
    output["selection_rank"] = range(1, len(output) + 1)
    output["teacher_claim_boundary"] = CLAIM_BOUNDARY
    return output.drop(columns=[column for column in output.columns if column.startswith("_")]).reset_index(drop=True)


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    frame = prepare_frame(input_path)
    selected = select_panel(frame)
    if len(selected) != 500:
        raise AssertionError(f"Teacher panel has {len(selected)} rows, expected 500")
    split_counts = dict(Counter(selected["formal_split"].astype(str)))
    layer_counts = dict(Counter(selected["teacher_selection_layer"].astype(str)))
    if split_counts != SPLIT_QUOTAS:
        raise AssertionError(f"Split quotas changed: {split_counts}")
    expected_layers = {name: sum(values.values()) for name, values in LAYER_SPLIT_QUOTAS.items()}
    if layer_counts != expected_layers:
        raise AssertionError(f"Layer quotas changed: {layer_counts}")
    parent_counts = Counter(selected["parent_id"].astype(str))
    stratum_counts = Counter(
        selected["parent_id"].astype(str)
        + "|" + selected["target_patch_id"].astype(str)
        + "|" + selected["design_mode"].astype(str)
    )
    if max(parent_counts.values()) > PARENT_CAP or max(stratum_counts.values()) > STRATUM_CAP:
        raise AssertionError("Teacher cap violation")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "pvrig_teacher500_manifest_v1.csv"
    fasta_path = output_dir / "pvrig_teacher500_v1.fasta"
    selected.to_csv(csv_path, index=False)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in selected.itertuples(index=False):
            handle.write(f">{row.candidate_id}\n{row.vhh_sequence}\n")
    audit: dict[str, Any] = {
        "status": "PASS_TEACHER500_SELECTED",
        "schema_version": "pvrig_formal_teacher500_selection_audit_v1",
        "seed": SEED,
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "eligible_input_candidates": len(frame),
        "selected_candidates": len(selected),
        "split_counts": split_counts,
        "layer_counts": layer_counts,
        "parent_count": len(parent_counts),
        "parent_count_range": [min(parent_counts.values()), max(parent_counts.values())],
        "parent_cap": PARENT_CAP,
        "parent_patch_mode_cap": STRATUM_CAP,
        "max_observed_parent_patch_mode_count": max(stratum_counts.values()),
        "output_paths": {"manifest": str(csv_path), "fasta": str(fasta_path)},
        "output_sha256": {"manifest": sha256_file(csv_path), "fasta": sha256_file(fasta_path)},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (output_dir / "teacher500_selection_audit_v1.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.input, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
