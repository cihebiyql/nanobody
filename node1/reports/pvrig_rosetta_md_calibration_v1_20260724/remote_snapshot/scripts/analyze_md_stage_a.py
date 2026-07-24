#!/usr/bin/env python3
"""Analyze completed 3-system x 3-seed GROMACS calibration trajectories."""

from __future__ import annotations

import csv
import fcntl
import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724"
)
GMX = Path(os.environ.get("GMX", "/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx"))
MANIFEST = ROOT / "manifests/MD_PRODUCTION_MANIFEST.tsv"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path, stdin: str | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        label = command[1] if len(command) > 1 else "command"
        (cwd / f"analysis_failed_{label}.stdout.log").write_text(result.stdout, encoding="utf-8")
        (cwd / f"analysis_failed_{label}.stderr.log").write_text(result.stderr, encoding="utf-8")
        raise RuntimeError(f"analysis command failed ({result.returncode}): {' '.join(command)}")


EXPECTED_INDEX_GROUPS = [
    "molindex_1",
    "molindex_2",
    'molindex_1_and_group_"Backbone"',
    'molindex_2_and_group_"Backbone"',
    '(molindex_1_or_molindex_2)_and_group_"Backbone"',
]


def validate_index_groups(path: Path) -> None:
    groups = re.findall(
        r"^\s*\[\s*(.*?)\s*\]\s*$",
        path.read_text(encoding="utf-8", errors="replace"),
        flags=re.MULTILINE,
    )
    if groups != EXPECTED_INDEX_GROUPS:
        raise RuntimeError(f"unexpected interface index groups in {path}: {groups}")


def xvg_values(
    path: Path, column: int = 1, start_ns: float = 1.0, end_ns: float = 2.0
) -> list[float]:
    values = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0] in "#@":
            continue
        fields = line.split()
        time_ns = float(fields[0])
        if start_ns <= time_ns <= end_ns + 1e-9:
            values.append(float(fields[column]))
    if len(values) < 90:
        raise RuntimeError(f"insufficient 1-2 ns samples in {path}: {len(values)}")
    return values


rows = list(csv.DictReader(MANIFEST.open(newline="", encoding="utf-8"), delimiter="\t"))
if len(rows) != 9:
    raise SystemExit(f"expected 9 MD jobs, found {len(rows)}")
lock_handle = (ROOT / "locks/md_stage_a_analysis.lock").open("w")
try:
    fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("another MD Stage A analysis owns the lock")

metrics = []
for row in rows:
    directory = ROOT / "md/production" / row["system_id"] / f'seed_{row["md_seed"]}'
    if not (directory / "COMPLETE.json").is_file():
        raise SystemExit(f"incomplete MD job: {directory}")
    required = ["prod.tpr", "prod.xtc", "prod.cpt", "prod.gro", "prod.log"]
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise SystemExit(f"completed job is missing files {missing}: {directory}")
    log_text = (directory / "prod.log").read_text(encoding="utf-8", errors="replace")
    if "Finished mdrun on rank 0" not in log_text:
        raise SystemExit(f"production log lacks normal termination marker: {directory}")
    selection = directory / "interface.sel"
    selection.write_text(
        'molindex 1;\n'
        'molindex 2;\n'
        'molindex 1 and group "Backbone";\n'
        'molindex 2 and group "Backbone";\n'
        '(molindex 1 or molindex 2) and group "Backbone";\n',
        encoding="utf-8",
    )
    run(
        [str(GMX), "select", "-s", "prod.tpr", "-sf", selection.name, "-on", "interface.ndx"],
        directory,
    )
    validate_index_groups(directory / "interface.ndx")
    if not (directory / "prod_whole.xtc").is_file():
        run(
            [
                str(GMX),
                "trjconv",
                "-s",
                "prod.tpr",
                "-f",
                "prod.xtc",
                "-o",
                "prod_whole.xtc",
                "-pbc",
                "mol",
                "-ur",
                "compact",
            ],
            directory,
            "0\n",
        )
    run(
        [
            str(GMX),
            "rms",
            "-s",
            "prod.tpr",
            "-f",
            "prod_whole.xtc",
            "-n",
            "interface.ndx",
            "-o",
            "vhh_receptor_fitted_rmsd.xvg",
            "-tu",
            "ns",
        ],
        directory,
        "2\n3\n",
    )
    run(
        [
            str(GMX),
            "rms",
            "-s",
            "prod.tpr",
            "-f",
            "prod_whole.xtc",
            "-n",
            "interface.ndx",
            "-o",
            "complex_backbone_rmsd.xvg",
            "-tu",
            "ns",
        ],
        directory,
        "4\n4\n",
    )
    run(
        [
            str(GMX),
            "mindist",
            "-s",
            "prod.tpr",
            "-f",
            "prod_whole.xtc",
            "-n",
            "interface.ndx",
            "-od",
            "interface_mindist.xvg",
            "-on",
            "interface_contacts_045nm.xvg",
            "-d",
            "0.45",
            "-tu",
            "ns",
        ],
        directory,
        "0\n1\n",
    )
    run(
        [
            str(GMX),
            "hbond",
            "-s",
            "prod.tpr",
            "-f",
            "prod_whole.xtc",
            "-n",
            "interface.ndx",
            "-r",
            'group "molindex_1"',
            "-t",
            'group "molindex_2"',
            "-num",
            "interface_hbonds.xvg",
            "-tu",
            "ns",
        ],
        directory,
    )
    values = {
        "vhh_rmsd_nm": xvg_values(directory / "vhh_receptor_fitted_rmsd.xvg"),
        "complex_rmsd_nm": xvg_values(directory / "complex_backbone_rmsd.xvg"),
        "min_distance_nm": xvg_values(directory / "interface_mindist.xvg"),
        "contacts_045nm": xvg_values(directory / "interface_contacts_045nm.xvg"),
        "interface_hbonds": xvg_values(directory / "interface_hbonds.xvg"),
    }
    result: dict[str, object] = {
        "system_id": row["system_id"],
        "pair_id": row["pair_id"],
        "pair_role": row["pair_role"],
        "md_seed": int(row["md_seed"]),
        "analysis_window_ns": "1.0-2.0",
    }
    for name, series in values.items():
        result[f"{name}_mean"] = statistics.mean(series)
        result[f"{name}_median"] = statistics.median(series)
        result[f"{name}_stdev"] = statistics.pstdev(series)
    metrics.append(result)

