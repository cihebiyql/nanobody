#!/usr/bin/env python3
"""Prepare deterministic V2.5-compatible coarse-pose shard manifests.

The canonical10644 structure manifest is already hash-closed and label-free.
This adapter only renames ``monomer_path`` to the frozen V2.5 CLI field
``monomer_pdb`` and partitions rows; it never opens teacher labels or Docking
poses and it does not change the frozen 36D feature implementation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "pvrig_v2_11_canonical10644_label_free_structure_manifest_v1"
PLAN_SCHEMA = "pvrig_v2_11_canonical10644_coarse_pose_shard_plan_v1"
READY_STATUS = "PASS_CANONICAL10644_COARSE_POSE_SHARD_PLAN"
CLAIM_BOUNDARY = (
    "Deterministic partition of hash-closed label-free VHH monomer metadata for "
    "the frozen V2.5 300-pose x two-public-PVRIG-target feature extractor; no "
    "teacher label, candidate Docking pose, binding, affinity, or blocking truth."
)
REQUIRED_FIELDS = (
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "model_split",
    "asset_lane",
    "monomer_path",
    "monomer_sha256",
    "monomer_chain",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "source_manifest_sha256",
    "claim_boundary",
)
SHARD_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "model_split",
    "asset_lane",
    "monomer_pdb",
    "monomer_sha256",
    "monomer_chain",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "source_manifest_sha256",
    "claim_boundary",
)


class ShardPlanError(RuntimeError):
    """Fail-closed shard-plan error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ShardPlanError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_id_sha256(candidate_ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(candidate_ids) + "\n").encode("utf-8")).hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ShardPlanError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_file:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_structure_manifest(path: Path) -> list[dict[str, str]]:
    require_regular_file(path, "structure_manifest")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "missing_manifest_header")
        require(len(reader.fieldnames) == len(set(reader.fieldnames)), "duplicate_manifest_header")
        missing = [field for field in REQUIRED_FIELDS if field not in reader.fieldnames]
        require(not missing, f"missing_manifest_fields:{','.join(missing)}")
        rows = list(reader)
    require(bool(rows), "empty_structure_manifest")
    candidate_ids: set[str] = set()
    for row in rows:
        candidate_id = row["candidate_id"]
        require(bool(candidate_id), "empty_candidate_id")
        require(candidate_id not in candidate_ids, f"duplicate_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)
        require(row["schema_version"] == INPUT_SCHEMA, f"input_schema_mismatch:{candidate_id}")
        require(row["model_split"] in {"train", "development"}, f"invalid_model_split:{candidate_id}")
        for field in ("sequence_sha256", "monomer_sha256", "source_manifest_sha256"):
            value = row[field]
            require(len(value) == 64 and all(char in "0123456789abcdef" for char in value),
                    f"invalid_sha256:{candidate_id}:{field}")
        monomer = Path(row["monomer_path"])
        require(monomer.is_absolute(), f"monomer_path_not_absolute:{candidate_id}")
        require_regular_file(monomer, f"monomer:{candidate_id}")
        for number in (1, 2, 3):
            parts = row[f"cdr{number}_range"].split("-")
            require(len(parts) == 2 and all(part.isdigit() for part in parts),
                    f"invalid_cdr_range:{candidate_id}:cdr{number}")
            start, stop = map(int, parts)
            require(1 <= start <= stop, f"invalid_cdr_range_order:{candidate_id}:cdr{number}")
    return rows


def render_tsv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(SHARD_FIELDS), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def prepare(
    input_manifest: Path,
    expected_manifest_sha256: str,
    output_dir: Path,
    expected_rows: int,
    shard_count: int,
) -> dict[str, Any]:
    input_manifest = input_manifest.resolve()
    output_dir = output_dir.resolve()
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_dir_exists:{output_dir}")
    require(16 <= shard_count <= 32, f"shard_count_out_of_range:{shard_count}")
    require_regular_file(input_manifest, "structure_manifest")
    actual_manifest_sha256 = sha256_file(input_manifest)
    require(actual_manifest_sha256 == expected_manifest_sha256, "structure_manifest_sha256_mismatch")
    rows = read_structure_manifest(input_manifest)
    require(len(rows) == expected_rows, f"structure_manifest_row_count_invalid:{len(rows)}")
    require(shard_count <= len(rows), "more_shards_than_candidates")

    base_size, remainder = divmod(len(rows), shard_count)
    cursor = 0
    shard_records: list[dict[str, Any]] = []
    for shard_index in range(shard_count):
        size = base_size + (1 if shard_index < remainder else 0)
        selected = rows[cursor:cursor + size]
        cursor += size
        adapted = [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "model_split": row["model_split"],
                "asset_lane": row["asset_lane"],
                "monomer_pdb": row["monomer_path"],
                "monomer_sha256": row["monomer_sha256"],
                "monomer_chain": row["monomer_chain"],
                "cdr1_range": row["cdr1_range"],
                "cdr2_range": row["cdr2_range"],
                "cdr3_range": row["cdr3_range"],
                "source_manifest_sha256": row["source_manifest_sha256"],
                "claim_boundary": CLAIM_BOUNDARY,
            }
            for row in selected
        ]
        relative_path = Path("manifests") / f"shard_{shard_index:03d}.tsv"
        path = output_dir / relative_path
        atomic_write(path, render_tsv(adapted))
        candidate_ids = [row["candidate_id"] for row in selected]
        shard_records.append({
            "shard_id": f"shard_{shard_index:03d}",
            "shard_index": shard_index,
            "manifest_relative_path": relative_path.as_posix(),
            "manifest_sha256": sha256_file(path),
            "candidate_count": len(selected),
            "first_candidate_id": candidate_ids[0],
            "last_candidate_id": candidate_ids[-1],
            "ordered_candidate_id_sha256": ordered_id_sha256(candidate_ids),
        })
    require(cursor == len(rows), "internal_shard_partition_error")

    candidate_ids = [row["candidate_id"] for row in rows]
    plan = {
        "schema_version": PLAN_SCHEMA,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "source": {
            "structure_manifest_path": str(input_manifest),
            "structure_manifest_sha256": actual_manifest_sha256,
            "structure_manifest_schema": INPUT_SCHEMA,
        },
        "counts": {
            "candidates": len(rows),
            "shards": shard_count,
            "splits": dict(sorted(Counter(row["model_split"] for row in rows).items())),
            "asset_lanes": dict(sorted(Counter(row["asset_lane"] for row in rows).items())),
        },
        "ordered_candidate_id_sha256": ordered_id_sha256(candidate_ids),
        "partition": "contiguous_in_frozen_structure_manifest_order",
        "shards": shard_records,
        "invariants": {
            "candidate_ids_unique": True,
            "candidate_order_preserved": True,
            "shard_union_exact": True,
            "frozen_v2_5_feature_code_modified": False,
            "teacher_label_files_opened": 0,
            "candidate_docking_pose_files_opened": 0,
        },
    }
    plan_path = output_dir / "SHARD_PLAN.json"
    atomic_write(plan_path, (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "rows": len(rows),
        "shards": shard_count,
        "plan_path": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--input-manifest", type=Path, required=True)
    result.add_argument("--expected-manifest-sha256", required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--expected-rows", type=int, default=10644)
    result.add_argument("--shards", type=int, default=32)
    return result


def main() -> int:
    args = parser().parse_args()
    result = prepare(
        args.input_manifest,
        args.expected_manifest_sha256,
        args.output_dir,
        args.expected_rows,
        args.shards,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
