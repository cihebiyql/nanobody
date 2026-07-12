#!/usr/bin/env python3
"""Stage RF2 inputs for primary seed42 plus seed43/44 enrichment runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_GPU_IDS = (1, 2, 3, 4, 5, 7)
DEFAULT_SEEDS = (42, 43, 44)
SOURCE_FIELDS = ("mpnn_pdb", "source_pdb", "pdb_path", "final_pdb", "staged_pdb")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def atomic_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def safe_candidate_id(value: str) -> bool:
    return bool(value) and value.replace("_", "").replace("-", "").replace(".", "").isalnum()


def source_path(row: dict[str, str]) -> Path:
    for field in SOURCE_FIELDS:
        value = row.get(field, "").strip()
        if value:
            return Path(value)
    raise ValueError(f"candidate {row.get('candidate_id', '<missing>')}: no source PDB field in {SOURCE_FIELDS}")


def ensure_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != target.resolve():
            raise ValueError(f"existing staged input would be overwritten: {link}")
        return
    link.symlink_to(target)


def prepare(
    candidates_tsv: Path,
    batch_root: Path,
    gpu_ids: list[int],
    seeds: list[int],
    expected_candidates: int = 1024,
) -> dict[str, object]:
    if not gpu_ids or len(set(gpu_ids)) != len(gpu_ids):
        raise ValueError("GPU IDs must be a non-empty unique list")
    if seeds != sorted(set(seeds)):
        raise ValueError("seeds must be unique and sorted so seed42 remains the primary run")
    if 42 not in seeds:
        raise ValueError("seed42 is required as the full primary RF2 gate")

    candidates = read_tsv(candidates_tsv)
    if expected_candidates and len(candidates) != expected_candidates:
        raise ValueError(f"expected {expected_candidates} candidates, found {len(candidates)} in {candidates_tsv}")
    if not candidates:
        raise ValueError("candidate TSV is empty")
    missing = {"candidate_id", "sequence"} - set(candidates[0])
    if missing:
        raise ValueError(f"candidate TSV is missing fields: {sorted(missing)}")

    batch_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    seen: set[str] = set()
    sorted_candidates = sorted(candidates, key=lambda item: item["candidate_id"])
    for index, row in enumerate(sorted_candidates):
        candidate_id = row["candidate_id"].strip()
        if candidate_id in seen:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        if not safe_candidate_id(candidate_id):
            raise ValueError(f"unsafe candidate_id for filesystem staging: {candidate_id!r}")
        seen.add(candidate_id)
        src = source_path(row)
        if not src.is_file():
            raise ValueError(f"candidate {candidate_id}: source PDB missing: {src}")
        src_sha = sha256_file(src)
        gpu_id = gpu_ids[index % len(gpu_ids)]
        for seed in seeds:
            seed_name = f"seed_{seed}"
            shard = f"gpu_{gpu_id}"
            shard_root = batch_root / "seeds" / seed_name / "shards" / shard
            staged_pdb = shard_root / "input" / f"{candidate_id}.pdb"
            output_pdb = shard_root / "output" / f"{candidate_id}_best.pdb"
            ensure_symlink(staged_pdb, src)
            manifest_rows.append(
                {
                    **row,
                    "candidate_id": candidate_id,
                    "seed": seed,
                    "seed_role": "primary_full_gate" if seed == 42 else "enrichment_after_seed42",
                    "gpu_id": gpu_id,
                    "shard": shard,
                    "source_pdb": str(src),
                    "source_pdb_sha256": src_sha,
                    "staged_pdb": str(staged_pdb),
                    "expected_output_pdb": str(output_pdb),
                    "old_gate_status": "PENDING_STRICT_SEED42" if seed == 42 else "NOT_APPLICABLE_ENRICHMENT_SEED",
                    "formal_multiseed_gate_status": "PENDING_SEED42_PRIMARY_BEFORE_ENRICHMENT",
                    "rf2_failure_label_policy": "rf2_fail_or_missing_is_not_a_negative_sample",
                }
            )

    manifest_path = batch_root / "rf2_multiseed_manifest.tsv"
    atomic_tsv(manifest_path, manifest_rows)
    counts_by_seed_gpu = Counter((int(row["seed"]), int(row["gpu_id"])) for row in manifest_rows)
    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates_tsv": str(candidates_tsv),
        "candidates_tsv_sha256": sha256_file(candidates_tsv),
        "candidate_count": len(candidates),
        "manifest_rows": len(manifest_rows),
        "seeds": seeds,
        "gpu_ids": gpu_ids,
        "primary_seed": 42,
        "primary_seed_min_outputs_for_enrichment": 1000,
        "seed_policy": "run seed42 to >=1000 RF2 outputs before enabling seed43/44 enrichment",
        "resume_policy": "runner builds per-launch todo inputs only for missing expected outputs",
        "overwrite_policy": "seed-specific output directories; existing expected outputs are never queued again",
        "failure_label_policy": "RF2 fail/missing is recorded as QC failure/missing, never as a negative training sample",
        "candidates_by_gpu": {str(k): v for k, v in sorted(Counter(int(r["gpu_id"]) for r in manifest_rows if int(r["seed"]) == 42).items())},
        "rows_by_seed_gpu": {f"seed_{seed}/gpu_{gpu}": count for (seed, gpu), count in sorted(counts_by_seed_gpu.items())},
        "manifest_tsv": str(manifest_path),
    }
    (batch_root / "rf2_multiseed_prepare_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def parse_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates_tsv", type=Path)
    parser.add_argument("batch_root", type=Path)
    parser.add_argument("--gpu-ids", default=",".join(str(x) for x in DEFAULT_GPU_IDS))
    parser.add_argument("--seeds", default=",".join(str(x) for x in DEFAULT_SEEDS))
    parser.add_argument("--expected-candidates", type=int, default=1024, help="set 0 to disable the fixed-count check")
    args = parser.parse_args()
    summary = prepare(
        args.candidates_tsv,
        args.batch_root,
        parse_csv_ints(args.gpu_ids),
        parse_csv_ints(args.seeds),
        args.expected_candidates,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
