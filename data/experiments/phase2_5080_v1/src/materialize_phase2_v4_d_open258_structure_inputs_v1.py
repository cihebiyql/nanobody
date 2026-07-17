#!/usr/bin/env python3
"""Materialize the label-free V4-D open258 frozen-monomer input bundle.

This builder reads only the frozen split manifest, docking job manifest, and
the monomer PDBs that were used as docking ligand inputs.  It never reads a
docking result, pose, score, geometry label, or prospective-test monomer.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "phase2_v4_d_open258_structure_inputs_v1"
READY_STATUS = "OPEN258_LABEL_FREE_FROZEN_MONOMERS_READY_TEST32_UNTOUCHED"
OPEN_SPLITS = ("OPEN_TRAIN", "OPEN_DEVELOPMENT")
SEALED_SPLIT = "PROSPECTIVE_COMPUTATIONAL_TEST"
EXPECTED_COUNTS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}
EXPECTED_OPEN_ROWS = 258
EXPECTED_SEALED_ROWS = 32
EXPECTED_JOBS_PER_CANDIDATE = 6
EXPECTED_MONOMER_KIND = "frozen_local_candidate"
MANIFEST_NAME = "open258_structure_manifest_v1.tsv"
AUDIT_NAME = "open258_structure_input_audit_v1.json"
CHECKSUM_NAME = "SHA256SUMS"
ARCHIVE_NAME = "open258_structure_inputs_v1.tar.gz"
CLAIM_BOUNDARY = (
    "Label-free frozen VHH monomer inputs for development-only computational "
    "docking-geometry surrogate research; no Docking Gold, binding, affinity, "
    "competition, experimental blocking, or final submission authority."
)
MANIFEST_FIELDS = (
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "model_split",
    "parent_framework_cluster",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr_residues",
    "monomer_source_kind",
    "monomer_source_chain",
    "source_relative_path",
    "bundle_relative_path",
    "monomer_sha256",
    "monomer_bytes",
    "atom_record_count",
    "heavy_atom_count",
    "ca_residue_count",
    "observed_chains",
    "claim_boundary",
)


class MaterializationError(RuntimeError):
    """Fail-closed materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MaterializationError(f"missing_file:{label}:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_or_symlink:{label}:{path}")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"temporary_exists:{temporary}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_tsv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular_file(path, label)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"empty_tsv:{label}")
    return fields, rows


def safe_candidate_filename(candidate_id: str) -> str:
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", candidate_id) is not None, f"unsafe_candidate_id:{candidate_id}")
    return f"{candidate_id}.pdb"


def parse_pdb_summary(path: Path, expected_chain: str) -> dict[str, Any]:
    require_regular_file(path, "monomer_pdb")
    atom_count = 0
    heavy_count = 0
    ca_residues: set[tuple[str, str, str]] = set()
    chains: set[str] = set()
    with path.open("r", encoding="ascii", errors="strict") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.startswith("ATOM  "):
                continue
            require(len(line) >= 54, f"short_atom_record:{path}:{line_number}")
            atom_count += 1
            atom_name = line[12:16].strip()
            chain = line[21:22]
            residue_number = line[22:26].strip()
            insertion_code = line[26:27]
            element = line[76:78].strip() if len(line) >= 78 else atom_name[:1]
            chains.add(chain)
            if element.upper() != "H" and not atom_name.upper().startswith("H"):
                heavy_count += 1
            if atom_name == "CA":
                key = (chain, residue_number, insertion_code)
                require(key not in ca_residues, f"duplicate_ca:{path}:{key}")
                ca_residues.add(key)
    require(atom_count > 0 and heavy_count > 0 and ca_residues, f"pdb_without_required_atoms:{path}")
    require(chains == {expected_chain}, f"unexpected_monomer_chains:{path}:{sorted(chains)}")
    return {
        "atom_record_count": atom_count,
        "heavy_atom_count": heavy_count,
        "ca_residue_count": len(ca_residues),
        "observed_chains": ",".join(sorted(chains)),
    }


