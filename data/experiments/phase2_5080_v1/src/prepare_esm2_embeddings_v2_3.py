#!/usr/bin/env python3
"""Prepare an offline, sharded ESM2-8M sequence embedding cache for Phase 2 V2.3.

The cache is sequence-identity based: each unique cleaned amino-acid sequence is
keyed by SHA256 and stored once, even if it appears in multiple strict site,
pair, ranking, or contact manifests.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_SITE_MANIFEST = EXP_DIR / "data_splits" / "zym_site_split_manifest_v2_clustered.csv"
DEFAULT_PAIR_MANIFEST = EXP_DIR / "data_splits" / "pair_binding_split_v2_clustered.csv"
DEFAULT_RANKING_MANIFEST = EXP_DIR / "data_splits" / "pair_ranking_triplets_v2_clustered.csv"
DEFAULT_CONTACT_MAPS = EXP_DIR / "prepared" / "structure_contact_maps_v3_clustered.jsonl"
DEFAULT_OUTPUT_DIR = EXP_DIR / "prepared" / "esm2_8m_v2_3_cache"
DEFAULT_INFERENCE_CANDIDATES = DATA_ROOT / "model_data" / "mvp_candidates_v0.csv"
DEFAULT_TARGET_FASTA = DATA_ROOT / "model_data" / "pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_MODEL_PATH = Path(os.environ.get("ESM2_8M_LOCAL_MODEL", "models/esm2_t6_8M_UR50D"))
DEFAULT_MAX_RESIDUES = 1024
AA_PATTERN = re.compile(r"^[A-Z*.-]+$")
MANIFEST_COLUMNS = [
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


@dataclass(frozen=True)
class SequenceRecord:
    sequence_sha256: str
    sequence: str
    chain_type: str
    original_length: int | None = None

    @property
    def source_length(self) -> int:
        return self.original_length if self.original_length is not None else len(self.sequence)


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
    return text


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


def apply_prefix_length_policy(records: Sequence[SequenceRecord], max_residues: int) -> list[SequenceRecord]:
    if max_residues <= 0:
        raise ValueError("max_residues must be positive")
    return [
        SequenceRecord(
            sequence_sha256=record.sequence_sha256,
            sequence=record.sequence[:max_residues],
            chain_type=record.chain_type,
            original_length=record.source_length,
        )
        for record in records
    ]


def add_sequence(records: dict[str, SequenceRecord], sequence: Any, chain_type: str) -> None:
    cleaned = clean_sequence(sequence)
    if not cleaned:
        return
    if not AA_PATTERN.match(cleaned):
        raise ValueError(f"Invalid sequence characters for {chain_type}: {cleaned[:40]!r}")
    digest = sequence_sha256(cleaned)
    existing = records.get(digest)
    if existing is None:
        records[digest] = SequenceRecord(digest, cleaned, chain_type)
        return
    if existing.sequence != cleaned:
        raise ValueError(f"SHA256 collision or inconsistent sequence for {digest}")
    if existing.chain_type != chain_type and existing.chain_type != "mixed":
        records[digest] = SequenceRecord(digest, cleaned, "mixed")


def collect_unique_sequences(
    site_manifest: Path = DEFAULT_SITE_MANIFEST,
    pair_manifest: Path = DEFAULT_PAIR_MANIFEST,
    ranking_manifest: Path = DEFAULT_RANKING_MANIFEST,
    contact_maps: Path = DEFAULT_CONTACT_MAPS,
    inference_candidates: Path | None = None,
    target_fasta: Path | None = None,
    generic_binding_csv: Path | None = None,
) -> list[SequenceRecord]:
    records: dict[str, SequenceRecord] = {}
    for path in (site_manifest, pair_manifest):
        if not path.exists():
            continue
        for row in pd.read_csv(path, usecols=lambda name: name in {"vhh_seq", "antigen_seq"}).to_dict("records"):
            add_sequence(records, row.get("vhh_seq"), "vhh")
            add_sequence(records, row.get("antigen_seq"), "antigen")

    if ranking_manifest.exists():
        cols = {
            "positive_vhh_seq",
            "positive_antigen_seq",
            "negative_vhh_seq",
            "negative_antigen_seq",
        }
        for row in pd.read_csv(ranking_manifest, usecols=lambda name: name in cols).to_dict("records"):
            add_sequence(records, row.get("positive_vhh_seq"), "vhh")
            add_sequence(records, row.get("negative_vhh_seq"), "vhh")
            add_sequence(records, row.get("positive_antigen_seq"), "antigen")
            add_sequence(records, row.get("negative_antigen_seq"), "antigen")

    if contact_maps.exists():
        with contact_maps.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                try:
                    add_sequence(records, row.get("vhh_seq"), "vhh")
                    add_sequence(records, row.get("antigen_seq"), "antigen")
                except ValueError as exc:
                    raise ValueError(f"{contact_maps}:{line_number}: {exc}") from exc

    if inference_candidates is not None and inference_candidates.exists():
        for row in pd.read_csv(inference_candidates, usecols=lambda name: name == "vhh_seq").to_dict("records"):
            add_sequence(records, row.get("vhh_seq"), "vhh")
    if target_fasta is not None and target_fasta.exists():
        sequence = "".join(
            line.strip()
            for line in target_fasta.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(">")
        )
        add_sequence(records, sequence, "antigen")
    if generic_binding_csv is not None and generic_binding_csv.exists():
        columns = {"vhh_sequence", "target_sequence"}
        for row in pd.read_csv(
            generic_binding_csv,
            usecols=lambda name: name in columns,
        ).to_dict("records"):
            add_sequence(records, row.get("vhh_sequence"), "vhh")
            add_sequence(records, row.get("target_sequence"), "antigen")

    return sorted(records.values(), key=lambda item: (item.chain_type, item.sequence_sha256))


def compute_model_sha256(model_path: Path) -> str:
    if not model_path.exists():
        raise FileNotFoundError(f"Local model path does not exist: {model_path}")
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


def load_existing_manifest(manifest_path: Path, model_sha256: str) -> dict[str, dict[str, str]]:
    if not manifest_path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(MANIFEST_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Existing manifest is missing columns: {sorted(missing)}")
        for row in reader:
            if row["model_sha256"] != model_sha256:
                continue
            shard_path = manifest_path.parent / row["shard_path"]
            if not shard_path.exists():
                continue
            rows[row["sequence_sha256"]] = row
    return rows


def next_shard_index(existing_rows: Iterable[dict[str, str]]) -> int:
    highest = -1
    for row in existing_rows:
        match = re.search(r"shard_(\d+)\.pt$", row.get("shard_path", ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def shard_records(records: Sequence[SequenceRecord], shard_size: int) -> list[list[SequenceRecord]]:
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    return [list(records[index : index + shard_size]) for index in range(0, len(records), shard_size)]


def dynamic_attention_batches(
    records: Sequence[SequenceRecord],
    max_batch_size: int,
    attention_budget: int,
) -> list[list[SequenceRecord]]:
    if max_batch_size <= 0 or attention_budget <= 0:
        raise ValueError("max_batch_size and attention_budget must be positive")
    batches: list[list[SequenceRecord]] = []
    current: list[SequenceRecord] = []
    current_max = 0
    for record in records:
        proposed_max = max(current_max, len(record.sequence))
        exceeds = current and (len(current) + 1) * proposed_max * proposed_max > attention_budget
        if len(current) >= max_batch_size or exceeds:
            batches.append(current)
            current = []
            current_max = 0
        current.append(record)
        current_max = max(current_max, len(record.sequence))
    if current:
        batches.append(current)
    return batches


def write_manifest_atomic(manifest_path: Path, rows: Sequence[dict[str, Any]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=manifest_path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (str(item["chain_type"]), str(item["sequence_sha256"]))):
            writer.writerow({column: row[column] for column in MANIFEST_COLUMNS})
        tmp_path = Path(tmp.name)
    tmp_path.replace(manifest_path)


def append_sharded_embeddings(
    output_dir: Path,
    manifest_path: Path,
    records: Sequence[SequenceRecord],
    embeddings: dict[str, torch.Tensor],
    model_path: Path,
    model_sha256: str,
    existing_rows: dict[str, dict[str, str]] | None = None,
    shard_size: int = 512,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_rows = dict(existing_rows or {})
    rows: list[dict[str, Any]] = list(existing_rows.values())
    shard_index = next_shard_index(existing_rows.values())

    for shard in shard_records(list(records), shard_size):
        shard_name = f"shard_{shard_index:05d}.pt"
        shard_path = output_dir / shard_name
        payload: dict[str, torch.Tensor] = {}
        for record in shard:
            tensor = embeddings[record.sequence_sha256].detach().cpu().to(torch.float16).contiguous()
            if tensor.ndim != 2 or tensor.shape[0] != len(record.sequence):
                raise ValueError(
                    f"Embedding shape mismatch for {record.sequence_sha256}: "
                    f"expected first dimension {len(record.sequence)}, got {tuple(tensor.shape)}"
                )
            key = record.sequence_sha256
            payload[key] = tensor
            rows.append(
                {
                    "model_path": str(model_path),
                    "model_sha256": model_sha256,
                    "sequence_sha256": record.sequence_sha256,
                    "sequence_length": record.source_length,
                    "cached_length": len(record.sequence),
                    "truncation_policy": "none" if record.source_length == len(record.sequence) else f"prefix_{len(record.sequence)}",
                    "chain_type": record.chain_type,
                    "shard_path": shard_name,
                    "shard_key": key,
                }
            )
        torch.save(payload, shard_path)
        shard_index += 1

    write_manifest_atomic(manifest_path, rows)
    return rows


def load_local_esm2(model_path: Path) -> tuple[Any, Any]:
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModel.from_pretrained(str(model_path), local_files_only=True)
    model.eval()
    return tokenizer, model


def embed_batch(
    records: Sequence[SequenceRecord],
    tokenizer: Any,
    model: Any,
    device: torch.device,
    max_residues: int,
) -> dict[str, torch.Tensor]:
    for record in records:
        if len(record.sequence) > max_residues:
            raise ValueError(
                f"Sequence {record.sequence_sha256} length {len(record.sequence)} exceeds "
                f"max_residues={max_residues}; apply the explicit prefix policy before embedding"
            )
    encoded = tokenizer(
        [record.sequence for record in records],
        return_tensors="pt",
        padding=True,
        truncation=False,
        return_special_tokens_mask=True,
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    model.to(device)
    with torch.inference_mode():
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            outputs = model(input_ids=encoded["input_ids"], attention_mask=encoded.get("attention_mask"))
    hidden = outputs.last_hidden_state
    result: dict[str, torch.Tensor] = {}
    attention = encoded.get("attention_mask", torch.ones_like(encoded["input_ids"]))
    special = encoded["special_tokens_mask"]
    for index, record in enumerate(records):
        residue_mask = (attention[index] == 1) & (special[index] == 0)
        residue_embedding = hidden[index][residue_mask].detach().to(torch.float16).cpu().contiguous()
        if residue_embedding.shape[0] != len(record.sequence):
            raise ValueError(
                f"Tokenizer/model special-token alignment mismatch for {record.sequence_sha256}: "
                f"got {residue_embedding.shape[0]} residues for sequence length {len(record.sequence)}"
            )
        result[record.sequence_sha256] = residue_embedding
    return result


def build_cache(
    model_path: Path,
    output_dir: Path,
    site_manifest: Path,
    pair_manifest: Path,
    ranking_manifest: Path,
    contact_maps: Path,
    inference_candidates: Path | None,
    target_fasta: Path | None,
    batch_size: int,
    attention_budget: int,
    shard_size: int,
    max_residues: int,
    device_name: str,
    generic_binding_csv: Path | None = None,
) -> dict[str, int | str]:
    if device_name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(device_name)
    model_sha = compute_model_sha256(model_path)
    manifest_path = output_dir / "manifest.csv"
    source_records = collect_unique_sequences(
        site_manifest,
        pair_manifest,
        ranking_manifest,
        contact_maps,
        inference_candidates,
        target_fasta,
        generic_binding_csv,
    )
    all_records = apply_prefix_length_policy(source_records, max_residues)
    truncated_count = sum(record.source_length > len(record.sequence) for record in all_records)
    existing = load_existing_manifest(manifest_path, model_sha)
    missing = sorted(
        (record for record in all_records if record.sequence_sha256 not in existing),
        key=lambda record: (len(record.sequence), record.chain_type, record.sequence_sha256),
    )
    if not missing:
        return {
            "total_sequences": len(all_records),
            "new_sequences": 0,
            "truncated_sequences": truncated_count,
            "manifest": str(manifest_path),
        }

    tokenizer, model = load_local_esm2(model_path)
    new_rows: list[dict[str, str]] = []
    shard_index = next_shard_index(existing.values())
    for start in range(0, len(missing), shard_size):
        shard_records_slice = missing[start : start + shard_size]
        embeddings: dict[str, torch.Tensor] = {}
        for batch in dynamic_attention_batches(shard_records_slice, batch_size, attention_budget):
            embeddings.update(embed_batch(batch, tokenizer, model, device, max_residues))
        shard_name = f"shard_{shard_index:05d}.pt"
        shard_path = output_dir / shard_name
        output_dir.mkdir(parents=True, exist_ok=True)
        torch.save({record.sequence_sha256: embeddings[record.sequence_sha256] for record in shard_records_slice}, shard_path)
        for record in shard_records_slice:
            new_rows.append(
                {
                    "model_path": str(model_path),
                    "model_sha256": model_sha,
                    "sequence_sha256": record.sequence_sha256,
                    "sequence_length": str(record.source_length),
                    "cached_length": str(len(record.sequence)),
                    "truncation_policy": "none" if record.source_length == len(record.sequence) else f"prefix_{len(record.sequence)}",
                    "chain_type": record.chain_type,
                    "shard_path": shard_name,
                    "shard_key": record.sequence_sha256,
                }
            )
        shard_index += 1
    write_manifest_atomic(manifest_path, list(existing.values()) + new_rows)
    return {
        "total_sequences": len(all_records),
        "new_sequences": len(missing),
        "truncated_sequences": truncated_count,
        "manifest": str(manifest_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH, help="Frozen local ESM2-8M model directory/file")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--site-manifest", type=Path, default=DEFAULT_SITE_MANIFEST)
    parser.add_argument("--pair-manifest", type=Path, default=DEFAULT_PAIR_MANIFEST)
    parser.add_argument("--ranking-manifest", type=Path, default=DEFAULT_RANKING_MANIFEST)
    parser.add_argument("--contact-maps", type=Path, default=DEFAULT_CONTACT_MAPS)
    parser.add_argument("--inference-candidates", type=Path, default=DEFAULT_INFERENCE_CANDIDATES)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET_FASTA)
    parser.add_argument(
        "--generic-binding-csv",
        type=Path,
        help="Optional real-label binding CSV with vhh_sequence and target_sequence columns.",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--attention-budget",
        type=int,
        default=1_000_000,
        help="Maximum batch_size * padded_length^2; long sequences automatically use smaller batches.",
    )
    parser.add_argument("--shard-size", type=int, default=512)
    parser.add_argument(
        "--max-residues",
        type=int,
        default=DEFAULT_MAX_RESIDUES,
        help="Explicit prefix-cache length; full-sequence hashes and original lengths remain in the manifest.",
    )
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_cache(
        model_path=args.model_path,
        output_dir=args.output_dir,
        site_manifest=args.site_manifest,
        pair_manifest=args.pair_manifest,
        ranking_manifest=args.ranking_manifest,
        contact_maps=args.contact_maps,
        inference_candidates=args.inference_candidates,
        target_fasta=args.target_fasta,
        batch_size=args.batch_size,
        attention_budget=args.attention_budget,
        shard_size=args.shard_size,
        max_residues=args.max_residues,
        device_name=args.device,
        generic_binding_csv=args.generic_binding_csv,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
