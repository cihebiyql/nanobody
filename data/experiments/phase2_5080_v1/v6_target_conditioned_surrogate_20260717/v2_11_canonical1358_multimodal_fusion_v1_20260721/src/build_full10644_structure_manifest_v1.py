#!/usr/bin/env python3
"""Build a hash-closed, label-free monomer manifest for canonical10644.

The teacher TSV is projected onto an explicit metadata allowlist. Numeric target
columns are neither indexed nor parsed. Candidate Docking poses are never opened.
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
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "pvrig_v2_11_canonical10644_label_free_structure_manifest_v1"
READY_STATUS = "PASS_CANONICAL10644_LABEL_FREE_MONOMER_CLOSURE"
CLAIM_BOUNDARY = (
    "Label-free VHH monomer structures and sequence/CDR metadata only; no Docking "
    "pose, scalar geometry label, binding, affinity, or experimental blocking truth."
)
TEACHER_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_framework_cluster",
    "cdr1",
    "cdr2",
    "cdr3",
)


class ManifestError(RuntimeError):
    """Fail-closed manifest construction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ManifestError(f"missing_file:{label}:{path}") from exc
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


def projected_tsv(path: Path, fields: Iterable[str]) -> list[dict[str, str]]:
    """Read only explicitly selected columns from a TSV.

    This intentionally avoids DictReader rows containing forbidden target columns.
    """

    selected = tuple(fields)
    require_regular_file(path, "tsv")
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header_line = handle.readline()
        require(bool(header_line), f"empty_tsv:{path}")
        header = header_line.rstrip("\r\n").split("\t")
        require(len(header) == len(set(header)), f"duplicate_header:{path}")
        missing = [field for field in selected if field not in header]
        require(not missing, f"missing_columns:{path}:{','.join(missing)}")
        indices = {field: header.index(field) for field in selected}
        for line_number, line in enumerate(handle, start=2):
            values = line.rstrip("\r\n").split("\t")
            require(len(values) == len(header), f"field_count_mismatch:{path}:{line_number}")
            rows.append({field: values[index] for field, index in indices.items()})
    return rows


def unique_cdr_ranges(sequence: str, cdrs: Mapping[str, str], candidate_id: str) -> dict[str, str]:
    spans: dict[str, tuple[int, int]] = {}
    for name in ("cdr1", "cdr2", "cdr3"):
        cdr = cdrs[name]
        require(bool(cdr), f"empty_{name}:{candidate_id}")
        starts = [index for index in range(len(sequence)) if sequence.startswith(cdr, index)]
        require(len(starts) == 1, f"nonunique_{name}_mapping:{candidate_id}:{len(starts)}")
        start = starts[0]
        spans[name] = (start, start + len(cdr))
    require(
        spans["cdr1"][1] <= spans["cdr2"][0] and spans["cdr2"][1] <= spans["cdr3"][0],
        f"cdr_order_or_overlap_invalid:{candidate_id}",
    )
    return {name: f"{start + 1}-{stop}" for name, (start, stop) in spans.items()}


