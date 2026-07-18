#!/usr/bin/env python3
"""Wait for Node23 adaptive teacher, sync it, and materialize formal V2.4 inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence


REMOTE_ROOT = "/data/qlyu/projects/pvrig_v4_h_adaptive_contact_teacher_v2_20260718"
REMOTE_OUTPUT = f"{REMOTE_ROOT}/production_output_v2"
RAW_FILES = (
    "v4h_adaptive_residue_pair_contact_teacher.tsv.gz",
    "v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz",
    "v4h_adaptive_receptor_state.tsv.gz",
    "v4h_adaptive_candidate_state.tsv.gz",
    "v4h_adaptive_selected_job_inventory.tsv.gz",
    "v4h_adaptive_contact_extraction_audit.json",
)
SOURCE_STATUS = "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION"
EXPECTED = {
    "candidate_rows": 1320,
    "valid_candidate_rows": 1281,
    "technical_incomplete_candidate_rows": 39,
    "selected_paired_job_rows": 3536,
}


class WatchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WatchError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def remote_state() -> str:
    command = (
        f'ROOT={REMOTE_ROOT}; PID=$(cat "$ROOT/EXTRACTION.pid"); '
        f'if test -f "{REMOTE_OUTPUT}/RUN_RECEIPT.json"; then echo RECEIPT_READY; '
        'elif kill -0 "$PID" 2>/dev/null; then echo RUNNING; else echo DEAD_NO_RECEIPT; fi'
    )
    result = subprocess.run(["ssh.exe", "node23", command], check=True, text=True, capture_output=True)
    return result.stdout.strip().splitlines()[-1]


def validate_source(root: Path) -> dict[str, Any]:
    receipt_path = root / "RUN_RECEIPT.json"
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "source_receipt_missing_or_symlink")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("schema_version") == "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2_receipt", "source_receipt_schema")
    require(receipt.get("status") == SOURCE_STATUS, "source_receipt_status")
    for field, expected in EXPECTED.items():
        require(receipt.get(field) == expected, f"source_count:{field}:{receipt.get(field)}:{expected}")
    require(receipt.get("source_mutation_operations") == 0, "source_mutation")
    hashes = receipt.get("output_hashes")
    require(isinstance(hashes, dict), "source_output_hashes")
    for name in RAW_FILES:
        path = root / name
        require(path.is_file() and not path.is_symlink(), f"source_output_missing_or_symlink:{name}")
        require(hashes.get(name) == sha256_file(path), f"source_output_hash:{name}")
    return receipt


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def run(repo: Path, raw_final: Path, adapter_final: Path, status_path: Path, poll_seconds: int) -> dict[str, Any]:
    while True:
        state = remote_state()
        atomic_json(status_path, {"status": f"WAITING_NODE23_{state}", "remote_output": REMOTE_OUTPUT})
        if state == "RECEIPT_READY":
            break
        require(state == "RUNNING", f"node23_terminal_without_receipt:{state}")
        time.sleep(poll_seconds)

    if raw_final.exists():
        receipt = validate_source(raw_final)
    else:
        raw_final.parent.mkdir(parents=True, exist_ok=True)
        staging_parent = Path(tempfile.mkdtemp(prefix=f".{raw_final.name}.", dir=raw_final.parent))
        try:
            subprocess.run(["scp.exe", "-q", "-r", f"node23:{REMOTE_OUTPUT}", str(staging_parent)], check=True)
            downloaded = staging_parent / Path(REMOTE_OUTPUT).name
            receipt = validate_source(downloaded)
            os.replace(downloaded, raw_final)
        finally:
            if staging_parent.exists():
                shutil.rmtree(staging_parent)

    require(not adapter_final.exists(), f"adapter_final_already_exists:{adapter_final}")
    base = repo / "experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717"
    adapter_src = base / "adaptive_dual_targets_v3_20260718/src"
    sys.path.insert(0, str(adapter_src))
    materializer = load_module("adaptive_materializer", adapter_src / "materialize_adaptive_dual_targets_v3.py")
    v4d = repo / "experiments/phase2_5080_v1/prepared/pvrig_v6_v4d_open226_contact_teacher_v2_20260718"
    target = repo / "experiments/phase2_5080_v1/prepared/pvrig_v6_residue_v2_fixed_target_graphs_v1_20260718"
    materializer.materialize(
        training_tsv=base / "v2_4_fs_stack_prototype_v1_20260718/data_contract/materialized_v1/v6_supervised1507_v2_4.tsv",
        v4d_pair_tsv=v4d / "v4d_open226_multi_seed_pair_contact_teacher_v2.tsv.gz",
        v4d_marginal_tsv=v4d / "v4d_open226_multi_seed_residue_marginal_teacher_v2.tsv.gz",
        v4d_receipt=v4d / "RUN_RECEIPT.json",
        v4h_pair_tsv=raw_final / "v4h_adaptive_residue_pair_contact_teacher.tsv.gz",
        v4h_residue_tsv=raw_final / "v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz",
        v4h_candidate_tsv=raw_final / "v4h_adaptive_candidate_state.tsv.gz",
        v4h_receipt=raw_final / "RUN_RECEIPT.json",
        target_cache_npz=target / "target_graph_cache_v2.npz",
        target_manifest_tsv=target / "target_graph_manifest_v2.tsv",
        target_receipt=target / "target_graph_receipt_v2.json",
        output_root=adapter_final,
    )
    contract = adapter_final / materializer.CONTRACT_NAME
    prefreeze = load_module(
        "v2_prefreeze",
        base / "v2_4_fs_stack_prototype_v1_20260718/deployment/build_prefreeze_manifest_v2.py",
    )
    validation = prefreeze.validate_adaptive_inputs(
        input_contract_path=contract,
        expected_input_contract_sha256=sha256_file(contract),
        source_receipt_path=raw_final / "RUN_RECEIPT.json",
        v4d_source_receipt_path=v4d / "RUN_RECEIPT.json",
        marginal_table_path=adapter_final / "marginal" / materializer.marginal.OUTPUT_NAME,
        marginal_receipt_path=adapter_final / "marginal" / materializer.marginal.RECEIPT_NAME,
        pair_table_path=adapter_final / "pair" / materializer.pair.OUTPUT_NAME,
        pair_receipt_path=adapter_final / "pair" / materializer.pair.RECEIPT_NAME,
    )
    result = {
        "status": "PASS_NODE23_SYNC_ADAPTER_MATERIALIZATION_AND_PREFREEZE_VALIDATION",
        "raw_source_receipt_sha256": sha256_file(raw_final / "RUN_RECEIPT.json"),
        "adapter_materialization_receipt_sha256": sha256_file(adapter_final / materializer.RECEIPT_NAME),
        "adaptive_input_contract_sha256": sha256_file(contract),
        "prefreeze_validation_status": validation["status"],
        "source_counts": EXPECTED,
    }
    atomic_json(status_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", type=Path, required=True)
    value.add_argument("--raw-final", type=Path, required=True)
    value.add_argument("--adapter-final", type=Path, required=True)
    value.add_argument("--status-path", type=Path, required=True)
    value.add_argument("--poll-seconds", type=int, default=60)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run(args.repo.resolve(), args.raw_final, args.adapter_final, args.status_path, args.poll_seconds)
    except Exception as exc:
        atomic_json(args.status_path, {"status": "FAILED", "error": f"{type(exc).__name__}:{exc}"})
        raise
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
