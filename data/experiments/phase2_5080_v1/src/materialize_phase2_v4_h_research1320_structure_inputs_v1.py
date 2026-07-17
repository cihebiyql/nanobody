#!/usr/bin/env python3
"""Materialize the frozen V4-H research-1320 label-free structure inputs.

The production CLI reads exactly the local frozen candidate manifest and a
caller-provided portable monomer manifest plus monomers directory.  It never
discovers or reads docking outputs.  Publication is fail-closed and atomic.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

PHASE_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CANDIDATE_MANIFEST = (
    PHASE_ROOT
    / "prepared"
    / "pvrig_v4_h_research_pool_v1"
    / "outputs"
    / "research_ready1320.tsv"
)
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551"
)
EXPECTED_MONOMER_MANIFEST_SHA256 = (
    "e74b32d53d7a1fb2719d8b7e01b60bb2855553794607f011e14e0f5399fa8137"
)
EXPECTED_COUNT = 1320
EXPECTED_OUTPUT_BASENAME = "pvrig_v4_h_research1320_structure_inputs_v1"
OUTPUT_MANIFEST_NAME = "research1320_structure_inputs_v1.tsv"
PDB_BUNDLE_NAME = "pdb_bundle_v1"
RECEIPT_NAME = "MATERIALIZATION_RECEIPT_V1.json"
SHA256SUMS_NAME = "SHA256SUMS"
CLAIM_BOUNDARY = (
    "Label-free V4-H sequence and monomer structure inputs for computational "
    "development only; not docking results, pose labels, binding, affinity, "
    "competition, experimental blocking, Docking Gold, formal validation, or "
    "final submission authority."
)
FORBIDDEN_PATH_TOKENS = ("result", "status", "pose", "test32")
FORBIDDEN_COLUMN_TOKENS = ("result", "status", "pose", "test32")
STANDARD_AA_RE = re.compile(r"[ACDEFGHIKLMNPQRSTVWY]+")
CANDIDATE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def reject_forbidden_path(path: Path, label: str) -> None:
    absolute = lexical_absolute(path)
    for component in absolute.parts:
        lowered = component.casefold()
        for token in FORBIDDEN_PATH_TOKENS:
            require(token not in lowered, f"forbidden_path_component:{label}:{component}")


def reject_symlink_components(
    path: Path,
    label: str,
    *,
    missing_leaf_allowed: bool = False,
) -> None:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    components = absolute.parts[1:] if absolute.anchor else absolute.parts
    for index, component in enumerate(components):
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError as exc:
            if missing_leaf_allowed and index == len(components) - 1:
                return
            raise MaterializationError(f"path_component_missing:{label}:{current}") from exc
        require(not stat.S_ISLNK(metadata.st_mode), f"symlink_component_rejected:{label}:{current}")


def read_snapshot(path: Path, label: str) -> bytes:
    reject_forbidden_path(path, label)
    reject_symlink_components(path, label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MaterializationError(f"unable_to_open_snapshot:{label}:{path}") from exc
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode), f"snapshot_not_regular:{label}")
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(identity(before) == identity(after), f"snapshot_changed_during_read:{label}")
        require(len(raw) == before.st_size, f"snapshot_size_changed_during_read:{label}")
        return raw
    finally:
        os.close(descriptor)


def parse_tsv(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaterializationError(f"invalid_utf8:{label}") from exc
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t")
    try:
        fields = next(reader)
    except StopIteration as exc:
        raise MaterializationError(f"empty_tsv:{label}") from exc
    require(bool(fields) and all(fields), f"invalid_tsv_header:{label}")
    require(len(fields) == len(set(fields)), f"duplicate_tsv_header:{label}")
    for field in fields:
        lowered = field.casefold()
        for token in FORBIDDEN_COLUMN_TOKENS:
            require(token not in lowered, f"forbidden_column:{label}:{field}")
    rows: list[dict[str, str]] = []
    for line_number, values in enumerate(reader, start=2):
        require(len(values) == len(fields), f"tsv_width_mismatch:{label}:{line_number}")
        rows.append(dict(zip(fields, values)))
    return fields, rows


def validate_candidate_rows(
    fields: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    expected_count: int,
) -> list[dict[str, str]]:
    required = {
        "candidate_id",
        "sequence",
        "sequence_sha256",
        "sequence_length",
        "parent_id",
        "parent_framework_cluster",
        "target_patch_id",
        "design_mode",
        "research_pool_state",
        "monomer_structure_eligible",
        "sequence_repaired",
    }
    require(required.issubset(fields), "candidate_required_columns_missing")
    require(len(rows) == expected_count, f"candidate_count_mismatch:{len(rows)}")
    output: list[dict[str, str]] = []
    candidate_ids: set[str] = set()
    sequences: set[str] = set()
    sequence_hashes: set[str] = set()
    for row_number, source in enumerate(rows, start=2):
        row = dict(source)
        for field in required:
            require(bool(row.get(field)), f"candidate_required_value_missing:{row_number}:{field}")
        candidate_id = row["candidate_id"]
        sequence = row["sequence"]
        sequence_sha256 = row["sequence_sha256"]
        require(CANDIDATE_ID_RE.fullmatch(candidate_id) is not None, f"candidate_id_invalid:{candidate_id}")
        require(candidate_id not in candidate_ids, f"candidate_id_duplicate:{candidate_id}")
        require(STANDARD_AA_RE.fullmatch(sequence) is not None, f"candidate_sequence_invalid:{candidate_id}")
        require(sequence not in sequences, f"candidate_sequence_duplicate:{candidate_id}")
        require(SHA256_RE.fullmatch(sequence_sha256) is not None, f"candidate_sequence_sha_invalid:{candidate_id}")
        require(sequence_sha256 not in sequence_hashes, f"candidate_sequence_sha_duplicate:{candidate_id}")
        require(sha256_bytes(sequence.encode("ascii")) == sequence_sha256, f"candidate_sequence_sha_mismatch:{candidate_id}")
        try:
            declared_length = int(row["sequence_length"])
        except ValueError as exc:
            raise MaterializationError(f"candidate_sequence_length_invalid:{candidate_id}") from exc
        require(declared_length == len(sequence), f"candidate_sequence_length_mismatch:{candidate_id}")
        require(row["research_pool_state"] == "RESEARCH_READY", f"candidate_not_research_ready:{candidate_id}")
        require(row["monomer_structure_eligible"] == "true", f"candidate_not_monomer_eligible:{candidate_id}")
        require(row["sequence_repaired"] == "false", f"candidate_sequence_repaired:{candidate_id}")
        candidate_ids.add(candidate_id)
        sequences.add(sequence)
        sequence_hashes.add(sequence_sha256)
        output.append(row)
    return output


def validate_monomer_rows(
    fields: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    expected_count: int,
) -> list[dict[str, str]]:
    required = {
        "candidate_id",
        "sequence_sha256",
        "frozen_monomer_path",
        "source_chain",
        "sha256",
        "size_bytes",
    }
    require(required.issubset(fields), "monomer_required_columns_missing")
    require(len(rows) == expected_count, f"monomer_count_mismatch:{len(rows)}")
    output: list[dict[str, str]] = []
    ids: set[str] = set()
    composite_keys: set[tuple[str, str]] = set()
    pdb_hashes: set[str] = set()
    for row_number, source in enumerate(rows, start=2):
        row = dict(source)
        for field in required:
            require(bool(row.get(field)), f"monomer_required_value_missing:{row_number}:{field}")
        candidate_id = row["candidate_id"]
        sequence_sha256 = row["sequence_sha256"]
        pdb_sha256 = row["sha256"]
        require(CANDIDATE_ID_RE.fullmatch(candidate_id) is not None, f"monomer_candidate_id_invalid:{candidate_id}")
        require(SHA256_RE.fullmatch(sequence_sha256) is not None, f"monomer_sequence_sha_invalid:{candidate_id}")
        require(SHA256_RE.fullmatch(pdb_sha256) is not None, f"monomer_pdb_sha_invalid:{candidate_id}")
        require(candidate_id not in ids, f"monomer_candidate_id_duplicate:{candidate_id}")
        key = (candidate_id, sequence_sha256)
        require(key not in composite_keys, f"monomer_composite_key_duplicate:{candidate_id}")
        require(pdb_sha256 not in pdb_hashes, f"monomer_pdb_sha_duplicate:{candidate_id}")
        require(row["source_chain"] == "A", f"monomer_source_chain_invalid:{candidate_id}")
        expected_relative_text = f"monomers/{candidate_id}.pdb"
        expected_relative = PurePosixPath(expected_relative_text)
        try:
            actual_relative = PurePosixPath(row["frozen_monomer_path"])
        except Exception as exc:
            raise MaterializationError(f"monomer_path_invalid:{candidate_id}") from exc
        require(
            row["frozen_monomer_path"] == expected_relative_text
            and actual_relative == expected_relative,
            f"monomer_path_contract_invalid:{candidate_id}",
        )
        require(not actual_relative.is_absolute(), f"monomer_path_absolute:{candidate_id}")
        require(".." not in actual_relative.parts, f"monomer_path_traversal:{candidate_id}")
        reject_forbidden_path(Path(row["frozen_monomer_path"]), f"monomer_relative:{candidate_id}")
        require(
            re.fullmatch(r"[1-9][0-9]*", row["size_bytes"]) is not None,
            f"monomer_size_invalid:{candidate_id}",
        )
        try:
            size_bytes = int(row["size_bytes"])
        except ValueError as exc:
            raise MaterializationError(f"monomer_size_invalid:{candidate_id}") from exc
        require(size_bytes > 0, f"monomer_size_not_positive:{candidate_id}")
        ids.add(candidate_id)
        composite_keys.add(key)
        pdb_hashes.add(pdb_sha256)
        output.append(row)
    return output


def strict_composite_join(
    candidates: Sequence[Mapping[str, str]],
    monomers: Sequence[Mapping[str, str]],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    candidate_keys = [(row["candidate_id"], row["sequence_sha256"]) for row in candidates]
    monomer_by_key = {
        (row["candidate_id"], row["sequence_sha256"]): dict(row) for row in monomers
    }
    require(len(monomer_by_key) == len(monomers), "monomer_composite_key_not_unique")
    require(set(candidate_keys) == set(monomer_by_key), "candidate_monomer_composite_key_closure_failed")
    candidate_id_to_sha = {row["candidate_id"]: row["sequence_sha256"] for row in candidates}
    monomer_id_to_sha = {row["candidate_id"]: row["sequence_sha256"] for row in monomers}
    require(candidate_id_to_sha == monomer_id_to_sha, "candidate_monomer_id_sha_mapping_mismatch")
    return [(dict(candidate), monomer_by_key[key]) for candidate, key in zip(candidates, candidate_keys)]


def ensure_directory(path: Path, label: str) -> None:
    reject_forbidden_path(path, label)
    reject_symlink_components(path, label)
    require(path.is_dir(), f"directory_required:{label}:{path}")


def write_exclusive(path: Path, raw: bytes, mode: int = 0o444) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            require(written > 0, f"short_write:{path}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def tsv_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(fields),
        delimiter="\t",
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_output_root(output_root: Path, expected_basename: str) -> Path:
    output_root = lexical_absolute(output_root)
    reject_forbidden_path(output_root, "output_root")
    require(output_root.name == expected_basename, f"output_basename_invalid:{output_root.name}")
    parent = output_root.parent
    ensure_directory(parent, "output_parent")
    reject_symlink_components(output_root, "output_root", missing_leaf_allowed=True)
    require(not os.path.lexists(output_root), f"output_root_preexists:{output_root}")
    return output_root


def materialize(
    *,
    candidate_manifest: Path,
    monomer_manifest: Path,
    monomers_root: Path,
    output_root: Path,
    expected_candidate_manifest_sha256: str,
    expected_monomer_manifest_sha256: str,
    expected_count: int = EXPECTED_COUNT,
    expected_output_basename: str = EXPECTED_OUTPUT_BASENAME,
) -> dict[str, Any]:
    require(type(expected_count) is int and expected_count > 0, "expected_count_invalid")
    require(SHA256_RE.fullmatch(expected_candidate_manifest_sha256) is not None, "expected_candidate_sha_invalid")
    require(SHA256_RE.fullmatch(expected_monomer_manifest_sha256) is not None, "expected_monomer_sha_invalid")
    output_root = validate_output_root(output_root, expected_output_basename)
    ensure_directory(monomers_root, "monomers_root")

    candidate_raw = read_snapshot(candidate_manifest, "candidate_manifest")
    monomer_raw = read_snapshot(monomer_manifest, "monomer_manifest")
    candidate_manifest_sha256 = sha256_bytes(candidate_raw)
    monomer_manifest_sha256 = sha256_bytes(monomer_raw)
    require(
        candidate_manifest_sha256 == expected_candidate_manifest_sha256,
        "candidate_manifest_sha256_mismatch",
    )
    require(
        monomer_manifest_sha256 == expected_monomer_manifest_sha256,
        "monomer_manifest_sha256_mismatch",
    )
    candidate_fields, unvalidated_candidates = parse_tsv(candidate_raw, "candidate_manifest")
    monomer_fields, unvalidated_monomers = parse_tsv(monomer_raw, "monomer_manifest")
    candidates = validate_candidate_rows(candidate_fields, unvalidated_candidates, expected_count)
    monomers = validate_monomer_rows(monomer_fields, unvalidated_monomers, expected_count)
    joined = strict_composite_join(candidates, monomers)
    require(len(joined) == expected_count, "joined_count_mismatch")

    staging_path = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.staging.", dir=output_root.parent)
    )
    reject_forbidden_path(staging_path, "staging_root")
    pdb_bundle = staging_path / PDB_BUNDLE_NAME
    pdb_bundle.mkdir(mode=0o755)
    output_rows: list[dict[str, str]] = []
    pdb_entries: list[tuple[str, str]] = []
    candidate_chain = hashlib.sha256()
    monomer_set_chain = hashlib.sha256()
    candidate_sequence_pdb_chain = hashlib.sha256()
    try:
        for candidate, monomer in joined:
            candidate_id = candidate["candidate_id"]
            source_pdb = monomers_root / f"{candidate_id}.pdb"
            pdb_raw = read_snapshot(source_pdb, f"monomer_pdb:{candidate_id}")
            declared_size = int(monomer["size_bytes"])
            require(len(pdb_raw) == declared_size, f"monomer_pdb_size_mismatch:{candidate_id}")
            pdb_sha256 = sha256_bytes(pdb_raw)
            require(pdb_sha256 == monomer["sha256"], f"monomer_pdb_sha256_mismatch:{candidate_id}")
            relative_output = PurePosixPath(PDB_BUNDLE_NAME) / f"{candidate_id}.pdb"
            destination = staging_path / Path(relative_output)
            write_exclusive(destination, pdb_raw)
            require(sha256_bytes(destination.read_bytes()) == pdb_sha256, f"output_pdb_sha256_mismatch:{candidate_id}")
            candidate_chain.update(
                f"{candidate_id}\t{candidate['sequence_sha256']}\n".encode("utf-8")
            )
            monomer_set_chain.update(pdb_sha256.encode("ascii"))
            candidate_sequence_pdb_chain.update(
                f"{candidate_id}\t{candidate['sequence_sha256']}\t{pdb_sha256}\n".encode("utf-8")
            )
            output_rows.append(
                {
                    "candidate_id": candidate_id,
                    "sequence": candidate["sequence"],
                    "sequence_sha256": candidate["sequence_sha256"],
                    "parent_id": candidate["parent_id"],
                    "parent_framework_cluster": candidate["parent_framework_cluster"],
                    "target_patch_id": candidate["target_patch_id"],
                    "design_mode": candidate["design_mode"],
                    "monomer_relative_path": str(relative_output),
                    "monomer_sha256": pdb_sha256,
                    "monomer_size_bytes": str(declared_size),
                    "source_chain": monomer["source_chain"],
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
            pdb_entries.append((str(relative_output), pdb_sha256))

        output_fields = list(output_rows[0])
        output_manifest = staging_path / OUTPUT_MANIFEST_NAME
        write_exclusive(output_manifest, tsv_bytes(output_fields, output_rows))
        output_manifest_sha256 = sha256_bytes(output_manifest.read_bytes())
        receipt: dict[str, Any] = {
            "schema_version": "phase2_v4_h_research1320_structure_inputs_v1",
            "status": "PASS_LABEL_FREE_STRUCTURE_INPUTS_MATERIALIZED",
            "claim_boundary": CLAIM_BOUNDARY,
            "candidate_count": expected_count,
            "pdb_count": len(pdb_entries),
            "join_key": ["candidate_id", "sequence_sha256"],
            "join_cardinality": "ONE_TO_ONE_EXACT_CLOSURE",
            "candidate_manifest_path": str(lexical_absolute(candidate_manifest)),
            "candidate_manifest_sha256": candidate_manifest_sha256,
            "monomer_manifest_path": str(lexical_absolute(monomer_manifest)),
            "monomer_manifest_sha256": monomer_manifest_sha256,
            "monomers_root": str(lexical_absolute(monomers_root)),
            "output_manifest": OUTPUT_MANIFEST_NAME,
            "output_manifest_sha256": output_manifest_sha256,
            "pdb_bundle": PDB_BUNDLE_NAME,
            "candidate_id_sequence_sha256_chain": candidate_chain.hexdigest(),
            "monomer_set_sha256": monomer_set_chain.hexdigest(),
            "candidate_sequence_pdb_sha256_chain": candidate_sequence_pdb_chain.hexdigest(),
            "source_chain": "A",
            "forbidden_path_channels_opened": {
                "results": 0,
                "status": 0,
                "pose": 0,
                "test32": 0,
            },
        }
        receipt_path = staging_path / RECEIPT_NAME
        write_exclusive(
            receipt_path,
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        checksum_entries = [
            (OUTPUT_MANIFEST_NAME, output_manifest_sha256),
            *pdb_entries,
            (RECEIPT_NAME, sha256_bytes(receipt_path.read_bytes())),
        ]
        checksum_raw = "".join(
            f"{digest}  {relative}\n" for relative, digest in checksum_entries
        ).encode("utf-8")
        write_exclusive(staging_path / SHA256SUMS_NAME, checksum_raw)
        fsync_directory(pdb_bundle)
        fsync_directory(staging_path)
        os.replace(staging_path, output_root)
        fsync_directory(output_root.parent)
        return receipt
    except BaseException:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monomer-manifest", required=True, type=Path)
    parser.add_argument("--monomers-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    receipt = materialize(
        candidate_manifest=CANONICAL_CANDIDATE_MANIFEST,
        monomer_manifest=args.monomer_manifest,
        monomers_root=args.monomers_root,
        output_root=args.output_root,
        expected_candidate_manifest_sha256=EXPECTED_CANDIDATE_MANIFEST_SHA256,
        expected_monomer_manifest_sha256=EXPECTED_MONOMER_MANIFEST_SHA256,
        expected_count=EXPECTED_COUNT,
        expected_output_basename=EXPECTED_OUTPUT_BASENAME,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
