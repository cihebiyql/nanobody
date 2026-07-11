#!/usr/bin/env python3
"""Prepare Phase 2 V2.5 generic-transfer NanoBind affinity records.

This script keeps NanoBind affinity rows in the generic real-assay lane only. It
normalizes Kd values into within-assay ordinal scores, creates deterministic
leakage-group splits, writes a blinded formal manifest plus separate sealed
labels, and builds frozen per-sequence embeddings for the shallow V2.5 ranker.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_INPUT = DATA_ROOT / "datasets" / "10_github_repos" / "NanoBind" / "data" / "affinity" / "all.csv"
DEFAULT_MODEL_PATH = DATA_ROOT / "datasets" / "10_github_repos" / "NanoBind" / "models" / "esm2_t6_8M_UR50D"
DEFAULT_OUTPUT_DIR = EXP_DIR / "prepared" / "phase2_v2_5_generic"
DEFAULT_P1_TRAIN = EXP_DIR / "data_splits" / "phase2_v2_5_train_manifest.csv"
DEFAULT_P1_DEV = EXP_DIR / "data_splits" / "phase2_v2_5_dev_manifest.csv"
DEFAULT_P1_FORMAL = EXP_DIR / "data_splits" / "phase2_v2_5_generic_formal_manifest_blinded.csv"
AA_PATTERN = re.compile(r"^[A-Z*.-]+$")
LABEL_COLUMNS = {"label_value", "label_unit", "label_direction", "affinity_kd_m", "affinity_score"}
RECORD_COLUMNS = [
    "sample_id",
    "vhh_sequence",
    "target_sequence",
    "vhh_sequence_length",
    "target_sequence_length",
    "sequence_sha256",
    "target_sequence_sha256",
    "target_id",
    "target_construct",
    "label_axis",
    "evidence_level",
    "ground_truth_kind",
    "label_value",
    "label_unit",
    "label_direction",
    "affinity_kd_m",
    "affinity_score",
    "assay_type",
    "assay_batch",
    "replicate_count",
    "source_id",
    "source_record_ids",
    "source_record_count",
    "source_path_or_locator",
    "allowed_use",
    "forbidden_use",
    "family_id",
    "leakage_group_id",
    "split_group_id",
    "ranking_group_id",
    "sealed_status",
    "dataset_version",
    "mutation",
    "reference_sample_id",
    "pose_id",
    "pose_qc_status",
    "missing_reason",
    "split",
    "real_assay_lane",
    "proxy_lane",
]


@dataclass(frozen=True)
class PrepareSummary:
    input_csv: str
    output_dir: str
    records_csv: str
    train_dev_records_csv: str
    formal_blinded_csv: str
    formal_labels_sealed_csv: str
    embeddings_pt: str
    embedding_manifest_json: str
    audit_json: str
    input_rows: int
    total_records: int
    duplicate_group_count: int
    split_component_count: int
    ranking_group_count: int
    train_records: int
    dev_records: int
    formal_records: int
    unique_sequences: int
    new_embeddings: int
    embedding_backend: str
    model_path: str
    model_sha256: str
    split_seed: int
    split_source: str
    formal_unseal_status: str = "SEALED"


def clean_sequence(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip().upper().replace(" ", "").replace("\n", "")
    if text.lower() in {"nan", "none", "na", "n/a"}:
        return ""
    if not AA_PATTERN.match(text):
        raise ValueError(f"Invalid amino-acid sequence: {text[:40]!r}")
    return text


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_sample_id(vhh_sha: str, target_sha: str) -> str:
    return "nanobind_affinity_" + sha256_text(f"{vhh_sha}|{target_sha}")[:20]


def parse_positive_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"Invalid {field}: {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{field} must be finite and positive: {value!r}")
    return parsed


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def apply_authoritative_split_assignments(
    rows: list[dict[str, Any]],
    train_path: Path,
    dev_path: Path,
    formal_path: Path,
) -> dict[str, Any]:
    assignments: dict[tuple[str, str], dict[str, str]] = {}
    source_counts: dict[str, int] = {}
    paths = {"train": train_path, "dev": dev_path, "formal": formal_path}
    for split, path in paths.items():
        frame = pd.read_csv(path)
        required = {"sample_id", "sequence_sha256", "target_sequence_sha256", "target_id", "evidence_level", "split_group_id"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Authoritative {split} manifest missing columns {sorted(missing)}: {path}")
        generic = frame[
            frame["evidence_level"].astype(str).str.upper().eq("E4")
            & frame["target_id"].astype(str).str.upper().str.startswith("NANOBIND_TARGET_SHA256_")
        ].copy()
        source_counts[split] = int(len(generic))
        for _, source in generic.iterrows():
            key = (str(source["sequence_sha256"]), str(source["target_sequence_sha256"]))
            assignment = {
                "split": split,
                "split_group_id": str(source["split_group_id"]),
                "authoritative_sample_id": str(source["sample_id"]),
            }
            previous = assignments.get(key)
            if previous and previous != assignment:
                raise ValueError(f"Conflicting authoritative split assignment for pair {key}: {previous} vs {assignment}")
            assignments[key] = assignment

    expected = {(str(row["sequence_sha256"]), str(row["target_sequence_sha256"])) for row in rows}
    observed = set(assignments)
    missing_pairs = sorted(expected - observed)
    extra_pairs = sorted(observed - expected)
    if missing_pairs or extra_pairs:
        raise ValueError(
            "Authoritative P1 split must map every canonical NanoBind pair exactly once; "
            f"missing={missing_pairs[:5]} extra={extra_pairs[:5]} counts={source_counts}"
        )

    for row in rows:
        key = (str(row["sequence_sha256"]), str(row["target_sequence_sha256"]))
        assignment = assignments[key]
        row["split"] = assignment["split"]
        row["split_group_id"] = assignment["split_group_id"]
        row["leakage_group_id"] = assignment["split_group_id"]
        row["sealed_status"] = "SEALED_LABELS" if assignment["split"] == "formal" else "OPEN_DEVELOPMENT"

    for column in ("sequence_sha256", "target_sequence_sha256", "split_group_id"):
        split_count = pd.DataFrame(rows).groupby(column)["split"].nunique()
        if int(split_count.max()) != 1:
            raise ValueError(f"Authoritative split import leaked {column} across splits")
    return {
        "mode": "AUTHORITATIVE_P1_REGISTRY_COMPONENTS",
        "manifest_paths": {split: str(path.resolve()) for split, path in paths.items()},
        "manifest_sha256": {split: file_sha256(path) for split, path in paths.items()},
        "imported_e4_counts": source_counts,
        "canonical_pair_count": len(assignments),
    }


def compute_model_sha256(model_path: Path) -> str:
    if not model_path.exists():
        return "missing:sha256_not_available"
    hasher = hashlib.sha256()
    files = [model_path] if model_path.is_file() else sorted(p for p in model_path.rglob("*") if p.is_file())
    for file_path in files:
        rel = file_path.name if model_path.is_file() else str(file_path.relative_to(model_path))
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def assign_connected_components(rows: list[dict[str, Any]]) -> None:
    """Keep every exact VHH or exact target relation inside one split component."""

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root

    for row in rows:
        union(f"vhh:{row['sequence_sha256']}", f"target:{row['target_sequence_sha256']}")

    component_nodes: dict[str, set[str]] = defaultdict(set)
    for node in sorted(parent):
        component_nodes[find(node)].add(node)
    component_ids = {
        root: "exact_vhh_target_component_" + sha256_text("|".join(sorted(nodes)))[:24]
        for root, nodes in component_nodes.items()
    }
    for row in rows:
        component_id = component_ids[find(f"vhh:{row['sequence_sha256']}")]
        row["leakage_group_id"] = component_id
        row["split_group_id"] = component_id
        row["ranking_group_id"] = "exact_target_" + str(row["target_sequence_sha256"])


def normalize_records_with_audit(
    input_csv: Path,
    dataset_version: str,
    split_seed: int,
    formal_fraction: float,
    dev_fraction: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(input_csv)
    required = {"ID", "nanobody_chain", "seq_nanobody", "antigen_chain", "seq_antigen", "affinity"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"NanoBind affinity CSV missing columns: {sorted(missing)}")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for source_row_number, raw in enumerate(frame.to_dict("records"), start=2):
        vhh = clean_sequence(raw["seq_nanobody"])
        antigen = clean_sequence(raw["seq_antigen"])
        if not vhh or not antigen:
            raise ValueError(f"Missing normalized sequence at source CSV row {source_row_number}")
        kd_m = parse_positive_float(raw["affinity"], "affinity")
        vhh_sha = sha256_text(vhh)
        target_sha = sha256_text(antigen)
        grouped[(vhh_sha, target_sha)].append(
            {
                "raw": raw,
                "source_row_number": source_row_number,
                "vhh_sequence": vhh,
                "target_sequence": antigen,
                "affinity_kd_m": kd_m,
            }
        )

    rows: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    for (vhh_sha, target_sha), members in sorted(grouped.items()):
        vhh = str(members[0]["vhh_sequence"])
        antigen = str(members[0]["target_sequence"])
        kd_values = [float(member["affinity_kd_m"]) for member in members]
        kd_m = float(statistics.median(kd_values))
        sample_id = stable_sample_id(vhh_sha, target_sha)
        target_id = "nanobind_target_" + target_sha[:16]
        source_record_ids = sorted({str(member["raw"].get("ID", "")).strip() for member in members})
        constructs = sorted(
            {
                f"entry:{member['raw'].get('ID', '')}|antigen_chain:{member['raw'].get('antigen_chain', '')}"
                for member in members
            }
        )
        rows.append(
            {
                "sample_id": sample_id,
                "vhh_sequence": vhh,
                "target_sequence": antigen,
                "vhh_sequence_length": len(vhh),
                "target_sequence_length": len(antigen),
                "sequence_sha256": vhh_sha,
                "target_sequence_sha256": target_sha,
                "target_id": target_id,
                "target_construct": ";".join(constructs),
                "label_axis": "binding",
                "evidence_level": "E4",
                "ground_truth_kind": "real_assay_binding_kd",
                "label_value": f"{kd_m:.12g}",
                "label_unit": "M",
                "label_direction": "lower_is_better",
                "affinity_kd_m": f"{kd_m:.12g}",
                "affinity_score": f"{-math.log10(kd_m):.9f}",
                "assay_type": "affinity_kd",
                "assay_batch": "nanobind_affinity_all_csv",
                "replicate_count": "",
                "source_id": "NanoBind_affinity_all",
                "source_record_ids": ";".join(source_record_ids),
                "source_record_count": len(members),
                "source_path_or_locator": str(input_csv),
                "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                "forbidden_use": "blocker_truth;verified_nonbinder;ordinary_bce_negative;proxy_truth;target_pvrig_claim",
                "family_id": "target_family_" + target_sha[:16],
                "leakage_group_id": "",
                "split_group_id": "",
                "ranking_group_id": "exact_target_" + target_sha,
                "sealed_status": "OPEN_DEVELOPMENT",
                "dataset_version": dataset_version,
                "mutation": "",
                "reference_sample_id": "",
                "pose_id": "",
                "pose_qc_status": "",
                "missing_reason": (
                    "replicate_count:HISTORICAL_REPLICATE_COUNT_NOT_REPORTED;"
                    "mutation:NOT_APPLICABLE_BINDING_KD;reference_sample_id:NOT_APPLICABLE_BINDING_KD;"
                    "pose_id:NOT_APPLICABLE_NON_POSE_ROW;pose_qc_status:NOT_APPLICABLE_NON_POSE_ROW"
                ),
                "real_assay_lane": "yes",
                "proxy_lane": "no",
            }
        )
        if len(members) > 1:
            duplicate_groups.append(
                {
                    "canonical_sample_id": sample_id,
                    "sequence_sha256": vhh_sha,
                    "target_sequence_sha256": target_sha,
                    "source_record_ids": source_record_ids,
                    "source_row_numbers": sorted(int(member["source_row_number"]) for member in members),
                    "source_record_count": len(members),
                    "affinity_kd_m_values": sorted(kd_values),
                    "median_affinity_kd_m": kd_m,
                }
            )
    assign_connected_components(rows)
    assign_splits(rows, split_seed=split_seed, formal_fraction=formal_fraction, dev_fraction=dev_fraction)
    rows = sorted(rows, key=lambda item: item["sample_id"])
    audit = {
        "policy": "aggregate_exact_normalized_vhh_target_pair_with_median_kd",
        "input_row_count": int(len(frame)),
        "canonical_record_count": len(rows),
        "exact_pair_duplicate_group_count": len(duplicate_groups),
        "duplicate_input_row_count": sum(group["source_record_count"] for group in duplicate_groups),
        "merged_excess_row_count": int(len(frame) - len(rows)),
        "duplicate_groups": duplicate_groups,
    }
    return rows, audit


def normalize_records(input_csv: Path, dataset_version: str, split_seed: int, formal_fraction: float, dev_fraction: float) -> list[dict[str, Any]]:
    rows, _ = normalize_records_with_audit(input_csv, dataset_version, split_seed, formal_fraction, dev_fraction)
    return rows


def assign_splits(rows: list[dict[str, Any]], split_seed: int, formal_fraction: float, dev_fraction: float) -> None:
    if not 0.0 <= formal_fraction < 1.0 or not 0.0 <= dev_fraction < 1.0 or formal_fraction + dev_fraction >= 1.0:
        raise ValueError("Split fractions must be non-negative and leave train rows")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["split_group_id"], []).append(row)
    keys = sorted(groups)
    rng = random.Random(split_seed)
    rng.shuffle(keys)
    total = len(rows)
    formal_target = max(1, round(total * formal_fraction)) if formal_fraction > 0 else 0
    dev_target = max(1, round(total * dev_fraction)) if dev_fraction > 0 else 0
    counts = {"train": 0, "dev": 0, "formal": 0}
    for key in keys:
        size = len(groups[key])
        if counts["formal"] < formal_target:
            split = "formal"
        elif counts["dev"] < dev_target:
            split = "dev"
        else:
            split = "train"
        for row in groups[key]:
            row["split"] = split
            if split == "formal":
                row["sealed_status"] = "SEALED_LABELS"
        counts[split] += size
    if counts["train"] == 0 or counts["dev"] == 0:
        raise ValueError(f"Split assignment left required train/dev empty: {counts}")


def write_csv_atomic(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def hash_embedding(sequence: str, dim: int) -> torch.Tensor:
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(f"{sequence}|{counter}".encode("utf-8")).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) == dim:
                break
        counter += 1
    tensor = torch.tensor(values, dtype=torch.float32)
    return tensor / tensor.norm().clamp_min(1e-6)


def load_local_esm2(model_path: Path) -> tuple[Any, Any]:
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModel.from_pretrained(str(model_path), local_files_only=True)
    model.eval()
    return tokenizer, model


def esm2_mean_embeddings(sequences: Sequence[str], model_path: Path, device: torch.device, batch_size: int, max_residues: int) -> dict[str, torch.Tensor]:
    tokenizer, model = load_local_esm2(model_path)
    model.to(device)
    output: dict[str, torch.Tensor] = {}
    for start in range(0, len(sequences), batch_size):
        batch = list(sequences[start : start + batch_size])
        truncated = [sequence[:max_residues] for sequence in batch]
        encoded = tokenizer(truncated, return_tensors="pt", padding=True, truncation=False, return_special_tokens_mask=True)
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode():
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                hidden = model(input_ids=encoded["input_ids"], attention_mask=encoded.get("attention_mask")).last_hidden_state
        attention = encoded.get("attention_mask", torch.ones_like(encoded["input_ids"]))
        special = encoded["special_tokens_mask"]
        for index, sequence in enumerate(batch):
            residue_mask = (attention[index] == 1) & (special[index] == 0)
            pooled = hidden[index][residue_mask].float().mean(0).detach().cpu()
            output[sha256_text(sequence)] = pooled.contiguous()
    return output


def build_embeddings(
    rows: Sequence[dict[str, Any]],
    output_dir: Path,
    model_path: Path,
    backend: str,
    device_name: str,
    batch_size: int,
    max_residues: int,
    hash_dim: int,
) -> tuple[Path, Path, int, str]:
    sequences = sorted({row["vhh_sequence"] for row in rows} | {row["target_sequence"] for row in rows}, key=lambda s: (len(s), sha256_text(s)))
    model_sha = compute_model_sha256(model_path) if backend == "esm2" else f"hash_backend_dim_{hash_dim}"
    embeddings_path = output_dir / "frozen_sequence_embeddings.pt"
    manifest_path = output_dir / "embedding_manifest.json"
    existing: dict[str, torch.Tensor] = {}
    existing_meta: dict[str, Any] = {}
    if embeddings_path.exists() and manifest_path.exists():
        existing_meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing_meta.get("backend") == backend
            and existing_meta.get("model_sha256") == model_sha
            and int(existing_meta.get("max_residues", -1)) == max_residues
        ):
            existing = torch.load(embeddings_path, map_location="cpu", weights_only=False)
    missing = [sequence for sequence in sequences if sha256_text(sequence) not in existing]
    if missing:
        if backend == "hash":
            new = {sha256_text(sequence): hash_embedding(sequence, hash_dim) for sequence in missing}
        elif backend == "esm2":
            if device_name == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA was requested for ESM2 embedding but is not available")
            new = esm2_mean_embeddings(missing, model_path, torch.device(device_name), batch_size, max_residues)
        else:
            raise ValueError(f"Unknown embedding backend: {backend}")
        existing.update(new)
    torch.save({key: existing[key].detach().cpu().to(torch.float32).contiguous() for key in sorted(existing)}, embeddings_path)
    dims = sorted({int(tensor.numel()) for tensor in existing.values()})
    manifest = {
        "schema_version": "phase2_v2_5_generic_embeddings_v1",
        "backend": backend,
        "model_path": str(model_path),
        "model_sha256": model_sha,
        "embedding_dim": dims[0] if len(dims) == 1 else None,
        "embedding_dims_seen": dims,
        "sequence_count": len(existing),
        "required_sequence_count": len(sequences),
        "new_embeddings": len(missing),
        "max_residues": max_residues,
        "sequence_truncation_policy": "PREFIX_MAX_RESIDUES",
        "truncated_sequence_count": sum(len(sequence) > max_residues for sequence in sequences),
        "frozen": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return embeddings_path, manifest_path, len(missing), model_sha


def write_prepared_outputs(
    rows: list[dict[str, Any]],
    output_dir: Path,
    input_csv: Path,
    duplicate_audit: dict[str, Any],
    split_provenance: dict[str, Any],
) -> tuple[Path, Path, Path, Path, Path]:
    records_csv = output_dir / "nanobind_affinity_records_v2_5.csv"
    train_dev_csv = output_dir / "nanobind_affinity_train_dev_v2_5.csv"
    formal_blinded_csv = output_dir / "nanobind_affinity_formal_blinded_v2_5.csv"
    formal_labels_csv = output_dir / "nanobind_affinity_formal_labels_sealed_v2_5.csv"
    audit_json = output_dir / "nanobind_affinity_prepare_audit_v2_5.json"
    train_dev = [row for row in rows if row["split"] in {"train", "dev"}]
    formal = [row for row in rows if row["split"] == "formal"]
    public_records = []
    for row in rows:
        public_row = dict(row)
        if row["split"] == "formal":
            for column in LABEL_COLUMNS:
                public_row[column] = ""
        public_records.append(public_row)
    write_csv_atomic(records_csv, public_records, RECORD_COLUMNS)
    write_csv_atomic(train_dev_csv, train_dev, RECORD_COLUMNS)
    blinded_columns = [column for column in RECORD_COLUMNS if column not in LABEL_COLUMNS]
    write_csv_atomic(formal_blinded_csv, formal, blinded_columns)
    label_columns = [
        "sample_id",
        "label_value",
        "label_unit",
        "label_direction",
        "affinity_kd_m",
        "affinity_score",
        "sealed_status",
        "dataset_version",
    ]
    write_csv_atomic(formal_labels_csv, formal, label_columns)
    component_targets: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        component_targets[str(row["split_group_id"])].add(str(row["ranking_group_id"]))

    def cross_split_overlap_count(column: str) -> int:
        split_sets: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            split_sets[str(row[column])].add(str(row["split"]))
        return sum(len(splits) > 1 for splits in split_sets.values())

    counts = {
        "schema_version": "phase2_v2_5_generic_prepare_audit_v2",
        "input_csv": str(input_csv),
        "input_rows": duplicate_audit["input_row_count"],
        "records_total": len(rows),
        "duplicate_audit": duplicate_audit,
        "split_provenance": split_provenance,
        "split_counts": {split: sum(row["split"] == split for row in rows) for split in ("train", "dev", "formal")},
        "split_component_count": len(component_targets),
        "ranking_group_count": len({row["ranking_group_id"] for row in rows}),
        "cross_target_split_component_count": sum(len(targets) > 1 for targets in component_targets.values()),
        "split_overlap_audit": {
            "exact_vhh_cross_split_count": cross_split_overlap_count("sequence_sha256"),
            "exact_target_cross_split_count": cross_split_overlap_count("target_sequence_sha256"),
            "split_group_cross_split_count": cross_split_overlap_count("split_group_id"),
            "ranking_group_cross_split_count": cross_split_overlap_count("ranking_group_id"),
        },
        "evidence_level_counts": {str(key): int(value) for key, value in pd.Series([row["evidence_level"] for row in rows]).value_counts().sort_index().items()},
        "real_assay_rows": sum(row["real_assay_lane"] == "yes" for row in rows),
        "proxy_rows": sum(row["proxy_lane"] == "yes" for row in rows),
        "formal_labels_sealed_path": str(formal_labels_csv),
        "formal_blinded_exposes_label_columns": bool(set(blinded_columns) & LABEL_COLUMNS),
        "formal_blinded_retained_model_inputs": [
            "vhh_sequence",
            "target_sequence",
            "vhh_sequence_length",
            "target_sequence_length",
            "sequence_sha256",
            "target_sequence_sha256",
            "ranking_group_id",
        ],
        "records_csv_formal_labels_exposed": any(
            row["split"] == "formal" and any(str(public_row.get(column, "")).strip() for column in LABEL_COLUMNS)
            for row, public_row in zip(rows, public_records)
        ),
        "lane_policy": {
            "constructed_proxy_as_verified_nonbinder_allowed": False,
            "pose_proxy_as_experimental_label_allowed": False,
            "nanobind_affinity_allowed_for_pvrig_blocker_truth": False,
        },
    }
    audit_json.write_text(json.dumps(counts, indent=2, sort_keys=True), encoding="utf-8")
    return records_csv, train_dev_csv, formal_blinded_csv, formal_labels_csv, audit_json


def prepare(args: argparse.Namespace) -> PrepareSummary:
    output_dir = args.output_dir.resolve()
    rows, duplicate_audit = normalize_records_with_audit(
        args.input_csv.resolve(), args.dataset_version, args.split_seed, args.formal_fraction, args.dev_fraction
    )
    split_mode = getattr(args, "authoritative_split_mode", "internal")
    split_paths = (
        Path(getattr(args, "p1_train_manifest", DEFAULT_P1_TRAIN)),
        Path(getattr(args, "p1_dev_manifest", DEFAULT_P1_DEV)),
        Path(getattr(args, "p1_formal_manifest", DEFAULT_P1_FORMAL)),
    )
    manifests_present = all(path.exists() and path.stat().st_size > 0 for path in split_paths)
    if split_mode == "required" and not manifests_present:
        raise FileNotFoundError(f"Authoritative P1 split manifests are required but missing: {[str(path) for path in split_paths]}")
    if split_mode in {"auto", "required"} and manifests_present:
        split_provenance = apply_authoritative_split_assignments(rows, *split_paths)
    else:
        split_provenance = {
            "mode": "INTERNAL_NANOBIND_ONLY_COMPONENTS",
            "reason": "explicit internal mode" if split_mode == "internal" else "authoritative P1 manifests unavailable",
            "split_counts": {split: sum(row["split"] == split for row in rows) for split in ("train", "dev", "formal")},
        }
    records_csv, train_dev_csv, formal_blinded_csv, formal_labels_csv, audit_json = write_prepared_outputs(
        rows, output_dir, args.input_csv.resolve(), duplicate_audit, split_provenance
    )
    embeddings_pt, embedding_manifest, new_embeddings, model_sha = build_embeddings(
        rows=rows,
        output_dir=output_dir,
        model_path=args.model_path.resolve(),
        backend=args.embedding_backend,
        device_name=args.device,
        batch_size=args.batch_size,
        max_residues=args.max_residues,
        hash_dim=args.hash_dim,
    )
    summary = PrepareSummary(
        input_csv=str(args.input_csv.resolve()),
        output_dir=str(output_dir),
        records_csv=str(records_csv),
        train_dev_records_csv=str(train_dev_csv),
        formal_blinded_csv=str(formal_blinded_csv),
        formal_labels_sealed_csv=str(formal_labels_csv),
        embeddings_pt=str(embeddings_pt),
        embedding_manifest_json=str(embedding_manifest),
        audit_json=str(audit_json),
        input_rows=duplicate_audit["input_row_count"],
        total_records=len(rows),
        duplicate_group_count=duplicate_audit["exact_pair_duplicate_group_count"],
        split_component_count=len({row["split_group_id"] for row in rows}),
        ranking_group_count=len({row["ranking_group_id"] for row in rows}),
        train_records=sum(row["split"] == "train" for row in rows),
        dev_records=sum(row["split"] == "dev" for row in rows),
        formal_records=sum(row["split"] == "formal" for row in rows),
        unique_sequences=len({row["sequence_sha256"] for row in rows} | {row["target_sequence_sha256"] for row in rows}),
        new_embeddings=new_embeddings,
        embedding_backend=args.embedding_backend,
        model_path=str(args.model_path.resolve()),
        model_sha256=model_sha,
        split_seed=args.split_seed,
        split_source=split_provenance["mode"],
    )
    (output_dir / "prepare_summary_v2_5.json").write_text(json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dataset-version", default="NanoBind_affinity_all_v2_5_generic_20260711")
    parser.add_argument("--split-seed", type=int, default=43)
    parser.add_argument("--formal-fraction", type=float, default=0.20)
    parser.add_argument("--dev-fraction", type=float, default=0.20)
    parser.add_argument("--embedding-backend", choices=("esm2", "hash"), default="esm2")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-residues", type=int, default=1024)
    parser.add_argument("--hash-dim", type=int, default=64, help="Test-only deterministic embedding dimension for --embedding-backend hash")
    parser.add_argument("--authoritative-split-mode", choices=("auto", "required", "internal"), default="auto")
    parser.add_argument("--p1-train-manifest", type=Path, default=DEFAULT_P1_TRAIN)
    parser.add_argument("--p1-dev-manifest", type=Path, default=DEFAULT_P1_DEV)
    parser.add_argument("--p1-formal-manifest", type=Path, default=DEFAULT_P1_FORMAL)
    return parser.parse_args()


def main() -> None:
    summary = prepare(parse_args())
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
