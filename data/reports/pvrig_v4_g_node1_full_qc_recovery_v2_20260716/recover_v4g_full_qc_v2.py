#!/usr/bin/env python3
"""Fail-closed SSD-native recovery of the two interrupted V4-G Full-QC chunks."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ROOT = Path("/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_v1_20260716")
ROOT = Path("/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_20260716")
RUNTIME = ROOT / "runtime_closure"
CONTRACT = ROOT / "RECOVERY_CONTRACT.json"
RUNTIME_MANIFEST = RUNTIME / "RUNTIME_MANIFEST.json"
WORK = ROOT / "work/full_chunks"
OUTPUTS = ROOT / "outputs"
STATUS = ROOT / "status"
LOGS = ROOT / "logs"
PYTHON = Path("/data1/qlyu/software/envs/vhh-eval/bin/python").resolve()
CLAIM_BOUNDARY = "Sequence/developability QC only; no docking, binding, affinity, competition, or blocking labels."


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: object, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.chmod(mode)
    os.replace(tmp, path)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError(f"missing_or_empty_tsv:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing_empty_tsv:{path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def fasta_ids(path: Path) -> list[str]:
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError(f"missing_or_empty_fasta:{path}")
    return [line[1:].split()[0] for line in path.read_text().splitlines() if line.startswith(">")]


def verify_contract() -> tuple[dict, list[str]]:
    contract = json.loads(CONTRACT.read_text())
    if contract["schema_version"] != "pvrig_v4_g_unseen96_full_qc_recovery_contract_v2":
        raise RuntimeError("contract_schema_mismatch")
    if Path(contract["source_root"]) != SOURCE_ROOT or Path(contract["recovery_root"]) != ROOT:
        raise RuntimeError("contract_root_binding_mismatch")
    ids = contract["expected_shortlist_ids"]
    if len(ids) != 24 or len(set(ids)) != 24:
        raise RuntimeError("contract_shortlist_not_24_unique")
    ids_sha = hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()
    if ids_sha != contract["expected_shortlist_ids_sha256"]:
        raise RuntimeError("contract_shortlist_hash_mismatch")
    for relative, expected in contract["source_artifacts"].items():
        observed = sha256(SOURCE_ROOT / relative)
        if observed != expected:
            raise RuntimeError(f"source_artifact_hash_mismatch:{relative}:{observed}")
    shortlist_ids = [row["candidate_id"] for row in read_tsv(SOURCE_ROOT / "cascade/full_qc_shortlist.tsv")]
    if shortlist_ids != ids or fasta_ids(SOURCE_ROOT / "cascade/full_qc_shortlist.fasta") != ids:
        raise RuntimeError("source_shortlist_exact_order_closure_failed")
    return contract, ids


def verify_runtime() -> str:
    manifest_hash = sha256(RUNTIME_MANIFEST)
    manifest = json.loads(RUNTIME_MANIFEST.read_text())
    if manifest["status"] != "PASS_SSD_RUNTIME_CLOSURE_FROZEN":
        raise RuntimeError("runtime_manifest_not_pass")
    for relative, evidence in manifest["files"].items():
        path = RUNTIME / relative
        if not path.is_file() or sha256(path) != evidence["sha256"] or path.stat().st_size != evidence["size"]:
            raise RuntimeError(f"runtime_file_closure_failed:{relative}")
    for raw_path, expected in manifest["external_data1_runtime_hashes"].items():
        path = Path(raw_path)
        if not str(path).startswith("/data1/") or sha256(path.resolve()) != expected:
            raise RuntimeError(f"external_data1_runtime_hash_failed:{raw_path}")
    for path in RUNTIME.rglob("*"):
        if path.is_file() and path.name != "RUNTIME_MANIFEST.json":
            try:
                if b"/data/qlyu" in path.read_bytes():
                    raise RuntimeError(f"forbidden_nfs_runtime_dependency:{path}")
            except OSError:
                raise
    return manifest_hash


def validate_chunk(chunk: str, expected_ids: list[str], manifest_hash: str) -> dict:
    chunk_root = WORK / chunk
    input_path = chunk_root / "input.fasta"
    marker_path = chunk_root / "complete.json"
    portfolio = chunk_root / "qc_out/portfolio_ranked.tsv"
    if fasta_ids(input_path) != expected_ids:
        raise RuntimeError(f"chunk_input_id_order_mismatch:{chunk}")
    marker = json.loads(marker_path.read_text())
    observed_ids = [row.get("candidate_id", "") for row in read_tsv(portfolio)]
    if marker.get("status") != "complete" or marker.get("chunk") != chunk:
        raise RuntimeError(f"chunk_marker_not_complete:{chunk}")
    if marker.get("candidate_count") != 12 or set(observed_ids) != set(expected_ids) or len(set(observed_ids)) != 12:
        raise RuntimeError(f"chunk_output_id_closure_failed:{chunk}")
    if marker.get("input_fasta_sha256") != sha256(input_path):
        raise RuntimeError(f"chunk_input_hash_mismatch:{chunk}")
    if marker.get("portfolio_ranked_sha256") != sha256(portfolio):
        raise RuntimeError(f"chunk_portfolio_hash_mismatch:{chunk}")
    if marker.get("runtime_manifest_sha256") != manifest_hash:
        raise RuntimeError(f"chunk_runtime_binding_mismatch:{chunk}")
    return marker


def run_chunk(chunk: str, seed_input: Path, expected_ids: list[str], manifest_hash: str) -> dict:
    chunk_root = WORK / chunk
    marker = chunk_root / "complete.json"
    if marker.is_file():
        try:
            valid = validate_chunk(chunk, expected_ids, manifest_hash)
            return {**valid, "status": "reused"}
        except Exception:
            pass
    if chunk_root.exists():
        attempts = ROOT / "preserved_recovery_attempts"
        attempts.mkdir(parents=True, exist_ok=True)
        archived = attempts / f"{chunk}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.{os.getpid()}"
        shutil.move(str(chunk_root), archived)
    chunk_root.mkdir(parents=True)
    shutil.copy2(seed_input, chunk_root / "input.fasta")
    if fasta_ids(chunk_root / "input.fasta") != expected_ids:
        raise RuntimeError(f"seed_chunk_id_mismatch:{chunk}")
    out = chunk_root / "qc_out"
    command = [
        str(RUNTIME / "bin/vhh-competition-qc"), str(chunk_root / "input.fasta"),
        "-o", str(out), "--prefix", chunk, "--workers", "12", "--tnp-ncores", "4",
        "--identity-cache-size", "500000", "--gate-policy", "blocker_calibrated",
        "--skip-team-diversity", "--top-n", "100000000", "--reserve-n", "0",
        "--vhh-screen-bin", str(RUNTIME / "bin/vhh-screen"),
        "--validator-bin", str(RUNTIME / "bin/ab-data-validator"),
        "--anarci-bin", str(RUNTIME / "bin/ANARCI"),
        "--muscle-bin", str(RUNTIME / "bin/muscle"),
        "--positive-csv", str(RUNTIME / "validator_src/ab_data_validator/data/positive.csv"),
        "--official-positive-cdr-cache", str(RUNTIME / "references/official_positive_library_cdrs.csv"),
        "--local-positive-cdr-csv", str(RUNTIME / "references/local_pvrig_positive_vhh_cdrs.csv"),
        "--skip-tnp",
    ]
    (chunk_root / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    started = time.monotonic()
    env = dict(os.environ)
    env.update({
        "PATH": f"{RUNTIME / 'bin'}:/data1/qlyu/anaconda3/envs/boltz/bin:" + env.get("PATH", ""),
        "PYTHONPATH": f"{RUNTIME / 'validator_src'}:{RUNTIME / 'src'}",
        "AB_DATA_VALIDATOR_SRC": str(RUNTIME / "validator_src"),
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false",
    })
    with (chunk_root / "runner.stdout.log").open("w") as stdout, (chunk_root / "runner.stderr.log").open("w") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, text=True, env=env, check=False)
    elapsed = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        raise RuntimeError(f"chunk_command_failed:{chunk}:rc={completed.returncode}")
    observed_ids = [row.get("candidate_id", "") for row in read_tsv(out / "portfolio_ranked.tsv")]
    if len(observed_ids) != 12 or len(set(observed_ids)) != 12 or set(observed_ids) != set(expected_ids):
        raise RuntimeError(f"chunk_portfolio_exact_id_closure_failed:{chunk}")
    payload = {
        "schema_version": "pvrig_v4_g_full_qc_recovery_chunk_v2",
        "status": "complete", "chunk": chunk, "candidate_count": 12,
        "elapsed_seconds": elapsed, "finished_at_utc": now(),
        "input_fasta_sha256": sha256(chunk_root / "input.fasta"),
        "portfolio_ranked_sha256": sha256(out / "portfolio_ranked.tsv"),
        "runtime_manifest_sha256": manifest_hash,
    }
    atomic_json(marker, payload, 0o444)
    validate_chunk(chunk, expected_ids, manifest_hash)
    return payload


def merge_and_summarize(expected_ids: list[str], markers: list[dict], manifest_hash: str) -> None:
    all_rows: list[dict[str, str]] = []
    for chunk in ("chunk_000001", "chunk_000002"):
        all_rows.extend(read_tsv(WORK / chunk / "qc_out/portfolio_ranked.tsv"))
    ids = [row.get("candidate_id", "") for row in all_rows]
    if len(ids) != 24 or len(set(ids)) != 24 or set(ids) != set(expected_ids):
        raise RuntimeError("premerge_exact_24_id_closure_failed")
    def score(row: dict[str, str]) -> tuple[bool, float, float, str]:
        def number(value: str) -> float:
            try: return float(value or 0)
            except ValueError: return 0.0
        return row.get("hard_fail") == "True", -number(row.get("external_binder_score", "")), -number(row.get("final_score", "")), row.get("candidate_id", "")
    all_rows.sort(key=score)
    for rank, row in enumerate(all_rows, 1):
        row["cascade_full_rank"] = str(rank)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    write_tsv(OUTPUTS / "full_merged.tsv", all_rows)
    with (OUTPUTS / "full_chunk_status.tsv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["chunk", "status", "elapsed_seconds", "candidate_count"], delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for marker in sorted(markers, key=lambda x: x["chunk"]):
            writer.writerow({"chunk": marker["chunk"], "status": "complete", "elapsed_seconds": marker.get("elapsed_seconds", 0), "candidate_count": marker["candidate_count"]})
    hard_pass = [row for row in all_rows if row.get("hard_fail") != "True"]
    hard_fail = [row for row in all_rows if row.get("hard_fail") == "True"]
    summary = {
        "schema_version": "pvrig_v4_g_unseen96_full_qc_recovery_summary_v2",
        "status": "PASS_V4_G_UNSEEN96_FULL_QC_RECOVERED",
        "input_count": 96, "fast_hard_pass": 24, "full_rows": 24,
        "full_hard_pass": len(hard_pass), "full_hard_fail": len(hard_fail),
        "exact_shortlist_ids_sha256": hashlib.sha256(("\n".join(expected_ids) + "\n").encode()).hexdigest(),
        "runtime_manifest_sha256": manifest_hash,
        "output_sha256": {
            "full_chunk_status.tsv": sha256(OUTPUTS / "full_chunk_status.tsv"),
            "full_merged.tsv": sha256(OUTPUTS / "full_merged.tsv"),
        },
        "selection_policy": "exact frozen 24 Full-QC shortlist IDs; no replacement; no reselection",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(OUTPUTS / "full_qc_summary.json", summary, 0o444)


def validate_terminal(expected_ids: list[str], manifest_hash: str) -> dict:
    chunks = ["chunk_000001", "chunk_000002"]
    markers = [validate_chunk(c, expected_ids[i * 12:(i + 1) * 12], manifest_hash) for i, c in enumerate(chunks)]
    status_rows = read_tsv(OUTPUTS / "full_chunk_status.tsv")
    if {row.get("chunk") for row in status_rows} != set(chunks) or any(row.get("status") != "complete" for row in status_rows):
        raise RuntimeError("terminal_full_chunk_status_closure_failed")
    rows = read_tsv(OUTPUTS / "full_merged.tsv")
    ids = [row.get("candidate_id", "") for row in rows]
    if len(ids) != 24 or len(set(ids)) != 24 or set(ids) != set(expected_ids):
        raise RuntimeError("terminal_full_merged_exact_24_id_closure_failed")
    summary = json.loads((OUTPUTS / "full_qc_summary.json").read_text())
    if summary.get("status") != "PASS_V4_G_UNSEEN96_FULL_QC_RECOVERED" or summary.get("full_rows") != 24:
        raise RuntimeError("terminal_summary_not_pass")
    for name, expected in summary["output_sha256"].items():
        if sha256(OUTPUTS / name) != expected:
            raise RuntimeError(f"terminal_summary_hash_mismatch:{name}")
    return {
        "status": "PASS_V4_G_UNSEEN96_FULL_QC_RECOVERY_VALIDATED",
        "validated_at_utc": now(), "full_rows": 24,
        "full_hard_pass": sum(row.get("hard_fail") != "True" for row in rows),
        "full_hard_fail": sum(row.get("hard_fail") == "True" for row in rows),
        "shortlist_ids_sha256": hashlib.sha256(("\n".join(expected_ids) + "\n").encode()).hexdigest(),
        "runtime_manifest_sha256": manifest_hash,
        "outputs": {name: sha256(OUTPUTS / name) for name in ["full_chunk_status.tsv", "full_merged.tsv", "full_qc_summary.json"]},
        "chunk_markers": {marker["chunk"]: sha256(WORK / marker["chunk"] / "complete.json") for marker in markers},
        "old_false_terminal_preserved": {"path": str(SOURCE_ROOT / "status/runner.complete.json"), "sha256": sha256(SOURCE_ROOT / "status/runner.complete.json")},
        "claim_boundary": CLAIM_BOUNDARY,
    }


def main() -> int:
    STATUS.mkdir(parents=True, exist_ok=True); LOGS.mkdir(parents=True, exist_ok=True)
    atomic_json(STATUS / "recovery.running.json", {"status": "RUNNING_V4_G_FULL_QC_RECOVERY_V2", "pid": os.getpid(), "started_at_utc": now()})
    try:
        _, ids = verify_contract()
        manifest_hash = verify_runtime()
        seeds = [SOURCE_ROOT / f"cascade/full_chunks/chunk_{i:06d}/input.fasta" for i in (1, 2)]
        markers: list[dict] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(run_chunk, f"chunk_{i:06d}", seeds[i - 1], ids[(i - 1) * 12:i * 12], manifest_hash): i
                for i in (1, 2)
            }
            for future in as_completed(futures):
                markers.append(future.result())
        merge_and_summarize(ids, markers, manifest_hash)
        receipt = validate_terminal(ids, manifest_hash)
        atomic_json(STATUS / "recovery.complete.json", receipt, 0o444)
        atomic_json(STATUS / "recovery_state.json", {"stages": {"full": {"status": "complete", "chunks": 2}, "merge_full": {"status": "complete", "merged": 24}}, "updated_at_utc": now()}, 0o444)
        (STATUS / "recovery.running.json").unlink(missing_ok=True)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except BaseException as exc:
        failure = {"status": "FAIL_V4_G_FULL_QC_RECOVERY_V2", "failed_at_utc": now(), "error": f"{type(exc).__name__}:{exc}", "pid": os.getpid(), "claim_boundary": CLAIM_BOUNDARY}
        atomic_json(STATUS / "recovery.failed.json", failure, 0o444)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
