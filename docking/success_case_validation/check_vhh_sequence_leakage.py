#!/usr/bin/env python3
"""Check candidate VHH sequences against known positive/leakage reference sequences."""

from __future__ import annotations

import argparse
import csv
from collections import OrderedDict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATENT_FASTA = ROOT / "机制" / "data" / "sequences" / "PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta"
DEFAULT_KNOWN_POSITIVES = ROOT / "positives" / "known_positive_antibodies.fasta"
OUTPUT_FIELDS = [
    "candidate_id",
    "candidate_length",
    "nearest_reference_id",
    "nearest_reference_length",
    "identity_fraction",
    "same_length_hamming_distance",
    "leakage_label",
    "recommended_action",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate-fasta", type=Path)
    source.add_argument("--candidate-csv", type=Path)
    parser.add_argument("--id-column", default="mutant_name")
    parser.add_argument("--sequence-column", default="sequence")
    parser.add_argument(
        "--reference-fasta",
        type=Path,
        action="append",
        default=[DEFAULT_PATENT_FASTA, DEFAULT_KNOWN_POSITIVES],
        help="Known-positive/reference FASTA. Repeatable. Defaults to patent sequences plus positives FASTA.",
    )
    parser.add_argument("--near-identity", type=float, default=0.95)
    parser.add_argument("--max-near-mutations", type=int, default=6)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--fail-on-exact", action="store_true")
    return parser.parse_args()


def parse_fasta(path: Path) -> OrderedDict[str, str]:
    records: OrderedDict[str, str] = OrderedDict()
    header = ""
    parts: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                records[header.split("|", 1)[0]] = "".join(parts).upper()
            header = line[1:]
            parts = []
        else:
            parts.append(line)
    if header:
        records[header.split("|", 1)[0]] = "".join(parts).upper()
    return records


def read_candidate_csv(path: Path, id_column: str, sequence_column: str) -> OrderedDict[str, str]:
    records: OrderedDict[str, str] = OrderedDict()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            records[row[id_column]] = row[sequence_column].strip().upper()
    return records


def hamming(a: str, b: str) -> int | None:
    if len(a) != len(b):
        return None
    return sum(1 for left, right in zip(a, b) if left != right)


def identity(a: str, b: str) -> float:
    if len(a) == len(b):
        if not a:
            return 0.0
        return 1.0 - (hamming(a, b) or 0) / len(a)
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def classify(candidate: str, reference: str, ident: float, dist: int | None, near_identity: float, max_near_mutations: int) -> tuple[str, str]:
    if candidate == reference:
        return "EXACT_KNOWN_POSITIVE", "reject from new-candidate ranking; keep only as positive/leakage control"
    if ident >= near_identity or (dist is not None and dist <= max_near_mutations):
        return "NEAR_KNOWN_POSITIVE", "treat as leakage/perturbation control unless explicitly approved as a mutant-validation row"
    return "NO_CLOSE_KNOWN_POSITIVE", "sequence novelty gate passed; continue structure/docking/blocker workflow"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.candidate_fasta:
        candidates = parse_fasta(args.candidate_fasta)
    else:
        candidates = read_candidate_csv(args.candidate_csv, args.id_column, args.sequence_column)
    references: OrderedDict[str, str] = OrderedDict()
    for path in args.reference_fasta:
        for key, seq in parse_fasta(path).items():
            references.setdefault(key, seq)
    if not candidates:
        raise SystemExit("no candidate sequences found")
    if not references:
        raise SystemExit("no reference sequences found")

    rows: list[dict[str, str]] = []
    exact_count = 0
    near_count = 0
    for cand_id, cand_seq in candidates.items():
        best_ref_id = ""
        best_ref_seq = ""
        best_identity = -1.0
        best_dist: int | None = None
        for ref_id, ref_seq in references.items():
            ident = identity(cand_seq, ref_seq)
            dist = hamming(cand_seq, ref_seq)
            if ident > best_identity or (ident == best_identity and dist is not None and (best_dist is None or dist < best_dist)):
                best_ref_id = ref_id
                best_ref_seq = ref_seq
                best_identity = ident
                best_dist = dist
        label, action = classify(cand_seq, best_ref_seq, best_identity, best_dist, args.near_identity, args.max_near_mutations)
        exact_count += 1 if label == "EXACT_KNOWN_POSITIVE" else 0
        near_count += 1 if label == "NEAR_KNOWN_POSITIVE" else 0
        rows.append(
            {
                "candidate_id": cand_id,
                "candidate_length": str(len(cand_seq)),
                "nearest_reference_id": best_ref_id,
                "nearest_reference_length": str(len(best_ref_seq)),
                "identity_fraction": f"{best_identity:.6f}",
                "same_length_hamming_distance": "" if best_dist is None else str(best_dist),
                "leakage_label": label,
                "recommended_action": action,
            }
        )
    write_csv(args.out_csv, rows)
    print("OK sequence leakage checked")
    print(f"candidates={len(rows)}")
    print(f"references={len(references)}")
    print(f"exact_known_positive={exact_count}")
    print(f"near_known_positive={near_count}")
    print(f"out_csv={args.out_csv}")
    if args.fail_on_exact and exact_count:
        raise SystemExit(f"exact known-positive leakage found: {exact_count}")


if __name__ == "__main__":
    main()
