#!/usr/bin/env python3
"""Run the frozen V4-F96 sequence/developability Full-QC recovery on Node1 SSD."""
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/data1/qlyu/projects/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717")
INPUTS, CASCADE, OUTPUTS, STATUS, LOGS = (ROOT / name for name in ("inputs", "cascade", "outputs", "status", "logs"))
MANIFEST = INPUTS / "prospective_holdout96_manifest.tsv"
UPSTREAM_AUDIT = INPUTS / "prospective_holdout96_audit.json"
UPSTREAM_RECEIPT = INPUTS / "prospective_holdout96_receipt.json"
FASTA = INPUTS / "holdout96.fasta"
LINEAGE = INPUTS / "holdout96_lineage.tsv"
PREREG = ROOT / "phase2_v4_f_holdout96_full_qc_recovery_v2_preregistration.json"
FREEZE = ROOT / "IMPLEMENTATION_FREEZE.json"
PACKAGE_RECEIPT = ROOT / "PACKAGE_RECEIPT.json"

SCREEN = Path("/data1/qlyu/software/vhh_eval_tools/competition_qc/vhh_large_scale_screen.py")
PYTHON = Path("/data1/qlyu/software/envs/vhh-eval/bin/python")
RUNTIME = Path("/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure")
RUNTIME_MANIFEST = RUNTIME / "RUNTIME_MANIFEST.json"

EXPECTED = {
    "manifest": "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334",
    "upstream_audit": "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1",
    "upstream_receipt": "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f",
    "prereg": "b9d539f8936992df330e7ad844604d7d81114547e99de82b1a1fcbcbeecbebcb",
    "screen": "051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a",
    "python": "33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095",
    "runtime_manifest": "603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d",
}
EXPECTED_FIELDS = [
    "candidate_id", "sequence_sha256", "sequence", "parent_id", "parent_framework_cluster",
    "design_method", "design_mode", "target_patch_id", "cdr1", "cdr2", "cdr3", "cdr3_length",
    "model_split", "selection_stratum", "full_qc_and_docking_policy", "claim_boundary",
]
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
RESOURCE_POLICY = {
    "cpu_affinity": "0-23", "fast_chunk_size": 12, "full_chunk_size": 12,
    "chunk_jobs": 8, "full_chunk_jobs": 8, "workers_per_chunk": 3,
    "maximum_requested_cpu_workers": 24, "gpu_requested": 0,
}
CLAIM = (
    "Sequence and developability Full-QC evidence only. This is not Docking, docking geometry, "
    "PVRIG binding, affinity, competition, experimental blocking, blocker probability, or Docking Gold."
)


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
        writer.writeheader(); writer.writerows(rows)
    os.replace(tmp, path)


