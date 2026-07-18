#!/usr/bin/env python3
"""Resumable ESM residue/CDR pooling cache for PVRIG V6."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path: Path, max_rows: int = 0) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return rows[:max_rows] if max_rows else rows


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def model_manifest(model_path: Path) -> list[dict[str, object]]:
    names = {
        "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
        "vocab.txt", "merges.txt", "vocab.json", "model.safetensors", "pytorch_model.bin",
        "model.safetensors.index.json", "pytorch_model.bin.index.json",
    }
    files = []
    for path in sorted(candidate for candidate in model_path.rglob("*") if candidate.is_file()):
        if path.name in names or path.suffix in {".safetensors", ".bin", ".pth"}:
            files.append({
                "relative_path": str(path.relative_to(model_path)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    require(any(item["relative_path"] == "config.json" for item in files), "model_config_missing")
    require(any(str(item["relative_path"]).endswith((".safetensors", ".bin", ".pth")) for item in files), "model_weights_missing")
    return files


def cdr_bounds(sequence: str, cdr: str, candidate_id: str) -> tuple[int, int]:
    start = sequence.find(cdr)
    require(start >= 0, f"cdr_not_found:{candidate_id}:{cdr}")
    require(sequence.find(cdr, start + 1) < 0, f"cdr_not_unique:{candidate_id}:{cdr}")
    return start, start + len(cdr)


def load_model(model_path: Path, device: str, dtype: str):
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    torch_dtype = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}[dtype]
    model = AutoModel.from_pretrained(
        model_path,
        local_files_only=True,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
    ).eval().to(device)
    return tokenizer, model


@torch.inference_mode()
def embed_rows(rows: list[dict[str, str]], tokenizer, model, device: str) -> torch.Tensor:
    sequences = [row["sequence"] for row in rows]
    encoded = tokenizer(sequences, padding=True, return_tensors="pt", add_special_tokens=True)
    encoded = {key: value.to(device) for key, value in encoded.items()}
    hidden = model(**encoded).last_hidden_state
    outputs = []
    for index, row in enumerate(rows):
        length = len(row["sequence"])
        residue = hidden[index, 1 : length + 1].float()
        require(residue.shape[0] == length, f"token_length_mismatch:{row['candidate_id']}")
        pooled = [residue.mean(0)]
        for key in ("cdr1", "cdr2", "cdr3"):
            start, end = cdr_bounds(row["sequence"], row[key], row["candidate_id"])
            pooled.append(residue[start:end].mean(0))
        outputs.append(torch.cat(pooled, dim=0).cpu().to(torch.float16))
    return torch.stack(outputs)


def main(args: argparse.Namespace) -> dict[str, object]:
    rows = read_rows(args.input, args.max_rows)
    require(rows, "empty_input")
    require(len({row["candidate_id"] for row in rows}) == len(rows), "duplicate_candidate")
    for row in rows:
        require(hashlib.sha256(row["sequence"].encode()).hexdigest() == row["sequence_sha256"], f"sequence_hash:{row['candidate_id']}")
        for key in ("cdr1", "cdr2", "cdr3"):
            require(bool(row[key]), f"empty_{key}:{row['candidate_id']}")
            cdr_bounds(row["sequence"], row[key], row["candidate_id"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir = args.output_dir / "shards"
    shard_dir.mkdir(exist_ok=True)
    artifacts = model_manifest(args.model_path)
    model_artifact_fingerprint = hashlib.sha256(json.dumps(artifacts, sort_keys=True).encode()).hexdigest()
    input_sha256 = sha256_file(args.input)
    existing_receipt = args.output_dir / "embedding_cache_receipt.json"
    if existing_receipt.exists():
        receipt = json.loads(existing_receipt.read_text())
        require(receipt.get("input_sha256") == input_sha256, "existing_receipt_input_mismatch")
        require(receipt.get("model_artifact_fingerprint") == model_artifact_fingerprint, "existing_receipt_model_mismatch")
        require(int(receipt.get("rows", -1)) == len(rows), "existing_receipt_row_mismatch")
        for item in receipt.get("shards", []):
            path = Path(item["path"])
            if not path.exists():
                path = shard_dir / path.name
            require(path.exists() and sha256_file(path) == item["sha256"], f"existing_receipt_shard_mismatch:{path}")
        require(sum(int(item["rows"]) for item in receipt.get("shards", [])) == len(rows), "existing_receipt_shard_rows")
        return receipt
    tokenizer, model = load_model(args.model_path, args.device, args.dtype)
    hidden_size = int(model.config.hidden_size)
    model_config_sha = sha256_file(args.model_path / "config.json")
    shard_receipts = []
    for shard_index, start in enumerate(range(0, len(rows), args.shard_size)):
        shard_rows = rows[start : start + args.shard_size]
        path = shard_dir / f"shard_{shard_index:05d}.pt"
        ids = [row["candidate_id"] for row in shard_rows]
        hashes = [row["sequence_sha256"] for row in shard_rows]
        expected_meta = {
            "candidate_ids": ids,
            "sequence_sha256": hashes,
            "hidden_size": hidden_size,
            "pool_count": 4,
            "model_config_sha256": model_config_sha,
            "model_artifact_fingerprint": model_artifact_fingerprint,
        }
        if path.exists():
            payload = torch.load(path, map_location="cpu", weights_only=False)
            require(payload["metadata"] == expected_meta, f"existing_shard_mismatch:{path}")
        else:
            values = []
            for batch_start in range(0, len(shard_rows), args.batch_size):
                values.append(embed_rows(shard_rows[batch_start:batch_start + args.batch_size], tokenizer, model, args.device))
            payload = {"metadata": expected_meta, "embeddings": torch.cat(values, dim=0)}
            temporary = path.with_suffix(".tmp")
            torch.save(payload, temporary)
            temporary.replace(path)
        require(tuple(payload["embeddings"].shape) == (len(shard_rows), hidden_size * 4), f"shard_shape:{path}")
        shard_receipts.append({"path": str(path), "rows": len(shard_rows), "sha256": sha256_file(path)})

    receipt = {
        "schema_version": "pvrig_v6_esm_embedding_cache_v1",
        "status": "PASS_V6_ESM_EMBEDDING_CACHE_COMPLETE",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input": str(args.input),
        "input_sha256": input_sha256,
        "model_path": str(args.model_path),
        "model_config_sha256": model_config_sha,
        "model_artifact_fingerprint": model_artifact_fingerprint,
        "model_artifacts": artifacts,
        "rows": len(rows),
        "hidden_size": hidden_size,
        "embedding_dimension": hidden_size * 4,
        "dtype": "float16",
        "shards": shard_receipts,
    }
    receipt_path = args.output_dir / "embedding_cache_receipt.json"
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(receipt_path)
    return receipt


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--model-path", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--dtype", choices=("float32", "float16", "bfloat16"), default="bfloat16")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--shard-size", type=int, default=128)
    p.add_argument("--max-rows", type=int, default=0)
    return p


if __name__ == "__main__":
    print(json.dumps(main(parser().parse_args()), indent=2, sort_keys=True))
