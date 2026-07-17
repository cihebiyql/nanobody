#!/usr/bin/env python3
"""Publish successful V4-H monomers as a portable, hash-closed docking input."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CLAIM = (
    "Portable sequence and monomer input for computational dual-conformation docking only; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    return list(reader.fieldnames or []), rows


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def atomic_json(path: Path, payload: object) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def publish(candidate_manifest: Path, monomer_root: Path, output_root: Path) -> dict[str, object]:
    complete_path = monomer_root / "status" / "COMPLETE.json"
    monomer_manifest_path = monomer_root / "outputs" / "monomer_manifest.tsv"
    if not complete_path.is_file() or not monomer_manifest_path.is_file():
        raise RuntimeError("monomer_batch_not_complete")
    complete = json.loads(complete_path.read_text())
    if complete.get("status") != "PASS_MONOMER_BATCH_TERMINAL":
        raise RuntimeError(f"invalid_monomer_terminal_status:{complete.get('status')}")
    if complete.get("manifest_sha256") != sha256(monomer_manifest_path):
        raise RuntimeError("monomer_manifest_terminal_hash_mismatch")

    candidate_fields, candidates = read_tsv(candidate_manifest)
    _, monomers = read_tsv(monomer_manifest_path)
    by_candidate = {row["candidate_id"]: row for row in candidates}
    if len(by_candidate) != len(candidates) or len(monomers) != len(candidates):
        raise RuntimeError("candidate_or_monomer_identity_closure_failed")
    if [row["candidate_id"] for row in monomers] != [row["candidate_id"] for row in candidates]:
        raise RuntimeError("candidate_monomer_order_mismatch")

    staging = output_root.with_name(f".{output_root.name}.staging.{os.getpid()}")
    if output_root.exists() or staging.exists():
        raise FileExistsError(output_root if output_root.exists() else staging)
    (staging / "monomers").mkdir(parents=True)
    selected_candidates: list[dict[str, str]] = []
    portable_monomers: list[dict[str, str]] = []
    technical_failures: list[dict[str, str]] = []
    try:
        for row in monomers:
            candidate_id = row["candidate_id"]
            source = by_candidate[candidate_id]
            if row["sequence_sha256"] != source["sequence_sha256"]:
                raise RuntimeError(f"sequence_hash_mismatch:{candidate_id}")
            if row["monomer_status"] != "SUCCESS":
                technical_failures.append(
                    {
                        "candidate_id": candidate_id,
                        "sequence_sha256": row["sequence_sha256"],
                        "technical_failure_reason": row["technical_failure_reason"],
                    }
                )
                continue
            pdb = Path(row["pdb_path"])
            if not pdb.is_file() or sha256(pdb) != row["pdb_sha256"]:
                raise RuntimeError(f"monomer_pdb_hash_mismatch:{candidate_id}")
            destination = staging / "monomers" / f"{candidate_id}.pdb"
            shutil.copy2(pdb, destination)
            if sha256(destination) != row["pdb_sha256"]:
                raise RuntimeError(f"portable_copy_hash_mismatch:{candidate_id}")
            selected_candidates.append(source)
            portable_monomers.append(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": row["sequence_sha256"],
                    "frozen_monomer_path": f"monomers/{candidate_id}.pdb",
                    "source_chain": "A",
                    "sha256": row["pdb_sha256"],
                    "size_bytes": str(destination.stat().st_size),
                    "claim_boundary": CLAIM,
                }
            )
        if not selected_candidates:
            raise RuntimeError("zero_successful_monomers")
        write_tsv(staging / "candidates.tsv", selected_candidates, candidate_fields)
        write_tsv(
            staging / "monomer_manifest.tsv",
            portable_monomers,
            list(portable_monomers[0]),
        )
        if technical_failures:
            write_tsv(
                staging / "technical_failures.tsv",
                technical_failures,
                list(technical_failures[0]),
            )
        payload = {
            "schema_version": "phase2_v4_h_research_docking_input_receipt_v1",
            "status": "PASS_PORTABLE_RESEARCH_DOCKING_INPUT_READY",
            "source_candidate_count": len(candidates),
            "dockable_candidate_count": len(selected_candidates),
            "monomer_technical_failure_count": len(technical_failures),
            "candidate_manifest_sha256": sha256(staging / "candidates.tsv"),
            "monomer_manifest_sha256": sha256(staging / "monomer_manifest.tsv"),
            "monomer_set_sha256": hashlib.sha256(
                "".join(row["sha256"] for row in portable_monomers).encode()
            ).hexdigest(),
            "source_monomer_complete_sha256": sha256(complete_path),
            "source_monomer_manifest_sha256": sha256(monomer_manifest_path),
            "published_at_utc": now(),
            "claim_boundary": CLAIM,
        }
        atomic_json(staging / "INPUT_RECEIPT.json", payload)
        os.replace(staging, output_root)
        return payload
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--monomer-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.candidate_manifest, args.monomer_root, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
