#!/usr/bin/env python3
"""Resumable NanoBodyBuilder2 monomer generation for the V2.9 Docking10k panel."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import shlex
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CLAIM = (
    "Monomer structure generation and exact-sequence geometry QC only; not binding, "
    "affinity, competition, experimental blocking, or Docking Gold."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_manifest(path: Path, expected_count: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    required = {"candidate_id", "sequence", "sequence_sha256", "research_pool_state"}
    if not required <= set(reader.fieldnames or []):
        raise RuntimeError(f"manifest_fields_missing:{sorted(required - set(reader.fieldnames or []))}")
    if len(rows) != expected_count:
        raise RuntimeError(f"manifest_count:{len(rows)}:{expected_count}")
    ids: set[str] = set()
    sequences: set[str] = set()
    for row in rows:
        candidate_id = row["candidate_id"]
        sequence = row["sequence"].strip().upper()
        if not candidate_id or candidate_id in ids:
            raise RuntimeError(f"candidate_id_invalid_or_duplicate:{candidate_id}")
        if not sequence or sequence in sequences or set(sequence) - STANDARD_AA:
            raise RuntimeError(f"sequence_invalid_or_duplicate:{candidate_id}")
        if sha256_text(sequence) != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_hash_mismatch:{candidate_id}")
        if row["research_pool_state"] != "RESEARCH_READY":
            raise RuntimeError(f"non_ready_candidate_in_manifest:{candidate_id}")
        row["sequence"] = sequence
        ids.add(candidate_id)
        sequences.add(sequence)
    return rows


def pdb_chain_sequences(path: Path) -> dict[str, str]:
    by_chain: dict[str, list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54 or line[12:16].strip() != "CA":
            continue
        token = (line[21], line[22:26], line[26])
        if token in seen:
            continue
        seen.add(token)
        by_chain.setdefault(line[21], []).append(AA3.get(line[17:20].strip(), "X"))
    return {chain: "".join(values) for chain, values in by_chain.items()}


def normalize_and_validate(source: Path, destination: Path, sequence: str) -> dict[str, Any]:
    chain_sequences = pdb_chain_sequences(source)
    matches = [chain for chain, observed in chain_sequences.items() if observed == sequence]
    if len(matches) != 1:
        raise RuntimeError(f"exact_sequence_chain_count:{len(matches)}")
    source_chain = matches[0]
    residue_map: dict[tuple[str, str], int] = {}
    output: list[str] = []
    ca_coordinates: list[tuple[float, float, float]] = []
    ca_seen: set[tuple[str, str]] = set()
    for raw in source.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.startswith("ATOM  ") or len(raw) < 54 or raw[21] != source_chain:
            continue
        line = raw.ljust(80)
        key = (line[22:26], line[26])
        residue_map.setdefault(key, len(residue_map) + 1)
        output.append(f"{line[:21]}A{residue_map[key]:4d} {line[27:]}".rstrip())
        if line[12:16].strip() == "CA" and key not in ca_seen:
            ca_seen.add(key)
            ca_coordinates.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    if len(residue_map) != len(sequence) or len(ca_coordinates) != len(sequence):
        raise RuntimeError("residue_or_ca_count_mismatch")
    distances = []
    for left, right in zip(ca_coordinates, ca_coordinates[1:]):
        distance = math.dist(left, right)
        if not math.isfinite(distance):
            raise RuntimeError("nonfinite_ca_distance")
        distances.append(distance)
    if not distances or min(distances) < 2.8 or max(distances) > 4.5:
        raise RuntimeError(
            f"ca_geometry_out_of_range:{min(distances, default=0):.3f}:{max(distances, default=0):.3f}"
        )
    destination.write_text("\n".join(output) + "\nTER\nEND\n", encoding="utf-8")
    if pdb_chain_sequences(destination) != {"A": sequence}:
        raise RuntimeError("normalized_exact_sequence_validation_failed")
    return {
        "source_chain": source_chain,
        "residue_count": len(sequence),
        "ca_step_min": min(distances),
        "ca_step_max": max(distances),
    }


def prior_success_valid(status_path: Path, pdb_path: Path, row: dict[str, str]) -> bool:
    if not status_path.is_file() or not pdb_path.is_file():
        return False
    try:
        status = json.loads(status_path.read_text())
        if (
            status.get("status") != "SUCCESS"
            or status.get("candidate_id") != row["candidate_id"]
            or status.get("sequence_sha256") != row["sequence_sha256"]
            or status.get("pdb_sha256") != sha256_file(pdb_path)
            or pdb_chain_sequences(pdb_path) != {"A": row["sequence"]}
        ):
            return False
        return True
    except Exception:
        return False


def run_candidate(
    row: dict[str, str], root: Path, nbb2: Path, gpu: int, cpu_set: str, threads: int
) -> dict[str, Any]:
    candidate_id = row["candidate_id"]
    sequence = row["sequence"]
    work = root / "monomers" / candidate_id
    work.mkdir(parents=True, exist_ok=True)
    raw = work / "nbb2.raw.pdb"
    normalized = work / "nbb2.chainA.pdb"
    status_path = root / "status" / "candidates" / f"{candidate_id}.json"
    if prior_success_valid(status_path, normalized, row):
        return json.loads(status_path.read_text())

    env = dict(os.environ)
    env.update(
        {
            "CUDA_VISIBLE_DEVICES": str(gpu),
            "PATH": f"{nbb2.parent}:{env.get('PATH', '')}",
            "OMP_NUM_THREADS": str(threads),
            "MKL_NUM_THREADS": str(threads),
            "OPENBLAS_NUM_THREADS": str(threads),
            "NUMEXPR_NUM_THREADS": str(threads),
        }
    )
    attempts: list[dict[str, Any]] = []
    for mode, extra in (("REFINED", []), ("UNREFINED_FALLBACK", ["-u"])):
        raw.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)
        command = [
            "taskset", "-c", cpu_set, str(nbb2), "-H", sequence, "-o", str(raw),
            "--n_threads", str(threads), *extra, "-v",
        ]
        started = now()
        completed = subprocess.run(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=3600,
        )
        log = work / f"{mode.lower()}.log"
        log.write_text(
            f"$ {shlex.join(command)}\n{completed.stdout}\n[exit_code] {completed.returncode}\n",
            encoding="utf-8",
        )
        attempt: dict[str, Any] = {
            "mode": mode,
            "started_at_utc": started,
            "finished_at_utc": now(),
            "exit_code": completed.returncode,
            "log_sha256": sha256_file(log),
        }
        attempts.append(attempt)
        if completed.returncode != 0 or not raw.is_file():
            continue
        try:
            geometry = normalize_and_validate(raw, normalized, sequence)
            payload = {
                "schema_version": "pvrig_v2_9_monomer_candidate_v1",
                "status": "SUCCESS",
                "candidate_id": candidate_id,
                "sequence_sha256": row["sequence_sha256"],
                "gpu": gpu,
                "cpu_set": cpu_set,
                "successful_mode": mode,
                "pdb_path": str(normalized),
                "pdb_sha256": sha256_file(normalized),
                "geometry": geometry,
                "attempts": attempts,
                "finished_at_utc": now(),
                "claim_boundary": CLAIM,
            }
            atomic_json(status_path, payload)
            return payload
        except Exception as error:
            attempt["validation_error"] = f"{type(error).__name__}:{error}"

    payload = {
        "schema_version": "pvrig_v2_9_monomer_candidate_v1",
        "status": "TECHNICAL_FAILURE",
        "candidate_id": candidate_id,
        "sequence_sha256": row["sequence_sha256"],
        "gpu": gpu,
        "cpu_set": cpu_set,
        "attempts": attempts,
        "technical_failure_reason": "NBB2_REFINED_AND_UNREFINED_FAILED_OR_INVALID",
        "finished_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    atomic_json(status_path, payload)
    return payload


def write_progress(root: Path, expected: int) -> dict[str, Any]:
    statuses = []
    for path in sorted((root / "status" / "candidates").glob("*.json")):
        try:
            statuses.append(json.loads(path.read_text()))
        except Exception:
            pass
    counts: dict[str, int] = {}
    for row in statuses:
        counts[str(row.get("status", "INVALID"))] = counts.get(str(row.get("status", "INVALID")), 0) + 1
    payload = {
        "schema_version": "pvrig_v2_9_monomer_progress_v1",
        "expected": expected,
        "terminal": len(statuses),
        "pending": expected - len(statuses),
        "status_counts": counts,
        "updated_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    atomic_json(root / "status" / "PROGRESS.json", payload)
    return payload


def run_gpu_lane(
    rows: list[dict[str, str]], root: Path, nbb2: Path, gpu: int, cpu_set: str, threads: int, expected: int
) -> list[dict[str, Any]]:
    results = []
    for row in rows:
        try:
            results.append(run_candidate(row, root, nbb2, gpu, cpu_set, threads))
        except subprocess.TimeoutExpired as error:
            payload = {
                "schema_version": "pvrig_v2_9_monomer_candidate_v1",
                "status": "TECHNICAL_FAILURE",
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "gpu": gpu,
                "cpu_set": cpu_set,
                "technical_failure_reason": f"TIMEOUT:{error.timeout}",
                "finished_at_utc": now(),
                "claim_boundary": CLAIM,
            }
            atomic_json(root / "status" / "candidates" / f"{row['candidate_id']}.json", payload)
            results.append(payload)
        except Exception as error:
            payload = {
                "schema_version": "pvrig_v2_9_monomer_candidate_v1",
                "status": "TECHNICAL_FAILURE",
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "gpu": gpu,
                "cpu_set": cpu_set,
                "technical_failure_reason": f"{type(error).__name__}:{error}",
                "finished_at_utc": now(),
                "claim_boundary": CLAIM,
            }
            atomic_json(root / "status" / "candidates" / f"{row['candidate_id']}.json", payload)
            results.append(payload)
        write_progress(root, expected)
    return results


def publish_manifest(root: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    records = []
    for row in rows:
        status_path = root / "status" / "candidates" / f"{row['candidate_id']}.json"
        if not status_path.is_file():
            raise RuntimeError(f"candidate_status_missing:{row['candidate_id']}")
        status = json.loads(status_path.read_text())
        records.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "monomer_status": status["status"],
                "pdb_path": status.get("pdb_path", ""),
                "pdb_sha256": status.get("pdb_sha256", ""),
                "successful_mode": status.get("successful_mode", ""),
                "technical_failure_reason": status.get("technical_failure_reason", ""),
                "claim_boundary": CLAIM,
            }
        )
    manifest = root / "outputs" / "monomer_manifest.tsv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    success = sum(row["monomer_status"] == "SUCCESS" for row in records)
    payload = {
        "schema_version": "pvrig_v2_9_monomer_complete_v1",
        "status": "PASS_MONOMER_BATCH_TERMINAL",
        "candidate_count": len(records),
        "success_count": success,
        "technical_failure_count": len(records) - success,
        "manifest_path": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "completed_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    atomic_json(root / "status" / "COMPLETE.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--nbb2", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--gpus", default="0,1,2,3,4,5,6,7")
    parser.add_argument("--threads-per-worker", type=int, default=4)
    parser.add_argument("--smoke-count", type=int, default=0)
    args = parser.parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    lock_handle = (args.output_root / "RUN.lock").open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError("runner_already_active") from error
    if not args.nbb2.is_file() or args.nbb2.is_symlink():
        raise RuntimeError(f"nbb2_missing_or_symlink:{args.nbb2}")
    rows = read_manifest(args.manifest, args.expected_count)
    if args.smoke_count:
        rows = rows[: args.smoke_count]
    expected = len(rows)
    gpus = [int(value) for value in args.gpus.split(",") if value.strip()]
    if not gpus or len(gpus) * args.threads_per_worker > (os.cpu_count() or 1):
        raise RuntimeError("invalid_gpu_or_cpu_worker_contract")
    lanes = [[] for _ in gpus]
    for index, row in enumerate(rows):
        lanes[index % len(gpus)].append(row)
    cpu_sets = [
        f"{index * args.threads_per_worker}-{(index + 1) * args.threads_per_worker - 1}"
        for index in range(len(gpus))
    ]
    atomic_json(
        args.output_root / "status" / "RUNNING.json",
        {
            "status": "RUNNING_RESUMABLE_MONOMER_GENERATION",
            "candidate_count": expected,
            "manifest_sha256": sha256_file(args.manifest),
            "nbb2_path": str(args.nbb2),
            "nbb2_sha256": sha256_file(args.nbb2),
            "gpus": gpus,
            "threads_per_worker": args.threads_per_worker,
            "cpu_sets": cpu_sets,
            "started_at_utc": now(),
            "claim_boundary": CLAIM,
        },
    )
    write_progress(args.output_root, expected)
    with ThreadPoolExecutor(max_workers=len(gpus)) as pool:
        futures = [
            pool.submit(
                run_gpu_lane,
                lane,
                args.output_root,
                args.nbb2,
                gpu,
                cpu_set,
                args.threads_per_worker,
                expected,
            )
            for lane, gpu, cpu_set in zip(lanes, gpus, cpu_sets)
            if lane
        ]
        for future in as_completed(futures):
            future.result()
    print(json.dumps(publish_manifest(args.output_root, rows), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
