#!/usr/bin/env python3
"""Collect Rosetta scores and evaluate pre-registered positive/control gates."""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724"
)
V3_ROOT = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else "/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714"
)
MANIFEST = ROOT / "manifests/ROSETTA_JOB_MANIFEST.tsv"
CONTROL_METADATA = V3_ROOT / "inputs/calibration_controls_47.tsv"
OUT = ROOT / "reports"
OUT.mkdir(parents=True, exist_ok=True)

METRICS = {
    "dG_cross": "low",
    "dG_cross/dSASAx100": "low",
    "dG_separated": "low",
    "dG_separated/dSASAx100": "low",
    "dSASA_int": "high",
    "delta_unsatHbonds": "low",
    "hbond_E_fraction": "low",
    "hbonds_int": "high",
    "packstat": "high",
    "per_residue_energy_int": "low",
    "sc_value": "high",
    "complex_normalized": "low",
    "haddock_score": "low",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_score(path: Path) -> dict[str, float]:
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("SCORE:")]
    if len(lines) != 2:
        raise RuntimeError(f"expected score header and one data row: {path}")
    header = lines[0][1:]
    values = lines[1][1:]
    if len(header) != len(values):
        raise RuntimeError(f"score column mismatch: {path}")
    result: dict[str, float] = {}
    for name, value in zip(header, values):
        if name != "description":
            result[name] = float(value)
    return result


def family(base: str) -> str:
    for token in ("151", "20", "30", "38", "39"):
        if token in base:
            return token
    return base


def auc(labels: list[int], values: list[float], direction: str) -> float:
    positives = [value for label, value in zip(labels, values) if label == 1]
    negatives = [value for label, value in zip(labels, values) if label == 0]
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive == negative:
                wins += 0.5
            elif (direction == "high" and positive > negative) or (
                direction == "low" and positive < negative
            ):
                wins += 1.0
    return wins / (len(positives) * len(negatives))


def threshold_result(
    labels: list[int], values: list[float], direction: str
) -> tuple[dict[str, float | bool], bool]:
    unique = sorted(set(values))
    candidates = [unique[0] - 1e-9, *unique, unique[-1] + 1e-9]
    scored: list[dict[str, float | bool]] = []
    for threshold in candidates:
        predictions = [
            int(value >= threshold) if direction == "high" else int(value <= threshold)
            for value in values
        ]
        tp = sum(label == 1 and pred == 1 for label, pred in zip(labels, predictions))
        fn = sum(label == 1 and pred == 0 for label, pred in zip(labels, predictions))
        fp = sum(label == 0 and pred == 1 for label, pred in zip(labels, predictions))
        tn = sum(label == 0 and pred == 0 for label, pred in zip(labels, predictions))
        recall = tp / (tp + fn)
        fpr = fp / (fp + tn)
        scored.append(
            {
                "threshold": threshold,
                "recall": recall,
                "fpr": fpr,
                "specificity": 1.0 - fpr,
                "balanced_accuracy": (recall + 1.0 - fpr) / 2.0,
                "gate_feasible": recall >= 0.80 and fpr <= 0.30,
            }
        )
    feasible = [row for row in scored if row["gate_feasible"]]
    pool = feasible or scored
    best = max(pool, key=lambda row: (row["balanced_accuracy"], row["recall"], -row["fpr"]))
    return best, bool(feasible)


manifest = read_tsv(MANIFEST)
metadata = {row["control_id"]: row for row in read_tsv(CONTROL_METADATA)}
if len(manifest) != 150:
    raise SystemExit(f"expected 150 manifest rows, found {len(manifest)}")

positive_by_base = {
    row["base_molecule"]: row["control_id"]
    for row in metadata.values()
    if row["control_class"] == "positive_control"
    and row["control_id"].startswith("CTRL_PATENT_")
}

jobs: list[dict[str, object]] = []
for row in manifest:
    score_path = ROOT / "rosetta/jobs" / row["job_id"] / "score.sc"
    complete_path = score_path.parent / "COMPLETE.json"
    if not score_path.is_file() or not complete_path.is_file():
        raise SystemExit(f"incomplete Rosetta job: {row['job_id']}")
    meta = metadata[row["entity_id"]]
    record: dict[str, object] = {
        **row,
        "label": 1 if row["control_class"] == "positive_control" else 0,
        "base_molecule": meta["base_molecule"],
        "family": family(meta["base_molecule"]),
        "mutation_class": meta["mutation_class"],
    }
    record.update(parse_score(score_path))
    for name in ("haddock_score",):
        record[name] = float(row[name])
    jobs.append(record)

entity_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
for row in jobs:
    entity_groups[str(row["entity_id"])].append(row)
entities: list[dict[str, object]] = []
for entity_id, rows in entity_groups.items():
    first = rows[0]
    entity: dict[str, object] = {
        "entity_id": entity_id,
        "label": first["label"],
        "control_class": first["control_class"],
        "base_molecule": first["base_molecule"],
        "family": first["family"],
        "mutation_class": first["mutation_class"],
        "job_count": len(rows),
    }
    for metric in METRICS:
        entity[metric] = statistics.median(float(row[metric]) for row in rows)
    entities.append(entity)

