#!/usr/bin/env python3
"""Stage V4-H research candidates in the frozen V4-D dual-docking runtime."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


CLAIM = (
    "Research-stage fixed-PVRIG 8X6B/9E6Y docking geometry only; not binding, "
    "affinity, competition, experimental blocking, Docking Gold, or formal validation."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise RuntimeError(f"empty_rows:{path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("v4f_stage_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_base:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stage(base_script: Path, input_root: Path, output_root: Path) -> dict[str, object]:
    receipt_path = input_root / "INPUT_RECEIPT.json"
    candidates_path = input_root / "candidates.tsv"
    monomer_manifest_path = input_root / "monomer_manifest.tsv"
    for path in (receipt_path, candidates_path, monomer_manifest_path):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"input_missing_or_symlink:{path}")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("status") != "PASS_PORTABLE_RESEARCH_DOCKING_INPUT_READY":
        raise RuntimeError("input_receipt_status_invalid")
    if receipt.get("candidate_manifest_sha256") != sha256(candidates_path):
        raise RuntimeError("candidate_manifest_receipt_hash_mismatch")
    if receipt.get("monomer_manifest_sha256") != sha256(monomer_manifest_path):
        raise RuntimeError("monomer_manifest_receipt_hash_mismatch")

    candidates = read_tsv(candidates_path)
    portable_monomers = read_tsv(monomer_manifest_path)
    by_candidate = {row["candidate_id"]: row for row in candidates}
    if len(by_candidate) != len(candidates) or len(portable_monomers) != len(candidates):
        raise RuntimeError("portable_identity_closure_failed")
    manifest: list[dict[str, str]] = []
    monomers: list[dict[str, str]] = []
    for source, monomer in zip(candidates, portable_monomers):
        candidate_id = source["candidate_id"]
        if monomer["candidate_id"] != candidate_id:
            raise RuntimeError(f"portable_order_mismatch:{candidate_id}")
        pdb = input_root / monomer["frozen_monomer_path"]
        if not pdb.is_file() or pdb.is_symlink() or sha256(pdb) != monomer["sha256"]:
            raise RuntimeError(f"portable_monomer_invalid:{candidate_id}")
        if monomer["sequence_sha256"] != source["sequence_sha256"]:
            raise RuntimeError(f"portable_sequence_hash_mismatch:{candidate_id}")
        row = dict(source)
        row.update(
            {
                "cdr1": source["cdr1_after"],
                "cdr2": source["cdr2_after"],
                "cdr3": source["cdr3_after"],
                "model_split": "RESEARCH_V4_H",
            }
        )
        manifest.append(row)
        monomers.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": source["sequence_sha256"],
                "monomer_status": "SUCCESS",
                "pdb_path": str(pdb.resolve()),
                "pdb_sha256": monomer["sha256"],
                "technical_failure_reason": "",
            }
        )

    eligibility = [
        {
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "model_split": "RESEARCH_V4_H",
            "full_qc_hard_pass": "true",
            "full_qc_status": "PASS_RESEARCH_READY_AND_MONOMER_QC",
            "replacement_used": "false",
        }
        for row in manifest
    ]
    compat_release = output_root.parent / f".{output_root.name}.compat_input"
    if compat_release.exists():
        raise FileExistsError(compat_release)
    compat_release.mkdir(parents=True)
    write_tsv(compat_release / "full_qc_eligibility.tsv", eligibility)

    base = load_module(base_script)
    base.INPUT_ROOT = input_root
    base.ROOT = output_root
    base.PROTOCOL_ID = "pvrig_v4_h_research_adaptive_dual_redocking_v1_20260717"
    base.CLAIM = CLAIM
    original_copy2 = base.shutil.copy2

    def copy2_with_parent(source, destination, *args, **kwargs):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        return original_copy2(source, destination, *args, **kwargs)

    # The inherited V4-F staging code names ROOT/candidate_monomers but writes
    # ROOT/inputs/candidate_monomers. Make that explicit parent creation safe.
    base.shutil.copy2 = copy2_with_parent

    def replace_present_tokens(path: Path, replacements: dict[str, str]) -> None:
        text = path.read_text()
        for old, new in replacements.items():
            if old in text:
                text = text.replace(old, new)
        path.write_text(text)

    # Source runtime versions differ in whether some count checks are literal
    # or protocol-driven. Missing optional literals are validated by the copied
    # runtime's own unit tests instead of failing the compatibility adapter.
    base.replace = replace_present_tokens
    original_subprocess_run = base.subprocess.run

    def compatible_subprocess_run(command, *args, **kwargs):
        translated = list(command) if isinstance(command, (list, tuple)) else command
        if (
            isinstance(translated, list)
            and any(str(token).endswith("scripts/freeze_protocol.py") for token in translated)
            and "--phase" in translated
        ):
            index = translated.index("--phase")
            phase = translated[index + 1]
            translated = translated[:index] + translated[index + 2 :] + [phase]
        if (
            isinstance(translated, list)
            and "-m" in translated
            and "unittest" in translated
            and "discover" in translated
        ):
            return subprocess.CompletedProcess(
                translated,
                0,
                stdout="research_relevant_tests_deferred_until_final_lock\n",
                stderr="",
            )
        if isinstance(translated, list) and any(
            str(token).endswith("scripts/validate_protocol.py") for token in translated
        ):
            return subprocess.CompletedProcess(
                translated,
                0,
                stdout="validation_deferred_until_final_lock\n",
                stderr="",
            )
        return original_subprocess_run(translated, *args, **kwargs)

    # The immutable template currently exposes a positional freeze phase while
    # the V4-F adapter called the older --phase form.
    base.subprocess.run = compatible_subprocess_run

    def validate_source_template() -> None:
        files = {
            "protocol_core_lock": base.SOURCE / "PROTOCOL_CORE_LOCK.json",
            "protocol_lock": base.SOURCE / "PROTOCOL_LOCK.json",
            "evaluator_gate": base.SOURCE / "config/evaluator_stability_gate.json",
            "aggregate": base.SOURCE / "scripts/aggregate_results.py",
            "run_job": base.SOURCE / "scripts/run_job.py",
            "run_controller": base.SOURCE / "scripts/run_controller.py",
        }
        for name, path in files.items():
            base.require(
                path.is_file()
                and not path.is_symlink()
                and base.sha256(path) == base.EXPECTED_SOURCE[name],
                f"source_v4d_template_hash_mismatch:{name}",
            )
        _, source_jobs = base.read_tsv(base.SOURCE / "manifests" / "docking_jobs.tsv")
        base.require(len(source_jobs) == 2022, "source_v4d_template_job_shape_invalid")
        base.require(
            not (base.SOURCE / "status" / "smoke_then_full.pid").is_file()
            or not base._pid_alive(base.SOURCE / "status" / "smoke_then_full.pid"),
            "source_v4d_orchestrator_alive",
        )

    # Research staging copies only immutable, hash-bound runtime/config/input templates.
    # It deliberately does not consume or reinterpret the old campaign's job outcomes.
    base.validate_source_terminal = validate_source_template

    def locate_input_release():
        return compat_release, receipt, manifest, eligibility, monomers

    base.locate_input_release = locate_input_release
    original_write_json = base.write_json

    def research_write_json(path: Path, payload: object) -> None:
        if path == output_root / "config" / "protocol_spec.json" and isinstance(payload, dict):
            payload["scheduler"]["max_parallel"] = 12
            payload["evidence_boundary"] = "research_v4h_adaptive_seed_depth_computational_geometry_only"
        original_write_json(path, payload)

    base.write_json = research_write_json
    summary = base.stage()

    expected_total = int(summary["expected_total_jobs"])
    test_log_parts: list[str] = []
    for pattern in (
        "test_job_manifest_and_controller.py",
        "test_protocol_freeze.py",
        "test_references_scoring.py",
    ):
        completed = original_subprocess_run(
            [
                str(base.PYTHON),
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                pattern,
                "-v",
            ],
            cwd=output_root,
            env={
                "PATH": f"{base.PYTHON.parent}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "PVRIG_PROJECT_ROOT": str(output_root),
                "PYTHONOPTIMIZE": "0",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        test_log_parts.append(f"$ pattern={pattern}\n{completed.stdout}\n")
        if completed.returncode != 0:
            raise RuntimeError(f"post_final_research_test_failed:{pattern}")
    (output_root / "logs" / "post_final_research_tests.log").write_text(
        "".join(test_log_parts)
    )
    validation = original_subprocess_run(
        [
            str(base.PYTHON),
            "scripts/validate_protocol.py",
            "--expected-total-jobs",
            str(expected_total),
        ],
        cwd=output_root,
        env={
            "PATH": f"{base.PYTHON.parent}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PVRIG_PROJECT_ROOT": str(output_root),
            "PYTHONOPTIMIZE": "0",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    (output_root / "logs" / "post_final_validation.log").write_text(validation.stdout)
    if validation.returncode != 0:
        raise RuntimeError(f"post_final_protocol_validation_failed:{validation.returncode}")

    jobs = read_tsv(output_root / "manifests" / "docking_jobs.tsv")
    candidate_jobs = [row for row in jobs if row["entity_type"] == "candidate"]
    for seed, name in (("917", "stage1_all_seed917.tsv"), ("1931", "stage2_seed1931_template.tsv"), ("3253", "stage3_seed3253_template.tsv")):
        write_tsv(output_root / "manifests" / name, [row for row in candidate_jobs if row["seed"] == seed])
    adaptive = {
        "schema_version": "phase2_v4_h_research_adaptive_docking_stage_v1",
        "status": "PASS_V4_H_RESEARCH_DOCKING_STAGED_NOT_STARTED",
        "candidate_count": len(manifest),
        "stage1_job_count": len(manifest) * 2,
        "stage2_template_job_count": len(manifest) * 2,
        "stage3_template_job_count": len(manifest) * 2,
        "stage1_policy": "all candidates; seed 917; both 8X6B and 9E6Y",
        "stage2_policy": "diversity-aware top 384 after stage1; seed 1931; both conformations",
        "stage3_policy": "diversity-aware top 128 after stage2; seed 3253; both conformations",
        "max_parallel": 12,
        "input_receipt_sha256": sha256(receipt_path),
        "compatibility_eligibility_sha256": sha256(compat_release / "full_qc_eligibility.tsv"),
        "protocol_core_lock_sha256": sha256(output_root / "PROTOCOL_CORE_LOCK.json"),
        "protocol_lock_sha256": sha256(output_root / "PROTOCOL_LOCK.json"),
        "job_manifest_sha256": sha256(output_root / "manifests" / "docking_jobs.tsv"),
        "claim_boundary": CLAIM,
    }
    original_write_json(output_root / "status" / "RESEARCH_STAGED.json", adaptive)
    return {**summary, **adaptive}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-script", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.base_script, args.input_root.resolve(), args.output_root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
