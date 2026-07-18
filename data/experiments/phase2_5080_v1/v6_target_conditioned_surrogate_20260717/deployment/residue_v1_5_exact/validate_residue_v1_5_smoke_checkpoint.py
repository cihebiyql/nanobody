#!/usr/bin/env python3
"""Fail-closed audit of V1.5 smoke checkpoints.

This deployment-only helper verifies that checkpoints contain trainable adapter
state only.  It never imports or modifies the frozen V1.5 implementation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "pvrig_v6_residue_v1_5_smoke_checkpoint_audit_v1"


class CheckpointAuditError(RuntimeError):
    """Raised when a smoke checkpoint violates the adapter-only contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckpointAuditError(message)


def regular_file(path: pathlib.Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"missing_or_symlink_{label}:{path}")


def classify_key(name: str) -> str:
    lowered = name.lower()
    if name.startswith("head."):
        return "head"
    if name.startswith("backbone.") and "lora_" in lowered:
        return "lora"
    return "base_or_unexpected"


def load_trainable_keys(path: pathlib.Path) -> list[str]:
    try:
        import torch
    except ImportError as error:  # pragma: no cover - Node1 environment gate
        raise CheckpointAuditError("torch_import_failed") from error
    payload = torch.load(path, map_location="cpu", weights_only=False)
    require(isinstance(payload, Mapping), f"checkpoint_payload_not_mapping:{path}")
    state = payload.get("trainable_state")
    require(isinstance(state, Mapping) and bool(state), f"missing_or_empty_trainable_state:{path}")
    keys = sorted(str(key) for key in state)
    require(len(keys) == len(state), f"non_string_or_duplicate_trainable_key:{path}")
    return keys


def peak_gpu_memory_mib(path: pathlib.Path) -> int:
    regular_file(path, "gpu_memory_csv")
    values: list[int] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == ["timestamp_utc", "memory_used_mib"], "gpu_memory_csv_header_invalid")
        for row in reader:
            try:
                value = int(row["memory_used_mib"])
            except (KeyError, TypeError, ValueError) as error:
                raise CheckpointAuditError("gpu_memory_csv_value_invalid") from error
            require(value >= 0, "gpu_memory_csv_value_negative")
            values.append(value)
    require(bool(values), "gpu_memory_csv_has_no_samples")
    return max(values)


def audit_checkpoints(
    output_dir: pathlib.Path,
    mode: str,
    gpu_memory_csv: pathlib.Path,
) -> dict[str, Any]:
    require(mode in {"frozen", "lora"}, f"invalid_mode:{mode}")
    require(output_dir.is_dir() and not output_dir.is_symlink(), f"output_dir_invalid:{output_dir}")
    final = output_dir / "adapter_head_final.pt"
    regular_file(final, "adapter_head_final")
    last_paths = sorted(output_dir.rglob("last.pt"))
    require(bool(last_paths), "last_checkpoint_missing")
    checkpoints = [final, *last_paths]
    require(len(checkpoints) >= 2, "checkpoint_count_below_two")

    records: list[dict[str, Any]] = []
    total_bytes = 0
    total_keys = total_head = total_lora = total_base = 0
    for path in checkpoints:
        regular_file(path, "checkpoint")
        keys = load_trainable_keys(path)
        classes = [classify_key(key) for key in keys]
        head_count = classes.count("head")
        lora_count = classes.count("lora")
        base_count = classes.count("base_or_unexpected")
        require(head_count > 0, f"checkpoint_missing_head:{path}")
        require(base_count == 0, f"checkpoint_contains_base_or_unexpected:{path}")
        if mode == "frozen":
            require(lora_count == 0, f"frozen_checkpoint_contains_lora:{path}")
            require(head_count == len(keys), f"frozen_checkpoint_not_head_only:{path}")
        else:
            require(lora_count > 0, f"lora_checkpoint_missing_lora:{path}")
            require(head_count + lora_count == len(keys), f"lora_checkpoint_contains_non_adapter:{path}")
        size = path.stat().st_size
        require(size > 0, f"checkpoint_empty:{path}")
        total_bytes += size
        total_keys += len(keys)
        total_head += head_count
        total_lora += lora_count
        total_base += base_count
        records.append(
            {
                "relative_path": str(path.relative_to(output_dir)),
                "bytes": size,
                "trainable_key_count": len(keys),
                "head_key_count": head_count,
                "lora_key_count": lora_count,
                "base_or_unexpected_key_count": base_count,
            }
        )

    peak = peak_gpu_memory_mib(gpu_memory_csv)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_ADAPTER_ONLY_CHECKPOINT_AUDIT",
        "mode": mode,
        "output_dir": str(output_dir),
        "checkpoint_count": len(checkpoints),
        "checkpoint_total_bytes": total_bytes,
        "trainable_key_count": total_keys,
        "head_key_count": total_head,
        "lora_key_count": total_lora,
        "base_or_unexpected_key_count": total_base,
        "peak_gpu_memory_mib": peak,
        "gpu_memory_sample_file": str(gpu_memory_csv),
        "checkpoints": records,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def atomic_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--mode", required=True, choices=("frozen", "lora"))
    parser.add_argument("--gpu-memory-csv", required=True, type=pathlib.Path)
    parser.add_argument("--audit-json", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = audit_checkpoints(args.output_dir, args.mode, args.gpu_memory_csv)
    atomic_json(args.audit_json, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
