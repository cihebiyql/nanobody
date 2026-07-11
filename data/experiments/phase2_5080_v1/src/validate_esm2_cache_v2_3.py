#!/usr/bin/env python3
"""Validate every frozen ESM2 cache row, shard key, dtype, and tensor shape."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_MANIFEST = EXP_DIR / "prepared" / "esm2_8m_v2_3_cache" / "manifest.csv"
DEFAULT_CONFIG = EXP_DIR / "configs" / "phase2_v2_3_5080_16gb.json"
DEFAULT_SUMMARY = EXP_DIR / "audits" / "esm2_cache_validation_v2_3.json"
DEFAULT_REPORT = EXP_DIR / "audits" / "ESM2_CACHE_VALIDATION_V2_3.md"
REQUIRED_COLUMNS = {
    "model_path",
    "model_sha256",
    "sequence_sha256",
    "sequence_length",
    "cached_length",
    "truncation_policy",
    "chain_type",
    "shard_path",
    "shard_key",
}
ALLOWED_CHAIN_TYPES = {"vhh", "antigen", "mixed"}


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _positive_int(raw: str, field: str, digest: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{digest}: {field} is not an integer: {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{digest}: {field} must be positive, got {value}")
    return value


def validate_cache(manifest_path: Path, expected_dim: int = 320) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    if expected_dim <= 0:
        raise ValueError("expected_dim must be positive")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing ESM2 cache manifest: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Manifest missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("ESM2 cache manifest is empty")

    seen_hashes: set[str] = set()
    refs_by_shard: dict[Path, list[tuple[dict[str, str], int]]] = defaultdict(list)
    chain_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    model_hashes: set[str] = set()
    model_paths: set[str] = set()
    total_cached_residues = 0
    max_sequence_length = 0
    max_cached_length = 0

    for index, row in enumerate(rows, start=2):
        digest = row["sequence_sha256"].strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"manifest line {index}: invalid sequence_sha256 {digest!r}")
        if digest in seen_hashes:
            raise ValueError(f"manifest line {index}: duplicate sequence_sha256 {digest}")
        seen_hashes.add(digest)

        sequence_length = _positive_int(row["sequence_length"], "sequence_length", digest)
        cached_length = _positive_int(row["cached_length"], "cached_length", digest)
        if cached_length > sequence_length:
            raise ValueError(f"{digest}: cached_length {cached_length} exceeds sequence_length {sequence_length}")
        policy = row["truncation_policy"].strip()
        expected_policy = "none" if cached_length == sequence_length else f"prefix_{cached_length}"
        if policy != expected_policy:
            raise ValueError(f"{digest}: truncation_policy {policy!r} != expected {expected_policy!r}")
        chain_type = row["chain_type"].strip()
        if chain_type not in ALLOWED_CHAIN_TYPES:
            raise ValueError(f"{digest}: unsupported chain_type {chain_type!r}")
        if not row["model_sha256"].strip() or not row["model_path"].strip():
            raise ValueError(f"{digest}: model_path/model_sha256 must be non-empty")

        shard_rel = Path(row["shard_path"].strip())
        if shard_rel.is_absolute() or ".." in shard_rel.parts:
            raise ValueError(f"{digest}: shard_path must remain inside the cache directory: {shard_rel}")
        shard_path = (manifest_path.parent / shard_rel).resolve()
        if not shard_path.exists():
            raise FileNotFoundError(f"{digest}: missing shard {shard_path}")
        shard_key = row["shard_key"].strip()
        if not shard_key:
            raise ValueError(f"{digest}: empty shard_key")

        refs_by_shard[shard_path].append((row, cached_length))
        chain_counts[chain_type] += 1
        policy_counts[policy] += 1
        model_hashes.add(row["model_sha256"].strip())
        model_paths.add(row["model_path"].strip())
        total_cached_residues += cached_length
        max_sequence_length = max(max_sequence_length, sequence_length)
        max_cached_length = max(max_cached_length, cached_length)

    dtype_counts: Counter[str] = Counter()
    orphan_keys = 0
    referenced_keys = 0
    for shard_path, refs in sorted(refs_by_shard.items(), key=lambda item: str(item[0])):
        payload = torch.load(shard_path, map_location="cpu", weights_only=False)
        if not isinstance(payload, dict):
            raise ValueError(f"Shard is not a dictionary: {shard_path}")
        expected_keys = {row["shard_key"].strip() for row, _ in refs}
        orphan_keys += len(set(payload) - expected_keys)
        for row, cached_length in refs:
            digest = row["sequence_sha256"].strip().lower()
            key = row["shard_key"].strip()
            if key not in payload:
                raise KeyError(f"{digest}: shard key {key!r} missing from {shard_path}")
            tensor = payload[key]
            if not isinstance(tensor, torch.Tensor):
                raise TypeError(f"{digest}: shard value is not a tensor")
            if tensor.ndim != 2 or tuple(tensor.shape) != (cached_length, expected_dim):
                raise ValueError(
                    f"{digest}: tensor shape {tuple(tensor.shape)} != ({cached_length}, {expected_dim})"
                )
            if not tensor.is_floating_point():
                raise ValueError(f"{digest}: tensor dtype must be floating point, got {tensor.dtype}")
            if not torch.isfinite(tensor).all():
                raise ValueError(f"{digest}: tensor contains NaN or infinity")
            dtype_counts[str(tensor.dtype)] += 1
            referenced_keys += 1
        del payload

    return {
        "status": "PASS",
        "manifest": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "manifest_rows": len(rows),
        "unique_sequence_hashes": len(seen_hashes),
        "validated_tensor_keys": referenced_keys,
        "shard_count": len(refs_by_shard),
        "orphan_shard_keys": orphan_keys,
        "expected_embedding_dim": expected_dim,
        "dtype_counts": dict(sorted(dtype_counts.items())),
        "chain_type_counts": dict(sorted(chain_counts.items())),
        "truncation_policy_counts": dict(sorted(policy_counts.items())),
        "model_sha256_values": sorted(model_hashes),
        "model_paths": sorted(model_paths),
        "total_cached_residues": total_cached_residues,
        "max_sequence_length": max_sequence_length,
        "max_cached_length": max_cached_length,
    }


def write_report(summary: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Frozen ESM2 Cache Validation V2.3",
        "",
        f"- Status: **{summary['status']}**",
        f"- Manifest rows / unique hashes: {summary['manifest_rows']} / {summary['unique_sequence_hashes']}",
        f"- Validated tensor keys: {summary['validated_tensor_keys']}",
        f"- Shards: {summary['shard_count']}",
        f"- Embedding dimension: {summary['expected_embedding_dim']}",
        f"- Dtypes: `{json.dumps(summary['dtype_counts'], sort_keys=True)}`",
        f"- Chain types: `{json.dumps(summary['chain_type_counts'], sort_keys=True)}`",
        f"- Truncation policies: `{json.dumps(summary['truncation_policy_counts'], sort_keys=True)}`",
        f"- Orphan shard keys: {summary['orphan_shard_keys']}",
        f"- Manifest SHA256: `{summary['manifest_sha256']}`",
        "",
        "Every manifest row was resolved to a finite floating-point tensor with the declared cached length and the expected 320-dimensional ESM2 representation.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-dim", type=int, default=320)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-input-validation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = validate_cache(args.manifest, args.expected_dim)
    if not args.skip_input_validation:
        from train_phase2_v2_3 import load_config, validate_inputs

        paths = validate_inputs(load_config(args.config))
        summary["strict_input_validation"] = "PASS"
        summary["strict_inputs"] = {name: str(path) for name, path in paths.items()}
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(summary, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