def fasta_records(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    cid: str | None = None
    parts: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if cid is not None:
                records.append((cid, "".join(parts)))
            cid, parts = line[1:].split()[0], []
        else:
            parts.append(line.strip())
    if cid is not None:
        records.append((cid, "".join(parts)))
    return records


def validate_input_contract(root: Path = ROOT) -> list[dict[str, str]]:
    paths = {
        "manifest": root / "inputs" / MANIFEST.name,
        "upstream_audit": root / "inputs" / UPSTREAM_AUDIT.name,
        "upstream_receipt": root / "inputs" / UPSTREAM_RECEIPT.name,
        "prereg": root / PREREG.name,
    }
    for key, path in paths.items():
        if not path.is_file() or path.is_symlink() or sha256(path) != EXPECTED[key]:
            raise RuntimeError(f"frozen_input_hash_or_type_mismatch:{key}")
    fields, rows = read_tsv(paths["manifest"])
    if fields != EXPECTED_FIELDS or len(rows) != 96:
        raise RuntimeError("manifest_schema_or_count_mismatch")
    for key in ("candidate_id", "sequence_sha256", "sequence"):
        if len({row[key] for row in rows}) != 96:
            raise RuntimeError(f"not_96_unique:{key}")
    if Counter(row["parent_framework_cluster"] for row in rows) != Counter({p: 24 for p in {r['parent_framework_cluster'] for r in rows}}) or len({r["parent_framework_cluster"] for r in rows}) != 4:
        raise RuntimeError("parent_4x24_closure_failed")
    if Counter(row["target_patch_id"] for row in rows) != Counter({"A_CENTER": 32, "B_LOWER": 32, "C_CROSS": 32}):
        raise RuntimeError("patch_balance_failed")
    if Counter(row["design_mode"] for row in rows) != Counter({"H3": 48, "H1H3": 48}):
        raise RuntimeError("design_mode_balance_failed")
    if set(Counter(row["selection_stratum"] for row in rows).values()) != {4}:
        raise RuntimeError("selection_stratum_4_each_failed")
    frozen_policy = "run_full_qc_on_all_96_then_dock_every_full_qc_hard_pass;no_model_score_reselection"
    for row in rows:
        sequence = row["sequence"]
        if not sequence or set(sequence) - STANDARD_AA or hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_closure_failed:{row['candidate_id']}")
        if row["model_split"] != "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT" or row["full_qc_and_docking_policy"] != frozen_policy:
            raise RuntimeError(f"split_or_policy_mismatch:{row['candidate_id']}")
    fasta = root / "inputs" / FASTA.name
    lineage = root / "inputs" / LINEAGE.name
    lineage_fields, lineage_rows = read_tsv(lineage)
    if lineage_fields != fields or lineage_rows != rows:
        raise RuntimeError("lineage_manifest_exact_closure_failed")
    if fasta_records(fasta) != [(row["candidate_id"], row["sequence"]) for row in rows]:
        raise RuntimeError("fasta_manifest_exact_closure_failed")

    audit = json.loads(paths["upstream_audit"].read_text())
    receipt = json.loads(paths["upstream_receipt"].read_text())
    prereg = json.loads(paths["prereg"].read_text())
    if audit.get("status") != "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN" or audit.get("checks", {}).get("row_count") != 96:
        raise RuntimeError("upstream_audit_not_frozen")
    if audit.get("output", {}).get("sha256") != EXPECTED["manifest"]:
        raise RuntimeError("upstream_audit_manifest_binding_failed")
    if receipt.get("status") != "PASS_COMPLETE_HASH_CLOSURE" or receipt.get("manifest_sha256") != EXPECTED["manifest"] or receipt.get("audit_file_sha256") != EXPECTED["upstream_audit"]:
        raise RuntimeError("upstream_receipt_closure_failed")
    if prereg.get("status") != "FROZEN_BEFORE_V4_F96_RECOVERY_V2_PACKAGE_OR_REMOTE_EXECUTION" or any(int(v) for v in prereg.get("label_path_access", {}).values()):
        raise RuntimeError("preregistration_not_label_free_and_frozen")

    freeze_path, package_path = root / FREEZE.name, root / PACKAGE_RECEIPT.name
    for path in (freeze_path, package_path):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"package_control_missing_or_symlink:{path.name}")
    freeze = json.loads(freeze_path.read_text())
    package = json.loads(package_path.read_text())
    if freeze.get("status") != "FROZEN_BEFORE_REMOTE_EXECUTION" or freeze.get("input_hashes", {}).get(MANIFEST.name) != EXPECTED["manifest"]:
        raise RuntimeError("implementation_freeze_not_closed")
    if freeze.get("implementation_hashes", {}).get(Path(__file__).name) != sha256(Path(__file__).resolve()):
        raise RuntimeError("runner_self_hash_not_frozen")
    if package.get("status") != "PASS_V4_F96_FULL_QC_RECOVERY_V2_PACKAGE_HASH_CLOSED" or package.get("candidate_count") != 96 or package.get("label_or_model_fields_accepted") != 0:
        raise RuntimeError("package_receipt_not_closed")
    for rel, digest in package.get("outputs", {}).items():
        path = root / rel
        if not path.is_file() or path.is_symlink() or sha256(path) != digest:
            raise RuntimeError(f"package_output_hash_mismatch:{rel}")
    return rows


def validate_runtime_contract() -> dict[str, Any]:
    if any(str(path).startswith("/data/qlyu/") for path in (ROOT, SCREEN, PYTHON, RUNTIME)):
        raise RuntimeError("nfs_data_prefix_forbidden")
    observed = {"screen": sha256(SCREEN), "python": sha256(PYTHON), "runtime_manifest": sha256(RUNTIME_MANIFEST)}
    for key, digest in observed.items():
        if digest != EXPECTED[key]:
            raise RuntimeError(f"runtime_hash_mismatch:{key}")
    manifest = json.loads(RUNTIME_MANIFEST.read_text())
    if manifest.get("status") != "PASS_SSD_RUNTIME_CLOSURE_FROZEN" or manifest.get("forbidden_runtime_prefix_hits") != 0 or manifest.get("runtime_root") != str(RUNTIME):
        raise RuntimeError("runtime_manifest_not_ssd_closed")
    for rel, metadata in manifest.get("files", {}).items():
        path = RUNTIME / rel
        if not path.is_file() or path.is_symlink() or path.stat().st_size != int(metadata["size"]) or sha256(path) != metadata["sha256"]:
            raise RuntimeError(f"runtime_file_closure_failed:{rel}")
    return {"observed_hashes": observed, "runtime_files": len(manifest.get("files", {})), "ssd_only": True}


