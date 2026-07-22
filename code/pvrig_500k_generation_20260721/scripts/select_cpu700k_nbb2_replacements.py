#!/usr/bin/env python3
"""Replace deterministic NBB2-incompatible CPU candidates route-for-route."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


COMMON = [
    "candidate_id", "sequence", "sequence_sha256", "sequence_length", "route_id",
    "generation_seed", "target_patch_assignment", "design_mode", "parent_id",
    "parent_cluster", "cdr1_after", "cdr2_after", "cdr3_after", "designed_regions",
    "generator", "generator_version", "generation_batch", "max_positive_cdr_identity",
    "max_positive_cdr_identity_detail",
]
SOURCE = [
    "source_candidate_id", "source_run_id", "source_arm_id",
    "source_backbone_group_id", "source_pose_id", "source_mpnn_index", "source_row_kind",
]


def op(path: Path, mode: str):
    return gzip.open(path, mode, newline="") if path.suffix == ".gz" else path.open(mode, newline="")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: str | None, default: float) -> float:
    try:
        result = float(value or "")
        return result if math.isfinite(result) else default
    except ValueError:
        return default


def quality(row: dict[str, str]) -> tuple:
    tier = {"LOW": 0, "MODERATE": 1}.get(row.get("risk_tier", ""), 2)
    return (
        tier,
        number(row.get("developability_risk_proxy_partial"), 1e9),
        number(row.get("expression_purity_risk_proxy_partial"), 1e9),
        -number(row.get("AbNatiV VHH Score"), -1),
        -number(row.get("mean_self_probability"), -1),
        number(row.get("binding_model_raw_disagreement"), 1e9),
        -0.5 * (
            number(row.get("deepnano_binding_prior"), 0)
            + number(row.get("nanobind_binding_prior"), 0)
        ),
        row["candidate_id"],
    )


def full_gate(row: dict[str, str]) -> bool:
    return (
        row.get("anarci_qc_status") == "PASS"
        and row.get("abnativ_status") == "PASS"
        and row.get("numbered_sequence_matches_input_slice") == "True"
        and row.get("imgt_cys23") == "C"
        and row.get("imgt_cys104") == "C"
        # Calibrated against ImmuneBuilder's exact min(IMGT)<8 and
        # max(IMGT)>120 sanity check.  In this library FR1 length 19 maps to
        # min=7 and FR4 length 8 maps to max=125; both are model-valid.
        and len(row.get("anarci_fr1", "")) >= 19
        and len(row.get("anarci_fr4", "")) >= 4
        and row.get("risk_tier") in {"LOW", "MODERATE"}
        and 95 <= int(row.get("sequence_length") or 0) <= 160
        # Replacement structures must avoid the observed OpenMM topology
        # failure mode caused by stochastic extra-CDR disulfide assignment.
        and row.get("sequence", "").count("C") == 2
        and number(row.get("max_positive_cdr_identity"), 1) < 0.8
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", type=Path, action="append", required=True)
    parser.add_argument("--invalid", type=Path, required=True)
    parser.add_argument("--reserve-candidates", type=Path, required=True)
    parser.add_argument("--reserve-prefilter", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=700000)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with op(args.invalid, "rt") as handle:
        invalid_rows = list(csv.DictReader(handle, delimiter="\t"))
    invalid_ids = {row["candidate_id"] for row in invalid_rows}
    invalid_route = Counter(row["route_id"] for row in invalid_rows)
    if len(invalid_ids) != len(invalid_rows):
        raise SystemExit("invalid audit IDs are not exact unique")

    reserve: dict[str, dict[str, str]] = {}
    with op(args.reserve_candidates, "rt") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["candidate_id"] in reserve:
                raise SystemExit(f"duplicate reserve ID: {row['candidate_id']}")
            reserve[row["candidate_id"]] = row

    prefilter: dict[str, dict[str, str]] = {}
    prefilter_fields: list[str] | None = None
    with op(args.reserve_prefilter, "rt") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        prefilter_fields = list(reader.fieldnames or [])
        for row in reader:
            candidate_id = row["candidate_id"]
            if candidate_id in prefilter:
                raise SystemExit(f"duplicate prefilter ID: {candidate_id}")
            prefilter[candidate_id] = row
    if set(reserve) != set(prefilter):
        raise SystemExit(
            f"reserve/prefilter ID mismatch missing={len(set(reserve)-set(prefilter))} "
            f"extra={len(set(prefilter)-set(reserve))}"
        )

    grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    gate_failures: Counter[str] = Counter()
    for candidate_id, candidate in reserve.items():
        row = dict(candidate)
        row.update(prefilter[candidate_id])
        if not full_gate(row):
            gate_failures[candidate["route_id"]] += 1
            continue
        grouped[candidate["route_id"]][candidate.get("parent_cluster", "UNKNOWN")].append(row)

    selected: list[dict[str, str]] = []
    selected_counts: Counter[str] = Counter()
    selected_parent_counts: Counter[tuple[str, str]] = Counter()
    for route, target in sorted(invalid_route.items()):
        queues = {
            parent: deque(sorted(rows, key=quality))
            for parent, rows in grouped[route].items()
        }
        parents = sorted(queues)
        while selected_counts[route] < target:
            progressed = False
            for parent in parents:
                if not queues[parent]:
                    continue
                row = queues[parent].popleft()
                selected.append(row)
                selected_counts[route] += 1
                selected_parent_counts[(route, parent)] += 1
                progressed = True
                if selected_counts[route] == target:
                    break
            if not progressed:
                raise SystemExit(
                    f"insufficient fully passing replacements for {route}: "
                    f"{selected_counts[route]} < {target}"
                )

    selected_ids = {row["candidate_id"] for row in selected}
    selected_sequences = {row["sequence"] for row in selected}
    if len(selected_ids) != len(selected) or len(selected_sequences) != len(selected):
        raise SystemExit("selected replacements are not exact unique")

    candidate_path = args.output_dir / "cpu700k_corrected.tsv.gz"
    fasta_path = args.output_dir / "cpu700k_corrected.fasta.gz"
    replacement_path = args.output_dir / "replacement_selected3031.tsv.gz"
    replacement_prefilter_path = args.output_dir / "replacement_selected3031_prefilter.tsv.gz"
    replacement_fasta_path = args.output_dir / "replacement_selected3031.fasta.gz"
    mapping_path = args.output_dir / "replacement_map.tsv.gz"
    fields = COMMON + SOURCE
    final_ids: set[str] = set()
    final_sequences: set[str] = set()
    final_routes: Counter[str] = Counter()
    cpu_rows = 0
    with gzip.open(candidate_path, "wt", newline="") as out, gzip.open(fasta_path, "wt") as fasta:
        writer = csv.DictWriter(out, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for source in args.cpu:
            with op(source, "rt") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    if row["candidate_id"] in invalid_ids:
                        continue
                    candidate_id, sequence = row["candidate_id"], row["sequence"]
                    if candidate_id in final_ids or sequence in final_sequences:
                        raise SystemExit(f"CPU duplicate after removal: {candidate_id}")
                    final_ids.add(candidate_id); final_sequences.add(sequence)
                    final_routes[row["route_id"]] += 1; cpu_rows += 1
                    writer.writerow(row); fasta.write(f">{candidate_id}\n{sequence}\n")
        for row in selected:
            candidate_id, sequence = row["candidate_id"], row["sequence"]
            if candidate_id in final_ids or sequence in final_sequences:
                raise SystemExit(f"replacement overlaps retained CPU: {candidate_id}")
            final_ids.add(candidate_id); final_sequences.add(sequence)
            final_routes[row["route_id"]] += 1; cpu_rows += 1
            writer.writerow(row); fasta.write(f">{candidate_id}\n{sequence}\n")

    if cpu_rows != args.expected or len(final_ids) != args.expected or len(final_sequences) != args.expected:
        raise SystemExit(f"corrected CPU closure failed: {cpu_rows}")
    expected_routes = {
        "conservative_cdr_redesign": 400000,
        "natural_cdr_donor": 200000,
        "profile_diversified_exploration_control": 100000,
    }
    if args.expected == 700000 and dict(final_routes) != expected_routes:
        raise SystemExit(f"corrected route counts mismatch: {dict(final_routes)}")

    selected.sort(key=lambda row: row["candidate_id"])
    with gzip.open(replacement_path, "wt", newline="") as handle, gzip.open(replacement_fasta_path, "wt") as fasta:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in selected:
            writer.writerow(row); fasta.write(f">{row['candidate_id']}\n{row['sequence']}\n")
    with gzip.open(replacement_prefilter_path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prefilter_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in selected:
            writer.writerow(prefilter[row["candidate_id"]])
    with gzip.open(mapping_path, "wt", newline="") as handle:
        map_fields = ["route_id", "removed_candidate_id", "replacement_candidate_id"]
        writer = csv.DictWriter(handle, fieldnames=map_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        removed_by_route = defaultdict(list)
        selected_by_route = defaultdict(list)
        for row in invalid_rows: removed_by_route[row["route_id"]].append(row["candidate_id"])
        for row in selected: selected_by_route[row["route_id"]].append(row["candidate_id"])
        for route in sorted(invalid_route):
            for removed, replacement in zip(sorted(removed_by_route[route]), sorted(selected_by_route[route]), strict=True):
                writer.writerow({"route_id": route, "removed_candidate_id": removed, "replacement_candidate_id": replacement})

    outputs = [candidate_path, fasta_path, replacement_path, replacement_prefilter_path, replacement_fasta_path, mapping_path]
    receipt = {
        "status": "READY_FOR_REPLACEMENT_NBB2_TNP",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": args.expected,
        "removed_records": len(invalid_rows),
        "removed_route_counts": dict(sorted(invalid_route.items())),
        "replacement_records": len(selected),
        "replacement_route_counts": dict(sorted(selected_counts.items())),
        "replacement_gate_failure_counts": dict(sorted(gate_failures.items())),
        "replacement_parent_cluster_counts": {
            route: len({parent for item_route, parent in selected_parent_counts if item_route == route})
            for route in selected_counts
        },
        "replacement_max_per_parent": {
            route: max(count for (item_route, _), count in selected_parent_counts.items() if item_route == route)
            for route in selected_counts
        },
        "route_counts": dict(sorted(final_routes.items())),
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "technical_na_is_not_biological_negative": True,
        "outputs": {path.name: sha(path) for path in outputs},
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(
        "".join(f"{receipt['outputs'][path.name]}  {path.name}\n" for path in outputs)
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
