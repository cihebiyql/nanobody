#!/usr/bin/env python3
"""Prepare open development and sealed formal data for the V3 binding prior."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from phase2_v3_contracts import (
    ContractError,
    ensure_no_label_columns,
    normalize_antigen_sequence,
    normalize_vhh_sequence,
    sha256_file,
    sha256_text,
    stable_pair_id,
    write_csv_atomic,
    write_json_atomic,
)

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_DATASET_ROOT = DATA_ROOT / "datasets" / "24_hf_nanobody"
DEFAULT_OUTPUT = EXP_DIR / "prepared" / "phase2_v3_binding"
DEFAULT_PVRIG_PANEL = EXP_DIR / "data_splits" / "pvrig_v2_5_prospective_assay_panel.csv"
DEFAULT_PVRIG_CONSTRUCT = EXP_DIR / "assays" / "pvrig_v2_5_prospective_v1" / "construct_manifest.csv"

MODEL_INPUT_COLUMNS = [
    "sample_id",
    "dataset_id",
    "source_split",
    "split",
    "formal_block",
    "target_id",
    "vhh_sequence",
    "target_sequence",
    "sequence_sha256",
    "target_sequence_sha256",
    "vhh_sequence_length",
    "target_sequence_length",
    "normalization_events",
    "subject_id",
    "evidence_level",
    "ground_truth_kind",
    "allowed_use",
    "sealed_status",
    "claim_boundary",
]
TRAIN_COLUMNS = MODEL_INPUT_COLUMNS + ["label"]


@dataclass(frozen=True)
class SourceSpec:
    dataset_id: str
    csv_path: Path
    source_split: str
    split: str
    formal_block: str = ""
    antigen_map_path: Path | None = None


def default_sources(dataset_root: Path) -> list[SourceSpec]:
    return [
        SourceSpec("nbbench_sars", dataset_root / "NbBench/SARS-CoV-2/train.csv", "train", "train"),
        SourceSpec("nbbench_sars", dataset_root / "NbBench/SARS-CoV-2/val.csv", "val", "dev"),
        SourceSpec("nbbench_hil6", dataset_root / "NbBench/hIL6/train.csv", "train", "train"),
        SourceSpec("nbbench_hil6", dataset_root / "NbBench/hIL6/val.csv", "val", "dev"),
        SourceSpec(
            "avida_htnfa",
            dataset_root / "AVIDa-hTNFa/AVIDa-hTNFa.csv",
            "external",
            "formal",
            "external_hTNFa",
            dataset_root / "AVIDa-hTNFa/antigen_sequences.csv",
        ),
        SourceSpec(
            "nbbench_sars",
            dataset_root / "NbBench/SARS-CoV-2/test.csv",
            "test",
            "formal",
            "sars_target_transfer",
        ),
        SourceSpec(
            "nbbench_hil6",
            dataset_root / "NbBench/hIL6/test.csv",
            "test",
            "formal",
            "hil6_mutant_transfer",
        ),
    ]


def load_antigen_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    frame = pd.read_csv(path)
    required = {"Ag_label", "Ag_sequence"}
    if required - set(frame.columns):
        raise ContractError(f"Antigen map {path} is missing {sorted(required - set(frame.columns))}")
    return {str(row.Ag_label): str(row.Ag_sequence) for row in frame.itertuples(index=False)}


def iter_source_rows(spec: SourceSpec, chunksize: int) -> Iterable[dict[str, Any]]:
    antigen_map = load_antigen_map(spec.antigen_map_path)
    for chunk in pd.read_csv(spec.csv_path, chunksize=chunksize):
        required = {"VHH_sequence", "Ag_label", "label"}
        if required - set(chunk.columns):
            raise ContractError(f"Source {spec.csv_path} is missing {sorted(required - set(chunk.columns))}")
        for row in chunk.to_dict("records"):
            target = row.get("Ag_sequence") or antigen_map.get(str(row.get("Ag_label", "")), "")
            yield {
                "vhh": row.get("VHH_sequence"),
                "target": target,
                "target_id": str(row.get("Ag_label", "")),
                "label": row.get("label"),
                "subject_id": str(row.get("subject_name", "")),
            }


def normalize_source(spec: SourceSpec, chunksize: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rejected = Counter()
    trim_events = Counter()
    input_rows = 0
    for source in iter_source_rows(spec, chunksize):
        input_rows += 1
        try:
            vhh = normalize_vhh_sequence(source["vhh"])
            target = normalize_antigen_sequence(source["target"])
            label = int(source["label"])
            if label not in {0, 1}:
                raise ContractError(f"Binary label must be 0 or 1, got {label}")
        except (ContractError, TypeError, ValueError) as exc:
            rejected[type(exc).__name__ + ":" + str(exc)] += 1
            continue
        vhh_sha = sha256_text(vhh.sequence)
        target_sha = sha256_text(target.sequence)
        for event in vhh.normalization_events:
            trim_events[event.split(":", 1)[0]] += 1
        rows.append(
            {
                "sample_id": stable_pair_id(vhh_sha, target_sha),
                "dataset_id": spec.dataset_id,
                "source_split": spec.source_split,
                "split": spec.split,
                "formal_block": spec.formal_block,
                "target_id": source["target_id"],
                "vhh_sequence": vhh.sequence,
                "target_sequence": target.sequence,
                "sequence_sha256": vhh_sha,
                "target_sequence_sha256": target_sha,
                "vhh_sequence_length": len(vhh.sequence),
                "target_sequence_length": len(target.sequence),
                "normalization_events": ";".join(vhh.normalization_events),
                "subject_id": source["subject_id"],
                "evidence_level": "E4_REAL_BINARY_BINDING_ASSAY",
                "ground_truth_kind": "real_assay_binary_binding",
                "allowed_use": "GENERIC_BINDING_PRIOR_ONLY",
                "sealed_status": "SEALED_LABELS" if spec.split == "formal" else "OPEN_DEVELOPMENT",
                "claim_boundary": "binary_binding_prior_not_affinity_or_blocking_truth",
                "label": label,
            }
        )
    return rows, {
        "input_rows": input_rows,
        "accepted_rows_before_dedup": len(rows),
        "rejected_rows": input_rows - len(rows),
        "rejection_reasons": dict(rejected),
        "normalization_events": dict(trim_events),
    }


def deduplicate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["sample_id"])].append(row)
    output: list[dict[str, Any]] = []
    conflicts = []
    merged_duplicate_rows = 0
    for sample_id, group in sorted(grouped.items()):
        labels = {int(row["label"]) for row in group}
        locations = {(str(row["split"]), str(row["formal_block"])) for row in group}
        if len(locations) > 1:
            raise ContractError(f"Exact pair {sample_id} crosses development/formal or formal blocks: {sorted(locations)}")
        if len(labels) > 1:
            conflicts.append({"sample_id": sample_id, "row_count": len(group), "labels": sorted(labels)})
            continue
        representative = dict(group[0])
        representative["source_row_count"] = len(group)
        representative["dataset_id"] = ";".join(sorted({str(row["dataset_id"]) for row in group}))
        representative["subject_id"] = ";".join(sorted({str(row["subject_id"]) for row in group if row["subject_id"]}))
        output.append(representative)
        merged_duplicate_rows += len(group) - 1
    return output, {
        "unique_pairs": len(output),
        "merged_duplicate_rows": merged_duplicate_rows,
        "conflicting_pair_count": len(conflicts),
        "conflicting_pairs": conflicts[:100],
    }


def build_sequence_manifest(
    rows: list[dict[str, Any]], extra_sequences: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    sequences: dict[str, dict[str, Any]] = {}
    for row in rows:
        for role, sha_col, seq_col in (
            ("vhh", "sequence_sha256", "vhh_sequence"),
            ("antigen", "target_sequence_sha256", "target_sequence"),
        ):
            sha = str(row[sha_col])
            sequence = str(row[seq_col])
            entry = sequences.setdefault(sha, {"sequence_sha256": sha, "sequence": sequence, "roles": set()})
            if entry["sequence"] != sequence:
                raise ContractError(f"SHA256 collision for {sha}")
            entry["roles"].add(role)
    for extra in extra_sequences or []:
        sha = str(extra["sequence_sha256"])
        sequence = str(extra["sequence"])
        role = str(extra["role"])
        entry = sequences.setdefault(sha, {"sequence_sha256": sha, "sequence": sequence, "roles": set()})
        if entry["sequence"] != sequence:
            raise ContractError(f"SHA256 collision for deployment sequence {sha}")
        entry["roles"].update({role, "deployment"})
    return [
        {
            "sequence_sha256": sha,
            "sequence": item["sequence"],
            "sequence_length": len(item["sequence"]),
            "roles": ";".join(sorted(item["roles"])),
        }
        for sha, item in sorted(sequences.items())
    ]


def load_pvrig_deployment_sequences(panel_path: Path, construct_path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    panel = pd.read_csv(panel_path)
    required = {"candidate_id", "vhh_sequence", "sequence_sha256"}
    if required - set(panel.columns) or len(panel) != 24 or panel["candidate_id"].nunique() != 24:
        raise ContractError("PVRIG deployment panel must contain 24 unique candidate rows")
    extras: list[dict[str, str]] = []
    for row in panel.to_dict("records"):
        normalized = normalize_vhh_sequence(row["vhh_sequence"])
        observed = sha256_text(normalized.sequence)
        if observed != str(row["sequence_sha256"]):
            raise ContractError(f"PVRIG panel sequence hash mismatch for {row['candidate_id']}")
        extras.append({"sequence_sha256": observed, "sequence": normalized.sequence, "role": "vhh"})

    construct = pd.read_csv(construct_path)
    target_required = {"target_sequence", "target_sequence_sha256"}
    if target_required - set(construct.columns):
        raise ContractError("PVRIG construct manifest lacks target sequence provenance")
    target_pairs = construct[["target_sequence", "target_sequence_sha256"]].drop_duplicates()
    if len(target_pairs) != 1:
        raise ContractError("PVRIG construct manifest must reference exactly one frozen target sequence")
    target_row = target_pairs.iloc[0]
    target = normalize_antigen_sequence(target_row["target_sequence"])
    target_sha = sha256_text(target.sequence)
    if target_sha != str(target_row["target_sequence_sha256"]):
        raise ContractError("PVRIG target sequence hash mismatch")
    extras.append({"sequence_sha256": target_sha, "sequence": target.sequence, "role": "antigen"})
    return extras, {
        "panel_path": str(panel_path),
        "panel_sha256": sha256_file(panel_path),
        "candidate_count": 24,
        "target_construct_path": str(construct_path),
        "target_construct_sha256": sha256_file(construct_path),
        "target_sequence_sha256": target_sha,
    }


def validate_split_policy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    development = [row for row in rows if row["split"] in {"train", "dev"}]
    formal = [row for row in rows if row["split"] == "formal"]
    development_pairs = {row["sample_id"] for row in development}
    formal_pairs = {row["sample_id"] for row in formal}
    if development_pairs & formal_pairs:
        raise ContractError("Exact development/formal pair leakage detected")
    dev_vhh = {row["sequence_sha256"] for row in development}
    overlaps: dict[str, int] = {}
    for block in sorted({str(row["formal_block"]) for row in formal}):
        block_vhh = {row["sequence_sha256"] for row in formal if row["formal_block"] == block}
        overlaps[block] = len(dev_vhh & block_vhh)
    if overlaps.get("external_hTNFa", 0) != 0:
        raise ContractError("Primary external hTNFa block overlaps development VHH hashes")
    return {
        "development_formal_pair_overlap": 0,
        "formal_vhh_overlap_with_development_by_block": overlaps,
        "primary_external_hTNFa_vhh_overlap": overlaps.get("external_hTNFa", 0),
    }


def filter_primary_vhh_overlap(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    development_vhh = {
        str(row["sequence_sha256"])
        for row in rows
        if str(row["split"]) in {"train", "dev"}
    }
    excluded = [
        row
        for row in rows
        if str(row["formal_block"]) == "external_hTNFa"
        and str(row["sequence_sha256"]) in development_vhh
    ]
    excluded_ids = {str(row["sample_id"]) for row in excluded}
    filtered = [row for row in rows if str(row["sample_id"]) not in excluded_ids]
    return filtered, {
        "policy": "exclude_primary_formal_rows_with_development_vhh_sha256_overlap",
        "excluded_row_count": len(excluded),
        "excluded_sample_ids": sorted(excluded_ids),
    }


def prepare(
    sources: list[SourceSpec],
    output_dir: Path,
    chunksize: int = 100_000,
    deployment_sequences: list[dict[str, str]] | None = None,
    deployment_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    source_audits = []
    input_hashes: dict[str, str] = {}
    for spec in sources:
        if not spec.csv_path.is_file():
            raise FileNotFoundError(spec.csv_path)
        rows, audit = normalize_source(spec, chunksize)
        all_rows.extend(rows)
        input_hashes[str(spec.csv_path)] = sha256_file(spec.csv_path)
        if spec.antigen_map_path:
            input_hashes[str(spec.antigen_map_path)] = sha256_file(spec.antigen_map_path)
        source_audits.append({**asdict(spec), "csv_path": str(spec.csv_path), "antigen_map_path": str(spec.antigen_map_path or ""), **audit})

    rows, duplicate_audit = deduplicate_rows(all_rows)
    rows, primary_overlap_filter = filter_primary_vhh_overlap(rows)
    split_audit = validate_split_policy(rows)
    rows.sort(key=lambda row: (str(row["split"]), str(row["formal_block"]), str(row["sample_id"])))
    train_dev = [row for row in rows if row["split"] in {"train", "dev"}]
    formal = [row for row in rows if row["split"] == "formal"]
    blinded = [{column: row[column] for column in MODEL_INPUT_COLUMNS} for row in formal]
    ensure_no_label_columns(blinded[0].keys() if blinded else [])
    labels = [
        {
            "sample_id": row["sample_id"],
            "formal_block": row["formal_block"],
            "label": row["label"],
            "sealed_status": "SEALED_LABELS",
        }
        for row in formal
    ]
    sequence_manifest = build_sequence_manifest(rows, deployment_sequences)

    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "binding_train_dev_v3.csv"
    blinded_path = output_dir / "binding_formal_blinded_v3.csv"
    labels_path = output_dir / "binding_formal_labels_sealed_v3.csv"
    sequences_path = output_dir / "sequence_manifest_v3.csv"
    write_csv_atomic(train_path, train_dev, TRAIN_COLUMNS + ["source_row_count"])
    write_csv_atomic(blinded_path, blinded, MODEL_INPUT_COLUMNS)
    write_csv_atomic(labels_path, labels, ["sample_id", "formal_block", "label", "sealed_status"])
    write_csv_atomic(sequences_path, sequence_manifest, ["sequence_sha256", "sequence", "sequence_length", "roles"])

    split_counts = Counter(str(row["split"]) for row in rows)
    block_counts = Counter(str(row["formal_block"]) for row in formal)
    label_counts = {
        split: dict(Counter(int(row["label"]) for row in rows if row["split"] == split))
        for split in ("train", "dev", "formal")
    }
    summary = {
        "schema_version": "phase2_v3_binding_prepare_summary_v1",
        "output_dir": str(output_dir),
        "source_audits": source_audits,
        "duplicate_audit": duplicate_audit,
        "primary_overlap_filter": primary_overlap_filter,
        "split_audit": split_audit,
        "row_counts": dict(split_counts),
        "formal_block_counts": dict(block_counts),
        "label_counts_by_split": label_counts,
        "unique_sequences": len(sequence_manifest),
        "deployment_sequence_audit": deployment_audit or {"status": "NOT_PROVIDED"},
        "input_sha256": input_hashes,
        "output_paths": {
            "train_dev": str(train_path),
            "formal_blinded": str(blinded_path),
            "formal_labels_sealed": str(labels_path),
            "sequence_manifest": str(sequences_path),
        },
    }
    summary["output_sha256"] = {name: sha256_file(Path(path)) for name, path in summary["output_paths"].items()}
    write_json_atomic(output_dir / "binding_prepare_audit_v3.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pvrig-panel", type=Path, default=DEFAULT_PVRIG_PANEL)
    parser.add_argument("--pvrig-construct", type=Path, default=DEFAULT_PVRIG_CONSTRUCT)
    parser.add_argument("--chunksize", type=int, default=100_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    deployment_sequences, deployment_audit = load_pvrig_deployment_sequences(args.pvrig_panel, args.pvrig_construct)
    summary = prepare(
        default_sources(args.dataset_root),
        args.output_dir,
        args.chunksize,
        deployment_sequences,
        deployment_audit,
    )
    print(json.dumps({"output_dir": summary["output_dir"], "row_counts": summary["row_counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
