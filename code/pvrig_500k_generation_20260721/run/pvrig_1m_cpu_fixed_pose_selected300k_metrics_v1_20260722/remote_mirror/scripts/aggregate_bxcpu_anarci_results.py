#!/usr/bin/env python3
"""Create fixed-width IMGT hard-QC rows from sharded ANARCI CSV outputs."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


POSITION = re.compile(r"^(\d+)([A-Z]*)$")
REGIONS = {
    "fr1": (1, 26),
    "cdr1": (27, 38),
    "fr2": (39, 55),
    "cdr2": (56, 65),
    "fr3": (66, 104),
    "cdr3": (105, 117),
    "fr4": (118, 128),
}


def fasta_records(paths: list[Path]):
    for path in paths:
        name = None
        parts: list[str] = []
        with path.open() as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    if name is not None:
                        yield name, "".join(parts)
                    name = line[1:].split()[0]
                    parts = []
                else:
                    parts.append(line)
        if name is not None:
            yield name, "".join(parts)


def numbered_region(row: dict[str, str], start: int, end: int) -> str:
    residues = []
    for key, value in row.items():
        match = POSITION.match(key)
        if match and start <= int(match.group(1)) <= end and value not in ("", "-"):
            residues.append(value)
    return "".join(residues)


def numbered_sequence(row: dict[str, str]) -> str:
    return numbered_region(row, 1, 128)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    input_paths = sorted(args.input_dir.glob("task_*.fasta"))
    result_paths = sorted(args.results_dir.glob("task_*/anarci_imgt_H.csv"))
    if not input_paths or len(input_paths) != len(result_paths):
        raise ValueError(f"incomplete shards: input={len(input_paths)} results={len(result_paths)}")

    sequences = dict(fasta_records(input_paths))
    if len(sequences) != sum(1 for _ in fasta_records(input_paths)):
        raise ValueError("duplicate FASTA IDs")
    by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    unknown = 0
    for path in result_paths:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                candidate_id = row.get("Id", "")
                if candidate_id not in sequences:
                    unknown += 1
                by_id[candidate_id].append(row)
    if unknown:
        raise ValueError(f"ANARCI emitted {unknown} unknown IDs")

    fields = [
        "candidate_id", "sequence_length", "anarci_qc_status", "anarci_qc_reasons",
        "anarci_domain_count", "anarci_species", "anarci_chain_type", "anarci_evalue",
        "anarci_score", "seqstart_index", "seqend_index", "numbered_sequence",
        "numbered_sequence_matches_input_slice", "fr1", "cdr1", "fr2", "cdr2",
        "fr3", "cdr3", "fr4", "imgt_cys23", "imgt_cys104",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    reasons_count: Counter[str] = Counter()
    with gzip.open(args.output, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for candidate_id, sequence in sequences.items():
            domains = [row for row in by_id.get(candidate_id, []) if row.get("chain_type") == "H"]
            reasons: list[str] = []
            if not domains:
                reasons.append("anarci_no_H_domain")
                row: dict[str, str] = {}
            else:
                if len(domains) != 1:
                    reasons.append("anarci_multiple_H_domains")
                row = max(domains, key=lambda item: float(item.get("score") or "-inf"))
            regions = {name: numbered_region(row, *bounds) for name, bounds in REGIONS.items()}
            if row and any(not value for value in regions.values()):
                reasons.append("anarci_incomplete_FR_CDR")
            numbered = numbered_sequence(row)
            start = int(row.get("seqstart_index") or 0) if row else 0
            end = int(row.get("seqend_index") or -1) if row else -1
            input_slice = sequence[start : end + 1] if end >= start else ""
            matches = bool(numbered) and numbered == input_slice
            if row and not matches:
                reasons.append("anarci_numbered_sequence_mismatch")
            if regions["fr1"] and numbered_region(row, 23, 23) != "C":
                reasons.append("imgt_Cys23_missing")
            if regions["fr3"] and numbered_region(row, 104, 104) != "C":
                reasons.append("imgt_Cys104_missing")
            status = "PASS" if not reasons else "FAIL"
            counts[status] += 1
            reasons_count.update(reasons)
            writer.writerow({
                "candidate_id": candidate_id,
                "sequence_length": len(sequence),
                "anarci_qc_status": status,
                "anarci_qc_reasons": "|".join(reasons),
                "anarci_domain_count": len(domains),
                "anarci_species": row.get("hmm_species", ""),
                "anarci_chain_type": row.get("chain_type", ""),
                "anarci_evalue": row.get("e-value", ""),
                "anarci_score": row.get("score", ""),
                "seqstart_index": row.get("seqstart_index", ""),
                "seqend_index": row.get("seqend_index", ""),
                "numbered_sequence": numbered,
                "numbered_sequence_matches_input_slice": str(matches).lower(),
                **regions,
                "imgt_cys23": numbered_region(row, 23, 23),
                "imgt_cys104": numbered_region(row, 104, 104),
            })

    summary = {
        "status": "PASS",
        "records": len(sequences),
        "input_shards": len(input_paths),
        "result_shards": len(result_paths),
        "qc_status_counts": dict(sorted(counts.items())),
        "failure_reason_counts": dict(sorted(reasons_count.items())),
        "output": str(args.output.resolve()),
        "output_sha256": sha256(args.output),
        "scientific_boundary": "ANARCI/IMGT identity and domain-completeness QC; not binding, affinity, purity, or blocking evidence",
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
