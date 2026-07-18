#!/usr/bin/env python3
"""Publish multiple terminal monomer lanes as one portable docking input."""

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def parse_lane(value: str) -> tuple[str, Path, Path]:
    parts = value.split("::", 2)
    if len(parts) != 3 or not parts[0]:
        raise argparse.ArgumentTypeError("lane must be NAME::CANDIDATE_MANIFEST::MONOMER_ROOT")
    return parts[0], Path(parts[1]), Path(parts[2])


def publish(lanes: list[tuple[str, Path, Path]], output_root: Path) -> dict[str, object]:
    if not lanes or len({name for name, _, _ in lanes}) != len(lanes):
        raise RuntimeError("lane_names_missing_or_not_unique")
    staging = output_root.with_name(f".{output_root.name}.staging.{os.getpid()}")
    if output_root.exists() or staging.exists():
        raise FileExistsError(output_root if output_root.exists() else staging)
    (staging / "monomers").mkdir(parents=True)
    all_fields: list[str] = []
    selected: list[dict[str, str]] = []
    portable: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    lane_receipts: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    try:
        for lane_name, candidate_manifest, monomer_root in lanes:
            complete_path = monomer_root / "status/COMPLETE.json"
            monomer_manifest_path = monomer_root / "outputs/monomer_manifest.tsv"
            if not complete_path.is_file() or not monomer_manifest_path.is_file():
                raise RuntimeError(f"monomer_batch_not_complete:{lane_name}")
            complete = json.loads(complete_path.read_text())
            if complete.get("status") != "PASS_MONOMER_BATCH_TERMINAL":
                raise RuntimeError(f"invalid_monomer_terminal_status:{lane_name}:{complete.get('status')}")
            if complete.get("manifest_sha256") != sha256(monomer_manifest_path):
                raise RuntimeError(f"monomer_manifest_terminal_hash_mismatch:{lane_name}")
            fields, candidates = read_tsv(candidate_manifest)
            _, monomers = read_tsv(monomer_manifest_path)
            for field in fields + ["source_lane"]:
                if field not in all_fields:
                    all_fields.append(field)
            if len(candidates) != len(monomers):
                raise RuntimeError(f"lane_count_closure_failed:{lane_name}")
            if [row["candidate_id"] for row in candidates] != [row["candidate_id"] for row in monomers]:
                raise RuntimeError(f"candidate_monomer_order_mismatch:{lane_name}")
            lane_success = 0
            lane_failures = 0
            for candidate, monomer in zip(candidates, monomers):
                candidate_id = candidate["candidate_id"]
                sequence_hash = candidate["sequence_sha256"]
                if candidate_id in seen_ids or sequence_hash in seen_hashes:
                    raise RuntimeError(f"cross_lane_duplicate:{lane_name}:{candidate_id}")
                seen_ids.add(candidate_id)
                seen_hashes.add(sequence_hash)
                if monomer["sequence_sha256"] != sequence_hash:
                    raise RuntimeError(f"sequence_hash_mismatch:{candidate_id}")
                if monomer["monomer_status"] != "SUCCESS":
                    failures.append({
                        "candidate_id": candidate_id,
                        "sequence_sha256": sequence_hash,
                        "source_lane": lane_name,
                        "technical_failure_reason": monomer.get("technical_failure_reason", ""),
                    })
                    lane_failures += 1
                    continue
                source_pdb = Path(monomer["pdb_path"])
                if not source_pdb.is_file() or sha256(source_pdb) != monomer["pdb_sha256"]:
                    raise RuntimeError(f"monomer_pdb_hash_mismatch:{candidate_id}")
                destination = staging / "monomers" / f"{candidate_id}.pdb"
                shutil.copy2(source_pdb, destination)
                if sha256(destination) != monomer["pdb_sha256"]:
                    raise RuntimeError(f"portable_copy_hash_mismatch:{candidate_id}")
                candidate_row = dict(candidate)
                candidate_row["source_lane"] = lane_name
                selected.append(candidate_row)
                portable.append({
                    "candidate_id": candidate_id,
                    "sequence_sha256": sequence_hash,
                    "frozen_monomer_path": f"monomers/{candidate_id}.pdb",
                    "source_chain": "A",
                    "sha256": monomer["pdb_sha256"],
                    "size_bytes": str(destination.stat().st_size),
                    "source_lane": lane_name,
                    "claim_boundary": CLAIM,
                })
                lane_success += 1
            lane_receipts.append({
                "lane": lane_name,
                "source_candidate_count": len(candidates),
                "dockable_candidate_count": lane_success,
                "technical_failure_count": lane_failures,
                "candidate_manifest_sha256": sha256(candidate_manifest),
                "monomer_complete_sha256": sha256(complete_path),
                "monomer_manifest_sha256": sha256(monomer_manifest_path),
            })
        if not selected:
            raise RuntimeError("zero_successful_monomers")
        normalized = [{field: row.get(field, "") for field in all_fields} for row in selected]
        write_tsv(staging / "candidates.tsv", normalized, all_fields)
        write_tsv(staging / "monomer_manifest.tsv", portable, list(portable[0]))
        if failures:
            write_tsv(staging / "technical_failures.tsv", failures, list(failures[0]))
        receipt = {
            "schema_version": "phase2_v4_i_round2_combined_docking_input_v1",
            "status": "PASS_PORTABLE_RESEARCH_DOCKING_INPUT_READY",
            "source_candidate_count": len(seen_ids),
            "dockable_candidate_count": len(selected),
            "monomer_technical_failure_count": len(failures),
            "candidate_manifest_sha256": sha256(staging / "candidates.tsv"),
            "monomer_manifest_sha256": sha256(staging / "monomer_manifest.tsv"),
            "monomer_set_sha256": hashlib.sha256("".join(row["sha256"] for row in portable).encode()).hexdigest(),
            "lanes": lane_receipts,
            "published_at_utc": datetime.now(timezone.utc).isoformat(),
            "claim_boundary": CLAIM,
        }
        atomic_json(staging / "INPUT_RECEIPT.json", receipt)
        os.replace(staging, output_root)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", action="append", type=parse_lane, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.lane, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
