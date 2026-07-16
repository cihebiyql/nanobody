#!/usr/bin/env python3
"""Cross-check Node1 IgFold models against frozen NanobodyBuilder2 monomers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_SHORTLIST = EXP_DIR / "prepared/pvrig_pre_shortlist100_deepqc_v1/inputs/pre_shortlist100.tsv"
DEFAULT_MANIFEST = EXP_DIR / "prepared/pvrig_candidate_evidence_master_v1/sources/v4d_candidate_monomers_manifest.tsv"
DEFAULT_IGFOLD_ROOT = EXP_DIR / "prepared/pvrig_pre_shortlist100_deepqc_v1/runs"
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_pre_shortlist100_deepqc_v1/reports"
EXPECTED_COUNT = 100

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V",
}


@dataclass
class Residue:
    key: tuple[str, int, str]
    aa: str
    ca: np.ndarray | None


@dataclass
class Structure:
    residues: list[Residue]
    heavy_atom_count: int


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"missing TSV header: {path}")
        return list(reader)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_unique_ids(rows: list[dict[str, str]], name: str, expected_count: int | None = None) -> dict[str, dict[str, str]]:
    ids = [row.get("candidate_id", "") for row in rows]
    if not all(ids):
        raise ValueError(f"{name} has an empty candidate_id")
    duplicate_ids = sorted(candidate_id for candidate_id, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"{name} has duplicate candidate_ids: {duplicate_ids[:5]}")
    if expected_count is not None and len(ids) != expected_count:
        raise ValueError(f"{name} must contain exactly {expected_count} IDs, found {len(ids)}")
    return {row["candidate_id"]: row for row in rows}


def parse_pdb(path: Path, requested_chain: str | None = None) -> Structure:
    """Parse first-model ATOM records without relying on a structural package."""
    residue_atoms: dict[tuple[str, int, str], dict[str, np.ndarray]] = {}
    residue_names: dict[tuple[str, int, str], str] = {}
    heavy_atoms: dict[tuple[str, int, str], int] = Counter()
    in_first_model = True
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        record = line[:6].strip()
        if record == "ENDMDL":
            break
        if record == "MODEL":
            if not in_first_model:
                break
            in_first_model = False
            continue
        if record != "ATOM" or len(line) < 54:
            continue
        altloc = line[16:17]
        if altloc not in (" ", "A", "1"):
            continue
        chain = line[21:22].strip() or "_"
        if requested_chain and chain != requested_chain:
            continue
        try:
            residue_number = int(line[22:26])
            xyz = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=float)
        except ValueError:
            continue
        key = (chain, residue_number, line[26:27].strip())
        atom_name = line[12:16].strip()
        residue_atoms.setdefault(key, {})[atom_name] = xyz
        residue_names[key] = line[17:20].strip().upper()
        # PDB atom names retain the element in the first character for protein atoms.
        if not atom_name.startswith("H"):
            heavy_atoms[key] += 1
    if not residue_atoms:
        raise ValueError(f"no usable ATOM records in {path}")
    if requested_chain is None:
        chain_counts = Counter(key[0] for key in residue_atoms)
        selected_chain = max(chain_counts, key=lambda chain: (chain_counts[chain], chain))
        residue_atoms = {key: atoms for key, atoms in residue_atoms.items() if key[0] == selected_chain}
    residues = [
        Residue(key=key, aa=AA3_TO_1.get(residue_names[key], "X"), ca=atoms.get("CA"))
        for key, atoms in sorted(residue_atoms.items(), key=lambda item: (item[0][1], item[0][2]))
    ]
    return Structure(residues=residues, heavy_atom_count=sum(heavy_atoms[key] for key in residue_atoms))


def align_residues_to_sequence(residues: list[Residue], sequence: str) -> dict[int, int]:
    """Return PDB-residue-index -> target-sequence-index using global alignment."""
    observed = "".join(residue.aa for residue in residues)
    rows, cols = len(observed), len(sequence)
    score = np.zeros((rows + 1, cols + 1), dtype=int)
    trace = np.zeros((rows + 1, cols + 1), dtype=np.int8)
    score[:, 0] = -np.arange(rows + 1)
    score[0, :] = -np.arange(cols + 1)
    trace[1:, 0] = 1
    trace[0, 1:] = 2
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            diagonal = score[i - 1, j - 1] + (2 if observed[i - 1] == sequence[j - 1] and observed[i - 1] != "X" else -1)
            up, left = score[i - 1, j] - 1, score[i, j - 1] - 1
            best = max(diagonal, up, left)
            score[i, j] = best
            trace[i, j] = 0 if best == diagonal else (1 if best == up else 2)
    mapping: dict[int, int] = {}
    i, j = rows, cols
    while i or j:
        direction = trace[i, j] if i and j else (1 if i else 2)
        if direction == 0:
            if observed[i - 1] == sequence[j - 1] and observed[i - 1] != "X":
                mapping[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif direction == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def cdr_positions(sequence: str, row: dict[str, str]) -> tuple[set[int], tuple[int, int]]:
    positions: set[int] = set()
    cdr3_bounds: tuple[int, int] | None = None
    for column in ("cdr1", "cdr2", "cdr3"):
        cdr = row.get(column, "")
        start = sequence.find(cdr) if cdr else -1
        if start < 0 or (cdr and sequence.find(cdr, start + 1) >= 0):
            raise ValueError(f"{column}_NOT_UNIQUE_OR_ABSENT")
        bounds = (start, start + len(cdr) - 1)
        positions.update(range(bounds[0], bounds[1] + 1))
        if column == "cdr3":
            cdr3_bounds = bounds
    if cdr3_bounds is None:
        raise ValueError("CDR3_NOT_UNIQUE_OR_ABSENT")
    return positions, cdr3_bounds


def kabsch_rmsd(reference: np.ndarray, mobile: np.ndarray) -> float:
    if reference.shape != mobile.shape or reference.shape[0] < 3:
        raise ValueError("INSUFFICIENT_COMMON_FRAMEWORK_CA")
    ref_centered = reference - reference.mean(axis=0)
    mob_centered = mobile - mobile.mean(axis=0)
    u, _singular_values, vt = np.linalg.svd(mob_centered.T @ ref_centered)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    aligned = mob_centered @ rotation
    return float(np.sqrt(np.mean(np.sum((aligned - ref_centered) ** 2, axis=1))))


def locate_igfold_pdb(root: Path, candidate_id: str) -> Path:
    direct = [root / f"{candidate_id}.pdb", root / candidate_id / "igfold.pdb"]
    found = [path for path in direct if path.is_file()]
    if root.is_dir():
        found.extend(path for path in root.rglob("*.pdb") if candidate_id in path.parts)
    unique = sorted({path.resolve() for path in found})
    if not unique:
        raise FileNotFoundError("MISSING_IGFOLD_PDB")
    if len(unique) > 1:
        raise ValueError("AMBIGUOUS_IGFOLD_PDB")
    return unique[0]


def float_or_blank(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def crosscheck_candidate(row: dict[str, str], manifest_row: dict[str, str], igfold_path: Path, monomer_root: Path) -> dict[str, str]:
    candidate_id, sequence = row["candidate_id"], row["sequence"]
    result = {
        "candidate_id": candidate_id,
        "igfold_pdb": str(igfold_path),
        "nbb2_pdb": "",
        "sequence_length": str(len(sequence)),
        "igfold_residue_count": "", "nbb2_residue_count": "",
        "igfold_heavy_atom_count": "", "nbb2_heavy_atom_count": "",
        "igfold_sequence_coverage": "", "nbb2_sequence_coverage": "",
        "igfold_ca_coverage": "", "nbb2_ca_coverage": "",
        "common_framework_ca_count": "", "framework_ca_rmsd": "", "cdr3_anchor_distance_delta": "",
        "nbb2_manifest_sha256_verified": "false", "nbb2_sequence_exact": "false",
        "status": "FAIL", "failure_reason": "",
    }
    try:
        source_path = Path(manifest_row.get("source_remote_path", ""))
        monomer_path = (
            source_path
            if source_path.is_absolute() and source_path.is_file()
            else monomer_root / manifest_row["frozen_monomer_path"]
        )
        if not monomer_path.is_file():
            raise FileNotFoundError("MISSING_NBB2_MONOMER")
        result["nbb2_pdb"] = str(monomer_path)
        expected_monomer_sha = manifest_row.get("sha256", "")
        if not expected_monomer_sha or sha256_file(monomer_path) != expected_monomer_sha:
            raise ValueError("NBB2_MONOMER_SHA256_MISMATCH")
        result["nbb2_manifest_sha256_verified"] = "true"
        expected_sequence_sha = manifest_row.get("sequence_sha256", "")
        if not expected_sequence_sha or hashlib.sha256(sequence.encode("utf-8")).hexdigest() != expected_sequence_sha:
            raise ValueError("NBB2_MANIFEST_SEQUENCE_SHA256_MISMATCH")
        igfold = parse_pdb(igfold_path)
        nbb2 = parse_pdb(monomer_path, manifest_row.get("source_chain") or None)
        if "".join(residue.aa for residue in nbb2.residues) != sequence:
            raise ValueError("NBB2_PDB_SEQUENCE_NOT_EXACT")
        result["nbb2_sequence_exact"] = "true"
        result.update({
            "igfold_residue_count": str(len(igfold.residues)), "nbb2_residue_count": str(len(nbb2.residues)),
            "igfold_heavy_atom_count": str(igfold.heavy_atom_count), "nbb2_heavy_atom_count": str(nbb2.heavy_atom_count),
        })
        igfold_map = align_residues_to_sequence(igfold.residues, sequence)
        nbb2_map = align_residues_to_sequence(nbb2.residues, sequence)
        result["igfold_sequence_coverage"] = float_or_blank(len(igfold_map) / len(sequence))
        result["nbb2_sequence_coverage"] = float_or_blank(len(nbb2_map) / len(sequence))
        excluded, (cdr3_start, cdr3_end) = cdr_positions(sequence, row)
        igfold_ca = {target: igfold.residues[index].ca for index, target in igfold_map.items() if igfold.residues[index].ca is not None}
        nbb2_ca = {target: nbb2.residues[index].ca for index, target in nbb2_map.items() if nbb2.residues[index].ca is not None}
        result["igfold_ca_coverage"] = float_or_blank(len(igfold_ca) / len(sequence))
        result["nbb2_ca_coverage"] = float_or_blank(len(nbb2_ca) / len(sequence))
        framework = sorted((set(igfold_ca) & set(nbb2_ca)) - excluded)
        result["common_framework_ca_count"] = str(len(framework))
        rmsd = kabsch_rmsd(np.array([igfold_ca[index] for index in framework]), np.array([nbb2_ca[index] for index in framework]))
        result["framework_ca_rmsd"] = float_or_blank(rmsd)
        anchors = (cdr3_start - 1, cdr3_end + 1)
        if anchors[0] not in igfold_ca or anchors[1] not in igfold_ca or anchors[0] not in nbb2_ca or anchors[1] not in nbb2_ca:
            raise ValueError("MISSING_CDR3_ANCHOR_CA")
        igfold_distance = float(np.linalg.norm(igfold_ca[anchors[0]] - igfold_ca[anchors[1]]))
        nbb2_distance = float(np.linalg.norm(nbb2_ca[anchors[0]] - nbb2_ca[anchors[1]]))
        result["cdr3_anchor_distance_delta"] = float_or_blank(abs(igfold_distance - nbb2_distance))
        result["status"] = "PASS"
    except (FileNotFoundError, ValueError) as exc:
        result["failure_reason"] = str(exc)
    return result


FIELDS = [
    "candidate_id", "igfold_pdb", "nbb2_pdb", "sequence_length", "igfold_residue_count", "nbb2_residue_count",
    "igfold_heavy_atom_count", "nbb2_heavy_atom_count", "igfold_sequence_coverage", "nbb2_sequence_coverage",
    "igfold_ca_coverage", "nbb2_ca_coverage",
    "common_framework_ca_count", "framework_ca_rmsd", "cdr3_anchor_distance_delta", "status", "failure_reason",
    "nbb2_manifest_sha256_verified", "nbb2_sequence_exact",
]


def run(args: argparse.Namespace) -> dict[str, object]:
    shortlist = require_unique_ids(read_tsv(args.pre_shortlist), "pre_shortlist100", EXPECTED_COUNT)
    manifest = require_unique_ids(read_tsv(args.monomer_manifest), "candidate_monomers_manifest")
    missing_manifest = sorted(set(shortlist) - set(manifest))
    if missing_manifest:
        raise ValueError(f"100-ID closure failed; IDs absent from monomer manifest: {missing_manifest[:5]}")
    rows: list[dict[str, str]] = []
    for candidate_id, row in shortlist.items():
        try:
            igfold_path = locate_igfold_pdb(args.igfold_root, candidate_id)
        except (FileNotFoundError, ValueError) as exc:
            rows.append({field: "" for field in FIELDS} | {
                "candidate_id": candidate_id, "status": "FAIL", "failure_reason": str(exc),
            })
            continue
        rows.append(crosscheck_candidate(row, manifest[candidate_id], igfold_path, args.monomer_root))
    if len(rows) != EXPECTED_COUNT or len({row["candidate_id"] for row in rows}) != EXPECTED_COUNT:
        raise RuntimeError("internal 100-ID output closure failure")
    args.outdir.mkdir(parents=True, exist_ok=True)
    tsv_path, json_path = args.outdir / "igfold_nbb2_crosscheck.tsv", args.outdir / "igfold_nbb2_crosscheck.json"
    with tsv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if row["status"] != "PASS"]
    summary: dict[str, object] = {
        "schema_version": "igfold_nbb2_crosscheck_v1", "candidate_count": len(rows),
        "unique_candidate_count": len({row["candidate_id"] for row in rows}),
        "pass_count": len(rows) - len(failures), "failure_count": len(failures),
        "status": "PASS" if not failures else "FAIL", "failure_reasons": dict(Counter(row["failure_reason"] for row in failures)),
        "outputs": {"tsv": str(tsv_path), "json": str(json_path)},
        "claim_boundary": "Monomer structure agreement only; this audit does not establish PVRIG binding, affinity, docking, or blocking.",
    }
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.terminal and failures:
        raise RuntimeError(f"terminal crosscheck failure: {len(failures)} of {EXPECTED_COUNT} candidates failed")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-shortlist", type=Path, default=DEFAULT_SHORTLIST)
    parser.add_argument("--monomer-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--monomer-root", type=Path, default=EXP_DIR / "prepared/pvrig_candidate_evidence_master_v1")
    parser.add_argument("--igfold-root", type=Path, default=DEFAULT_IGFOLD_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--terminal", action="store_true", help="fail after writing reports when any candidate fails")
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
