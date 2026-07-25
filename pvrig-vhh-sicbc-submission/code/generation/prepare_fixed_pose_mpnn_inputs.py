#!/usr/bin/env python3
"""Normalize frozen HADDOCK positive poses for RFantibody ProteinMPNN design."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def normalize_pose(source: Path, target: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    seen_residues: set[tuple[str, str]] = set()
    output = []
    for raw in source.read_text(encoding="ascii", errors="replace").splitlines():
        line = raw
        if line.startswith(("ATOM  ", "HETATM", "TER   ")) and len(line) > 21:
            chain = line[21]
            if chain == "A":
                line = line[:21] + "H" + line[22:]
            elif chain == "B":
                line = line[:21] + "T" + line[22:]
            elif chain.strip():
                raise ValueError(f"unexpected chain {chain!r} in {source}")
        if line.startswith("ATOM  ") and len(line) >= 27 and line[12:16].strip() == "CA":
            key = (line[21], line[22:27])
            if key not in seen_residues:
                seen_residues.add(key)
                counts[line[21]] += 1
        output.append(line)
    if not 95 <= counts["H"] <= 160 or counts["T"] < 50:
        raise ValueError(f"unexpected normalized chain lengths in {source}: {dict(counts)}")
    target.write_text("\n".join(output) + "\n", encoding="ascii")
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seqs-per-pose", type=int, default=800)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()
    if args.seqs_per_pose <= 0 or args.temperature <= 0:
        parser.error("seqs-per-pose and temperature must be positive")
    manifest_path = args.pose_manifest.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    pose_dir = output / "poses_ht"
    pose_dir.mkdir()
    rows = read_tsv(manifest_path)
    if len(rows) != 99:
        raise ValueError(f"expected 99 frozen poses, found {len(rows)}")
    tasks = []
    for index, row in enumerate(rows, start=1):
        source = Path(row["frozen_pose"])
        if sha256_file(source) != row["pose_sha256"]:
            raise ValueError(f"source pose SHA mismatch: {source}")
        pose_id = f"FPMPNN_{index:03d}_{row['candidate_id']}__pose{int(row['pose_rank']):02d}"
        target = pose_dir / f"{pose_id}.pdb"
        chain_lengths = normalize_pose(source, target)
        tasks.append(
            {
                "pose_id": pose_id,
                "source_candidate_id": row["candidate_id"],
                "source_molecule_name": row["molecule_name"],
                "source_pose_rank": row["pose_rank"],
                "source_pose": str(source),
                "source_pose_sha256": row["pose_sha256"],
                "normalized_pose_relpath": str(target.relative_to(output)),
                "normalized_pose_sha256": sha256_file(target),
                "normalized_vhh_chain": "H",
                "normalized_target_chain": "T",
                "vhh_length": chain_lengths["H"],
                "target_length": chain_lengths["T"],
                "loop_string": "H1,H2,H3",
                "seqs_per_pose": args.seqs_per_pose,
                "temperature": args.temperature,
                "physical_gpu": 1 + ((index - 1) % 7),
                "worker_slot": ((index - 1) // 7) % 3,
                "status": "PENDING_SMOKE",
            }
        )
    task_path = output / "fixed_pose_mpnn_tasks.tsv"
    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tasks[0]), delimiter="\t")
        writer.writeheader(); writer.writerows(tasks)
    summary = {
        "status": "INPUTS_PREPARED_NOT_YET_SMOKE_VALIDATED",
        "pose_count": len(tasks),
        "source_candidate_count": len({row["source_candidate_id"] for row in tasks}),
        "seqs_per_pose": args.seqs_per_pose,
        "raw_sequence_target": len(tasks) * args.seqs_per_pose,
        "exact_unique_freeze_target": 75_000,
        "gpu_plan": "physical GPUs 1-7, three workers per GPU after RFantibody controller completes",
        "chain_mapping": "H=VHH (source A); T=PVRIG (source B)",
        "scientific_boundary": "Positive-pose-conditioned ProteinMPNN sequence proposal; not affinity or blocking proof.",
    }
    (output / "PREPARED.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(output)}\n" for path in files),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