def write_manifest(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=MANIFEST_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in MANIFEST_FIELDS})
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def write_checksums(outputs: Path, relative_names: list[str]) -> None:
    lines = [f"{sha256_file(outputs / name)}  outputs/{name}" for name in sorted(relative_names)]
    atomic_write(outputs / CHECKSUM_NAME, ("\n".join(lines) + "\n").encode("ascii"))


def deterministic_archive(output_dir: Path, member_names: list[str]) -> Path:
    archive = output_dir / ARCHIVE_NAME
    temporary = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for name in sorted(member_names):
                    source = output_dir / name
                    require_regular_file(source, f"archive_member:{name}")
                    info = tarfile.TarInfo(name=name)
                    info.size = source.stat().st_size
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with source.open("rb") as handle:
                        bundle.addfile(info, handle)
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, archive)
    atomic_write(output_dir / f"{ARCHIVE_NAME}.sha256", f"{sha256_file(archive)}  {ARCHIVE_NAME}\n".encode("ascii"))
    return archive


def materialize(split_manifest: Path, job_manifest: Path, campaign_root: Path, output_dir: Path) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    _, split_rows = load_tsv(split_manifest, "split_manifest")
    split_counts = Counter(row.get("model_split", "") for row in split_rows)
    require(
        split_counts == Counter({**EXPECTED_COUNTS, SEALED_SPLIT: EXPECTED_SEALED_ROWS}),
        f"split_counts_invalid:{dict(split_counts)}",
    )
    open_rows = {row["candidate_id"]: row for row in split_rows if row["model_split"] in OPEN_SPLITS}
    sealed_ids = {row["candidate_id"] for row in split_rows if row["model_split"] == SEALED_SPLIT}
    require(len(open_rows) == EXPECTED_OPEN_ROWS and len(sealed_ids) == EXPECTED_SEALED_ROWS, "split_cardinality_invalid")

    _, job_rows = load_tsv(job_manifest, "job_manifest")
    jobs_by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    sealed_job_rows_seen = 0
    for row in job_rows:
        if row.get("entity_type") != "candidate":
            continue
        candidate_id = row.get("entity_id", "")
        if candidate_id in sealed_ids:
            sealed_job_rows_seen += 1
            continue
        if candidate_id in open_rows:
            jobs_by_candidate[candidate_id].append(row)
    require(sealed_job_rows_seen == EXPECTED_SEALED_ROWS * EXPECTED_JOBS_PER_CANDIDATE, "sealed_job_manifest_count_invalid")
    require(set(jobs_by_candidate) == set(open_rows), "open_candidate_job_closure_failed")

    output_dir.mkdir(parents=True)
    outputs = output_dir / "outputs"
    monomers = outputs / "monomers"
    monomers.mkdir(parents=True)
    manifest_rows: list[dict[str, Any]] = []
    source_paths: set[str] = set()
    source_hashes: set[str] = set()
    for candidate_id in sorted(open_rows):
        rows = jobs_by_candidate[candidate_id]
        require(len(rows) == EXPECTED_JOBS_PER_CANDIDATE, f"job_count_invalid:{candidate_id}:{len(rows)}")
        invariant_fields = (
            "sequence_sha256", "cdr1_range", "cdr2_range", "cdr3_range", "cdr_residues",
            "monomer_source", "monomer_source_kind", "monomer_source_chain",
        )
        values = {field: {row.get(field, "") for row in rows} for field in invariant_fields}
        for field, distinct in values.items():
            require(len(distinct) == 1, f"job_invariant_mismatch:{candidate_id}:{field}")
        job = rows[0]
        split = open_rows[candidate_id]
        require(job["sequence_sha256"] == split["sequence_sha256"], f"sequence_sha_mismatch:{candidate_id}")
        require(job["monomer_source_kind"] == EXPECTED_MONOMER_KIND, f"monomer_kind_invalid:{candidate_id}")
        relative = PurePosixPath(job["monomer_source"])
        require(not relative.is_absolute() and ".." not in relative.parts and "." not in relative.parts, f"unsafe_source_path:{candidate_id}")
        source = campaign_root.joinpath(*relative.parts)
        require_regular_file(source, f"source_monomer:{candidate_id}")
        source_hash = sha256_file(source)
        filename = safe_candidate_filename(candidate_id)
        destination = monomers / filename
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        require(sha256_file(destination) == source_hash, f"copied_monomer_hash_mismatch:{candidate_id}")
        pdb = parse_pdb_summary(destination, job["monomer_source_chain"])
        source_paths.add(relative.as_posix())
        source_hashes.add(source_hash)
        manifest_rows.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "sequence_sha256": split["sequence_sha256"],
            "model_split": split["model_split"],
            "parent_framework_cluster": split["parent_framework_cluster"],
            "cdr1_range": job["cdr1_range"],
            "cdr2_range": job["cdr2_range"],
            "cdr3_range": job["cdr3_range"],
            "cdr_residues": job["cdr_residues"],
            "monomer_source_kind": job["monomer_source_kind"],
            "monomer_source_chain": job["monomer_source_chain"],
            "source_relative_path": relative.as_posix(),
            "bundle_relative_path": f"outputs/monomers/{filename}",
            "monomer_sha256": source_hash,
            "monomer_bytes": destination.stat().st_size,
            **pdb,
            "claim_boundary": CLAIM_BOUNDARY,
        })
    require(len(manifest_rows) == EXPECTED_OPEN_ROWS, "manifest_row_count_invalid")
    require(len(source_paths) == EXPECTED_OPEN_ROWS and len(source_hashes) == EXPECTED_OPEN_ROWS, "monomer_uniqueness_invalid")
    write_manifest(outputs / MANIFEST_NAME, manifest_rows)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "inputs": {
            "split_manifest_sha256": sha256_file(split_manifest),
            "job_manifest_sha256": sha256_file(job_manifest),
            "campaign_root": str(campaign_root),
            "monomer_source_kind": EXPECTED_MONOMER_KIND,
        },
        "output": {
            "manifest": f"outputs/{MANIFEST_NAME}",
            "manifest_sha256": sha256_file(outputs / MANIFEST_NAME),
            "candidate_count": len(manifest_rows),
            "split_counts": dict(sorted(Counter(row["model_split"] for row in manifest_rows).items())),
            "unique_monomer_paths": len(source_paths),
            "unique_monomer_hashes": len(source_hashes),
        },
        "sealed_boundary": {
            "sealed_candidate_count_in_split_manifest": len(sealed_ids),
            "sealed_job_manifest_rows_skipped": sealed_job_rows_seen,
            "sealed_monomer_files_opened": 0,
            "docking_result_files_opened": 0,
            "pose_files_opened": 0,
            "geometry_label_values_read": 0,
        },
    }
    atomic_write(outputs / AUDIT_NAME, canonical_json(audit))
    payload_names = [MANIFEST_NAME, AUDIT_NAME] + [f"monomers/{safe_candidate_filename(row['candidate_id'])}" for row in manifest_rows]
    write_checksums(outputs, payload_names)
    archive_members = [f"outputs/{name}" for name in payload_names + [CHECKSUM_NAME]]
    archive = deterministic_archive(output_dir, archive_members)
    return {
        "status": READY_STATUS,
        "candidate_count": EXPECTED_OPEN_ROWS,
        "split_counts": EXPECTED_COUNTS,
        "manifest_sha256": sha256_file(outputs / MANIFEST_NAME),
        "audit_sha256": sha256_file(outputs / AUDIT_NAME),
        "archive_sha256": sha256_file(archive),
        "sealed_monomer_files_opened": 0,
        "geometry_label_values_read": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(args.split_manifest, args.job_manifest, args.campaign_root, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