def load_split_map(path: Path, expected_sha256: str) -> tuple[dict[str, str], dict[str, Any]]:
    require_regular_file(path, "split_manifest")
    require(sha256_file(path) == expected_sha256, "split_manifest_sha256_mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for parent in payload.get("train_parents", []):
        require(parent not in mapping, f"duplicate_split_parent:{parent}")
        mapping[parent] = "train"
    for parent in payload.get("score_parents", []):
        require(parent not in mapping, f"cross_split_parent:{parent}")
        mapping[parent] = "development"
    require(mapping, "empty_split_mapping")
    return mapping, payload


def source_rows(kind: str, manifest: Path, root: Path) -> list[dict[str, str]]:
    if kind == "v29":
        fields = ("candidate_id", "sequence_sha256", "monomer_status", "pdb_path", "pdb_sha256")
        rows = projected_tsv(manifest, fields)
        return [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "monomer_path": str(Path(row["pdb_path"]).resolve()),
                "monomer_sha256": row["pdb_sha256"],
                "chain": "A",
            }
            for row in rows
            if row["monomer_status"] == "SUCCESS"
        ]
    if kind in {"v4i", "v4h"}:
        fields = ("candidate_id", "sequence_sha256", "frozen_monomer_path", "sha256")
        rows = projected_tsv(manifest, fields)
        return [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "monomer_path": str((root / row["frozen_monomer_path"]).resolve()),
                "monomer_sha256": row["sha256"],
                "chain": "A",
            }
            for row in rows
        ]
    if kind == "v4d":
        fields = (
            "candidate_id", "sequence_sha256", "bundle_relative_path",
            "monomer_sha256", "monomer_source_chain",
        )
        rows = projected_tsv(manifest, fields)
        return [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "monomer_path": str((root / row["bundle_relative_path"]).resolve()),
                "monomer_sha256": row["monomer_sha256"],
                "chain": row["monomer_source_chain"],
            }
            for row in rows
        ]
    raise ManifestError(f"unsupported_source_kind:{kind}")


