#!/usr/bin/env python3
"""Freeze and extract two representative docking poses per Top200 candidate.

One pose is selected for each receptor conformation.  Selection is deterministic:
STRICT_A before SUPPORTED_AB, then higher model-level strict-A support, lower
HADDOCK score, lower seed, and finally job ID.  Existing docking is reused; this
script never launches docking.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import tarfile
from pathlib import Path
from typing import Any


CONFORMATIONS = ("8x6b", "9e6y")
LABEL_PRIORITY = {"STRICT_A": 0, "SUPPORTED_AB": 1, "OTHER": 2}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def member_key(member: tarfile.TarInfo, model: str) -> tuple[int, int, str] | None:
    if not member.isfile():
        return None
    member_name = Path(member.name).name
    model_plain = model[:-3] if model.endswith(".gz") else model
    member_plain = member_name[:-3] if member_name.endswith(".gz") else member_name
    if member_plain != model_plain:
        return None
    if "/6_seletopclusts/" in member.name:
        location = 0
    elif "/selected_models/" in member.name:
        location = 1
    else:
        location = 2
    compressed = 1 if member_name.endswith(".gz") else 0
    return location, compressed, member.name


def extract_model(archive_path: Path, model: str) -> tuple[bytes, str]:
    if archive_path.name.endswith(".tar.zst"):
        raise RuntimeError(
            f"tar.zst extraction is intentionally unsupported without a frozen "
            f"decompressor contract: {archive_path}"
        )
    with tarfile.open(archive_path, mode="r:*") as archive:
        matches = [
            (key, member)
            for member in archive.getmembers()
            if (key := member_key(member, model)) is not None
        ]
        if not matches:
            raise RuntimeError(f"{archive_path}: representative model missing: {model}")
        _key, member = sorted(matches, key=lambda item: item[0])[0]
        handle = archive.extractfile(member)
        if handle is None:
            raise RuntimeError(f"{archive_path}: cannot extract {member.name}")
        payload = handle.read()
        if member.name.endswith(".gz") or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        if not payload.startswith((b"ATOM", b"REMARK", b"MODEL", b"HEADER")):
            raise RuntimeError(f"{archive_path}: extracted payload is not a PDB")
        return payload, member.name


def chain_set(payload: bytes) -> str:
    chains = {
        line[21:22].decode("ascii")
        for line in payload.splitlines()
        if line.startswith((b"ATOM  ", b"HETATM")) and len(line) >= 22
    }
    return "".join(sorted(chains))


def selection_key(row: dict[str, str]) -> tuple[float, float, float, int, str]:
    label = row.get("representative_pair_label", "").upper()
    return (
        LABEL_PRIORITY.get(label, 9),
        -number(row.get("model_strict_a_fraction"), -1.0),
        number(row.get("haddock_score"), math.inf),
        int(number(row.get("seed"), 10**9)),
        row.get("job_id", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--old-jobs", type=Path, required=True)
    parser.add_argument("--c2-jobs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    top = read_tsv(args.top200)
    if len(top) != 200 or len({row["candidate_id"] for row in top}) != 200:
        raise ValueError("Top200 must contain exactly 200 unique candidates")
    top_by_id = {row["candidate_id"]: row for row in top}
    jobs = read_tsv(args.old_jobs) + read_tsv(args.c2_jobs)
    by_candidate: dict[str, list[dict[str, str]]] = {
        candidate_id: [] for candidate_id in top_by_id
    }
    for row in jobs:
        candidate_id = row.get("candidate_id") or row.get("entity_id") or ""
        if (
            candidate_id in by_candidate
            and row.get("state", "").upper() == "SUCCESS"
            and row.get("representative_model")
            and row.get("archive_path")
            and row.get("conformation", "").lower() in CONFORMATIONS
        ):
            by_candidate[candidate_id].append(row)

    args.out.mkdir(parents=True, exist_ok=True)
    pdb_dir = args.out / "inputs" / "pdb"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for candidate_id in sorted(top_by_id):
        top_row = top_by_id[candidate_id]
        candidate_jobs = by_candidate[candidate_id]
        for conformation in CONFORMATIONS:
            choices = [
                row
                for row in candidate_jobs
                if row.get("conformation", "").lower() == conformation
            ]
            if not choices:
                failures.append(
                    {
                        "candidate_id": candidate_id,
                        "conformation": conformation,
                        "reason": "no_successful_representative_job",
                    }
                )
                continue
            chosen = sorted(choices, key=selection_key)[0]
            archive_path = Path(chosen["archive_path"])
            payload, archive_member = extract_model(
                archive_path, chosen["representative_model"]
            )
            chains = chain_set(payload)
            if not {"A", "T"}.issubset(set(chains)):
                failures.append(
                    {
                        "candidate_id": candidate_id,
                        "conformation": conformation,
                        "reason": f"required_chains_A_T_missing:{chains}",
                    }
                )
                continue
            output_path = pdb_dir / f"{chosen['job_id']}.pdb"
            payload_hash = sha256_bytes(payload)
            if output_path.exists():
                if sha256_file(output_path) != payload_hash:
                    raise RuntimeError(f"frozen PDB mismatch: {output_path}")
            else:
                temporary = output_path.with_suffix(".pdb.tmp")
                temporary.write_bytes(payload)
                temporary.replace(output_path)
            manifest.append(
                {
                    "static_job_id": chosen["job_id"],
                    "candidate_id": candidate_id,
                    "top200_rank": top_row.get("top200_rank", ""),
                    "selection_channel": top_row.get("selection_channel", ""),
                    "route": top_row.get("route", ""),
                    "parent_cluster": top_row.get("parent_cluster", ""),
                    "cdr1": top_row.get("cdr1", ""),
                    "cdr2": top_row.get("cdr2", ""),
                    "cdr3": top_row.get("cdr3", ""),
                    "conformation": conformation,
                    "seed": chosen.get("seed", ""),
                    "representative_pair_label": chosen.get(
                        "representative_pair_label", ""
                    ),
                    "representative_model": chosen.get("representative_model", ""),
                    "haddock_score": chosen.get("haddock_score", ""),
                    "air_energy": chosen.get("air_energy", ""),
                    "model_strict_a_fraction": chosen.get(
                        "model_strict_a_fraction", ""
                    ),
                    "native_hotspot_overlap": chosen.get(
                        "native_hotspot_overlap", ""
                    ),
                    "cross_hotspot_overlap": chosen.get(
                        "cross_hotspot_overlap", ""
                    ),
                    "native_total_occlusion": chosen.get(
                        "native_total_occlusion", ""
                    ),
                    "cross_total_occlusion": chosen.get(
                        "cross_total_occlusion", ""
                    ),
                    "native_cdr3_occlusion": chosen.get(
                        "native_cdr3_occlusion", ""
                    ),
                    "cross_cdr3_occlusion": chosen.get(
                        "cross_cdr3_occlusion", ""
                    ),
                    "native_clash_atom_pairs": chosen.get(
                        "native_clash_atom_pairs", ""
                    ),
                    "cross_clash_atom_pairs": chosen.get(
                        "cross_clash_atom_pairs", ""
                    ),
                    "native_overlay_rmsd_a": chosen.get(
                        "native_overlay_rmsd_a", ""
                    ),
                    "cross_overlay_rmsd_a": chosen.get(
                        "cross_overlay_rmsd_a", ""
                    ),
                    "source_job_hash": chosen.get("job_hash", ""),
                    "source_protocol_sha256": chosen.get(
                        "protocol_core_sha256", ""
                    ),
                    "source_archive": str(archive_path),
                    "source_archive_member": archive_member,
                    "frozen_pdb": str(output_path),
                    "frozen_pdb_sha256": payload_hash,
                    "chain_set": chains,
                }
            )

    if failures:
        write_tsv(args.out / "STATIC_PREPARE_FAILURES.tsv", failures)
        raise RuntimeError(f"Top200 static preparation had {len(failures)} failures")
    if len(manifest) != 400:
        raise RuntimeError(f"expected 400 static jobs, got {len(manifest)}")
    if len({row["static_job_id"] for row in manifest}) != 400:
        raise RuntimeError("static job IDs are not unique")
    manifest_path = args.out / "STATIC_JOB_MANIFEST.tsv"
    write_tsv(manifest_path, manifest)
    receipt = {
        "schema_version": "pvrig.top200.static_prepare.v1",
        "state": "STATIC_PANEL_PREPARED",
        "candidates": 200,
        "jobs": 400,
        "conformation_counts": {
            conformation: sum(
                row["conformation"] == conformation for row in manifest
            )
            for conformation in CONFORMATIONS
        },
        "input_hashes": {
            str(args.top200): sha256_file(args.top200),
            str(args.old_jobs): sha256_file(args.old_jobs),
            str(args.c2_jobs): sha256_file(args.c2_jobs),
        },
        "manifest_sha256": sha256_file(manifest_path),
        "claim_boundary": (
            "Frozen existing docking poses only; no new docking and no wet-lab claim."
        ),
    }
    receipt_path = args.out / "STATIC_PREPARE_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": 200, "jobs": 400}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
