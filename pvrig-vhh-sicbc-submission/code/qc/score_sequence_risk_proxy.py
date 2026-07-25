#!/usr/bin/env python3
"""Compute auditable sequence-only expression/purity risk proxies.

This is a cheap prefilter, not a calibrated expression or purity predictor.
It intentionally leaves structure/model-dependent fields (AbNatiV, TNP and
instability index) absent so missing evidence cannot masquerade as a pass.
"""

import argparse
import csv
import gzip
import hashlib
import math
import re
from pathlib import Path


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
HYDROPHOBIC = set("AVILMFWY")
HYDROPATHY = {
    "A": 1.8, "C": 2.5, "D": -3.5, "E": -3.5, "F": 2.8,
    "G": -0.4, "H": -3.2, "I": 4.5, "K": -3.9, "L": 3.8,
    "M": 1.9, "N": -3.5, "P": -1.6, "Q": -3.5, "R": -4.5,
    "S": -0.8, "T": -0.7, "V": 4.2, "W": -0.9, "Y": -1.3,
}
RESIDUE_MASS = {
    "A": 71.0788, "C": 103.1388, "D": 115.0886, "E": 129.1155,
    "F": 147.1766, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "K": 128.1741, "L": 113.1594, "M": 131.1926, "N": 114.1038,
    "P": 97.1167, "Q": 128.1307, "R": 156.1875, "S": 87.0782,
    "T": 101.1051, "V": 99.1326, "W": 186.2132, "Y": 163.1760,
}
WATER_MASS = 18.01528


def open_text(path, mode):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8", newline="")
    return path.open(mode, encoding="utf-8", newline="")


def read_fasta(path):
    name = None
    parts = []
    with open_text(path, "r") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts).upper()
                name = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts).upper()


def charge_at_ph(sequence, ph):
    # Standard sequence-only Henderson-Hasselbalch approximation.
    positive = 1.0 / (1.0 + 10 ** (ph - 8.6))
    negative = 1.0 / (1.0 + 10 ** (3.6 - ph))
    positive += sequence.count("K") / (1.0 + 10 ** (ph - 10.5))
    positive += sequence.count("R") / (1.0 + 10 ** (ph - 12.5))
    positive += sequence.count("H") / (1.0 + 10 ** (ph - 6.5))
    negative += sequence.count("D") / (1.0 + 10 ** (3.9 - ph))
    negative += sequence.count("E") / (1.0 + 10 ** (4.1 - ph))
    negative += sequence.count("C") / (1.0 + 10 ** (8.5 - ph))
    negative += sequence.count("Y") / (1.0 + 10 ** (10.1 - ph))
    return positive - negative


def isoelectric_point(sequence):
    low, high = 0.0, 14.0
    for _ in range(60):
        mid = (low + high) / 2.0
        if charge_at_ph(sequence, mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def motif_count(pattern, sequence):
    return len(re.findall(f"(?=({pattern}))", sequence))


def clamp(value):
    return max(0.0, min(100.0, value))


def score_record(candidate_id, sequence):
    valid = bool(sequence) and set(sequence) <= STANDARD_AA
    if not valid:
        return {
            "candidate_id": candidate_id,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "sequence_length": len(sequence),
            "descriptor_status": "INVALID_SEQUENCE",
            "expression_purity_risk_proxy_partial": "",
            "developability_risk_proxy_partial": "",
            "risk_tier": "NA",
            "scientific_boundary": "sequence-only risk proxy; not measured purity or expression",
        }

    length = len(sequence)
    cys = sequence.count("C")
    gravy = sum(HYDROPATHY[aa] for aa in sequence) / length
    mw = sum(RESIDUE_MASS[aa] for aa in sequence) + WATER_MASS
    pi = isoelectric_point(sequence)
    charge = charge_at_ph(sequence, 7.4)
    nglyc = motif_count(r"N[^P][ST]", sequence)
    deamidation = motif_count(r"N[GSTH]", sequence)
    isomerization = motif_count(r"D[GSDT]", sequence)
    acid_cleavage = motif_count(r"DP", sequence)
    hydrophobic_5 = motif_count(r"[AVILMFWY]{5}", sequence)
    poly_basic_4 = motif_count(r"[KR]{4}", sequence)
    poly_acidic_4 = motif_count(r"[DE]{4}", sequence)
    high_charge = abs(charge) > 8 or pi > 9.5
    if hydrophobic_5 and high_charge:
        polyreactivity = "high"
    elif high_charge or poly_basic_4:
        polyreactivity = "moderate"
    else:
        polyreactivity = "low"

    expression = 100.0
    if pi < 4.5 or pi > 10.5:
        expression -= 35
    elif pi < 5.0 or pi > 9.5:
        expression -= 15
    if abs(charge) > 12:
        expression -= 30
    elif abs(charge) > 8:
        expression -= 12
    if gravy > 0.2:
        expression -= 20
    elif gravy > 0.0:
        expression -= 8
    if hydrophobic_5:
        expression -= 35
    if cys != 2:
        expression -= 20
    if polyreactivity == "high":
        expression -= 25
    elif polyreactivity == "moderate":
        expression -= 10
    expression = clamp(expression)

    developability = 100.0
    developability -= min(20, nglyc * 8)
    developability -= min(12, deamidation * 2)
    developability -= min(8, isomerization * 2)
    developability -= min(8, acid_cleavage * 3)
    if cys != 2:
        developability -= 15
    if hydrophobic_5:
        developability -= 35
    developability = clamp(developability)

    risk_tier = "HIGH" if min(expression, developability) < 50 else (
        "MODERATE" if min(expression, developability) < 70 else "LOW"
    )
    return {
        "candidate_id": candidate_id,
        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        "sequence_length": length,
        "descriptor_status": "PASS",
        "molecular_weight_da": f"{mw:.3f}",
        "pI_proxy": f"{pi:.4f}",
        "net_charge_pH7_4_proxy": f"{charge:.4f}",
        "gravy": f"{gravy:.5f}",
        "cys_count": cys,
        "nglyc_motif_count": nglyc,
        "deamidation_risk_count": deamidation,
        "isomerization_risk_count": isomerization,
        "acid_cleavage_DP_count": acid_cleavage,
        "hydrophobic_5_count": hydrophobic_5,
        "poly_basic_4_count": poly_basic_4,
        "poly_acidic_4_count": poly_acidic_4,
        "polyreactivity_proxy": polyreactivity,
        "expression_purity_risk_proxy_partial": f"{expression:.2f}",
        "developability_risk_proxy_partial": f"{developability:.2f}",
        "risk_tier": risk_tier,
        "model_coverage": "sequence_descriptors_only;AbNatiV=NA;TNP=NA;instability=NA",
        "scientific_boundary": "sequence-only risk proxy; not measured purity or expression",
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_fasta", type=Path)
    parser.add_argument("output_tsv", type=Path)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("require 0 <= shard-index < shard-count")
    return args


def main():
    args = parse_args()
    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    rows = (
        score_record(candidate_id, sequence)
        for index, (candidate_id, sequence) in enumerate(read_fasta(args.input_fasta))
        if index % args.shard_count == args.shard_index
    )
    first = next(rows, None)
    with open_text(args.output_tsv, "w") as handle:
        if first is None:
            return 0
        writer = csv.DictWriter(handle, fieldnames=list(first), delimiter="\t")
        writer.writeheader()
        writer.writerow(first)
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