def build(
    teacher_tsv: Path,
    teacher_sha256: str,
    split_manifest: Path,
    split_sha256: str,
    sources: list[tuple[str, str, Path, Path, str]],
    output_dir: Path,
    expected_rows: int,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_dir_exists:{output_dir}")
    require_regular_file(teacher_tsv, "teacher_tsv")
    require(sha256_file(teacher_tsv) == teacher_sha256, "teacher_sha256_mismatch")
    teacher = projected_tsv(teacher_tsv, TEACHER_FIELDS)
    require(len(teacher) == expected_rows, f"teacher_row_count_invalid:{len(teacher)}")
    split_map, split_payload = load_split_map(split_manifest, split_sha256)

    candidate_ids = [row["candidate_id"] for row in teacher]
    sequence_hashes = [row["sequence_sha256"] for row in teacher]
    require(len(candidate_ids) == len(set(candidate_ids)), "duplicate_teacher_candidate_id")
    require(len(sequence_hashes) == len(set(sequence_hashes)), "duplicate_teacher_sequence_sha256")

    assets: dict[tuple[str, str], dict[str, str]] = {}
    source_audit: dict[str, Any] = {}
    for lane, kind, manifest, root, expected_manifest_sha256 in sources:
        require_regular_file(manifest, f"source_manifest:{lane}")
        actual_manifest_sha256 = sha256_file(manifest)
        require(actual_manifest_sha256 == expected_manifest_sha256, f"source_manifest_sha256_mismatch:{lane}")
        rows = source_rows(kind, manifest, root)
        for row in rows:
            key = (row["candidate_id"], row["sequence_sha256"])
            require(key not in assets, f"ambiguous_cross_source_asset:{key[0]}")
            row["asset_lane"] = lane
            row["source_manifest_sha256"] = actual_manifest_sha256
            assets[key] = row
        source_audit[lane] = {
            "kind": kind,
            "manifest_path": str(manifest.resolve()),
            "manifest_sha256": actual_manifest_sha256,
            "eligible_asset_rows": len(rows),
        }

    output_rows: list[dict[str, str]] = []
    for row in teacher:
        candidate_id = row["candidate_id"]
        sequence = row["sequence"]
        require(sequence and sequence.isascii() and sequence.isalpha() and sequence.upper() == sequence,
                f"invalid_sequence:{candidate_id}")
        require(sha256_text(sequence) == row["sequence_sha256"], f"sequence_sha256_mismatch:{candidate_id}")
        key = (candidate_id, row["sequence_sha256"])
        require(key in assets, f"missing_monomer_asset:{candidate_id}")
        asset = assets[key]
        monomer_path = Path(asset["monomer_path"])
        require_regular_file(monomer_path, f"monomer:{candidate_id}")
        require(len(asset["monomer_sha256"]) == 64, f"invalid_monomer_sha256:{candidate_id}")
        require(sha256_file(monomer_path) == asset["monomer_sha256"], f"monomer_sha256_mismatch:{candidate_id}")
        require(row["parent_framework_cluster"] in split_map, f"parent_not_in_open_split:{candidate_id}")
        ranges = unique_cdr_ranges(
            sequence,
            {"cdr1": row["cdr1"], "cdr2": row["cdr2"], "cdr3": row["cdr3"]},
            candidate_id,
        )
        output_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "model_split": split_map[row["parent_framework_cluster"]],
            "asset_lane": asset["asset_lane"],
            "monomer_path": str(monomer_path),
            "monomer_sha256": asset["monomer_sha256"],
            "monomer_chain": asset["chain"],
            "cdr1_range": ranges["cdr1"],
            "cdr2_range": ranges["cdr2"],
            "cdr3_range": ranges["cdr3"],
            "source_manifest_sha256": asset["source_manifest_sha256"],
            "claim_boundary": CLAIM_BOUNDARY,
        })

    require(len(output_rows) == expected_rows, "output_row_count_invalid")
    output_dir.mkdir(parents=True)
    output = output_dir / "canonical10644_structure_manifest_v1.tsv"
    fields = list(output_rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    atomic_write(output, buffer.getvalue().encode("utf-8"))
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": {
            "candidates": len(output_rows),
            "splits": dict(sorted(Counter(row["model_split"] for row in output_rows).items())),
            "asset_lanes": dict(sorted(Counter(row["asset_lane"] for row in output_rows).items())),
            "unique_candidate_ids": len({row["candidate_id"] for row in output_rows}),
            "unique_sequence_sha256": len({row["sequence_sha256"] for row in output_rows}),
            "unique_monomer_sha256": len({row["monomer_sha256"] for row in output_rows}),
        },
        "inputs": {
            "teacher_tsv_sha256": teacher_sha256,
            "split_manifest_sha256": split_sha256,
            "split_id": split_payload.get("split_id"),
            "sources": source_audit,
        },
        "output": {"path": output.name, "sha256": sha256_file(output)},
        "invariants": {
            "candidate_sequence_asset_exact_closure": True,
            "sequence_sha256_recomputed": True,
            "monomer_sha256_recomputed": True,
            "cdr_unique_exact_mapping": True,
            "teacher_columns_accessed": list(TEACHER_FIELDS),
            "numeric_geometry_target_columns_accessed": 0,
            "candidate_docking_pose_files_opened": 0,
        },
    }
    receipt_path = output_dir / "canonical10644_structure_manifest_v1.receipt.json"
    atomic_write(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "rows": len(output_rows),
        "manifest_sha256": sha256_file(output),
        "receipt_sha256": sha256_file(receipt_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-tsv", type=Path, required=True)
    parser.add_argument("--teacher-sha256", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--split-sha256", required=True)
    for lane in ("v29", "v4i", "v4h", "v4d"):
        parser.add_argument(f"--{lane}-manifest", type=Path, required=True)
        parser.add_argument(f"--{lane}-root", type=Path, required=True)
        parser.add_argument(f"--{lane}-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=10644)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = [
        ("V29", "v29", args.v29_manifest, args.v29_root, args.v29_manifest_sha256),
        ("V4I", "v4i", args.v4i_manifest, args.v4i_root, args.v4i_manifest_sha256),
        ("V4H", "v4h", args.v4h_manifest, args.v4h_root, args.v4h_manifest_sha256),
        ("V4D", "v4d", args.v4d_manifest, args.v4d_root, args.v4d_manifest_sha256),
    ]
    result = build(
        args.teacher_tsv, args.teacher_sha256, args.split_manifest, args.split_sha256,
        sources, args.output_dir, args.expected_rows,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
