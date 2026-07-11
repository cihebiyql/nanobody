#!/usr/bin/env python3
"""Postprocess completed geometry-4 runs and build the cascade import summary."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_MANIFEST = PACKAGE_ROOT / "manifests/geometry4_candidates.tsv"
DEFAULT_AUDIT_CSV = PACKAGE_ROOT / "reports/candidate_level_8x6b_9e6y_audit.csv"
DEFAULT_FINALIZE_CSV = PACKAGE_ROOT / "reports/cascade_finalize_docking_summary.csv"
DEFAULT_STATUS_JSON = PACKAGE_ROOT / "reports/dual_baseline_postprocess_status.json"
PROCESSOR = REPO_ROOT / "docking/success_case_validation/process_haddock3_calibration_run.py"
SUMMARY_BUILDER = PACKAGE_ROOT / "scripts/build_candidate_level_docking_summary.py"
FINALIZE_METRICS = (
    "hotspot_overlap_count",
    "total_vhh_pvrl2_residue_pair_occlusion",
    "cdr3_pvrl2_residue_pair_occlusion",
    "cdr3_occlusion_fraction",
)
COMPLETE_BLOCKER_CLASSES = {
    "CONSENSUS_BLOCKER_LIKE_A",
    "SINGLE_BASELINE_BLOCKER_RECHECK",
    "BLOCKER_PLAUSIBLE_B",
    "CONSENSUS_BINDER_LIKE_C",
    "DISCORDANT_REDOCK_REQUIRED",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit-csv", type=Path, default=DEFAULT_AUDIT_CSV)
    parser.add_argument("--finalize-csv", type=Path, default=DEFAULT_FINALIZE_CSV)
    parser.add_argument("--status-json", type=Path, default=DEFAULT_STATUS_JSON)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def run_complete(run_dir: Path) -> bool:
    top_dir = run_dir / "6_seletopclusts"
    return (run_dir / "traceback/consensus.tsv").is_file() and any(
        top_dir.glob("cluster_*_model_*.pdb*")
    )


def run_postprocess(row: dict[str, str], force: bool) -> dict[str, str]:
    workdir = Path(row["workdir"])
    run_dir = workdir / row["run_dir_name"]
    consensus = workdir / "reports" / row["consensus_filename"]
    if not run_complete(run_dir):
        return {
            "candidate_id": row["candidate_id"],
            "source_candidate_id": row["source_candidate_id"],
            "status": "PENDING_HADDOCK3",
            "run_dir": str(run_dir),
            "consensus": str(consensus),
        }
    if consensus.is_file() and not force:
        return {
            "candidate_id": row["candidate_id"],
            "source_candidate_id": row["source_candidate_id"],
            "status": "REUSED_COMPLETE_CONSENSUS",
            "run_dir": str(run_dir),
            "consensus": str(consensus),
            "consensus_sha256": sha256_file(consensus),
        }

    command = [
        sys.executable,
        str(PROCESSOR),
        "--workdir",
        str(workdir),
        "--run-dir",
        str(run_dir),
        "--name",
        row["source_candidate_id"],
        "--cdr1",
        row["cdr1_range"],
        "--cdr2",
        row["cdr2_range"],
        "--cdr3",
        row["cdr3_range"],
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    if not consensus.is_file():
        raise RuntimeError(f"Postprocess did not produce expected consensus: {consensus}")
    return {
        "candidate_id": row["candidate_id"],
        "source_candidate_id": row["source_candidate_id"],
        "status": "POSTPROCESS_COMPLETE",
        "run_dir": str(run_dir),
        "consensus": str(consensus),
        "consensus_sha256": sha256_file(consensus),
    }


def write_finalize_csv(audit_csv: Path, finalize_csv: Path) -> int:
    with audit_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0]) if rows else []
    importable = [
        row
        for row in rows
        if row.get("import_status") == "IMPORTED"
        and row.get("run_status") == "RUN"
        and row.get("baseline_count") == "2"
        and row.get("blocker_class") in COMPLETE_BLOCKER_CLASSES
        and all(row.get(metric, "").strip() for metric in FINALIZE_METRICS)
    ]
    finalize_csv.parent.mkdir(parents=True, exist_ok=True)
    with finalize_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(importable)
    return len(importable)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_tsv(args.manifest)
    statuses = [] if args.summary_only else [run_postprocess(row, args.force) for row in rows]

    subprocess.run(
        [
            sys.executable,
            str(SUMMARY_BUILDER),
            "--manifest",
            str(args.manifest),
            "--out-csv",
            str(args.audit_csv),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    importable_count = write_finalize_csv(args.audit_csv, args.finalize_csv)
    status = {
        "schema_version": "pvrig_v2_5_geometry4_postprocess_status_v1",
        "claim_boundary": "dual_baseline_geometry_priority_not_experimental_binding_or_blocking_truth",
        "manifest": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "candidate_count": len(rows),
        "importable_candidate_count": importable_count,
        "audit_csv": str(args.audit_csv),
        "audit_csv_sha256": sha256_file(args.audit_csv),
        "finalize_csv": str(args.finalize_csv),
        "finalize_csv_sha256": sha256_file(args.finalize_csv),
        "candidate_status": statuses,
    }
    args.status_json.parent.mkdir(parents=True, exist_ok=True)
    args.status_json.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
