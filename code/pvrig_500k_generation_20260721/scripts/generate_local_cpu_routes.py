#!/usr/bin/env python3
"""Generate and fast-QC the two validated local CPU routes for the PVRIG pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path


AA = set("ACDEFGHIKLMNPQRSTVWY")
HYDROPHOBIC = set("AVILMFWY")
POSITIVE = set("KRH")
NEGATIVE = set("DE")
CONSERVATIVE_GROUPS = (
    "AVLIM",
    "FYW",
    "STNQ",
    "KRH",
    "DE",
    "GP",
)
LOCAL_ROUTES = {"conservative_cdr_redesign", "natural_cdr_donor"}


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


def global_identity(a: str, b: str) -> float:
    """Needleman-Wunsch identity over aligned positions, returned as a fraction."""
    if not a or not b:
        return 0.0
    match, mismatch, gap = 1, -1, -1
    score = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    trace = [[""] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        score[i][0], trace[i][0] = i * gap, "U"
    for j in range(1, len(b) + 1):
        score[0][j], trace[0][j] = j * gap, "L"
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            diagonal = score[i - 1][j - 1] + (match if a[i - 1] == b[j - 1] else mismatch)
            up = score[i - 1][j] + gap
            left = score[i][j - 1] + gap
            best = max(diagonal, up, left)
            score[i][j] = best
            trace[i][j] = "D" if best == diagonal else "U" if best == up else "L"
    i, j, matches, aligned = len(a), len(b), 0, 0
    while i or j:
        direction = trace[i][j]
        if direction == "D":
            aligned += 1
            matches += a[i - 1] == b[j - 1]
            i -= 1
            j -= 1
        elif direction == "U":
            aligned += 1
            i -= 1
        else:
            aligned += 1
            j -= 1
    return matches / aligned if aligned else 0.0


def replace_cdr(sequence: str, old: str, new: str) -> str:
    if not old or sequence.count(old) != 1:
        raise ValueError("CDR must occur exactly once in parent sequence")
    return sequence.replace(old, new, 1)


def sequence_order_cdr3(sequence: str, length: int) -> str:
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


def designed_regions(mode: str) -> list[str]:
    if mode == "H3":
        return ["cdr3"]
    if mode == "H1H3":
        return ["cdr1", "cdr3"]
    if mode == "H1H2H3":
        return ["cdr1", "cdr2", "cdr3"]
    raise ValueError(f"unsupported design mode: {mode}")


def conservative_mutate(cdr: str, rng: random.Random) -> str:
    mutable = [i for i, aa in enumerate(cdr) if aa != "C"]
    if not mutable:
        return cdr
    mutation_count = max(1, round(len(cdr) * 0.15))
    positions = rng.sample(mutable, min(mutation_count, len(mutable)))
    result = list(cdr)
    for position in positions:
        source = result[position]
        group = next((group for group in CONSERVATIVE_GROUPS if source in group), "STNQKRHDEGPAVLIMFYW")
        choices = [aa for aa in group if aa != source and aa != "C"]
        result[position] = rng.choice(choices)
    return "".join(result)


def donor_index(parents: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    index: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for parent in parents:
        for region in ("cdr1", "cdr2", "cdr3"):
            index[(region, len(parent[region]))].append(parent)
    return index


def cdr3_bin(length: int) -> str:
    if 18 <= length <= 22:
        return "18_22"
    if 16 <= length <= 17:
        return "16_17"
    if 10 <= length <= 15:
        return "10_15"
    return "other"


def select_donor(
    parent: dict[str, str],
    region: str,
    index: dict[tuple[str, int], list[dict[str, str]]],
    rng: random.Random,
    current_cys_count: int | None = None,
    require_even_after_replacement: bool = False,
) -> dict[str, str]:
    pool = [
        row
        for row in index[(region, len(parent[region]))]
        if row["cluster_id"] != parent["cluster_id"] and row[region] != parent[region]
    ]
    if not pool:
        fallback: list[dict[str, str]] = []
        for (candidate_region, candidate_length), rows in index.items():
            if candidate_region != region:
                continue
            if region == "cdr3":
                allowed = cdr3_bin(candidate_length) == cdr3_bin(len(parent[region]))
            else:
                allowed = abs(candidate_length - len(parent[region])) <= 2
            if allowed:
                fallback.extend(rows)
        pool = [
            row
            for row in fallback
            if row["cluster_id"] != parent["cluster_id"] and row[region] != parent[region]
        ]
    pool = [
        row
        for row in pool
        if not has_n_glyco(row[region]) and longest_hydrophobic_run(row[region]) < 5
    ]
    if require_even_after_replacement and current_cys_count is not None:
        parity_safe = [
            row
            for row in pool
            if (current_cys_count - parent[region].count("C") + row[region].count("C")) % 2 == 0
        ]
        if parity_safe:
            pool = parity_safe
    if not pool:
        raise ValueError(f"no natural donor for {parent['sequence_id']} {region}")
    return pool[rng.randrange(len(pool))]


def read_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    current = ""
    chunks: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if current:
                records[current] = "".join(chunks)
            current = line[1:].split("|", 1)[0].split()[0]
            chunks = []
        else:
            chunks.append(line.strip())
    if current:
        records[current] = "".join(chunks)
    return records


def load_positive_cdrs(path: Path, fasta_path: Path) -> dict[str, dict[str, str]]:
    positives: dict[str, dict[str, str]] = {}
    sequences = read_fasta(fasta_path)
    for row in read_csv(path):
        if row["chain"] in {"VH", "VHH"}:
            positives[row["record_id"]] = {region: row[region] for region in ("cdr1", "cdr2", "cdr3")}
            if row["record_id"] not in sequences:
                raise ValueError(f"positive sequence missing for {row['record_id']}")
            positives[row["record_id"]]["cdr3"] = sequence_order_cdr3(
                sequences[row["record_id"]], int(row["cdr3_len"])
            )
    return positives


def max_positive_identity(cdrs: dict[str, str], positives: dict[str, dict[str, str]]) -> tuple[float, str]:
    best = (0.0, "")
    for positive_id, positive_cdrs in positives.items():
        for region in ("cdr1", "cdr2", "cdr3"):
            value = global_identity(cdrs[region], positive_cdrs[region])
            if value > best[0]:
                best = (value, f"{positive_id}:{region}")
    return best


def has_n_glyco(sequence: str) -> bool:
    return any(
        sequence[i] == "N" and sequence[i + 1] != "P" and sequence[i + 2] in {"S", "T"}
        for i in range(len(sequence) - 2)
    )


def longest_hydrophobic_run(sequence: str) -> int:
    longest = current = 0
    for aa in sequence:
        current = current + 1 if aa in HYDROPHOBIC else 0
        longest = max(longest, current)
    return longest


def fast_qc(
    sequence: str,
    cdrs: dict[str, str],
    parent_sequence: str,
    positives: dict[str, dict[str, str]],
) -> dict[str, object]:
    reasons: list[str] = []
    if not 95 <= len(sequence) <= 160:
        reasons.append("length_outside_95_160")
    if set(sequence) - AA:
        reasons.append("invalid_amino_acid")
    if sequence == parent_sequence:
        reasons.append("unchanged_from_parent")
    if any(not cdr or sequence.count(cdr) != 1 for cdr in cdrs.values()):
        reasons.append("cdr_missing_or_nonunique")
    cys_count = sequence.count("C")
    if cys_count % 2:
        reasons.append("odd_total_cys")
    if has_n_glyco("".join(cdrs.values())):
        reasons.append("cdr_n_glyco_motif")
    hydrophobic_fraction = sum(aa in HYDROPHOBIC for aa in sequence) / len(sequence)
    if hydrophobic_fraction > 0.52:
        reasons.append("high_hydrophobic_fraction")
    low_complexity = max(Counter(sequence).values()) / len(sequence)
    if low_complexity > 0.28:
        reasons.append("severe_low_complexity")
    hydrophobic_run = longest_hydrophobic_run(sequence)
    parent_hydrophobic_run = longest_hydrophobic_run(parent_sequence)
    if hydrophobic_run >= 5 and hydrophobic_run > parent_hydrophobic_run:
        reasons.append("new_or_worsened_hydrophobic_run_ge_5")
    max_identity, max_identity_detail = max_positive_identity(cdrs, positives)
    if max_identity >= 0.80:
        reasons.append("positive_any_cdr_identity_ge_80pct")
    charge = sum(aa in POSITIVE for aa in sequence) - sum(aa in NEGATIVE for aa in sequence)
    return {
        "fast_qc_status": "PASS" if not reasons else "FAIL",
        "fast_qc_reasons": "|".join(reasons),
        "sequence_length": len(sequence),
        "total_cys": cys_count,
        "hydrophobic_fraction": f"{hydrophobic_fraction:.6f}",
        "longest_hydrophobic_run": hydrophobic_run,
        "parent_longest_hydrophobic_run": parent_hydrophobic_run,
        "inherited_hydrophobic_run_flag": str(hydrophobic_run >= 5 and hydrophobic_run <= parent_hydrophobic_run).lower(),
        "low_complexity_score": f"{low_complexity:.6f}",
        "net_charge_proxy": charge,
        "max_positive_cdr_identity": f"{max_identity:.6f}",
        "max_positive_cdr_identity_detail": max_identity_detail,
    }


def generate_candidate(
    task: dict[str, str],
    parent: dict[str, str],
    donors: dict[tuple[str, int], list[dict[str, str]]],
) -> dict[str, object]:
    rng = random.Random(int(task["generation_seed"]))
    sequence = parent["sequence_aa"]
    cdrs = {region: parent[region] for region in ("cdr1", "cdr2", "cdr3")}
    donor_ids: list[str] = []
    regions = designed_regions(task["design_mode"])
    for region_index, region in enumerate(regions):
        old = cdrs[region]
        if task["route_id"] == "conservative_cdr_redesign":
            new = conservative_mutate(old, rng)
            donor_ids.append(f"{region}:profile_conservative")
        elif task["route_id"] == "natural_cdr_donor":
            donor = select_donor(
                parent,
                region,
                donors,
                rng,
                current_cys_count=sequence.count("C"),
                require_even_after_replacement=region_index == len(regions) - 1,
            )
            new = donor[region]
            donor_ids.append(f"{region}:{donor['sequence_id']}")
        else:
            raise ValueError(f"unsupported local route: {task['route_id']}")
        sequence = replace_cdr(sequence, old, new)
        cdrs[region] = new
    sequence_hash = sha256_text(sequence)
    candidate_id = f"P50K__{task['route_id'].upper()}__{sequence_hash[:16].upper()}"
    return {
        **task,
        "candidate_id": candidate_id,
        "sequence": sequence,
        "sequence_sha256": sequence_hash,
        "cdr1_after": cdrs["cdr1"],
        "cdr2_after": cdrs["cdr2"],
        "cdr3_after": cdrs["cdr3"],
        "designed_regions": ",".join(designed_regions(task["design_mode"])),
        "donor_or_profile_provenance": ";".join(donor_ids),
        "generator": "pvrig_local_cpu_route_generator",
        "generator_version": "1",
    }


def write_fasta(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign_dir
    tasks = [row for row in read_tsv(campaign / "manifests" / "pilot_generation_tasks.tsv") if row["route_id"] in LOCAL_ROUTES]
    parents = read_csv(campaign / "inputs" / "top_200_vhh_scaffolds_for_design.csv")
    for parent in parents:
        parent["cdr1"] = sequence_order_cdr12(parent["sequence_aa"], parent["cdr1"], "cdr1")
        parent["cdr2"] = sequence_order_cdr12(parent["sequence_aa"], parent["cdr2"], "cdr2")
        parent["cdr3"] = sequence_order_cdr3(parent["sequence_aa"], int(parent["cdr3_len"]))
    parent_by_id = {row["sequence_id"]: row for row in parents}
    donors = donor_index(parents)
    positives = load_positive_cdrs(
        campaign / "inputs" / "known_positive_CDR_table.csv",
        campaign / "inputs" / "known_positive_antibodies.fasta",
    )

    generated: list[dict[str, object]] = []
    seen_sequences: set[str] = set()
    for task in tasks:
        candidate = generate_candidate(task, parent_by_id[task["parent_id"]], donors)
        qc = fast_qc(
            str(candidate["sequence"]),
            {region: str(candidate[f"{region}_after"]) for region in ("cdr1", "cdr2", "cdr3")},
            task["parent_sequence"],
            positives,
        )
        duplicate = str(candidate["sequence"]) in seen_sequences
        seen_sequences.add(str(candidate["sequence"]))
        candidate.update(qc)
        candidate["exact_duplicate_global"] = str(duplicate).lower()
        if duplicate:
            candidate["fast_qc_status"] = "FAIL"
            candidate["fast_qc_reasons"] = "|".join(
                filter(None, [str(candidate["fast_qc_reasons"]), "exact_duplicate_global"])
            )
        generated.append(candidate)

    raw_path = campaign / "raw" / "local_cpu_routes_raw.tsv"
    write_tsv(raw_path, generated, list(generated[0]))
    accepted: list[dict[str, object]] = []
    route_status: dict[str, dict[str, object]] = {}
    for route_id in sorted(LOCAL_ROUTES):
        route_rows = [row for row in generated if row["route_id"] == route_id]
        passes = [row for row in route_rows if row["fast_qc_status"] == "PASS"]
        selected = passes[:5000]
        accepted.extend(selected)
        route_status[route_id] = {
            "raw": len(route_rows),
            "fast_qc_pass": len(passes),
            "pre_anarci_selected": len(selected),
            "status": "READY_FOR_ANARCI" if len(selected) == 5000 else "HOLD_INSUFFICIENT_FAST_QC_PASS",
            "top_failure_reasons": Counter(
                reason
                for row in route_rows
                for reason in str(row["fast_qc_reasons"]).split("|")
                if reason
            ).most_common(10),
        }
    selected_path = campaign / "qc" / "local_cpu_routes_pre_anarci.tsv"
    write_tsv(selected_path, accepted, list(generated[0]))
    write_fasta(campaign / "qc" / "local_cpu_routes_pre_anarci.fasta", accepted)
    summary = {
        "schema_version": 1,
        "status": "READY_FOR_ANARCI" if all(x["status"] == "READY_FOR_ANARCI" for x in route_status.values()) else "HOLD",
        "generated": len(generated),
        "global_unique_sequences": len(seen_sequences),
        "pre_anarci_selected": len(accepted),
        "routes": route_status,
        "scientific_boundary": "fast QC and sequence design only; no binding, structure, docking, or blocking claim",
    }
    (campaign / "reports" / "local_cpu_generation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (campaign / "status" / "LOCAL_CPU_GENERATION.json").write_text(
        json.dumps(
            {
                "status": summary["status"],
                "raw_tsv": str(raw_path.relative_to(campaign)),
                "pre_anarci_tsv": str(selected_path.relative_to(campaign)),
                "pre_anarci_fasta": "qc/local_cpu_routes_pre_anarci.fasta",
                "selected_count": len(accepted),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "READY_FOR_ANARCI" else 2


if __name__ == "__main__":
    raise SystemExit(main())
