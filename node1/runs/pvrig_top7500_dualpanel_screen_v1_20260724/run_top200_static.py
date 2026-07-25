#!/usr/bin/env python3
"""Run the calibrated Top200 static-review panel on frozen docking poses.

Each frozen pose receives:
* deterministic interface contact/geometry proxies;
* Rosetta InterfaceAnalyzer (descriptive only; calibration rejected ranking);
* PRODIGY (weak prior only);
* explicit FoldX NOT_RUN status because cross-candidate absolute ranking was
  rejected by calibration.

The program is resumable and never overwrites a completed job whose input hash
matches the manifest.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROSETTA_DEFAULT = (
    "/data/qlyu/software/rosetta_3.15/main/source/bin/"
    "InterfaceAnalyzer.static.linuxgccrelease"
)
PRODIGY_DEFAULT = "/data/qlyu/anaconda3/envs/prodigy/bin/prodigy"
AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
HYDROPHOBIC = set("AVILMFWY")
POSITIVE_ATOMS = {
    ("ARG", "NE"), ("ARG", "NH1"), ("ARG", "NH2"), ("LYS", "NZ"),
    ("HIS", "ND1"), ("HIS", "NE2"),
}
NEGATIVE_ATOMS = {
    ("ASP", "OD1"), ("ASP", "OD2"), ("GLU", "OE1"), ("GLU", "OE2"),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty TSV: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_score(path: Path) -> dict[str, float]:
    lines = [
        line.split()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("SCORE:")
    ]
    if len(lines) != 2:
        raise RuntimeError(f"expected score header and one row: {path}")
    header, values = lines[0][1:], lines[1][1:]
    if len(header) != len(values):
        raise RuntimeError(f"score column mismatch: {path}")
    return {
        name: float(value)
        for name, value in zip(header, values)
        if name != "description"
    }


def parse_prodigy(stdout: str) -> float:
    for line in reversed(stdout.splitlines()):
        tokens = line.split()
        if not tokens:
            continue
        try:
            value = float(tokens[-1])
        except ValueError:
            continue
        if math.isfinite(value):
            return value
    raise RuntimeError("PRODIGY output did not contain a finite affinity value")


def parse_atoms(path: Path) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for line in path.read_text(encoding="ascii", errors="ignore").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54:
            continue
        chain = line[21:22]
        if chain not in {"A", "T"}:
            continue
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        atom = line[12:16].strip()
        resname = line[17:20].strip()
        element = line[76:78].strip() if len(line) >= 78 else ""
        if not element:
            element = re.sub("[^A-Za-z]", "", atom)[:1].upper()
        if element == "H":
            continue
        atoms.append(
            {
                "chain": chain,
                "atom": atom,
                "resname": resname,
                "residue": (chain, line[22:26].strip(), line[26:27].strip()),
                "xyz": (x, y, z),
                "element": element,
            }
        )
    if not atoms:
        raise RuntimeError(f"no A/T heavy atoms parsed: {path}")
    return atoms


def distance2(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right))


def residue_sequence(
    atoms: list[dict[str, Any]], chain: str
) -> tuple[list[tuple[str, str, str]], str]:
    ordered: list[tuple[str, str, str]] = []
    names: dict[tuple[str, str, str], str] = {}
    for atom in atoms:
        if atom["chain"] != chain:
            continue
        residue = atom["residue"]
        if residue not in names:
            ordered.append(residue)
            names[residue] = atom["resname"]
    sequence = "".join(AA3.get(names[residue], "X") for residue in ordered)
    return ordered, sequence


def cdr_residue_labels(
    atoms: list[dict[str, Any]], cdrs: dict[str, str]
) -> dict[tuple[str, str, str], str]:
    residues, sequence = residue_sequence(atoms, "A")
    labels = {residue: "framework" for residue in residues}
    cursor = 0
    for name in ("cdr1", "cdr2", "cdr3"):
        motif = cdrs.get(name, "")
        if not motif:
            continue
        index = sequence.find(motif, cursor)
        if index < 0:
            index = sequence.find(motif)
        if index < 0:
            raise RuntimeError(f"{name} sequence not found in frozen PDB")
        for residue in residues[index : index + len(motif)]:
            labels[residue] = name
        cursor = index + len(motif)
    return labels


def static_geometry(path: Path, cdrs: dict[str, str]) -> dict[str, Any]:
    atoms = parse_atoms(path)
    cdr_labels = cdr_residue_labels(atoms, cdrs)
    receptor = [atom for atom in atoms if atom["chain"] == "T"]
    vhh = [atom for atom in atoms if atom["chain"] == "A"]
    if not receptor or not vhh:
        raise RuntimeError("frozen pose lacks receptor T or VHH A atoms")
    cell_size = 5.0
    grid: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for atom in receptor:
        key = tuple(math.floor(value / cell_size) for value in atom["xyz"])
        grid[key].append(atom)
    atom_contacts = clash_pairs = hbond_proxy = salt_bridge_proxy = 0
    residue_pairs: set[tuple[Any, Any]] = set()
    hydrophobic_residue_pairs: set[tuple[Any, Any]] = set()
    vhh_contact_residues: set[tuple[str, str, str]] = set()
    for atom in vhh:
        cell = tuple(math.floor(value / cell_size) for value in atom["xyz"])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other in grid.get(
                        (cell[0] + dx, cell[1] + dy, cell[2] + dz), []
                    ):
                        d2 = distance2(atom["xyz"], other["xyz"])
                        if d2 <= 25.0:
                            residue_pair = (atom["residue"], other["residue"])
                            residue_pairs.add(residue_pair)
                            vhh_contact_residues.add(atom["residue"])
                            if (
                                AA3.get(atom["resname"]) in HYDROPHOBIC
                                and AA3.get(other["resname"]) in HYDROPHOBIC
                            ):
                                hydrophobic_residue_pairs.add(residue_pair)
                        if d2 <= 20.25:
                            atom_contacts += 1
                        if d2 <= 4.0:
                            clash_pairs += 1
                        if (
                            d2 <= 12.25
                            and atom["element"] in {"N", "O"}
                            and other["element"] in {"N", "O"}
                            and atom["element"] != other["element"]
                        ):
                            hbond_proxy += 1
                        charge_left = (atom["resname"], atom["atom"])
                        charge_right = (other["resname"], other["atom"])
                        if d2 <= 16.0 and (
                            (
                                charge_left in POSITIVE_ATOMS
                                and charge_right in NEGATIVE_ATOMS
                            )
                            or (
                                charge_left in NEGATIVE_ATOMS
                                and charge_right in POSITIVE_ATOMS
                            )
                        ):
                            salt_bridge_proxy += 1
    label_counts = Counter(
        cdr_labels.get(residue, "unknown") for residue in vhh_contact_residues
    )
    a_residues, a_sequence = residue_sequence(atoms, "A")
    t_residues, _ = residue_sequence(atoms, "T")
    # A low same-chain CA-neighbour count is a deliberately labelled exposure proxy.
    ca_by_residue = {
        atom["residue"]: atom["xyz"]
        for atom in vhh
        if atom["atom"] == "CA"
    }
    exposed_hydrophobic = 0
    for residue, aa in zip(a_residues, a_sequence):
        if aa not in HYDROPHOBIC or residue not in ca_by_residue:
            continue
        neighbours = sum(
            other != residue
            and distance2(ca_by_residue[residue], xyz) <= 64.0
            for other, xyz in ca_by_residue.items()
        )
        if neighbours < 8:
            exposed_hydrophobic += 1
    ptm_positions: set[int] = set()
    for pattern in (r"N[^P][ST]", r"N[GS]", r"D[GS]", r"[MW]"):
        for match in re.finditer(pattern, a_sequence):
            ptm_positions.update(range(match.start(), match.end()))
    exposed_ptm = 0
    for index in ptm_positions:
        if index >= len(a_residues):
            continue
        residue = a_residues[index]
        if residue not in ca_by_residue:
            continue
        neighbours = sum(
            other != residue
            and distance2(ca_by_residue[residue], xyz) <= 64.0
            for other, xyz in ca_by_residue.items()
        )
        exposed_ptm += int(neighbours < 8)
    return {
        "interface_atom_contacts_4p5a": atom_contacts,
        "interface_residue_pairs_5a": len(residue_pairs),
        "interface_contact_density_proxy": round(
            len(residue_pairs) / math.sqrt(max(1, len(a_residues) * len(t_residues))),
            8,
        ),
        "physical_clash_atom_pairs_2a": clash_pairs,
        "hbond_donor_acceptor_distance_proxy_3p5a": hbond_proxy,
        "salt_bridge_distance_proxy_4a": salt_bridge_proxy,
        "hydrophobic_interface_residue_pairs_5a": len(hydrophobic_residue_pairs),
        "vhh_contact_residue_count": len(vhh_contact_residues),
        "cdr1_contact_residue_count": label_counts["cdr1"],
        "cdr2_contact_residue_count": label_counts["cdr2"],
        "cdr3_contact_residue_count": label_counts["cdr3"],
        "framework_contact_residue_count": label_counts["framework"],
        "cdr_contact_fraction": round(
            (
                label_counts["cdr1"]
                + label_counts["cdr2"]
                + label_counts["cdr3"]
            )
            / max(1, len(vhh_contact_residues)),
            8,
        ),
        "cdr3_contact_fraction": round(
            label_counts["cdr3"] / max(1, len(vhh_contact_residues)), 8
        ),
        "exposed_hydrophobic_residue_count_proxy": exposed_hydrophobic,
        "ptm_motif_residue_exposed_count_proxy": exposed_ptm,
    }


def run_one(
    row: dict[str, str],
    root: Path,
    rosetta: Path,
    prodigy: Path,
) -> dict[str, Any]:
    job_id = row["static_job_id"]
    job_dir = root / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    complete_path = job_dir / "COMPLETE.json"
    failed_path = job_dir / "FAILED.json"
    pdb_path = Path(row["frozen_pdb"])
    observed_hash = sha256_file(pdb_path)
    if observed_hash != row["frozen_pdb_sha256"]:
        raise RuntimeError(f"{job_id}: frozen PDB hash mismatch")
    if complete_path.is_file():
        previous = json.loads(complete_path.read_text(encoding="utf-8"))
        if (
            previous.get("frozen_pdb_sha256") == observed_hash
            and (job_dir / "static_metrics.json").is_file()
            and (job_dir / "score.sc").is_file()
        ):
            return {
                "static_job_id": job_id,
                "state": "SKIPPED_COMPLETE",
                "elapsed_seconds": previous.get("elapsed_seconds", 0),
            }
        raise RuntimeError(f"{job_id}: stale or mismatched COMPLETE marker")
    failed_path.unlink(missing_ok=True)
    start = time.time()
    geometry = static_geometry(
        pdb_path,
        {"cdr1": row.get("cdr1", ""), "cdr2": row.get("cdr2", ""), "cdr3": row.get("cdr3", "")},
    )
    rosetta_cmd = [
        str(rosetta),
        "-s", str(pdb_path),
        "-interface", "T_A",
        "-pack_input", "true",
        "-pack_separated", "true",
        "-compute_packstat", "true",
        "-tracer_data_print", "true",
        "-out:file:score_only", "score.sc",
        "-out:file:scorefile", "score.sc",
        "-overwrite",
    ]
    rosetta_result = subprocess.run(
        rosetta_cmd,
        cwd=job_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (job_dir / "rosetta.stdout.log").write_text(
        rosetta_result.stdout, encoding="utf-8"
    )
    (job_dir / "rosetta.stderr.log").write_text(
        rosetta_result.stderr, encoding="utf-8"
    )
    score_path = job_dir / "score.sc"
    if rosetta_result.returncode != 0 or not score_path.is_file():
        failure = {
            "state": "FAILED",
            "stage": "ROSETTA",
            "return_code": rosetta_result.returncode,
            "finished_at": utcnow(),
        }
        failed_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        return {"static_job_id": job_id, **failure}
    rosetta_scores = parse_score(score_path)
    prodigy_result = subprocess.run(
        [str(prodigy), str(pdb_path), "--selection", "T", "A", "-q"],
        cwd=job_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (job_dir / "prodigy.stdout.log").write_text(
        prodigy_result.stdout, encoding="utf-8"
    )
    (job_dir / "prodigy.stderr.log").write_text(
        prodigy_result.stderr, encoding="utf-8"
    )
    if prodigy_result.returncode != 0:
        failure = {
            "state": "FAILED",
            "stage": "PRODIGY",
            "return_code": prodigy_result.returncode,
            "finished_at": utcnow(),
        }
        failed_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        return {"static_job_id": job_id, **failure}
    prodigy_affinity = parse_prodigy(prodigy_result.stdout)
    metrics = {
        **row,
        **geometry,
        **{f"rosetta_{key}": value for key, value in rosetta_scores.items()},
        "prodigy_predicted_dg_kcal_mol": prodigy_affinity,
        "rosetta_calibration_role": "DESCRIPTIVE_ONLY",
        "prodigy_calibration_role": "WEAK_PRIOR_ONLY",
        "foldx_status": "NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED",
        "static_rank_contribution": 0.0,
        "static_review_evidence_boundary": (
            "Static structure diagnostics only; not experimental affinity, "
            "blocking, expression or purity."
        ),
    }
    metrics_path = job_dir / "static_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    complete = {
        "state": "COMPLETE",
        "static_job_id": job_id,
        "candidate_id": row["candidate_id"],
        "frozen_pdb_sha256": observed_hash,
        "metrics_sha256": sha256_file(metrics_path),
        "score_sha256": sha256_file(score_path),
        "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "finished_at": utcnow(),
        "elapsed_seconds": round(time.time() - start, 3),
    }
    complete_path.write_text(
        json.dumps(complete, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"static_job_id": job_id, **complete}


def collect(manifest: list[dict[str, str]], root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    output: list[dict[str, Any]] = []
    failures: list[str] = []
    for row in manifest:
        job_dir = root / "jobs" / row["static_job_id"]
        complete = job_dir / "COMPLETE.json"
        metrics = job_dir / "static_metrics.json"
        if not complete.is_file() or not metrics.is_file():
            failures.append(row["static_job_id"])
            continue
        payload = json.loads(metrics.read_text(encoding="utf-8"))
        if payload.get("frozen_pdb_sha256") != row.get("frozen_pdb_sha256"):
            failures.append(row["static_job_id"])
            continue
        output.append(payload)
    return output, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rosetta", type=Path, default=Path(ROSETTA_DEFAULT))
    parser.add_argument("--prodigy", type=Path, default=Path(PRODIGY_DEFAULT))
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    if not args.rosetta.is_file() or not os.access(args.rosetta, os.X_OK):
        parser.error(f"Rosetta executable unavailable: {args.rosetta}")
    if not args.prodigy.is_file() or not os.access(args.prodigy, os.X_OK):
        parser.error(f"PRODIGY executable unavailable: {args.prodigy}")
    manifest = read_tsv(args.manifest)
    if len(manifest) != 400:
        raise ValueError(f"expected 400 static jobs, got {len(manifest)}")
    args.out.mkdir(parents=True, exist_ok=True)
    lock_path = args.out / "STATIC_CONTROLLER.lock"
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another static controller owns the lock")
    status_path = args.out / "STATIC_LIVE_STATUS.json"
    status_path.write_text(
        json.dumps(
            {
                "state": "RUNNING",
                "started_at": utcnow(),
                "pid": os.getpid(),
                "total": len(manifest),
                "workers": args.workers,
                "completed": 0,
                "failed": 0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    completed = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_one, row, args.out, args.rosetta, args.prodigy): row
            for row in manifest
        }
        for future in as_completed(futures):
            result = future.result()
            if result.get("state") in {"COMPLETE", "SKIPPED_COMPLETE"}:
                completed += 1
            else:
                failed += 1
            status_path.write_text(
                json.dumps(
                    {
                        "state": "RUNNING",
                        "updated_at": utcnow(),
                        "pid": os.getpid(),
                        "total": len(manifest),
                        "workers": args.workers,
                        "completed": completed,
                        "failed": failed,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    rows, missing = collect(manifest, args.out)
    if missing or failed or len(rows) != 400:
        status = {
            "state": "PARTIAL",
            "finished_at": utcnow(),
            "total": 400,
            "completed": len(rows),
            "failed": failed,
            "missing": missing,
        }
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"static panel incomplete: {status}")
    metrics_path = args.out / "STATIC_POSE_METRICS.tsv"
    write_tsv(metrics_path, rows)
    candidate_counts = Counter(row["candidate_id"] for row in rows)
    if set(candidate_counts.values()) != {2} or len(candidate_counts) != 200:
        raise RuntimeError("static panel does not have exactly two poses per candidate")
    elapsed_values = [
        json.loads(
            (args.out / "jobs" / row["static_job_id"] / "COMPLETE.json").read_text(
                encoding="utf-8"
            )
        )["elapsed_seconds"]
        for row in manifest
    ]
    receipt = {
        "schema_version": "pvrig.top200.static_review.v1",
        "state": "STATIC_COMPLETE",
        "candidates": 200,
        "jobs": 400,
        "workers": args.workers,
        "median_job_seconds": statistics.median(elapsed_values),
        "manifest_sha256": sha256_file(args.manifest),
        "metrics_sha256": sha256_file(metrics_path),
        "method_roles": {
            "rosetta": "DESCRIPTIVE_ONLY",
            "prodigy": "WEAK_PRIOR_ONLY",
            "foldx": "NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED",
        },
        "claim_boundary": (
            "Static computational diagnostics; no BLI, Kd, IC50, expression or "
            "purity claim."
        ),
    }
    receipt_path = args.out / "STATIC_COMPLETE.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    status_path.write_text(
        json.dumps(
            {"state": "COMPLETE", "finished_at": utcnow(), **receipt},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"candidates": 200, "jobs": 400, "failed": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
