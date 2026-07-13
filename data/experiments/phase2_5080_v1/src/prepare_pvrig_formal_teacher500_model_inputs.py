#!/usr/bin/env python3
"""Prepare frozen residue-model inputs for the formal PVRIG Teacher500."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_teacher_formal_v1/model_inputs"
DEFAULT_MODEL = WORKSPACE_ROOT / "code/downloaded_models/NanoBind/models/esm2_t6_8M_UR50D"
EXPECTED_CANDIDATES = 500
EXPECTED_SELECTION_SHA256 = "9285dd09db2ca1492fa97d52e7d009f4891777548adf06bc1845935aceeb0991"
EXPECTED_TARGET_SEQUENCE_SHA256 = "b3d2735abe671004474d0196f9d010bbdf22ea2cec9ccb6d71b28f9bdb328075"
TARGET_ID = "PVRIG_structural_ectodomain_proxy_v1"
CLAIM_BOUNDARY = "formal_docking_teacher_sequence_inputs_not_binding_or_experimental_blocking_truth"
AA_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")

CACHE_COLUMNS = [
    "model_path",
    "model_sha256",
    "sequence_sha256",
    "sequence_length",
    "cached_length",
    "truncation_policy",
    "chain_type",
    "shard_path",
    "shard_key",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv_atomic(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})
        temporary = Path(handle.name)
    temporary.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def read_target(path: Path) -> str:
    sequence = "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )
    validate_sequence(sequence, "PVRIG target")
    return sequence


def validate_sequence(sequence: str, label: str) -> None:
    if not sequence:
        raise ValueError(f"Empty sequence for {label}")
    invalid = sorted(set(sequence) - AA_ALPHABET)
    if invalid:
        raise ValueError(f"Invalid amino acids for {label}: {''.join(invalid)}")


def verify_cdr(row: dict[str, str], cdr_name: str) -> tuple[int, int, str]:
    sequence = row["vhh_sequence"].strip().upper()
    cdr = row[f"{cdr_name}_after"].strip().upper()
    start = int(row[f"{cdr_name}_start_1based"])
    end = int(row[f"{cdr_name}_end_1based"])
    if not (1 <= start <= end <= len(sequence)):
        raise ValueError(f"{row['candidate_id']} {cdr_name} coordinates are out of bounds: {start}-{end}")
    if sequence[start - 1 : end] != cdr:
        raise ValueError(
            f"{row['candidate_id']} {cdr_name} frozen coordinates do not match sequence: {start}-{end} {cdr}"
        )
    return start - 1, end, cdr


def validate_selection(
    selection: Path,
    expected_selection_sha256: str | None,
) -> list[dict[str, str]]:
    actual_selection_sha256 = sha256_file(selection)
    if expected_selection_sha256 and actual_selection_sha256 != expected_selection_sha256:
        raise ValueError(
            "Frozen Teacher500 selection SHA256 mismatch: "
            f"expected={expected_selection_sha256} actual={actual_selection_sha256}"
        )
    rows = read_csv(selection)
    if len(rows) != EXPECTED_CANDIDATES:
        raise ValueError(f"Teacher500 selection must contain exactly {EXPECTED_CANDIDATES} rows, found {len(rows)}")
    ids = [row["candidate_id"].strip() for row in rows]
    sequences = [row["vhh_sequence"].strip().upper() for row in rows]
    declared_hashes = [row["sequence_sha256"].strip() for row in rows]
    if len(set(ids)) != EXPECTED_CANDIDATES:
        raise ValueError("Teacher500 selection must contain 500 exact-unique candidate IDs")
    if len(set(sequences)) != EXPECTED_CANDIDATES:
        raise ValueError("Teacher500 selection must contain 500 exact-unique VHH sequences")
    if len(set(declared_hashes)) != EXPECTED_CANDIDATES:
        raise ValueError("Teacher500 selection must contain 500 exact-unique declared sequence hashes")

    for row, sequence in zip(rows, sequences):
        validate_sequence(sequence, row["candidate_id"])
        if int(row["sequence_length"]) != len(sequence):
            raise ValueError(f"{row['candidate_id']} sequence_length does not match the sequence")
        actual_hash = sequence_sha256(sequence)
        if actual_hash != row["sequence_sha256"].strip():
            raise ValueError(
                f"{row['candidate_id']} sequence SHA256 mismatch: "
                f"declared={row['sequence_sha256']} actual={actual_hash}"
            )
        spans = [verify_cdr(row, name) for name in ("cdr1", "cdr2", "cdr3")]
        if not (spans[0][1] <= spans[1][0] and spans[1][1] <= spans[2][0]):
            raise ValueError(f"{row['candidate_id']} frozen CDR coordinates overlap or are out of order")
    return rows


def cdr_mask_row(row: dict[str, str]) -> dict[str, str]:
    sequence = row["vhh_sequence"].strip().upper()
    mask = [0] * len(sequence)
    spans: dict[str, list[int]] = {}
    cdrs: dict[str, str] = {}
    for cdr_type, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
        start, end, cdr = verify_cdr(row, name)
        mask[start:end] = [cdr_type] * (end - start)
        spans[name] = [start, end]
        cdrs[name] = cdr
    return {
        "sequence_hash": row["sequence_sha256"],
        "vhh_seq": sequence,
        "vhh_len": str(len(sequence)),
        "cdr_mask_json": json.dumps(mask, separators=(",", ":")),
        "spans_json": json.dumps(spans, sort_keys=True, separators=(",", ":")),
        "cdr1_seq": cdrs["cdr1"],
        "cdr2_seq": cdrs["cdr2"],
        "cdr3_seq": cdrs["cdr3"],
        "annotation_source": "pvrig_teacher500_frozen_manifest_v1",
        "status": "exact_annotation",
        "fallback_reason": "",
        "manifest_sources_json": '["pvrig_formal_teacher500"]',
    }


def prepare_sequence_inputs(
    selection: Path,
    target_fasta: Path,
    outdir: Path,
    expected_selection_sha256: str | None = EXPECTED_SELECTION_SHA256,
    expected_target_sequence_sha256: str | None = EXPECTED_TARGET_SEQUENCE_SHA256,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    rows = validate_selection(selection, expected_selection_sha256)
    target = read_target(target_fasta)
    target_hash = sequence_sha256(target)
    if expected_target_sequence_sha256 and target_hash != expected_target_sequence_sha256:
        raise ValueError(
            "Frozen PVRIG target sequence SHA256 mismatch: "
            f"expected={expected_target_sequence_sha256} actual={target_hash}"
        )

    outdir.mkdir(parents=True, exist_ok=True)
    candidate_path = outdir / "pvrig_formal_teacher500_candidates.csv"
    pair_path = outdir / "pvrig_formal_teacher500_pair_inputs.csv"
    cdr_path = outdir / "vhh_cdr_type_masks.csv"
    sequence_path = outdir / "sequence_manifest.csv"

    ordered = sorted(rows, key=lambda row: int(row["selection_rank"]))
    candidates = [
        {
            "candidate_id": row["candidate_id"],
            "vhh_seq": row["vhh_sequence"].strip().upper(),
            "sequence_sha256": row["sequence_sha256"],
            "cdr1": row["cdr1_after"],
            "cdr2": row["cdr2_after"],
            "cdr3": row["cdr3_after"],
            "cdr1_start_1based": row["cdr1_start_1based"],
            "cdr1_end_1based": row["cdr1_end_1based"],
            "cdr2_start_1based": row["cdr2_start_1based"],
            "cdr2_end_1based": row["cdr2_end_1based"],
            "cdr3_start_1based": row["cdr3_start_1based"],
            "cdr3_end_1based": row["cdr3_end_1based"],
            "parent_id": row["parent_id"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "target_patch_id": row["target_patch_id"],
            "design_mode": row["design_mode"],
            "formal_split": row["formal_split"],
            "selection_rank": row["selection_rank"],
        }
        for row in ordered
    ]
    pairs = [
        {
            "sample_id": row["candidate_id"],
            "vhh_sequence": row["vhh_sequence"].strip().upper(),
            "vhh_sequence_sha256": row["sequence_sha256"],
            "target_id": TARGET_ID,
            "target_sequence": target,
            "target_sequence_sha256": target_hash,
            "teacher_split": row["formal_split"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        for row in ordered
    ]
    cdr_rows = sorted((cdr_mask_row(row) for row in rows), key=lambda row: row["sequence_hash"])
    sequence_rows = [
        {
            "sequence_id": TARGET_ID,
            "sequence": target,
            "sequence_sha256": target_hash,
            "sequence_length": str(len(target)),
            "chain_type": "antigen",
        }
    ] + [
        {
            "sequence_id": row["candidate_id"],
            "sequence": row["vhh_sequence"].strip().upper(),
            "sequence_sha256": row["sequence_sha256"],
            "sequence_length": str(len(row["vhh_sequence"].strip())),
            "chain_type": "vhh",
        }
        for row in sorted(rows, key=lambda row: row["sequence_sha256"])
    ]

    candidate_fields = list(candidates[0])
    pair_fields = list(pairs[0])
    cdr_fields = list(cdr_rows[0])
    sequence_fields = list(sequence_rows[0])
    write_csv_atomic(candidate_path, candidates, candidate_fields)
    write_csv_atomic(pair_path, pairs, pair_fields)
    write_csv_atomic(cdr_path, cdr_rows, cdr_fields)
    write_csv_atomic(sequence_path, sequence_rows, sequence_fields)

    audit: dict[str, Any] = {
        "status": "PASS_FORMAL_TEACHER500_SEQUENCE_INPUTS_READY",
        "schema_version": "pvrig_formal_teacher500_model_inputs_v1",
        "candidate_count": len(candidates),
        "unique_candidate_id_count": len({row["candidate_id"] for row in candidates}),
        "unique_vhh_sequence_count": len({row["vhh_seq"] for row in candidates}),
        "sequence_manifest_count": len(sequence_rows),
        "target_id": TARGET_ID,
        "target_length": len(target),
        "target_sequence_sha256": target_hash,
        "parent_framework_cluster_count": len({row["parent_framework_cluster"] for row in candidates}),
        "formal_split_counts": dict(sorted(Counter(row["formal_split"] for row in candidates).items())),
        "cdr_mask_status_counts": {"exact_annotation": len(cdr_rows)},
        "paths": {
            "selection": str(selection),
            "target_fasta": str(target_fasta),
            "candidate_csv": str(candidate_path),
            "pair_csv": str(pair_path),
            "cdr_masks": str(cdr_path),
            "sequence_manifest": str(sequence_path),
        },
        "sha256": {
            "selection": sha256_file(selection),
            "target_fasta": sha256_file(target_fasta),
            "candidate_csv": sha256_file(candidate_path),
            "pair_csv": sha256_file(pair_path),
            "cdr_masks": sha256_file(cdr_path),
            "sequence_manifest": sha256_file(sequence_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json_atomic(outdir / "prepare_audit.json", audit)
    return audit, sequence_rows


def compute_model_sha256(model_path: Path) -> str:
    if not model_path.exists():
        raise FileNotFoundError(f"Local ESM2 model not found: {model_path}")
    digest = hashlib.sha256()
    files = [model_path] if model_path.is_file() else sorted(path for path in model_path.rglob("*") if path.is_file())
    for path in files:
        relative = path.name if model_path.is_file() else str(path.relative_to(model_path))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_cache_manifest(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    write_csv_atomic(
        path,
        sorted(rows, key=lambda row: (str(row["chain_type"]), str(row["sequence_sha256"]))),
        CACHE_COLUMNS,
    )


def load_valid_existing_cache_rows(
    manifest_path: Path,
    model_sha256: str,
    expected: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    if not manifest_path.exists():
        return {}
    valid: dict[str, dict[str, str]] = {}
    shard_payloads: dict[Path, dict[str, torch.Tensor]] = {}
    for row in read_csv(manifest_path):
        digest = row.get("sequence_sha256", "")
        source = expected.get(digest)
        if source is None or row.get("model_sha256") != model_sha256:
            continue
        shard_path = manifest_path.parent / row.get("shard_path", "")
        try:
            if shard_path not in shard_payloads:
                shard_payloads[shard_path] = torch.load(shard_path, map_location="cpu", weights_only=True)
            tensor = shard_payloads[shard_path][row.get("shard_key", "")]
            expected_length = int(source["sequence_length"])
            if (
                tensor.ndim != 2
                or tensor.shape[0] != expected_length
                or tensor.dtype != torch.float16
                or int(row.get("sequence_length", -1)) != expected_length
                or int(row.get("cached_length", -1)) != expected_length
                or row.get("truncation_policy") != "none"
                or row.get("chain_type") != source["chain_type"]
            ):
                continue
        except (FileNotFoundError, KeyError, RuntimeError, TypeError, ValueError):
            continue
        valid[digest] = row
    return valid


def next_shard_index(rows: Iterable[dict[str, str]]) -> int:
    indices: list[int] = []
    for row in rows:
        name = Path(row["shard_path"]).stem
        if name.startswith("shard_") and name[6:].isdigit():
            indices.append(int(name[6:]))
    return max(indices, default=-1) + 1


def load_esm2(model_path: Path) -> tuple[Any, Any]:
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModel.from_pretrained(str(model_path), local_files_only=True)
    model.eval()
    return tokenizer, model


def dynamic_batches(rows: Sequence[dict[str, str]], batch_size: int, attention_budget: int) -> list[list[dict[str, str]]]:
    if batch_size <= 0 or attention_budget <= 0:
        raise ValueError("batch_size and attention_budget must be positive")
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_max = 0
    for row in rows:
        length = int(row["sequence_length"])
        proposed_max = max(current_max, length)
        if current and (len(current) >= batch_size or (len(current) + 1) * proposed_max**2 > attention_budget):
            batches.append(current)
            current = []
            current_max = 0
        current.append(row)
        current_max = max(current_max, length)
    if current:
        batches.append(current)
    return batches


def embed_rows(
    rows: Sequence[dict[str, str]],
    tokenizer: Any,
    model: Any,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    encoded = tokenizer(
        [row["sequence"] for row in rows],
        return_tensors="pt",
        padding=True,
        truncation=False,
        return_special_tokens_mask=True,
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            output = model(input_ids=encoded["input_ids"], attention_mask=encoded.get("attention_mask"))
    attention = encoded.get("attention_mask", torch.ones_like(encoded["input_ids"]))
    special = encoded["special_tokens_mask"]
    embeddings: dict[str, torch.Tensor] = {}
    for index, row in enumerate(rows):
        residue_mask = (attention[index] == 1) & (special[index] == 0)
        tensor = output.last_hidden_state[index][residue_mask].detach().cpu().to(torch.float16).contiguous()
        if tensor.ndim != 2 or tensor.shape[0] != int(row["sequence_length"]):
            raise ValueError(f"ESM2 residue alignment mismatch for {row['sequence_sha256']}: {tuple(tensor.shape)}")
        embeddings[row["sequence_sha256"]] = tensor
    return embeddings


def build_resumable_cache(
    sequence_rows: Sequence[dict[str, str]],
    model_path: Path,
    cache_dir: Path,
    device_name: str,
    batch_size: int,
    attention_budget: int,
    shard_size: int,
) -> dict[str, Any]:
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    if device_name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.csv"
    model_hash = compute_model_sha256(model_path)
    expected = {row["sequence_sha256"]: row for row in sequence_rows}
    if len(expected) != EXPECTED_CANDIDATES + 1:
        raise ValueError("The residue cache requires exactly 501 exact-unique sequences")
    existing = load_valid_existing_cache_rows(manifest_path, model_hash, expected)
    missing = sorted(
        (row for digest, row in expected.items() if digest not in existing),
        key=lambda row: (int(row["sequence_length"]), row["chain_type"], row["sequence_sha256"]),
    )
    if not missing:
        return {
            "total_sequences": len(expected),
            "resumed_sequences": len(existing),
            "new_sequences": 0,
            "manifest": str(manifest_path),
            "model_sha256": model_hash,
        }

    tokenizer, model = load_esm2(model_path)
    device = torch.device(device_name)
    model.to(device)
    shard_index = next_shard_index(existing.values())
    manifest_rows: dict[str, dict[str, Any]] = dict(existing)
    for start in range(0, len(missing), shard_size):
        shard_rows = missing[start : start + shard_size]
        embeddings: dict[str, torch.Tensor] = {}
        for batch in dynamic_batches(shard_rows, batch_size, attention_budget):
            embeddings.update(embed_rows(batch, tokenizer, model, device))
        shard_name = f"shard_{shard_index:05d}.pt"
        final_shard = cache_dir / shard_name
        with tempfile.NamedTemporaryFile("wb", dir=cache_dir, delete=False) as handle:
            temporary_shard = Path(handle.name)
        torch.save({row["sequence_sha256"]: embeddings[row["sequence_sha256"]] for row in shard_rows}, temporary_shard)
        temporary_shard.replace(final_shard)
        for row in shard_rows:
            digest = row["sequence_sha256"]
            manifest_rows[digest] = {
                "model_path": str(model_path),
                "model_sha256": model_hash,
                "sequence_sha256": digest,
                "sequence_length": row["sequence_length"],
                "cached_length": row["sequence_length"],
                "truncation_policy": "none",
                "chain_type": row["chain_type"],
                "shard_path": shard_name,
                "shard_key": digest,
            }
        # Each completed shard is a durable resume checkpoint.
        write_cache_manifest(manifest_path, manifest_rows.values())
        shard_index += 1
    return {
        "total_sequences": len(expected),
        "resumed_sequences": len(existing),
        "new_sequences": len(missing),
        "manifest": str(manifest_path),
        "model_sha256": model_hash,
    }


def validate_model_inputs(outdir: Path, expected_dim: int = 320) -> dict[str, Any]:
    candidate_path = outdir / "pvrig_formal_teacher500_candidates.csv"
    pair_path = outdir / "pvrig_formal_teacher500_pair_inputs.csv"
    cdr_path = outdir / "vhh_cdr_type_masks.csv"
    sequence_path = outdir / "sequence_manifest.csv"
    cache_path = outdir / "esm2_8m_cache/manifest.csv"
    candidates = read_csv(candidate_path)
    pairs = read_csv(pair_path)
    cdrs = read_csv(cdr_path)
    sequences = read_csv(sequence_path)
    cache = read_csv(cache_path)
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    pair_by_id = {row["sample_id"]: row for row in pairs}
    cdr_by_hash = {row["sequence_hash"]: row for row in cdrs}
    candidate_hashes = {row["sequence_sha256"] for row in candidates}
    sequence_by_hash = {row["sequence_sha256"]: row for row in sequences}
    if not (
        len(candidates) == len(pairs) == len(cdrs) == EXPECTED_CANDIDATES
        and len(sequences) == len(cache) == EXPECTED_CANDIDATES + 1
    ):
        raise ValueError("Formal model-input row counts are incomplete")
    if len(sequence_by_hash) != EXPECTED_CANDIDATES + 1 or len({row["sequence_sha256"] for row in cache}) != EXPECTED_CANDIDATES + 1:
        raise ValueError("Formal model-input sequence hashes are not exact-unique")
    if candidate_hashes != {row["sequence_hash"] for row in cdrs}:
        raise ValueError("Candidate and CDR-mask sequence hash sets differ")
    if len(candidate_by_id) != EXPECTED_CANDIDATES or set(candidate_by_id) != set(pair_by_id):
        raise ValueError("Candidate and pair candidate-ID sets differ")
    for candidate_id, candidate in candidate_by_id.items():
        pair = pair_by_id[candidate_id]
        cdr = cdr_by_hash[candidate["sequence_sha256"]]
        sequence = candidate["vhh_seq"]
        if (
            sequence_sha256(sequence) != candidate["sequence_sha256"]
            or pair["vhh_sequence"] != sequence
            or pair["vhh_sequence_sha256"] != candidate["sequence_sha256"]
            or pair["teacher_split"] != candidate["formal_split"]
            or pair["parent_framework_cluster"] != candidate["parent_framework_cluster"]
            or cdr["vhh_seq"] != sequence
        ):
            raise ValueError(f"Candidate/pair/CDR identity closure failed for {candidate_id}")
    if candidate_hashes | {EXPECTED_TARGET_SEQUENCE_SHA256} != set(sequence_by_hash):
        raise ValueError("The 501-sequence manifest is not exactly Teacher500 plus fixed PVRIG")
    if set(sequence_by_hash) != {row["sequence_sha256"] for row in cache}:
        raise ValueError("Sequence and ESM2 cache hash sets differ")
    if len({row["model_sha256"] for row in cache}) != 1:
        raise ValueError("ESM2 cache manifest contains multiple model hashes")
    for digest, source in sequence_by_hash.items():
        if sequence_sha256(source["sequence"]) != digest:
            raise ValueError(f"Sequence manifest hash mismatch for {digest}")
    for row in pairs:
        if (
            row["target_sequence_sha256"] != EXPECTED_TARGET_SEQUENCE_SHA256
            or sequence_sha256(row["target_sequence"]) != EXPECTED_TARGET_SEQUENCE_SHA256
        ):
            raise ValueError(f"Pair target identity mismatch for {row['sample_id']}")

    shard_payloads: dict[Path, dict[str, torch.Tensor]] = {}
    failures: list[str] = []
    embedding_dims: set[int] = set()
    for row in cache:
        digest = row["sequence_sha256"]
        source = sequence_by_hash[digest]
        shard_path = cache_path.parent / row["shard_path"]
        try:
            if shard_path not in shard_payloads:
                shard_payloads[shard_path] = torch.load(shard_path, map_location="cpu", weights_only=True)
            tensor = shard_payloads[shard_path][row["shard_key"]]
            embedding_dims.add(int(tensor.shape[1]) if tensor.ndim == 2 else -1)
            if (
                tensor.ndim != 2
                or tensor.shape != (int(source["sequence_length"]), expected_dim)
                or tensor.dtype != torch.float16
                or int(row["sequence_length"]) != int(source["sequence_length"])
                or int(row["cached_length"]) != int(source["sequence_length"])
                or row["shard_key"] != digest
                or row["chain_type"] != source["chain_type"]
                or row["truncation_policy"] != "none"
            ):
                failures.append(digest)
        except (FileNotFoundError, KeyError, RuntimeError, TypeError, ValueError):
            failures.append(digest)
    if failures:
        raise ValueError(f"ESM2 cache tensor validation failed for {len(failures)} rows; first={failures[0]}")

    audit = {
        "status": "PASS_FORMAL_TEACHER500_MODEL_INPUTS_READY",
        "schema_version": "pvrig_formal_teacher500_model_input_validation_v1",
        "candidate_rows": len(candidates),
        "pair_rows": len(pairs),
        "cdr_mask_rows": len(cdrs),
        "sequence_rows": len(sequences),
        "cache_rows": len(cache),
        "cache_chain_type_counts": dict(sorted(Counter(row["chain_type"] for row in cache).items())),
        "cache_shard_count": len(shard_payloads),
        "cache_embedding_dimensions": sorted(embedding_dims),
        "target_sequence_sha256": EXPECTED_TARGET_SEQUENCE_SHA256,
        "sha256": {
            "candidate_csv": sha256_file(candidate_path),
            "pair_csv": sha256_file(pair_path),
            "cdr_masks": sha256_file(cdr_path),
            "sequence_manifest": sha256_file(sequence_path),
            "cache_manifest": sha256_file(cache_path),
            "cache_shards": {str(path): sha256_file(path) for path in sorted(shard_payloads)},
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json_atomic(outdir / "model_input_validation.json", audit)
    return audit


def run(
    selection: Path,
    target_fasta: Path,
    outdir: Path,
    model_path: Path,
    device: str = "cuda",
    batch_size: int = 64,
    attention_budget: int = 4_000_000,
    shard_size: int = 256,
    expected_selection_sha256: str | None = EXPECTED_SELECTION_SHA256,
    expected_target_sequence_sha256: str | None = EXPECTED_TARGET_SEQUENCE_SHA256,
    skip_embeddings: bool = False,
) -> dict[str, Any]:
    prepare_audit, sequence_rows = prepare_sequence_inputs(
        selection,
        target_fasta,
        outdir,
        expected_selection_sha256,
        expected_target_sequence_sha256,
    )
    if skip_embeddings:
        return prepare_audit
    cache_summary = build_resumable_cache(
        sequence_rows,
        model_path,
        outdir / "esm2_8m_cache",
        device,
        batch_size,
        attention_budget,
        shard_size,
    )
    validation = validate_model_inputs(outdir)
    validation["cache_generation"] = cache_summary
    write_json_atomic(outdir / "model_input_validation.json", validation)
    return validation


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--attention-budget", type=int, default=4_000_000)
    parser.add_argument("--shard-size", type=int, default=256)
    parser.add_argument("--expected-selection-sha256", default=EXPECTED_SELECTION_SHA256)
    parser.add_argument("--expected-target-sequence-sha256", default=EXPECTED_TARGET_SEQUENCE_SHA256)
    parser.add_argument("--skip-embeddings", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    result = run(
        selection=args.selection,
        target_fasta=args.target_fasta,
        outdir=args.outdir,
        model_path=args.model_path,
        device=args.device,
        batch_size=args.batch_size,
        attention_budget=args.attention_budget,
        shard_size=args.shard_size,
        expected_selection_sha256=args.expected_selection_sha256 or None,
        expected_target_sequence_sha256=args.expected_target_sequence_sha256 or None,
        skip_embeddings=args.skip_embeddings,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
