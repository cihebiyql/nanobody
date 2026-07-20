#!/usr/bin/env python3
"""Stage a hash-bound seven-candidate dual-receptor pilot from NBB2 smoke outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


SOURCE = Path("/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714")
STRUCTURE_ROOT = Path("/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720")
ROOT = Path("/data/qlyu/projects/pvrig_v29_pilot7_dual_docking_v1_20260720")
PANEL = STRUCTURE_ROOT / "input/structure_candidates10000.tsv"
MONOMERS = STRUCTURE_ROOT / "smoke7/outputs/monomer_manifest.tsv"
PROTOCOL_ID = "pvrig_v29_pilot7_independent_dual_redocking_v1_20260720"
CLAIM = (
    "Seven-candidate computational protocol smoke for independent 8X6B/9E6Y Docking geometry; "
    "not training labels, binding, affinity, experimental blocking, expression, purity, or Docking Gold."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def stage() -> dict[str, object]:
    require(SOURCE.is_dir(), "source_protocol_missing")
    require(PANEL.is_file() and MONOMERS.is_file(), "structure_smoke_inputs_missing")
    require(not ROOT.exists(), f"target_exists:{ROOT}")
    for directory in ("config", "scripts"):
        shutil.copytree(SOURCE / directory, ROOT / directory)
    for directory in ("source", "normalized"):
        shutil.copytree(SOURCE / "inputs" / directory, ROOT / "inputs" / directory)
    for directory in ("inputs/candidate_monomers", "manifests", "reports", "status/jobs", "status/locks", "logs/jobs", "runs", "results", "failed_attempts"):
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / "reports/reference_normalization_summary.json", ROOT / "reports/reference_normalization_summary.json")

    _, panel_rows = read_tsv(PANEL)
    _, monomer_rows = read_tsv(MONOMERS)
    require(len(monomer_rows) == 7, f"smoke_monomer_count:{len(monomer_rows)}")
    require(all(row["monomer_status"] == "SUCCESS" for row in monomer_rows), "smoke_monomer_failure")
    panel_by = {row["candidate_id"]: row for row in panel_rows}
    candidates: list[dict[str, str]] = []
    frozen: list[dict[str, str]] = []
    for monomer in monomer_rows:
        candidate_id = monomer["candidate_id"]
        require(candidate_id in panel_by, f"candidate_not_in_panel:{candidate_id}")
        row = panel_by[candidate_id]
        source = Path(monomer["pdb_path"])
        require(source.is_file() and sha256_file(source) == monomer["pdb_sha256"], f"monomer_invalid:{candidate_id}")
        destination = ROOT / "inputs/candidate_monomers" / f"{candidate_id}.pdb"
        shutil.copy2(source, destination)
        require(sha256_file(destination) == monomer["pdb_sha256"], f"monomer_copy_hash:{candidate_id}")
        candidates.append({
            "candidate_id": candidate_id, "sequence": row["sequence"], "sequence_sha256": row["sequence_sha256"],
            "cdr1": row["anarci_cdr1"], "cdr2": row["anarci_cdr2"], "cdr3": row["anarci_cdr3"],
            "parent_framework_cluster": row["parent_framework_cluster"], "model_split": row["model_split"],
        })
        frozen.append({
            "candidate_id": candidate_id, "sequence_sha256": row["sequence_sha256"],
            "frozen_monomer_path": str(destination.relative_to(ROOT)), "source_chain": "A",
            "sha256": sha256_file(destination), "size_bytes": str(destination.stat().st_size),
        })
    write_tsv(ROOT / "inputs/candidates_128.tsv", candidates, list(candidates[0]))
    write_tsv(ROOT / "inputs/candidate_monomers_manifest.tsv", frozen, list(frozen[0]))
    control_fields, _ = read_tsv(SOURCE / "inputs/calibration_controls_47.tsv")
    write_tsv(ROOT / "inputs/calibration_controls_47.tsv", [], control_fields)

    protocol_path = ROOT / "config/protocol_spec.json"
    protocol = json.loads(protocol_path.read_text())
    protocol.update({"protocol_id": PROTOCOL_ID, "status": "PILOT_PRELOCK", "evidence_boundary": CLAIM})
    protocol["candidate_panel"].update({
        "panel_id": "v29_anarci_verified_nbb2_smoke7_v1", "expected_count": 7,
        "selection_algorithm": "first_seven_frozen_structure_smoke_rows_only",
        "monomer_source_policy": "NanoBodyBuilder2_smoke7_hash_bound_no_replacement",
    })
    protocol["controls"].update({"panel_id": "none_for_compute_smoke", "expected_count": 0})
    protocol["docking"].update({
        "seeds": [917], "expected_candidate_jobs": 14, "expected_control_jobs": 0,
        "expected_total_jobs": 14, "smoke_seed": 917, "smoke_control_id": "",
        "smoke_candidate_id": candidates[0]["candidate_id"], "expected_smoke_jobs": 2,
    })
    protocol["scheduler"]["max_parallel"] = 4
    write_json(protocol_path, protocol)

    freeze_path = ROOT / "scripts/freeze_protocol.py"
    freeze_text = freeze_path.read_text()
    require("len(monomers) != 128" in freeze_text, "freeze_patch_anchor_missing")
    freeze_path.write_text(freeze_text.replace("len(monomers) != 128", "len(monomers) != 7").replace(
        "expected 128 frozen candidate monomers", "expected 7 frozen candidate monomers"
    ))
    env = {**os.environ, "PVRIG_PROJECT_ROOT": str(ROOT)}
    python = Path("/data/qlyu/anaconda3/envs/haddock3/bin/python")
    commands = [
        [str(python), "scripts/freeze_protocol.py", "core", "--root", str(ROOT)],
        [str(python), "scripts/build_docking_jobs.py"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (ROOT / "logs/staging.log").open("a").write("$ " + " ".join(command) + "\n" + result.stdout + "\n")
        require(result.returncode == 0, f"staging_command_failed:{command[1]}:{result.returncode}")
    _, jobs = read_tsv(ROOT / "manifests/docking_jobs.tsv")
    require(len(jobs) == 14 and len({row["job_id"] for row in jobs}) == 14, "pilot_job_manifest_invalid")
    jobs = sorted(jobs, key=lambda row: row["job_hash"])
    node1 = jobs[::2]; node23 = jobs[1::2]
    require(len(node1) == len(node23) == 7, "pilot_shard_count")
    fields = ["job_id", "entity_id", "conformation", "seed", "job_hash"]
    write_tsv(ROOT / "manifests/node1_jobs.tsv", node1, fields)
    write_tsv(ROOT / "manifests/node23_jobs.tsv", node23, fields)

    core = json.loads((ROOT / "PROTOCOL_CORE_LOCK.json").read_text())
    final_material = {
        "schema_version": 1, "protocol_id": PROTOCOL_ID,
        "protocol_core_sha256": core["protocol_core_sha256"],
        "core_lock_sha256": sha256_file(ROOT / "PROTOCOL_CORE_LOCK.json"),
        "job_count": 14, "job_manifest_sha256": sha256_file(ROOT / "manifests/docking_jobs.tsv"),
        "node1_jobs_sha256": sha256_file(ROOT / "manifests/node1_jobs.tsv"),
        "node23_jobs_sha256": sha256_file(ROOT / "manifests/node23_jobs.tsv"),
        "reference_normalization_summary_sha256": sha256_file(ROOT / "reports/reference_normalization_summary.json"),
        "scope": "compute_smoke_before_full10k_monomer_terminal",
    }
    lock = {**final_material, "status": "LOCKED", "protocol_lock_sha256": sha256_text(json.dumps(final_material, sort_keys=True, separators=(",", ":")))}
    write_json(ROOT / "PROTOCOL_LOCK.json", lock)
    receipt = {
        "schema_version": "pvrig_v29_pilot7_dual_docking_stage_v1", "status": "PASS_PILOT7_STAGED",
        "candidate_count": 7, "job_count": 14, "node1_jobs": 7, "node23_jobs": 7,
        "protocol_core_sha256": core["protocol_core_sha256"], "protocol_lock_sha256": lock["protocol_lock_sha256"],
        "job_manifest_sha256": final_material["job_manifest_sha256"], "claim_boundary": CLAIM,
    }
    write_json(ROOT / "status/STAGED.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return receipt


if __name__ == "__main__":
    stage()