fields = list(metrics[0])
with (REPORTS / "md_stage_a_seed_metrics.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(metrics)

direction_spec = {
    "vhh_rmsd_nm_mean": "low",
    "complex_rmsd_nm_mean": "low",
    "min_distance_nm_mean": "low",
    "contacts_045nm_mean": "high",
    "interface_hbonds_mean": "high",
}
positive = {row["md_seed"]: row for row in metrics if row["system_id"] == "P20_F99A_positive"}
negative = {row["md_seed"]: row for row in metrics if row["system_id"] == "P20_F99A_destructive"}
if set(positive) != {917, 1931, 3253} or set(negative) != set(positive):
    raise SystemExit(
        f"P20 positive/destructive seed mismatch: positive={sorted(positive)}, "
        f"destructive={sorted(negative)}"
    )
direction_rows = []
for metric, direction in direction_spec.items():
    checks = []
    deltas = []
    for seed in sorted(positive):
        p, n = float(positive[seed][metric]), float(negative[seed][metric])
        checks.append(int(p < n if direction == "low" else p > n))
        deltas.append(p - n)
    fraction = statistics.mean(checks)
    direction_rows.append(
        {
            "metric": metric,
            "expected_positive_direction": direction,
            "seed_direction_fraction": fraction,
            "paired_seed_delta_median": statistics.median(deltas),
            "passes_2_of_3": fraction >= 2 / 3,
        }
    )
with (REPORTS / "md_stage_a_p20_f99a_directions.tsv").open(
    "w", newline="", encoding="utf-8"
) as handle:
    writer = csv.DictWriter(
        handle, fieldnames=list(direction_rows[0]), delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(direction_rows)

interface_passes = sum(
    row["passes_2_of_3"]
    for row in direction_rows
    if row["metric"] in {"min_distance_nm_mean", "contacts_045nm_mean", "interface_hbonds_mean"}
)
hr151_rmsd = statistics.median(
    float(row["vhh_rmsd_nm_mean"]) for row in metrics if row["system_id"] == "HR151_positive"
)
receipt = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "state": "MD_STAGE_A_ANALYSIS_COMPLETE",
    "trajectories": len(metrics),
    "production_ns_each": 2,
    "analysis_window_ns": "1.0-2.0",
    "hr151_median_vhh_rmsd_nm": hr151_rmsd,
    "interface_metrics_passing_2_of_3": interface_passes,
    "stage_a_direction_gate": "PASS" if interface_passes >= 2 else "FAIL",
    "decision": (
        "ELIGIBLE_TO_EXPAND_P30_P38_P39"
        if interface_passes >= 2
        else "DO_NOT_EXPAND_MD_AS_RANKING_SIGNAL"
    ),
    "evidence_boundary": (
        "2 ns trajectories are stability and paired-direction calibration only; "
        "they are not experimental affinity or blocking evidence."
    ),
}
(REPORTS / "MD_STAGE_A_CALIBRATION_RECEIPT.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2))
