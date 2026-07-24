#!/usr/bin/env python3
"""Analyze P30/P38/P39 expansion and combine it with the P20 pilot."""

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


ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724")
GMX = Path(os.environ.get("GMX", "/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx"))
MANIFEST = ROOT / "manifests/MD_EXPANSION_PRODUCTION.tsv"
PRODUCTION = ROOT / "md/expansion/production"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)
lock = (ROOT / "locks/md_expansion_analysis.lock").open("w")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def run(command: list[str], cwd: Path, stdin: str | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, input=stdin, text=True, capture_output=True)
    if result.returncode:
        label = command[1] if len(command) > 1 else "command"
        (cwd / f"analysis_failed_{label}.stdout.log").write_text(result.stdout, encoding="utf-8")
        (cwd / f"analysis_failed_{label}.stderr.log").write_text(result.stderr, encoding="utf-8")
        raise RuntimeError(f"analysis command failed: {' '.join(command)}")


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


def values(path: Path, start_ns: float = 1.0, end_ns: float = 2.0) -> list[float]:
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0] in "#@":
            continue
        fields = line.split()
        time_ns = float(fields[0]) if len(fields) >= 2 else -1.0
        if len(fields) >= 2 and start_ns <= time_ns <= end_ns + 1e-9:
            output.append(float(fields[1]))
    if len(output) < 90:
        raise RuntimeError(f"insufficient 1-2 ns samples in {path}: {len(output)}")
    return output


rows = list(csv.DictReader(MANIFEST.open(newline="", encoding="utf-8"), delimiter="\t"))
if len(rows) != 18:
    raise SystemExit(f"expected 18 expansion trajectories, found {len(rows)}")
manifest_keys = [(row["system_id"], row["pair_role"], row["md_seed"]) for row in rows]
if len(manifest_keys) != len(set(manifest_keys)):
    raise SystemExit("duplicate expansion (system_id, pair_role, md_seed) rows")

metrics = []
for row in rows:
    directory = PRODUCTION / row["system_id"] / f'seed_{row["md_seed"]}'
    required = ["COMPLETE.json", "prod.tpr", "prod.xtc", "prod.cpt", "prod.gro", "prod.log"]
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise SystemExit(f"missing {missing}: {directory}")
    if "Finished mdrun on rank 0" not in (directory / "prod.log").read_text(errors="replace"):
        raise SystemExit(f"normal termination marker absent: {directory}")
    (directory / "interface.sel").write_text(
        'molindex 1;\nmolindex 2;\nmolindex 1 and group "Backbone";\n'
        'molindex 2 and group "Backbone";\n'
        '(molindex 1 or molindex 2) and group "Backbone";\n',
        encoding="utf-8",
    )
    run([str(GMX), "select", "-s", "prod.tpr", "-sf", "interface.sel", "-on", "interface.ndx"], directory)
    validate_index_groups(directory / "interface.ndx")
    if not (directory / "prod_whole.xtc").is_file():
        run(
            [str(GMX), "trjconv", "-s", "prod.tpr", "-f", "prod.xtc", "-o", "prod_whole.xtc", "-pbc", "mol", "-ur", "compact"],
            directory,
            "0\n",
        )
    run([str(GMX), "rms", "-s", "prod.tpr", "-f", "prod_whole.xtc", "-n", "interface.ndx", "-o", "vhh_rmsd.xvg", "-tu", "ns"], directory, "2\n3\n")
    run([str(GMX), "rms", "-s", "prod.tpr", "-f", "prod_whole.xtc", "-n", "interface.ndx", "-o", "complex_rmsd.xvg", "-tu", "ns"], directory, "4\n4\n")
    run(
        [str(GMX), "mindist", "-s", "prod.tpr", "-f", "prod_whole.xtc", "-n", "interface.ndx", "-od", "mindist.xvg", "-on", "contacts.xvg", "-d", "0.45", "-tu", "ns"],
        directory,
        "0\n1\n",
    )
    run(
        [str(GMX), "hbond", "-s", "prod.tpr", "-f", "prod_whole.xtc", "-n", "interface.ndx", "-r", 'group "molindex_1"', "-t", 'group "molindex_2"', "-num", "hbonds.xvg", "-tu", "ns"],
        directory,
    )
    series = {
        "vhh_rmsd_nm_mean": values(directory / "vhh_rmsd.xvg"),
        "complex_rmsd_nm_mean": values(directory / "complex_rmsd.xvg"),
        "min_distance_nm_mean": values(directory / "mindist.xvg"),
        "contacts_045nm_mean": values(directory / "contacts.xvg"),
        "interface_hbonds_mean": values(directory / "hbonds.xvg"),
    }
    result: dict[str, object] = {
        "system_id": row["system_id"],
        "pair_id": row["pair_id"],
        "pair_role": row["pair_role"],
        "md_seed": int(row["md_seed"]),
        "analysis_window_ns": "1.0-2.0",
    }
    for name, data in series.items():
        result[name] = statistics.mean(data)
        result[name.replace("_mean", "_median")] = statistics.median(data)
        result[name.replace("_mean", "_stdev")] = statistics.pstdev(data)
    metrics.append(result)

