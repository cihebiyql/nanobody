#!/usr/bin/env python3
"""Build the isolated V1.1 recovery source/overlay/autostart packages.

V1.1 changes only the dynamic-import context used by the real-1507 adapter
loader and the launch-time audit plumbing.  Model, data, split, losses,
thresholds, GPU1/CPU8 resources and the sealed-test firewall remain identical
to the failed V1 attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
DATE = "20260718"
SOURCE_REMOTE_ROOT = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_1_{DATE}"
OVERLAY_REMOTE_ROOT = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_overlay_v1_1_{DATE}"
RUNTIME_REMOTE_ROOT = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_smoke_runtime_v1_1_{DATE}"
AUTH_REMOTE_PATH = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_sequential_operator_authorization_v1_1_{DATE}.json"
AUTOSTART_REMOTE_ROOT = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_recovery_autostart_package_v1_1_{DATE}"
WATCH_REMOTE_ROOT = f"/data1/qlyu/projects/pvrig_v2_5_ortho_heads_gpu1_recovery_watch_v1_1_{DATE}"
PILOT_REMOTE_ROOT = "/data1/qlyu/projects/pvrig_v2_5_d_inner_optimizer_pilot_runtime_v1_2_20260718"
NODE1_PYTHON = "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
AUTH_TOKEN = "I_ACCEPT_V2_5_GPU1_SEQUENTIAL_ONE_EPOCH_REAL_SMOKE_V1_1_RECOVERY"
CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking geometry; "
    "not binding probability, affinity, experimental blocking, Docking Gold, or submission evidence."
)


class RecoveryBuildError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryBuildError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def read_sha256s(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        require(len(digest) == 64 and relative not in result, f"sha256_line:{relative}")
        result[relative] = digest
    return result


def rewrite_json(path: Path, updates: Mapping[str, Any]) -> None:
    payload = json.loads(path.read_text())
    payload.update(dict(updates))
    atomic_json(path, payload)


def regenerate_sha256s(root: Path) -> None:
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(root)}\n" for path in files)
    )


def audit_file_closure(root: Path, expected_members: set[str] | None = None) -> dict[str, str]:
    require(root.is_dir() and not root.is_symlink(), f"package_root:{root}")
    require((root / "SHA256SUMS").is_file() and not (root / "SHA256SUMS").is_symlink(), "sha256s_missing")
    listed = read_sha256s(root)
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(set(listed) == actual, f"file_closure:{root}")
    if expected_members is not None:
        require(actual == expected_members, f"expected_members:{root}")
    for relative, expected in listed.items():
        path = root / relative
        require(not path.is_symlink() and sha256_file(path) == expected, f"file_hash:{root}:{relative}")
    return listed


def launcher_source(plan_sha: str, overlay_sha: str, source_manifest_sha: str, source_sha256s_sha: str) -> str:
    auth_token_sha = hashlib.sha256(AUTH_TOKEN.encode()).hexdigest()
    template = r'''#!/usr/bin/env python3
"""Fail-closed V1.1 sequential recovery launcher."""
import hashlib, json, os, subprocess, traceback
from pathlib import Path

PACKAGE_ROOT = Path(@OVERLAY_ROOT@)
SOURCE_ROOT = Path(@SOURCE_ROOT@)
RUNTIME_ROOT = Path(@RUNTIME_ROOT@)
AUTHORIZATION = Path(@AUTH_PATH@)
PLAN = PACKAGE_ROOT / "GPU1_SEQUENTIAL_JOB_PLAN.json"
OVERLAY = PACKAGE_ROOT / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
EXPECTED_PLAN_SHA = @PLAN_SHA@
EXPECTED_OVERLAY_SHA = @OVERLAY_SHA@
EXPECTED_SOURCE_MANIFEST_SHA = @SOURCE_MANIFEST_SHA@
EXPECTED_SOURCE_SHA256S_SHA = @SOURCE_SHA256S_SHA@
EXPECTED_AUTH_TOKEN_SHA = @AUTH_TOKEN_SHA@

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def atomic_json(path, payload):
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)

def read_sha256s(root):
    values = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        require(len(digest) == 64 and relative not in values, "sha256_line:" + relative)
        values[relative] = digest
    return values

def verify_package(root, expected_sha256s_sha):
    require(root.is_dir() and not root.is_symlink(), "package_root:" + str(root))
    sha_file = root / "SHA256SUMS"
    require(sha_file.is_file() and not sha_file.is_symlink(), "sha256s_missing:" + str(root))
    require(sha(sha_file) == expected_sha256s_sha, "sha256s_hash:" + str(root))
    listed = read_sha256s(root)
    actual = {
        str(path.relative_to(root)) for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(set(listed) == actual, "package_file_closure:" + str(root))
    for relative, expected in listed.items():
        path = root / relative
        require(not path.is_symlink() and sha(path) == expected, "package_file_hash:" + relative)
    return len(listed)

def write_final(status, **extra):
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    payload.update(extra)
    atomic_json(RUNTIME_ROOT / "TERMINAL.json", payload)

def run():
    require(sha(PLAN) == EXPECTED_PLAN_SHA, "plan_hash_gate")
    require(sha(OVERLAY) == EXPECTED_OVERLAY_SHA, "overlay_hash_gate")
    require(sha(SOURCE_ROOT / "PACKAGE_MANIFEST.json") == EXPECTED_SOURCE_MANIFEST_SHA, "source_manifest_hash_gate")
    require(AUTHORIZATION.is_file() and not AUTHORIZATION.is_symlink(), "explicit_operator_authorization_missing")
    auth = json.loads(AUTHORIZATION.read_text())
    require(auth.get("status") == "EXPLICITLY_AUTHORIZED_FOR_ONE_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY", "authorization_status")
    require(hashlib.sha256(str(auth.get("authorization_token", "")).encode()).hexdigest() == EXPECTED_AUTH_TOKEN_SHA, "authorization_token")
    require(auth.get("job_plan_sha256") == EXPECTED_PLAN_SHA, "authorization_plan_binding")
    require(auth.get("overlay_sha256") == EXPECTED_OVERLAY_SHA, "authorization_overlay_binding")
    require(auth.get("physical_gpu") == 1 and auth.get("max_cpu_per_process") == 8, "authorization_resources")
    require(auth.get("v4_f_test32_access_count") == 0, "authorization_sealed_access")
    source_files = verify_package(SOURCE_ROOT, auth.get("source_sha256s_sha256"))
    overlay_files = verify_package(PACKAGE_ROOT, auth.get("overlay_sha256s_sha256"))
    require(auth.get("source_sha256s_sha256") == EXPECTED_SOURCE_SHA256S_SHA, "source_sha256s_auth_binding")
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
        require("CUDA_VISIBLE_DEVICES=1" in command and @NODE1_PYTHON@ in command, "gpu_python_gate")
        joined = " ".join(command).lower().replace("-", "_")
        require("v4_f" not in joined and "test32" not in joined, "sealed_command_reference")
        log_dir = RUNTIME_ROOT / "logs" / (f"{index:02d}_" + job["job_id"])
        log_dir.mkdir(parents=True)
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        (log_dir / "STDOUT.log").write_text(completed.stdout)
        (log_dir / "STDERR.log").write_text(completed.stderr)
        atomic_json(log_dir / "TERMINAL.json", {
            "job_id": job["job_id"],
            "returncode": completed.returncode,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
        })
        require(completed.returncode == 0, "job_failed:" + job["job_id"])
        result = Path(job["expected_result"])
        require(result.is_file() and not result.is_symlink(), "result_missing:" + job["job_id"])
        receipt = json.loads(result.read_text())
        require(receipt.get("v4_f_test32_access_count") == 0, "result_sealed_firewall")
        require(receipt.get("prediction_metrics_access_count") == 0, "result_metrics_firewall")
        completed_ids.append(job["job_id"])
    write_final(
        "PASS_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY",
        completed_jobs=completed_ids,
        job_count=6,
        source_files_verified=source_files,
        overlay_files_verified=overlay_files,
    )
    return 0

def main():
    try:
        return run()
    except Exception as exc:
        write_final(
            "FAIL_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
    replacements = {
        "@OVERLAY_ROOT@": repr(OVERLAY_REMOTE_ROOT),
        "@SOURCE_ROOT@": repr(SOURCE_REMOTE_ROOT),
        "@RUNTIME_ROOT@": repr(RUNTIME_REMOTE_ROOT),
        "@AUTH_PATH@": repr(AUTH_REMOTE_PATH),
        "@PLAN_SHA@": repr(plan_sha),
        "@OVERLAY_SHA@": repr(overlay_sha),
        "@SOURCE_MANIFEST_SHA@": repr(source_manifest_sha),
        "@SOURCE_SHA256S_SHA@": repr(source_sha256s_sha),
        "@AUTH_TOKEN_SHA@": repr(auth_token_sha),
        "@NODE1_PYTHON@": repr(NODE1_PYTHON),
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    require("@" not in template, "launcher_template_placeholder")
    return template


def autostart_source(
    *,
    source_sha256s_sha: str,
    overlay_sha256s_sha: str,
    plan_sha: str,
    overlay_sha: str,
    launcher_sha: str,
) -> str:
    template = r'''#!/usr/bin/env python3
"""Checksum-closed V1.1 recovery autostart; waits for child terminal."""
import hashlib, json, os, subprocess, traceback
from pathlib import Path

PILOT_ROOT = Path(@PILOT_ROOT@)
SOURCE_ROOT = Path(@SOURCE_ROOT@)
OVERLAY_ROOT = Path(@OVERLAY_ROOT@)
RUNTIME_ROOT = Path(@RUNTIME_ROOT@)
AUTH_PATH = Path(@AUTH_PATH@)
WATCH_ROOT = Path(@WATCH_ROOT@)
LAUNCHER = OVERLAY_ROOT / "src" / "launch_gpu1_sequential_smoke_v1.py"
EXPECTED_SOURCE_SHA256S_SHA = @SOURCE_SHA256S_SHA@
EXPECTED_OVERLAY_SHA256S_SHA = @OVERLAY_SHA256S_SHA@
EXPECTED_PLAN_SHA = @PLAN_SHA@
EXPECTED_OVERLAY_SHA = @OVERLAY_SHA@
EXPECTED_LAUNCHER_SHA = @LAUNCHER_SHA@
AUTH_TOKEN = @AUTH_TOKEN@

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def atomic_json(path, payload):
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)

def read_sha256s(root):
    values = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        require(len(digest) == 64 and relative not in values, "sha256_line:" + relative)
        values[relative] = digest
    return values

def verify_package(root, expected_sha256s_sha):
    require(root.is_dir() and not root.is_symlink(), "package_root:" + str(root))
    sha_file = root / "SHA256SUMS"
    require(sha_file.is_file() and not sha_file.is_symlink(), "sha256s_missing:" + str(root))
    require(sha(sha_file) == expected_sha256s_sha, "sha256s_hash:" + str(root))
    listed = read_sha256s(root)
    actual = {
        str(path.relative_to(root)) for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    require(set(listed) == actual, "package_file_closure:" + str(root))
    for relative, expected in listed.items():
        path = root / relative
        require(not path.is_symlink() and sha(path) == expected, "package_file_hash:" + relative)
    return len(listed)

def write_watch(status, **extra):
    WATCH_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    payload.update(extra)
    atomic_json(WATCH_ROOT / "TERMINAL.json", payload)

def run():
    require(not WATCH_ROOT.exists(), "watch_root_exists")
    require(not AUTH_PATH.exists(), "authorization_already_exists")
    require(not RUNTIME_ROOT.exists(), "runtime_root_exists")
    WATCH_ROOT.mkdir(parents=True, exist_ok=False)
    atomic_json(WATCH_ROOT / "STATUS.json", {
        "status": "VERIFYING_PILOT_AND_V1_1_PACKAGE_FILE_CLOSURE",
        "physical_gpu": 1,
        "v4_f_test32_access_count": 0,
    })
    pilot_terminal = PILOT_ROOT / "TERMINAL.json"
    pilot_results = PILOT_ROOT / "RESULTS.tsv"
    require(pilot_terminal.is_file() and pilot_results.is_file(), "optimizer_pilot_terminal_missing")
    pilot = json.loads(pilot_terminal.read_text())
    require(pilot.get("status") == "PASS_INNER_ONLY_OPTIMIZER_PILOT_COMPLETE", "optimizer_pilot_not_pass")
    require(pilot.get("variants") == 6 and pilot.get("sealed_evaluation_access_count") == 0, "optimizer_pilot_contract")
    require(sha(pilot_results) == pilot.get("results_sha256"), "optimizer_results_hash")
    source_files = verify_package(SOURCE_ROOT, EXPECTED_SOURCE_SHA256S_SHA)
    overlay_files = verify_package(OVERLAY_ROOT, EXPECTED_OVERLAY_SHA256S_SHA)
    require(sha(OVERLAY_ROOT / "GPU1_SEQUENTIAL_JOB_PLAN.json") == EXPECTED_PLAN_SHA, "plan_hash")
    require(sha(OVERLAY_ROOT / "EXPLICIT_AUTHORIZATION_OVERLAY.json") == EXPECTED_OVERLAY_SHA, "overlay_hash")
    require(sha(LAUNCHER) == EXPECTED_LAUNCHER_SHA, "launcher_hash")
    authorization = {
        "status": "EXPLICITLY_AUTHORIZED_FOR_ONE_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY",
        "authorization_token": AUTH_TOKEN,
        "job_plan_sha256": EXPECTED_PLAN_SHA,
        "overlay_sha256": EXPECTED_OVERLAY_SHA,
        "source_sha256s_sha256": EXPECTED_SOURCE_SHA256S_SHA,
        "overlay_sha256s_sha256": EXPECTED_OVERLAY_SHA256S_SHA,
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "v4_f_test32_access_count": 0,
    }
    atomic_json(AUTH_PATH, authorization)
    stdout_path = WATCH_ROOT / "SMOKE_LAUNCHER_STDOUT.log"
    stderr_path = WATCH_ROOT / "SMOKE_LAUNCHER_STDERR.log"
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            [@NODE1_PYTHON@, str(LAUNCHER)],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        atomic_json(WATCH_ROOT / "LAUNCH_RECEIPT.json", {
            "status": "PASS_V1_1_RECOVERY_CHILD_LAUNCHED_WAITING_TERMINAL",
            "pid": process.pid,
            "source_files_verified": source_files,
            "overlay_files_verified": overlay_files,
            "source_sha256s_sha256": EXPECTED_SOURCE_SHA256S_SHA,
            "overlay_sha256s_sha256": EXPECTED_OVERLAY_SHA256S_SHA,
            "physical_gpu": 1,
            "max_cpu_per_process": 8,
            "v4_f_test32_access_count": 0,
        })
        returncode = process.wait()
    terminal_path = RUNTIME_ROOT / "TERMINAL.json"
    require(terminal_path.is_file() and not terminal_path.is_symlink(), "child_terminal_missing")
    child = json.loads(terminal_path.read_text())
    require(returncode == 0, "child_returncode:" + str(returncode))
    require(child.get("status") == "PASS_GPU1_SEQUENTIAL_REAL_SMOKE_V1_1_RECOVERY", "child_terminal_status")
    require(child.get("v4_f_test32_access_count") == 0, "child_sealed_access")
    write_watch(
        "PASS_GPU1_RECOVERY_AUTOSTART_V1_1_CHILD_TERMINAL_VERIFIED",
        child_pid=process.pid,
        child_returncode=returncode,
        child_terminal_sha256=sha(terminal_path),
        source_files_verified=source_files,
        overlay_files_verified=overlay_files,
    )
    return 0

def main():
    try:
        return run()
    except Exception as exc:
        write_watch(
            "FAIL_GPU1_RECOVERY_AUTOSTART_V1_1",
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
    replacements = {
        "@PILOT_ROOT@": repr(PILOT_REMOTE_ROOT),
        "@SOURCE_ROOT@": repr(SOURCE_REMOTE_ROOT),
        "@OVERLAY_ROOT@": repr(OVERLAY_REMOTE_ROOT),
        "@RUNTIME_ROOT@": repr(RUNTIME_REMOTE_ROOT),
        "@AUTH_PATH@": repr(AUTH_REMOTE_PATH),
        "@WATCH_ROOT@": repr(WATCH_REMOTE_ROOT),
        "@SOURCE_SHA256S_SHA@": repr(source_sha256s_sha),
        "@OVERLAY_SHA256S_SHA@": repr(overlay_sha256s_sha),
        "@PLAN_SHA@": repr(plan_sha),
        "@OVERLAY_SHA@": repr(overlay_sha),
        "@LAUNCHER_SHA@": repr(launcher_sha),
        "@AUTH_TOKEN@": repr(AUTH_TOKEN),
        "@NODE1_PYTHON@": repr(NODE1_PYTHON),
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    require("@" not in template, "autostart_template_placeholder")
    return template


def build_recovery(source_evidence_root: Path, output_parent: Path) -> dict[str, Any]:
    source_out = output_parent / "node1_smoke_source_package_v1_1"
    overlay_out = output_parent / "gpu1_sequential_overlay_v1_1"
    autostart_out = output_parent / "gpu1_recovery_autostart_package_v1_1"
    for path in (source_out, overlay_out, autostart_out):
        require(not path.exists(), f"output_exists:{path}")

    source_builder = load_module(HERE.with_name("build_node1_smoke_package_v1.py"), "v25_source_builder_v1_1")
    source_builder.SCHEMA_VERSION = "pvrig_v2_5_ortho_node1_smoke_package_v1_1"
    source_builder.REMOTE_PACKAGE_ROOT = SOURCE_REMOTE_ROOT
    source_builder.REMOTE_RUNTIME_ROOT = RUNTIME_REMOTE_ROOT
    source_builder.build_package(source_out, source_evidence_root)
    rewrite_json(
        source_out / "NONLAUNCHING_JOB_PLAN.json",
        {
            "schema_version": "pvrig_v2_5_ortho_node1_smoke_nonlaunching_plan_v1_1",
            "recovery_change_scope": "dynamic_import_sibling_path_only_plus_launch_audit_hardening",
        },
    )
    manifest = json.loads((source_out / "PACKAGE_MANIFEST.json").read_text())
    manifest.update(
        {
            "schema_version": "pvrig_v2_5_ortho_node1_smoke_package_v1_1",
            "recovery_change_scope": "dynamic_import_sibling_path_only_plus_launch_audit_hardening",
            "supersedes_failed_remote_v1": True,
        }
    )
    manifest["job_plan"]["sha256"] = sha256_file(source_out / "NONLAUNCHING_JOB_PLAN.json")
    atomic_json(source_out / "PACKAGE_MANIFEST.json", manifest)
    regenerate_sha256s(source_out)
    source_members = {
        "INPUT_CONTRACT.json",
        "NONLAUNCHING_JOB_PLAN.json",
        "PACKAGE_MANIFEST.json",
        "src/residue_model_v2_5_ortho.py",
        "src/run_real1507_split_v1.py",
        "src/train_v2_5_ortho_heads.py",
    }
    source_hashes = audit_file_closure(source_out, source_members)
    source_manifest = json.loads((source_out / "PACKAGE_MANIFEST.json").read_text())
    require(source_manifest["node1_package_root"] == SOURCE_REMOTE_ROOT, "source_remote_root")
    require(source_manifest["node1_runtime_root"] == RUNTIME_REMOTE_ROOT, "source_runtime_root")
    require(
        source_manifest["source_code_sha256"]["residue_model_v2_5_ortho.py"]
        == "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521",
        "model_hash_changed",
    )
    require(
        source_manifest["source_code_sha256"]["train_v2_5_ortho_heads.py"]
        == "a3d480fe4e164e74e2f64598e8ca53d42131c2e9e6ad16074fb7274e33a906b8",
        "trainer_hash_changed",
    )

    overlay_builder = load_module(
        HERE.with_name("build_gpu1_sequential_authorization_overlay_v1.py"),
        "v25_overlay_builder_v1_1",
    )
    overlay_builder.SCHEMA_VERSION = "pvrig_v2_5_gpu1_sequential_explicit_authorization_overlay_v1_1"
    overlay_builder.SOURCE_REMOTE_ROOT = SOURCE_REMOTE_ROOT
    overlay_builder.OVERLAY_REMOTE_ROOT = OVERLAY_REMOTE_ROOT
    overlay_builder.RUNTIME_REMOTE_ROOT = RUNTIME_REMOTE_ROOT
    overlay_builder.AUTHORIZATION_REMOTE_PATH = AUTH_REMOTE_PATH
    overlay_builder.AUTH_TOKEN = AUTH_TOKEN
    overlay_builder.AUTH_TOKEN_SHA256 = hashlib.sha256(AUTH_TOKEN.encode()).hexdigest()
    overlay_builder.SOURCE_EXPECTED = {
        **source_hashes,
        "SHA256SUMS": sha256_file(source_out / "SHA256SUMS"),
    }
    overlay_builder.launcher_source = launcher_source
    overlay_builder.build_package(source_out, overlay_out)
    overlay_builder.audit_package(source_out, overlay_out)
    overlay_members = {
        "SOURCE_PACKAGE_BINDING.json",
        "EXPLICIT_AUTHORIZATION_OVERLAY.json",
        "GPU1_SEQUENTIAL_JOB_PLAN.json",
        "PACKAGE_MANIFEST.json",
        "src/launch_gpu1_sequential_smoke_v1.py",
    }
    overlay_hashes = audit_file_closure(overlay_out, overlay_members)

    autostart_out.mkdir(parents=True)
    (autostart_out / "src").mkdir()
    autostart = autostart_out / "src" / "launch_gpu1_smoke_recovery_after_pilot_v1_1.py"
    autostart.write_text(
        autostart_source(
            source_sha256s_sha=sha256_file(source_out / "SHA256SUMS"),
            overlay_sha256s_sha=sha256_file(overlay_out / "SHA256SUMS"),
            plan_sha=sha256_file(overlay_out / "GPU1_SEQUENTIAL_JOB_PLAN.json"),
            overlay_sha=sha256_file(overlay_out / "EXPLICIT_AUTHORIZATION_OVERLAY.json"),
            launcher_sha=sha256_file(overlay_out / "src" / "launch_gpu1_sequential_smoke_v1.py"),
        )
    )
    autostart.chmod(0o755)
    autostart_manifest = {
        "schema_version": "pvrig_v2_5_gpu1_recovery_autostart_package_v1_1",
        "status": "PASS_BUILD_AUDIT_NOT_DEPLOYED_NOT_LAUNCHED",
        "node1_autostart_root": AUTOSTART_REMOTE_ROOT,
        "node1_watch_root": WATCH_REMOTE_ROOT,
        "node1_source_root": SOURCE_REMOTE_ROOT,
        "node1_overlay_root": OVERLAY_REMOTE_ROOT,
        "node1_runtime_root": RUNTIME_REMOTE_ROOT,
        "node1_authorization_path": AUTH_REMOTE_PATH,
        "autostart_sha256": sha256_file(autostart),
        "source_sha256s_sha256": sha256_file(source_out / "SHA256SUMS"),
        "overlay_sha256s_sha256": sha256_file(overlay_out / "SHA256SUMS"),
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(autostart_out / "PACKAGE_MANIFEST.json", autostart_manifest)
    regenerate_sha256s(autostart_out)
    autostart_hashes = audit_file_closure(
        autostart_out,
        {"PACKAGE_MANIFEST.json", "src/launch_gpu1_smoke_recovery_after_pilot_v1_1.py"},
    )
    return {
        "schema_version": "pvrig_v2_5_gpu1_smoke_recovery_build_v1_1",
        "status": "PASS_V1_1_RECOVERY_PACKAGES_BUILT_AUDITED_NOT_DEPLOYED_NOT_LAUNCHED",
        "source_root": str(source_out),
        "overlay_root": str(overlay_out),
        "autostart_root": str(autostart_out),
        "source_files": len(source_hashes),
        "overlay_files": len(overlay_hashes),
        "autostart_files": len(autostart_hashes),
        "source_sha256s_sha256": sha256_file(source_out / "SHA256SUMS"),
        "overlay_sha256s_sha256": sha256_file(overlay_out / "SHA256SUMS"),
        "autostart_sha256s_sha256": sha256_file(autostart_out / "SHA256SUMS"),
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "prediction_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--source-evidence-root", type=Path, required=True)
    value.add_argument("--output-parent", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = build_recovery(args.source_evidence_root, args.output_parent)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
