#!/usr/bin/env python3
"""Postprocess the 96-candidate PVRIG docking pilot through both baselines."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_manifest.tsv"
DEFAULT_SYNC_ROOT = EXP_DIR / "runs/pvrig_teacher_v1_20260712/pilot96_node1_selected"
DEFAULT_WORK_ROOT = EXP_DIR / "runs/pvrig_teacher_v1_20260712/pilot96_postprocessed"
DEFAULT_AUDIT = EXP_DIR / "audits/pvrig_teacher_pilot96_postprocess_audit.json"
DEFAULT_PROCESSOR = WORKSPACE_ROOT / "docking/success_case_validation/process_haddock3_calibration_run.py"
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
    pattern = f"shard_*/haddock3/{candidate_id}/run_{candidate_id}_pvrig_hotspot"
    matches = sorted(path for path in sync_root.glob(pattern) if path.is_dir())
    if len(matches) != 1:
        raise ValueError(f"Expected one synced HADDOCK run for {candidate_id}; found {len(matches)}")
    return matches[0]


def selected_model_count(run_dir: Path) -> int:
    selected = run_dir / "6_seletopclusts"
    names = {
        path.name.removesuffix(".pdb.gz").removesuffix(".pdb")
        for path in selected.glob("cluster_*_model_*.pdb*")
    }
    return len(names)


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def completion_evidence(workdir: Path, candidate_id: str, top_n: int) -> dict[str, object]:
    consensus = workdir / "reports" / f"{candidate_id}_8x6b_9e6y_consensus.csv"
    class_8 = workdir / "reports" / f"{candidate_id}_8x6b_blocker_classification.csv"
    class_9 = workdir / "reports" / f"{candidate_id}_9e6y_blocker_classification.csv"
    aligned_8 = len(list((workdir / "haddock3/top_models_aligned_to_8x6b").glob("*_aligned_to_8x6b.pdb")))
    aligned_9 = len(list((workdir / "haddock3/top_models_aligned_to_9e6y").glob("*_aligned_to_9e6y.pdb")))
    evidence = {
        "consensus_rows": count_csv_rows(consensus),
        "classification_8x6b_rows": count_csv_rows(class_8),
        "classification_9e6y_rows": count_csv_rows(class_9),
        "aligned_8x6b_models": aligned_8,
        "aligned_9e6y_models": aligned_9,
    }
    evidence["complete"] = all(int(value) == top_n for value in evidence.values())
    return evidence


def process_one(
    row: dict[str, str],
    sync_root: Path,
    work_root: Path,
    processor: Path,
    top_n: int,
    min_models: int,
) -> dict[str, object]:
    candidate_id = row["candidate_id"]
    workdir = work_root / candidate_id
    try:
        run_dir = find_run_dir(sync_root, candidate_id)
        expected_models = min(top_n, selected_model_count(run_dir))
        if expected_models < min_models:
            raise ValueError(f"Only {expected_models} selected models; minimum is {min_models}")
    except Exception as error:
        return {
            "candidate_id": candidate_id,
            "status": f"FAIL:{type(error).__name__}:{error}",
            "seconds": 0.0,
            "complete": False,
        }
    before = completion_evidence(workdir, candidate_id, expected_models)
    if before["complete"]:
        return {"candidate_id": candidate_id, "status": "SKIP_COMPLETE", "seconds": 0.0, "expected_models": expected_models, **before}

    start = time.monotonic()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "inputs").mkdir(exist_ok=True)
    (workdir / "inputs" / f"{candidate_id}_vhh.fasta").write_text(
        f">{candidate_id}\n{row['sequence']}\n", encoding="utf-8"
    )
    log_path = workdir / "postprocess.log"
    try:
        cmd = [
            sys.executable,
            str(processor),
            "--workdir",
            str(workdir),
            "--name",
            candidate_id,
            "--run-dir",
            str(run_dir),
            "--cdr1",
            cdr_range(row["sequence"], row["cdr1"]),
            "--cdr2",
            cdr_range(row["sequence"], row["cdr2"]),
            "--cdr3",
            cdr_range(row["sequence"], row["cdr3"]),
            "--top-n",
            str(top_n),
        ]
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=WORKSPACE_ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        evidence = completion_evidence(workdir, candidate_id, expected_models)
        status = "PASS" if evidence["complete"] else "FAIL_INCOMPLETE_OUTPUT"
        return {
            "candidate_id": candidate_id,
            "status": status,
            "seconds": round(time.monotonic() - start, 3),
            "expected_models": expected_models,
            "run_dir": str(run_dir),
            "log": str(log_path),
            **evidence,
        }
    except Exception as error:  # Preserve all failures for a resumable batch audit.
        return {
            "candidate_id": candidate_id,
            "status": f"FAIL:{type(error).__name__}:{error}",
            "seconds": round(time.monotonic() - start, 3),
            "expected_models": expected_models,
            "log": str(log_path),
            **completion_evidence(workdir, candidate_id, expected_models),
        }


def run(args: argparse.Namespace) -> dict[str, object]:
    rows = read_tsv(args.manifest)
    if len(rows) != 96 or len({row["candidate_id"] for row in rows}) != 96:
        raise ValueError("The pilot manifest must contain 96 unique candidates")
    if args.candidate_id:
        wanted = set(args.candidate_id)
        rows = [row for row in rows if row["candidate_id"] in wanted]
        missing = sorted(wanted - {row["candidate_id"] for row in rows})
        if missing:
            raise ValueError(f"Unknown candidate IDs: {missing}")

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
        "status": "PASS" if not failed else "FAIL_POSTPROCESS_INCOMPLETE",
        "schema_version": "pvrig_teacher_pilot96_postprocess_audit_v1",
        "manifest": str(args.manifest),
        "sync_root": str(args.sync_root),
        "work_root": str(args.work_root),
        "top_n": args.top_n,
        "min_models": args.min_models,
        "requested_candidates": len(rows),
        "complete_candidates": sum(row["status"] in {"PASS", "SKIP_COMPLETE"} for row in results),
        "processed_candidates": sum(row["status"] == "PASS" for row in results),
        "resumed_candidates": sum(row["status"] == "SKIP_COMPLETE" for row in results),
        "failed_candidates": len(failed),
        "results": results,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failed:
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sync-root", type=Path, default=DEFAULT_SYNC_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--processor", type=Path, default=DEFAULT_PROCESSOR)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-models", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--candidate-id", action="append")
    args = parser.parse_args(argv)
    if args.top_n <= 0 or args.min_models <= 0 or args.min_models > args.top_n or args.workers <= 0:
        parser.error("Require 0 < --min-models <= --top-n and positive --workers")
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
