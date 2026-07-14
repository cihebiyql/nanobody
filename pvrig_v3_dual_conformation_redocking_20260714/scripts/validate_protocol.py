#!/usr/bin/env python3
"""Validate frozen protocol/job artifacts before V3 redocking execution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import canonical_json, read_json, sha256_file, sha256_text, write_json

PASS = "PASS"
FAIL = "FAIL"
NOT_READY = "NOT_READY"
VALID_STATES = {PASS, FAIL, NOT_READY}


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        payload = read_json(path)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("jobs") or payload.get("rows") or []
        else:
            rows = []
        return [{str(k): "" if v is None else str(v) for k, v in row.items()} for row in rows]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{k: ("" if v is None else v) for k, v in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def gate(status: str, reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    if status not in VALID_STATES:
        raise ValueError(status)
    payload: dict[str, Any] = {"status": status, "reasons": sorted(reasons or [])}
    payload.update(extra)
    return payload


def overall_status(gates: dict[str, dict[str, Any]], readiness_gates: set[str] | None = None) -> str:
    readiness_gates = readiness_gates or set()
    if any(item["status"] == FAIL for item in gates.values()):
        return FAIL
    if any(item["status"] == NOT_READY for name, item in gates.items() if not readiness_gates or name in readiness_gates):
        return NOT_READY
    if any(item["status"] == NOT_READY for item in gates.values()):
        return NOT_READY
    return PASS


def hard_interface_rows(protocol: dict[str, Any], root: Path) -> list[dict[str, str]]:
    source = root / protocol["interface"]["source"]
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row.get("design_use") != "soft_hint_only_not_hard_constraint"]


def validate_interface(protocol: dict[str, Any], root: Path) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        rows = hard_interface_rows(protocol, root)
    except OSError as exc:
        return gate(FAIL, [f"interface_source_unreadable:{exc}"])
    unique_positions = {(row.get("uniprot_accession"), row.get("uniprot_position")) for row in rows}
    expected = int(protocol["interface"]["unique_interface_residue_count"])
    if len(unique_positions) != expected:
        reasons.append(f"expected_{expected}_unique_interface_residues_got_{len(unique_positions)}")
    accessions = {row.get("uniprot_accession") for row in rows}
    if accessions != {"Q6DKI7"}:
        reasons.append("non_q6dki7_uniprot_accession_present")
    sorted_rows = sorted(rows, key=lambda row: (int(row.get("alignment_col") or 0), row.get("hotspot_id", "")))
    anchors = {row.get("hotspot_id") for idx, row in enumerate(sorted_rows) if idx % 2 == 0}
    holdouts = {row.get("hotspot_id") for idx, row in enumerate(sorted_rows) if idx % 2 == 1}
    if len(anchors) != int(protocol["interface"]["air_anchor_count"]):
        reasons.append(f"air_anchor_count_{len(anchors)}")
    if len(holdouts) != int(protocol["interface"]["holdout_count"]):
        reasons.append(f"holdout_count_{len(holdouts)}")
    if anchors & holdouts:
        reasons.append("anchor_holdout_overlap")
    return gate(PASS if not reasons else FAIL, reasons, hard_rows=len(rows), anchors=len(anchors), holdouts=len(holdouts))


def normalize_text(text: str) -> str:
    return text.replace("\\n", "\n")


def cfg_content(row: dict[str, str], root: Path) -> str:
    if row.get("cfg_text"):
        return normalize_text(row["cfg_text"])
    if row.get("cfg_path"):
        path = Path(row["cfg_path"])
        if not path.is_absolute():
            path = root / path
        return path.read_text(encoding="utf-8")
    return ""


def has_hetatm(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return any(line.startswith("HETATM") for line in handle)
    except OSError:
        return False


def validate_standard_atoms(rows: list[dict[str, str]], root: Path) -> dict[str, Any]:
    paths = sorted({row.get("pdb_path") or row.get("standardized_pdb") or "" for row in rows if row.get("pdb_path") or row.get("standardized_pdb")})
    if not paths:
        return gate(NOT_READY, ["no_standardized_pdb_paths_in_job_manifest"])
    bad: list[str] = []
    missing: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            missing.append(raw)
        elif has_hetatm(path):
            bad.append(raw)
    reasons = [f"missing_pdb:{item}" for item in missing] + [f"hetatm_present:{item}" for item in bad]
    return gate(PASS if not reasons else FAIL, reasons, checked_paths=len(paths))


def validate_job_manifest(protocol: dict[str, Any], rows: list[dict[str, str]], expected_total_jobs: int | None, root: Path) -> dict[str, Any]:
    if not rows:
        return gate(NOT_READY, ["job_manifest_missing_or_empty"])
    reasons: list[str] = []
    job_ids = [row.get("job_id", "") for row in rows]
    if any(not job_id for job_id in job_ids):
        reasons.append("blank_job_id")
    if len(set(job_ids)) != len(job_ids):
        reasons.append("duplicate_job_id")
    expected = expected_total_jobs if expected_total_jobs is not None else int(protocol["docking"]["expected_total_jobs"])
    if len(rows) != expected:
        reasons.append(f"expected_{expected}_jobs_got_{len(rows)}")
    conformations = set(protocol["references"]["conformations"].keys())
    seeds = {str(seed) for seed in protocol["docking"]["seeds"]}
    by_entity_seed: dict[tuple[str, str], set[str]] = defaultdict(set)
    hashes_by_entity_seed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        entity = row.get("entity_id") or row.get("candidate_id") or row.get("control_id") or ""
        conformation = row.get("conformation", "")
        seed = row.get("seed", "")
        if conformation not in conformations:
            reasons.append(f"invalid_conformation:{row.get('job_id', '')}:{conformation}")
        if seed not in seeds:
            reasons.append(f"invalid_seed:{row.get('job_id', '')}:{seed}")
        if row.get("receptor_chain") and row["receptor_chain"] != protocol["references"]["receptor_chain"]:
            reasons.append(f"bad_receptor_chain:{row.get('job_id', '')}")
        if row.get("ligand_chain") and row["ligand_chain"] != protocol["references"]["ligand_chain"]:
            reasons.append(f"bad_ligand_chain:{row.get('job_id', '')}")
        if row.get("numbering") and row["numbering"] != protocol["references"]["numbering"]:
            reasons.append(f"bad_numbering:{row.get('job_id', '')}")
        if entity and seed:
            by_entity_seed[(entity, seed)].add(conformation)
            if row.get("job_hash"):
                hashes_by_entity_seed[(entity, seed)].add(row["job_hash"])
    for key, seen in sorted(by_entity_seed.items()):
        if seen != conformations:
            reasons.append(f"missing_independent_conformation:{key[0]}:{key[1]}")
    for key, hashes in sorted(hashes_by_entity_seed.items()):
        if len(hashes) < len(conformations):
            reasons.append(f"nonindependent_job_hash:{key[0]}:{key[1]}")
    return gate(PASS if not reasons else FAIL, reasons, job_count=len(rows), unique_jobs=len(set(job_ids)))


def validate_seed_hash(rows: list[dict[str, str]], root: Path) -> dict[str, Any]:
    if not rows:
        return gate(NOT_READY, ["job_manifest_missing_or_empty"])
    reasons: list[str] = []
    cfg_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        job_id = row.get("job_id", "")
        seed = row.get("seed", "")
        try:
            content = cfg_content(row, root)
        except OSError as exc:
            reasons.append(f"cfg_unreadable:{job_id}:{exc}")
            continue
        if not content:
            reasons.append(f"cfg_missing:{job_id}")
            continue
        if seed and seed not in content:
            reasons.append(f"seed_missing_from_cfg:{job_id}")
        cfg_hash = row.get("cfg_hash", "")
        if cfg_hash:
            actual = sha256_text(content)
            if actual != cfg_hash:
                reasons.append(f"cfg_hash_mismatch:{job_id}")
            entity = row.get("entity_id") or row.get("candidate_id") or row.get("control_id") or ""
            conformation = row.get("conformation", "")
            cfg_hashes[(entity, conformation)].add(cfg_hash)
        else:
            reasons.append(f"cfg_hash_missing:{job_id}")
        if row.get("job_hash") and seed and seed not in (row.get("job_hash_basis") or row.get("job_id", "") or content):
            # A cryptographic hash cannot be reversed; require an auditable basis when job_id does not carry the seed.
            reasons.append(f"seed_not_auditable_in_job_hash_basis:{job_id}")
    for key, hashes in sorted(cfg_hashes.items()):
        if len(hashes) < 3:
            reasons.append(f"cfg_hash_not_seed_specific:{key[0]}:{key[1]}")
    return gate(PASS if not reasons else FAIL, reasons)


def evaluate(protocol_path: Path, jobs_path: Path, out_path: Path | None = None, expected_total_jobs: int | None = None) -> dict[str, Any]:
    root = protocol_path.resolve().parents[1]
    protocol = read_json(protocol_path)
    rows = load_rows(jobs_path)
    gates = {
        "interface_split": validate_interface(protocol, root),
        "job_manifest": validate_job_manifest(protocol, rows, expected_total_jobs, root),
        "standard_atom_only": validate_standard_atoms(rows, root),
        "seed_in_cfg_hash": validate_seed_hash(rows, root),
    }
    status = overall_status(gates, {"job_manifest", "standard_atom_only", "seed_in_cfg_hash"})
    protocol_hash = sha256_file(protocol_path)
    job_hashes = sorted(row.get("job_hash", "") for row in rows if row.get("job_hash"))
    payload = {
        "status": status,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_hash": protocol_hash,
        "job_count": len(rows),
        "job_set_hash": sha256_text("\n".join(job_hashes)) if job_hashes else "",
        "gates": gates,
    }
    if out_path is not None:
        write_json(out_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="config/protocol_spec.json")
    parser.add_argument("--jobs", default="reports/job_manifest.tsv")
    parser.add_argument("--out", default="reports/PROTOCOL_VALIDATION.json")
    parser.add_argument("--expected-total-jobs", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = evaluate(Path(args.protocol), Path(args.jobs), Path(args.out), args.expected_total_jobs)
    print(json.dumps({"status": payload["status"], "out": str(args.out)}, sort_keys=True))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
