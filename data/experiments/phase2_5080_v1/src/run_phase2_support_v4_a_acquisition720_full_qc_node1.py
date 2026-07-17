#!/usr/bin/env python3
"""Run the frozen Support V4-A 720 label-free Node1 Full-QC acquisition."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717")
INPUTS = ROOT / "inputs"
CASCADE = ROOT / "cascade"
OUTPUTS = ROOT / "outputs"
STATUS = ROOT / "status"
LOGS = ROOT / "logs"
MANIFEST = INPUTS / "support_v4_a_future_teacher_acquisition_pool_v1.tsv"
UPSTREAM_AUDIT = INPUTS / "support_v4_a_acquisition_readiness_audit_v1.json"
UPSTREAM_RECEIPT = INPUTS / "support_v4_a_acquisition_readiness_receipt_v1.json"
FASTA = INPUTS / "support_v4_a_acquisition720.fasta"
PREREG = ROOT / "phase2_support_v4_a_acquisition720_full_qc_v1_preregistration.json"
FREEZE = ROOT / "IMPLEMENTATION_FREEZE.json"
PACKAGE_RECEIPT = ROOT / "PACKAGE_RECEIPT.json"

SCREEN = Path("/data1/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py")
PYTHON = Path("/data1/qlyu/software/envs/vhh-eval/bin/python")
RUNTIME = Path("/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure")
RUNTIME_MANIFEST = RUNTIME / "RUNTIME_MANIFEST.json"

EXPECTED = {
    "manifest": "73454cbf8194d3faa5cad354a5b2f31f433e317d5222a6cd59906775fb56bfca",
    "upstream_audit": "19f7465978601b346b98b7cf9fe0385cf5b139db0e1bf1ae09a3dbae5b214f1e",
    "upstream_receipt": "440e675b1a6e39771a830d282e7e575dfe7ce24f7cb91c2966f71f577c655181",
    "screen": "051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a",
    "python": "33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095",
    "runtime_manifest": "603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d",
}
EXPECTED_FIELDS = [
    "candidate_id", "sequence", "sequence_sha256", "parent_id",
    "parent_framework_cluster", "parent_role", "target_patch_id", "design_mode",
    "cdr3", "cdr3_length", "max_positive_cdr_identity", "fast_qc_state",
    "selection_hash", "acquisition_role", "selection_rank_within_parent",
    "cdr3_min_normalized_edit_distance_to_previous", "claim_boundary",
]
FORBIDDEN_FIELD_TOKENS = (
    "model_score", "model_prediction", "docking", "geometry_label", "r_dual",
    "binding_label", "affinity", "experimental_label", "blocker_label",
)
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CLAIM = (
    "This run measures sequence and developability Full-QC only. It is not Docking, "
    "docking geometry, PVRIG binding, affinity, competition, experimental blocking, "
    "blocker probability, or a biological teacher label."
)
RESOURCE_POLICY = {
    "fast_chunk_size": 45,
    "full_chunk_size": 45,
    "chunk_jobs": 16,
    "full_chunk_jobs": 16,
    "workers_per_chunk": 2,
    "maximum_requested_cpu_workers": 32,
    "gpu_requested": 0,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.chmod(mode)
    os.replace(tmp, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError(f"missing_or_empty:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def fasta_records(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    candidate_id: str | None = None
    parts: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if candidate_id is not None:
                records.append((candidate_id, "".join(parts)))
            candidate_id, parts = line[1:].split()[0], []
        else:
            parts.append(line.strip())
    if candidate_id is not None:
        records.append((candidate_id, "".join(parts)))
    return records


def validate_input_contract(root: Path = ROOT) -> list[dict[str, str]]:
    inputs = root / "inputs"
    manifest = inputs / MANIFEST.name
    upstream_audit_path = inputs / UPSTREAM_AUDIT.name
    upstream_receipt_path = inputs / UPSTREAM_RECEIPT.name
    fasta = inputs / FASTA.name
    prereg_path = root / PREREG.name
    freeze_path = root / FREEZE.name
    package_receipt_path = root / PACKAGE_RECEIPT.name
    for path in (manifest, upstream_audit_path, upstream_receipt_path, fasta, prereg_path, freeze_path, package_receipt_path):
        if path.is_symlink():
            raise RuntimeError(f"symlink_forbidden:{path}")
    if sha256(manifest) != EXPECTED["manifest"]:
        raise RuntimeError("manifest_hash_mismatch")
    if sha256(upstream_audit_path) != EXPECTED["upstream_audit"]:
        raise RuntimeError("upstream_audit_hash_mismatch")
    if sha256(upstream_receipt_path) != EXPECTED["upstream_receipt"]:
        raise RuntimeError("upstream_receipt_hash_mismatch")

    fields, rows = read_tsv(manifest)
    if fields != EXPECTED_FIELDS:
        raise RuntimeError(f"manifest_schema_mismatch:{fields}")
    if any(any(token in field.lower() for token in FORBIDDEN_FIELD_TOKENS) for field in fields):
        raise RuntimeError("forbidden_model_label_or_docking_field")
    if len(rows) != 720:
        raise RuntimeError(f"expected_720_rows:{len(rows)}")
    if Counter(row["parent_framework_cluster"] for row in rows) != Counter({p: 36 for p in {r['parent_framework_cluster'] for r in rows}}) or len({r["parent_framework_cluster"] for r in rows}) != 20:
        raise RuntimeError("parent_20x36_closure_failed")
    if Counter(row["acquisition_role"] for row in rows) != Counter({"FUTURE_NODE1_TEACHER_ACQUISITION": 480, "LABEL_FREE_AUDIT": 240}):
        raise RuntimeError("acquisition_audit_480_240_closure_failed")
    if Counter(row["target_patch_id"] for row in rows) != Counter({"A_CENTER": 240, "B_LOWER": 240, "C_CROSS": 240}):
        raise RuntimeError("patch_3x240_closure_failed")
    if {row["parent_role"] for row in rows} != {"OPEN_TRAIN"} or {row["fast_qc_state"] for row in rows} != {"HARD_PASS"}:
        raise RuntimeError("parent_role_or_fast_qc_state_mismatch")
    for key in ("candidate_id", "sequence", "sequence_sha256", "cdr3"):
        if len({row[key] for row in rows}) != 720:
            raise RuntimeError(f"not_720_unique:{key}")
    if len({(row["parent_framework_cluster"], row["cdr3"]) for row in rows}) != 720:
        raise RuntimeError("parent_cdr3_uniqueness_failed")
    for row in rows:
        sequence = row["sequence"]
        if not sequence or set(sequence) - STANDARD_AA:
            raise RuntimeError(f"invalid_sequence:{row['candidate_id']}")
        if hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_sha256_mismatch:{row['candidate_id']}")
        if len(row["cdr3"]) != int(row["cdr3_length"]):
            raise RuntimeError(f"cdr3_length_mismatch:{row['candidate_id']}")

    fasta_rows = fasta_records(fasta)
    if fasta_rows != [(row["candidate_id"], row["sequence"]) for row in rows]:
        raise RuntimeError("fasta_manifest_order_or_sequence_mismatch")

    audit = json.loads(upstream_audit_path.read_text())
    upstream_receipt = json.loads(upstream_receipt_path.read_text())
    prereg = json.loads(prereg_path.read_text())
    freeze = json.loads(freeze_path.read_text())
    package_receipt = json.loads(package_receipt_path.read_text())
    if audit.get("selected_rows") != 720 or audit.get("acquisition_rows") != 480 or audit.get("audit_rows") != 240:
        raise RuntimeError("upstream_audit_count_closure_failed")
    if any(int(v) != 0 for v in audit.get("label_path_access", {}).values()):
        raise RuntimeError("upstream_audit_label_access_nonzero")
    if upstream_receipt.get("output_sha256", {}).get(MANIFEST.name) != EXPECTED["manifest"]:
        raise RuntimeError("upstream_receipt_manifest_binding_failed")
    if prereg.get("status") != "FROZEN_BEFORE_SUPPORT_V4_A_720_FULL_QC_EXECUTION":
        raise RuntimeError("preregistration_not_frozen")
    if any(int(v) != 0 for v in prereg.get("label_path_access", {}).values()):
        raise RuntimeError("preregistration_label_access_nonzero")
    if freeze.get("status") != "FROZEN_BEFORE_REMOTE_FULL_QC_EXECUTION":
        raise RuntimeError("implementation_freeze_not_frozen")
    if freeze.get("input_hashes", {}).get(MANIFEST.name) != EXPECTED["manifest"]:
        raise RuntimeError("implementation_freeze_manifest_binding_failed")
    if freeze.get("implementation_hashes", {}).get(Path(__file__).name) != sha256(Path(__file__).resolve()):
        raise RuntimeError("runner_self_hash_not_bound_by_freeze")
    if package_receipt.get("status") != "PASS_PACKAGE_HASH_CLOSED_BEFORE_REMOTE_EXECUTION":
        raise RuntimeError("package_receipt_not_pass")
    for rel, digest in package_receipt.get("outputs", {}).items():
        path = root / rel
        if not path.is_file() or path.is_symlink() or sha256(path) != digest:
            raise RuntimeError(f"package_receipt_output_hash_mismatch:{rel}")
    if package_receipt.get("label_or_model_fields_accepted") != 0:
        raise RuntimeError("package_receipt_label_or_model_acceptance_nonzero")
    return rows


def validate_runtime_contract() -> dict[str, Any]:
    if any(str(path).startswith("/data/qlyu/") for path in (ROOT, SCREEN, PYTHON, RUNTIME)):
        raise RuntimeError("nfs_data_prefix_forbidden")
    observed = {"screen": sha256(SCREEN), "python": sha256(PYTHON), "runtime_manifest": sha256(RUNTIME_MANIFEST)}
    for key, digest in observed.items():
        if digest != EXPECTED[key]:
            raise RuntimeError(f"runtime_hash_mismatch:{key}")
    manifest = json.loads(RUNTIME_MANIFEST.read_text())
    if manifest.get("status") != "PASS_SSD_RUNTIME_CLOSURE_FROZEN" or manifest.get("forbidden_runtime_prefix_hits") != 0:
        raise RuntimeError("runtime_manifest_not_ssd_closed")
    if manifest.get("runtime_root") != str(RUNTIME):
        raise RuntimeError("runtime_root_mismatch")
    for rel, metadata in manifest.get("files", {}).items():
        path = RUNTIME / rel
        if not path.is_file() or path.is_symlink() or path.stat().st_size != int(metadata["size"]) or sha256(path) != metadata["sha256"]:
            raise RuntimeError(f"runtime_file_closure_failed:{rel}")
    return {"observed_hashes": observed, "runtime_files": len(manifest.get("files", {})), "ssd_only": True}


def preflight(root: Path = ROOT, *, verify_runtime: bool = True) -> dict[str, Any]:
    rows = validate_input_contract(root)
    runtime = validate_runtime_contract() if verify_runtime else {"skipped_for_fixture": True}
    return {
        "schema_version": "phase2_support_v4_a_acquisition720_full_qc_preflight_v1",
        "status": "PASS_ZERO_WORK_PREFLIGHT",
        "candidate_count": len(rows),
        "parent_count": len({row["parent_framework_cluster"] for row in rows}),
        "resource_policy": RESOURCE_POLICY,
        "runtime": runtime,
        "label_path_access": {"model": 0, "docking": 0, "geometry": 0, "experimental": 0},
        "claim_boundary": CLAIM,
    }


def screen_command(stage: str) -> list[str]:
    return [
        str(PYTHON), str(SCREEN), str(FASTA), "-o", str(CASCADE),
        "--qc-bin", str(RUNTIME / "bin/vhh-competition-qc"),
        "--local-positive-cdr-csv", str(RUNTIME / "references/local_pvrig_positive_vhh_cdrs.csv"),
        "--muscle-bin", str(RUNTIME / "bin/muscle"), "--stage", stage,
        "--fast-chunk-size", "45", "--full-chunk-size", "45",
        "--chunk-jobs", "16", "--full-chunk-jobs", "16",
        "--workers", "2", "--tnp-ncores", "1", "--identity-cache-size", "500000",
        "--full-qc-limit", "0", "--geometry-limit", "720", "--geometry-pool-size", "720",
        "--geometry-cluster-limit", "720", "--skip-final-diversity",
    ]


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "PATH": f"{RUNTIME / 'bin'}:/data1/qlyu/anaconda3/envs/boltz/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": f"{RUNTIME / 'validator_src'}:{RUNTIME / 'src'}",
        "AB_DATA_VALIDATOR_SRC": str(RUNTIME / "validator_src"),
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false",
        "CUDA_VISIBLE_DEVICES": "",
    })
    if "/data/qlyu" in env["PATH"] or "/data/qlyu" in env["PYTHONPATH"]:
        raise RuntimeError("nfs_prefix_in_execution_environment")
    return env


def _hard_pass(row: dict[str, str]) -> bool:
    value = str(row.get("hard_fail", "")).lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"invalid_hard_fail:{row.get('candidate_id', '')}:{value}")
    return value == "false"


def aggregate_attrition(source: list[dict[str, str]], fast: list[dict[str, str]], full: list[dict[str, str]], group: str) -> list[dict[str, Any]]:
    fast_by = {row["candidate_id"]: row for row in fast}
    full_by = {row["candidate_id"]: row for row in full}
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in source:
        grouped[row[group]].append(row)
    output: list[dict[str, Any]] = []
    for value in sorted(grouped):
        rows = grouped[value]
        ids = [row["candidate_id"] for row in rows]
        fast_pass = sum(_hard_pass(fast_by[cid]) for cid in ids)
        full_rows = sum(cid in full_by for cid in ids)
        full_pass = sum(cid in full_by and _hard_pass(full_by[cid]) for cid in ids)
        output.append({
            group: value, "input_rows": len(ids), "fast_hard_pass": fast_pass,
            "fast_hard_fail": len(ids) - fast_pass, "full_rows": full_rows,
            "full_hard_pass": full_pass, "full_hard_fail": full_rows - full_pass,
            "fast_to_full_attrition": fast_pass - full_rows,
        })
    return output


def validate_and_publish_terminal(source: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads((CASCADE / "cascade_state.json").read_text())
    stages = state.get("stages", {})
    for stage in ("prepare", "fast", "merge_fast", "full", "merge_full"):
        if stages.get(stage, {}).get("status") != "complete":
            raise RuntimeError(f"cascade_stage_not_complete:{stage}")
    _, fast = read_tsv(CASCADE / "fast_merged.tsv")
    _, shortlist = read_tsv(CASCADE / "full_qc_shortlist.tsv")
    _, excluded = read_tsv(CASCADE / "full_qc_excluded_due_cap.tsv") if (CASCADE / "full_qc_excluded_due_cap.tsv").stat().st_size else ([], [])
    _, full = read_tsv(CASCADE / "full_merged.tsv")
    expected_ids = {row["candidate_id"] for row in source}
    fast_ids = [row.get("candidate_id", "") for row in fast]
    shortlist_ids = [row.get("candidate_id", "") for row in shortlist]
    full_ids = [row.get("candidate_id", "") for row in full]
    if len(fast_ids) != 720 or len(set(fast_ids)) != 720 or set(fast_ids) != expected_ids:
        raise RuntimeError("fast_720_exact_id_closure_failed")
    fast_pass_ids = {row["candidate_id"] for row in fast if _hard_pass(row)}
    if excluded:
        raise RuntimeError("full_qc_cap_excluded_nonempty")
    if len(shortlist_ids) != len(set(shortlist_ids)) or set(shortlist_ids) != fast_pass_ids:
        raise RuntimeError("all_fast_survivors_shortlist_closure_failed")
    if len(full_ids) != len(set(full_ids)) or set(full_ids) != fast_pass_ids:
        raise RuntimeError("full_merged_all_survivors_no_replacement_closure_failed")
    expected_fast_chunks = math.ceil(720 / RESOURCE_POLICY["fast_chunk_size"])
    expected_full_chunks = math.ceil(len(fast_pass_ids) / RESOURCE_POLICY["full_chunk_size"]) if fast_pass_ids else 0
    fast_chunks = list((CASCADE / "fast_chunks").glob("chunk_*/complete.json"))
    full_chunks = list((CASCADE / "full_chunks").glob("chunk_*/complete.json"))
    if len(fast_chunks) != expected_fast_chunks or len(full_chunks) != expected_full_chunks:
        raise RuntimeError(f"chunk_completion_closure_failed:{len(fast_chunks)}:{len(full_chunks)}")

    attrition_specs = [
        ("parent_framework_cluster", "full_qc_attrition_by_parent.tsv"),
        ("acquisition_role", "full_qc_attrition_by_role.tsv"),
        ("target_patch_id", "full_qc_attrition_by_patch.tsv"),
    ]
    attrition_hashes: dict[str, str] = {}
    for group, name in attrition_specs:
        rows = aggregate_attrition(source, fast, full, group)
        fields = [group, "input_rows", "fast_hard_pass", "fast_hard_fail", "full_rows", "full_hard_pass", "full_hard_fail", "fast_to_full_attrition"]
        path = OUTPUTS / name
        write_tsv(path, rows, fields)
        attrition_hashes[name] = sha256(path)

    summary = {
        "schema_version": "phase2_support_v4_a_acquisition720_full_qc_terminal_summary_v1",
        "status": "PASS_SUPPORT_V4_A_ACQUISITION720_SEQUENCE_DEVELOPABILITY_FULL_QC_COMPLETE",
        "published_at_utc": now(),
        "input_rows": 720,
        "fast_rows": len(fast), "fast_hard_pass": len(fast_pass_ids), "fast_hard_fail": 720 - len(fast_pass_ids),
        "full_rows": len(full), "full_hard_pass": sum(_hard_pass(row) for row in full),
        "full_hard_fail": sum(not _hard_pass(row) for row in full),
        "no_replacement": True, "full_qc_limit": 0, "tnp_run": False,
        "tnp_policy": "DEFERRED_NO_IMPUTATION", "resource_policy": RESOURCE_POLICY,
        "screen_source_sha256": EXPECTED["screen"], "runtime_manifest_sha256": EXPECTED["runtime_manifest"],
        "input_manifest_sha256": EXPECTED["manifest"],
        "cascade_output_sha256": {name: sha256(CASCADE / name) for name in ("fast_merged.tsv", "full_qc_shortlist.tsv", "full_merged.tsv", "cascade_state.json")},
        "attrition_output_sha256": attrition_hashes,
        "label_path_access": {"model": 0, "docking": 0, "geometry": 0, "experimental": 0},
        "claim_boundary": CLAIM,
    }
    atomic_json(OUTPUTS / "full_qc_terminal_summary.json", summary, 0o444)
    return summary


def run() -> int:
    STATUS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    lock_handle = (STATUS / "runner.lock").open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("runner_already_active")
    running = {"status": "RUNNING_SUPPORT_V4_A_ACQUISITION720_FULL_QC", "pid": os.getpid(), "started_at_utc": now(), "resource_policy": RESOURCE_POLICY, "claim_boundary": CLAIM}
    atomic_json(STATUS / "runner.running.json", running)
    source = validate_input_contract()
    validate_runtime_contract()
    env = clean_env()
    for stage in ("prepare", "fast", "full"):
        command = screen_command(stage)
        print(json.dumps({"started_at_utc": now(), "stage": stage, "command": command}), flush=True)
        completed = subprocess.run(command, env=env, check=False)
        if completed.returncode:
            raise RuntimeError(f"screen_stage_failed:{stage}:rc={completed.returncode}")
    summary = validate_and_publish_terminal(source)
    completion = {**summary, "runner_pid": os.getpid(), "finished_at_utc": now(), "terminal_summary_sha256": sha256(OUTPUTS / "full_qc_terminal_summary.json")}
    atomic_json(STATUS / "runner.complete.json", completion, 0o444)
    (STATUS / "runner.running.json").unlink(missing_ok=True)
    print(json.dumps(completion, indent=2, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        print(json.dumps({"status": "PASS_RUNNER_SHELL_SMOKE", "root": str(ROOT), "cpu_max": 32, "gpu": 0, "stages": ["prepare", "fast", "full"]}, sort_keys=True))
        return 0
    if args.preflight:
        result = preflight()
        atomic_json(STATUS / "zero_work_preflight.json", result, 0o444)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    try:
        return run()
    except BaseException as error:
        failure = {"status": "FAIL_SUPPORT_V4_A_ACQUISITION720_FULL_QC", "failed_at_utc": now(), "error": f"{type(error).__name__}:{error}", "pid": os.getpid(), "claim_boundary": CLAIM}
        atomic_json(STATUS / "runner.failed.json", failure, 0o444)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
