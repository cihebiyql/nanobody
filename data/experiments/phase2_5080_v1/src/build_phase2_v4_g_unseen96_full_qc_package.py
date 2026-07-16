#!/usr/bin/env python3
"""Build and verify the label-free V4-G unseen96 Full-QC package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


PHASE2 = Path(__file__).resolve().parents[1]
SPLIT = PHASE2 / "data_splits/pvrig_v4_g"
TEMPLATES = Path(__file__).resolve().parent / "templates"
DEFAULT_MANIFEST = SPLIT / "unseen96_acquisition_manifest.tsv"
DEFAULT_PREREG = SPLIT / "phase2_v4_g_active_learning_preregistration.json"
DEFAULT_FREEZE_RECEIPT = SPLIT / "v4_g_active_learning_freeze_receipt.json"
DEFAULT_OUTPUT = PHASE2 / "prepared/pvrig_v4_g_unseen96_full_qc_v1"
RUNNER_TEMPLATE = TEMPLATES / "pvrig_v4_g_unseen96_full_qc_runner.sh.in"
LAUNCHER_TEMPLATE = TEMPLATES / "pvrig_v4_g_unseen96_waiting_launcher.sh.in"

EXPECTED_MANIFEST_SHA256 = "e814103ee90831e33b3f04a7e8a477e68695d61401d96732b7e95829b1bd306f"
EXPECTED_PREREG_SHA256 = "1ba6ecb0e5541516649c9d3c8dc30c82f411f3c5296e0e04681486bd9441bf55"
EXPECTED_FREEZE_RECEIPT_SHA256 = "bb1e68b826987a146d7eeaa6f2a2262336b3bb82898b3a9147dbad4abb022b24"
EXPECTED_ROWS = 96
EXPECTED_SPLIT = "V4_G_ACTIVE_LEARNING_UNSEEN_ACQUISITION"
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
PACKAGE_FILES = {
    "unseen96.fasta",
    "unseen96_lineage.csv",
    "input_audit.json",
    "run_full_qc_node1.sh",
    "wait_for_ssd_deepqc_delivery_then_run_node1.sh",
    "PACKAGE_RECEIPT.json",
}
CANONICAL_REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_v1_20260716"
CANONICAL_SCREEN = "/data1/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen"
CANONICAL_RECOVERY_RECEIPT = "/data1/qlyu/pvrig_migration_20260716/deepqc_recovery_v1/ssd_recovery_receipt.json"
CANONICAL_PATH_SWITCH_RECEIPT = "/data1/qlyu/pvrig_migration_20260716/ACTIVE_DEEPQC_DELIVERY_PATH_SWITCH.json"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def atomic_write(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def csv_bytes(rows: list[dict[str, str]], fields: list[str]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode()


def validate_sources(
    manifest: Path,
    prereg_path: Path,
    receipt_path: Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    observed = {
        "manifest": sha256_file(manifest),
        "preregistration": sha256_file(prereg_path),
        "freeze_receipt": sha256_file(receipt_path),
    }
    expected = {
        "manifest": EXPECTED_MANIFEST_SHA256,
        "preregistration": EXPECTED_PREREG_SHA256,
        "freeze_receipt": EXPECTED_FREEZE_RECEIPT_SHA256,
    }
    if observed != expected:
        raise RuntimeError(f"frozen V4-G source hash mismatch: observed={observed}")
    rows = read_tsv(manifest)
    prereg = json.loads(prereg_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"expected 96 unseen acquisition rows, found {len(rows)}")
    ids = [row["candidate_id"] for row in rows]
    sequences = [row["sequence"] for row in rows]
    if len(set(ids)) != EXPECTED_ROWS or len(set(sequences)) != EXPECTED_ROWS:
        raise RuntimeError("candidate IDs or sequences are not unique")
    frozen_policy = "run_full_qc_on_all_96;dock_every_full_qc_hard_pass;record_attrition;no_replacement"
    for row in rows:
        sequence = row["sequence"]
        if set(sequence) - STANDARD_AA:
            raise RuntimeError(f"invalid amino acid in {row['candidate_id']}")
        if sha256_bytes(sequence.encode()) != row["sequence_sha256"]:
            raise RuntimeError(f"sequence hash mismatch: {row['candidate_id']}")
        if row["model_split"] != EXPECTED_SPLIT or row["full_qc_and_docking_policy"] != frozen_policy:
            raise RuntimeError(f"frozen policy/split mismatch: {row['candidate_id']}")
    config = prereg["configuration"]
    unseen = prereg["unseen96"]
    reserve = set(prereg["untouched_reserve2"]["parent_clusters"])
    parents = {row["parent_framework_cluster"] for row in rows}
    if parents != set(unseen["parent_clusters"]) or len(parents) != config["expected_counts"]["acquisition_parents"]:
        raise RuntimeError("unseen96 parent-cluster closure failed")
    if parents & reserve:
        raise RuntimeError(f"untouched reserve2 entered package: {sorted(parents & reserve)}")
    if Counter(row["parent_framework_cluster"] for row in rows) != Counter({parent: 12 for parent in parents}):
        raise RuntimeError("expected 12 candidates per parent")
    if Counter(row["target_patch_id"] for row in rows) != Counter({"A_CENTER": 32, "B_LOWER": 32, "C_CROSS": 32}):
        raise RuntimeError("patch balance mismatch")
    if Counter(row["design_mode"] for row in rows) != Counter({"H3": 48, "H1H3": 48}):
        raise RuntimeError("design-mode balance mismatch")
    if set(Counter(row["selection_stratum"] for row in rows).values()) != {2}:
        raise RuntimeError("each acquisition stratum must contain exactly two candidates")
    if unseen["rows"] != EXPECTED_ROWS or unseen["manifest_sha256"] != observed["manifest"]:
        raise RuntimeError("preregistration unseen96 hash/count mismatch")
    if config["selection_uses_docking_or_test_labels"] is not False:
        raise RuntimeError("preregistration is not label-free")
    if any(int(value) != 0 for value in prereg["label_access"].values()):
        raise RuntimeError("preregistration reports label access")
    if receipt["status"] != "PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST":
        raise RuntimeError("freeze receipt is not terminal PASS")
    if receipt["outputs"]["unseen96_acquisition_manifest.tsv"] != observed["manifest"]:
        raise RuntimeError("freeze receipt manifest binding mismatch")
    if receipt["outputs"]["phase2_v4_g_active_learning_preregistration.json"] != observed["preregistration"]:
        raise RuntimeError("freeze receipt preregistration binding mismatch")
    if int(receipt["docking_or_test_label_files_opened"]) != 0:
        raise RuntimeError("freeze receipt reports label access")
    return rows, {
        "source_hashes": observed,
        "parent_clusters": sorted(parents),
        "reserve2_parent_clusters_excluded": sorted(reserve),
        "claim_boundary": prereg["claim_boundary"],
    }


def render_runner(fasta_sha: str, lineage_sha: str) -> bytes:
    text = RUNNER_TEMPLATE.read_text()
    return (
        text.replace("@FASTA_SHA@", fasta_sha)
        .replace("@LINEAGE_SHA@", lineage_sha)
        .replace("@MANIFEST_SHA@", EXPECTED_MANIFEST_SHA256)
        .encode()
    )


def render_launcher() -> bytes:
    return LAUNCHER_TEMPLATE.read_bytes()


def validate_shell_contracts(output: Path) -> dict[str, Any]:
    scripts = {
        "runner": output / "run_full_qc_node1.sh",
        "waiter": output / "wait_for_ssd_deepqc_delivery_then_run_node1.sh",
    }
    environment = dict(os.environ)
    environment.update({
        "PVRIG_V4G_ROOT": "/tmp/forbidden-root-override",
        "VHH_SCREEN": "/tmp/forbidden-screen-override",
        "PVRIG_DEEPQC_RECOVERY_RECEIPT": "/tmp/forbidden-recovery-receipt",
        "PVRIG_DEEPQC_PATH_SWITCH_RECEIPT": "/tmp/forbidden-path-switch-receipt",
    })
    results: dict[str, Any] = {}
    for name, path in scripts.items():
        text = path.read_text()
        if "${{" in text:
            raise RuntimeError(f"invalid double-brace shell substitution: {path.name}")
        syntax = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, check=False,
        )
        if syntax.returncode != 0:
            raise RuntimeError(f"shell syntax validation failed: {path.name}: {syntax.stderr.strip()}")
        smoke = subprocess.run(
            ["bash", "-c", 'exec "$1" --smoke-test', "v4g-shell-smoke", str(path)],
            capture_output=True, text=True, check=False, env=environment,
        )
        if smoke.returncode != 0:
            raise RuntimeError(f"shell runtime smoke failed: {path.name}: {smoke.stderr.strip()}")
        try:
            results[name] = json.loads(smoke.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"shell smoke returned invalid JSON: {path.name}") from exc
    runner = results["runner"]
    waiter = results["waiter"]
    if runner != {
        "status": "PASS_V4_G_RUNNER_SHELL_SMOKE",
        "root": CANONICAL_REMOTE_ROOT,
        "screen": CANONICAL_SCREEN,
        "common_arg_count": 26,
    }:
        raise RuntimeError(f"runner canonical binding/smoke mismatch: {runner}")
    if waiter != {
        "status": "PASS_V4_G_WAITER_SHELL_SMOKE",
        "root": CANONICAL_REMOTE_ROOT,
        "recovery_receipt": CANONICAL_RECOVERY_RECEIPT,
        "path_switch_receipt": CANONICAL_PATH_SWITCH_RECEIPT,
    }:
        raise RuntimeError(f"waiter canonical binding/smoke mismatch: {waiter}")
    return results


def build_package(manifest: Path, prereg: Path, freeze_receipt: Path, output: Path) -> dict[str, Any]:
    rows, metadata = validate_sources(manifest, prereg, freeze_receipt)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    fasta_raw = "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in rows).encode()
    lineage_raw = csv_bytes(rows, list(rows[0]))
    runner_raw = render_runner(sha256_bytes(fasta_raw), sha256_bytes(lineage_raw))
    launcher_raw = render_launcher()
    atomic_write(output / "unseen96.fasta", fasta_raw)
    atomic_write(output / "unseen96_lineage.csv", lineage_raw)
    atomic_write(output / "run_full_qc_node1.sh", runner_raw, 0o755)
    atomic_write(output / "wait_for_ssd_deepqc_delivery_then_run_node1.sh", launcher_raw, 0o755)
    audit = {
        "schema_version": "pvrig_v4_g_unseen96_full_qc_input_v1",
        "status": "PASS_LABEL_FREE_UNSEEN96_FULL_QC_INPUT_READY",
        "candidate_count": EXPECTED_ROWS,
        "source_manifest": str(manifest.resolve()),
        "source_manifest_sha256": metadata["source_hashes"]["manifest"],
        "active_learning_preregistration": str(prereg.resolve()),
        "active_learning_preregistration_sha256": metadata["source_hashes"]["preregistration"],
        "active_learning_freeze_receipt": str(freeze_receipt.resolve()),
        "active_learning_freeze_receipt_sha256": metadata["source_hashes"]["freeze_receipt"],
        "fasta_sha256": sha256_bytes(fasta_raw),
        "lineage_sha256": sha256_bytes(lineage_raw),
        "runner_sha256": sha256_bytes(runner_raw),
        "waiting_launcher_sha256": sha256_bytes(launcher_raw),
        "implementation": {
            "builder": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
            "runner_template": {"path": str(RUNNER_TEMPLATE.resolve()), "sha256": sha256_file(RUNNER_TEMPLATE)},
            "waiting_launcher_template": {
                "path": str(LAUNCHER_TEMPLATE.resolve()),
                "sha256": sha256_file(LAUNCHER_TEMPLATE),
            },
        },
        "parent_clusters": metadata["parent_clusters"],
        "reserve2_parent_clusters_excluded": metadata["reserve2_parent_clusters_excluded"],
        "selection_policy": "all frozen unseen96 enter label-free Full-QC; record attrition; no replacement; no model-score reselection",
        "upstream_gate": "receipt-bound immutable /data1 DeepQC delivery plus explicit path-switch receipt; never old NFS COMPLETE",
        "label_files_opened": 0,
        "claim_boundary": "Sequence/developability QC only; no docking, binding, affinity, competition, or blocking labels.",
    }
    audit_raw = json_bytes(audit)
    atomic_write(output / "input_audit.json", audit_raw)
    outputs = {
        "unseen96.fasta": sha256_bytes(fasta_raw),
        "unseen96_lineage.csv": sha256_bytes(lineage_raw),
        "input_audit.json": sha256_bytes(audit_raw),
        "run_full_qc_node1.sh": sha256_bytes(runner_raw),
        "wait_for_ssd_deepqc_delivery_then_run_node1.sh": sha256_bytes(launcher_raw),
    }
    receipt = {
        "schema_version": "pvrig_v4_g_unseen96_full_qc_package_receipt_v1",
        "status": "PASS_V4_G_UNSEEN96_FULL_QC_PACKAGE_READY",
        "candidate_count": EXPECTED_ROWS,
        "sources": metadata["source_hashes"],
        "outputs": outputs,
        "parent_clusters": metadata["parent_clusters"],
        "reserve2_parent_clusters_excluded": metadata["reserve2_parent_clusters_excluded"],
        "label_files_opened": 0,
        "remote_execution_started": False,
        "nfs_upstream_complete_allowed": False,
        "required_upstream": "immutable /data1 content-addressed DeepQC delivery plus explicit path-switch receipt",
        "receipt_publication_order": "LAST_AFTER_ALL_PACKAGE_OUTPUTS_VERIFIED",
        "claim_boundary": audit["claim_boundary"],
    }
    for name, digest in outputs.items():
        if sha256_file(output / name) != digest:
            raise RuntimeError(f"pre-receipt output hash mismatch: {name}")
    atomic_write(output / "PACKAGE_RECEIPT.json", json_bytes(receipt), 0o444)
    return validate_package(output, manifest, prereg, freeze_receipt)


def validate_package(output: Path, manifest: Path, prereg: Path, freeze_receipt: Path) -> dict[str, Any]:
    rows, metadata = validate_sources(manifest, prereg, freeze_receipt)
    actual_files = {path.name for path in output.iterdir()}
    if actual_files != PACKAGE_FILES:
        raise RuntimeError(f"package file closure mismatch: {sorted(actual_files)}")
    receipt = json.loads((output / "PACKAGE_RECEIPT.json").read_text())
    audit = json.loads((output / "input_audit.json").read_text())
    if receipt["status"] != "PASS_V4_G_UNSEEN96_FULL_QC_PACKAGE_READY":
        raise RuntimeError("package receipt status is not PASS")
    if receipt["sources"] != metadata["source_hashes"]:
        raise RuntimeError("package source hash closure failed")
    if receipt["label_files_opened"] != 0 or receipt["remote_execution_started"] is not False:
        raise RuntimeError("package receipt violates label-free/not-started boundary")
    for name, digest in receipt["outputs"].items():
        if sha256_file(output / name) != digest:
            raise RuntimeError(f"package output hash mismatch: {name}")
    if audit["source_manifest_sha256"] != EXPECTED_MANIFEST_SHA256 or audit["candidate_count"] != EXPECTED_ROWS:
        raise RuntimeError("input audit closure failed")
    audit_hashes = {
        "unseen96.fasta": audit["fasta_sha256"],
        "unseen96_lineage.csv": audit["lineage_sha256"],
        "run_full_qc_node1.sh": audit["runner_sha256"],
        "wait_for_ssd_deepqc_delivery_then_run_node1.sh": audit["waiting_launcher_sha256"],
    }
    if any(receipt["outputs"][name] != digest for name, digest in audit_hashes.items()):
        raise RuntimeError("input audit output hash closure failed")
    if audit["active_learning_preregistration_sha256"] != EXPECTED_PREREG_SHA256:
        raise RuntimeError("input audit preregistration hash mismatch")
    if audit["active_learning_freeze_receipt_sha256"] != EXPECTED_FREEZE_RECEIPT_SHA256:
        raise RuntimeError("input audit freeze-receipt hash mismatch")
    fasta_ids = [
        line[1:].split()[0] for line in (output / "unseen96.fasta").read_text().splitlines()
        if line.startswith(">")
    ]
    with (output / "unseen96_lineage.csv").open(newline="") as handle:
        lineage = list(csv.DictReader(handle))
    if fasta_ids != [row["candidate_id"] for row in rows] or lineage != rows:
        raise RuntimeError("FASTA/lineage/source ordering closure failed")
    launcher = (output / "wait_for_ssd_deepqc_delivery_then_run_node1.sh").read_text()
    runner = (output / "run_full_qc_node1.sh").read_text()
    if "/data/qlyu/" in launcher or "/data/qlyu/" in runner:
        raise RuntimeError("package retains an old NFS execution dependency")
    required = [
        "/data1/qlyu/pvrig_migration_20260716/deepqc_recovery_v1/ssd_recovery_receipt.json",
        "/data1/qlyu/pvrig_migration_20260716/ACTIVE_DEEPQC_DELIVERY_PATH_SWITCH.json",
        "PASS_SSD_DEEPQC_DELIVERY_PATH_SWITCHED",
        "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
    ]
    if any(token not in launcher for token in required):
        raise RuntimeError("launcher lacks immutable SSD receipt/path-switch gates")
    if set(audit["parent_clusters"]) & set(audit["reserve2_parent_clusters_excluded"]):
        raise RuntimeError("reserve2 overlap in audit")
    if (output / "PACKAGE_RECEIPT.json").stat().st_mode & 0o222:
        raise RuntimeError("package receipt is writable")
    for script in ("run_full_qc_node1.sh", "wait_for_ssd_deepqc_delivery_then_run_node1.sh"):
        if not (output / script).stat().st_mode & 0o111:
            raise RuntimeError(f"package script is not executable: {script}")
    validate_shell_contracts(output)
    return {
        "status": "PASS",
        "candidate_count": EXPECTED_ROWS,
        "package_receipt_sha256": sha256_file(output / "PACKAGE_RECEIPT.json"),
        "output_hashes": receipt["outputs"],
        "label_files_opened": 0,
        "remote_execution_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        validate_package(args.output, args.manifest, args.preregistration, args.freeze_receipt)
        if args.verify_only
        else build_package(args.manifest, args.preregistration, args.freeze_receipt, args.output)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
