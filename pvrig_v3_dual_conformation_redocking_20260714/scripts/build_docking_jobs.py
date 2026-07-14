#!/usr/bin/env python3
"""Build the deterministic 1050-row docking job manifest."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

from common import canonical_json, project_root, read_json, read_tsv, sha256_file, sha256_text, write_json, write_tsv

CONFORMATIONS = ("8x6b", "9e6y")
JOB_FIELDS = [
    "job_id",
    "priority",
    "entity_type",
    "entity_id",
    "conformation",
    "seed",
    "monomer_path",
    "source_path",
    "receptor_pdb",
    "cfg_hash",
    "restraint_hash",
    "protocol_core_sha256",
    "protocol_hash",
    "job_hash",
]
CANDIDATE_MANIFESTS = (
    "inputs/candidate_panel_128.tsv",
    "inputs/candidates_128.tsv",
    "manifests/candidate_panel_128.tsv",
)
REMOTE_CANDIDATE_ROOT = Path("/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712/docking/haddock")


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def protocol() -> dict[str, Any]:
    return read_json(root() / "config" / "protocol_spec.json")


def protocol_core_sha256() -> str:
    path = root() / "PROTOCOL_CORE_LOCK.json"
    if not path.exists():
        raise RuntimeError("PROTOCOL_CORE_LOCK.json is not available yet; waiting for main agent to freeze protocol_core_sha256")
    value = str(read_json(path).get("protocol_core_sha256", "")).strip()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise RuntimeError(f"invalid protocol_core_sha256 in {path}")
    return value.lower()


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def anchor_restraints(conformation: str, core_hash: str) -> str:
    rows = [r for r in read_csv_dicts(root() / "inputs" / "source" / "PVRIG_hotspot_set_v1.csv") if not r["hotspot_id"].startswith("soft_hint")]
    rows.sort(key=lambda r: int(r["alignment_col"]))
    anchors = rows[::2]
    if len(anchors) != 12:
        raise RuntimeError(f"expected 12 AIR anchors after even-index split, found {len(anchors)}")
    ref_col = "pdb_8x6b_ref" if conformation == "8x6b" else "pdb_9e6y_ref"
    lines = [f"! protocol_core_sha256={core_hash}", f"! {conformation} 12-anchor AIR; holdouts excluded from restraints"]
    for row in anchors:
        ref = row[ref_col].split(":")
        if len(ref) < 2:
            raise RuntimeError(f"bad reference residue for {row['hotspot_id']}: {row[ref_col]}")
        chain = "T"
        resid = "".join(ch for ch in ref[1] if ch.isdigit())
        lines.append(f"assign (segid {chain} and resid {resid}) (segid L) 2.0 2.0 0.0 ! {row['hotspot_id']}")
    return "\n".join(lines) + "\n"


def cfg_payload(conformation: str, seed: str, core_hash: str) -> dict[str, Any]:
    spec = protocol()
    docking = spec["docking"]
    return {
        "protocol_core_sha256": core_hash,
        "conformation": conformation,
        "modules": {
            "topoaa": {"iniseed": int(seed)},
            "rigidbody": {"iniseed": int(seed), "sampling": docking["sampling"], "tolerance": docking["rigidbody_tolerance"], "randremoval": True, "npart": docking["npart"], "ncores": docking["ncores"]},
            "flexref": {"iniseed": int(seed), "tolerance": docking["flexref_tolerance"], "ncores": docking["ncores"]},
            "emref": {"iniseed": int(seed), "ncores": docking["ncores"]},
            "seletop": {"select": docking["seletop_select"]},
            "seletopclusts": {"top_models": docking["seletopclusts_top_models"]},
        },
    }


def find_candidate_manifest() -> Path | None:
    for rel in CANDIDATE_MANIFESTS:
        path = root() / rel
        if path.exists():
            return path
    return None


def candidate_path(candidate_id: str) -> Path:
    return REMOTE_CANDIDATE_ROOT / candidate_id / "data" / f"{candidate_id}_vhh_chainA.pdb"


def load_candidates() -> list[dict[str, str]]:
    path = find_candidate_manifest()
    if path is None:
        searched = ", ".join(CANDIDATE_MANIFESTS)
        raise RuntimeError(f"candidate panel manifest is not available yet; waiting for main agent to generate one of: {searched}")
    rows = read_tsv(path)
    if len(rows) != int(protocol()["candidate_panel"]["expected_count"]):
        raise RuntimeError(f"candidate panel expected 128 rows, found {len(rows)} in {path}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        cid = (row.get("candidate_id") or row.get("entity_id") or row.get("id") or "").strip()
        if not cid:
            raise RuntimeError(f"candidate manifest row lacks candidate_id: {row}")
        if cid in seen:
            raise RuntimeError(f"duplicate candidate_id {cid}")
        seen.add(cid)
        monomer = Path((row.get("monomer_path") or row.get("source_path") or "").strip()) if (row.get("monomer_path") or row.get("source_path")) else candidate_path(cid)
        if not monomer.exists():
            raise RuntimeError(f"candidate monomer missing for {cid}: {monomer}")
        out.append({"entity_id": cid, "monomer_path": str(monomer), "source_path": str(monomer)})
    return sorted(out, key=lambda r: r["entity_id"])


def load_controls() -> list[dict[str, str]]:
    path = root() / "inputs" / "calibration_controls_47.tsv"
    if not path.exists():
        raise RuntimeError("control manifest missing; run scripts/build_calibration_manifest.py first")
    rows = read_tsv(path)
    if len(rows) != int(protocol()["controls"]["expected_count"]):
        raise RuntimeError(f"control manifest expected 47 rows, found {len(rows)}")
    return [
        {"entity_id": row["control_id"], "monomer_path": str(root() / row["frozen_monomer_path"]), "source_path": row["source_path"]}
        for row in rows
    ]


def make_job(entity_type: str, entity: dict[str, str], conformation: str, seed: int, priority: int) -> dict[str, str]:
    spec = protocol()
    core_hash = protocol_core_sha256()
    cfg_hash = sha256_text(canonical_json(cfg_payload(conformation, str(seed), core_hash)))
    restraint_hash = sha256_text(anchor_restraints(conformation, core_hash))
    protocol_hash = sha256_text(canonical_json({"protocol_core_sha256": core_hash, "protocol": spec, "cfg_hash": cfg_hash, "restraint_hash": restraint_hash}))
    key = {
        "entity_type": entity_type,
        "entity_id": entity["entity_id"],
        "conformation": conformation,
        "seed": seed,
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_core_sha256": core_hash,
        "protocol_hash": protocol_hash,
    }
    job_hash = sha256_text(canonical_json(key))
    job_id = f"{entity_type.upper()}_{entity['entity_id']}_{conformation}_s{seed}_{job_hash[:12]}"
    receptor = spec["references"]["conformations"][conformation]["source_pdb"]
    return {
        "job_id": job_id,
        "priority": str(priority),
        "entity_type": entity_type,
        "entity_id": entity["entity_id"],
        "conformation": conformation,
        "seed": str(seed),
        "monomer_path": entity["monomer_path"],
        "source_path": entity["source_path"],
        "receptor_pdb": receptor,
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_hash": protocol_hash,
        "job_hash": job_hash,
    }


def build_jobs() -> list[dict[str, str]]:
    spec = protocol()
    seeds = spec["docking"]["seeds"]
    jobs: list[dict[str, str]] = []
    priority = 0
    for entity in load_controls():
        for conformation in CONFORMATIONS:
            for seed in seeds:
                priority += 1
                jobs.append(make_job("control", entity, conformation, int(seed), priority))
    for entity in load_candidates():
        for conformation in CONFORMATIONS:
            for seed in seeds:
                priority += 1
                jobs.append(make_job("candidate", entity, conformation, int(seed), priority))
    expected = int(spec["docking"]["expected_total_jobs"])
    if len(jobs) != expected:
        raise RuntimeError(f"expected {expected} jobs, built {len(jobs)}")
    ids = [j["job_id"] for j in jobs]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate job_id generated")
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="manifests/docking_jobs.tsv")
    parser.add_argument("--summary", default="reports/job_manifest_summary.json")
    args = parser.parse_args(argv)
    try:
        jobs = build_jobs()
        out_path = root() / args.output
        write_tsv(out_path, jobs, JOB_FIELDS)
        summary = {
            "status": "OK",
            "job_count": len(jobs),
            "control_jobs": sum(1 for j in jobs if j["entity_type"] == "control"),
            "candidate_jobs": sum(1 for j in jobs if j["entity_type"] == "candidate"),
            "output": args.output,
            "sha256": sha256_file(out_path),
        }
        write_json(root() / args.summary, summary)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        waiting = "candidate panel" in str(exc) or "PROTOCOL_CORE_LOCK" in str(exc)
        write_json(root() / args.summary, {"status": "WAITING" if waiting else "ERROR", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
