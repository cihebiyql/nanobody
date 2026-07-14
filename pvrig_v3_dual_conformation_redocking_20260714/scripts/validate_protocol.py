#!/usr/bin/env python3
"""Validate frozen references, protocol lock, and all 1050 docking jobs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_docking_jobs import render_cfg_from_job, render_restraints_from_job
from common import STANDARD_RESIDUES, read_json, sha256_file, sha256_text, write_json


PASS = "PASS"
FAIL = "FAIL"
NOT_READY = "NOT_READY"
VALID_STATES = {PASS, FAIL, NOT_READY}


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        payload = read_json(path)
        raw_rows = payload if isinstance(payload, list) else payload.get("jobs", payload.get("rows", []))
        return [{str(key): "" if value is None else str(value) for key, value in row.items()} for row in raw_rows]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{key: "" if value is None else value for key, value in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def gate(status: str, reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    if status not in VALID_STATES:
        raise ValueError(status)
    return {"status": status, "reasons": sorted(reasons or []), **extra}


def overall_status(gates: dict[str, dict[str, Any]], readiness_gates: set[str] | None = None) -> str:
    if any(item["status"] == FAIL for item in gates.values()):
        return FAIL
    if any(item["status"] == NOT_READY for item in gates.values()):
        return NOT_READY
    return PASS


def validate_interface(protocol: dict[str, Any], root: Path) -> dict[str, Any]:
    path = root / "inputs/normalized/interface_hotspots_uniprot.tsv"
    if not path.is_file():
        return gate(NOT_READY, [f"missing:{path}"])
    rows = load_rows(path)
    positions = [int(row["uniprot_position"]) for row in rows]
    anchors = {int(row["uniprot_position"]) for row in rows if row["restraint_role"] == "AIR_ANCHOR"}
    holdouts = {int(row["uniprot_position"]) for row in rows if row["restraint_role"] == "SCORING_HOLDOUT"}
    reasons: list[str] = []
    if len(rows) != int(protocol["interface"]["unique_interface_residue_count"]) or len(set(positions)) != len(rows):
        reasons.append(f"unique_interface_count:{len(rows)}:{len(set(positions))}")
    if len(anchors) != int(protocol["interface"]["air_anchor_count"]):
        reasons.append(f"anchor_count:{len(anchors)}")
    if len(holdouts) != int(protocol["interface"]["holdout_count"]):
        reasons.append(f"holdout_count:{len(holdouts)}")
    if anchors & holdouts or anchors | holdouts != set(positions):
        reasons.append("anchor_holdout_partition_invalid")
    return gate(PASS if not reasons else FAIL, reasons, positions=positions, anchors=sorted(anchors), holdouts=sorted(holdouts))


def pdb_audit(path: Path) -> dict[str, Any]:
    chains: set[str] = set()
    residues: dict[str, set[int]] = defaultdict(set)
    atom_count = 0
    hetatm = 0
    nonstandard = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("HETATM"):
            hetatm += 1
        if not line.startswith("ATOM  "):
            continue
        atom_count += 1
        chain = line[21]
        chains.add(chain)
        residues[chain].add(int(line[22:26]))
        if line[17:20].strip().upper() not in STANDARD_RESIDUES:
            nonstandard += 1
    return {
        "chains": sorted(chains),
        "residues": {chain: sorted(values) for chain, values in sorted(residues.items())},
        "atom_count": atom_count,
        "hetatm_count": hetatm,
        "nonstandard_atom_count": nonstandard,
    }


def validate_references(protocol: dict[str, Any], root: Path, interface_gate: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    audits: dict[str, Any] = {}
    hotspot_positions = set(interface_gate.get("positions", []))
    for conformation, config in sorted(protocol["references"]["conformations"].items()):
        for kind, expected_chains in (("normalized_receptor_pdb", {"T"}), ("normalized_reference_pdb", {"T", "L"})):
            path = root / config[kind]
            if not path.is_file():
                reasons.append(f"missing_reference:{conformation}:{kind}:{path}")
                continue
            audit = pdb_audit(path)
            audits[f"{conformation}:{kind}"] = {**audit, "path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            if set(audit["chains"]) != expected_chains:
                reasons.append(f"bad_chains:{conformation}:{kind}:{audit['chains']}")
            if audit["hetatm_count"]:
                reasons.append(f"hetatm_present:{conformation}:{kind}:{audit['hetatm_count']}")
            if audit["nonstandard_atom_count"]:
                reasons.append(f"nonstandard_atom:{conformation}:{kind}:{audit['nonstandard_atom_count']}")
            if not hotspot_positions.issubset(set(audit["residues"].get("T", []))):
                reasons.append(f"hotspots_missing_from_T:{conformation}:{kind}")
    for sentinel in (71, 135):
        for conformation in protocol["references"]["conformations"]:
            receptor = audits.get(f"{conformation}:normalized_receptor_pdb", {})
            if sentinel not in receptor.get("residues", {}).get("T", []):
                reasons.append(f"uniprot_sentinel_missing:{conformation}:{sentinel}")
    status = PASS if not reasons else (NOT_READY if any(reason.startswith("missing_reference") for reason in reasons) else FAIL)
    return gate(status, reasons, audits=audits)


def validate_core_lock(root: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    path = root / "PROTOCOL_CORE_LOCK.json"
    if not path.is_file():
        return gate(NOT_READY, ["PROTOCOL_CORE_LOCK.json_missing"])
    payload = read_json(path)
    expected = payload.get("protocol_core_sha256", "")
    reasons: list[str] = []
    if payload.get("status") != "CORE_LOCKED":
        reasons.append("core_lock_status_not_locked")
    drifted: list[str] = []
    for record in payload.get("files", []):
        relative = str(record.get("path", ""))
        file_path = root / relative
        if not relative or not file_path.is_file() or sha256_file(file_path) != record.get("sha256"):
            drifted.append(relative or "MISSING_PATH")
    if drifted:
        reasons.append(f"core_files_drifted:{','.join(sorted(drifted))}")
    observed = {row.get("protocol_core_sha256", "") for row in rows if row.get("protocol_core_sha256")}
    if rows and observed != {expected}:
        reasons.append(f"job_core_hash_mismatch:{sorted(observed)}")
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        protocol_core_sha256=expected,
        core_lock_file_sha256=sha256_file(path),
        checked_core_files=len(payload.get("files", [])),
    )


def validate_final_lock(root: Path) -> dict[str, Any]:
    path = root / "PROTOCOL_LOCK.json"
    if not path.is_file():
        return gate(NOT_READY, ["PROTOCOL_LOCK.json_missing"])
    payload = read_json(path)
    reasons: list[str] = []
    if payload.get("status") != "LOCKED":
        reasons.append("final_lock_status_not_locked")
    core_path = root / "PROTOCOL_CORE_LOCK.json"
    if not core_path.is_file() or sha256_file(core_path) != payload.get("core_lock_sha256"):
        reasons.append("core_lock_file_sha256_mismatch")
    manifest_path = root / "manifests/docking_jobs.tsv"
    if not manifest_path.is_file() or sha256_file(manifest_path) != payload.get("job_manifest_sha256"):
        reasons.append("job_manifest_sha256_mismatch")
    drifted: list[str] = []
    for record in payload.get("files", []):
        relative = str(record.get("path", ""))
        file_path = root / relative
        if not relative or not file_path.is_file() or sha256_file(file_path) != record.get("sha256"):
            drifted.append(relative or "MISSING_PATH")
    if drifted:
        reasons.append(f"final_protocol_files_drifted:{','.join(sorted(drifted))}")
    return gate(
        PASS if not reasons else FAIL,
        reasons,
        final_lock_file_sha256=sha256_file(path),
        protocol_lock_sha256=payload.get("protocol_lock_sha256", ""),
        checked_final_files=len(payload.get("files", [])),
    )


def validate_job_manifest(protocol: dict[str, Any], rows: list[dict[str, str]], expected_total_jobs: int | None) -> dict[str, Any]:
    if not rows:
        return gate(NOT_READY, ["job_manifest_missing_or_empty"])
    reasons: list[str] = []
    expected = expected_total_jobs or int(protocol["docking"]["expected_total_jobs"])
    if len(rows) != expected:
        reasons.append(f"expected_{expected}_jobs_got_{len(rows)}")
    job_ids = [row.get("job_id", "") for row in rows]
    if "" in job_ids or len(set(job_ids)) != len(job_ids):
        reasons.append("job_ids_blank_or_duplicate")
    if len({row.get("job_hash", "") for row in rows}) != len(rows):
        reasons.append("job_hashes_blank_or_duplicate")
    counts = Counter(row.get("entity_type", "") for row in rows)
    full_contract = expected == int(protocol["docking"]["expected_total_jobs"])
    if full_contract and counts != Counter({"control": 282, "candidate": 768}):
        reasons.append(f"entity_type_counts:{dict(counts)}")
    if full_contract and (any(row["entity_type"] != "control" for row in rows[:282]) or any(row["entity_type"] != "candidate" for row in rows[282:])):
        reasons.append("controls_not_scheduled_first")
    conformations = set(protocol["references"]["conformations"])
    seeds = {str(seed) for seed in protocol["docking"]["seeds"]}
    matrix: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        matrix[row["entity_id"]].add((row["conformation"], row["seed"]))
        if row["conformation"] not in conformations or row["seed"] not in seeds:
            reasons.append(f"invalid_conformation_or_seed:{row['job_id']}")
        if row.get("receptor_chain") != "T" or row.get("ligand_chain") != "L" or row.get("vhh_chain") != "A":
            reasons.append(f"bad_chain_contract:{row['job_id']}")
        if row.get("numbering") != "UniProt_Q6DKI7":
            reasons.append(f"bad_numbering:{row['job_id']}")
        if row["entity_type"] == "control" and not row.get("control_class"):
            reasons.append(f"unlabeled_control:{row['job_id']}")
    expected_matrix = {(conformation, seed) for conformation in conformations for seed in seeds}
    for entity, observed in sorted(matrix.items()):
        if observed != expected_matrix:
            reasons.append(f"incomplete_2x3_matrix:{entity}")
    return gate(PASS if not reasons else FAIL, reasons, job_count=len(rows), entity_count=len(matrix), counts=dict(counts))


def validate_rendered_configs(protocol: dict[str, Any], rows: list[dict[str, str]], interface_gate: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return gate(NOT_READY, ["job_manifest_missing_or_empty"])
    reasons: list[str] = []
    anchors = set(interface_gate.get("anchors", []))
    holdouts = set(interface_gate.get("holdouts", []))
    for row in rows:
        try:
            cfg = render_cfg_from_job(row)
            restraints = render_restraints_from_job(row)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            reasons.append(f"cannot_render_frozen_job:{row.get('job_id', '')}:{exc}")
            continue
        seed_token = f"iniseed = {row['seed']}"
        if cfg.count(seed_token) != 4:
            reasons.append(f"four_explicit_seeds_missing:{row['job_id']}")
        if cfg.count('ambig_fname = "data/air.tbl"') != 3:
            reasons.append(f"air_not_loaded_by_all_docking_modules:{row['job_id']}")
        if sha256_text(cfg) != row.get("cfg_hash"):
            reasons.append(f"cfg_hash_mismatch:{row['job_id']}")
        if sha256_text(restraints) != row.get("restraint_hash"):
            reasons.append(f"restraint_hash_mismatch:{row['job_id']}")
        if any(f"(resi {position} and segid T)" not in restraints for position in anchors):
            reasons.append(f"anchor_missing_from_air:{row['job_id']}")
        if any(f"(resi {position} and segid T)" in restraints for position in holdouts):
            reasons.append(f"holdout_leaked_into_air:{row['job_id']}")
        try:
            basis = json.loads(row.get("job_hash_basis", ""))
        except json.JSONDecodeError:
            reasons.append(f"job_hash_basis_invalid:{row['job_id']}")
            continue
        if str(basis.get("seed")) != row["seed"] or sha256_text(row["job_hash_basis"]) != row.get("job_hash"):
            reasons.append(f"job_hash_not_seed_auditable:{row['job_id']}")
    return gate(PASS if not reasons else FAIL, reasons, checked_jobs=len(rows))


def evaluate(
    protocol_path: Path,
    jobs_path: Path,
    out_path: Path | None = None,
    expected_total_jobs: int | None = None,
) -> dict[str, Any]:
    root = protocol_path.resolve().parents[1]
    protocol = read_json(protocol_path)
    rows = load_rows(jobs_path)
    interface = validate_interface(protocol, root)
    gates = {
        "interface_split": interface,
        "normalized_references": validate_references(protocol, root, interface),
        "core_lock": validate_core_lock(root, rows),
        "final_lock": validate_final_lock(root),
        "job_manifest": validate_job_manifest(protocol, rows, expected_total_jobs),
        "rendered_cfg_and_air": validate_rendered_configs(protocol, rows, interface),
    }
    payload = {
        "status": overall_status(gates),
        "protocol_id": protocol.get("protocol_id"),
        "protocol_file_sha256": sha256_file(protocol_path),
        "job_manifest_sha256": sha256_file(jobs_path) if jobs_path.is_file() else "",
        "job_set_hash": sha256_text("\n".join(sorted(row.get("job_hash", "") for row in rows))) if rows else "",
        "job_count": len(rows),
        "gates": gates,
    }
    if out_path is not None:
        write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="config/protocol_spec.json")
    parser.add_argument("--jobs", default="manifests/docking_jobs.tsv")
    parser.add_argument("--out", default="reports/PROTOCOL_VALIDATION.json")
    parser.add_argument("--expected-total-jobs", type=int)
    args = parser.parse_args(argv)
    payload = evaluate(Path(args.protocol), Path(args.jobs), Path(args.out), args.expected_total_jobs)
    print(json.dumps({"status": payload["status"], "out": str(args.out)}, sort_keys=True))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
