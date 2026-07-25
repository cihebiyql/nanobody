#!/usr/bin/env python3
"""Analyze the 20-candidate short-MD panel as descriptive pose-persistence evidence."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GMX_DEFAULT = "/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx"
HOTSPOTS = [71, 72, 74, 81, 82, 83, 87, 90, 92, 95, 96, 97, 98, 100, 135, 137, 138, 139, 140, 141, 142, 143, 144]
AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, stdin: str | None = None) -> None:
    result = subprocess.run(
        command, cwd=cwd, input=stdin, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        label = command[1] if len(command) > 1 else "command"
        (cwd / f"analysis_{label}.stdout.log").write_text(result.stdout, encoding="utf-8")
        (cwd / f"analysis_{label}.stderr.log").write_text(result.stderr, encoding="utf-8")
        raise RuntimeError(f"analysis failed: {' '.join(command)}")


def series(path: Path, start: float = 1.0, end: float = 2.0) -> list[float]:
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0] in "#@":
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        time_ns, value = float(fields[0]), float(fields[1])
        if start <= time_ns <= end + 1e-9:
            output.append(value)
    if len(output) < 90:
        raise RuntimeError(f"insufficient samples in {path}: {len(output)}")
    return output


def all_values(path: Path) -> list[float]:
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0] in "#@":
            continue
        fields = line.split()
        if len(fields) >= 2:
            output.append(float(fields[1]))
    if not output:
        raise RuntimeError(f"no values in {path}")
    return output


def cdr3_residue_numbers(path: Path, motif: str) -> list[int]:
    residues: list[tuple[int, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="ascii", errors="ignore").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21:22] != "A":
            continue
        key = (line[22:26].strip(), line[26:27])
        if key in seen:
            continue
        seen.add(key)
        residues.append((int(line[22:26]), AA3.get(line[17:20].strip(), "X")))
    sequence = "".join(aa for _number, aa in residues)
    index = sequence.find(motif)
    if index < 0:
        raise RuntimeError(f"CDR3 motif not found in {path}")
    return [number for number, _aa in residues[index : index + len(motif)]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--gmx", type=Path, default=Path(GMX_DEFAULT))
    args = parser.parse_args()
    root = args.root.resolve()
    mdroot = root / "run" / "md"
    systems = {row["system_id"]: row for row in read_tsv(mdroot / "md_systems.tsv")}
    jobs = read_tsv(mdroot / "md_manifest.tsv")
    if len(systems) != 20 or len(jobs) != 60:
        raise ValueError("expected 20 systems and 60 MD jobs")
    lock_path = mdroot / "locks" / "md_analysis.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    trajectory_rows: list[dict[str, Any]] = []
    for row in jobs:
        system = systems[row["system_id"]]
        directory = mdroot / "production" / row["system_id"] / f"seed_{row['md_seed']}"
        required = ["COMPLETE.json", "prod.tpr", "prod.xtc", "prod.cpt", "prod.gro", "prod.log"]
        missing = [name for name in required if not (directory / name).is_file()]
        if missing:
            raise RuntimeError(f"{directory}: missing {missing}")
        cdr3_resids = cdr3_residue_numbers(Path(system["source_pdb"]), system["cdr3"])
        selection = (
            "molindex 1;\n"
            "molindex 2;\n"
            'molindex 1 and group "Backbone";\n'
            'molindex 2 and group "Backbone";\n'
            '(molindex 1 or molindex 2) and group "Backbone";\n'
            f"molindex 2 and resid {' '.join(map(str, cdr3_resids))} and name CA;\n"
            f"molindex 1 and resid {' '.join(map(str, HOTSPOTS))};\n"
        )
        (directory / "interface.sel").write_text(selection, encoding="utf-8")
        run(
            [str(args.gmx), "select", "-s", "prod.tpr", "-sf", "interface.sel", "-on", "interface.ndx"],
            directory,
        )
        groups = re.findall(
            r"^\s*\[\s*(.*?)\s*\]\s*$",
            (directory / "interface.ndx").read_text(encoding="utf-8", errors="replace"),
            flags=re.MULTILINE,
        )
        if len(groups) != 7:
            raise RuntimeError(f"unexpected index groups for {directory}: {groups}")
        if not (directory / "prod_whole.xtc").is_file():
            run(
                [str(args.gmx), "trjconv", "-s", "prod.tpr", "-f", "prod.xtc",
                 "-o", "prod_whole.xtc", "-pbc", "mol", "-ur", "compact"],
                directory, "0\n",
            )
        run(
            [str(args.gmx), "rms", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-o", "vhh_rmsd.xvg", "-tu", "ns"],
            directory, "2\n3\n",
        )
        run(
            [str(args.gmx), "rms", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-o", "complex_rmsd.xvg", "-tu", "ns"],
            directory, "4\n4\n",
        )
        run(
            [str(args.gmx), "mindist", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-od", "mindist.xvg", "-on", "contacts.xvg",
             "-d", "0.45", "-tu", "ns"],
            directory, "0\n1\n",
        )
        run(
            [str(args.gmx), "mindist", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-od", "hotspot_mindist.xvg",
             "-on", "hotspot_contacts.xvg", "-d", "0.45", "-tu", "ns"],
            directory, "6\n1\n",
        )
        run(
            [str(args.gmx), "hbond", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-r", 'group "molindex_1"',
             "-t", 'group "molindex_2"', "-num", "hbonds.xvg", "-tu", "ns"],
            directory,
        )
        run(
            [str(args.gmx), "rmsf", "-s", "prod.tpr", "-f", "prod_whole.xtc",
             "-n", "interface.ndx", "-o", "cdr3_rmsf.xvg", "-res",
             "-b", "1000", "-e", "2000"],
            directory, "5\n",
        )
        data = {
            "vhh_rmsd_nm": series(directory / "vhh_rmsd.xvg"),
            "complex_rmsd_nm": series(directory / "complex_rmsd.xvg"),
            "min_interface_distance_nm": series(directory / "mindist.xvg"),
            "interface_contacts_045nm": series(directory / "contacts.xvg"),
            "hotspot_contacts_045nm": series(directory / "hotspot_contacts.xvg"),
            "interface_hbonds": series(directory / "hbonds.xvg"),
        }
        record: dict[str, Any] = {
            **row,
            "analysis_window_ns": "1.0-2.0",
            "cdr3_rmsf_nm_mean": statistics.mean(all_values(directory / "cdr3_rmsf.xvg")),
            "pvrl2_occlusion_retention_status": "NOT_DIRECTLY_OBSERVABLE_IN_BINARY_MD",
            "md_role": "DESCRIPTIVE_ONLY",
        }
        for name, values in data.items():
            record[f"{name}_mean"] = statistics.mean(values)
            record[f"{name}_median"] = statistics.median(values)
            record[f"{name}_stdev"] = statistics.pstdev(values)
            if name in {"interface_contacts_045nm", "hotspot_contacts_045nm", "interface_hbonds"}:
                record[f"{name}_nonzero_occupancy"] = sum(value > 0 for value in values) / len(values)
        trajectory_rows.append(record)
    report_dir = mdroot / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = report_dir / "md_trajectory_metrics.tsv"
    write_tsv(trajectory_path, trajectory_rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trajectory_rows:
        grouped[str(row["candidate_id"])].append(row)
    candidates: list[dict[str, Any]] = []
    metric_keys = [
        "vhh_rmsd_nm_mean", "complex_rmsd_nm_mean",
        "min_interface_distance_nm_mean", "interface_contacts_045nm_mean",
        "hotspot_contacts_045nm_mean", "interface_hbonds_mean",
        "cdr3_rmsf_nm_mean", "interface_contacts_045nm_nonzero_occupancy",
        "hotspot_contacts_045nm_nonzero_occupancy",
        "interface_hbonds_nonzero_occupancy",
    ]
    for candidate_id, rows in sorted(grouped.items()):
        if len(rows) != 3:
            raise RuntimeError(f"{candidate_id}: expected three MD seeds")
        output: dict[str, Any] = {
            "candidate_id": candidate_id,
            "trajectory_count": 3,
            "seed_count": 3,
            "md_status": "COMPLETE_DESCRIPTIVE_ONLY",
            "md_role": "DESCRIPTIVE_ONLY",
            "pvrl2_occlusion_retention_status": "NOT_DIRECTLY_OBSERVABLE_IN_BINARY_MD",
        }
        for key in metric_keys:
            values = [float(row[key]) for row in rows]
            output[f"seed_median_{key}"] = statistics.median(values)
            output[f"seed_range_{key}"] = f"{min(values):.9g},{max(values):.9g}"
        candidates.append(output)
    candidate_path = report_dir / "md_candidate_summary.tsv"
    write_tsv(candidate_path, candidates)
    receipt = {
        "schema_version": "pvrig.top80.md20_analysis.v1",
        "state": "MD20_ANALYSIS_COMPLETE",
        "candidates": 20,
        "trajectories": 60,
        "production_ns_each": 2,
        "analysis_window_ns": "1.0-2.0",
        "method_role": "DESCRIPTIVE_ONLY",
        "trajectory_metrics_sha256": sha256_file(trajectory_path),
        "candidate_summary_sha256": sha256_file(candidate_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": (
            "Short binary-complex MD measures pose persistence; it does not "
            "measure PVRL2 occlusion directly and is not experimental affinity "
            "or blocking."
        ),
    }
    receipt_path = report_dir / "MD20_ANALYSIS_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidates": 20, "trajectories": 60}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
