#!/usr/bin/env python3
"""Shared fail-closed utilities for the frozen V2.5 execution adapter."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ExecutionContractError(RuntimeError):
    """Raised when a frozen execution boundary is violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutionContractError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"json_file_required:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"invalid_json:{path}") from exc
    require(isinstance(value, dict), f"json_object_required:{path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_file_required:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def finite_float(row: Mapping[str, Any], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionContractError(f"invalid_numeric:{field}") from exc
    require(math.isfinite(value), f"nonfinite_numeric:{field}")
    return value


def unique_by(rows: Sequence[Mapping[str, Any]], field: str, context: str) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = str(row[field])
        require(key and key not in output, f"duplicate_{context}:{key}")
        output[key] = row
    return output


def scan_zero_access_counts(value: Any, *, context: str) -> None:
    """Require every explicitly recorded protected-access counter to remain zero."""
    protected = {
        "sealed_evaluation_access_count",
        "prediction_metrics_access_count",
        "v4_f_test32_access_count",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in protected:
                require(int(item) == 0, f"protected_access_nonzero:{context}:{key}:{item}")
            scan_zero_access_counts(item, context=context)
    elif isinstance(value, list):
        for item in value:
            scan_zero_access_counts(item, context=context)


def verify_named_hashes(root: Path, specifications: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, specification in specifications.items():
        path = root / str(specification["filename"])
        observed = sha256_file(path)
        expected = str(specification["sha256"])
        require(observed == expected, f"input_hash_mismatch:{name}:{observed}:{expected}")
        hashes[name] = observed
    return hashes


def assert_exact_model_matrix(contract: Mapping[str, Any]) -> None:
    expected = [
        "D_ONLY_FROZEN_BASE",
        "M2_C2_CONVEX",
        "M2_D_CONVEX",
        "M2_D_C2_CONVEX",
        "M2_D_C2_RELIABILITY_CONVEX",
        "D_C2_CONTACT_RELIABILITY_HIST_GBDT",
    ]
    observed = [str(row["model_id"]) for row in contract["formal_model_matrix"]]
    require(observed == expected, f"formal_model_matrix_mismatch:{observed}")


def selected_c2_alpha_rows(rows: Iterable[Mapping[str, Any]]) -> dict[int, float]:
    output: dict[int, float] = {}
    for row in rows:
        if str(row.get("selected", "")).lower() != "true":
            continue
        fold = int(row["outer_fold"])
        require(fold not in output, f"duplicate_selected_c2_alpha:{fold}")
        output[fold] = finite_float(row, "alpha")
    require(set(output) == set(range(5)), f"selected_c2_alpha_fold_closure:{sorted(output)}")
    return output
