#!/usr/bin/env python3
"""Continuously import hash-verified Node23 NBB2 tail successes into Node1's resumable root."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


AA3 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I",
    "LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
}
CLAIM = "Cross-node monomer compute import with exact sequence/PDB hashes only; not a scientific label."


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True); handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_manifest(path: Path, expected_count: int) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != expected_count or len({row["candidate_id"] for row in rows}) != expected_count:
        raise RuntimeError("manifest_count_or_id_closure")
    return {row["candidate_id"]: row for row in rows}


def pdb_sequence(path: Path) -> str:
    residues: list[str] = []; seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(errors="strict").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54 or line[21] != "A" or line[12:16].strip() != "CA":
            continue
        key = (line[21], line[22:26], line[26])
        if key in seen: continue
        seen.add(key); residues.append(AA3.get(line[17:20].strip(), "X"))
    return "".join(residues)


def active_candidates(candidate_ids: set[str]) -> set[str]:
    result = subprocess.run(["pgrep", "-af", "NanoBodyBuilder2"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return {candidate_id for candidate_id in candidate_ids if candidate_id in result.stdout}


def valid_destination(status_path: Path, pdb_path: Path, row: dict[str, str]) -> bool:
    if not status_path.is_file() or not pdb_path.is_file(): return False
    try:
        status = json.loads(status_path.read_text())
        return (
            status.get("status") == "SUCCESS" and status.get("candidate_id") == row["candidate_id"]
            and status.get("sequence_sha256") == row["sequence_sha256"]
            and status.get("pdb_sha256") == sha256_file(pdb_path)
            and pdb_sequence(pdb_path) == row["sequence"]
        )
    except Exception:
        return False


def import_pass(
    source_root: Path,
    destination_root: Path,
    manifest: dict[str, dict[str, str]],
    status_prefix: str = "NODE23_IMPORT",
) -> dict[str, object]:
    active = active_candidates(set(manifest)); source_statuses = list((source_root / "status/candidates").glob("*.json"))
    source_counts: dict[str, int] = {}; imported = 0; already = 0; active_skips = 0; invalid = []
    for status_path in source_statuses:
        try: status = json.loads(status_path.read_text())
        except Exception: continue
        state = str(status.get("status", "INVALID")); source_counts[state] = source_counts.get(state, 0) + 1
        if state != "SUCCESS": continue
        candidate_id = str(status.get("candidate_id", "")); row = manifest.get(candidate_id)
        if row is None or status.get("sequence_sha256") != row["sequence_sha256"]:
            invalid.append(f"manifest_binding:{candidate_id}"); continue
        source_pdb = Path(str(status.get("pdb_path", "")))
        try: source_pdb.resolve().relative_to(source_root.resolve())
        except Exception: invalid.append(f"source_path:{candidate_id}"); continue
        if not source_pdb.is_file() or sha256_file(source_pdb) != status.get("pdb_sha256") or pdb_sequence(source_pdb) != row["sequence"]:
            invalid.append(f"source_pdb:{candidate_id}"); continue
        destination_dir = destination_root / "monomers" / candidate_id
        destination_pdb = destination_dir / "nbb2.chainA.pdb"
        destination_status = destination_root / "status/candidates" / f"{candidate_id}.json"
        if valid_destination(destination_status, destination_pdb, row): already += 1; continue
        if candidate_id in active: active_skips += 1; continue
        destination_dir.mkdir(parents=True, exist_ok=True)
        temporary = destination_dir / f".nbb2.chainA.pdb.importing.{os.getpid()}"
        shutil.copy2(source_pdb, temporary)
        if sha256_file(temporary) != status["pdb_sha256"]: temporary.unlink(missing_ok=True); raise RuntimeError(f"copy_hash:{candidate_id}")
        os.replace(temporary, destination_pdb)
        payload = dict(status)
        payload.update({
            "pdb_path": str(destination_pdb), "imported_from_node23": True,
            "node23_source_pdb_path": str(source_pdb), "node23_source_status_sha256": sha256_file(status_path),
            "imported_at_utc": now(), "claim_boundary": CLAIM,
        })
        atomic_json(destination_status, payload); imported += 1
    if invalid: raise RuntimeError("invalid_source_rows:" + ",".join(invalid[:10]))
    complete = (source_root / "status/COMPLETE.json").is_file()
    payload = {
        "schema_version":"pvrig_v29_node23_tail_import_progress_v1", "status":"RUNNING" if not complete else "SOURCE_TERMINAL",
        "source_terminal_status_count":len(source_statuses), "source_status_counts":source_counts,
        "imported_this_pass":imported, "already_valid":already, "active_candidate_skips":active_skips,
        "source_complete":complete, "updated_at_utc":now(), "claim_boundary":CLAIM,
    }
    atomic_json(destination_root / f"status/{status_prefix}_PROGRESS.json", payload)
    return payload


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True); parser.add_argument("--destination-root",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True); parser.add_argument("--poll-seconds",type=int,default=30); parser.add_argument("--once",action="store_true")
    parser.add_argument("--expected-count",type=int,default=4000); parser.add_argument("--status-prefix",default="NODE23_IMPORT")
    args=parser.parse_args(); manifest=read_manifest(args.manifest,args.expected_count)
    lock_path=args.destination_root/f"status/{args.status_prefix}.lock"; lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            payload=import_pass(args.source_root,args.destination_root,manifest,args.status_prefix)
            if args.once: print(json.dumps(payload,indent=2,sort_keys=True)); return 0
            if payload["source_complete"] and payload["source_status_counts"].get("SUCCESS",0)==payload["already_valid"]:
                final={**payload,"status":"PASS_NODE23_TAIL_IMPORT_COMPLETE","completed_at_utc":now()}
                atomic_json(args.destination_root/f"status/{args.status_prefix}_COMPLETE.json",final); print(json.dumps(final,indent=2,sort_keys=True)); return 0
            time.sleep(args.poll_seconds)


if __name__=="__main__": raise SystemExit(main())
