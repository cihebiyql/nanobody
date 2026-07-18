#!/usr/bin/env python3
"""Run Full-QC for the V4-I Top114 ProteinMPNN expansion pool on Node23."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/data/qlyu/projects/pvrig_v4_i_mpnn1008_qc_v1_20260718")
POOL = Path("/data/qlyu/projects/pvrig_v4_i_top114_mpnn_pool_v1_20260718")
MANIFEST = POOL / "outputs/mpnn_expansion_candidates.tsv"
FASTA = POOL / "outputs/mpnn_expansion_candidates.fasta"
SCREEN = Path("/data/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py")
PYTHON = Path("/data/qlyu/software/envs/vhh-eval/bin/python")
RUNTIME = Path("/data/qlyu/projects/pvrig_v4_i_runtime_closure_v1_20260718")
EXPECTED = 1008
CLAIM_BOUNDARY = (
    "Sequence/developability Full-QC for computational PVRIG docking expansion only; "
    "not docking geometry, binding, affinity, competition, or experimental blocking."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def preflight() -> dict[str, Any]:
    required = [MANIFEST, FASTA, SCREEN, PYTHON, RUNTIME / "bin/vhh-competition-qc", RUNTIME / "bin/muscle"]
    for path in required:
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"required_file_missing:{path}")
    fields, rows = read_tsv(MANIFEST)
    needed = {"candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"}
    if not needed <= set(fields):
        raise RuntimeError(f"manifest_fields_missing:{sorted(needed - set(fields))}")
    if len(rows) != EXPECTED or len({row["candidate_id"] for row in rows}) != EXPECTED:
        raise RuntimeError(f"manifest_count_or_id_closure:{len(rows)}")
    if len({row["sequence_sha256"] for row in rows}) != EXPECTED:
        raise RuntimeError("manifest_sequence_hash_not_unique")
    for row in rows:
        if hashlib.sha256(row["sequence"].encode()).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_hash_mismatch:{row['candidate_id']}")
    fasta_count = sum(1 for line in FASTA.read_text().splitlines() if line.startswith(">"))
    if fasta_count != EXPECTED:
        raise RuntimeError(f"fasta_count:{fasta_count}")
    return {
        "schema_version": "pvrig_v4_i_mpnn1008_full_qc_preflight_v1",
        "status": "PASS_ZERO_WORK_PREFLIGHT",
        "candidate_count": EXPECTED,
        "input_hashes": {"manifest": sha256(MANIFEST), "fasta": sha256(FASTA)},
        "runtime_hashes": {"screen": sha256(SCREEN), "python": sha256(PYTHON)},
        "resource_policy": {"chunk_jobs": 16, "workers_per_chunk": 2, "maximum_cpu_workers": 32},
        "claim_boundary": CLAIM_BOUNDARY,
    }


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "PATH": f"{RUNTIME / 'bin'}:/data/qlyu/anaconda3/envs/boltz/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": f"{RUNTIME / 'validator_src'}:{RUNTIME / 'src'}",
        "AB_DATA_VALIDATOR_SRC": str(RUNTIME / "validator_src"),
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": "",
    })
    return env


def command(stage: str) -> list[str]:
    return [
        str(PYTHON), str(SCREEN), str(FASTA), "-o", str(ROOT / "cascade"),
        "--qc-bin", str(RUNTIME / "bin/vhh-competition-qc"),
        "--local-positive-cdr-csv", str(RUNTIME / "references/local_pvrig_positive_vhh_cdrs.csv"),
        "--muscle-bin", str(RUNTIME / "bin/muscle"), "--stage", stage,
        "--fast-chunk-size", "45", "--full-chunk-size", "45",
        "--chunk-jobs", "16", "--full-chunk-jobs", "16", "--workers", "2",
        "--tnp-ncores", "1", "--identity-cache-size", "500000", "--full-qc-limit", "0",
        "--geometry-limit", str(EXPECTED), "--geometry-pool-size", str(EXPECTED),
        "--geometry-cluster-limit", str(EXPECTED), "--skip-final-diversity",
    ]


def hard_pass(row: dict[str, str]) -> bool:
    value = row.get("hard_fail", "").lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"invalid_hard_fail:{row.get('candidate_id', '')}:{value}")
    return value == "false"


def publish() -> dict[str, Any]:
    fields, source = read_tsv(MANIFEST)
    _, fast = read_tsv(ROOT / "cascade/fast_merged.tsv")
    _, full = read_tsv(ROOT / "cascade/full_merged.tsv")
    if len(fast) != EXPECTED or {row["candidate_id"] for row in fast} != {row["candidate_id"] for row in source}:
        raise RuntimeError("fast_exact_closure_failed")
    full_by = {row["candidate_id"]: row for row in full}
    fast_by = {row["candidate_id"]: row for row in fast}
    ready: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for row in source:
        candidate_id = row["candidate_id"]
        fast_ok = hard_pass(fast_by[candidate_id])
        full_ok = candidate_id in full_by and hard_pass(full_by[candidate_id])
        states.append({
            "candidate_id": candidate_id, "sequence_sha256": row["sequence_sha256"],
            "fast_hard_pass": str(fast_ok).lower(), "full_hard_pass": str(full_ok).lower(),
            "qc_state": "HARD_PASS" if full_ok else "HARD_FAIL",
        })
        if full_ok:
            selected = dict(row)
            selected["research_pool_state"] = "RESEARCH_READY"
            selected["full_qc_state"] = "HARD_PASS"
            ready.append(selected)
    output = ROOT / "outputs"
    write_tsv(output / "candidate_qc_states.tsv", states, list(states[0]))
    ready_fields = list(ready[0]) if ready else fields + ["full_qc_state"]
    write_tsv(output / "research_ready_candidates.tsv", ready, ready_fields)
    (output / "research_ready_candidates.fasta").write_text(
        "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in ready)
    )
    summary = {
        "schema_version": "pvrig_v4_i_mpnn1008_full_qc_terminal_v1",
        "status": "PASS_MPNN1008_FULL_QC_COMPLETE",
        "input_count": EXPECTED,
        "fast_hard_pass": sum(hard_pass(row) for row in fast),
        "full_rows": len(full),
        "full_hard_pass": len(ready),
        "full_hard_fail": len(full) - len(ready),
        "output_hashes": {
            "candidate_qc_states.tsv": sha256(output / "candidate_qc_states.tsv"),
            "research_ready_candidates.tsv": sha256(output / "research_ready_candidates.tsv"),
            "research_ready_candidates.fasta": sha256(output / "research_ready_candidates.fasta"),
        },
        "finished_at_utc": now(),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(output / "FULL_QC_RECEIPT.json", summary)
    return summary


def run() -> int:
    (ROOT / "status").mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    lock_handle = (ROOT / "status/runner.lock").open("w")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    atomic_json(ROOT / "status/runner.running.json", {"status": "RUNNING", "pid": os.getpid(), "started_at_utc": now()})
    preflight_result = preflight()
    atomic_json(ROOT / "status/preflight.json", preflight_result)
    with (ROOT / "logs/full_qc.log").open("a", encoding="utf-8") as log:
        for stage in ("prepare", "fast", "full"):
            atomic_json(ROOT / "status/progress.json", {"status": "RUNNING", "stage": stage, "updated_at_utc": now()})
            completed = subprocess.run(command(stage), env=environment(), stdout=log, stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                raise RuntimeError(f"screen_stage_failed:{stage}:rc={completed.returncode}")
    result = publish()
    atomic_json(ROOT / "status/runner.complete.json", result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        result = preflight() if args.preflight else None
        if result is not None:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        return run()
    except BaseException as error:
        atomic_json(ROOT / "status/runner.failed.json", {
            "status": "FAILED", "error": f"{type(error).__name__}:{error}",
            "failed_at_utc": now(), "pid": os.getpid(), "claim_boundary": CLAIM_BOUNDARY,
        })
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
