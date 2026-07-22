#!/usr/bin/env python3
"""Prepare, but do not start, expanded RFantibody and fixed-pose MPNN campaigns.

The new campaigns request at least twice as many deterministic samples as the
75k campaigns. RFantibody includes a hard-QC capacity margin for glycosylation
motif loss and exact duplicates. The later global freeze removes overlap.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


RF_BACKBONES_PER_ARM = 360


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_components(source: Path, target: Path, names: tuple[str, ...]) -> None:
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True)
    for name in names:
        shutil.copytree(source / name, target / name, symlinks=True)
    (target / "logs").mkdir()
    (target / "status").mkdir()


def rewrite_tsv(path: Path, updates: dict[str, str]) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError(f"empty TSV: {path}")
    for row in rows:
        row.update(updates)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def replace_required(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old not in text:
            raise ValueError(f"required text not found in {path}: {old}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def manifest(root: Path) -> None:
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "PREPARED_SHA256SUMS")
    (root / "PREPARED_SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n" for path in files),
        encoding="utf-8",
    )


def validate_mpnn_pose_inputs(root: Path) -> int:
    table = root / "inputs/fixed_pose_mpnn_tasks.tsv"
    with table.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    paths: set[Path] = set()
    for row in rows:
        path = root / "inputs" / row["normalized_pose_relpath"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if sha256_file(path) != row["normalized_pose_sha256"]:
            raise ValueError(f"normalized pose hash mismatch: {path}")
        paths.add(path.resolve())
    if len(rows) != 99 or len(paths) != 99:
        raise ValueError(f"expected 99 unique fixed poses, rows={len(rows)} paths={len(paths)}")
    return len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rf-source", type=Path, required=True)
    parser.add_argument("--rf-target", type=Path, required=True)
    parser.add_argument("--mpnn-source", type=Path, required=True)
    parser.add_argument("--mpnn-target", type=Path, required=True)
    args = parser.parse_args()

    rf_source, rf_target = args.rf_source.resolve(), args.rf_target.resolve()
    mpnn_source, mpnn_target = args.mpnn_source.resolve(), args.mpnn_target.resolve()

    copy_components(rf_source, rf_target, ("inputs", "config", "scripts"))
    primary_rows = rewrite_tsv(
        rf_target / "config/generation_arms_primary.tsv",
        {"target_backbones": str(RF_BACKBONES_PER_ARM)},
    )
    rewrite_tsv(
        rf_target / "config/generation_arms.tsv",
        {"target_backbones": str(RF_BACKBONES_PER_ARM)},
    )
    replace_required(
        rf_target / "scripts/run_rfantibody_75k_controller.sh",
        {
            "RFantibody 75k raw target 90432; 36 arms; 157 backbones x 16 sequences":
                "RFantibody 150k capacity-safe raw target 207360; 36 arms; 360 backbones x 16 sequences",
            "balanced exact-unique RFantibody target 75000": "balanced exact-unique RFantibody target 150000",
            "--target 75000": "--target 150000",
            "75000 exact-unique RFantibody candidates frozen": "150000 exact-unique RFantibody candidates frozen",
        },
    )
    rf_receipt = {
        "status": "PREPARED_NOT_STARTED",
        "campaign": "pvrig_1m_rfantibody150k_v1_20260722",
        "source_campaign": str(rf_source),
        "arms": primary_rows,
        "target_backbones_per_arm": RF_BACKBONES_PER_ARM,
        "sequences_per_backbone": 16,
        "raw_target": primary_rows * RF_BACKBONES_PER_ARM * 16,
        "freeze_target": 150000,
        "capacity_margin_basis": "partial hard-QC sample projected 82.2% exact-unique pass; 207360 raw projects about 170450",
        "duplicate_semantics": "Deterministic first-half overlap with the 75k campaign is expected and must be removed by global exact-sequence deduplication.",
    }
    (rf_target / "PREPARED.json").write_text(json.dumps(rf_receipt, indent=2, sort_keys=True) + "\n")
    manifest(rf_target)

    copy_components(mpnn_source, mpnn_target, ("inputs", "scripts"))
    task_rows = rewrite_tsv(mpnn_target / "inputs/fixed_pose_mpnn_tasks.tsv", {"seqs_per_pose": "2400"})
    replace_required(
        mpnn_target / "scripts/run_fixed_pose_mpnn_controller.sh",
        {
            "99 poses; 118800 raw sequence PDBs; 7 GPUs x 3 workers":
                "99 poses; 237600 raw sequence PDBs; 7 GPUs x 3 workers",
            "run_21_workers generation \"$RUN_ROOT/inputs/fixed_pose_mpnn_tasks.tsv\" 1200":
                "run_21_workers generation \"$RUN_ROOT/inputs/fixed_pose_mpnn_tasks.tsv\" 2400",
            "if len(paths)!=sum(expected.values()):": "if len(paths)!=sum(expected.values()):",
            "118800 raw sequence PDBs; postprocessing/QC required":
                "237600 raw sequence PDBs; postprocessing/QC required",
            "--target 75000": "--target 150000",
            "summary['raw_output_count']!=118800 or summary['frozen_count']!=75000":
                "summary['raw_output_count']!=237600 or summary['frozen_count']!=150000",
            "fixed_pose_candidates_frozen75k.tsv.gz": "fixed_pose_candidates_frozen150k.tsv.gz",
            "if rows!=75000: raise SystemExit('frozen TSV row mismatch: {}'.format(rows))":
                "if rows!=150000: raise SystemExit('frozen TSV row mismatch: {}'.format(rows))",
            "75000 exact-unique fast-QC fixed-pose candidates frozen; ANARCI still required":
                "150000 exact-unique fast-QC fixed-pose candidates frozen; ANARCI still required",
        },
    )
    replace_required(
        mpnn_target / "scripts/collect_fixed_pose_mpnn_candidates.py",
        {
            'data/"fixed_pose_candidates_frozen75k.tsv.gz"': 'data/"fixed_pose_candidates_frozen150k.tsv.gz"',
            'data/"fixed_pose_candidates_frozen75k.fasta.gz"': 'data/"fixed_pose_candidates_frozen150k.fasta.gz"',
        },
    )
    pose_inputs = validate_mpnn_pose_inputs(mpnn_target)
    controller_text = (mpnn_target / "scripts/run_fixed_pose_mpnn_controller.sh").read_text()
    stale_tokens = ("rows!=75000", "118800 raw sequence PDBs", "frozen75k.tsv.gz")
    stale = [token for token in stale_tokens if token in controller_text]
    if stale:
        raise ValueError(f"stale 75k controller tokens after rewrite: {stale}")
    mpnn_receipt = {
        "status": "PREPARED_NOT_STARTED",
        "campaign": "pvrig_1m_fixed_pose_mpnn150k_v1_20260722",
        "source_campaign": str(mpnn_source),
        "poses": task_rows,
        "pose_input_hash_closure": True,
        "unique_pose_inputs": pose_inputs,
        "sequences_per_pose": 2400,
        "raw_target": task_rows * 2400,
        "freeze_target": 150000,
        "duplicate_semantics": "Deterministic first-half overlap with the 75k campaign is expected and must be removed by global exact-sequence deduplication.",
    }
    (mpnn_target / "PREPARED.json").write_text(json.dumps(mpnn_receipt, indent=2, sort_keys=True) + "\n")
    manifest(mpnn_target)

    print(json.dumps({"rfantibody": rf_receipt, "fixed_pose_mpnn": mpnn_receipt}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
