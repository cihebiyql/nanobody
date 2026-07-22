#!/usr/bin/env python3
"""Independent completion audit for the exact 1M computational release."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


AA20 = set("ACDEFGHIKLMNPQRSTVWY")
EXPECTED_ROUTES = {
    "conservative_cdr_redesign": 400000,
    "natural_cdr_donor": 200000,
    "profile_diversified_exploration_control": 100000,
    "rfantibody": 150000,
    "fixed_pose_mpnn": 150000,
}


def row_digest(row: dict[str, str], fields: list[str]) -> str:
    payload = json.dumps([row.get(field, "") for field in fields], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--multimetric", type=Path, required=True)
    parser.add_argument("--freeze-receipt", type=Path, required=True)
    parser.add_argument("--release-ready", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=1000000)
    args = parser.parse_args()

    freeze = json.loads(args.freeze_receipt.read_text())
    release = json.loads(args.release_ready.read_text())
    if freeze.get("status") != "PASS" or freeze.get("records") != args.expected:
        raise SystemExit("freeze receipt is not exact PASS")
    if release.get("status") != "PASS" or release.get("records") != args.expected:
        raise SystemExit("release receipt is not exact PASS")
    expected_candidate_hash = freeze.get("outputs", {}).get(args.candidates.name)
    if expected_candidate_hash != sha(args.candidates):
        raise SystemExit("candidate file hash does not match freeze receipt")
    if release.get("sha256") != sha(args.multimetric):
        raise SystemExit("multimetric file hash does not match release receipt")

    with tempfile.NamedTemporaryFile(prefix="pvrig_final_audit_", suffix=".sqlite") as tmp:
        conn = sqlite3.connect(tmp.name)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(
            "CREATE TABLE candidate(candidate_id TEXT PRIMARY KEY, sequence TEXT UNIQUE, metadata_sha256 TEXT)"
        )
        route_counts: Counter[str] = Counter()
        candidate_count = 0
        with gzip.open(args.candidates, "rt", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            candidate_fields = list(reader.fieldnames or [])
            required = {"candidate_id", "sequence", "sequence_sha256", "route_id", "max_positive_cdr_identity"}
            missing = required - set(candidate_fields)
            if missing:
                raise SystemExit(f"candidate fields missing: {sorted(missing)}")
            batch = []
            for row in reader:
                candidate_id = row["candidate_id"]
                sequence = row["sequence"].strip().upper()
                if not 95 <= len(sequence) <= 160 or not set(sequence) <= AA20:
                    raise SystemExit(f"invalid sequence alphabet/length: {candidate_id}")
                if hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
                    raise SystemExit(f"sequence hash mismatch: {candidate_id}")
                if float(row["max_positive_cdr_identity"]) >= 0.8:
                    raise SystemExit(f"positive CDR identity gate failed: {candidate_id}")
                batch.append((candidate_id, sequence, row_digest(row, candidate_fields)))
                route_counts[row["route_id"]] += 1
                candidate_count += 1
                if len(batch) == 5000:
                    conn.executemany("INSERT INTO candidate VALUES (?,?,?)", batch)
                    batch = []
            if batch:
                conn.executemany("INSERT INTO candidate VALUES (?,?,?)", batch)
        conn.commit()
        if candidate_count != args.expected:
            raise SystemExit(f"candidate count {candidate_count} != {args.expected}")
        if args.expected == 1000000 and dict(route_counts) != EXPECTED_ROUTES:
            raise SystemExit(f"route count mismatch: {dict(route_counts)}")

        conn.execute("CREATE TABLE metric(candidate_id TEXT PRIMARY KEY, metadata_sha256 TEXT)")
        metric_count = 0
        statuses = {"anarci": Counter(), "nbb2": Counter(), "tnp": Counter()}
        with gzip.open(args.multimetric, "rt", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            metric_fields = list(reader.fieldnames or [])
            required = {
                "candidate_id", "sequence", "sequence_sha256", "route_id", "prefilter_anarci_qc_status",
                "nbb2_status", "tnp_status",
            }
            missing = required - set(metric_fields)
            if missing:
                raise SystemExit(f"multimetric fields missing: {sorted(missing)}")
            release_schema = release.get("schema_fields")
            if not isinstance(release_schema, list) or metric_fields != release_schema:
                raise SystemExit("multimetric schema does not exactly match release receipt")
            observed_schema_sha = hashlib.sha256("\t".join(metric_fields).encode()).hexdigest()
            if release.get("schema_sha256") != observed_schema_sha:
                raise SystemExit("multimetric schema SHA256 does not match release receipt")
            if metric_fields[: len(candidate_fields)] != candidate_fields:
                raise SystemExit("multimetric candidate metadata prefix schema mismatch")
            batch = []
            for row in reader:
                candidate_id = row["candidate_id"]
                batch.append((candidate_id, row_digest(row, candidate_fields)))
                statuses["anarci"][row["prefilter_anarci_qc_status"]] += 1
                statuses["nbb2"][row["nbb2_status"]] += 1
                statuses["tnp"][row["tnp_status"]] += 1
                metric_count += 1
                if len(batch) == 5000:
                    conn.executemany("INSERT INTO metric VALUES (?,?)", batch)
                    batch = []
            if batch:
                conn.executemany("INSERT INTO metric VALUES (?,?)", batch)
        conn.commit()
        if metric_count != args.expected:
            raise SystemExit(f"multimetric count {metric_count} != {args.expected}")
        missing = conn.execute(
            "SELECT COUNT(*) FROM candidate c LEFT JOIN metric m USING(candidate_id) WHERE m.candidate_id IS NULL"
        ).fetchone()[0]
        extra = conn.execute(
            "SELECT COUNT(*) FROM metric m LEFT JOIN candidate c USING(candidate_id) WHERE c.candidate_id IS NULL"
        ).fetchone()[0]
        if missing or extra:
            raise SystemExit(f"candidate/metric ID mismatch missing={missing} extra={extra}")
        metadata_mismatch = conn.execute(
            "SELECT COUNT(*) FROM candidate c JOIN metric m USING(candidate_id) "
            "WHERE c.metadata_sha256 != m.metadata_sha256"
        ).fetchone()[0]
        if metadata_mismatch:
            raise SystemExit(f"candidate/multimetric metadata closure mismatch records={metadata_mismatch}")

    if statuses["anarci"] != {"PASS": args.expected}:
        raise SystemExit(f"ANARCI status closure failed: {dict(statuses['anarci'])}")
    if statuses["nbb2"] != {"SUCCESS": args.expected}:
        raise SystemExit(f"NBB2 status closure failed: {dict(statuses['nbb2'])}")
    if statuses["tnp"] != {"PASS": args.expected}:
        raise SystemExit(f"TNP status closure failed: {dict(statuses['tnp'])}")

    payload = {
        "status": "PASS",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "records": args.expected,
        "candidate_id_exact_unique": True,
        "sequence_exact_unique": True,
        "candidate_multimetric_id_set_exact_match": True,
        "candidate_multimetric_metadata_exact_match": True,
        "multimetric_schema_exact_match": True,
        "sequence_alphabet_and_length_gate": True,
        "sequence_sha256_closure": True,
        "positive_cdr_identity_below_0_8": True,
        "route_counts": dict(sorted(route_counts.items())),
        "status_counts": {key: dict(sorted(value.items())) for key, value in statuses.items()},
        "candidate_sha256": sha(args.candidates),
        "multimetric_sha256": sha(args.multimetric),
        "scientific_boundaries": release.get("scientific_boundaries", {}),
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