with (REPORTS / "md_expansion_seed_metrics.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(metrics[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(metrics)

directions = {
    "vhh_rmsd_nm_mean": "low",
    "complex_rmsd_nm_mean": "low",
    "min_distance_nm_mean": "low",
    "contacts_045nm_mean": "high",
    "interface_hbonds_mean": "high",
}
pair_rows = []
for pair_id in sorted({str(row["pair_id"]) for row in metrics}):
    positive = {int(row["md_seed"]): row for row in metrics if row["pair_id"] == pair_id and row["pair_role"] == "positive"}
    negative = {int(row["md_seed"]): row for row in metrics if row["pair_id"] == pair_id and row["pair_role"] == "destructive"}
    if set(positive) != {917, 1931, 3253} or set(negative) != set(positive):
        raise SystemExit(
            f"{pair_id} positive/destructive seed mismatch: "
            f"positive={sorted(positive)}, destructive={sorted(negative)}"
        )
    for metric, direction in directions.items():
        checks, deltas = [], []
        for seed in sorted(positive):
            p, n = float(positive[seed][metric]), float(negative[seed][metric])
            checks.append(int(p < n if direction == "low" else p > n))
            deltas.append(p - n)
        fraction = statistics.mean(checks)
        pair_rows.append(
            {
                "pair_id": pair_id,
                "metric": metric,
                "expected_positive_direction": direction,
                "seed_direction_fraction": fraction,
                "paired_seed_delta_median": statistics.median(deltas),
                "passes_2_of_3": fraction >= 2 / 3,
            }
        )

with (REPORTS / "md_expansion_pair_directions.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(pair_rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(pair_rows)

pilot = list(
    csv.DictReader(
        (REPORTS / "md_stage_a_p20_f99a_directions.tsv").open(newline="", encoding="utf-8"),
        delimiter="\t",
    )
)
combined = [
    {
        "pair_id": "P20_F99A",
        "metric": row["metric"],
        "seed_direction_fraction": float(row["seed_direction_fraction"]),
        "passes_2_of_3": row["passes_2_of_3"] == "True",
    }
    for row in pilot
] + [
    {
        "pair_id": row["pair_id"],
        "metric": row["metric"],
        "seed_direction_fraction": float(row["seed_direction_fraction"]),
        "passes_2_of_3": bool(row["passes_2_of_3"]),
    }
    for row in pair_rows
]
metric_summary = []
for metric in directions:
    relevant = [row for row in combined if row["metric"] == metric]
    fraction = statistics.mean(bool(row["passes_2_of_3"]) for row in relevant)
    metric_summary.append(
        {
            "metric": metric,
            "families_total": len(relevant),
            "families_passing_2_of_3": sum(bool(row["passes_2_of_3"]) for row in relevant),
            "family_direction_fraction": fraction,
            "accepted_secondary_metric": fraction >= 0.75,
        }
    )
with (REPORTS / "md_combined_four_family_metric_summary.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(metric_summary[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(metric_summary)

interface = {"min_distance_nm_mean", "contacts_045nm_mean", "interface_hbonds_mean"}
pair_interface_passes = {
    pair: sum(
        bool(row["passes_2_of_3"])
        for row in combined
        if row["pair_id"] == pair and row["metric"] in interface
    )
    for pair in sorted({str(row["pair_id"]) for row in combined})
}
accepted = [row["metric"] for row in metric_summary if row["accepted_secondary_metric"]]
gate = len(accepted) >= 3 and all(value >= 2 for value in pair_interface_passes.values())
receipt = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "state": "MD_EXPANSION_ANALYSIS_COMPLETE",
    "expansion_trajectories": len(metrics),
    "combined_pairs": sorted(pair_interface_passes),
    "accepted_secondary_metrics": accepted,
    "pair_interface_metrics_passing": pair_interface_passes,
    "four_family_gate": "PASS" if gate else "FAIL",
    "decision": "MD_CALIBRATED_SECONDARY_SIGNAL" if gate else "MD_DESCRIPTIVE_ONLY",
    "evidence_boundary": "Short MD remains a secondary computational stability signal, not affinity or blocking proof.",
}
temporary = REPORTS / ".MD_EXPANSION_CALIBRATION_RECEIPT.json.tmp"
temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, REPORTS / "MD_EXPANSION_CALIBRATION_RECEIPT.json")
print(json.dumps(receipt, indent=2))
