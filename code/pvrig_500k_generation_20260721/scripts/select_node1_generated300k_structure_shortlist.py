#!/usr/bin/env python3
"""Select a route-normalized, diversity-capped NBB2 shortlist from the Node1 300k pool."""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def route(candidate_id: str) -> str:
    if "source_rfantibody" in candidate_id:
        return "rfantibody"
    if "source_fixed_pose_mpnn" in candidate_id:
        return "fixed_pose_mpnn"
    return "other"


@dataclass
class Candidate:
    row: dict[str, str]
    route: str
    percentiles: dict[str, float]
    developability_component: float
    binding_component: float
    prestructure_score: float
    disagreement_percentile: float
    abnativ_na: bool
    cdr3: str

    @property
    def candidate_id(self) -> str:
        return self.row["candidate_id"]


class RoutePercentiles:
    def __init__(self, rows: list[dict[str, str]], fields: list[str]) -> None:
        self.values: dict[tuple[str, str], list[float]] = {}
        self.medians: dict[tuple[str, str], float] = {}
        by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
        for row in rows:
            candidate_route = route(row["candidate_id"])
            for field in fields:
                value = finite_float(row.get(field, ""))
                if value is not None:
                    by_key[(candidate_route, field)].append(value)
        for key, values in by_key.items():
            values.sort()
            self.values[key] = values
            self.medians[key] = statistics.median(values)

    def percentile(
        self,
        candidate_route: str,
        field: str,
        value: str,
        *,
        missing: float = 0.5,
    ) -> float:
        parsed = finite_float(value)
        values = self.values.get((candidate_route, field), [])
        if parsed is None or not values:
            return missing
        return bisect.bisect_right(values, parsed) / len(values)


