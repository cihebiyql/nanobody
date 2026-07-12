#!/usr/bin/env python3
"""Select 40 diverse, leakage-controlled VHH parents for formal PVRIG design."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_ROOT = EXP_DIR.parents[2]
DEFAULT_SOURCE = WORKSPACE_ROOT / "scaffolds/top_200_vhh_scaffolds_for_design.csv"
DEFAULT_POSITIVE_ROOT = WORKSPACE_ROOT / "docking/calibration/patent_success_validation"
DEFAULT_OUTDIR = EXP_DIR / "data_splits/pvrig_teacher_formal_v1"
CLAIM_BOUNDARY = "multi_parent_design_starting_points_not_pvrig_binding_or_blocking_truth"
SEED = "pvrig_formal_parent40_v1_seed101"
BIN_QUOTA = 10
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
LENGTH_BINS = (
    ("short_5_13", 5, 13),
    ("medium_14_16", 14, 16),
    ("long_17_19", 17, 19),
    ("xlong_20_25", 20, 25),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}\t{value}".encode()).hexdigest()


def unique_span(sequence: str, subsequence: str) -> tuple[int, int] | None:
    starts = [match.start() for match in re.finditer(f"(?={re.escape(subsequence)})", sequence)]
    if len(starts) != 1:
        return None
    start = starts[0]
    return start, start + len(subsequence)


def infer_cdr3(sequence: str) -> tuple[int, int, str, str] | None:
    """Infer the contiguous CDR3 from conserved pre-CDR3 Cys and FR4 tail."""
    fr4_candidates: list[int] = []
    for index, residue in enumerate(sequence):
        if residue != "W" or not 8 <= len(sequence) - index <= 16:
            continue
        tail = sequence[index:]
        if "TV" not in tail:
            continue
        if any(motif in tail[:7] for motif in ("GQG", "GRG", "GAG", "GKG", "GHG", "GPG", "SQG", "RGQG")):
            fr4_candidates.append(index)
    if not fr4_candidates:
        return None
    fr4_start = fr4_candidates[-1]
    conserved = list(re.finditer(r"(?:YYC|YFC|FYC|FFC)", sequence[:fr4_start]))
    if not conserved:
        return None
    cys_index = conserved[-1].end() - 1
    start = cys_index + 1
    cdr3 = sequence[start:fr4_start]
    if not 5 <= len(cdr3) <= 25:
        return None
    return start, fr4_start, cdr3, sequence[fr4_start:]


def length_bin(length: int) -> str | None:
    for name, lower, upper in LENGTH_BINS:
        if lower <= length <= upper:
            return name
    return None


def framework_signature(sequence: str, spans: Sequence[tuple[int, int]]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(sequence[cursor:start])
        cursor = end
    pieces.append(sequence[cursor:])
    return "".join(pieces)


def kmer_set(sequence: str, k: int = 3) -> set[str]:
    return {sequence[index : index + k] for index in range(max(0, len(sequence) - k + 1))}


def jaccard_distance(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 - (len(left & right) / len(union) if union else 1.0)


def positive_sequences(root: Path) -> set[str]:
    sequences: set[str] = set()
    for path in sorted(root.glob("case*/inputs/*.fasta")):
        sequence = "".join(
            line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith(">")
        )
        if sequence:
            sequences.add(sequence)
    return sequences


def prepare_rows(source: Path) -> tuple[list[dict[str, object]], Counter[str]]:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.DictReader(handle))
    eligible: list[dict[str, object]] = []
    exclusions: Counter[str] = Counter()
    for raw in raw_rows:
        sequence = raw["sequence_aa"].strip().upper()
        if not sequence or set(sequence) - STANDARD_AA:
            exclusions["nonstandard_sequence"] += 1
            continue
        if len(sequence) < 115:
            exclusions["sequence_too_short_for_full_framework"] += 1
            continue
        if raw.get("keep_or_drop") != "keep" or raw.get("framework_health_status") != "pass_framework_health":
            exclusions["source_gate_not_passed"] += 1
            continue
        if raw.get("developability_status") != "pass_developability":
            exclusions["developability_not_passed"] += 1
            continue
        if float(raw["max_cdr_identity_to_HR151_Tab5"]) >= 75.0:
            exclusions["positive_cdr_identity_ge_75"] += 1
            continue
        cdr1_span = unique_span(sequence, raw["cdr1"])
        cdr2_span = unique_span(sequence, raw["cdr2"])
        cdr3_info = infer_cdr3(sequence)
        if cdr1_span is None:
            exclusions["cdr1_not_unique_contiguous"] += 1
            continue
        if cdr2_span is None:
            exclusions["cdr2_not_unique_contiguous"] += 1
            continue
        if cdr3_info is None:
            exclusions["cdr3_contiguous_inference_failed"] += 1
            continue
        cdr3_start, cdr3_end, cdr3, fr4 = cdr3_info
        if not (cdr1_span[1] <= cdr2_span[0] < cdr2_span[1] <= cdr3_start < cdr3_end):
            exclusions["cdr_order_invalid"] += 1
            continue
        bin_name = length_bin(len(cdr3))
        if bin_name is None:
            exclusions["cdr3_length_outside_bins"] += 1
            continue
        signature = framework_signature(sequence, (cdr1_span, cdr2_span, (cdr3_start, cdr3_end)))
        row: dict[str, object] = {
            "parent_id": raw["sequence_id"],
            "sequence": sequence,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "cluster_id": raw["cluster_id"],
            "source": raw["source"],
            "source_accession": raw["source_accession"],
            "license_or_use_terms": raw["license_or_use_terms"],
            "species": raw["species"],
            "cdr1": raw["cdr1"],
            "cdr1_start_1based": cdr1_span[0] + 1,
            "cdr1_end_1based": cdr1_span[1],
            "cdr2": raw["cdr2"],
            "cdr2_start_1based": cdr2_span[0] + 1,
            "cdr2_end_1based": cdr2_span[1],
            "cdr3": cdr3,
            "cdr3_start_1based": cdr3_start + 1,
            "cdr3_end_1based": cdr3_end,
            "cdr3_length": len(cdr3),
            "cdr3_length_bin": bin_name,
            "source_cdr3": raw["cdr3"],
            "source_cdr3_matches_contiguous": str(raw["cdr3"] == cdr3).lower(),
            "fr4_tail": fr4,
            "sequence_length": len(sequence),
            "hydrophobic_fraction": float(raw["hydrophobic_fraction"]),
            "net_charge": int(raw["net_charge"]),
            "max_cdr_identity_to_HR151_Tab5": float(raw["max_cdr_identity_to_HR151_Tab5"]),
            "score_v1_1": float(raw["score_v1_1"]),
            "framework_signature": signature,
            "framework_kmers": kmer_set(signature),
        }
        eligible.append(row)
    return eligible, exclusions


def select_parents(eligible: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    pools = {
        name: [row for row in eligible if row["cdr3_length_bin"] == name]
        for name, _, _ in LENGTH_BINS
    }
    for name, pool in pools.items():
        if len(pool) < BIN_QUOTA:
            raise ValueError(f"Insufficient eligible parents in {name}: {len(pool)}")
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    per_bin_rank: Counter[str] = Counter()
    for _round in range(BIN_QUOTA):
        for bin_name, _, _ in LENGTH_BINS:
            candidates = [row for row in pools[bin_name] if str(row["parent_id"]) not in selected_ids]

            def score(row: dict[str, object]) -> tuple[float, float, float, float, str]:
                if selected:
                    minimum_distance = min(
                        jaccard_distance(row["framework_kmers"], other["framework_kmers"])  # type: ignore[arg-type]
                        for other in selected
                    )
                    charge_novelty = min(abs(int(row["net_charge"]) - int(other["net_charge"])) for other in selected)
                    hydro_novelty = min(
                        abs(float(row["hydrophobic_fraction"]) - float(other["hydrophobic_fraction"]))
                        for other in selected
                    )
                else:
                    minimum_distance, charge_novelty, hydro_novelty = 1.0, 20.0, 1.0
                return (
                    minimum_distance,
                    charge_novelty,
                    hydro_novelty,
                    float(row["score_v1_1"]),
                    stable_key(str(row["parent_id"])),
                )

            chosen = max(candidates, key=score)
            selected.append(chosen)
            selected_ids.add(str(chosen["parent_id"]))
            per_bin_rank[bin_name] += 1
            chosen["within_bin_rank"] = per_bin_rank[bin_name]

    output: list[dict[str, object]] = []
    for rank, row in enumerate(selected, start=1):
        bin_index = next(index for index, value in enumerate(LENGTH_BINS) if value[0] == row["cdr3_length_bin"])
        within_bin_rank = int(row["within_bin_rank"])
        if within_bin_rank <= 7:
            split = "train"
        elif bin_index % 2 == 0:
            split = "dev" if within_bin_rank <= 9 else "test"
        else:
            split = "dev" if within_bin_rank == 8 else "test"
        output.append(
            {
                "schema_version": "pvrig_formal_parent40_manifest_v1",
                "selection_rank": rank,
                "parent_framework_cluster": row["cluster_id"],
                "formal_split": split,
                "selection_method": "cdr3_bin_quota_then_framework_kmer_maximin",
                **{key: value for key, value in row.items() if key not in {"framework_kmers", "within_bin_rank"}},
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    return output


def run(source: Path, positive_root: Path, outdir: Path) -> dict[str, object]:
    eligible, exclusions = prepare_rows(source)
    selected = select_parents(eligible)
    positives = positive_sequences(positive_root)
    exact_overlaps = sorted(row["parent_id"] for row in selected if row["sequence"] in positives)
    if exact_overlaps:
        raise ValueError(f"Known-positive exact sequence overlap: {exact_overlaps}")
    if len(selected) != 40 or len({row["parent_framework_cluster"] for row in selected}) != 40:
        raise ValueError("Selection must contain 40 unique parent clusters")

    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "parent40_manifest.tsv"
    fasta_path = outdir / "parent40.fasta"
    audit_path = outdir / "parent40_selection_audit.json"
    fields = [key for key in selected[0] if key != "framework_signature"]
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(f">{row['parent_id']}|cluster={row['parent_framework_cluster']}|split={row['formal_split']}\n")
            handle.write(f"{row['sequence']}\n")

    audit: dict[str, object] = {
        "status": "PASS_PARENT40_FROZEN",
        "schema_version": "pvrig_formal_parent40_selection_audit_v1",
        "seed": SEED,
        "source_rows": 200,
        "eligible_rows": len(eligible),
        "exclusion_counts": dict(sorted(exclusions.items())),
        "selected_rows": len(selected),
        "unique_sequences": len({row["sequence"] for row in selected}),
        "unique_parent_clusters": len({row["parent_framework_cluster"] for row in selected}),
        "cdr3_length_bin_counts": dict(sorted(Counter(str(row["cdr3_length_bin"]) for row in selected).items())),
        "formal_split_counts": dict(sorted(Counter(str(row["formal_split"]) for row in selected).items())),
        "net_charge_range": [min(int(row["net_charge"]) for row in selected), max(int(row["net_charge"]) for row in selected)],
        "hydrophobic_fraction_range": [
            min(float(row["hydrophobic_fraction"]) for row in selected),
            max(float(row["hydrophobic_fraction"]) for row in selected),
        ],
        "source_cdr3_contiguous_mismatch_count": sum(
            row["source_cdr3_matches_contiguous"] == "false" for row in selected
        ),
        "known_positive_reference_sequences": len(positives),
        "exact_known_positive_sequence_overlaps": exact_overlaps,
        "input_sha256": {str(source): sha256_file(source)},
        "output_sha256": {
            str(manifest_path): sha256_file(manifest_path),
            str(fasta_path): sha256_file(fasta_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--positive-root", type=Path, default=DEFAULT_POSITIVE_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.source, args.positive_root, args.outdir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
