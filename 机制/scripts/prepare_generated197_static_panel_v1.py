#!/usr/bin/env python3
"""Freeze two representative docking poses for generated Top3000 QC197.

This is the generated-candidate equivalent of the old Top200 static-panel
preparation.  It reuses completed compact HADDOCK archives; no docking is
launched.  One representative is chosen independently for 8X6B and 9E6Y with
the frozen order STRICT_A, model strict-A fraction, HADDOCK score, seed, job ID.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFORMATIONS = ("8x6b", "9e6y")
EXPECTED_SEEDS = {"42", "917", "1931", "3047"}
LABEL_PRIORITY = {"STRICT_A": 0, "SUPPORTED_AB": 1, "OTHER": 2}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def number(row: dict[str, str], key: str, default: float) -> float:
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def selection_key(row: dict[str, str]) -> tuple[float, float, float, int, str]:
    label = row.get("representative_pair_label", "").upper()
    return (
        LABEL_PRIORITY.get(label, 9),
        -number(row, "model_strict_a_fraction", -1.0),
        number(row, "haddock_score", math.inf),
        int(number(row, "seed", 10**9)),
        row.get("job_id", ""),
    )


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
    return location, int(member_name.endswith(".gz")), member.name


def extract_model(archive_path: Path, model: str) -> tuple[bytes, str]:
    with tarfile.open(archive_path, mode="r:*") as archive:
        matches = [
            (key, member)
            for member in archive.getmembers()
            if (key := member_key(member, model)) is not None
        ]
        if not matches:
            raise RuntimeError(f"representative model absent from {archive_path}: {model}")
        _key, member = sorted(matches, key=lambda pair: pair[0])[0]
        handle = archive.extractfile(member)
        if handle is None:
            raise RuntimeError(f"cannot read {member.name} from {archive_path}")
        payload = handle.read()
        if member.name.endswith(".gz") or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
    if not payload.startswith((b"ATOM", b"REMARK", b"MODEL", b"HEADER")):
        raise RuntimeError(f"not a PDB payload: {archive_path}")
    return payload, member.name


def chain_set(payload: bytes) -> str:
    chains = {
        line[21:22].decode("ascii")
        for line in payload.splitlines()
        if line.startswith((b"ATOM  ", b"HETATM")) and len(line) >= 22
    }
    return "".join(sorted(chains))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qc-eligible", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--vhh-eval", type=Path, required=True)
    parser.add_argument("--combined-qc-rank", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    qc_rows = read_tsv(args.qc_eligible)
    if len(qc_rows) != 197:
        raise ValueError(f"expected 197 QC eligible candidates, got {len(qc_rows)}")
    qc_by_id = {row["candidate_id"]: row for row in qc_rows}
    if len(qc_by_id) != 197:
        raise ValueError("QC candidate IDs are not unique")
    vhh_by_id = {row["id"]: row for row in read_tsv(args.vhh_eval)}
    if not set(qc_by_id).issubset(vhh_by_id):
        raise ValueError("VHH evaluation lacks one or more QC candidate IDs")
    combined_by_id = {
        row["candidate_id"]: row for row in read_tsv(args.combined_qc_rank)
    }
    if not set(qc_by_id).issubset(combined_by_id):
        raise ValueError("combined QC rank lacks generated QC candidate IDs")

    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    protocol_values: set[str] = set()
    for row in read_tsv(args.job_results):
        candidate_id = row.get("candidate_id", "")
        if candidate_id in qc_by_id:
            by_candidate[candidate_id].append(row)
    manifest: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    pdb_dir = args.out / "inputs" / "pdb"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    for candidate_id in sorted(qc_by_id):
        candidate_jobs = by_candidate[candidate_id]
        if len(candidate_jobs) != 8:
            failures.append({"candidate_id": candidate_id, "reason": f"expected_8_jobs_got_{len(candidate_jobs)}"})
            continue
        if {row.get("seed", "") for row in candidate_jobs} != EXPECTED_SEEDS:
            failures.append({"candidate_id": candidate_id, "reason": "seed_set_mismatch"})
            continue
        vhh = vhh_by_id[candidate_id]
        cdrs = {
            "cdr1": vhh.get("imgt_cdr1", ""),
            "cdr2": vhh.get("imgt_cdr2", ""),
            "cdr3": vhh.get("imgt_cdr3", ""),
        }
        if not all(cdrs.values()):
            failures.append({"candidate_id": candidate_id, "reason": "missing_imgt_cdr"})
            continue
        for conformation in CONFORMATIONS:
            choices = [
                row
                for row in candidate_jobs
                if row.get("conformation", "").lower() == conformation
                and row.get("state", "").upper() == "SUCCESS"
                and row.get("representative_model", "")
            ]
            if not choices:
                failures.append({"candidate_id": candidate_id, "reason": f"no_successful_{conformation}"})
                continue
            chosen = sorted(choices, key=selection_key)[0]
            archive_path = args.archive_root / f"{chosen['job_id']}.tar.gz"
            if not archive_path.is_file():
                failures.append({"candidate_id": candidate_id, "reason": f"archive_absent:{chosen['job_id']}"})
                continue
            try:
                payload, member = extract_model(archive_path, chosen["representative_model"])
            except Exception as exc:  # receipt contains a candidate-scoped error only
                failures.append({"candidate_id": candidate_id, "reason": f"extract_error:{type(exc).__name__}"})
                continue
            chains = chain_set(payload)
            if not {"A", "T"}.issubset(chains):
                failures.append({"candidate_id": candidate_id, "reason": f"chains_missing:{chains}"})
                continue
            output = pdb_dir / f"{chosen['job_id']}.pdb"
            payload_hash = sha256_bytes(payload)
            if output.exists():
                if sha256_file(output) != payload_hash:
                    raise RuntimeError(f"frozen PDB hash mismatch: {output}")
            else:
                temporary = output.with_suffix(".pdb.tmp")
                temporary.write_bytes(payload)
                temporary.replace(output)
            protocol_values.add("8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3")
            manifest.append(
                {
                    "static_job_id": chosen["job_id"],
                    "candidate_id": candidate_id,
                    "top200_rank": combined_by_id[candidate_id].get("merged_common4_qc_geometry_rank", ""),
                    "selection_channel": combined_by_id[candidate_id].get("source_panel_membership", ""),
                    "route": combined_by_id[candidate_id].get("source_route", ""),
                    "parent_cluster": f"GENERATED_{qc_by_id[candidate_id].get('structure_selection_route','').upper()}_{qc_by_id[candidate_id].get('rfantibody_patch','') or 'FIXED_POSE_MPNN'}",
                    "cdr1": cdrs["cdr1"],
                    "cdr2": cdrs["cdr2"],
                    "cdr3": cdrs["cdr3"],
                    "conformation": conformation,
                    "seed": chosen["seed"],
                    "representative_pair_label": chosen.get("representative_pair_label", ""),
                    "representative_model": chosen["representative_model"],
                    "haddock_score": chosen.get("haddock_score", ""),
                    "air_energy": chosen.get("air_energy", ""),
                    "model_strict_a_fraction": chosen.get("model_strict_a_fraction", ""),
                    "source_job_hash": chosen.get("job_hash", ""),
                    "source_archive": str(archive_path),
                    "source_archive_member": member,
                    "frozen_pdb": str(output),
                    "frozen_pdb_sha256": payload_hash,
                    "chain_set": chains,
                }
            )
    if failures:
        write_tsv(args.out / "STATIC_PREPARE_FAILURES.tsv", failures)
        raise RuntimeError(f"generated static preparation failed for {len(failures)} records")
    if len(manifest) != 394 or len({row["static_job_id"] for row in manifest}) != 394:
        raise RuntimeError(f"expected 394 unique static jobs, got {len(manifest)}")
    for candidate_id in qc_by_id:
        confs = {row["conformation"] for row in manifest if row["candidate_id"] == candidate_id}
        if confs != set(CONFORMATIONS):
            raise RuntimeError(f"candidate lacks one conformation: {candidate_id}")
    manifest_path = args.out / "STATIC_JOB_MANIFEST.tsv"
    write_tsv(manifest_path, manifest)
    receipt = {
        "schema_version": "pvrig.generated_top3000.static_prepare.v1",
        "state": "STATIC_PANEL_PREPARED",
        "candidates": 197,
        "jobs": 394,
        "representative_selection": [
            "STRICT_A first",
            "model strict-A fraction descending",
            "HADDOCK score ascending",
            "seed ascending",
            "job ID ascending",
        ],
        "protocol_core_sha256": sorted(protocol_values),
        "input_hashes": {
            str(args.qc_eligible): sha256_file(args.qc_eligible),
            str(args.job_results): sha256_file(args.job_results),
            str(args.vhh_eval): sha256_file(args.vhh_eval),
            str(args.combined_qc_rank): sha256_file(args.combined_qc_rank),
        },
        "manifest_sha256": sha256_file(manifest_path),
        "claim_boundary": "Frozen completed docking poses only; no docking rerun and no wet-lab claim.",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.out / "STATIC_PREPARE_COMPLETE.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": 197, "jobs": 394}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