class Cdr3FamilyIndex:
    """Greedy same-length Hamming clustering using d+1 exact-match bands."""

    def __init__(self) -> None:
        self.representatives: dict[str, str] = {}
        self.band_index: dict[tuple[int, int, str], set[str]] = defaultdict(set)
        self.next_id = 1

    @staticmethod
    def max_mismatches(sequence: str) -> int:
        return max(1, math.floor(0.20 * len(sequence)))

    @staticmethod
    def bands(sequence: str, pieces: int) -> list[str]:
        length = len(sequence)
        starts = [round(index * length / pieces) for index in range(pieces + 1)]
        return [sequence[starts[i] : starts[i + 1]] for i in range(pieces)]

    def assign(self, sequence: str) -> str:
        distance = self.max_mismatches(sequence)
        pieces = distance + 1
        candidate_ids: set[str] = set()
        for index, band in enumerate(self.bands(sequence, pieces)):
            candidate_ids.update(self.band_index.get((len(sequence), index, band), set()))
        for family_id in sorted(candidate_ids):
            representative = self.representatives[family_id]
            mismatches = sum(a != b for a, b in zip(sequence, representative))
            if len(sequence) == len(representative) and mismatches <= distance:
                return family_id
        family_id = f"CDR3FAM_{self.next_id:06d}"
        self.next_id += 1
        self.representatives[family_id] = sequence
        for index, band in enumerate(self.bands(sequence, pieces)):
            self.band_index[(len(sequence), index, band)].add(family_id)
        return family_id


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    ids = [row["candidate_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate IDs in multimetric input")
    return fields, rows


def build_candidates(rows: list[dict[str, str]]) -> list[Candidate]:
    metric_fields = [
        "developability_score",
        "expression_purity_risk_score",
        "sapiens_mean_self_probability",
        "abnativ_AbNatiV VHH Score",
        "deepnano_binding_prior",
        "nanobind_binding_prior",
        "novelty_score",
        "binding_model_percentile_disagreement",
    ]
    percentiles = RoutePercentiles(rows, metric_fields)
    candidates: list[Candidate] = []
    for row in rows:
        if row.get("sequence_hard_gate") != "True":
            continue
        candidate_route = route(row["candidate_id"])
        p = {
            field: percentiles.percentile(candidate_route, field, row.get(field, ""))
            for field in metric_fields
        }
        abnativ_na = row.get("abnativ_abnativ_status") != "PASS"
        developability_component = statistics.fmean(
            [
                p["developability_score"],
                p["expression_purity_risk_score"],
                p["sapiens_mean_self_probability"],
                p["abnativ_AbNatiV VHH Score"],
            ]
        )
        binding_component = statistics.fmean(
            [p["deepnano_binding_prior"], p["nanobind_binding_prior"]]
        )
        score = (
            0.35
            * statistics.fmean(
                [
                    p["developability_score"],
                    p["expression_purity_risk_score"],
                ]
            )
            + 0.20 * p["sapiens_mean_self_probability"]
            + 0.20 * p["abnativ_AbNatiV VHH Score"]
            + 0.15 * binding_component
            + 0.10 * p["novelty_score"]
        )
        if abnativ_na:
            score -= 0.05
        candidates.append(
            Candidate(
                row=row,
                route=candidate_route,
                percentiles=p,
                developability_component=developability_component,
                binding_component=binding_component,
                prestructure_score=score,
                disagreement_percentile=p[
                    "binding_model_percentile_disagreement"
                ],
                abnativ_na=abnativ_na,
                cdr3=row.get("IMGT_CDR3", ""),
            )
        )
    return candidates


def candidate_sort_key(candidate: Candidate) -> tuple[float, float, float, str]:
    return (
        -candidate.prestructure_score,
        -candidate.binding_component,
        -candidate.developability_component,
        candidate.candidate_id,
    )


def select_with_caps(
    ordered: list[Candidate],
    *,
    wanted: int,
    selected_ids: set[str],
    family_index: Cdr3FamilyIndex,
    exact_counts: Counter[str],
    family_counts: Counter[str],
    exact_cap: int,
    family_cap: int,
    lane: str,
    selected: list[tuple[Candidate, str, str]],
) -> int:
    added = 0
    for candidate in ordered:
        if added >= wanted or candidate.candidate_id in selected_ids:
            continue
        if exact_counts[candidate.cdr3] >= exact_cap:
            continue
        family_id = family_index.assign(candidate.cdr3)
        if family_counts[family_id] >= family_cap:
            continue
        selected_ids.add(candidate.candidate_id)
        exact_counts[candidate.cdr3] += 1
        family_counts[family_id] += 1
        selected.append((candidate, lane, family_id))
        added += 1
    return added


def select_route_main(
    route_candidates: list[Candidate],
    *,
    main_target: int,
    selected_ids: set[str],
    family_index: Cdr3FamilyIndex,
    exact_counts: Counter[str],
    family_counts: Counter[str],
) -> tuple[list[tuple[Candidate, str, str]], dict[str, int]]:
    main: list[tuple[Candidate, str, str]] = []
    lane_targets = {
        "EXPLOITATION": round(main_target * 0.70),
        "MODEL_DISAGREEMENT": round(main_target * 0.10),
        "DIVERSITY": round(main_target * 0.15),
    }
    lane_targets["SPECIAL_COVERAGE"] = main_target - sum(lane_targets.values())

    exploitation = sorted(route_candidates, key=candidate_sort_key)
    disagreement = sorted(
        [
            candidate
            for candidate in route_candidates
            if candidate.disagreement_percentile >= 0.85
            and candidate.developability_component >= 0.50
        ],
        key=lambda candidate: (
            -candidate.developability_component,
            -candidate.percentiles["novelty_score"],
            candidate.candidate_id,
        ),
    )
    diversity = sorted(
        route_candidates,
        key=lambda candidate: (
            -candidate.percentiles["novelty_score"],
            -candidate.prestructure_score,
            candidate.candidate_id,
        ),
    )
    special = sorted(
        [
            candidate
            for candidate in route_candidates
            if candidate.abnativ_na
            or len(candidate.cdr3) <= 8
            or len(candidate.cdr3) >= 18
        ],
        key=candidate_sort_key,
    )
    lane_inputs = {
        "EXPLOITATION": exploitation,
        "MODEL_DISAGREEMENT": disagreement,
        "DIVERSITY": diversity,
        "SPECIAL_COVERAGE": special,
    }
    lane_counts: dict[str, int] = {}
    for lane, target in lane_targets.items():
        lane_counts[lane] = select_with_caps(
            lane_inputs[lane],
            wanted=target,
            selected_ids=selected_ids,
            family_index=family_index,
            exact_counts=exact_counts,
            family_counts=family_counts,
            exact_cap=5,
            family_cap=25,
            lane=lane,
            selected=main,
        )
    if len(main) < main_target:
        lane_counts["BACKFILL"] = select_with_caps(
            exploitation,
            wanted=main_target - len(main),
            selected_ids=selected_ids,
            family_index=family_index,
            exact_counts=exact_counts,
            family_counts=family_counts,
            exact_cap=5,
            family_cap=25,
            lane="BACKFILL",
            selected=main,
        )
    if len(main) != main_target:
        raise ValueError(
            f"could not fill route main target {main_target}; selected={len(main)}"
        )

    return main, lane_counts


def select_route_reserve(
    route_candidates: list[Candidate],
    *,
    reserve_target: int,
    selected_ids: set[str],
    family_index: Cdr3FamilyIndex,
    exact_counts: Counter[str],
    family_counts: Counter[str],
) -> list[tuple[Candidate, str, str]]:
    reserve: list[tuple[Candidate, str, str]] = []
    added = select_with_caps(
        sorted(route_candidates, key=candidate_sort_key),
        wanted=reserve_target,
        selected_ids=selected_ids,
        family_index=family_index,
        exact_counts=exact_counts,
        family_counts=family_counts,
        exact_cap=8,
        family_cap=40,
        lane="RESERVE",
        selected=reserve,
    )
    if added != reserve_target:
        raise ValueError(
            f"could not fill route reserve target {reserve_target}; selected={added}"
        )
    return reserve


def write_selection(
    path: Path,
    fasta: Path,
    input_fields: list[str],
    rows: list[tuple[Candidate, str, str]],
) -> None:
    derived = [
        "structure_selection_route",
        "structure_selection_lane",
        "prestructure_priority_score",
        "route_developability_percentile",
        "route_binding_consensus_percentile",
        "route_binding_disagreement_percentile",
        "cdr3_near_family_id",
        "cdr3_family_definition",
        "sequence_sha256",
    ]
    with (
        gzip.open(path, "wt", newline="", compresslevel=1) as handle,
        gzip.open(fasta, "wt", compresslevel=1) as fasta_handle,
    ):
        writer = csv.DictWriter(
            handle,
            fieldnames=input_fields + derived,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for candidate, lane, family_id in rows:
            sequence = candidate.row["sequence"]
            row = dict(candidate.row)
            row.update(
                {
                    "structure_selection_route": candidate.route,
                    "structure_selection_lane": lane,
                    "prestructure_priority_score": f"{candidate.prestructure_score:.8f}",
                    "route_developability_percentile": (
                        f"{candidate.developability_component:.8f}"
                    ),
                    "route_binding_consensus_percentile": (
                        f"{candidate.binding_component:.8f}"
                    ),
                    "route_binding_disagreement_percentile": (
                        f"{candidate.disagreement_percentile:.8f}"
                    ),
                    "cdr3_near_family_id": family_id,
                    "cdr3_family_definition": (
                        "greedy_same_length_Hamming_identity_ge_80pct"
                    ),
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                }
            )
            writer.writerow(row)
            fasta_handle.write(f">{candidate.candidate_id}\n{sequence}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", type=int, default=300_000)
    parser.add_argument("--main", type=int, default=100_000)
    parser.add_argument("--reserve", type=int, default=20_000)
    args = parser.parse_args()

    fields, rows = load_rows(args.input)
    if len(rows) != args.expected:
        raise ValueError(f"expected {args.expected} records, found {len(rows)}")
    candidates = build_candidates(rows)
    by_route: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_route[candidate.route].append(candidate)
    required_routes = {"rfantibody", "fixed_pose_mpnn"}
    if set(by_route) != required_routes:
        raise ValueError(f"unexpected route set: {sorted(by_route)}")
    if args.main % 2 or args.reserve % 2:
        raise ValueError("main and reserve counts must be divisible by two")

    main: list[tuple[Candidate, str, str]] = []
    reserve: list[tuple[Candidate, str, str]] = []
    lane_counts: dict[str, dict[str, int]] = {}
    selected_ids: set[str] = set()
    family_index = Cdr3FamilyIndex()
    exact_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    for candidate_route in sorted(required_routes):
        route_main, route_lanes = select_route_main(
            by_route[candidate_route],
            main_target=args.main // 2,
            selected_ids=selected_ids,
            family_index=family_index,
            exact_counts=exact_counts,
            family_counts=family_counts,
        )
        main.extend(route_main)
        lane_counts[candidate_route] = route_lanes
    for candidate_route in sorted(required_routes):
        reserve.extend(
            select_route_reserve(
                by_route[candidate_route],
                reserve_target=args.reserve // 2,
                selected_ids=selected_ids,
                family_index=family_index,
                exact_counts=exact_counts,
                family_counts=family_counts,
            )
        )

    main.sort(key=lambda item: candidate_sort_key(item[0]))
    reserve.sort(key=lambda item: candidate_sort_key(item[0]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    main_table = args.output_dir / "STRUCTURE_PRIMARY_100K.tsv.gz"
    main_fasta = args.output_dir / "STRUCTURE_PRIMARY_100K.fasta.gz"
    reserve_table = args.output_dir / "STRUCTURE_RESERVE_20K.tsv.gz"
    reserve_fasta = args.output_dir / "STRUCTURE_RESERVE_20K.fasta.gz"
    write_selection(main_table, main_fasta, fields, main)
    write_selection(reserve_table, reserve_fasta, fields, reserve)

    main_routes = Counter(candidate.route for candidate, _, _ in main)
    reserve_routes = Counter(candidate.route for candidate, _, _ in reserve)
    main_lanes = Counter(lane for _, lane, _ in main)
    exact_cdr3 = Counter(candidate.cdr3 for candidate, _, _ in main)
    near_cdr3 = Counter(family_id for _, _, family_id in main)
    outputs = {
        path.name: sha256(path)
        for path in [main_table, main_fasta, reserve_table, reserve_fasta]
    }
    receipt = {
        "schema_version": "pvrig.node1_generated300k.structure_shortlist.v1",
        "status": "READY_FOR_STRUCTURE_PREDICTION",
        "input_records": len(rows),
        "hardpass_candidates": len(candidates),
        "main_records": len(main),
        "reserve_records": len(reserve),
        "main_route_counts": dict(sorted(main_routes.items())),
        "reserve_route_counts": dict(sorted(reserve_routes.items())),
        "main_lane_counts": dict(sorted(main_lanes.items())),
        "route_lane_fill_counts": lane_counts,
        "main_unique_exact_cdr3": len(exact_cdr3),
        "main_max_exact_cdr3_count": max(exact_cdr3.values()),
        "main_unique_near_cdr3_families": len(near_cdr3),
        "main_max_near_cdr3_family_count": max(near_cdr3.values()),
        "route_normalization": True,
        "score": (
            "0.35*mean(route_pct(developability),route_pct(expression_purity_proxy))"
            "+0.20*route_pct(Sapiens)+0.20*route_pct(AbNatiV)"
            "+0.15*mean(route_pct(DeepNano),route_pct(NanoBind))"
            "+0.10*route_pct(novelty)-0.05_if_AbNatiV_NA"
        ),
        "diversity_caps": {
            "main_exact_cdr3": 5,
            "main_same_length_hamming_identity_ge_80pct_family": 25,
            "reserve_total_exact_cdr3": 8,
            "reserve_total_near_family": 40,
        },
        "outputs": outputs,
        "scientific_boundaries": {
            "shortlist": "resource allocation for monomer prediction; not binding or blocking evidence",
            "binding_models": "weak priors only; no hard biological cutoff",
            "developability": "sequence proxies only; not measured purity or expression",
            "next": "NBB2 monomer prediction, TNP and frozen Docking surrogate",
        },
        "created_epoch": time.time(),
    }
    (args.output_dir / "READY.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    primary_ready = {
        "schema_version": "pvrig.node1_generated300k.structure_primary.v1",
        "status": "READY_FOR_STRUCTURE_PREDICTION",
        "records": len(main),
        "selection": main_table.name,
        "selection_sha256": outputs[main_table.name],
        "fasta": main_fasta.name,
        "fasta_sha256": outputs[main_fasta.name],
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "route_counts": dict(sorted(main_routes.items())),
        "scientific_boundary": (
            "Resource allocation for VHH monomer prediction; not binding, "
            "affinity, docking, or blocking evidence"
        ),
    }
    reserve_ready = {
        "schema_version": "pvrig.node1_generated300k.structure_reserve.v1",
        "status": "READY_FOR_STRUCTURE_PREDICTION",
        "records": len(reserve),
        "selection": reserve_table.name,
        "selection_sha256": outputs[reserve_table.name],
        "fasta": reserve_fasta.name,
        "fasta_sha256": outputs[reserve_fasta.name],
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "route_counts": dict(sorted(reserve_routes.items())),
        "scientific_boundary": (
            "Reserve resource allocation for VHH monomer prediction; not binding, "
            "affinity, docking, or blocking evidence"
        ),
    }
    (args.output_dir / "PRIMARY_READY.json").write_text(
        json.dumps(primary_ready, indent=2, sort_keys=True) + "\n"
    )
    (args.output_dir / "RESERVE_READY.json").write_text(
        json.dumps(reserve_ready, indent=2, sort_keys=True) + "\n"
    )
    (args.output_dir / "SHA256SUMS").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in outputs.items()) + "\n"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