def preflight(root: Path = ROOT, verify_runtime: bool = True) -> dict[str, Any]:
    rows = validate_input_contract(root)
    return {
        "schema_version": "phase2_v4_f_holdout96_full_qc_recovery_v2_preflight",
        "status": "PASS_ZERO_WORK_PREFLIGHT", "candidate_count": len(rows),
        "resource_policy": RESOURCE_POLICY,
        "runtime": validate_runtime_contract() if verify_runtime else {"skipped_for_fixture": True},
        "label_path_access": {"model": 0, "docking": 0, "geometry": 0, "experimental": 0, "v4_f_predictions": 0},
        "claim_boundary": CLAIM,
    }


def screen_command(stage: str) -> list[str]:
    return [
        str(PYTHON), str(SCREEN), str(FASTA), "-o", str(CASCADE),
        "--qc-bin", str(RUNTIME / "bin/vhh-competition-qc"),
        "--local-positive-cdr-csv", str(RUNTIME / "references/local_pvrig_positive_vhh_cdrs.csv"),
        "--muscle-bin", str(RUNTIME / "bin/muscle"), "--stage", stage,
        "--fast-chunk-size", "12", "--full-chunk-size", "12",
        "--chunk-jobs", "8", "--full-chunk-jobs", "8", "--workers", "3",
        "--tnp-ncores", "1", "--identity-cache-size", "500000", "--full-qc-limit", "0",
        "--geometry-limit", "96", "--geometry-pool-size", "96", "--geometry-cluster-limit", "96",
        "--skip-final-diversity",
    ]


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "PATH": f"{RUNTIME / 'bin'}:/data1/qlyu/anaconda3/envs/boltz/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONPATH": f"{RUNTIME / 'validator_src'}:{RUNTIME / 'src'}", "AB_DATA_VALIDATOR_SRC": str(RUNTIME / "validator_src"),
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false", "CUDA_VISIBLE_DEVICES": "",
    })
    if "/data/qlyu" in env["PATH"] or "/data/qlyu" in env["PYTHONPATH"]:
        raise RuntimeError("nfs_prefix_in_execution_environment")
    return env


def hard_pass(row: dict[str, str]) -> bool:
    value = str(row.get("hard_fail", "")).lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"invalid_hard_fail:{row.get('candidate_id', '')}:{value}")
    return value == "false"


