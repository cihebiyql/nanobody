#!/usr/bin/env python3
"""Run resumable mutant-panel structure, docking, and postprocess stages."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL = ROOT / "docking" / "calibration" / "mutant_validation_panel" / "mutant_panel.csv"
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"
QC_SCRIPT = ROOT / "docking" / "scripts" / "pdb_geometry_qc.py"
POSTPROCESS_SCRIPT = WORKFLOW_DIR / "process_haddock3_calibration_run.py"
STATUS_SCRIPT = WORKFLOW_DIR / "summarize_mutant_panel_status.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-csv", type=Path, default=DEFAULT_PANEL)
    parser.add_argument(
        "--stage",
        choices=["structure", "docking", "postprocess", "qc", "status", "all"],
        default="all",
    )
    parser.add_argument("--limit", type=int, help="Run at most N pending rows for the selected stage(s).")
    parser.add_argument("--jobs", type=int, default=1, help="Concurrent rows for docking/postprocess/qc stages. Structure stays sequential.")
    parser.add_argument("--start-after", help="Skip rows through this mutant_name, then start after it.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-going", action="store_true", help="Continue after a failed row and summarize failures at the end.")
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def workdir_for(row: dict[str, str]) -> Path:
    if row.get("workdir"):
        return Path(row["workdir"])
    return DEFAULT_PANEL.parent / "workdirs" / row["mutant_name"]


def ensure_logs(workdir: Path) -> Path:
    path = workdir / "reports" / "stage_logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_logged(cmd: list[str], cwd: Path, log_path: Path, dry_run: bool) -> None:
    print("+ " + " ".join(cmd))
    print(f"  log={log_path}")
    if dry_run:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("+ " + " ".join(cmd) + "\n")
        log.flush()
        subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True, check=True)


def structure_pdb(row: dict[str, str]) -> Path:
    workdir = workdir_for(row)
    name = row["mutant_name"]
    return workdir / "haddock3" / "data" / f"{name}_vhh_chainA.pdb"


def raw_pdb(row: dict[str, str]) -> Path:
    workdir = workdir_for(row)
    name = row["mutant_name"]
    return workdir / "monomer" / f"{name}_nanobodybuilder2.pdb"


def run_dir(row: dict[str, str]) -> Path:
    workdir = workdir_for(row)
    name = row["mutant_name"]
    return workdir / "haddock3" / f"run_{name}_pvrig_hotspot_test"


def consensus_csv(row: dict[str, str]) -> Path:
    workdir = workdir_for(row)
    name = row["mutant_name"]
    return workdir / "reports" / f"{name}_8x6b_9e6y_consensus.csv"


def qc_json(row: dict[str, str]) -> Path:
    return workdir_for(row) / "reports" / "structure_qc_chainA.json"


def run_structure(row: dict[str, str], dry_run: bool) -> bool:
    workdir = workdir_for(row)
    if structure_pdb(row).exists() and raw_pdb(row).exists():
        return False
    run_logged(["bash", str(workdir / "run_node1_structure_prediction.sh")], ROOT, ensure_logs(workdir) / "structure_prediction.log", dry_run)
    return True


def run_qc(row: dict[str, str], dry_run: bool) -> bool:
    pdb = structure_pdb(row)
    out = qc_json(row)
    if not pdb.exists():
        raise RuntimeError(f"missing structure for QC: {pdb}")
    if out.exists():
        return False
    run_logged(
        [sys.executable, str(QC_SCRIPT), "--pdb", str(pdb), "--chain", "A", "--out-json", str(out)],
        ROOT,
        ensure_logs(workdir_for(row)) / "structure_qc.log",
        dry_run,
    )
    return True


def run_docking(row: dict[str, str], dry_run: bool) -> bool:
    workdir = workdir_for(row)
    if run_dir(row).exists():
        return False
    if not structure_pdb(row).exists():
        raise RuntimeError(f"missing normalized structure before docking: {structure_pdb(row)}")
    run_logged(["bash", str(workdir / "run_node1_haddock3.sh")], ROOT, ensure_logs(workdir) / "haddock3.log", dry_run)
    return True


def run_postprocess(row: dict[str, str], dry_run: bool) -> bool:
    workdir = workdir_for(row)
    name = row["mutant_name"]
    if consensus_csv(row).exists():
        return False
    if not run_dir(row).exists():
        raise RuntimeError(f"missing HADDOCK3 run dir before postprocess: {run_dir(row)}")
    run_logged(
        [
            sys.executable,
            str(POSTPROCESS_SCRIPT),
            "--workdir",
            str(workdir),
            "--name",
            name,
            "--cdr1",
            row["cdr1_range"],
            "--cdr2",
            row["cdr2_range"],
            "--cdr3",
            row["cdr3_range"],
        ],
        ROOT,
        ensure_logs(workdir) / "postprocess.log",
        dry_run,
    )
    return True


def is_pending(row: dict[str, str], stage: str) -> bool:
    if stage == "structure":
        return not (structure_pdb(row).exists() and raw_pdb(row).exists())
    if stage == "qc":
        return structure_pdb(row).exists() and not qc_json(row).exists()
    if stage == "docking":
        return not run_dir(row).exists()
    if stage == "postprocess":
        return not consensus_csv(row).exists()
    raise ValueError(f"unknown stage: {stage}")


def refresh_status(dry_run: bool) -> None:
    run_logged([sys.executable, str(STATUS_SCRIPT)], ROOT, DEFAULT_PANEL.parent / "batch_runner_status_refresh.log", dry_run)


def filtered_rows(rows: list[dict[str, str]], start_after: str | None) -> list[dict[str, str]]:
    if not start_after:
        return rows
    output: list[dict[str, str]] = []
    seen = False
    for row in rows:
        if seen:
            output.append(row)
        if row["mutant_name"] == start_after:
            seen = True
    if not seen:
        raise SystemExit(f"--start-after mutant not found: {start_after}")
    return output


def run_one_stage_row(
    row: dict[str, str],
    stage: str,
    dry_run: bool,
) -> bool:
    actions = {
        "structure": run_structure,
        "qc": run_qc,
        "docking": run_docking,
        "postprocess": run_postprocess,
    }
    changed = actions[stage](row, dry_run)
    if changed and stage == "structure" and not dry_run:
        run_qc(row, dry_run)
    return changed


def run_stage(
    rows: list[dict[str, str]],
    stage: str,
    limit: int | None,
    dry_run: bool,
    keep_going: bool,
    jobs: int,
) -> tuple[int, list[str]]:
    failures: list[str] = []
    pending = [row for row in rows if is_pending(row, stage)]
    if limit is not None:
        pending = pending[:limit]
    if stage == "structure" and jobs > 1:
        print("structure stage is kept sequential because generated NanoBodyBuilder2 scripts share CUDA_VISIBLE_DEVICES=0")
        jobs = 1

    if jobs <= 1:
        count = 0
        for row in pending:
            try:
                changed = run_one_stage_row(row, stage, dry_run)
                count += 1 if changed else 0
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{row['mutant_name']} {stage}: {exc}")
                print(f"FAIL {row['mutant_name']} {stage}: {exc}")
                if not keep_going:
                    raise
        print(f"stage={stage} actions={count} failures={len(failures)}")
        return count, failures

    count = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(run_one_stage_row, row, stage, dry_run): row for row in pending}
        for future in as_completed(futures):
            row = futures[future]
            try:
                changed = future.result()
                count += 1 if changed else 0
                print(f"done {stage}: {row['mutant_name']}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{row['mutant_name']} {stage}: {exc}")
                print(f"FAIL {row['mutant_name']} {stage}: {exc}")
                if not keep_going:
                    raise
    print(f"stage={stage} actions={count} failures={len(failures)}")
    return count, failures


def main() -> None:
    args = parse_args()
    rows = filtered_rows(read_rows(args.panel_csv), args.start_after)
    stages = ["structure", "docking", "postprocess"] if args.stage == "all" else [args.stage]
    all_failures: list[str] = []
    if args.stage == "status":
        refresh_status(args.dry_run)
        return
    for stage in stages:
        _count, failures = run_stage(rows, stage, args.limit, args.dry_run, args.keep_going, args.jobs)
        all_failures.extend(failures)
        refresh_status(args.dry_run)
    if all_failures:
        print("Failures:")
        for item in all_failures:
            print(f"- {item}")
        raise SystemExit(1)
    print("OK mutant panel batch runner complete")


if __name__ == "__main__":
    main()
