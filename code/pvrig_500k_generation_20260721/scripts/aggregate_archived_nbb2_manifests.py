#!/usr/bin/env python3
"""Extract and aggregate NanoBodyBuilder2 manifests from durable node archives."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


EXTRA_FIELDS = [
    "nbb2_wave",
    "nbb2_archive_path",
    "nbb2_archive_sha256",
    "nbb2_archive_member",
    "nbb2_manifest_member",
]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_declared_archive_sha256(archive: Path) -> str:
    checksum = archive.with_suffix("").with_suffix(".sha256")
    if not checksum.is_file():
        raise FileNotFoundError(checksum)
    value = checksum.read_text().strip().split()[0]
    if not HEX64.fullmatch(value):
        raise ValueError(f"invalid archive SHA256 in {checksum}: {value!r}")
    return value


def collect_archive(archive: Path) -> tuple[list[str], list[dict[str, str]]]:
    declared_sha256 = read_declared_archive_sha256(archive)
    wave = next((part for part in archive.parts if re.fullmatch(r"wave_\d{2}", part)), "")
    if not wave:
        raise ValueError(f"cannot infer wave from {archive}")

    rows: list[dict[str, str]] = []
    fields: list[str] | None = None
    with tarfile.open(archive, "r:gz") as tar:
        manifests = sorted(
            (member for member in tar.getmembers() if member.isfile() and member.name.endswith("/manifest.tsv")),
            key=lambda member: member.name,
        )
        if not manifests:
            raise ValueError(f"no worker manifests in {archive}")
        for member in manifests:
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot extract {member.name} from {archive}")
            reader = csv.DictReader(io.TextIOWrapper(extracted, encoding="utf-8"), delimiter="\t")
            current_fields = list(reader.fieldnames or [])
            if fields is None:
                fields = current_fields
            elif fields != current_fields:
                raise ValueError(f"manifest schema mismatch in {archive}: {member.name}")
            worker_dir = str(Path(member.name).parent)
            for row in reader:
                pdb_name = row.get("pdb_relative_path", "")
                enriched = dict(row)
                enriched.update(
                    {
                        "nbb2_wave": wave,
                        "nbb2_archive_path": str(archive),
                        "nbb2_archive_sha256": declared_sha256,
                        "nbb2_archive_member": f"{worker_dir}/{pdb_name}" if pdb_name else "",
                        "nbb2_manifest_member": member.name,
                    }
                )
                rows.append(enriched)
    assert fields is not None
    return fields + EXTRA_FIELDS, rows


def write_gzip_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=int)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    archives = sorted(args.archive_root.glob("wave_*/archives_*/*.tar.gz"))
    if not archives:
        raise FileNotFoundError(f"no archives below {args.archive_root}")

    args.output_dir.mkdir(parents=True)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(collect_archive, archives))

    fields = results[0][0]
    rows: list[dict[str, str]] = []
    for current_fields, current_rows in results:
        if current_fields != fields:
            raise ValueError("cross-archive manifest schema mismatch")
        rows.extend(current_rows)
    rows.sort(key=lambda row: row["candidate_id"])

    candidate_ids = [row["candidate_id"] for row in rows]
    if len(rows) != args.expected or len(set(candidate_ids)) != args.expected:
        raise ValueError(
            f"record closure failure records={len(rows)} unique_ids={len(set(candidate_ids))} expected={args.expected}"
        )
    if any(row.get("status") != "SUCCESS" for row in rows):
        raise ValueError("non-SUCCESS structure row present")
    if any(row.get("pdb_sequence_match", "").lower() != "true" for row in rows):
        raise ValueError("PDB/sequence mismatch present")
    if any(not HEX64.fullmatch(row.get("sequence_sha256", "")) for row in rows):
        raise ValueError("invalid sequence SHA256 present")
    if any(not HEX64.fullmatch(row.get("pdb_sha256", "")) for row in rows):
        raise ValueError("invalid PDB SHA256 present")

    output = args.output_dir / "nbb2_top150k_manifest.tsv.gz"
    write_gzip_tsv(output, fields, rows)
    output_sha256 = sha256(output)
    receipt = {
        "status": "PASS",
        "records": len(rows),
        "unique_candidate_ids": len(set(candidate_ids)),
        "archives": len(archives),
        "waves": sorted({row["nbb2_wave"] for row in rows}),
        "output": output.name,
        "output_sha256": output_sha256,
        "scientific_boundary": "durable VHH monomer structure manifest; not binding, affinity, docking, or blocking evidence",
        "created_epoch": time.time(),
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(f"{output_sha256}  {output.name}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
