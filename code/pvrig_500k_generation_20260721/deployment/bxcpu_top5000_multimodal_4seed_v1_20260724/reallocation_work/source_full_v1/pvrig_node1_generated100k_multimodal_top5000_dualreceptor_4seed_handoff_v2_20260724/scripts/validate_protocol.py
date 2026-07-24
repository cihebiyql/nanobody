#!/usr/bin/env python3
"""Validate a candidate-only PVRIG Docking manifest without 47-control gates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PASS = "PASS"
FAIL = "FAIL"
NOT_READY = "NOT_READY"
EXPECTED_CONFORMATIONS = {"8x6b", "9e6y"}
EXPECTED_SEEDS = {"917", "1931"}


def gate(status: str, reasons: Iterable[str], **details: Any) -> dict[str, Any]:
    return {"status": status, "reasons": list(reasons), **details}


def overall_status(gates: dict[str, dict[str, Any]]) -> str:
    states = {value.get("status") for value in gates.values()}
    if FAIL in states:
        return FAIL
    if NOT_READY in states:
        return NOT_READY
    return PASS


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate(
    protocol_path: Path,
    jobs_path: Path,
    output_path: Path,
    expected_total_jobs: int | None = None,
) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    root = protocol_path.parents[1]
    jobs_path = jobs_path.resolve() if jobs_path.is_absolute() else root / jobs_path
    output_path = output_path.resolve() if output_path.is_absolute() else root / output_path
    jobs = load_rows(jobs_path)
    expected = expected_total_jobs if expected_total_jobs is not None else len(jobs)
    gates: dict[str, dict[str, Any]] = {}

    if not protocol_path.is_file():
        gates["protocol_present"] = gate(NOT_READY, ["protocol_missing"])
        protocol: dict[str, Any] = {}
    else:
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        gates["protocol_present"] = gate(PASS, [])

    lock_path = root / "PROTOCOL_CORE_LOCK.json"
    if not lock_path.is_file():
        gates["core_lock"] = gate(NOT_READY, ["protocol_core_lock_missing"])
        core_hash = ""
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        core_hash = str(lock.get("protocol_core_sha256", ""))
        reasons = []
        if lock.get("status") != "CORE_LOCKED":
            reasons.append("core_lock_status_not_CORE_LOCKED")
        if len(core_hash) != 64:
            reasons.append("invalid_protocol_core_sha256")
        gates["core_lock"] = gate(
            FAIL if reasons else PASS,
            reasons,
            protocol_core_sha256=core_hash,
            protocol_core_lock_file_sha256=sha256_file(lock_path),
        )

    if not jobs:
        gates["manifest_shape"] = gate(NOT_READY, ["job_manifest_missing_or_empty"])
    else:
        required = {
            "job_id", "entity_type", "entity_id", "conformation", "seed",
            "sequence_sha256", "monomer_sha256", "cfg_hash", "restraint_hash",
            "protocol_core_sha256", "job_hash", "job_hash_basis",
        }
        missing = sorted(required - set(jobs[0]))
        reasons = []
        if missing:
            reasons.append(f"missing_fields:{','.join(missing)}")
        if len(jobs) != expected:
            reasons.append(f"expected_{expected}_jobs_got_{len(jobs)}")
        if len({row.get("job_id", "") for row in jobs}) != len(jobs):
            reasons.append("job_ids_blank_or_duplicate")
        if len({row.get("job_hash", "") for row in jobs}) != len(jobs):
            reasons.append("job_hashes_blank_or_duplicate")
        if {row.get("entity_type", "") for row in jobs} != {"candidate"}:
            reasons.append("manifest_is_not_candidate_only")
        if {row.get("conformation", "") for row in jobs} != EXPECTED_CONFORMATIONS:
            reasons.append("conformation_set_is_not_8x6b_9e6y")
        if {row.get("seed", "") for row in jobs} != EXPECTED_SEEDS:
            reasons.append("seed_set_is_not_917_1931")
        if core_hash and {row.get("protocol_core_sha256", "") for row in jobs} != {core_hash}:
            reasons.append("manifest_protocol_core_mismatch")
        gates["manifest_shape"] = gate(
            FAIL if reasons else PASS,
            reasons,
            expected_jobs=expected,
            observed_jobs=len(jobs),
        )

    pair_reasons: list[str] = []
    units: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    entities: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in jobs:
        units[(row.get("entity_id", ""), row.get("seed", ""))].append(row)
        entities[row.get("entity_id", "")].append(row)
    for key, rows in units.items():
        if len(rows) != 2 or {row.get("conformation", "") for row in rows} != EXPECTED_CONFORMATIONS:
            pair_reasons.append(f"candidate_seed_pair_incomplete:{key[0]}:{key[1]}")
    for entity, rows in entities.items():
        if {row.get("seed", "") for row in rows} != EXPECTED_SEEDS or len(rows) != 4:
            pair_reasons.append(f"candidate_not_four_jobs:{entity}")
        if len({row.get("sequence_sha256", "") for row in rows}) != 1:
            pair_reasons.append(f"candidate_sequence_hash_drift:{entity}")
        if len({row.get("monomer_sha256", "") for row in rows}) != 1:
            pair_reasons.append(f"candidate_monomer_hash_drift:{entity}")
    gates["candidate_seed_receptor_matrix"] = gate(
        FAIL if pair_reasons else (PASS if jobs else NOT_READY),
        pair_reasons or ([] if jobs else ["job_manifest_missing_or_empty"]),
        candidates=len(entities),
        candidate_seed_units=len(units),
    )

    lineage_reasons: list[str] = []
    for row in jobs:
        job_id = row.get("job_id", "")
        try:
            basis = json.loads(row.get("job_hash_basis", ""))
        except json.JSONDecodeError:
            lineage_reasons.append(f"invalid_job_hash_basis:{job_id}")
            continue
        expected_basis = {
            "entity_type": row.get("entity_type", ""),
            "entity_id": row.get("entity_id", ""),
            "conformation": row.get("conformation", ""),
            "seed": int(row.get("seed", "0")),
            "cfg_hash": row.get("cfg_hash", ""),
            "restraint_hash": row.get("restraint_hash", ""),
            "protocol_core_sha256": row.get("protocol_core_sha256", ""),
            "sequence_sha256": row.get("sequence_sha256", ""),
            "monomer_sha256": row.get("monomer_sha256", ""),
        }
        if basis != expected_basis:
            lineage_reasons.append(f"job_hash_basis_field_mismatch:{job_id}")
        observed_hash = hashlib.sha256(canonical_json(basis).encode()).hexdigest()
        if observed_hash != row.get("job_hash", ""):
            lineage_reasons.append(f"job_hash_mismatch:{job_id}")
    gates["job_lineage"] = gate(
        FAIL if lineage_reasons else (PASS if jobs else NOT_READY),
        lineage_reasons or ([] if jobs else ["job_manifest_missing_or_empty"]),
    )

    cfg_shape = Counter((row.get("seed", ""), row.get("conformation", ""), row.get("cfg_hash", "")) for row in jobs)
    cfg_reasons = []
    for seed in EXPECTED_SEEDS:
        for conformation in EXPECTED_CONFORMATIONS:
            hashes = {
                cfg_hash for (observed_seed, observed_conformation, cfg_hash) in cfg_shape
                if observed_seed == seed and observed_conformation == conformation
            }
            if len(hashes) != 1 or "" in hashes:
                cfg_reasons.append(f"cfg_hash_not_unique:{seed}:{conformation}")
    gates["cfg_hash_matrix"] = gate(
        FAIL if cfg_reasons else (PASS if jobs else NOT_READY),
        cfg_reasons or ([] if jobs else ["job_manifest_missing_or_empty"]),
    )

    payload = {
        "schema_version": "pvrig.candidate_only_protocol_validation.v2",
        "status": overall_status(gates),
        "candidate_only": True,
        "controls_applied": False,
        "expected_total_jobs": expected,
        "job_count": len(jobs),
        "job_set_hash": hashlib.sha256(
            "".join(sorted(row.get("job_hash", "") for row in jobs)).encode()
        ).hexdigest(),
        "job_manifest_sha256": sha256_file(jobs_path) if jobs_path.is_file() else "",
        "gates": gates,
        "claim_boundary": (
            "Candidate-only protocol and lineage validation; no 47-control evaluator "
            "calibration, binding, affinity, purity, expression or experimental blocking claim."
        ),
    }
    write_json(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="config/protocol_spec.json")
    parser.add_argument("--jobs", default="manifests/docking_jobs.tsv")
    parser.add_argument("--out", default="reports/PROTOCOL_VALIDATION_CANDIDATE_ONLY.json")
    parser.add_argument("--expected-total-jobs", type=int)
    args = parser.parse_args()
    payload = evaluate(
        Path(args.protocol), Path(args.jobs), Path(args.out), args.expected_total_jobs
    )
    print(json.dumps({"status": payload["status"], "out": args.out}, sort_keys=True))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
