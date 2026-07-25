#!/usr/bin/env python3
"""Fast, dependency-free integrity checks for the competition submission."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def fasta_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(">"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    ranked = tsv(ROOT / "data/submission/final_top50_ranked.tsv")
    trace = tsv(ROOT / "data/submission/candidate_traceability.tsv")
    top10 = tsv(ROOT / "data/submission/top10_priority.tsv")
    required = {
        "candidate_id",
        "sequence",
        "parent_id",
        "generation_method",
        "generation_seed",
        "cdr_modifications",
        "generation_model_version",
        "qc_official_validator_pass",
        "monomer_structure",
        "docking_protocol_sha256",
        "docking_seed_8X6B",
        "docking_seed_9E6Y",
        "R8_static_haddock_score",
        "R9_static_haddock_score",
        "Rdual_static_mean_haddock_score",
        "manual_review_status",
        "final_rank",
    }
    if len(ranked) != 50 or len(trace) != 50 or fasta_count(ROOT / "data/submission/final_top50_ranked.fasta") != 50:
        raise SystemExit("Top50 count check failed")
    if {row["candidate_id"] for row in ranked} != {row["candidate_id"] for row in trace}:
        raise SystemExit("candidate_id set differs between ranked and trace tables")
    missing = required - set(trace[0])
    if missing:
        raise SystemExit(f"traceability columns missing: {sorted(missing)}")
    if any(row["qc_official_validator_pass"].lower() not in {"true", "pass"} for row in trace):
        raise SystemExit("a submitted candidate lacks official validator pass")
    if not (ROOT / "data/submission/final50.official_submit.xlsx").is_file():
        raise SystemExit("official Excel export missing")
    poses = sorted((ROOT / "evidence/top10_poses").glob("*.pdb"))
    if len(poses) != 10 or len(top10) != 10:
        raise SystemExit("Top10 representative pose count failed")
    top10_ids = {row["candidate_id"] for row in top10}
    if any(not any(candidate_id in pose.name for candidate_id in top10_ids) for pose in poses):
        raise SystemExit("Top10 pose filename does not map to a Top10 candidate")
    banned = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if ".git" in rel.parts:
            continue
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache", ".conda", "cache", "logs"}:
            banned.append(str(rel))
        if path.is_file() and path.suffix in {".log", ".key", ".pem"}:
            banned.append(str(rel))
        if path.is_file() and path.stat().st_size > 100 * 1024 * 1024:
            banned.append(str(rel))
    if banned:
        raise SystemExit(f"non-lightweight payload detected: {banned}")
    checks = ROOT / "evidence/manifests/SHA256SUMS"
    expected_files: set[str] = set()
    failures = []
    for line in checks.read_text(encoding="utf-8").splitlines():
        expected, rel = line.split("  ", 1)
        expected_files.add(rel)
        path = ROOT / rel
        if not path.is_file() or sha256(path) != expected:
            failures.append(rel)
    if failures:
        raise SystemExit(f"checksum mismatch: {failures}")
    actual_files = {
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file()
        and path != checks
        and ".git" not in path.relative_to(ROOT).parts
        and "__pycache__" not in path.relative_to(ROOT).parts
        and ".pytest_cache" not in path.relative_to(ROOT).parts
    }
    if expected_files != actual_files:
        raise SystemExit(
            "checksum inventory differs from package files: "
            f"missing={sorted(actual_files - expected_files)} "
            f"unexpected={sorted(expected_files - actual_files)}"
        )
    print(json.dumps({"status": "ok", "top50": len(ranked), "top10_poses": len(poses), "checksums": "verified"}))


if __name__ == "__main__":
    main()
