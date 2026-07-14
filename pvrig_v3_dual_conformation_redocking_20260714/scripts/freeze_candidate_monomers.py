#!/usr/bin/env python3
"""Freeze the 128 existing candidate monomers from node1 into this protocol."""

from __future__ import annotations

import argparse
import io
import os
import shlex
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

from common import STANDARD_RESIDUES, project_root, read_tsv, sha256_file, write_json, write_tsv


REMOTE_ROOT = Path("/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712/docking/haddock")
AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
FIELDS = [
    "candidate_id",
    "sequence_sha256",
    "source_remote_path",
    "frozen_monomer_path",
    "source_chain",
    "sha256",
    "size_bytes",
    "atom_count",
    "residue_count",
    "first_residue",
    "last_residue",
]


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def relative_source(candidate_id: str) -> str:
    return f"{candidate_id}/data/{candidate_id}_vhh_chainA.pdb"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def pdb_sequence_and_stats(path: Path, chain: str = "A") -> tuple[str, int, list[int]]:
    residues: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    atom_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54 or line[21] != chain:
            continue
        resname = line[17:20].strip().upper()
        if resname not in STANDARD_RESIDUES:
            continue
        atom_count += 1
        key = (int(line[22:26]), line[26])
        if key not in seen:
            seen.add(key)
            residues.append((key[0], key[1], resname))
    if not residues:
        raise RuntimeError(f"no standard residues in chain {chain}: {path}")
    sequence = "".join(AA3_TO_1[resname] for _number, _icode, resname in residues)
    return sequence, atom_count, [number for number, _icode, _resname in residues]


def download(rows: list[dict[str, str]], host: str, ssh_bin: str) -> None:
    relative_paths = [relative_source(row["candidate_id"]) for row in rows]
    command = [ssh_bin, host, f"cd {shlex.quote(str(REMOTE_ROOT))} && tar -czf - -T -"]
    process = subprocess.run(
        command,
        input=("\n".join(relative_paths) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        raise RuntimeError(f"remote monomer tar failed: {process.stderr.decode(errors='replace')}")
    expected = set(relative_paths)
    observed: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(process.stdout), mode="r:gz") as archive:
        for member in archive.getmembers():
            normalized = member.name.removeprefix("./")
            if normalized not in expected or not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                raise RuntimeError(f"cannot extract {normalized}")
            candidate_id = normalized.split("/", 1)[0]
            atomic_write_bytes(root() / "inputs/candidate_monomers" / f"{candidate_id}.pdb", handle.read())
            observed.add(normalized)
    missing = sorted(expected - observed)
    if missing:
        raise RuntimeError(f"remote monomer archive omitted {len(missing)} paths: {missing[:5]}")


def build_manifest(candidate_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in candidate_rows:
        candidate_id = row["candidate_id"]
        path = root() / "inputs/candidate_monomers" / f"{candidate_id}.pdb"
        sequence, atom_count, residue_numbers = pdb_sequence_and_stats(path)
        if sequence != row["sequence"]:
            raise RuntimeError(f"candidate monomer sequence mismatch: {candidate_id}")
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": row["sequence_sha256"],
                "source_remote_path": str(REMOTE_ROOT / relative_source(candidate_id)),
                "frozen_monomer_path": str(path.relative_to(root())),
                "source_chain": "A",
                "sha256": sha256_file(path),
                "size_bytes": str(path.stat().st_size),
                "atom_count": str(atom_count),
                "residue_count": str(len(residue_numbers)),
                "first_residue": str(min(residue_numbers)),
                "last_residue": str(max(residue_numbers)),
            }
        )
    return output


def verify_manifest(candidate_rows: list[dict[str, str]], manifest_rows: list[dict[str, str]]) -> None:
    if len(manifest_rows) != 128 or {row["candidate_id"] for row in manifest_rows} != {row["candidate_id"] for row in candidate_rows}:
        raise RuntimeError("candidate monomer manifest does not cover exactly the fixed128 panel")
    for row in manifest_rows:
        path = root() / row["frozen_monomer_path"]
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"frozen candidate monomer missing or hash mismatch: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="node1")
    parser.add_argument("--ssh-bin", default="ssh.exe")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        candidates = read_tsv(root() / "inputs/candidates_128.tsv")
        if len(candidates) != 128:
            raise RuntimeError(f"expected 128 candidates, found {len(candidates)}")
        manifest_path = root() / "inputs/candidate_monomers_manifest.tsv"
        if args.verify_only:
            verify_manifest(candidates, read_tsv(manifest_path))
            return 0
        download(candidates, args.host, args.ssh_bin)
        manifest = build_manifest(candidates)
        write_tsv(manifest_path, manifest, FIELDS)
        verify_manifest(candidates, manifest)
        write_json(
            root() / "reports/candidate_monomer_freeze_summary.json",
            {
                "status": "OK",
                "candidate_count": len(manifest),
                "manifest": str(manifest_path.relative_to(root())),
                "manifest_sha256": sha256_file(manifest_path),
                "total_bytes": sum(int(row["size_bytes"]) for row in manifest),
                "source_remote_root": str(REMOTE_ROOT),
            },
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
