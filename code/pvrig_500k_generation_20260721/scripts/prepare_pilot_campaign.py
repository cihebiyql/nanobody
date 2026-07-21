#!/usr/bin/env python3
"""Freeze the PVRIG 25k pilot inputs and materialize resumable generation tasks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
from collections import Counter
from pathlib import Path


CURRENT_PARENT_RE = re.compile(r"__(C\d+)__")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def allocate_labels(counts: dict[str, int], seed: int) -> list[str]:
    labels = [label for label, count in counts.items() for _ in range(count)]
    random.Random(seed).shuffle(labels)
    return labels


def cdr3_bin(length: int) -> str:
    if 18 <= length <= 22:
        return "18_22"
    if 16 <= length <= 17:
        return "16_17"
    if 10 <= length <= 15:
        return "10_15"
    return "other"


def sequence_order_cdr3(sequence: str, length: int) -> str:
    """Recover CDR3 in sequence order when ANARCI insertion columns were reordered."""
    candidates = [
        sequence[match.end() : match.end() + length]
        for match in re.finditer(r"[FY].C", sequence)
        if match.start() >= 70 and match.end() + length + 8 <= len(sequence)
    ]
    if len(candidates) != 1:
        raise ValueError(f"could not uniquely recover CDR3 of length {length}")
    return candidates[0]


def sequence_order_cdr12(sequence: str, cdr: str, region: str) -> str:
    bounds = {"cdr1": (5, 50), "cdr2": (25, 85)}
    start, stop = bounds[region]
    exact = sequence.find(cdr, start, min(len(sequence), stop + len(cdr)))
    if exact >= 0 and exact <= stop:
        return cdr
    candidates = {
        sequence[position : position + len(cdr)]
        for position in range(start, min(stop, len(sequence) - len(cdr)) + 1)
        if Counter(sequence[position : position + len(cdr)]) == Counter(cdr)
    }
    if len(candidates) != 1:
        raise ValueError(f"could not uniquely recover {region} in sequence order")
    return candidates.pop()


def current_parent_ids(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    parents: set[str] = set()
    for row in read_tsv(path):
        match = CURRENT_PARENT_RE.search(row.get("entity_id", ""))
        if match:
            parents.add(match.group(1))
    return parents


def build_tasks(
    spec: dict[str, object],
    parents: list[dict[str, str]],
    current_parents: set[str],
) -> list[dict[str, object]]:
    factor = float(spec["raw_generation_policy"]["initial_overgeneration_factor"])
    patch_counts = {"C_CROSS": 2600, "B_LOWER": 2275, "A_CENTER": 1625}
    mode_counts = {"H1H2H3": 2925, "H1H3": 2275, "H3": 1300}
    length_counts = {"18_22": 4550, "16_17": 1300, "10_15": 650}
    raw_per_route = round(5000 * factor)
    if raw_per_route != 6500:
        raise ValueError("v1 task materializer requires a 1.3 overgeneration factor")
    if not all(sum(x.values()) == raw_per_route for x in (patch_counts, mode_counts, length_counts)):
        raise AssertionError("quota counts do not sum to raw route target")

    by_bin: dict[str, list[dict[str, str]]] = {key: [] for key in length_counts}
    for parent in parents:
        sequence_cdr3 = parent.get("cdr3_sequence_order", parent["cdr3"])
        bucket = cdr3_bin(len(sequence_cdr3))
        if bucket in by_bin:
            by_bin[bucket].append(parent)
    if any(not values for values in by_bin.values()):
        raise ValueError("Top200 input does not cover every requested CDR3 length bin")

    route_registry = {
        "conservative_cdr_redesign": ("LOCAL_CPU_READY", False),
        "natural_cdr_donor": ("LOCAL_CPU_READY", False),
        "fixed_pose_mpnn_antifold": ("BLOCKED_NO_VALIDATED_FIXED_POSE_OR_ANTIFOLD_INPUT", True),
        "epitope_conditioned_rfantibody": ("NODE1_GPU_READY_PENDING_LIVE_RESOURCE_CHECK", True),
        "denovo_disagreement_control": ("BLOCKED_NO_VALIDATED_GENERATOR", False),
    }

    rows: list[dict[str, object]] = []
    for route_index, route in enumerate(spec["routes"]):
        route_id = str(route["route_id"])
        patches = allocate_labels(patch_counts, 917 + route_index * 101)
        modes = allocate_labels(mode_counts, 1931 + route_index * 101)
        bins = allocate_labels(length_counts, 3253 + route_index * 101)
        per_bin_cursor = Counter()
        implementation_status, patch_conditioned = route_registry[route_id]
        for ordinal in range(raw_per_route):
            bucket = bins[ordinal]
            pool = by_bin[bucket]
            parent = pool[(per_bin_cursor[bucket] + route_index * 13) % len(pool)]
            per_bin_cursor[bucket] += 1
            task_id = f"P25K__{route_id.upper()}__{ordinal + 1:05d}"
            seed = int(sha256_text(f"{task_id}|20260721")[:8], 16)
            rows.append(
                {
                    "task_id": task_id,
                    "route_id": route_id,
                    "route_ordinal": ordinal + 1,
                    "generation_seed": seed,
                    "implementation_status": implementation_status,
                    "target_patch_assignment": patches[ordinal],
                    "patch_conditioned_generation": str(patch_conditioned).lower(),
                    "design_mode": modes[ordinal],
                    "requested_cdr3_length_bin": bucket,
                    "parent_id": parent["sequence_id"],
                    "parent_cluster": parent["cluster_id"],
                    "parent_is_current_v29": str(parent["cluster_id"] in current_parents).lower(),
                    "parent_sequence": parent["sequence_aa"],
                    "parent_sequence_sha256": sha256_text(parent["sequence_aa"]),
                    "parent_cdr1": parent.get("cdr1_sequence_order", parent["cdr1"]),
                    "parent_cdr2": parent.get("cdr2_sequence_order", parent["cdr2"]),
                    "parent_cdr3": parent.get("cdr3_sequence_order", parent["cdr3"]),
                    "parent_cdr3_len": len(parent.get("cdr3_sequence_order", parent["cdr3"])),
                    "status": "PENDING",
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--parents", type=Path, required=True)
    parser.add_argument("--parents-fasta", type=Path, required=True)
    parser.add_argument("--positives", type=Path, required=True)
    parser.add_argument("--positive-fasta", type=Path, required=True)
    parser.add_argument("--current-v29-dual", type=Path)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    all_parents = read_csv(args.parents)
    if len(all_parents) != 200:
        raise ValueError(f"expected exactly 200 parents, found {len(all_parents)}")
    if len({row["sequence_aa"] for row in all_parents}) != 200:
        raise ValueError("Top200 contains duplicate sequences")
    if len({row["cluster_id"] for row in all_parents}) != 200:
        raise ValueError("Top200 contains duplicate parent clusters")
    required = {"sequence_id", "sequence_aa", "cluster_id", "cdr1", "cdr2", "cdr3", "cdr3_len"}
    if not required.issubset(all_parents[0]):
        raise ValueError(f"parent table missing fields: {sorted(required - set(all_parents[0]))}")
    parent_target = int(spec["quota_targets"]["parent_cluster_target_max"])
    parents = all_parents[:parent_target]
    cdr_order_mismatches = Counter()
    for parent in parents:
        for region in ("cdr1", "cdr2"):
            recovered = sequence_order_cdr12(parent["sequence_aa"], parent[region], region)
            parent[f"{region}_sequence_order"] = recovered
            cdr_order_mismatches[region] += recovered != parent[region]
        recovered = sequence_order_cdr3(parent["sequence_aa"], int(parent["cdr3_len"]))
        parent["cdr3_sequence_order"] = recovered
        cdr_order_mismatches["cdr3"] += recovered != parent["cdr3"]

    # Build and validate everything in memory before touching campaign state.
    current = current_parent_ids(args.current_v29_dual)
    tasks = build_tasks(spec, parents, current)
    route_counts = Counter(str(row["route_id"]) for row in tasks)
    parent_counts = Counter(str(row["parent_cluster"]) for row in tasks)
    new_parent_tasks = sum(row["parent_is_current_v29"] == "false" for row in tasks)
    min_parent_count = int(spec["quota_targets"]["parent_cluster_target_min"])
    max_parent_count = int(spec["quota_targets"]["parent_cluster_target_max"])
    if not min_parent_count <= len(parent_counts) <= max_parent_count:
        raise ValueError(f"parent cluster count outside frozen range: {len(parent_counts)}")
    max_parent_fraction = max(parent_counts.values()) / len(tasks)
    if max_parent_fraction > float(spec["quota_targets"]["max_single_parent_fraction"]):
        raise ValueError(f"single-parent raw-task cap exceeded: {max_parent_fraction:.6f}")
    new_parent_fraction = new_parent_tasks / len(tasks)
    if new_parent_fraction < float(spec["quota_targets"]["min_new_parent_fraction"]):
        raise ValueError(f"new-parent raw-task fraction too low: {new_parent_fraction:.6f}")
    summary = {
        "schema_version": 1,
        "campaign_id": spec["campaign_id"],
        "status": "PREFLIGHT_READY_PARTIAL_GENERATORS",
        "task_count": len(tasks),
        "effective_target": spec["pilot_effective_target"],
        "raw_target_per_route": dict(sorted(route_counts.items())),
        "parent_count": len(parent_counts),
        "max_raw_tasks_per_parent": max(parent_counts.values()),
        "current_v29_parent_count_from_local_evidence": len(current),
        "new_parent_raw_task_fraction": new_parent_fraction,
        "max_single_parent_raw_task_fraction": max_parent_fraction,
        "parent_cdr_anarci_order_mismatch_counts": dict(sorted(cdr_order_mismatches.items())),
        "implementation_status_counts": dict(
            sorted(Counter(str(row["implementation_status"]) for row in tasks).items())
        ),
        "known_limitations": [
            "target_patch_assignment is not a conditioning input for the two local CPU routes",
            "fixed-pose/AntiFold route is blocked until a validated pose or AntiFold deployment is frozen",
            "de novo route is blocked until a validated generator is frozen",
            "RFantibody route requires a fresh Node1 GPU and disk preflight before launch",
            "current-top20 parent cap is enforced at effective-candidate merge after the authoritative top20 list is frozen",
            "CDR3 80-percent family cap is enforced after sequence generation, not at task materialization",
        ],
    }

    campaign = args.campaign_dir
    inputs = campaign / "inputs"
    manifests = campaign / "manifests"
    reports = campaign / "reports"
    status = campaign / "status"
    for path in (inputs, manifests, reports, status, campaign / "raw", campaign / "qc", campaign / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    # READY is the consumption gate; remove it before any stateful rewrite.
    (status / "PREFLIGHT_READY.json").unlink(missing_ok=True)

    frozen = {
        "pilot25000_spec.json": args.spec,
        "top_200_vhh_scaffolds_for_design.csv": args.parents,
        "top_200_vhh_scaffolds_for_design.fasta": args.parents_fasta,
        "known_positive_CDR_table.csv": args.positives,
        "known_positive_antibodies.fasta": args.positive_fasta,
    }
    for name, source in frozen.items():
        shutil.copy2(source, inputs / name)

    (inputs / "current_v29_parent_clusters.txt").write_text(
        "".join(f"{parent}\n" for parent in sorted(current)), encoding="utf-8"
    )
    fields = list(tasks[0])
    write_tsv(manifests / "pilot_generation_tasks.tsv", tasks, fields)
    (reports / "preflight_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checksum_paths = sorted(
        [path for path in inputs.iterdir() if path.is_file()]
        + [manifests / "pilot_generation_tasks.tsv", reports / "preflight_summary.json"]
    )
    with (manifests / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in checksum_paths:
            if path.name == "SHA256SUMS":
                continue
            handle.write(f"{sha256_file(path)}  {path.relative_to(campaign)}\n")
    (status / "PREFLIGHT_READY.json").write_text(
        json.dumps(
            {
                "status": summary["status"],
                "task_manifest": "manifests/pilot_generation_tasks.tsv",
                "task_manifest_sha256": sha256_file(manifests / "pilot_generation_tasks.tsv"),
                "summary_sha256": sha256_file(reports / "preflight_summary.json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
