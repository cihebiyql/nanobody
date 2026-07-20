#!/usr/bin/env python3
"""Stage and launch the allocation-exact V2.9 Docking workload after monomer terminality."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


SOURCE = Path("/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714")
STRUCTURE_ROOT = Path("/data1/qlyu/projects/pvrig_v2_9_monomers10k_v1_20260720")
PANEL = STRUCTURE_ROOT / "input/structure_candidates10000.tsv"
ALLOCATION = STRUCTURE_ROOT / "input/docking_allocation25000.tsv"
MONOMER_COMPLETE = STRUCTURE_ROOT / "full10k/status/COMPLETE.json"
MONOMER_MANIFEST = STRUCTURE_ROOT / "full10k/outputs/monomer_manifest.tsv"
CUSTOM_BUILDER = STRUCTURE_ROOT / "src/build_docking_jobs_v29.py"
FINAL_ROOT = Path("/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720")
PROTOCOL_ID = "pvrig_v29_allocation_exact_dual_redocking_v1_20260720"
CLAIM = (
    "Independent 8X6B/9E6Y computational Docking geometry teacher only; technical failures are NA, "
    "not negative labels; not binding, affinity, experimental blocking, expression, purity, or Docking Gold."
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


def run_checked(command: list[str], root: Path, env: dict[str, str], log: Path) -> None:
    result = subprocess.run(command, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write("$ " + " ".join(command) + "\n" + result.stdout + "\n")
    require(result.returncode == 0, f"command_failed:{command[1]}:{result.returncode}")


def preflight() -> dict[str, object]:
    required = [
        SOURCE / "config/protocol_spec.json", SOURCE / "scripts/run_job.py", SOURCE / "scripts/score_pose.py",
        SOURCE / "reports/reference_normalization_summary.json", PANEL, ALLOCATION, CUSTOM_BUILDER,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    require(not missing, "preflight_missing:" + ",".join(missing))
    _, panel = read_tsv(PANEL); _, allocation = read_tsv(ALLOCATION)
    require(len(panel) == 10000 and len({row["candidate_id"] for row in panel}) == 10000, "preflight_panel_count")
    require(len(allocation) == 25000 and len({row["job_id"] for row in allocation}) == 25000, "preflight_allocation_count")
    require(not FINAL_ROOT.exists(), f"preflight_final_root_exists:{FINAL_ROOT}")
    ssh = subprocess.run(["ssh", "-o", "BatchMode=yes", "node23", "true"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(ssh.returncode == 0, "preflight_node23_ssh")
    free = shutil.disk_usage("/data").free
    require(free >= 5 * 1024**4, f"preflight_nfs_free_below_5TiB:{free}")
    payload = {
        "schema_version":"pvrig_v29_full_docking_preflight_v1", "status":"PASS_WAITING_MONOMER_TERMINAL",
        "panel_count":10000, "allocation_count":25000, "node1_parallel_jobs":5, "node23_parallel_jobs":8,
        "nfs_free_bytes":free, "monomer_complete":MONOMER_COMPLETE.is_file(),
        "input_hashes":{"panel":sha256_file(PANEL),"allocation":sha256_file(ALLOCATION),"custom_builder":sha256_file(CUSTOM_BUILDER)},
        "claim_boundary":CLAIM,
    }
    return payload


def stage() -> tuple[Path, dict[str, object]]:
    require(not FINAL_ROOT.exists(), f"final_root_exists:{FINAL_ROOT}")
    required = [SOURCE, PANEL, ALLOCATION, MONOMER_COMPLETE, MONOMER_MANIFEST, CUSTOM_BUILDER]
    require(all(path.exists() for path in required), "required_input_missing")
    complete = json.loads(MONOMER_COMPLETE.read_text())
    require(complete.get("status") == "PASS_MONOMER_BATCH_TERMINAL", "monomer_batch_not_terminal")
    _, panel = read_tsv(PANEL); panel_by = {row["candidate_id"]: row for row in panel}
    allocation_fields, allocation_all = read_tsv(ALLOCATION)
    _, monomers = read_tsv(MONOMER_MANIFEST)
    require(len(panel) == 10000 and len(allocation_all) == 25000 and len(monomers) == 10000, "input_count_closure")
    successful = [row for row in monomers if row["monomer_status"] == "SUCCESS"]
    failures = [row for row in monomers if row["monomer_status"] != "SUCCESS"]
    success_ids = {row["candidate_id"] for row in successful}
    executable_allocation = [row for row in allocation_all if row["candidate_id"] in success_ids]
    expected_executable = sum(1 for row in allocation_all if row["candidate_id"] in success_ids)
    require(len(executable_allocation) == expected_executable, "executable_allocation_count")
    staging = FINAL_ROOT.with_name(f".{FINAL_ROOT.name}.staging.{os.getpid()}")
    require(not staging.exists(), f"staging_exists:{staging}")
    for directory in ("config", "scripts"):
        shutil.copytree(SOURCE / directory, staging / directory)
    shutil.copy2(CUSTOM_BUILDER, staging / "scripts/build_docking_jobs.py")
    for directory in ("source", "normalized"):
        shutil.copytree(SOURCE / "inputs" / directory, staging / "inputs" / directory)
    for directory in ("inputs/candidate_monomers", "manifests", "reports", "status/jobs", "status/locks", "logs/jobs", "runs", "results", "failed_attempts"):
        (staging / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / "reports/reference_normalization_summary.json", staging / "reports/reference_normalization_summary.json")

    candidates: list[dict[str, str]] = []
    frozen: list[dict[str, str]] = []
    for monomer in successful:
        candidate_id = monomer["candidate_id"]; row = panel_by[candidate_id]
        sequence = row["sequence"]
        cdrs = {label: row[f"{label}_after"] for label in ("cdr1", "cdr2", "cdr3")}
        require(
            all(cdrs[label] and sequence.count(cdrs[label]) == 1 for label in cdrs),
            f"designed_cdr_absent_or_nonunique:{candidate_id}",
        )
        source = Path(monomer["pdb_path"])
        require(source.is_file() and sha256_file(source) == monomer["pdb_sha256"], f"monomer_invalid:{candidate_id}")
        destination = staging / "inputs/candidate_monomers" / f"{candidate_id}.pdb"
        shutil.copy2(source, destination)
        candidates.append({
            "candidate_id": candidate_id, "sequence": sequence, "sequence_sha256": row["sequence_sha256"],
            "cdr1": cdrs["cdr1"], "cdr2": cdrs["cdr2"], "cdr3": cdrs["cdr3"],
            "parent_framework_cluster": row["parent_framework_cluster"], "model_split": row["model_split"],
        })
        frozen.append({
            "candidate_id": candidate_id, "sequence_sha256": row["sequence_sha256"],
            "frozen_monomer_path": str(destination.relative_to(staging)), "source_chain": "A",
            "sha256": sha256_file(destination), "size_bytes": str(destination.stat().st_size),
        })
    require(len(candidates) == len(success_ids), "candidate_success_closure")
    write_tsv(staging / "inputs/candidates_128.tsv", candidates, list(candidates[0]))
    write_tsv(staging / "inputs/candidate_monomers_manifest.tsv", frozen, list(frozen[0]))
    control_fields, _ = read_tsv(SOURCE / "inputs/calibration_controls_47.tsv")
    write_tsv(staging / "inputs/calibration_controls_47.tsv", [], control_fields)
    write_tsv(staging / "inputs/docking_allocation25000.tsv", executable_allocation, allocation_fields)
    write_tsv(staging / "inputs/docking_allocation25000_frozen_all.tsv", allocation_all, allocation_fields)
    failure_fields = list(failures[0]) if failures else ["candidate_id", "sequence_sha256", "monomer_status", "technical_failure_reason"]
    write_tsv(staging / "inputs/monomer_technical_failures.tsv", failures, failure_fields)

    protocol_path = staging / "config/protocol_spec.json"
    protocol = json.loads(protocol_path.read_text())
    protocol.update({"protocol_id": PROTOCOL_ID, "status": "PRELOCK_VALIDATION_REQUIRED", "evidence_boundary": CLAIM})
    protocol["candidate_panel"].update({
        "panel_id": "v29_anarci_verified_docking10k_no_replacement_v1", "expected_count": len(candidates),
        "selection_algorithm": "frozen_allocation_exact_with_technical_failures_NA_no_replacement",
        "monomer_source_policy": "NanoBodyBuilder2_refined_then_unrefined_fallback_hash_bound",
    })
    protocol["controls"].update({"panel_id": "reused_frozen_evaluator_controls_not_rerun", "expected_count": 0})
    protocol["docking"].update({
        "seeds": [917, 1931, 3253], "expected_candidate_jobs": len(executable_allocation),
        "expected_control_jobs": 0, "expected_total_jobs": len(executable_allocation),
        "smoke_seed": 917, "smoke_control_id": "", "smoke_candidate_id": candidates[0]["candidate_id"],
        "expected_smoke_jobs": 2,
    })
    protocol["scheduler"]["max_parallel"] = 13
    write_json(protocol_path, protocol)

    freeze_path = staging / "scripts/freeze_protocol.py"
    freeze_text = freeze_path.read_text()
    require("len(monomers) != 128" in freeze_text, "freeze_count_patch_anchor_missing")
    freeze_text = freeze_text.replace("len(monomers) != 128", f"len(monomers) != {len(candidates)}")
    freeze_text = freeze_text.replace("expected 128 frozen candidate monomers", f"expected {len(candidates)} frozen candidate monomers")
    anchor = '    "inputs/candidates_128.tsv",\n'
    require(anchor in freeze_text, "freeze_allocation_anchor_missing")
    freeze_text = freeze_text.replace(anchor, anchor + '    "inputs/docking_allocation25000.tsv",\n')
    freeze_path.write_text(freeze_text)

    python = Path("/data/qlyu/anaconda3/envs/haddock3/bin/python")
    env = {**os.environ, "PVRIG_PROJECT_ROOT": str(staging)}
    run_checked([str(python), "scripts/freeze_protocol.py", "core", "--root", str(staging)], staging, env, staging / "logs/staging.log")
    run_checked([str(python), "scripts/build_docking_jobs.py"], staging, env, staging / "logs/staging.log")
    _, jobs = read_tsv(staging / "manifests/docking_jobs.tsv")
    require(len(jobs) == len(executable_allocation), "job_manifest_count")
    jobs = sorted(jobs, key=lambda row: row["job_hash"])
    node1, node23 = jobs[::2], jobs[1::2]
    shard_fields = ["job_id", "entity_id", "conformation", "seed", "job_hash"]
    write_tsv(staging / "manifests/node1_jobs.tsv", node1, shard_fields)
    write_tsv(staging / "manifests/node23_jobs.tsv", node23, shard_fields)
    core = json.loads((staging / "PROTOCOL_CORE_LOCK.json").read_text())
    material = {
        "schema_version": 1, "protocol_id": PROTOCOL_ID, "protocol_core_sha256": core["protocol_core_sha256"],
        "core_lock_sha256": sha256_file(staging / "PROTOCOL_CORE_LOCK.json"), "job_count": len(jobs),
        "job_manifest_sha256": sha256_file(staging / "manifests/docking_jobs.tsv"),
        "node1_jobs_sha256": sha256_file(staging / "manifests/node1_jobs.tsv"),
        "node23_jobs_sha256": sha256_file(staging / "manifests/node23_jobs.tsv"),
        "reference_normalization_summary_sha256": sha256_file(staging / "reports/reference_normalization_summary.json"),
    }
    launch_specs = {
        "node1": (5, "/data1/qlyu/scratch/pvrig_v29_docking25k"),
        "node23": (8, "/tmp/pvrig_v29_docking25k"),
    }
    for host, (parallel, scratch) in launch_specs.items():
        script = staging / f"scripts/launch_{host}_shard.sh"
        script.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            f"ROOT={FINAL_ROOT}\nSCRATCH={scratch}\nmkdir -p \"$SCRATCH\"\n"
            f"tail -n +2 \"$ROOT/manifests/{host}_jobs.tsv\" | cut -f1 | "
            f"xargs -r -I{{}} -P{parallel} sh -c 'PVRIG_PROJECT_ROOT=\"$2\" PVRIG_LOCAL_SCRATCH_ROOT=\"$3\" "
            "HADDOCK3=/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 "
            "/data/qlyu/anaconda3/envs/haddock3/bin/python \"$2/scripts/run_job.py\" \"$1\" --max-attempts 2' "
            "_ {} \"$ROOT\" \"$SCRATCH\"\n"
        )
        script.chmod(0o755)
    material["launch_script_hashes"] = {
        host: sha256_file(staging / f"scripts/launch_{host}_shard.sh") for host in launch_specs
    }
    lock = {**material, "status": "LOCKED", "protocol_lock_sha256": sha256_text(json.dumps(material, sort_keys=True, separators=(",", ":")))}
    write_json(staging / "PROTOCOL_LOCK.json", lock)
    receipt = {
        "schema_version": "pvrig_v29_full_docking_stage_v1", "status": "PASS_FULL_DOCKING_STAGED",
        "panel_count": 10000, "monomer_success_count": len(candidates), "monomer_technical_failure_count": len(failures),
        "frozen_allocation_count": 25000, "executable_job_count": len(jobs),
        "node1_job_count": len(node1), "node23_job_count": len(node23),
        "docking_cdr_source": "sequence_exact_unique_cdr1_after_cdr2_after_cdr3_after",
        "protocol_core_sha256": core["protocol_core_sha256"], "protocol_lock_sha256": lock["protocol_lock_sha256"],
        "claim_boundary": CLAIM,
    }
    write_json(staging / "status/STAGED.json", receipt)
    os.replace(staging, FINAL_ROOT)
    return FINAL_ROOT, receipt


def launch(root: Path, receipt: dict[str, object]) -> dict[str, object]:
    node1_log = (root / "logs/node1_shard.log").open("ab")
    node1_process = subprocess.Popen(
        [str(root / "scripts/launch_node1_shard.sh")],
        stdout=node1_log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    (root / "status/node1_shard.pid").write_text(str(node1_process.pid) + "\n")
    remote_inner = (
        f"nohup {root}/scripts/launch_node23_shard.sh > {root}/logs/node23_shard.log "
        "2>&1 < /dev/null & echo $!"
    )
    remote = subprocess.run(["ssh", "-o", "BatchMode=yes", "node23", remote_inner], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(remote.returncode == 0 and remote.stdout.strip().isdigit(), f"node23_launch_failed:{remote.stderr}")
    (root / "status/node23_shard.pid").write_text(remote.stdout.strip() + "\n")
    launched = {**receipt, "status": "RUNNING_FULL_DOCKING", "node1_pid": node1_process.pid, "node23_pid": int(remote.stdout.strip())}
    write_json(root / "status/LAUNCHED.json", launched)
    return launched


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--preflight",action="store_true"); parser.add_argument("--stage-only",action="store_true")
    args=parser.parse_args()
    if args.preflight:
        print(json.dumps(preflight(),indent=2,sort_keys=True))
    else:
        project, staged = stage()
        print(json.dumps(staged if args.stage_only else launch(project, staged), indent=2, sort_keys=True))
