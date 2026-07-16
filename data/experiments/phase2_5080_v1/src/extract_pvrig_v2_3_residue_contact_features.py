#!/usr/bin/env python3
"""Extract label-free V2.3 residue/contact features for PVRIG candidates.

Only sequence-side artifacts are accepted: candidate sequences, exact CDR
masks, a frozen ESM2 residue cache, frozen V2.3 checkpoints, the fixed PVRIG
target sequence, and the fixed PVRIG interface hotspot table.  V4-D job state,
raw docking results, teacher tables, and geometry labels are neither accepted
as arguments nor discovered by this runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import tempfile
from collections import Counter
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import torch
from torch.nn.utils.rnn import pad_sequence

from score_pvrig_candidates_v2_3 import load_model_from_checkpoint
from train_phase2_v2_3 import CDRMaskStore, Config, ESM2Cache, clean, seq_hash


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_CANDIDATES = EXP_DIR / "prepared/pvrig_v4_d/residue_features/candidate7087_v23_inputs.csv"
DEFAULT_MASKS = EXP_DIR / "prepared/pvrig_v4_d/residue_features/vhh_cdr_type_masks_v23_candidate7087.csv"
DEFAULT_CACHE = EXP_DIR / "prepared/pvrig_v4_d/residue_features/esm2_8m_residue_cache_v1/manifest.csv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_HOTSPOTS = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_CHECKPOINTS = tuple(
    EXP_DIR / f"checkpoints/phase2_v2_3_strict_seed{seed}_best_checkpoint.pt"
    for seed in (43, 53, 67)
)
DEFAULT_OUTPUT = EXP_DIR / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv"
DEFAULT_SUPERSEDED_OUTPUTS = (
    EXP_DIR / "predictions/pvrig_candidate_v2_3_residue_contact_features_v1.csv",
    EXP_DIR / "predictions/pvrig_candidate_v2_3_residue_contact_features_v2.csv",
)

SCHEMA_VERSION = "pvrig_candidate_v2_3_label_free_residue_contact_features_v3"
AUDIT_SCHEMA_VERSION = "pvrig_candidate_v2_3_label_free_residue_contact_feature_audit_v3"
RECEIPT_SCHEMA_VERSION = "pvrig_candidate_v2_3_label_free_residue_contact_release_receipt_v1"
VERIFICATION_SCHEMA_VERSION = "pvrig_candidate_v2_3_label_free_residue_contact_release_verification_v1"
ADAPTER_SCHEMA_VERSION = "pvrig_candidate7087_v23_label_free_input_adapter_v1"
SUPERSEDED_SCHEMA_VERSIONS = (
    "pvrig_candidate_v2_3_label_free_residue_contact_features_v1",
    "pvrig_candidate_v2_3_label_free_residue_contact_features_v2",
)
CLAIM_BOUNDARY = (
    "generic V2.3 sequence-to-fixed-PVRIG residue/contact AI prior only; "
    "not docking geometry, binding, affinity, competition, or functional blocking truth"
)
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
PROVENANCE_FIELDS = (
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
)
ADAPTER_REQUIRED_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "vhh_seq",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr1_span_0based",
    "cdr2_span_0based",
    "cdr3_span_0based",
    *PROVENANCE_FIELDS,
)
ARCHITECTURE_FIELDS = (
    "d_model",
    "esm_dim",
    "contact_dim",
    "layers",
    "cross_layers",
    "heads",
    "dropout",
    "max_vhh_len",
    "max_antigen_len",
)
FEATURE_NAMES = (
    "pair_ranking_logit_weak",
    "pair_ranking_sigmoid_weak",
    "paratope_mean",
    "paratope_cdr_mean",
    "paratope_cdr3_mean",
    "paratope_cdr3_max",
    "paratope_cdr_mass_fraction",
    "contact_global_mean",
    "contact_global_top20_mean",
    "contact_hotspot_weighted_mean",
    "contact_hotspot_top20_mean",
    "contact_hotspot_fraction",
    "contact_cdr_hotspot_weighted_mean",
    "contact_cdr_hotspot_mass_length_confounded_diagnostic",
    "contact_cdr3_hotspot_weighted_mean",
    "contact_cdr3_hotspot_top20_mean",
    "contact_cdr3_hotspot_mass_length_confounded_diagnostic",
    "contact_noninterface_mean",
    "contact_interface_specificity",
    "epitope_hotspot_weighted_mean",
    "epitope_noninterface_mean",
    "epitope_interface_specificity",
)
DIAGNOSTIC_ONLY_FEATURES = (
    "contact_cdr_hotspot_mass_length_confounded_diagnostic",
    "contact_cdr3_hotspot_mass_length_confounded_diagnostic",
)
STABLE_FEATURE_NAMES = tuple(feature for feature in FEATURE_NAMES if feature not in DIAGNOSTIC_ONLY_FEATURES)
LENGTH_ONLY_BASELINE_FIELDS = ("sequence_length", "cdr1_length", "cdr2_length", "cdr3_length")
PRODUCTION_EXPECTED_HASHES = {
    "candidates": "3099d49f150ef21a97822fc4e0d2cc2c9bc3580654a4de2e46f1768ea3e6e222",
    "cache_manifest": "1300b7f1c32a917e0b95831c54bb483663b1fe59024982412440dfe51444aa40",
    "cdr_masks": "5b6b8c2749ea25335a232d1c61dcf56b4fba8c046892493775e047a4bc34c29f",
    "target_fasta": "4113f40833627aaede888e5ee9e9e1a99bdceced4f856fa08e02bc666da15c50",
    "hotspots": "9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd",
}
PRODUCTION_EXPECTED_CHECKPOINT_HASHES = {
    43: "27d2c3c9c89a0e4fd3d725cc64e433933aa1717ae19e7246b599ef8931db7c97",
    53: "2876155dffdedf0d4bee41daddd25a1c9e67aeba1101950fe508e2fd4df3260b",
    67: "f717a68056b2569d5a5d4b59fd49e08ee659b33f7dacc23e21cc737b3030cfe9",
}
FORBIDDEN_EXACT_COLUMNS = {
    "model_split",
    "r_8x6b",
    "r_9e6y",
    "r_dual",
    "r_dual_min",
    "r_dual_gap",
    "geometry_tier",
    "consensus_geometry_tier",
    "hotspot_overlap",
    "total_occlusion",
    "cdr3_occlusion",
    "support_fraction",
    "supporting_pose_count",
}
FORBIDDEN_COLUMN_TOKENS = (
    "docking_label",
    "docking_score",
    "haddock_score",
    "teacher_label",
    "teacher_score",
    "pose_result",
    "blocker_probability",
)


class FeatureExtractionError(RuntimeError):
    """Raised when label-free input closure or inference fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_csv(path: Path, delimiter: str | None = None) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise FeatureExtractionError(f"missing input table: {path}")
    chosen = delimiter or ("\t" if path.suffix.lower() == ".tsv" else ",")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=chosen)
        fieldnames = list(reader.fieldnames or [])
        return list(reader), fieldnames


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def snapshot_files(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for label, path in sorted(paths.items()):
        resolved = path.resolve()
        if not resolved.is_file():
            raise FeatureExtractionError(f"snapshot input missing: {label}={resolved}")
        stat = resolved.stat()
        snapshot[label] = {
            "path": str(resolved),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(resolved),
        }
    return snapshot


def snapshot_content_closure(snapshot: dict[str, dict[str, Any]]) -> str:
    return sha256_json(
        {
            label: {
                "path": row["path"],
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
            }
            for label, row in sorted(snapshot.items())
        }
    )


def compare_snapshots(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    changed: dict[str, dict[str, Any]] = {}
    for label in sorted(set(before) | set(after)):
        left = before.get(label)
        right = after.get(label)
        if left is None or right is None or (
            left["path"], left["size_bytes"], left["sha256"]
        ) != (
            right["path"], right["size_bytes"], right["sha256"]
        ):
            changed[label] = {"before": left, "after": right}
    return changed


def output_schema_version(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if "schema_version" not in (reader.fieldnames or []):
            raise FeatureExtractionError(f"existing output lacks schema_version: {path}")
        first = next(reader, None)
    if first is None:
        raise FeatureExtractionError(f"existing output is empty: {path}")
    return first["schema_version"]


def quarantine_superseded_release(
    paths: Sequence[Path], output_path: Path, quarantine_root: Path | None = None
) -> dict[str, Any]:
    schema = output_schema_version(output_path)
    if not schema:
        return {"status": "NOT_NEEDED", "moved": []}
    if schema not in SUPERSEDED_SCHEMA_VERSIONS:
        raise FeatureExtractionError(
            f"refusing to replace existing non-superseded output schema {schema}: {output_path}"
        )
    digest = sha256_file(output_path)[:12]
    root = quarantine_root or output_path.parent / "quarantine"
    destination = root / f"{output_path.stem}__{schema}__{digest}"
    if destination.exists():
        raise FeatureExtractionError(f"superseded release quarantine already exists: {destination}")
    destination.mkdir(parents=True)
    moved: list[dict[str, str]] = []
    for path in paths:
        if path.is_file():
            target = destination / path.name
            shutil.move(str(path), str(target))
            moved.append({"source": str(path.resolve()), "quarantined": str(target.resolve())})
    return {
        "status": "QUARANTINED_SUPERSEDED_RELEASE",
        "superseded_schema": schema,
        "destination": str(destination.resolve()),
        "moved": moved,
    }


def read_fasta(path: Path) -> str:
    if not path.is_file():
        raise FeatureExtractionError(f"missing target FASTA: {path}")
    sequence = "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )
    if not sequence or not AA_RE.fullmatch(sequence):
        raise FeatureExtractionError(f"target FASTA is empty or contains noncanonical residues: {path}")
    return sequence


def forbidden_candidate_columns(fieldnames: Sequence[str]) -> list[str]:
    bad: list[str] = []
    for field in fieldnames:
        lowered = field.strip().lower()
        if lowered in FORBIDDEN_EXACT_COLUMNS or any(token in lowered for token in FORBIDDEN_COLUMN_TOKENS):
            bad.append(field)
    return sorted(set(bad))


def parse_zero_based_span(value: str, sequence_length: int, label: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)-(\d+)", value.strip())
    if not match:
        raise FeatureExtractionError(f"invalid 0-based half-open span for {label}: {value!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if not 0 <= start < end <= sequence_length:
        raise FeatureExtractionError(f"out-of-bounds 0-based half-open span for {label}: {start}-{end}")
    return start, end


def load_candidates(path: Path, expected_count: int | None) -> tuple[list[dict[str, str]], list[str]]:
    rows, fieldnames = read_csv(path)
    if tuple(fieldnames) != ADAPTER_REQUIRED_FIELDS:
        missing = sorted(set(ADAPTER_REQUIRED_FIELDS) - set(fieldnames))
        extra = sorted(set(fieldnames) - set(ADAPTER_REQUIRED_FIELDS))
        raise FeatureExtractionError(
            "candidate adapter schema mismatch; "
            f"missing={missing} extra={extra} expected_order={list(ADAPTER_REQUIRED_FIELDS)}"
        )
    if expected_count is not None and len(rows) != expected_count:
        raise FeatureExtractionError(f"expected {expected_count} candidates, found {len(rows)}")
    candidates: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for source in rows:
        candidate_id = source["candidate_id"].strip()
        sequence = source["vhh_seq"].strip().upper()
        digest = seq_hash(sequence)
        if not candidate_id or candidate_id in seen_ids:
            raise FeatureExtractionError(f"empty or duplicate candidate_id: {candidate_id!r}")
        if not AA_RE.fullmatch(sequence):
            raise FeatureExtractionError(f"noncanonical candidate sequence: {candidate_id}")
        if source["sequence_sha256"].strip().lower() != digest:
            raise FeatureExtractionError(f"candidate sequence hash mismatch: {candidate_id}")
        if digest in seen_hashes:
            raise FeatureExtractionError(f"candidate sequences are not exact-unique: {candidate_id}")
        seen_ids.add(candidate_id)
        seen_hashes.add(digest)
        spans: list[tuple[int, int]] = []
        cdr_values: dict[str, str] = {}
        for name in ("cdr1", "cdr2", "cdr3"):
            cdr = source[name].strip().upper()
            start, end = parse_zero_based_span(
                source[f"{name}_span_0based"], len(sequence), f"{candidate_id}:{name}"
            )
            if sequence[start:end] != cdr:
                raise FeatureExtractionError(
                    f"candidate adapter CDR subsequence mismatch: {candidate_id}:{name}"
                )
            spans.append((start, end))
            cdr_values[name] = cdr
        if not (spans[0][1] <= spans[1][0] and spans[1][1] <= spans[2][0]):
            raise FeatureExtractionError(f"candidate adapter CDR spans overlap: {candidate_id}")
        row = {
            "candidate_id": candidate_id,
            "vhh_seq": sequence,
            "sequence_sha256": digest,
            **cdr_values,
            **{
                f"{name}_span_0based": source[f"{name}_span_0based"].strip()
                for name in ("cdr1", "cdr2", "cdr3")
            },
            **{field: source.get(field, "").strip() for field in PROVENANCE_FIELDS},
        }
        candidates.append(row)
    return sorted(candidates, key=lambda row: row["candidate_id"]), fieldnames


def verify_cdr(source: dict[str, str], name: str) -> tuple[int, int, str]:
    sequence = source["vhh_sequence"].strip().upper()
    cdr = source[f"{name}_after"].strip().upper()
    start = int(source[f"{name}_start_1based"])
    end = int(source[f"{name}_end_1based"])
    if not (1 <= start <= end <= len(sequence)) or sequence[start - 1 : end] != cdr:
        raise FeatureExtractionError(
            f"{source.get('candidate_id')} {name} sequence/span mismatch: {start}-{end} {cdr}"
        )
    return start - 1, end, cdr


def prepare_label_free_inputs(
    source_path: Path,
    adapter_output: Path,
    mask_output: Path,
    receipt_output: Path,
    expected_count: int = 7087,
) -> dict[str, Any]:
    source_rows, fieldnames = read_csv(source_path)
    required = {
        "candidate_id", "vhh_sequence", "sequence_sha256", "sequence_length",
        "cdr1_after", "cdr2_after", "cdr3_after",
        "cdr1_start_1based", "cdr1_end_1based", "cdr2_start_1based", "cdr2_end_1based",
        "cdr3_start_1based", "cdr3_end_1based",
    }
    missing = required - set(fieldnames)
    if missing:
        raise FeatureExtractionError(f"source candidates lack exact adapter fields: {sorted(missing)}")
    forbidden = forbidden_candidate_columns(fieldnames)
    if forbidden:
        raise FeatureExtractionError(f"source candidates contain forbidden docking/teacher fields: {forbidden}")
    if len(source_rows) != expected_count:
        raise FeatureExtractionError(f"expected {expected_count} source candidates, found {len(source_rows)}")
    adapter_rows: list[dict[str, str]] = []
    mask_rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for source in source_rows:
        candidate_id = source["candidate_id"].strip()
        sequence = source["vhh_sequence"].strip().upper()
        digest = seq_hash(sequence)
        if candidate_id in seen_ids or digest in seen_hashes:
            raise FeatureExtractionError(f"adapter source is not candidate/sequence unique: {candidate_id}")
        if source["sequence_sha256"].strip().lower() != digest or int(source["sequence_length"]) != len(sequence):
            raise FeatureExtractionError(f"adapter source sequence identity mismatch: {candidate_id}")
        spans: dict[str, list[int]] = {}
        cdrs: dict[str, str] = {}
        mask = [0] * len(sequence)
        for cdr_type, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
            start, end, cdr = verify_cdr(source, name)
            spans[name] = [start, end]
            cdrs[name] = cdr
            mask[start:end] = [cdr_type] * (end - start)
        if not (spans["cdr1"][1] <= spans["cdr2"][0] and spans["cdr2"][1] <= spans["cdr3"][0]):
            raise FeatureExtractionError(f"overlapping CDR spans: {candidate_id}")
        adapter_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "vhh_seq": sequence,
                "cdr1": cdrs["cdr1"],
                "cdr2": cdrs["cdr2"],
                "cdr3": cdrs["cdr3"],
                "cdr1_span_0based": f"{spans['cdr1'][0]}-{spans['cdr1'][1]}",
                "cdr2_span_0based": f"{spans['cdr2'][0]}-{spans['cdr2'][1]}",
                "cdr3_span_0based": f"{spans['cdr3'][0]}-{spans['cdr3'][1]}",
                **{field: source.get(field, "").strip() for field in PROVENANCE_FIELDS},
            }
        )
        mask_rows.append(
            {
                "sequence_hash": digest,
                "vhh_seq": sequence,
                "vhh_len": str(len(sequence)),
                "cdr_mask_json": json.dumps(mask, separators=(",", ":")),
                "spans_json": json.dumps(spans, separators=(",", ":"), sort_keys=True),
                "cdr1_seq": cdrs["cdr1"],
                "cdr2_seq": cdrs["cdr2"],
                "cdr3_seq": cdrs["cdr3"],
                "annotation_source": ADAPTER_SCHEMA_VERSION,
                "status": "exact_annotation",
                "fallback_reason": "",
                "manifest_sources_json": '["pvrig_candidate_adapter"]',
            }
        )
        seen_ids.add(candidate_id)
        seen_hashes.add(digest)
    adapter_rows.sort(key=lambda row: row["candidate_id"])
    mask_rows.sort(key=lambda row: row["sequence_hash"])
    atomic_write_csv(adapter_output, adapter_rows, list(adapter_rows[0]))
    atomic_write_csv(mask_output, mask_rows, list(mask_rows[0]))
    receipt = {
        "status": "PASS",
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "candidate_count": len(adapter_rows),
        "exact_mask_count": len(mask_rows),
        "input_sha256": sha256_file(source_path),
        "adapter_output": str(adapter_output.resolve()),
        "adapter_sha256": sha256_file(adapter_output),
        "mask_output": str(mask_output.resolve()),
        "mask_sha256": sha256_file(mask_output),
        "label_free": True,
        "recommended_cache_builder": str((SCRIPT_DIR / "prepare_esm2_embeddings_v2_3.py").resolve()),
        "cache_builder_contract": (
            "pass adapter_output as --inference-candidates, the fixed target FASTA as --target-fasta, "
            "and absent paths for site/pair/ranking/contact inputs to build a dedicated 7088-sequence cache"
        ),
    }
    atomic_write_json(receipt_output, receipt)
    return receipt


def load_hotspot_weights(
    path: Path,
    target_sequence: str,
    target_uniprot_start: int,
    expected_count: int,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    rows, fieldnames = read_csv(path)
    required = {"uniprot_position", "uniprot_aa", "priority_weight"}
    if not required.issubset(fieldnames):
        rows, fieldnames = read_csv(path, delimiter="\t")
    missing = required - set(fieldnames)
    if missing:
        raise FeatureExtractionError(f"hotspot table lacks fields: {sorted(missing)}")
    weights = np.zeros(len(target_sequence), dtype=np.float32)
    selected: list[dict[str, Any]] = []
    for row in rows:
        hotspot_class = row.get("hotspot_class", "").strip()
        if hotspot_class and hotspot_class not in {"core_hotspot", "secondary_hotspot"}:
            continue
        weight = float(row.get("priority_weight") or 0.0)
        if weight <= 0:
            continue
        uniprot_position = int(row["uniprot_position"])
        index = uniprot_position - target_uniprot_start
        if not 0 <= index < len(target_sequence):
            raise FeatureExtractionError(f"hotspot UniProt position outside target: {uniprot_position}")
        aa = row["uniprot_aa"].strip().upper()
        if target_sequence[index] != aa:
            raise FeatureExtractionError(
                f"hotspot/target residue mismatch at UniProt {uniprot_position}: {aa}!={target_sequence[index]}"
            )
        if weights[index] > 0:
            raise FeatureExtractionError(f"duplicate selected hotspot at UniProt {uniprot_position}")
        weights[index] = weight
        selected.append(
            {
                "hotspot_id": row.get("hotspot_id", ""),
                "hotspot_class": hotspot_class,
                "uniprot_position": uniprot_position,
                "target_index_0based": index,
                "aa": aa,
                "weight": weight,
            }
        )
    if len(selected) != expected_count:
        raise FeatureExtractionError(f"expected {expected_count} fixed hotspots, found {len(selected)}")
    return weights, sorted(selected, key=lambda row: row["target_index_0based"])


def load_cache_manifest(path: Path) -> dict[str, dict[str, str]]:
    rows, fieldnames = read_csv(path)
    required = {"sequence_sha256", "sequence_length", "cached_length", "shard_path", "shard_key"}
    missing = required - set(fieldnames)
    if missing:
        raise FeatureExtractionError(f"ESM2 cache manifest lacks fields: {sorted(missing)}")
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        digest = row["sequence_sha256"]
        if digest in mapping:
            raise FeatureExtractionError(f"duplicate sequence in ESM2 cache manifest: {digest}")
        mapping[digest] = row
    return mapping


def load_mask_inventory(path: Path) -> tuple[dict[str, dict[str, str]], Counter[str]]:
    rows, fieldnames = read_csv(path)
    required = {
        "sequence_hash", "vhh_seq", "vhh_len", "cdr_mask_json", "spans_json",
        "cdr1_seq", "cdr2_seq", "cdr3_seq", "status",
    }
    missing = required - set(fieldnames)
    if missing:
        raise FeatureExtractionError(f"CDR mask table lacks fields: {sorted(missing)}")
    mapping: dict[str, dict[str, str]] = {}
    statuses: Counter[str] = Counter()
    for row in rows:
        digest = row["sequence_hash"]
        if digest in mapping:
            raise FeatureExtractionError(f"duplicate sequence in CDR mask table: {digest}")
        mapping[digest] = row
        statuses[row.get("status", "")] += 1
    return mapping, statuses


def validate_candidate_mask(candidate: dict[str, str], mask_row: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    sequence = candidate["vhh_seq"]
    digest = candidate["sequence_sha256"]
    mask_sequence = mask_row.get("vhh_seq", "").strip().upper()
    if mask_row.get("sequence_hash", "").strip().lower() != digest:
        reasons.append("sequence_hash_key_mismatch")
    if seq_hash(mask_sequence) != digest:
        reasons.append("mask_vhh_seq_hash_mismatch")
    if mask_sequence != sequence:
        reasons.append("mask_vhh_seq_candidate_sequence_mismatch")
    try:
        if int(mask_row["vhh_len"]) != len(sequence):
            reasons.append("vhh_len_mismatch")
    except (TypeError, ValueError):
        reasons.append("vhh_len_invalid")
    try:
        values = [int(value) for value in json.loads(mask_row["cdr_mask_json"])]
    except (TypeError, ValueError, json.JSONDecodeError):
        values = []
        reasons.append("cdr_mask_json_invalid")
    try:
        spans_payload = json.loads(mask_row["spans_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        spans_payload = {}
        reasons.append("spans_json_invalid")
    expected_mask = [0] * len(sequence)
    previous_end = 0
    for cdr_type, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
        try:
            adapter_start, adapter_end = parse_zero_based_span(
                candidate[f"{name}_span_0based"], len(sequence), f"{candidate['candidate_id']}:{name}"
            )
        except FeatureExtractionError:
            reasons.append(f"{name}_adapter_span_invalid")
            continue
        raw_span = spans_payload.get(name) if isinstance(spans_payload, dict) else None
        if not isinstance(raw_span, list) or len(raw_span) != 2:
            reasons.append(f"{name}_mask_span_invalid")
            continue
        try:
            mask_start, mask_end = int(raw_span[0]), int(raw_span[1])
        except (TypeError, ValueError):
            reasons.append(f"{name}_mask_span_invalid")
            continue
        if (mask_start, mask_end) != (adapter_start, adapter_end):
            reasons.append(f"{name}_span_mismatch")
        if mask_start < previous_end or not 0 <= mask_start < mask_end <= len(sequence):
            reasons.append(f"{name}_mask_span_order_or_bounds")
            continue
        previous_end = mask_end
        candidate_cdr = candidate[name]
        mask_cdr = mask_row.get(f"{name}_seq", "").strip().upper()
        if mask_cdr != candidate_cdr:
            reasons.append(f"{name}_sequence_mismatch")
        if sequence[mask_start:mask_end] != candidate_cdr:
            reasons.append(f"{name}_subsequence_mismatch")
        expected_mask[mask_start:mask_end] = [cdr_type] * (mask_end - mask_start)
    if len(values) != len(sequence):
        reasons.append("cdr_mask_length_mismatch")
    elif values != expected_mask:
        reasons.append("cdr_mask_identity_mismatch")
    if mask_row.get("status") != "exact_annotation":
        reasons.append("mask_status_not_exact_annotation")
    return sorted(set(reasons))


def checkpoint_descriptors(paths: Sequence[Path], expected_seeds: set[int]) -> list[dict[str, Any]]:
    allowed_cfg = {field.name for field in fields(Config)}
    descriptors: list[dict[str, Any]] = []
    architecture: dict[str, Any] | None = None
    for path in paths:
        if not path.is_file():
            raise FeatureExtractionError(f"missing frozen checkpoint: {path}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        raw_cfg = payload.get("cfg")
        state = payload.get("model")
        if not isinstance(raw_cfg, dict) or not isinstance(state, dict):
            raise FeatureExtractionError(f"checkpoint lacks cfg/model: {path}")
        unknown = set(raw_cfg) - allowed_cfg
        if unknown:
            raise FeatureExtractionError(f"checkpoint config has unknown fields: {sorted(unknown)}")
        cfg = Config(**{**asdict(Config()), **raw_cfg})
        signature = {field: getattr(cfg, field) for field in ARCHITECTURE_FIELDS}
        if architecture is None:
            architecture = signature
        elif signature != architecture:
            raise FeatureExtractionError("V2.3 checkpoints do not share one inference architecture")
        descriptors.append(
            {
                "seed": int(cfg.seed),
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "epoch": int(payload.get("epoch", -1)),
                "best_score": float(payload.get("best_score", 0.0)),
                "architecture": signature,
            }
        )
    observed = {row["seed"] for row in descriptors}
    if len(descriptors) != len(expected_seeds) or observed != expected_seeds:
        raise FeatureExtractionError(
            f"checkpoint seed closure mismatch: expected={sorted(expected_seeds)} observed={sorted(observed)}"
        )
    return sorted(descriptors, key=lambda row: row["seed"])


def preflight(
    *,
    candidates_path: Path,
    cache_manifest_path: Path,
    mask_path: Path,
    target_path: Path,
    hotspot_path: Path,
    checkpoint_paths: Sequence[Path],
    expected_count: int | None,
    expected_seeds: set[int],
    target_uniprot_start: int,
    expected_hotspots: int,
    test_only_allow_unfrozen_input_hashes: bool = False,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if test_only_allow_unfrozen_input_hashes and expected_count == 7087:
        raise FeatureExtractionError(
            "test-only unfrozen hash override is forbidden for the 7,087-candidate production panel"
        )
    candidates, candidate_fields = load_candidates(candidates_path, expected_count)
    target_sequence = read_fasta(target_path)
    _weights, hotspots = load_hotspot_weights(
        hotspot_path, target_sequence, target_uniprot_start, expected_hotspots
    )
    checkpoints = checkpoint_descriptors(checkpoint_paths, expected_seeds)
    cache = load_cache_manifest(cache_manifest_path)
    masks, mask_statuses = load_mask_inventory(mask_path)
    required_hashes = {row["sequence_sha256"] for row in candidates}
    required_cache_hashes = required_hashes | {seq_hash(target_sequence)}
    missing_cache = sorted(required_cache_hashes - set(cache))
    missing_masks = sorted(required_hashes - set(masks))
    invalid_cache_identity: list[str] = []
    invalid_masks: list[str] = []
    for row in candidates:
        digest = row["sequence_sha256"]
        cached = cache.get(digest)
        if cached and (
            int(cached["sequence_length"]) != len(row["vhh_seq"])
            or int(cached["cached_length"]) != len(row["vhh_seq"])
            or cached.get("shard_key", "") != digest
        ):
            invalid_cache_identity.append(digest)
        mask_row = masks.get(digest)
        if mask_row:
            if validate_candidate_mask(row, mask_row):
                invalid_masks.append(digest)
    target_cache = cache.get(seq_hash(target_sequence))
    if target_cache and (
        int(target_cache["sequence_length"]) != len(target_sequence)
        or int(target_cache["cached_length"]) != len(target_sequence)
        or target_cache.get("shard_key", "") != seq_hash(target_sequence)
    ):
        invalid_cache_identity.append(seq_hash(target_sequence))
    missing_shards = sorted(
        {
            row["shard_path"]
            for digest, row in cache.items()
            if digest in required_cache_hashes and not (cache_manifest_path.parent / row["shard_path"]).is_file()
        }
    )
    blockers = {
        "missing_cache_sequences": len(missing_cache),
        "missing_cdr_masks": len(missing_masks),
        "invalid_cache_identity": len(invalid_cache_identity),
        "invalid_or_nonexact_cdr_masks": len(invalid_masks),
        "missing_cache_shards": len(missing_shards),
    }
    ready = not any(blockers.values())
    input_hashes = {
        "candidates": sha256_file(candidates_path),
        "cache_manifest": sha256_file(cache_manifest_path),
        "cdr_masks": sha256_file(mask_path),
        "target_fasta": sha256_file(target_path),
        "hotspots": sha256_file(hotspot_path),
    }
    hash_lock_mismatches: dict[str, dict[str, str]] = {}
    if not test_only_allow_unfrozen_input_hashes:
        for name, expected_hash in PRODUCTION_EXPECTED_HASHES.items():
            actual_hash = input_hashes[name]
            if actual_hash != expected_hash:
                hash_lock_mismatches[name] = {"expected": expected_hash, "actual": actual_hash}
        for checkpoint in checkpoints:
            expected_hash = PRODUCTION_EXPECTED_CHECKPOINT_HASHES.get(checkpoint["seed"], "")
            if checkpoint["sha256"] != expected_hash:
                hash_lock_mismatches[f"checkpoint_seed{checkpoint['seed']}"] = {
                    "expected": expected_hash,
                    "actual": checkpoint["sha256"],
                }
    if hash_lock_mismatches:
        blockers["production_hash_lock_mismatches"] = len(hash_lock_mismatches)
        ready = False
    report = {
        "status": "READY" if ready else "BLOCKED_INPUT_COVERAGE",
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "label_free_contract": {
            "docking_label_inputs_read": 0,
            "v4d_raw_results_read": 0,
            "v4d_job_state_read": 0,
            "accepted_inputs": [
                "candidate_sequences_and_generation_provenance",
                "exact_cdr_masks",
                "frozen_esm2_residue_cache",
                "frozen_v2_3_checkpoints",
                "fixed_pvrig_target_fasta",
                "fixed_pvrig_hotspot_table",
            ],
            "claim_boundary": CLAIM_BOUNDARY,
            "production_hash_locks_enforced": not test_only_allow_unfrozen_input_hashes,
            "test_only_unfrozen_hash_override": test_only_allow_unfrozen_input_hashes,
        },
        "candidate_count": len(candidates),
        "candidate_fields": candidate_fields,
        "candidate_unique_sequence_count": len({row["sequence_sha256"] for row in candidates}),
        "target_sequence_sha256": seq_hash(target_sequence),
        "target_length": len(target_sequence),
        "hotspot_count": len(hotspots),
        "hotspots": hotspots,
        "checkpoints": checkpoints,
        "cache_manifest_row_count": len(cache),
        "cache_required_sequence_count": len(required_cache_hashes),
        "cache_coverage_count": len(required_cache_hashes) - len(missing_cache),
        "cdr_mask_row_count": len(masks),
        "cdr_mask_coverage_count": len(required_hashes) - len(missing_masks),
        "cdr_mask_status_counts": dict(sorted(mask_statuses.items())),
        "blockers": blockers,
        "blocker_examples": {
            "missing_cache_sequences": missing_cache[:20],
            "missing_cdr_masks": missing_masks[:20],
            "invalid_cache_identity": sorted(invalid_cache_identity)[:20],
            "invalid_or_nonexact_cdr_masks": sorted(invalid_masks)[:20],
            "missing_cache_shards": missing_shards[:20],
            "production_hash_lock_mismatches": hash_lock_mismatches,
        },
        "input_hashes": input_hashes,
        "production_hash_lock": {
            "enforced": not test_only_allow_unfrozen_input_hashes,
            "expected_inputs": PRODUCTION_EXPECTED_HASHES,
            "expected_checkpoints_by_seed": {
                str(seed): digest
                for seed, digest in sorted(PRODUCTION_EXPECTED_CHECKPOINT_HASHES.items())
            },
            "mismatches": hash_lock_mismatches,
        },
        "input_closure_sha256": sha256_json(
            {"input_hashes": input_hashes, "checkpoints": checkpoints, "feature_names": FEATURE_NAMES}
        ),
    }
    return report, candidates


def topk_mean(values: np.ndarray, k: int = 20) -> float:
    flat = np.asarray(values, dtype=np.float64).reshape(-1)
    if flat.size == 0:
        return 0.0
    selected = np.partition(flat, max(0, flat.size - min(k, flat.size)))[-min(k, flat.size) :]
    return float(selected.mean())


def safe_mean(values: np.ndarray) -> float:
    return float(values.mean()) if values.size else 0.0


def residue_features(
    pair_logit: float,
    paratope: np.ndarray,
    epitope: np.ndarray,
    contacts: np.ndarray,
    cdr_mask: np.ndarray,
    hotspot_weights: np.ndarray,
) -> dict[str, float]:
    hotspot_indices = np.flatnonzero(hotspot_weights > 0)
    noninterface_indices = np.flatnonzero(hotspot_weights == 0)
    weights = hotspot_weights[hotspot_indices].astype(np.float64)
    cdr_rows = np.flatnonzero(cdr_mask > 0)
    cdr3_rows = np.flatnonzero(cdr_mask == 3)
    hotspot_contacts = contacts[:, hotspot_indices]
    cdr_hotspot = contacts[np.ix_(cdr_rows, hotspot_indices)]
    cdr3_hotspot = contacts[np.ix_(cdr3_rows, hotspot_indices)]

    def weighted_contact_mean(matrix: np.ndarray) -> float:
        if matrix.size == 0:
            return 0.0
        return float((matrix * weights[None, :]).sum() / (matrix.shape[0] * weights.sum()))

    hotspot_mean = weighted_contact_mean(hotspot_contacts)
    noninterface_mean = safe_mean(contacts[:, noninterface_indices])
    epi_hotspot = float(np.average(epitope[hotspot_indices], weights=weights))
    epi_noninterface = safe_mean(epitope[noninterface_indices])
    total_contact = float(contacts.sum())
    return {
        "pair_ranking_logit_weak": float(pair_logit),
        "pair_ranking_sigmoid_weak": float(
            1.0 / (1.0 + np.exp(-pair_logit))
            if pair_logit >= 0
            else np.exp(pair_logit) / (1.0 + np.exp(pair_logit))
        ),
        "paratope_mean": safe_mean(paratope),
        "paratope_cdr_mean": safe_mean(paratope[cdr_rows]),
        "paratope_cdr3_mean": safe_mean(paratope[cdr3_rows]),
        "paratope_cdr3_max": float(paratope[cdr3_rows].max()) if cdr3_rows.size else 0.0,
        "paratope_cdr_mass_fraction": float(paratope[cdr_rows].sum() / max(float(paratope.sum()), 1e-12)),
        "contact_global_mean": safe_mean(contacts),
        "contact_global_top20_mean": topk_mean(contacts),
        "contact_hotspot_weighted_mean": hotspot_mean,
        "contact_hotspot_top20_mean": topk_mean(hotspot_contacts),
        "contact_hotspot_fraction": float(hotspot_contacts.sum() / max(total_contact, 1e-12)),
        "contact_cdr_hotspot_weighted_mean": weighted_contact_mean(cdr_hotspot),
        "contact_cdr_hotspot_mass_length_confounded_diagnostic": float(
            (cdr_hotspot * weights[None, :]).sum()
        ),
        "contact_cdr3_hotspot_weighted_mean": weighted_contact_mean(cdr3_hotspot),
        "contact_cdr3_hotspot_top20_mean": topk_mean(cdr3_hotspot),
        "contact_cdr3_hotspot_mass_length_confounded_diagnostic": float(
            (cdr3_hotspot * weights[None, :]).sum()
        ),
        "contact_noninterface_mean": noninterface_mean,
        "contact_interface_specificity": hotspot_mean - noninterface_mean,
        "epitope_hotspot_weighted_mean": epi_hotspot,
        "epitope_noninterface_mean": epi_noninterface,
        "epitope_interface_specificity": epi_hotspot - epi_noninterface,
    }


def infer_one_seed(
    *,
    model: torch.nn.Module,
    cfg: Config,
    cache: ESM2Cache,
    masks: CDRMaskStore,
    candidates: Sequence[dict[str, str]],
    target_sequence: str,
    hotspot_weights: np.ndarray,
    device: torch.device,
    batch_size: int,
    use_amp: bool,
) -> dict[str, dict[str, float]]:
    target = cache.get(target_sequence, cfg.max_antigen_len).to(device)
    target_weights = hotspot_weights[: target.shape[0]]
    output: dict[str, dict[str, float]] = {}
    model.eval()
    amp_enabled = bool(use_amp and device.type == "cuda")
    with torch.inference_mode():
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            vhh_tensors: list[torch.Tensor] = []
            cdr_tensors: list[torch.Tensor] = []
            lengths: list[int] = []
            for row in batch:
                tensor = cache.get(row["vhh_seq"], cfg.max_vhh_len)
                cdr = masks.get(row["vhh_seq"], cfg.max_vhh_len)[: tensor.shape[0]]
                if len(cdr) != len(tensor):
                    raise FeatureExtractionError(f"cache/mask length mismatch: {row['candidate_id']}")
                vhh_tensors.append(tensor)
                cdr_tensors.append(cdr)
                lengths.append(len(tensor))
            vhh = pad_sequence(vhh_tensors, batch_first=True).to(device)
            cdr = pad_sequence(cdr_tensors, batch_first=True, padding_value=0).to(device)
            antigen = target.unsqueeze(0).expand(len(batch), -1, -1)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp_enabled):
                hv, ha, vm, am = model.encode(vhh, cdr, antigen)
                pair_logits = model.pair_logits_from_encoded(hv, ha, vm, am, cdr)
                para_logits, epi_logits = model.site_logits(hv, ha)
                contact_logits = model.contact_logits(hv, ha)
            pair_values = pair_logits.float().cpu().numpy()
            para_values = torch.sigmoid(para_logits.float()).cpu().numpy()
            epi_values = torch.sigmoid(epi_logits.float()).cpu().numpy()
            contact_values = torch.sigmoid(contact_logits.float()).cpu().numpy()
            cdr_values = cdr.cpu().numpy().astype(np.int8)
            for index, row in enumerate(batch):
                length = lengths[index]
                output[row["candidate_id"]] = residue_features(
                    float(pair_values[index]),
                    para_values[index, :length],
                    epi_values[index, : target.shape[0]],
                    contact_values[index, :length, : target.shape[0]],
                    cdr_values[index, :length],
                    target_weights,
                )
    return output


def format_float(value: float) -> str:
    if not np.isfinite(value):
        raise FeatureExtractionError(f"nonfinite feature value: {value}")
    return format(float(value), ".10g")


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FeatureExtractionError(f"missing JSON artifact: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FeatureExtractionError(f"malformed JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FeatureExtractionError(f"JSON artifact is not an object: {path}")
    return payload


def verify_release_receipt(receipt_path: Path) -> dict[str, Any]:
    receipt = load_json_object(receipt_path)
    if receipt.get("status") != "PASS" or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise FeatureExtractionError("release receipt status/schema mismatch")
    if receipt.get("feature_schema_version") != SCHEMA_VERSION:
        raise FeatureExtractionError("release receipt feature schema is not current v3")
    output_path = Path(str(receipt.get("output", "")))
    audit_path = Path(str(receipt.get("audit", "")))
    if sha256_file(output_path) != receipt.get("output_sha256"):
        raise FeatureExtractionError("release output hash does not match receipt")
    if sha256_file(audit_path) != receipt.get("audit_sha256"):
        raise FeatureExtractionError("release audit hash does not match receipt")
    if sha256_file(Path(str(receipt.get("script", "")))) != receipt.get("script_sha256"):
        raise FeatureExtractionError("release script hash does not match receipt")
    snapshot = receipt.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise FeatureExtractionError("release receipt lacks input snapshot")
    current_paths = {
        label: Path(str(row.get("path", "")))
        for label, row in snapshot.items()
        if isinstance(row, dict)
    }
    if set(current_paths) != set(snapshot):
        raise FeatureExtractionError("release receipt input snapshot is malformed")
    current_snapshot = snapshot_files(current_paths)
    changed = compare_snapshots(snapshot, current_snapshot)
    if changed:
        raise FeatureExtractionError(
            f"release input snapshot no longer matches: {json.dumps(changed, sort_keys=True)}"
        )
    if snapshot_content_closure(current_snapshot) != receipt.get("input_snapshot_content_closure_sha256"):
        raise FeatureExtractionError("release input snapshot closure mismatch")
    audit = load_json_object(audit_path)
    if audit.get("status") != "PASS" or audit.get("feature_schema_version") != SCHEMA_VERSION:
        raise FeatureExtractionError("release audit status/schema mismatch")
    if audit.get("output_sha256") != receipt.get("output_sha256"):
        raise FeatureExtractionError("audit/output receipt closure mismatch")
    if audit.get("input_snapshot_unchanged") is not True:
        raise FeatureExtractionError("audit does not prove unchanged inference inputs")
    contract = audit.get("label_free_contract")
    if not isinstance(contract, dict):
        raise FeatureExtractionError("audit lacks label-free contract")
    if int(receipt.get("output_row_count", -1)) == 7087 and (
        contract.get("production_hash_locks_enforced") is not True
        or contract.get("test_only_unfrozen_hash_override") is not False
    ):
        raise FeatureExtractionError("formal 7,087 release did not enforce production input hashes")
    policy = audit.get("feature_policy")
    if not isinstance(policy, dict):
        raise FeatureExtractionError("audit lacks feature policy")
    stable = set(policy.get("stable_default_trainer_features") or [])
    prohibited = set(policy.get("default_trainer_must_exclude") or [])
    if stable != set(STABLE_FEATURE_NAMES) or prohibited != set(DIAGNOSTIC_ONLY_FEATURES):
        raise FeatureExtractionError("audit feature policy does not match current stable schema")
    if stable & prohibited:
        raise FeatureExtractionError("stable and prohibited feature policies overlap")
    rows, fieldnames = read_csv(output_path)
    if len(rows) != int(receipt.get("output_row_count", -1)):
        raise FeatureExtractionError("release output row count does not match receipt")
    if not rows or any(row.get("schema_version") != SCHEMA_VERSION for row in rows):
        raise FeatureExtractionError("release output rows do not uniformly use current v3 schema")
    if any(row.get("supersedes") != ";".join(SUPERSEDED_SCHEMA_VERSIONS) for row in rows):
        raise FeatureExtractionError("release output supersedes field mismatch")
    for feature in DIAGNOSTIC_ONLY_FEATURES:
        if not any(field.startswith(feature) for field in fieldnames):
            raise FeatureExtractionError(f"diagnostic feature missing from release: {feature}")
    return {
        "status": "PASS",
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verified_at": utc_now(),
        "receipt": str(receipt_path.resolve()),
        "receipt_sha256": sha256_file(receipt_path),
        "output_sha256": receipt["output_sha256"],
        "audit_sha256": receipt["audit_sha256"],
        "input_snapshot_content_closure_sha256": receipt["input_snapshot_content_closure_sha256"],
        "row_count": len(rows),
        "feature_schema_version": SCHEMA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def run_extraction(
    *,
    candidates_path: Path,
    cache_manifest_path: Path,
    mask_path: Path,
    target_path: Path,
    hotspot_path: Path,
    checkpoint_paths: Sequence[Path],
    output_path: Path,
    audit_path: Path,
    receipt_path: Path | None = None,
    verification_path: Path | None = None,
    quarantine_root: Path | None = None,
    superseded_output_paths: Sequence[Path] = DEFAULT_SUPERSEDED_OUTPUTS,
    expected_count: int | None = 7087,
    expected_seeds: set[int] = frozenset({43, 53, 67}),
    target_uniprot_start: int = 39,
    expected_hotspots: int = 23,
    batch_size: int = 32,
    device_name: str = "cuda",
    use_amp: bool = True,
    test_only_allow_unfrozen_input_hashes: bool = False,
) -> dict[str, Any]:
    report, candidates = preflight(
        candidates_path=candidates_path,
        cache_manifest_path=cache_manifest_path,
        mask_path=mask_path,
        target_path=target_path,
        hotspot_path=hotspot_path,
        checkpoint_paths=checkpoint_paths,
        expected_count=expected_count,
        expected_seeds=set(expected_seeds),
        target_uniprot_start=target_uniprot_start,
        expected_hotspots=expected_hotspots,
        test_only_allow_unfrozen_input_hashes=test_only_allow_unfrozen_input_hashes,
    )
    if report["status"] != "READY":
        raise FeatureExtractionError(
            f"label-free feature preflight blocked: {json.dumps(report['blockers'], sort_keys=True)}"
        )
    if batch_size < 1:
        raise FeatureExtractionError("batch_size must be positive")
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise FeatureExtractionError("CUDA requested but unavailable")
    target_sequence = read_fasta(target_path)
    hotspot_weights, _hotspots = load_hotspot_weights(
        hotspot_path, target_sequence, target_uniprot_start, expected_hotspots
    )
    cache_inventory = load_cache_manifest(cache_manifest_path)
    required_hashes = {row["sequence_sha256"] for row in candidates} | {seq_hash(target_sequence)}
    referenced_shards = sorted({cache_inventory[digest]["shard_path"] for digest in required_hashes})
    snapshot_paths = {
        "candidates": candidates_path,
        "cache_manifest": cache_manifest_path,
        "cdr_masks": mask_path,
        "target_fasta": target_path,
        "hotspots": hotspot_path,
        **{
            f"checkpoint_seed{checkpoint['seed']}": Path(checkpoint["path"])
            for checkpoint in report["checkpoints"]
        },
        **{
            f"cache_shard:{shard}": cache_manifest_path.parent / shard
            for shard in referenced_shards
        },
    }
    input_snapshot_before = snapshot_files(snapshot_paths)
    architecture = report["checkpoints"][0]["architecture"]
    cache = ESM2Cache(cache_manifest_path, int(architecture["esm_dim"]))
    masks = CDRMaskStore(mask_path)
    features_by_candidate: dict[str, dict[int, dict[str, float]]] = {
        row["candidate_id"]: {} for row in candidates
    }
    checkpoint_by_seed = {row["seed"]: row for row in report["checkpoints"]}
    for seed in sorted(expected_seeds):
        checkpoint = Path(checkpoint_by_seed[seed]["path"])
        model, cfg, _payload = load_model_from_checkpoint(checkpoint, None, device)
        per_seed = infer_one_seed(
            model=model,
            cfg=cfg,
            cache=cache,
            masks=masks,
            candidates=candidates,
            target_sequence=target_sequence,
            hotspot_weights=hotspot_weights,
            device=device,
            batch_size=batch_size,
            use_amp=use_amp,
        )
        for candidate_id, values in per_seed.items():
            features_by_candidate[candidate_id][seed] = values
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()

    seeds = sorted(expected_seeds)
    input_snapshot_after = snapshot_files(snapshot_paths)
    snapshot_changes = compare_snapshots(input_snapshot_before, input_snapshot_after)
    if snapshot_changes:
        raise FeatureExtractionError(
            f"frozen inference inputs changed during extraction: {json.dumps(snapshot_changes, sort_keys=True)}"
        )

    identity_fields = [
        "schema_version", "supersedes", "candidate_id", "sequence_sha256", "sequence_length",
        "cdr1_length", "cdr2_length", "cdr3_length",
        *PROVENANCE_FIELDS, "cdr_mask_status", "seed_count", "claim_boundary",
    ]
    seed_fields = [f"seed{seed}_{feature}" for seed in seeds for feature in FEATURE_NAMES]
    aggregate_fields = [
        field
        for feature in FEATURE_NAMES
        for field in (f"{feature}_seed_mean", f"{feature}_seed_std")
    ]
    output_fields = identity_fields + seed_fields + aggregate_fields
    output_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        seed_values = features_by_candidate[candidate_id]
        if set(seed_values) != set(seeds):
            raise FeatureExtractionError(f"incomplete seed feature closure: {candidate_id}")
        row: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "supersedes": ";".join(SUPERSEDED_SCHEMA_VERSIONS),
            "candidate_id": candidate_id,
            "sequence_sha256": candidate["sequence_sha256"],
            "sequence_length": len(candidate["vhh_seq"]),
            "cdr1_length": len(candidate["cdr1"]),
            "cdr2_length": len(candidate["cdr2"]),
            "cdr3_length": len(candidate["cdr3"]),
            **{field: candidate.get(field, "") for field in PROVENANCE_FIELDS},
            "cdr_mask_status": masks.status_for(candidate["vhh_seq"]),
            "seed_count": len(seeds),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        for seed in seeds:
            for feature in FEATURE_NAMES:
                row[f"seed{seed}_{feature}"] = format_float(seed_values[seed][feature])
        for feature in FEATURE_NAMES:
            values = [seed_values[seed][feature] for seed in seeds]
            row[f"{feature}_seed_mean"] = format_float(statistics.fmean(values))
            row[f"{feature}_seed_std"] = format_float(statistics.pstdev(values))
        output_rows.append(row)
    receipt_path = receipt_path or output_path.with_suffix(".receipt.json")
    verification_path = verification_path or output_path.with_suffix(".verification.json")
    quarantine_records: list[dict[str, Any]] = []
    release_outputs = [*superseded_output_paths]
    if output_path not in release_outputs:
        release_outputs.append(output_path)
    for old_output in release_outputs:
        if not old_output.is_file():
            continue
        associated = (
            old_output,
            old_output.with_suffix(".audit.json"),
            old_output.with_suffix(".receipt.json"),
            old_output.with_suffix(".verification.json"),
        )
        quarantine_records.append(
            quarantine_superseded_release(associated, old_output, quarantine_root)
        )
    atomic_write_csv(output_path, output_rows, output_fields)
    shard_hashes = {
        shard: input_snapshot_after[f"cache_shard:{shard}"]["sha256"]
        for shard in referenced_shards
    }
    report.update(
        {
            "status": "PASS",
            "feature_schema_version": SCHEMA_VERSION,
            "supersedes": list(SUPERSEDED_SCHEMA_VERSIONS),
            "feature_names": list(FEATURE_NAMES),
            "feature_policy": {
                "stable_default_trainer_features": list(STABLE_FEATURE_NAMES),
                "stable_default_trainer_columns": [
                    column
                    for feature in STABLE_FEATURE_NAMES
                    for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
                ],
                "diagnostic_only_length_confounded_features": list(DIAGNOSTIC_ONLY_FEATURES),
                "default_trainer_must_exclude": list(DIAGNOSTIC_ONLY_FEATURES),
                "default_trainer_must_exclude_columns": [
                    column
                    for feature in DIAGNOSTIC_ONLY_FEATURES
                    for column in (
                        *(f"seed{seed}_{feature}" for seed in seeds),
                        f"{feature}_seed_mean",
                        f"{feature}_seed_std",
                    )
                ],
                "length_only_baseline_fields": list(LENGTH_ONLY_BASELINE_FIELDS),
                "required_shortcut_baselines": [
                    "sequence_and_cdr_length_only",
                    "parent_framework_cluster_only",
                    "design_metadata_only",
                ],
            },
            "feature_schema_sha256": sha256_json(
                {"schema_version": SCHEMA_VERSION, "output_fields": output_fields}
            ),
            "seed_aggregation": "arithmetic_mean_and_population_standard_deviation_ddof0",
            "device": str(device),
            "amp_enabled": bool(use_amp and device.type == "cuda"),
            "batch_size": batch_size,
            "output": str(output_path.resolve()),
            "output_row_count": len(output_rows),
            "output_column_count": len(output_fields),
            "output_sha256": sha256_file(output_path),
            "referenced_cache_shard_sha256": shard_hashes,
            "input_snapshot_before": input_snapshot_before,
            "input_snapshot_after": input_snapshot_after,
            "input_snapshot_content_closure_sha256": snapshot_content_closure(input_snapshot_before),
            "input_snapshot_unchanged": True,
            "quarantine": quarantine_records or [{"status": "NOT_NEEDED", "moved": []}],
            "receipt": str(receipt_path.resolve()),
            "verification": str(verification_path.resolve()),
            "script_sha256": sha256_file(Path(__file__)),
            "completed_at": utc_now(),
        }
    )
    report["release_closure_sha256"] = sha256_json(
        {
            "input_closure_sha256": report["input_closure_sha256"],
            "output_sha256": report["output_sha256"],
            "feature_schema_sha256": report["feature_schema_sha256"],
            "referenced_cache_shard_sha256": shard_hashes,
            "script_sha256": report["script_sha256"],
            "input_snapshot_content_closure_sha256": report[
                "input_snapshot_content_closure_sha256"
            ],
            "stable_feature_names": list(STABLE_FEATURE_NAMES),
            "diagnostic_only_features": list(DIAGNOSTIC_ONLY_FEATURES),
        }
    )
    atomic_write_json(audit_path, report)
    receipt = {
        "status": "PASS",
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "feature_schema_version": SCHEMA_VERSION,
        "supersedes": list(SUPERSEDED_SCHEMA_VERSIONS),
        "created_at": utc_now(),
        "output": str(output_path.resolve()),
        "output_sha256": sha256_file(output_path),
        "output_row_count": len(output_rows),
        "audit": str(audit_path.resolve()),
        "audit_sha256": sha256_file(audit_path),
        "input_snapshot": input_snapshot_after,
        "input_snapshot_content_closure_sha256": snapshot_content_closure(input_snapshot_after),
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__)),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_write_json(receipt_path, receipt)
    verification = verify_release_receipt(receipt_path)
    atomic_write_json(verification_path, verification)
    report["receipt_sha256"] = sha256_file(receipt_path)
    report["verification_sha256"] = sha256_file(verification_path)
    return report


def add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--cache-manifest", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--cdr-masks", type=Path, default=DEFAULT_MASKS)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--hotspots", type=Path, default=DEFAULT_HOTSPOTS)
    parser.add_argument("--checkpoints", type=Path, nargs="+", default=list(DEFAULT_CHECKPOINTS))
    parser.add_argument("--expected-candidates", type=int, default=7087)
    parser.add_argument("--expected-seeds", default="43,53,67")
    parser.add_argument("--target-uniprot-start", type=int, default=39)
    parser.add_argument("--expected-hotspots", type=int, default=23)
    parser.add_argument(
        "--test-only-allow-unfrozen-input-hashes",
        action="store_true",
        help="Synthetic tests only; rejected when --expected-candidates=7087.",
    )


def parse_seed_set(value: str) -> set[int]:
    try:
        seeds = {int(token.strip()) for token in value.split(",") if token.strip()}
    except ValueError as exc:
        raise FeatureExtractionError(f"invalid expected seed list: {value!r}") from exc
    if not seeds:
        raise FeatureExtractionError("expected seed list is empty")
    return seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-inputs", help="Adapt the fast-gate table and derive exact CDR masks")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--adapter-output", type=Path, required=True)
    prepare.add_argument("--mask-output", type=Path, required=True)
    prepare.add_argument("--receipt-output", type=Path, required=True)
    prepare.add_argument("--expected-candidates", type=int, default=7087)
    preflight_parser = subparsers.add_parser("preflight", help="Validate label-free input closure without inference")
    add_common_inputs(preflight_parser)
    preflight_parser.add_argument("--audit-output", type=Path)
    extract = subparsers.add_parser("extract", help="Run three-seed V2.3 residue/contact inference")
    add_common_inputs(extract)
    extract.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    extract.add_argument("--audit-output", type=Path)
    extract.add_argument("--receipt-output", type=Path)
    extract.add_argument("--verification-output", type=Path)
    extract.add_argument("--quarantine-root", type=Path)
    extract.add_argument(
        "--superseded-output",
        type=Path,
        action="append",
        default=list(DEFAULT_SUPERSEDED_OUTPUTS),
        help="Superseded v1/v2 CSV to quarantine only after v3 inference succeeds.",
    )
    extract.add_argument("--batch-size", type=int, default=32)
    extract.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    extract.add_argument("--no-amp", action="store_true")
    verify = subparsers.add_parser("verify-receipt", help="Independently verify a frozen feature release receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--output", type=Path, help="Optional verification JSON")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-inputs":
            result = prepare_label_free_inputs(
                args.source,
                args.adapter_output,
                args.mask_output,
                args.receipt_output,
                args.expected_candidates,
            )
        elif args.command == "verify-receipt":
            result = verify_release_receipt(args.receipt)
            if args.output:
                atomic_write_json(args.output, result)
        else:
            expected_seeds = parse_seed_set(args.expected_seeds)
            common = {
                "candidates_path": args.candidates,
                "cache_manifest_path": args.cache_manifest,
                "mask_path": args.cdr_masks,
                "target_path": args.target_fasta,
                "hotspot_path": args.hotspots,
                "checkpoint_paths": args.checkpoints,
                "expected_count": args.expected_candidates,
                "expected_seeds": expected_seeds,
                "target_uniprot_start": args.target_uniprot_start,
                "expected_hotspots": args.expected_hotspots,
                "test_only_allow_unfrozen_input_hashes": args.test_only_allow_unfrozen_input_hashes,
            }
            if args.command == "preflight":
                result, _candidates = preflight(**common)
                if args.audit_output:
                    atomic_write_json(args.audit_output, result)
            else:
                audit_path = args.audit_output or args.output.with_suffix(".audit.json")
                result = run_extraction(
                    **common,
                    output_path=args.output,
                    audit_path=audit_path,
                    receipt_path=args.receipt_output,
                    verification_path=args.verification_output,
                    quarantine_root=args.quarantine_root,
                    superseded_output_paths=args.superseded_output,
                    batch_size=args.batch_size,
                    device_name=args.device,
                    use_amp=not args.no_amp,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] in {"PASS", "READY"} else 3
    except (FeatureExtractionError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