def validate_and_publish_terminal(source: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads((CASCADE / "cascade_state.json").read_text())
    for stage in ("prepare", "fast", "merge_fast", "full", "merge_full"):
        if state.get("stages", {}).get(stage, {}).get("status") != "complete":
            raise RuntimeError(f"cascade_stage_not_complete:{stage}")
    _, fast = read_tsv(CASCADE / "fast_merged.tsv")
    _, shortlist = read_tsv(CASCADE / "full_qc_shortlist.tsv")
    excluded_path = CASCADE / "full_qc_excluded_due_cap.tsv"
    excluded = read_tsv(excluded_path)[1] if excluded_path.is_file() and excluded_path.stat().st_size else []
    _, full = read_tsv(CASCADE / "full_merged.tsv")
    expected_ids = {row["candidate_id"] for row in source}
    fast_ids = [row.get("candidate_id", "") for row in fast]
    shortlist_ids = [row.get("candidate_id", "") for row in shortlist]
    full_ids = [row.get("candidate_id", "") for row in full]
    if len(fast_ids) != 96 or len(set(fast_ids)) != 96 or set(fast_ids) != expected_ids:
        raise RuntimeError("fast_exact_96_id_closure_failed")
    fast_pass_ids = {row["candidate_id"] for row in fast if hard_pass(row)}
    if excluded or set(shortlist_ids) != fast_pass_ids or len(shortlist_ids) != len(set(shortlist_ids)):
        raise RuntimeError("all_fast_survivors_shortlist_no_cap_closure_failed")
    if set(full_ids) != fast_pass_ids or len(full_ids) != len(set(full_ids)):
        raise RuntimeError("full_merged_all_survivors_no_replacement_closure_failed")
    if len(list((CASCADE / "fast_chunks").glob("chunk_*/complete.json"))) != 8:
        raise RuntimeError("fast_chunk_completion_closure_failed")
    expected_full_chunks = math.ceil(len(fast_pass_ids) / 12) if fast_pass_ids else 0
    if len(list((CASCADE / "full_chunks").glob("chunk_*/complete.json"))) != expected_full_chunks:
        raise RuntimeError("full_chunk_completion_closure_failed")

    tnp_rows = []
    for row in source:
        state_name = "DEFERRED_UNRUN" if row["candidate_id"] in fast_pass_ids else "UPSTREAM_FAST_HARD_FAIL_NA"
        tnp_rows.append({"candidate_id": row["candidate_id"], "tnp_supervision_state": state_name, "tnp_score": "", "tnp_flag": ""})
    tnp_path = OUTPUTS / "tnp_three_state_unrun_summary.tsv"
    write_tsv(tnp_path, tnp_rows, ["candidate_id", "tnp_supervision_state", "tnp_score", "tnp_flag"])
    tnp_counts = Counter(row["tnp_supervision_state"] for row in tnp_rows)

    summary = {
        "schema_version": "phase2_v4_f_holdout96_full_qc_recovery_v2_terminal_summary",
        "status": "PASS_V4_F96_SEQUENCE_DEVELOPABILITY_FULL_QC_RECOVERY_V2_COMPLETE",
        "published_at_utc": now(), "input_rows": 96,
        "fast_rows": len(fast), "fast_hard_pass": len(fast_pass_ids), "fast_hard_fail": 96 - len(fast_pass_ids),
        "full_rows": len(full), "full_hard_pass": sum(hard_pass(row) for row in full), "full_hard_fail": sum(not hard_pass(row) for row in full),
        "no_replacement": True, "model_based_selection": False, "full_qc_limit": 0,
        "tnp_run": False, "tnp_policy": "DEFERRED_NO_IMPUTATION_THREE_STATE", "tnp_state_counts": dict(sorted(tnp_counts.items())),
        "tnp_numeric_or_flag_nonblank": sum(bool(row["tnp_score"] or row["tnp_flag"]) for row in tnp_rows),
        "resource_policy": RESOURCE_POLICY, "screen_source_sha256": EXPECTED["screen"],
        "runtime_manifest_sha256": EXPECTED["runtime_manifest"], "input_manifest_sha256": EXPECTED["manifest"],
        "cascade_output_sha256": {name: sha256(CASCADE / name) for name in ("fast_merged.tsv", "full_qc_shortlist.tsv", "full_merged.tsv", "cascade_state.json")},
        "tnp_state_summary_sha256": sha256(tnp_path),
        "label_path_access": {"model": 0, "docking": 0, "geometry": 0, "experimental": 0, "v4_f_predictions": 0},
        "claim_boundary": CLAIM,
    }
    atomic_json(OUTPUTS / "full_qc_terminal_summary.json", summary, 0o444)
    return summary


def run() -> int:
    for path in (STATUS, LOGS, OUTPUTS): path.mkdir(parents=True, exist_ok=True)
    lock_handle = (STATUS / "runner.lock").open("w")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("runner_already_active")
    atomic_json(STATUS / "runner.running.json", {"status": "RUNNING_V4_F96_FULL_QC_RECOVERY_V2", "pid": os.getpid(), "started_at_utc": now(), "resource_policy": RESOURCE_POLICY, "claim_boundary": CLAIM})
    source = validate_input_contract(); validate_runtime_contract(); env = clean_env()
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
    parser = argparse.ArgumentParser(); parser.add_argument("--preflight", action="store_true"); parser.add_argument("--smoke-test", action="store_true"); args = parser.parse_args()
    if args.smoke_test:
        print(json.dumps({"status": "PASS_V4_F96_RECOVERY_V2_RUNNER_SMOKE", "root": str(ROOT), "cpu_max": 24, "cpu_affinity": "0-23", "gpu": 0}, sort_keys=True)); return 0
    if args.preflight:
        result = preflight(); atomic_json(STATUS / "zero_work_preflight.json", result, 0o444); print(json.dumps(result, indent=2, sort_keys=True)); return 0
    try:
        return run()
    except BaseException as error:
        failure = {"status": "FAIL_V4_F96_FULL_QC_RECOVERY_V2", "failed_at_utc": now(), "error": f"{type(error).__name__}:{error}", "pid": os.getpid(), "claim_boundary": CLAIM}
        atomic_json(STATUS / "runner.failed.json", failure, 0o444); print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
