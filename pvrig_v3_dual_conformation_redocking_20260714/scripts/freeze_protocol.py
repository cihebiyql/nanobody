#!/usr/bin/env python3
"""Create immutable core/final manifests for the V3 docking evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import canonical_json, project_root, read_json, read_tsv, sha256_file, sha256_text, write_json


CORE_FILES = [
    "config/protocol_spec.json",
    "config/blocker_judgment_rules_v2.json",
    "inputs/source/8X6B.pdb",
    "inputs/source/9E6Y.pdb",
    "inputs/source/PVRIG_hotspot_set_v1.csv",
    "inputs/normalized/8x6b_pvrig_receptor.pdb",
    "inputs/normalized/8x6b_TL_reference.pdb",
    "inputs/normalized/9e6y_pvrig_receptor.pdb",
    "inputs/normalized/9e6y_TL_reference.pdb",
    "inputs/normalized/interface_hotspots_uniprot.tsv",
    "inputs/candidates_128.tsv",
    "inputs/candidate_monomers_manifest.tsv",
    "inputs/calibration_controls_47.tsv",
    "scripts/common.py",
    "scripts/prepare_references.py",
    "scripts/score_pose.py",
    "scripts/build_candidate_panel.py",
    "scripts/freeze_candidate_monomers.py",
    "scripts/build_calibration_manifest.py",
]

FINAL_FILES = [
    "manifests/docking_jobs.tsv",
    "manifests/smoke_jobs.tsv",
    "scripts/build_docking_jobs.py",
    "scripts/deploy_node1.sh",
    "scripts/freeze_protocol.py",
    "scripts/launch_node1.sh",
    "scripts/orchestrate_smoke_then_full.py",
    "scripts/run_job.py",
    "scripts/run_controller.py",
    "scripts/sync_remote_status.sh",
    "scripts/status.py",
    "scripts/aggregate_results.py",
    "scripts/validate_protocol.py",
    "scripts/guard_next_generation.py",
    "tests/test_candidate_panel.py",
    "tests/test_job_manifest_and_controller.py",
    "tests/test_protocol_freeze.py",
    "tests/test_references_scoring.py",
    "tests/test_stability_gate.py",
]


def file_records(root: Path, relpaths: list[str]) -> list[dict[str, object]]:
    missing = [rel for rel in relpaths if not (root / rel).is_file()]
    if missing:
        raise ValueError(f"cannot freeze protocol; missing files: {missing}")
    return [
        {
            "path": rel,
            "bytes": (root / rel).stat().st_size,
            "sha256": sha256_file(root / rel),
        }
        for rel in sorted(relpaths)
    ]


def core_files(root: Path) -> list[str]:
    monomers = sorted((root / "inputs/candidate_monomers").glob("*.pdb"))
    if len(monomers) != 128:
        raise ValueError(f"expected 128 frozen candidate monomers, found {len(monomers)}")
    return CORE_FILES + [str(path.relative_to(root)) for path in monomers]


def assert_frozen_counts(root: Path, spec: dict[str, object]) -> None:
    candidates = read_tsv(root / "inputs/candidates_128.tsv")
    controls = read_tsv(root / "inputs/calibration_controls_47.tsv")
    expected_candidates = int(spec["candidate_panel"]["expected_count"])
    expected_controls = int(spec["controls"]["expected_count"])
    if len(candidates) != expected_candidates:
        raise ValueError(f"candidate count mismatch: {len(candidates)} != {expected_candidates}")
    if len(controls) != expected_controls:
        raise ValueError(f"control count mismatch: {len(controls)} != {expected_controls}")
    candidate_ids = [row.get("candidate_id", "") for row in candidates]
    control_ids = [row.get("control_id", row.get("candidate_id", "")) for row in controls]
    if len(set(candidate_ids)) != len(candidate_ids) or "" in candidate_ids:
        raise ValueError("candidate IDs must be non-empty and unique")
    if len(set(control_ids)) != len(control_ids) or "" in control_ids:
        raise ValueError("control IDs must be non-empty and unique")


def freeze_core(root: Path) -> dict[str, object]:
    spec = read_json(root / "config/protocol_spec.json")
    records = file_records(root, core_files(root))
    assert_frozen_counts(root, spec)
    core_material = {
        "schema_version": 1,
        "protocol_id": spec["protocol_id"],
        "protocol_spec_sha256": sha256_file(root / "config/protocol_spec.json"),
        "files": records,
    }
    payload = {
        **core_material,
        "status": "CORE_LOCKED",
        "protocol_core_sha256": sha256_text(canonical_json(core_material)),
    }
    write_json(root / "manifests/protocol_core_manifest.json", payload)
    write_json(root / "PROTOCOL_CORE_LOCK.json", payload)
    return payload


def freeze_final(root: Path) -> dict[str, object]:
    core_path = root / "PROTOCOL_CORE_LOCK.json"
    core = read_json(core_path)
    if core.get("status") != "CORE_LOCKED":
        raise ValueError("PROTOCOL_CORE_LOCK.json is absent or not CORE_LOCKED")
    drifted = []
    for record in core.get("files", []):
        path = root / str(record["path"])
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            drifted.append(str(record["path"]))
    if drifted:
        raise ValueError(f"core inputs or scripts drifted after core lock: {drifted}")
    final_records = file_records(root, FINAL_FILES)
    jobs = read_tsv(root / "manifests/docking_jobs.tsv")
    spec = read_json(root / "config/protocol_spec.json")
    expected_jobs = int(spec["docking"]["expected_total_jobs"])
    if len(jobs) != expected_jobs:
        raise ValueError(f"job count mismatch: {len(jobs)} != {expected_jobs}")
    job_ids = [row.get("job_id", "") for row in jobs]
    if len(set(job_ids)) != len(job_ids) or "" in job_ids:
        raise ValueError("job IDs must be non-empty and unique")
    bound_hashes = {row.get("protocol_core_sha256", "") for row in jobs}
    if bound_hashes != {core["protocol_core_sha256"]}:
        raise ValueError("every job must bind the current protocol_core_sha256")
    final_material = {
        "schema_version": 1,
        "protocol_id": core["protocol_id"],
        "protocol_core_sha256": core["protocol_core_sha256"],
        "core_lock_sha256": sha256_file(core_path),
        "job_count": len(jobs),
        "job_manifest_sha256": sha256_file(root / "manifests/docking_jobs.tsv"),
        "files": final_records,
    }
    payload = {
        **final_material,
        "status": "LOCKED",
        "protocol_lock_sha256": sha256_text(canonical_json(final_material)),
        "next_generation_gate": "reports/EVALUATOR_STABLE.json must match this protocol lock and have status PASS",
    }
    write_json(root / "manifests/protocol_manifest.json", payload)
    write_json(root / "PROTOCOL_LOCK.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("core", "final"))
    parser.add_argument("--root", type=Path, default=project_root())
    args = parser.parse_args()
    payload = freeze_core(args.root.resolve()) if args.stage == "core" else freeze_final(args.root.resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
