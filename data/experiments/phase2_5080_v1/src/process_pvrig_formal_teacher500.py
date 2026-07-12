#!/usr/bin/env python3
"""Postprocess formal Teacher500 HADDOCK poses against both PVRIG baselines."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import process_pvrig_teacher_pilot96 as pilot  # noqa: E402

DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
DEFAULT_SYNC_ROOT = EXP_DIR / "runs/pvrig_teacher_formal_v1/teacher500_node1_selected"
DEFAULT_WORK_ROOT = EXP_DIR / "runs/pvrig_teacher_formal_v1/teacher500_postprocessed"
DEFAULT_AUDIT = EXP_DIR / "audits/pvrig_formal_teacher500_postprocess_audit.json"
EXPECTED_CANDIDATES = 500
CLAIM_BOUNDARY = "dual_baseline_docking_geometry_proxy_not_binding_or_experimental_blocking_truth"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    required = {
        "candidate_id",
        "vhh_sequence",
        "cdr1_after",
        "cdr2_after",
        "cdr3_after",
    }
    missing = required - set(row)
    if missing:
        raise ValueError(f"Formal Teacher500 row is missing {sorted(missing)}")
    return {
        **row,
        "sequence": row["vhh_sequence"],
        "cdr1": row["cdr1_after"],
        "cdr2": row["cdr2_after"],
        "cdr3": row["cdr3_after"],
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    rows = [normalize_row(row) for row in read_csv(args.selection)]
    if len(rows) != EXPECTED_CANDIDATES or len({row["candidate_id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise ValueError(f"Formal manifest must contain {EXPECTED_CANDIDATES} unique candidates")
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
            pool.submit(
                pilot.process_one,
                row,
                args.sync_root,
                args.work_root,
                args.processor,
                args.top_n,
                args.min_models,
            ): row["candidate_id"]
            for row in rows
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: str(row["candidate_id"]))
    failed = [row for row in results if row["status"] not in {"PASS", "SKIP_COMPLETE"}]
    audit: dict[str, object] = {
        "status": "PASS_FORMAL_TEACHER500_POSTPROCESS" if not failed else "FAIL_FORMAL_TEACHER500_POSTPROCESS_INCOMPLETE",
        "schema_version": "pvrig_formal_teacher500_postprocess_audit_v1",
        "manifest": str(args.selection),
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
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--sync-root", type=Path, default=DEFAULT_SYNC_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--processor", type=Path, default=pilot.DEFAULT_PROCESSOR)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-models", type=int, default=4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--candidate-id", action="append")
    args = parser.parse_args(argv)
    if args.top_n <= 0 or args.min_models <= 0 or args.min_models > args.top_n or args.workers <= 0:
        parser.error("Require 0 < --min-models <= --top-n and positive --workers")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    print(json.dumps(run(parse_args(argv)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
