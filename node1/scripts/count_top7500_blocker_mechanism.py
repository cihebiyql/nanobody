#!/usr/bin/env python3
"""Aggregate PVRIG blocker-like geometry from compact HADDOCK job archives."""

from __future__ import annotations

import argparse
import csv
import json
import re
import tarfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


JOB_RE = re.compile(
    r"^CANDIDATE_(?P<candidate>.+)_(?P<conformation>8x6b|9e6y)"
    r"_s(?P<seed>\d+)_[0-9a-f]+\.tar\.gz$"
)
SCORE_RE = re.compile(
    rb'"hotspot_overlap"\s*:\s*\{.*?'
    rb'"full"\s*:\s*\{[^{}]*?"count"\s*:\s*(\d+).*?'
    rb'"vhh_pvrl2_occlusion"\s*:\s*\{.*?'
    rb'"by_vhh_region_pair_count"\s*:\s*\{[^{}]*?"cdr3"\s*:\s*(\d+).*?'
    rb'"cdr3_fraction"\s*:\s*([0-9.eE+-]+).*?'
    rb'"residue_pair_count"\s*:\s*(\d+)',
    re.DOTALL,
)


def classify(hotspot: int, total: int, cdr3: int, fraction: float) -> str:
    if hotspot >= 14 and total >= 500 and cdr3 >= 100 and fraction >= 0.15:
        return "A"
    if total >= 500 and (hotspot >= 14 or cdr3 >= 50):
        return "B"
    if total >= 300 and hotspot >= 10 and cdr3 >= 50:
        return "B"
    if hotspot >= 14 and total < 50:
        return "C"
    return "E"


def read_job(path_str: str) -> dict:
    path = Path(path_str)
    match = JOB_RE.match(path.name)
    if not match:
        return {"error": "bad_filename", "path": path_str}
    try:
        with tarfile.open(path, "r:gz") as archive:
            member = next(
                (
                    item for item in archive.getmembers()
                    if item.isfile() and item.name.endswith("/job_result.json")
                ),
                None,
            )
            if member is None:
                result_path = (
                    path.parent.parent
                    / "results"
                    / path.name.removesuffix(".tar.gz")
                    / "job_result.json"
                )
                payload = result_path.read_bytes()
            else:
                handle = archive.extractfile(member)
                if handle is None:
                    raise RuntimeError("job_result.json could not be extracted")
                payload = handle.read()
    except Exception as exc:  # noqa: BLE001 - preserve per-job failures in receipt
        return {"error": f"{type(exc).__name__}: {exc}", "path": path_str}

    values = [
        (int(hot), int(total), int(cdr3), float(frac))
        for hot, cdr3, frac, total in SCORE_RE.findall(payload)
    ]
    if len(values) % 2 or not values:
        return {
            "error": f"unexpected_score_count:{len(values)}",
            "path": path_str,
        }

    pose_classes = []
    for index in range(0, len(values), 2):
        left = classify(*values[index])
        right = classify(*values[index + 1])
        pose_classes.append((left, right))

    return {
        "candidate": match.group("candidate"),
        "conformation": match.group("conformation"),
        "seed": int(match.group("seed")),
        "pose_count": len(pose_classes),
        "dual_a_pose_count": sum(a == "A" and b == "A" for a, b in pose_classes),
        "dual_ab_pose_count": sum(
            a in {"A", "B"} and b in {"A", "B"} for a, b in pose_classes
        ),
        "any_a_reference_pose": any(
            a == "A" or b == "A" for a, b in pose_classes
        ),
        "any_ab_reference_pose": any(
            a in {"A", "B"} or b in {"A", "B"} for a, b in pose_classes
        ),
    }


def candidate_summary(job_rows: list[dict]) -> tuple[list[dict], dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in job_rows:
        grouped[row["candidate"]].append(row)

    candidates = []
    for candidate, rows in grouped.items():
        by_seed: dict[int, dict[str, dict]] = defaultdict(dict)
        for row in rows:
            by_seed[row["seed"]][row["conformation"]] = row

        strict_seed_passes = 0
        broad_seed_passes = 0
        complete_seeds = 0
        for conformation_rows in by_seed.values():
            if {"8x6b", "9e6y"} <= conformation_rows.keys():
                complete_seeds += 1
                strict_seed_passes += all(
                    conformation_rows[c]["dual_a_pose_count"] > 0
                    for c in ("8x6b", "9e6y")
                )
                broad_seed_passes += all(
                    conformation_rows[c]["dual_ab_pose_count"] > 0
                    for c in ("8x6b", "9e6y")
                )

        candidates.append(
            {
                "candidate_id": candidate,
                "job_count": len(rows),
                "seed_count": len(by_seed),
                "complete_seed_count": complete_seeds,
                "stage1_any_strict_dual_reference_job": any(
                    row["dual_a_pose_count"] > 0 for row in rows
                ),
                "stage1_any_broad_dual_reference_job": any(
                    row["dual_ab_pose_count"] > 0 for row in rows
                ),
                "stage2_any_seed_dual_conformation_strict": strict_seed_passes >= 1,
                "stage2_any_seed_dual_conformation_broad": broad_seed_passes >= 1,
                "stage3_two_seed_dual_conformation_strict": strict_seed_passes >= 2,
                "stage3_two_seed_dual_conformation_broad": broad_seed_passes >= 2,
                "strict_seed_passes": strict_seed_passes,
                "broad_seed_passes": broad_seed_passes,
            }
        )

    bool_fields = [
        key for key in candidates[0]
        if key.startswith("stage")
    ] if candidates else []
    summary = {
        "candidate_count": len(candidates),
        "job_count": len(job_rows),
        "seed_coverage": dict(sorted(Counter(
            row["complete_seed_count"] for row in candidates
        ).items())),
        "counts": {
            field: sum(bool(row[field]) for row in candidates)
            for field in bool_fields
        },
        "eligible_two_seed_candidates": sum(
            row["complete_seed_count"] >= 2 for row in candidates
        ),
    }
    return candidates, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", action="append", nargs=2, metavar=("NAME", "DIR"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_jobs: dict[str, list[dict]] = {}
    receipt = {
        "rules": {
            "A": "hotspot>=14,total>=500,cdr3>=100,cdr3_fraction>=0.15",
            "B": "total>=500 and (hotspot>=14 or cdr3>=50), or total>=300 and hotspot>=10 and cdr3>=50",
            "dual_reference": "same pose passes both 8x6b and 9e6y overlay scores",
            "dual_conformation": "same candidate and seed passes both independently docked conformations",
        },
        "campaigns": {},
    }

    for name, directory in args.campaign:
        paths = sorted(Path(directory).glob("*.tar.gz"))
        if args.limit:
            paths = paths[: args.limit]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(read_job, map(str, paths), chunksize=8))
        errors = [row for row in rows if "error" in row]
        valid = [row for row in rows if "error" not in row]
        all_jobs[name] = valid
        candidates, summary = candidate_summary(valid)
        summary["archive_count"] = len(paths)
        summary["parse_error_count"] = len(errors)
        receipt["campaigns"][name] = summary
        with (output_dir / f"{name}_candidate_summary.tsv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=candidates[0].keys(), delimiter="\t")
            writer.writeheader()
            writer.writerows(sorted(candidates, key=lambda row: row["candidate_id"]))
        if errors:
            (output_dir / f"{name}_parse_errors.json").write_text(
                json.dumps(errors, indent=2), encoding="utf-8"
            )

    (output_dir / "mechanism_count_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
