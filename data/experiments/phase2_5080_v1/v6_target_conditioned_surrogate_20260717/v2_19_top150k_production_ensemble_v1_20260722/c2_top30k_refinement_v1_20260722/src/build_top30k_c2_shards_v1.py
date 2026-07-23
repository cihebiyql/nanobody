#!/usr/bin/env python3
"""Project the frozen preliminary Top30K into hash-closed C2 shard manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "pvrig_v2_19_top30k_c2_shard_plan_v1"
STATUS = "PASS_TOP30K_LABEL_FREE_C2_SHARD_PLAN"
CLAIM = "Label-free NBB2 monomers for fixed-target coarse-pose features; no Docking pose, teacher, binding, or experimental truth."
FORBIDDEN = ("truth", "teacher", "docking_score", "haddock", "occlusion", "experimental")
FIELDS = (
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "monomer_pdb",
    "monomer_sha256", "cdr1_range", "cdr2_range", "cdr3_range", "claim_boundary",
)


class ProjectionError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ProjectionError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ordered_id_sha256(ids: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()


def read_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header")
        for field in fields:
            normalized = field.lower()
            require(not any(token in normalized for token in FORBIDDEN), f"forbidden_{role}_field:{field}")
        rows = list(reader)
    require(rows, f"{role}_empty")
    return fields, rows


def by_id(rows: Sequence[Mapping[str, str]], role: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id", "")
        require(candidate and candidate not in result, f"{role}_duplicate:{candidate}")
        result[candidate] = row
    return result


def tsv_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(FIELDS), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode()


def atomic_write(path: Path, payload: bytes) -> None:
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def validate_receipt(path: Path, expected_status: str, output_name: str, output_path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "receipt_not_regular")
    payload = json.loads(path.read_text())
    require(payload.get("status") == expected_status, f"receipt_status:{payload.get('status')}")
    outputs = payload.get("outputs", {})
    expected = outputs.get(output_name)
    require(isinstance(expected, str) and len(expected) == 64, f"receipt_output_missing:{output_name}")
    observed = sha256_file(output_path)
    require(observed == expected, f"receipt_output_hash:{output_name}")
    return observed


def build(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_exists")
    require(16 <= args.shards <= 64, "shards_out_of_range")
    prelim_sha = validate_receipt(
        args.preliminary_receipt, "PASS_TOP150K_FOUR_MODEL_PRELIMINARY_SELECTION",
        "STAGE1_TOP30000_FOR_C2.tsv", args.stage1,
    )
    staging_sha = validate_receipt(
        args.staging_receipt, "PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING",
        "top150k_m2_structure_manifest_v1.tsv", args.structure_manifest,
    )
    p_fields, preliminary = read_tsv(args.stage1, "preliminary")
    s_fields, structures = read_tsv(args.structure_manifest, "structure")
    for field in ("candidate_id", "sequence_sha256", "parent_framework_cluster"):
        require(field in p_fields and field in s_fields, f"join_field_missing:{field}")
    for field in ("monomer_path", "monomer_sha256", "cdr1_range", "cdr2_range", "cdr3_range"):
        require(field in s_fields, f"structure_field_missing:{field}")
    require(len(preliminary) == args.expected_rows, f"stage1_rows:{len(preliminary)}")
    structures_by_id = by_id(structures, "structure")
    projected: list[dict[str, str]] = []
    seen_hashes: set[str] = set()
    for row in preliminary:
        candidate = row["candidate_id"]
        require(candidate in structures_by_id, f"structure_missing:{candidate}")
        source = structures_by_id[candidate]
        require(row["sequence_sha256"] == source["sequence_sha256"], f"sequence_hash:{candidate}")
        require(row["parent_framework_cluster"] == source["parent_framework_cluster"], f"parent:{candidate}")
        require(row["sequence_sha256"] not in seen_hashes, f"duplicate_sequence_hash:{candidate}")
        seen_hashes.add(row["sequence_sha256"])
        monomer = Path(source["monomer_path"])
        require(monomer.is_absolute() and monomer.is_file() and not monomer.is_symlink(), f"monomer:{candidate}")
        require(sha256_file(monomer) == source["monomer_sha256"], f"monomer_hash:{candidate}")
        projected.append({
            "candidate_id": candidate,
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "monomer_pdb": str(monomer.resolve()),
            "monomer_sha256": source["monomer_sha256"],
            "cdr1_range": source["cdr1_range"],
            "cdr2_range": source["cdr2_range"],
            "cdr3_range": source["cdr3_range"],
            "claim_boundary": CLAIM,
        })
    base, remainder = divmod(len(projected), args.shards)
    cursor = 0; records = []
    for index in range(args.shards):
        size = base + (index < remainder)
        rows = projected[cursor:cursor + size]; cursor += size
        relative = Path("manifests") / f"shard_{index:03d}.tsv"
        path = args.output_dir / relative
        atomic_write(path, tsv_bytes(rows))
        records.append({
            "shard_id": f"shard_{index:03d}", "relative_path": relative.as_posix(),
            "sha256": sha256_file(path), "rows": len(rows),
            "ordered_candidate_id_sha256": ordered_id_sha256([r["candidate_id"] for r in rows]),
        })
    plan = {
        "schema_version": SCHEMA, "status": STATUS, "claim_boundary": CLAIM,
        "counts": {"rows": len(projected), "shards": args.shards},
        "inputs": {"preliminary_sha256": prelim_sha, "structure_manifest_sha256": staging_sha},
        "candidate_set_sha256": ordered_id_sha256(sorted(r["candidate_id"] for r in projected)),
        "ordered_candidate_id_sha256": ordered_id_sha256([r["candidate_id"] for r in projected]),
        "shards": records,
        "invariants": {"sequence_sha256_join_exact": True, "parent_join_exact": True,
                       "monomer_sha256_recomputed": True, "truth_columns_read": 0,
                       "candidate_docking_pose_files_opened": 0},
    }
    plan_path = args.output_dir / "SHARD_PLAN.json"
    atomic_write(plan_path, (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode())
    return {"status": STATUS, "rows": len(projected), "plan_sha256": sha256_file(plan_path)}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage1", type=Path, required=True)
    p.add_argument("--preliminary-receipt", type=Path, required=True)
    p.add_argument("--structure-manifest", type=Path, required=True)
    p.add_argument("--staging-receipt", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-rows", type=int, default=30000)
    p.add_argument("--shards", type=int, default=32)
    return p


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), sort_keys=True))
