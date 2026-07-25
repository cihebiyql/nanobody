#!/usr/bin/env python3
"""Postprocess selected HADDOCK3 models against 8X6B and 9E6Y baselines."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_PROCESSOR = Path("/mnt/d/work/抗体/docking/success_case_validation/process_haddock3_calibration_run.py")
CLAIM_BOUNDARY = "dual_baseline_docking_geometry_proxy_not_binding_or_blocker_proof"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def cdr_range(sequence: str, cdr: str) -> str:
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise ValueError(f"CDR is missing or ambiguous: {cdr}")
    return f"{start + 1}-{start + len(cdr)}"


def find_run_dir(sync_root: Path, candidate_id: str) -> Path:
    matches = sorted(
        path
        for path in sync_root.glob(
            f"shard_*/haddock3/{candidate_id}/run_{candidate_id}_pvrig_hotspot"
        )
        if path.is_dir()
    )
    if len(matches) != 1:
        raise ValueError(f"Expected one synced HADDOCK run for {candidate_id}; found {len(matches)}")
    return matches[0]


def selected_model_count(run_dir: Path) -> int:
    selected = run_dir / "6_seletopclusts"
    return len(list(selected.glob("cluster_*_model_*.pdb"))) + len(
        list(selected.glob("cluster_*_model_*.pdb.gz"))
    )


def csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def completion_evidence(workdir: Path, candidate_id: str, expected: int) -> dict[str, object]:
    reports = workdir / "reports"
    evidence = {
        "consensus_rows": csv_rows(reports / f"{candidate_id}_8x6b_9e6y_consensus.csv"),
        "classification_8x6b_rows": csv_rows(reports / f"{candidate_id}_8x6b_blocker_classification.csv"),
        "classification_9e6y_rows": csv_rows(reports / f"{candidate_id}_9e6y_blocker_classification.csv"),
        "aligned_8x6b_models": len(list((workdir / "haddock3/top_models_aligned_to_8x6b").glob("*.pdb"))),
        "aligned_9e6y_models": len(list((workdir / "haddock3/top_models_aligned_to_9e6y").glob("*.pdb"))),
    }
    evidence["complete"] = all(int(value) == expected for value in evidence.values())
    return evidence


def process_one(row: dict[str, str], sync_root: Path, work_root: Path, processor: Path, top_n: int, min_models: int) -> dict[str, object]:
    candidate_id = row["candidate_id"]
    workdir = work_root / candidate_id
    start = time.monotonic()
    try:
        run_dir = find_run_dir(sync_root, candidate_id)
        expected = min(top_n, selected_model_count(run_dir))
        if expected < min_models:
            raise ValueError(f"Only {expected} selected models; minimum is {min_models}")
        before = completion_evidence(workdir, candidate_id, expected)
        if before["complete"]:
            return {"candidate_id": candidate_id, "status": "SKIP_COMPLETE", "expected_models": expected, **before}
        sequence = row.get("qc_synthesis_sequence") or row["sequence"]
        workdir.mkdir(parents=True, exist_ok=True)
        log_path = workdir / "postprocess.log"
        cmd = [
            sys.executable,
            str(processor),
            "--workdir", str(workdir),
            "--name", candidate_id,
            "--run-dir", str(run_dir),
            "--cdr1", cdr_range(sequence, row["cdr1"]),
            "--cdr2", cdr_range(sequence, row["cdr2"]),
            "--cdr3", cdr_range(sequence, row["cdr3"]),
            "--top-n", str(top_n),
        ]
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=Path("/mnt/d/work/抗体"), stdout=log, stderr=subprocess.STDOUT, check=True)
        evidence = completion_evidence(workdir, candidate_id, expected)
        return {
            "candidate_id": candidate_id,
            "status": "PASS" if evidence["complete"] else "FAIL_INCOMPLETE_OUTPUT",
            "seconds": round(time.monotonic() - start, 3),
            "expected_models": expected,
            "run_dir": str(run_dir),
            "log": str(log_path),
            **evidence,
        }
    except Exception as error:
        return {
            "candidate_id": candidate_id,
            "status": f"FAIL:{type(error).__name__}:{error}",
            "seconds": round(time.monotonic() - start, 3),
            "complete": False,
        }


def run(args: argparse.Namespace) -> dict[str, object]:
    rows = read_tsv(args.manifest)
    if not rows or len({row["candidate_id"] for row in rows}) != len(rows):
        raise ValueError("manifest must contain unique candidates")
    args.work_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_one, row, args.sync_root, args.work_root, args.processor, args.top_n, args.min_models): row["candidate_id"]
            for row in rows
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: str(row["candidate_id"]))
    failed = [row for row in results if row["status"] not in {"PASS", "SKIP_COMPLETE"}]
    audit: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS" if not failed else "FAIL_POSTPROCESS_INCOMPLETE",
        "manifest": str(args.manifest),
        "sync_root": str(args.sync_root),
        "work_root": str(args.work_root),
        "requested_candidates": len(rows),
        "complete_candidates": len(rows) - len(failed),
        "failed_candidates": len(failed),
        "top_n": args.top_n,
        "min_models": args.min_models,
        "results": results,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failed:
        raise RuntimeError(f"{len(failed)} docking postprocess candidates failed; see {args.audit}")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sync-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--processor", type=Path, default=DEFAULT_PROCESSOR)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-models", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

