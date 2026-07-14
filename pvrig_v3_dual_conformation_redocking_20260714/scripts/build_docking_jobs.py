#!/usr/bin/env python3
"""Build the frozen 1050-job independent dual-conformation docking manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from common import canonical_json, is_standard_atom_line, project_root, read_json, read_tsv, sha256_file, sha256_text, write_json, write_tsv


CONFORMATIONS = ("8x6b", "9e6y")
JOB_FIELDS = [
    "job_id",
    "priority",
    "entity_type",
    "entity_id",
    "control_class",
    "expected_behavior",
    "conformation",
    "seed",
    "sequence_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr_residues",
    "monomer_source",
    "monomer_source_kind",
    "monomer_source_chain",
    "receptor_pdb",
    "receptor_chain",
    "ligand_chain",
    "vhh_chain",
    "numbering",
    "cfg_hash",
    "restraint_hash",
    "protocol_core_sha256",
    "protocol_hash",
    "job_hash",
    "job_hash_basis",
]


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def protocol() -> dict[str, Any]:
    return read_json(root() / "config/protocol_spec.json")


def protocol_core_sha256() -> str:
    path = root() / "PROTOCOL_CORE_LOCK.json"
    if not path.is_file():
        raise RuntimeError("PROTOCOL_CORE_LOCK.json is not available; freeze the core protocol first")
    payload = read_json(path)
    if payload.get("status") != "CORE_LOCKED":
        raise RuntimeError("PROTOCOL_CORE_LOCK.json status is not CORE_LOCKED")
    value = str(payload.get("protocol_core_sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(f"invalid protocol_core_sha256 in {path}")
    return value


def parse_range(spec: str) -> list[int]:
    residues: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token[1:]:
            split_at = token[1:].index("-") + 1
            start, end = int(token[:split_at]), int(token[split_at + 1 :])
            if start > end:
                start, end = end, start
            residues.update(range(start, end + 1))
        else:
            residues.add(int(token))
    if not residues:
        raise RuntimeError(f"empty residue range: {spec!r}")
    return sorted(residues)


def unique_sequence_range(sequence: str, cdr: str, label: str, entity_id: str) -> str:
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise RuntimeError(f"{entity_id}: {label} absent or non-unique in sequence")
    return f"{start + 1}-{start + len(cdr)}"


def anchor_positions() -> list[int]:
    path = root() / "inputs/normalized/interface_hotspots_uniprot.tsv"
    rows = read_tsv(path)
    positions = [int(row["uniprot_position"]) for row in rows if row["restraint_role"] == "AIR_ANCHOR"]
    if len(positions) != 12 or len(set(positions)) != 12:
        raise RuntimeError(f"expected 12 unique AIR anchors, found {positions}")
    return positions


def render_restraints(cdr_residues: list[int], core_hash: str) -> str:
    anchors = anchor_positions()
    lines = [
        f"! protocol_core_sha256={core_hash}",
        "! VHH CDR residues (chain A) to 12 UniProt-numbered PVRIG AIR anchors (chain T)",
        "! 11 holdout interface residues are deliberately absent",
    ]
    for residue in cdr_residues:
        lines.append(f"assign (resi {residue} and segid A)")
        lines.append("(")
        for index, anchor in enumerate(anchors):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {anchor} and segid T)")
        lines.append(") 2.0 2.0 0.0\n")
    return "\n".join(lines) + "\n"


def cfg_payload(conformation: str, seed: int, core_hash: str) -> dict[str, Any]:
    docking = protocol()["docking"]
    return {
        "protocol_core_sha256": core_hash,
        "conformation": conformation,
        "seed": int(seed),
        "ncores": int(docking["ncores"]),
        "sampling": int(docking["sampling"]),
        "select": int(docking["seletop_select"]),
        "top_models": int(docking["seletopclusts_top_models"]),
        "rigidbody_tolerance": int(docking["rigidbody_tolerance"]),
        "flexref_tolerance": int(docking["flexref_tolerance"]),
        "randremoval": bool(docking["randremoval"]),
        "npart": int(docking["npart"]),
    }


def render_cfg(conformation: str, seed: int, core_hash: str) -> str:
    cfg = cfg_payload(conformation, seed, core_hash)
    boolean = "true" if cfg["randremoval"] else "false"
    return f'''# Frozen PVRIG V3 {conformation} independent docking config
# protocol_core_sha256={core_hash}
run_dir = "haddock_run"
mode = "local"
ncores = {cfg["ncores"]}

molecules = [
    "data/vhh_chainA.pdb",
    "data/pvrig_chainT.pdb",
]

[topoaa]
iniseed = {seed}

[rigidbody]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {cfg["rigidbody_tolerance"]}
sampling = {cfg["sampling"]}
randremoval = {boolean}
npart = {cfg["npart"]}

[seletop]
select = {cfg["select"]}

[flexref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {cfg["flexref_tolerance"]}
randremoval = {boolean}
npart = {cfg["npart"]}

[emref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
randremoval = {boolean}
npart = {cfg["npart"]}

[clustfcc]
min_population = 1

[seletopclusts]
top_models = {cfg["top_models"]}
'''


def available_residue_numbers(path: Path, chain: str) -> set[int]:
    return {
        int(line[22:26])
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if is_standard_atom_line(line) and line[21] == chain
    }


def load_candidates() -> list[dict[str, str]]:
    path = root() / "inputs/candidates_128.tsv"
    rows = read_tsv(path)
    if len(rows) != int(protocol()["candidate_panel"]["expected_count"]):
        raise RuntimeError(f"candidate panel expected 128 rows, found {len(rows)}")
    monomer_rows = read_tsv(root() / "inputs/candidate_monomers_manifest.tsv")
    monomers = {row["candidate_id"]: row for row in monomer_rows}
    if len(monomers) != len(rows):
        raise RuntimeError("candidate monomer manifest does not cover the fixed128 panel")
    entities: list[dict[str, str]] = []
    for row in rows:
        entity_id = row["candidate_id"]
        if entity_id not in monomers:
            raise RuntimeError(f"candidate monomer missing from freeze manifest: {entity_id}")
        monomer_row = monomers[entity_id]
        monomer = root() / monomer_row["frozen_monomer_path"]
        if not monomer.is_file() or sha256_file(monomer) != monomer_row["sha256"]:
            raise RuntimeError(f"frozen candidate monomer missing or hash mismatch: {monomer}")
        if monomer_row["sequence_sha256"] != row["sequence_sha256"]:
            raise RuntimeError(f"candidate monomer sequence hash mismatch: {entity_id}")
        sequence = row["sequence"]
        ranges = {
            label: unique_sequence_range(sequence, row[label], label, entity_id)
            for label in ("cdr1", "cdr2", "cdr3")
        }
        requested = set().union(*(set(parse_range(value)) for value in ranges.values()))
        available = available_residue_numbers(monomer, monomer_row["source_chain"])
        if not requested.issubset(available):
            raise RuntimeError(f"candidate monomer lacks CDR residues {sorted(requested - available)}: {entity_id}")
        entities.append(
            {
                "entity_id": entity_id,
                "control_class": "",
                "expected_behavior": "CANDIDATE_UNKNOWN",
                "sequence_sha256": row["sequence_sha256"],
                **{f"{label}_range": value for label, value in ranges.items()},
                "cdr_residues": ",".join(map(str, sorted(requested))),
                "monomer_source": monomer_row["frozen_monomer_path"],
                "monomer_source_kind": "frozen_local_candidate",
                "monomer_source_chain": monomer_row["source_chain"],
            }
        )
    if len({row["entity_id"] for row in entities}) != len(entities):
        raise RuntimeError("duplicate candidate entity IDs")
    return sorted(entities, key=lambda row: row["entity_id"])


def load_controls() -> list[dict[str, str]]:
    path = root() / "inputs/calibration_controls_47.tsv"
    rows = read_tsv(path)
    if len(rows) != int(protocol()["controls"]["expected_count"]):
        raise RuntimeError(f"control panel expected 47 rows, found {len(rows)}")
    entities: list[dict[str, str]] = []
    for row in rows:
        monomer = root() / row["frozen_monomer_path"]
        if not monomer.is_file() or sha256_file(monomer) != row["sha256"]:
            raise RuntimeError(f"frozen control monomer missing or hash mismatch: {monomer}")
        available_residues = available_residue_numbers(monomer, row["source_chain"])
        requested_cdr_residues = (
            set(parse_range(row["cdr1_range"]))
            | set(parse_range(row["cdr2_range"]))
            | set(parse_range(row["cdr3_range"]))
        )
        active_cdr_residues = sorted(requested_cdr_residues & available_residues)
        if not active_cdr_residues:
            raise RuntimeError(f"no CDR residues found in frozen control monomer: {monomer}")
        entities.append(
            {
                "entity_id": row["control_id"],
                "control_class": row["control_class"],
                "expected_behavior": row["expected_behavior"],
                "sequence_sha256": sha256_text(row.get("sequence", "")) if row.get("sequence") else "",
                "cdr1_range": row["cdr1_range"],
                "cdr2_range": row["cdr2_range"],
                "cdr3_range": row["cdr3_range"],
                "cdr_residues": ",".join(map(str, active_cdr_residues)),
                "monomer_source": row["frozen_monomer_path"],
                "monomer_source_kind": "frozen_local_control",
                "monomer_source_chain": row["source_chain"],
            }
        )
    if len({row["entity_id"] for row in entities}) != len(entities):
        raise RuntimeError("duplicate control entity IDs")
    return sorted(entities, key=lambda row: row["entity_id"])


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def make_job(entity_type: str, entity: dict[str, str], conformation: str, seed: int, priority: int) -> dict[str, str]:
    spec = protocol()
    core_hash = protocol_core_sha256()
    if entity.get("cdr_residues"):
        cdr_residues = [int(value) for value in entity["cdr_residues"].split(",") if value]
    else:
        cdr_residues = sorted(
            set(parse_range(entity["cdr1_range"]))
            | set(parse_range(entity["cdr2_range"]))
            | set(parse_range(entity["cdr3_range"]))
        )
    cfg_text = render_cfg(conformation, seed, core_hash)
    restraint_text = render_restraints(cdr_residues, core_hash)
    cfg_hash = sha256_text(cfg_text)
    restraint_hash = sha256_text(restraint_text)
    basis = {
        "entity_type": entity_type,
        "entity_id": entity["entity_id"],
        "conformation": conformation,
        "seed": seed,
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_core_sha256": core_hash,
    }
    basis_text = canonical_json(basis)
    job_hash = sha256_text(basis_text)
    receptor = spec["references"]["conformations"][conformation]["normalized_receptor_pdb"]
    if not (root() / receptor).is_file():
        raise RuntimeError(f"normalized receptor missing: {receptor}")
    return {
        "job_id": f"{entity_type.upper()}_{safe_id(entity['entity_id'])}_{conformation}_s{seed}_{job_hash[:12]}",
        "priority": str(priority),
        "entity_type": entity_type,
        "entity_id": entity["entity_id"],
        "control_class": entity["control_class"],
        "expected_behavior": entity["expected_behavior"],
        "conformation": conformation,
        "seed": str(seed),
        "sequence_sha256": entity["sequence_sha256"],
        "cdr1_range": entity["cdr1_range"],
        "cdr2_range": entity["cdr2_range"],
        "cdr3_range": entity["cdr3_range"],
        "cdr_residues": ",".join(map(str, cdr_residues)),
        "monomer_source": entity["monomer_source"],
        "monomer_source_kind": entity["monomer_source_kind"],
        "monomer_source_chain": entity["monomer_source_chain"],
        "receptor_pdb": receptor,
        "receptor_chain": spec["references"]["receptor_chain"],
        "ligand_chain": spec["references"]["ligand_chain"],
        "vhh_chain": "A",
        "numbering": spec["references"]["numbering"],
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_core_sha256": core_hash,
        "protocol_hash": core_hash,
        "job_hash": job_hash,
        "job_hash_basis": basis_text,
    }


def render_cfg_from_job(job: dict[str, str]) -> str:
    return render_cfg(job["conformation"], int(job["seed"]), job["protocol_core_sha256"])


def render_restraints_from_job(job: dict[str, str]) -> str:
    residues = [int(value) for value in job["cdr_residues"].split(",") if value]
    return render_restraints(residues, job["protocol_core_sha256"])


def build_jobs() -> list[dict[str, str]]:
    seeds = [int(seed) for seed in protocol()["docking"]["seeds"]]
    jobs: list[dict[str, str]] = []
    priority = 0
    for entity_type, entities in (("control", load_controls()), ("candidate", load_candidates())):
        for entity in entities:
            for conformation in CONFORMATIONS:
                for seed in seeds:
                    priority += 1
                    jobs.append(make_job(entity_type, entity, conformation, seed, priority))
    expected = int(protocol()["docking"]["expected_total_jobs"])
    if len(jobs) != expected:
        raise RuntimeError(f"expected {expected} jobs, built {len(jobs)}")
    if len({job["job_id"] for job in jobs}) != expected or len({job["job_hash"] for job in jobs}) != expected:
        raise RuntimeError("job IDs and hashes must be unique")
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="manifests/docking_jobs.tsv")
    parser.add_argument("--summary", default="reports/job_manifest_summary.json")
    parser.add_argument("--smoke-output", default="manifests/smoke_jobs.tsv")
    args = parser.parse_args(argv)
    try:
        jobs = build_jobs()
        out_path = root() / args.output
        write_tsv(out_path, jobs, JOB_FIELDS)
        docking = protocol()["docking"]
        smoke_entities = {docking["smoke_control_id"], docking["smoke_candidate_id"]}
        smoke_jobs = [
            job
            for job in jobs
            if job["entity_id"] in smoke_entities and int(job["seed"]) == int(docking["smoke_seed"])
        ]
        if len(smoke_jobs) != int(docking["expected_smoke_jobs"]):
            raise RuntimeError(f"expected {docking['expected_smoke_jobs']} smoke jobs, found {len(smoke_jobs)}")
        smoke_path = root() / args.smoke_output
        smoke_fields = ["job_id", "entity_type", "entity_id", "conformation", "seed", "job_hash"]
        write_tsv(smoke_path, smoke_jobs, smoke_fields)
        write_json(
            root() / args.summary,
            {
                "status": "OK",
                "job_count": len(jobs),
                "control_jobs": sum(job["entity_type"] == "control" for job in jobs),
                "candidate_jobs": sum(job["entity_type"] == "candidate" for job in jobs),
                "protocol_core_sha256": jobs[0]["protocol_core_sha256"],
                "output": args.output,
                "sha256": sha256_file(out_path),
                "smoke_output": args.smoke_output,
                "smoke_job_count": len(smoke_jobs),
                "smoke_sha256": sha256_file(smoke_path),
            },
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        waiting = "PROTOCOL_CORE_LOCK" in str(exc)
        write_json(root() / args.summary, {"status": "WAITING" if waiting else "ERROR", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
