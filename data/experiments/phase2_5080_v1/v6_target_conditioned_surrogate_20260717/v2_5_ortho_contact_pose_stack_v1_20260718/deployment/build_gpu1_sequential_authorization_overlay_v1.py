#!/usr/bin/env python3
"""Build/audit a pending explicit-authorization GPU1 sequential smoke overlay.

The overlay is deliberately not launch-authorized.  It binds an immutable
six-job command plan and a fail-closed launcher that requires a separately
materialized operator authorization file.  This builder never launches a job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve()
CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking geometry; "
    "not binding probability, affinity, experimental blocking, Docking Gold, or submission evidence."
)
SCHEMA_VERSION = "pvrig_v2_5_gpu1_sequential_explicit_authorization_overlay_v1"
SOURCE_REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_20260718"
OVERLAY_REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_overlay_v1_20260718"
RUNTIME_REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_smoke_runtime_v1_20260718"
AUTHORIZATION_REMOTE_PATH = "/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_operator_authorization_v1_20260718.json"
NODE1_PYTHON = "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
TASKSET = "/usr/bin/taskset"
ENV = "/usr/bin/env"
PHYSICAL_GPU = 1
CPU_CORE_LIST = "0-7"
MAX_CPU_PER_PROCESS = 8
AUTH_TOKEN = "I_ACCEPT_V2_5_GPU1_SEQUENTIAL_ONE_EPOCH_REAL_SMOKE"
AUTH_TOKEN_SHA256 = hashlib.sha256(AUTH_TOKEN.encode()).hexdigest()
LANE_ORDER = (
    "B_CLEAN_TARGET_ATTENTION",
    "E_DECOUPLED_CONTACT_DETACHED",
    "E_DECOUPLED_CONTACT_SHARED",
)
SOURCE_EXPECTED = {
    "INPUT_CONTRACT.json": "2162a2e396ccde97098a8382cb972d502995d6e0ac12f536292e541293962946",
    "NONLAUNCHING_JOB_PLAN.json": "aa3915bc9ba92cb5f8bac2be3027ff0f5949f36bf4ceb35b44f5ac9bf204d514",
    "PACKAGE_MANIFEST.json": "8fb2fda3c9d1ab19b1ed881e9c13fff826efccc6c14238182ce784e205af6849",
    "SHA256SUMS": "95788336b963a3eaf953f6c5434e94840cfd18cd5bb2a3d6eabc2e590a68d0a4",
    "src/residue_model_v2_5_ortho.py": "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521",
    "src/run_real1507_split_v1.py": "9f5dcedc1873628af9081a4d82fb2d1cc62634a12584f2286abe7a0ba4054e3a",
    "src/train_v2_5_ortho_heads.py": "a3d480fe4e164e74e2f64598e8ca53d42131c2e9e6ad16074fb7274e33a906b8",
}


class OverlayError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OverlayError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"json_object_required:{path}")
    return value


def read_sha256s(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        require(len(digest) == 64 and relative not in result, f"sha256s_invalid:{relative}")
        result[relative] = digest
    return result


def validate_source(source_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    require(source_root.is_dir() and not source_root.is_symlink(), "source_package_missing_or_symlink")
    for relative, expected in SOURCE_EXPECTED.items():
        path = source_root / relative
        require(path.is_file() and not path.is_symlink(), f"source_file_missing_or_symlink:{relative}")
        require(sha256_file(path) == expected, f"source_file_hash:{relative}")
    source_sha = read_sha256s(source_root / "SHA256SUMS")
    require(source_sha == {key: SOURCE_EXPECTED[key] for key in source_sha}, "source_sha256_manifest_values")
    require(set(source_sha) == {
        "INPUT_CONTRACT.json", "NONLAUNCHING_JOB_PLAN.json", "PACKAGE_MANIFEST.json",
        "src/residue_model_v2_5_ortho.py", "src/run_real1507_split_v1.py",
        "src/train_v2_5_ortho_heads.py",
    }, "source_sha256_manifest_members")
    source_manifest = read_json(source_root / "PACKAGE_MANIFEST.json")
    source_plan = read_json(source_root / "NONLAUNCHING_JOB_PLAN.json")
    source_inputs = read_json(source_root / "INPUT_CONTRACT.json")
    require(source_manifest.get("status") == "PASS_BUILD_TEST_DRY_RUN_NOT_DEPLOYED_NOT_LAUNCHED", "source_status")
    require(source_manifest.get("launch_authorized") is False, "source_launch_authorized")
    require(source_manifest.get("training_or_prediction_executed") is False, "source_already_executed")
    require(source_plan.get("job_count") == 6 and len(source_plan.get("jobs", [])) == 6, "source_job_count")
    require(all(job.get("command") is None for job in source_plan["jobs"]), "source_commands_not_null")
    require(source_inputs.get("training_contact_graph_candidate_closure") is True, "source_candidate_closure")
    require(source_inputs.get("v4_f_test32_access_count") == 0, "source_v4_f_access")
    require(source_inputs.get("prediction_metrics_access_count") == 0, "source_metrics_access")
    counts = source_inputs["source_local_evidence"]["counts"]
    require(counts == {"rows": 1269, "parents": 28, "train_rows": 1085, "score_rows": 184}, "source_counts")
    return {
        "root": str(source_root),
        "hashes": dict(SOURCE_EXPECTED),
        "source_sha256_manifest": source_sha,
        "source_plan": source_plan,
        "source_manifest": source_manifest,
        "source_inputs": source_inputs,
    }


def command_value(command: Sequence[str], option: str) -> str:
    require(command.count(option) == 1, f"command_option_count:{option}")
    index = command.index(option)
    require(index + 1 < len(command), f"command_option_value:{option}")
    return command[index + 1]


def source_job(source_plan: Mapping[str, Any], lane: str, suffix: str) -> Mapping[str, Any]:
    job_id = f"{lane}.{suffix}"
    jobs = [job for job in source_plan["jobs"] if job.get("job_id") == job_id]
    require(len(jobs) == 1, f"source_job_identity:{job_id}")
    return jobs[0]


def gpu1_command(source_command: Sequence[str], output_dir: str) -> list[str]:
    require(source_command and source_command[0] == NODE1_PYTHON, "source_python_drift")
    require(source_command[1] == f"{SOURCE_REMOTE_ROOT}/src/run_real1507_split_v1.py", "source_runner_drift")
    command = list(source_command)
    output_index = command.index("--output-dir") + 1
    command[output_index] = output_dir
    prefix = [
        TASKSET, "-c", CPU_CORE_LIST, ENV,
        "CUDA_VISIBLE_DEVICES=1",
        "OMP_NUM_THREADS=8",
        "MKL_NUM_THREADS=8",
        "OPENBLAS_NUM_THREADS=8",
        "NUMEXPR_NUM_THREADS=8",
        "TORCH_NUM_THREADS=8",
    ]
    return prefix + command


def validate_bound_command(command: Sequence[str], lane: str, mode: str, output_dir: str) -> None:
    prefix = [
        TASKSET, "-c", CPU_CORE_LIST, ENV,
        "CUDA_VISIBLE_DEVICES=1", "OMP_NUM_THREADS=8", "MKL_NUM_THREADS=8",
        "OPENBLAS_NUM_THREADS=8", "NUMEXPR_NUM_THREADS=8", "TORCH_NUM_THREADS=8",
    ]
    require(list(command[: len(prefix)]) == prefix, f"resource_prefix:{lane}:{mode}")
    payload = list(command[len(prefix):])
    require(payload[:2] == [NODE1_PYTHON, f"{SOURCE_REMOTE_ROOT}/src/run_real1507_split_v1.py"], "node1_python_runner_binding")
    require(command_value(payload, "--lane-variant") == lane, "lane_command_drift")
    require(command_value(payload, "--mode") == mode, "mode_command_drift")
    require(command_value(payload, "--output-dir") == output_dir, "output_command_drift")
    require(command_value(payload, "--device") == "cuda", "cuda_device_drift")
    joined = " ".join(payload).lower().replace("-", "_")
    require("v4_f" not in joined and "test32" not in joined, "sealed_command_reference")


def build_plan(source_plan: Mapping[str, Any]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    previous: str | None = None
    for lane in LANE_ORDER:
        for suffix, mode in (("preoptimizer", "preoptimizer"), ("one_epoch_smoke", "train-smoke")):
            source = source_job(source_plan, lane, suffix)
            job_id = f"{lane}.{suffix}"
            output_dir = f"{RUNTIME_REMOTE_ROOT}/{len(jobs):02d}_{job_id}"
            command = gpu1_command(source["command_template"], output_dir)
            validate_bound_command(command, lane, mode, output_dir)
            jobs.append({
                "job_id": job_id,
                "source_job_id": job_id,
                "kind": source["kind"],
                "lane": lane,
                "mode": mode,
                "physical_gpu": PHYSICAL_GPU,
                "visible_cuda_devices": [PHYSICAL_GPU],
                "cuda_logical_device": 0,
                "cpu_core_list": CPU_CORE_LIST,
                "max_cpu_per_process": MAX_CPU_PER_PROCESS,
                "dependencies": [] if previous is None else [previous],
                "command": None,
                "command_template": command,
                "output_dir": output_dir,
                "expected_result": f"{output_dir}/RESULT.json",
            })
            previous = job_id
    return {
        "schema_version": "pvrig_v2_5_gpu1_sequential_job_plan_v1",
        "status": "PENDING_EXPLICIT_OPERATOR_AUTHORIZATION_NOT_LAUNCHABLE",
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "job_count": 6,
        "max_concurrent_jobs": 1,
        "strictly_sequential": True,
        "physical_gpu_allowlist": [PHYSICAL_GPU],
        "cpu_core_list": CPU_CORE_LIST,
        "max_cpu_per_process": MAX_CPU_PER_PROCESS,
        "node1_python": NODE1_PYTHON,
        "source_package_root": SOURCE_REMOTE_ROOT,
        "runtime_root": RUNTIME_REMOTE_ROOT,
        "jobs": jobs,
        "claim_boundary": CLAIM_BOUNDARY,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }


def launcher_source(plan_sha: str, overlay_sha: str, source_manifest_sha: str, source_sha256s_sha: str) -> str:
    return f'''#!/usr/bin/env python3
"""Fail-closed sequential launcher; requires a separate operator authorization file."""
import hashlib, json, os, subprocess
from pathlib import Path

PACKAGE_ROOT = Path({OVERLAY_REMOTE_ROOT!r})
SOURCE_ROOT = Path({SOURCE_REMOTE_ROOT!r})
RUNTIME_ROOT = Path({RUNTIME_REMOTE_ROOT!r})
AUTHORIZATION = Path({AUTHORIZATION_REMOTE_PATH!r})
PLAN = PACKAGE_ROOT / "GPU1_SEQUENTIAL_JOB_PLAN.json"
OVERLAY = PACKAGE_ROOT / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
EXPECTED_PLAN_SHA = {plan_sha!r}
EXPECTED_OVERLAY_SHA = {overlay_sha!r}
EXPECTED_SOURCE_MANIFEST_SHA = {source_manifest_sha!r}
EXPECTED_SOURCE_SHA256S_SHA = {source_sha256s_sha!r}
EXPECTED_AUTH_TOKEN_SHA = {AUTH_TOKEN_SHA256!r}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    require(sha(PLAN) == EXPECTED_PLAN_SHA, "plan_hash_gate")
    require(sha(OVERLAY) == EXPECTED_OVERLAY_SHA, "overlay_hash_gate")
    require(sha(SOURCE_ROOT / "PACKAGE_MANIFEST.json") == EXPECTED_SOURCE_MANIFEST_SHA, "source_manifest_hash_gate")
    require(sha(SOURCE_ROOT / "SHA256SUMS") == EXPECTED_SOURCE_SHA256S_SHA, "source_sha256s_hash_gate")
    require(AUTHORIZATION.is_file() and not AUTHORIZATION.is_symlink(), "explicit_operator_authorization_missing")
    auth = json.loads(AUTHORIZATION.read_text())
    require(auth.get("status") == "EXPLICITLY_AUTHORIZED_FOR_ONE_GPU1_SEQUENTIAL_REAL_SMOKE", "authorization_status")
    require(hashlib.sha256(str(auth.get("authorization_token", "")).encode()).hexdigest() == EXPECTED_AUTH_TOKEN_SHA, "authorization_token")
    require(auth.get("job_plan_sha256") == EXPECTED_PLAN_SHA, "authorization_plan_binding")
    require(auth.get("overlay_sha256") == EXPECTED_OVERLAY_SHA, "authorization_overlay_binding")
    require(auth.get("physical_gpu") == 1 and auth.get("max_cpu_per_process") == 8, "authorization_resources")
    require(auth.get("v4_f_test32_access_count") == 0, "authorization_sealed_access")
    plan = json.loads(PLAN.read_text())
    require(plan.get("launch_authorized") is False and plan.get("job_count") == 6, "pending_plan_contract")
    jobs = plan["jobs"]
    require(all(job.get("command") is None for job in jobs), "immutable_pending_commands")
    require(not RUNTIME_ROOT.exists(), "runtime_root_exists")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=False)
    completed_ids = []
    for index, job in enumerate(jobs):
        require(job["dependencies"] == ([] if index == 0 else [jobs[index - 1]["job_id"]]), "sequential_dependency")
        require(job["physical_gpu"] == 1 and job["max_cpu_per_process"] == 8, "job_resource_gate")
        command = job["command_template"]
        require(command[:4] == ["/usr/bin/taskset", "-c", "0-7", "/usr/bin/env"], "taskset_gate")
        require("CUDA_VISIBLE_DEVICES=1" in command and {NODE1_PYTHON!r} in command, "gpu_python_gate")
        log_dir = RUNTIME_ROOT / "logs" / f"{{index:02d}}_{{job['job_id']}}"
        log_dir.mkdir(parents=True)
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        (log_dir / "STDOUT.log").write_text(completed.stdout)
        (log_dir / "STDERR.log").write_text(completed.stderr)
        terminal = {{"job_id": job["job_id"], "returncode": completed.returncode, "status": "PASS" if completed.returncode == 0 else "FAIL"}}
        (log_dir / "TERMINAL.json").write_text(json.dumps(terminal, indent=2, sort_keys=True) + "\\n")
        require(completed.returncode == 0, f"job_failed:{{job['job_id']}}")
        result = Path(job["expected_result"])
        require(result.is_file() and not result.is_symlink(), f"result_missing:{{job['job_id']}}")
        receipt = json.loads(result.read_text())
        require(receipt.get("v4_f_test32_access_count") == 0 and receipt.get("prediction_metrics_access_count") == 0, "result_firewall")
        completed_ids.append(job["job_id"])
    final = {{"status": "PASS_GPU1_SEQUENTIAL_REAL_SMOKE", "completed_jobs": completed_ids, "job_count": 6, "physical_gpu": 1, "max_cpu_per_process": 8, "v4_f_test32_access_count": 0}}
    (RUNTIME_ROOT / "TERMINAL.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def expected_sequential_dependencies(jobs: Sequence[Mapping[str, Any]]) -> None:
    require(len(jobs) == 6, "overlay_job_count")
    for index, job in enumerate(jobs):
        expected = [] if index == 0 else [jobs[index - 1]["job_id"]]
        require(job.get("dependencies") == expected, f"sequential_dependency:{job.get('job_id')}")


def build_package(source_root: Path, output_dir: Path) -> dict[str, Any]:
    source = validate_source(source_root)
    output_dir = output_dir.resolve()
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    try:
        (output_dir / "src").mkdir(parents=True)
        binding = {
            "schema_version": "pvrig_v2_5_gpu1_overlay_source_binding_v1",
            "source_local_root": source["root"],
            "source_node1_root": SOURCE_REMOTE_ROOT,
            "source_hashes": source["hashes"],
            "source_sha256_manifest": source["source_sha256_manifest"],
            "model_data_parent_contact_graph_hash_firewall_unchanged": True,
            "source_counts": {"rows": 1269, "parents": 28, "train_rows": 1085, "score_rows": 184},
            "claim_boundary": CLAIM_BOUNDARY,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        write_json(output_dir / "SOURCE_PACKAGE_BINDING.json", binding)
        overlay = {
            "schema_version": SCHEMA_VERSION,
            "status": "AUDITED_PENDING_EXPLICIT_OPERATOR_AUTHORIZATION",
            "launch_authorized": False,
            "training_or_prediction_executed": False,
            "authorization_scope": "one strictly sequential six-job outer0/inner0 real preoptimizer plus one-epoch smoke on physical GPU1",
            "authorization_token_sha256": AUTH_TOKEN_SHA256,
            "authorization_file_node1_path": AUTHORIZATION_REMOTE_PATH,
            "authorization_file_included": False,
            "model_data_parent_contact_graph_hash_firewall_unchanged": True,
            "source_package_manifest_sha256": SOURCE_EXPECTED["PACKAGE_MANIFEST.json"],
            "source_package_sha256s_sha256": SOURCE_EXPECTED["SHA256SUMS"],
            "physical_gpu_allowlist": [PHYSICAL_GPU],
            "max_concurrent_jobs": 1,
            "cpu_core_list": CPU_CORE_LIST,
            "max_cpu_per_process": MAX_CPU_PER_PROCESS,
            "node1_python": NODE1_PYTHON,
            "claim_boundary": CLAIM_BOUNDARY,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        write_json(output_dir / "EXPLICIT_AUTHORIZATION_OVERLAY.json", overlay)
        plan = build_plan(source["source_plan"])
        write_json(output_dir / "GPU1_SEQUENTIAL_JOB_PLAN.json", plan)
        plan_sha = sha256_file(output_dir / "GPU1_SEQUENTIAL_JOB_PLAN.json")
        overlay_sha = sha256_file(output_dir / "EXPLICIT_AUTHORIZATION_OVERLAY.json")
        launcher = output_dir / "src" / "launch_gpu1_sequential_smoke_v1.py"
        launcher.write_text(launcher_source(
            plan_sha, overlay_sha, SOURCE_EXPECTED["PACKAGE_MANIFEST.json"], SOURCE_EXPECTED["SHA256SUMS"]
        ))
        launcher.chmod(0o755)
        manifest = {
            "schema_version": "pvrig_v2_5_gpu1_sequential_overlay_package_v1",
            "status": "PASS_BUILD_TEST_AUDIT_PENDING_EXPLICIT_OPERATOR_AUTHORIZATION_NOT_LAUNCHED",
            "launch_authorized": False,
            "training_or_prediction_executed": False,
            "source_binding_sha256": sha256_file(output_dir / "SOURCE_PACKAGE_BINDING.json"),
            "explicit_authorization_overlay_sha256": overlay_sha,
            "job_plan_sha256": plan_sha,
            "launcher_sha256": sha256_file(launcher),
            "job_count": 6,
            "strictly_sequential": True,
            "physical_gpu_allowlist": [PHYSICAL_GPU],
            "max_cpu_per_process": MAX_CPU_PER_PROCESS,
            "node1_python": NODE1_PYTHON,
            "node1_overlay_root": OVERLAY_REMOTE_ROOT,
            "node1_source_package_root": SOURCE_REMOTE_ROOT,
            "node1_runtime_root": RUNTIME_REMOTE_ROOT,
            "authorization_file_node1_path": AUTHORIZATION_REMOTE_PATH,
            "authorization_file_included": False,
            "claim_boundary": CLAIM_BOUNDARY,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        write_json(output_dir / "PACKAGE_MANIFEST.json", manifest)
        files = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
        (output_dir / "SHA256SUMS").write_text("".join(
            f"{sha256_file(path)}  {path.relative_to(output_dir)}\n" for path in files
        ))
        return manifest
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def audit_package(source_root: Path, package_root: Path) -> dict[str, Any]:
    source = validate_source(source_root)
    package_root = package_root.resolve()
    require(package_root.is_dir() and not package_root.is_symlink(), "overlay_package_missing_or_symlink")
    expected_files = {
        "SOURCE_PACKAGE_BINDING.json", "EXPLICIT_AUTHORIZATION_OVERLAY.json",
        "GPU1_SEQUENTIAL_JOB_PLAN.json", "PACKAGE_MANIFEST.json", "SHA256SUMS",
        "src/launch_gpu1_sequential_smoke_v1.py",
    }
    actual_files = {str(path.relative_to(package_root)) for path in package_root.rglob("*") if path.is_file()}
    require(actual_files == expected_files, "overlay_package_file_members")
    sha_manifest = read_sha256s(package_root / "SHA256SUMS")
    require(set(sha_manifest) == expected_files - {"SHA256SUMS"}, "overlay_sha256_members")
    for relative, expected in sha_manifest.items():
        path = package_root / relative
        require(not path.is_symlink() and sha256_file(path) == expected, f"overlay_file_hash:{relative}")
    manifest = read_json(package_root / "PACKAGE_MANIFEST.json")
    overlay = read_json(package_root / "EXPLICIT_AUTHORIZATION_OVERLAY.json")
    plan = read_json(package_root / "GPU1_SEQUENTIAL_JOB_PLAN.json")
    binding = read_json(package_root / "SOURCE_PACKAGE_BINDING.json")
    require(manifest.get("launch_authorized") is False and overlay.get("launch_authorized") is False, "overlay_premature_authorization")
    require(plan.get("launch_authorized") is False, "plan_premature_authorization")
    require(manifest.get("training_or_prediction_executed") is False, "overlay_execution_claim")
    require(overlay.get("authorization_file_included") is False and manifest.get("authorization_file_included") is False, "authorization_file_included")
    require(not (package_root / "EXPLICIT_OPERATOR_AUTHORIZATION.json").exists(), "local_authorization_file_forbidden")
    require(manifest["source_binding_sha256"] == sha256_file(package_root / "SOURCE_PACKAGE_BINDING.json"), "binding_hash")
    require(manifest["explicit_authorization_overlay_sha256"] == sha256_file(package_root / "EXPLICIT_AUTHORIZATION_OVERLAY.json"), "overlay_hash")
    require(manifest["job_plan_sha256"] == sha256_file(package_root / "GPU1_SEQUENTIAL_JOB_PLAN.json"), "plan_hash")
    require(manifest["launcher_sha256"] == sha256_file(package_root / "src/launch_gpu1_sequential_smoke_v1.py"), "launcher_hash")
    require(binding.get("source_hashes") == source["hashes"], "source_binding_hashes")
    require(binding.get("source_sha256_manifest") == source["source_sha256_manifest"], "source_binding_manifest")
    require(binding.get("model_data_parent_contact_graph_hash_firewall_unchanged") is True, "source_binding_contract")
    require(plan.get("job_count") == 6 and plan.get("strictly_sequential") is True, "plan_shape")
    require(plan.get("max_concurrent_jobs") == 1, "plan_concurrency")
    require(plan.get("physical_gpu_allowlist") == [PHYSICAL_GPU], "plan_gpu")
    require(plan.get("max_cpu_per_process") == MAX_CPU_PER_PROCESS, "plan_cpu")
    require(plan.get("node1_python") == NODE1_PYTHON, "plan_python")
    jobs = plan["jobs"]
    expected_sequential_dependencies(jobs)
    expected_ids = []
    for lane in LANE_ORDER:
        expected_ids.extend([f"{lane}.preoptimizer", f"{lane}.one_epoch_smoke"])
    require([job["job_id"] for job in jobs] == expected_ids, "plan_job_order")
    for job in jobs:
        require(job.get("command") is None, f"job_command_not_null:{job['job_id']}")
        require(job.get("physical_gpu") == PHYSICAL_GPU and job.get("visible_cuda_devices") == [PHYSICAL_GPU], "job_gpu")
        require(job.get("max_cpu_per_process") == MAX_CPU_PER_PROCESS and job.get("cpu_core_list") == CPU_CORE_LIST, "job_cpu")
        validate_bound_command(job["command_template"], job["lane"], job["mode"], job["output_dir"])
    for record in (manifest, overlay, plan, binding):
        require(record.get("v4_f_test32_access_count") == 0, "sealed_access_count")
        require(record.get("prediction_metrics_access_count") == 0, "metrics_access_count")
        require(record.get("claim_boundary") == CLAIM_BOUNDARY, "claim_boundary")
    return {
        "schema_version": "pvrig_v2_5_gpu1_sequential_overlay_audit_v1",
        "status": "PASS_GPU1_SEQUENTIAL_OVERLAY_AUDIT_PENDING_AUTHORIZATION_NOT_LAUNCHED",
        "source_files_verified": len(source["hashes"]),
        "overlay_files_verified": len(expected_files),
        "job_count": len(jobs),
        "strictly_sequential": True,
        "physical_gpu": PHYSICAL_GPU,
        "max_cpu_per_process": MAX_CPU_PER_PROCESS,
        "node1_python": NODE1_PYTHON,
        "launch_authorized": False,
        "training_or_prediction_executed": False,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--source-package-root", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--audit-only", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = audit_package(args.source_package_root, args.output_dir) if args.audit_only else build_package(args.source_package_root, args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