job_index = {
    (str(row["entity_id"]), str(row["conformation"]), str(row["docking_seed"])): row
    for row in jobs
}
pair_rows: list[dict[str, object]] = []
for negative in jobs:
    if negative["label"] != 0:
        continue
    base = str(negative["base_molecule"])
    positive_entity = positive_by_base[base]
    positive = job_index[
        (positive_entity, str(negative["conformation"]), str(negative["docking_seed"]))
    ]
    pair: dict[str, object] = {
        "base_molecule": base,
        "family": family(base),
        "negative_entity_id": negative["entity_id"],
        "positive_entity_id": positive_entity,
        "conformation": negative["conformation"],
        "docking_seed": negative["docking_seed"],
    }
    for metric, direction in METRICS.items():
        p, n = float(positive[metric]), float(negative[metric])
        pair[f"{metric}_positive"] = p
        pair[f"{metric}_negative"] = n
        pair[f"{metric}_direction_correct"] = int(p > n if direction == "high" else p < n)
    pair_rows.append(pair)

metric_rows: list[dict[str, object]] = []
labels = [int(row["label"]) for row in entities]
for metric, direction in METRICS.items():
    values = [float(row[metric]) for row in entities]
    metric_auc = auc(labels, values, direction)
    threshold, feasible = threshold_result(labels, values, direction)
    entity_pair_directions: list[int] = []
    for negative_entity in [row for row in entities if row["label"] == 0]:
        positive_entity_id = positive_by_base[str(negative_entity["base_molecule"])]
        positive_entity = next(row for row in entities if row["entity_id"] == positive_entity_id)
        p, n = float(positive_entity[metric]), float(negative_entity[metric])
        entity_pair_directions.append(int(p > n if direction == "high" else p < n))
    family_directions = []
    by_family_positive: dict[str, list[float]] = defaultdict(list)
    by_family_negative: dict[str, list[float]] = defaultdict(list)
    for row in entities:
        target = by_family_positive if row["label"] == 1 else by_family_negative
        target[str(row["family"])].append(float(row[metric]))
    for fam in sorted(set(by_family_positive) & set(by_family_negative)):
        p = statistics.median(by_family_positive[fam])
        n = statistics.median(by_family_negative[fam])
        family_directions.append(int(p > n if direction == "high" else p < n))
    pair_fraction = statistics.mean(entity_pair_directions)
    family_fraction = statistics.mean(family_directions)
    accepted = (
        metric_auc >= 0.70
        and feasible
        and pair_fraction >= 0.70
        and family_fraction >= 0.70
        and not math.isclose(max(values), min(values))
    )
    metric_rows.append(
        {
            "metric": metric,
            "direction": direction,
            "entity_auc": round(metric_auc, 6),
            "threshold": threshold["threshold"],
            "positive_recall": round(float(threshold["recall"]), 6),
            "control_fpr": round(float(threshold["fpr"]), 6),
            "balanced_accuracy": round(float(threshold["balanced_accuracy"]), 6),
            "threshold_gate_feasible": feasible,
            "paired_entity_direction_fraction": round(pair_fraction, 6),
            "family_direction_fraction": round(family_fraction, 6),
            "nonconstant": not math.isclose(max(values), min(values)),
            "accepted_for_candidate_ranking": accepted,
        }
    )

job_fields = list(jobs[0])
write_tsv(OUT / "rosetta_job_scores.tsv", jobs, job_fields)
entity_fields = list(entities[0])
write_tsv(OUT / "rosetta_entity_medians.tsv", entities, entity_fields)
write_tsv(OUT / "rosetta_pair_directions.tsv", pair_rows, list(pair_rows[0]))
write_tsv(OUT / "rosetta_metric_calibration.tsv", metric_rows, list(metric_rows[0]))

accepted_metrics = [row["metric"] for row in metric_rows if row["accepted_for_candidate_ranking"]]
receipt = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "state": "CALIBRATION_COMPLETE",
    "job_count": len(jobs),
    "entity_count": len(entities),
    "positive_entities": sum(row["label"] == 1 for row in entities),
    "destructive_entities": sum(row["label"] == 0 for row in entities),
    "matched_job_pairs": len(pair_rows),
    "metric_acceptance_contract": {
        "entity_auc_min": 0.70,
        "positive_recall_min": 0.80,
        "control_fpr_max": 0.30,
        "paired_entity_direction_min": 0.70,
        "family_direction_min": 0.70,
    },
    "accepted_metrics": accepted_metrics,
    "decision": "PROMOTE_ACCEPTED_METRICS" if accepted_metrics else "ROSETTA_DESCRIPTIVE_ONLY",
}
(OUT / "ROSETTA_CALIBRATION_RECEIPT.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2))
