#!/usr/bin/env python3
"""Build and verify the frozen V4-F96 Node1 SSD Full-QC recovery V2 package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE2 = Path(__file__).resolve().parents[1]
SRC = Path(__file__).resolve().parent
SPLIT = PHASE2 / "data_splits/pvrig_v4_f"
DEFAULT_MANIFEST = SPLIT / "prospective_holdout96_manifest.tsv"
DEFAULT_AUDIT = SPLIT / "prospective_holdout96_audit.json"
DEFAULT_RECEIPT = SPLIT / "prospective_holdout96_receipt.json"
DEFAULT_PREREG = PHASE2 / "audits/phase2_v4_f_holdout96_full_qc_recovery_v2_preregistration.json"
DEFAULT_RUNNER = SRC / "run_phase2_v4_f_holdout96_full_qc_recovery_v2_node1.py"
DEFAULT_TEMPLATE = SRC / "templates/pvrig_v4_f_holdout96_full_qc_recovery_v2_waiter.sh.in"
DEFAULT_TEST = SRC / "test_build_phase2_v4_f_holdout96_full_qc_recovery_v2.py"
DEFAULT_OUTPUT = PHASE2 / "prepared/pvrig_v4_f_holdout96_full_qc_recovery_v2"
DEFAULT_FREEZE = PHASE2 / "audits/phase2_v4_f_holdout96_full_qc_recovery_v2_implementation_freeze.json"

EXPECTED = {
    "manifest": "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334",
    "audit": "fc24cc2bd203100e29be897e87850a67ddc362b1fa1635d4172ec4335f5083a1",
    "receipt": "3adc1e3194bdc5846f35b99020c3c996859caf3e3abc2b8e02df6ac75296512f",
    "prereg": "b9d539f8936992df330e7ad844604d7d81114547e99de82b1a1fcbcbeecbebcb",
    "screen": "051afdde9a1aaf41532a104fdb245ccd07c77d64448c8d7df9533db11a5e5d0a",
    "python": "33de598423ed1c2a7d65e8057df2b8831a0422ad51ae385c6cf362fd0d518095",
    "runtime_manifest": "603985f4af78151bbdb0b8ed8a3f2de8448f3bca57b011bbc2585a4754a6cc5d",
}
FIELDS = [
    "candidate_id", "sequence_sha256", "sequence", "parent_id", "parent_framework_cluster",
    "design_method", "design_mode", "target_patch_id", "cdr1", "cdr2", "cdr3", "cdr3_length",
    "model_split", "selection_stratum", "full_qc_and_docking_policy", "claim_boundary",
]
REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717"
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CLAIM = "Sequence and developability Full-QC evidence only; not Docking, geometry, binding, affinity, competition, experimental blocking, blocker probability, or Docking Gold."


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(name, mode); os.replace(name, path)
    finally:
        if Path(name).exists(): Path(name).unlink()


def jbytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def validate_sources(manifest: Path = DEFAULT_MANIFEST, audit: Path = DEFAULT_AUDIT, receipt: Path = DEFAULT_RECEIPT, prereg: Path = DEFAULT_PREREG) -> tuple[list[dict[str, str]], dict[str, str]]:
    observed = {"manifest": sha256(manifest), "audit": sha256(audit), "receipt": sha256(receipt), "prereg": sha256(prereg)}
    if observed != {key: EXPECTED[key] for key in observed}:
        raise RuntimeError(f"frozen_source_hash_mismatch:{observed}")
    fields, rows = read_tsv(manifest)
    if fields != FIELDS or len(rows) != 96:
        raise RuntimeError("manifest_schema_or_count_mismatch")
    if any(len({row[key] for row in rows}) != 96 for key in ("candidate_id", "sequence_sha256", "sequence")):
        raise RuntimeError("candidate_identity_uniqueness_failed")
    parents = {row["parent_framework_cluster"] for row in rows}
    if len(parents) != 4 or Counter(row["parent_framework_cluster"] for row in rows) != Counter({p: 24 for p in parents}):
        raise RuntimeError("parent_4x24_failed")
    if Counter(row["target_patch_id"] for row in rows) != Counter({"A_CENTER": 32, "B_LOWER": 32, "C_CROSS": 32}) or Counter(row["design_mode"] for row in rows) != Counter({"H3": 48, "H1H3": 48}):
        raise RuntimeError("balance_failed")
    frozen_policy = "run_full_qc_on_all_96_then_dock_every_full_qc_hard_pass;no_model_score_reselection"
    for row in rows:
        sequence = row["sequence"]
        if not sequence or set(sequence) - STANDARD_AA or hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_failed:{row['candidate_id']}")
        if row["model_split"] != "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT" or row["full_qc_and_docking_policy"] != frozen_policy:
            raise RuntimeError(f"frozen_policy_failed:{row['candidate_id']}")
    a, q, p = (json.loads(path.read_text()) for path in (audit, receipt, prereg))
    if a.get("status") != "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN" or a.get("output", {}).get("sha256") != EXPECTED["manifest"] or a.get("checks", {}).get("row_count") != 96:
        raise RuntimeError("audit_closure_failed")
    if q.get("status") != "PASS_COMPLETE_HASH_CLOSURE" or q.get("manifest_sha256") != EXPECTED["manifest"] or q.get("audit_file_sha256") != EXPECTED["audit"]:
        raise RuntimeError("receipt_closure_failed")
    if p.get("status") != "FROZEN_BEFORE_V4_F96_RECOVERY_V2_PACKAGE_OR_REMOTE_EXECUTION" or any(int(v) for v in p.get("label_path_access", {}).values()):
        raise RuntimeError("prereg_closure_failed")
    return rows, observed


def validate_shell(path: Path) -> dict[str, Any]:
    syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    if syntax.returncode:
        raise RuntimeError(f"waiter_syntax:{syntax.stderr}")
    smoke = subprocess.run(["bash", str(path), "--smoke-test"], capture_output=True, text=True)
    if smoke.returncode:
        raise RuntimeError(f"waiter_smoke:{smoke.stderr}")
    payload = json.loads(smoke.stdout)
    if payload != {"status": "PASS_V4_F96_RECOVERY_V2_WAITER_SMOKE", "root": REMOTE_ROOT, "structure_root": "/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_monomer_structures_v1_20260717", "cpu_affinity": "0-23", "maximum_cpu_workers": 24, "gpu": 0}:
        raise RuntimeError(f"waiter_smoke_contract:{payload}")
    return payload


def build(output: Path = DEFAULT_OUTPUT, freeze_out: Path = DEFAULT_FREEZE) -> dict[str, Any]:
    rows, source_hashes = validate_sources()
    if output.exists():
        if any(output.iterdir()): raise RuntimeError(f"nonempty_output:{output}")
    else: output.mkdir(parents=True)
    (output / "inputs").mkdir()
    for source in (DEFAULT_MANIFEST, DEFAULT_AUDIT, DEFAULT_RECEIPT):
        shutil.copyfile(source, output / "inputs" / source.name)
    shutil.copyfile(DEFAULT_PREREG, output / DEFAULT_PREREG.name)
    shutil.copyfile(DEFAULT_RUNNER, output / DEFAULT_RUNNER.name)
    (output / DEFAULT_RUNNER.name).chmod(0o755)
    fasta = "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in rows).encode()
    atomic(output / "inputs/holdout96.fasta", fasta)
    shutil.copyfile(DEFAULT_MANIFEST, output / "inputs/holdout96_lineage.tsv")
    runner_sha = sha256(output / DEFAULT_RUNNER.name)
    waiter = DEFAULT_TEMPLATE.read_text().replace("@RUNNER_SHA@", runner_sha).encode()
    atomic(output / "wait_for_support_v4a720_structures_then_run_full_qc.sh", waiter, 0o755)
    validate_shell(output / "wait_for_support_v4a720_structures_then_run_full_qc.sh")
    freeze = {
        "schema_version": "phase2_v4_f_holdout96_full_qc_recovery_v2_implementation_freeze",
        "status": "FROZEN_BEFORE_REMOTE_EXECUTION", "frozen_at_utc": now(),
        "input_hashes": {
            DEFAULT_MANIFEST.name: EXPECTED["manifest"], DEFAULT_AUDIT.name: EXPECTED["audit"],
            DEFAULT_RECEIPT.name: EXPECTED["receipt"], "holdout96.fasta": sha256(output / "inputs/holdout96.fasta"),
            "holdout96_lineage.tsv": sha256(output / "inputs/holdout96_lineage.tsv"),
        },
        "implementation_hashes": {
            Path(__file__).name: sha256(Path(__file__).resolve()), DEFAULT_RUNNER.name: runner_sha,
            DEFAULT_TEMPLATE.name: sha256(DEFAULT_TEMPLATE), DEFAULT_TEST.name: sha256(DEFAULT_TEST),
            "wait_for_support_v4a720_structures_then_run_full_qc.sh": sha256(output / "wait_for_support_v4a720_structures_then_run_full_qc.sh"),
        },
        "preregistration_sha256": EXPECTED["prereg"],
        "remote_bindings": {"remote_root": REMOTE_ROOT, "screen_sha256": EXPECTED["screen"], "python_sha256": EXPECTED["python"], "runtime_manifest_sha256": EXPECTED["runtime_manifest"]},
        "start_gate": {"structure_runner_terminal_and_process_free": True, "load1_max": 8.0, "structure_prereg_sha256": "9af5a9913addf2472e57c75fb1228eb8e9c77213f2d89c819d710581b1c233f6", "structure_runner_sha256": "3fe3be1da1591afca05c1e80d38911422645aaec421f7ce0ce803e7271e86c47", "structure_freeze_sha256": "71fa231196bc64c2661496889fa087e54d254e72e9071b966a3a915df741881b"},
        "resource_policy": {"cpu_affinity": "0-23", "maximum_cpu_workers": 24, "gpu_requested": 0},
        "execution_policy": "all frozen 96 -> Fast-QC -> every hard-pass Full-QC; no model selection; no replacement; TNP deferred explicit unrun/NA",
        "label_path_access": {"model": 0, "docking": 0, "geometry": 0, "experimental": 0, "v4_f_predictions": 0},
        "claim_boundary": CLAIM,
    }
    atomic(freeze_out, jbytes(freeze), 0o444)
    shutil.copyfile(freeze_out, output / "IMPLEMENTATION_FREEZE.json")
    rels = [
        f"inputs/{DEFAULT_MANIFEST.name}", f"inputs/{DEFAULT_AUDIT.name}", f"inputs/{DEFAULT_RECEIPT.name}",
        "inputs/holdout96.fasta", "inputs/holdout96_lineage.tsv", DEFAULT_PREREG.name,
        DEFAULT_RUNNER.name, "wait_for_support_v4a720_structures_then_run_full_qc.sh", "IMPLEMENTATION_FREEZE.json",
    ]
    receipt = {
        "schema_version": "phase2_v4_f_holdout96_full_qc_recovery_v2_package_receipt",
        "status": "PASS_V4_F96_FULL_QC_RECOVERY_V2_PACKAGE_HASH_CLOSED", "published_at_utc": now(),
        "candidate_count": 96, "outputs": {rel: sha256(output / rel) for rel in rels}, "source_hashes": source_hashes,
        "label_or_model_fields_accepted": 0, "remote_execution_started": False,
        "receipt_publication_order": "LAST_AFTER_PACKAGE_AND_IMPLEMENTATION_FREEZE_HASH_CLOSURE", "claim_boundary": CLAIM,
    }
    atomic(output / "PACKAGE_RECEIPT.json", jbytes(receipt), 0o444)
    return validate_package(output)


def validate_package(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    receipt = json.loads((output / "PACKAGE_RECEIPT.json").read_text())
    if receipt.get("status") != "PASS_V4_F96_FULL_QC_RECOVERY_V2_PACKAGE_HASH_CLOSED" or receipt.get("candidate_count") != 96 or receipt.get("label_or_model_fields_accepted") != 0:
        raise RuntimeError("package_receipt_contract_failed")
    expected_files = set(receipt["outputs"]) | {"PACKAGE_RECEIPT.json"}
    actual_files = {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()}
    if expected_files != actual_files:
        raise RuntimeError(f"package_file_closure:{sorted(expected_files ^ actual_files)}")
    for rel, digest in receipt["outputs"].items():
        path = output / rel
        if path.is_symlink() or sha256(path) != digest:
            raise RuntimeError(f"package_hash_mismatch:{rel}")
    fields, rows = read_tsv(output / "inputs" / DEFAULT_MANIFEST.name)
    if fields != FIELDS or len(rows) != 96:
        raise RuntimeError("packaged_manifest_failed")
    if sum(line.startswith(">") for line in (output / "inputs/holdout96.fasta").read_text().splitlines()) != 96:
        raise RuntimeError("packaged_fasta_count_failed")
    return {"status": "PASS", "candidate_count": 96, "package_receipt_sha256": sha256(output / "PACKAGE_RECEIPT.json"), "implementation_freeze_sha256": sha256(output / "IMPLEMENTATION_FREEZE.json"), "runner_sha256": sha256(output / DEFAULT_RUNNER.name), "waiter_sha256": sha256(output / "wait_for_support_v4a720_structures_then_run_full_qc.sh")}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT); parser.add_argument("--freeze-out", type=Path, default=DEFAULT_FREEZE); parser.add_argument("--verify-only", action="store_true"); args = parser.parse_args()
    result = validate_package(args.output) if args.verify_only else build(args.output, args.freeze_out)
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
