#!/usr/bin/env python3
"""Compare frozen NBB2, IgFold, and NanoNet Top200 monomer structures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
PAIR_NAMES = (
    ("igfold", "nbb2"),
    ("igfold", "nanonet"),
    ("nbb2", "nanonet"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_model(path: Path) -> tuple[str, list[np.ndarray]]:
    chains: dict[str, list[tuple[str, np.ndarray]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
            continue
        if line[16] not in (" ", "A"):
            continue
        chain = line[21].strip() or "_"
        key = (chain, line[22:26], line[26])
        if key in seen:
            continue
        seen.add(key)
        aa = AA3.get(line[17:20].strip().upper())
        if aa is None:
            continue
        coord = np.array(
            [float(line[30:38]), float(line[38:46]), float(line[46:54])],
            dtype=float,
        )
        chains.setdefault(chain, []).append((aa, coord))
    if not chains:
        return "", []
    _, residues = max(chains.items(), key=lambda item: len(item[1]))
    return "".join(aa for aa, _ in residues), [coord for _, coord in residues]


def locate_regions(sequence: str, cdrs: tuple[str, str, str]) -> dict[str, list[int]]:
    regions: dict[str, list[int]] = {}
    start = 0
    occupied: set[int] = set()
    for name, cdr in zip(("cdr1", "cdr2", "cdr3"), cdrs):
        index = sequence.find(cdr, start)
        if index < 0:
            raise ValueError(f"{name} not found in sequence: {cdr}")
        indices = list(range(index, index + len(cdr)))
        regions[name] = indices
        occupied.update(indices)
        start = index + len(cdr)
    regions["framework"] = [
        index for index in range(len(sequence)) if index not in occupied
    ]
    return regions


def fit_on_framework(
    reference: list[np.ndarray],
    mobile: list[np.ndarray],
    framework: list[int],
) -> tuple[np.ndarray, np.ndarray, float]:
    indices = [
        index for index in framework
        if index < len(reference) and index < len(mobile)
    ]
    if len(indices) < 20:
        raise ValueError("fewer than 20 common framework CA atoms")
    ref = np.stack([reference[index] for index in indices])
    mob = np.stack([mobile[index] for index in indices])
    ref_center = ref.mean(axis=0)
    mob_center = mob.mean(axis=0)
    covariance = (mob - mob_center).T @ (ref - ref_center)
    u_matrix, _, vt_matrix = np.linalg.svd(covariance)
    rotation = vt_matrix.T @ u_matrix.T
    if np.linalg.det(rotation) < 0:
        vt_matrix[-1, :] *= -1
        rotation = vt_matrix.T @ u_matrix.T
    transformed = (mob - mob_center) @ rotation.T + ref_center
    rmsd = float(np.sqrt(np.mean(np.sum((transformed - ref) ** 2, axis=1))))
    translation = ref_center - mob_center @ rotation.T
    return rotation, translation, rmsd


def region_rmsd(
    reference: list[np.ndarray],
    mobile: list[np.ndarray],
    indices: list[int],
    rotation: np.ndarray,
    translation: np.ndarray,
) -> float | None:
    common = [
        index for index in indices
        if index < len(reference) and index < len(mobile)
    ]
    if not common:
        return None
    ref = np.stack([reference[index] for index in common])
    mob = np.stack([mobile[index] for index in common])
    transformed = mob @ rotation.T + translation
    return float(np.sqrt(np.mean(np.sum((transformed - ref) ** 2, axis=1))))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t",
            extrasaction="ignore", lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    array = np.array(values, dtype=float)
    return {
        "min": round(float(np.min(array)), 4),
        "q25": round(float(np.quantile(array, 0.25)), 4),
        "median": round(float(np.median(array)), 4),
        "q75": round(float(np.quantile(array, 0.75)), 4),
        "max": round(float(np.max(array)), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    manifest_path = project / "manifests" / "top200_structure_manifest.tsv"
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        manifest = list(csv.DictReader(handle, delimiter="\t"))

    rows: list[dict[str, object]] = []
    for item in sorted(manifest, key=lambda row: int(row["top200_rank"])):
        candidate = item["candidate_id"]
        paths = {
            "nbb2": Path(item["nbb2_pdb"]),
            "igfold": project / "models" / "igfold" / f"{candidate}.pdb",
            "nanonet": (
                project / "models" / "nanonet"
                / f"{candidate}_nanonet_backbone_cb.pdb"
            ),
        }
        models: dict[str, list[np.ndarray]] = {}
        reasons: list[str] = []
        output: dict[str, object] = {
            "top200_rank": item["top200_rank"],
            "candidate_id": candidate,
            "sequence_sha256": item["sequence_sha256"],
        }
        for tool, path in paths.items():
            output[f"{tool}_pdb"] = str(path)
            if not path.is_file():
                output[f"{tool}_state"] = "MISSING"
                reasons.append(f"{tool}_missing")
                continue
            observed, coords = parse_model(path)
            sequence_match = observed == item["sequence"]
            output[f"{tool}_state"] = "PASS" if sequence_match else "SEQUENCE_MISMATCH"
            output[f"{tool}_sequence_match"] = str(sequence_match).lower()
            output[f"{tool}_ca_count"] = len(coords)
            output[f"{tool}_coverage"] = round(len(coords) / len(item["sequence"]), 4)
            output[f"{tool}_pdb_sha256"] = sha256_file(path)
            if not sequence_match:
                reasons.append(f"{tool}_sequence_mismatch")
            else:
                models[tool] = coords

        regions = locate_regions(
            item["sequence"],
            (item["imgt_cdr1"], item["imgt_cdr2"], item["imgt_cdr3"]),
        )
        fr_values: list[float] = []
        cdr3_values: list[float] = []
        for first, second in PAIR_NAMES:
            prefix = f"{first}_vs_{second}"
            if first not in models or second not in models:
                output[f"{prefix}_fr_rmsd_a"] = ""
                continue
            rotation, translation, fr_rmsd = fit_on_framework(
                models[first], models[second], regions["framework"]
            )
            output[f"{prefix}_fr_rmsd_a"] = round(fr_rmsd, 4)
            fr_values.append(fr_rmsd)
            for region_name in ("cdr1", "cdr2", "cdr3"):
                value = region_rmsd(
                    models[first], models[second], regions[region_name],
                    rotation, translation,
                )
                output[f"{prefix}_{region_name}_rmsd_a"] = (
                    "" if value is None else round(value, 4)
                )
                if region_name == "cdr3" and value is not None:
                    cdr3_values.append(value)

        coverage_values = [
            float(output[f"{tool}_coverage"])
            for tool in ("nbb2", "igfold", "nanonet")
            if output.get(f"{tool}_coverage") not in ("", None)
        ]
        output["max_pairwise_fr_rmsd_a"] = (
            round(max(fr_values), 4) if fr_values else ""
        )
        output["max_pairwise_cdr3_rmsd_a"] = (
            round(max(cdr3_values), 4) if cdr3_values else ""
        )

        label = "PASS"
        if len(models) != 3 or any(value < 0.90 for value in coverage_values):
            label = "FAIL"
        igfold_nbb2 = output.get("igfold_vs_nbb2_fr_rmsd_a")
        if igfold_nbb2 not in ("", None) and float(igfold_nbb2) > 4.0:
            label = "FAIL"
            reasons.append("igfold_vs_nbb2_fr_rmsd_gt_4A")
        if label != "FAIL" and (
            any(value < 0.97 for value in coverage_values)
            or any(value > 3.0 for value in fr_values)
        ):
            label = "WARN"
        if output["max_pairwise_cdr3_rmsd_a"] not in ("", None):
            if float(output["max_pairwise_cdr3_rmsd_a"]) > 4.0:
                reasons.append("cdr3_cross_tool_disagreement_gt_4A_diagnostic")
        output["structure_consistency_label"] = label
        output["high_uncertainty"] = str(
            label != "PASS"
            or "cdr3_cross_tool_disagreement_gt_4A_diagnostic" in reasons
        ).lower()
        output["reasons"] = ";".join(sorted(set(reasons)))
        rows.append(output)

    fields = [
        "top200_rank", "candidate_id", "sequence_sha256",
        "structure_consistency_label", "high_uncertainty", "reasons",
    ]
    for tool in ("nbb2", "igfold", "nanonet"):
        fields.extend(
            [
                f"{tool}_state", f"{tool}_sequence_match", f"{tool}_ca_count",
                f"{tool}_coverage", f"{tool}_pdb", f"{tool}_pdb_sha256",
            ]
        )
    for first, second in PAIR_NAMES:
        prefix = f"{first}_vs_{second}"
        fields.extend(
            [
                f"{prefix}_fr_rmsd_a", f"{prefix}_cdr1_rmsd_a",
                f"{prefix}_cdr2_rmsd_a", f"{prefix}_cdr3_rmsd_a",
            ]
        )
    fields.extend(["max_pairwise_fr_rmsd_a", "max_pairwise_cdr3_rmsd_a"])

    reports = project / "reports"
    metrics_path = reports / "TOP200_STRUCTURE_CONSISTENCY_METRICS.tsv"
    uncertain_path = reports / "TOP200_STRUCTURE_HIGH_UNCERTAINTY.tsv"
    write_tsv(metrics_path, rows, fields)
    uncertain = [row for row in rows if row["high_uncertainty"] == "true"]
    write_tsv(uncertain_path, uncertain, fields)

    summary = {
        "schema_version": "pvrig.top200.structure_consistency.summary.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "label_counts": dict(
            sorted(Counter(row["structure_consistency_label"] for row in rows).items())
        ),
        "high_uncertainty_count": len(uncertain),
        "complete_three_tool_count": sum(
            all(row.get(f"{tool}_state") == "PASS" for tool in ("nbb2", "igfold", "nanonet"))
            for row in rows
        ),
        "fr_rmsd_quantiles_a": {
            f"{first}_vs_{second}": quantiles(
                [
                    float(row[f"{first}_vs_{second}_fr_rmsd_a"])
                    for row in rows
                    if row.get(f"{first}_vs_{second}_fr_rmsd_a") not in ("", None)
                ]
            )
            for first, second in PAIR_NAMES
        },
        "cdr3_rmsd_quantiles_a": {
            f"{first}_vs_{second}": quantiles(
                [
                    float(row[f"{first}_vs_{second}_cdr3_rmsd_a"])
                    for row in rows
                    if row.get(f"{first}_vs_{second}_cdr3_rmsd_a") not in ("", None)
                ]
            )
            for first, second in PAIR_NAMES
        },
        "manifest_sha256": sha256_file(manifest_path),
        "metrics_sha256": sha256_file(metrics_path),
        "high_uncertainty_sha256": sha256_file(uncertain_path),
        "claim_boundary": (
            "Cross-tool monomer consistency is a structural uncertainty diagnostic; "
            "it is not experimental binding, affinity, purity, or blocking evidence."
        ),
    }
    summary_path = reports / "TOP200_STRUCTURE_CONSISTENCY_SUMMARY.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
