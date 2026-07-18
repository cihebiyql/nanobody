#!/usr/bin/env python3
"""Materialize a separately authorized V2.2.2 strict nested-stack graph."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any


HERE = Path(__file__).resolve()
BUILD_PATH = HERE.with_name("build_v2_2_2_strict_nested_package_v1.py")
AUDIT_DRY_PATH = HERE.with_name("audit_v2_2_2_strict_nested_package_v1.py")
AUTH_TOKEN = "I_ACCEPT_OPEN_DEVELOPMENT_TRAINING"
AUTH_TOKEN_SHA = hashlib.sha256(AUTH_TOKEN.encode()).hexdigest()
AUTHORIZED_STATUS = "READY_EXECUTABLE_POSTCALIBRATION_FREEZE"
PACKAGE_STATUS = "PASS_EXPLICIT_AUTHORIZATION_LAYER_AUDITED_READY_TO_LAUNCH"
NODE1_PACKAGE_ROOT = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_20260718"
NODE1_RUNTIME_ROOT = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_20260718"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_spec_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_module("v222_dry_builder", BUILD_PATH)
dry_auditor = load_module("v222_dry_auditor", AUDIT_DRY_PATH)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def validate_authorized_graph(graph: dict[str, Any], authorized_view_sha: str) -> dict[str, Any]:
    base.require(graph.get("status") == AUTHORIZED_STATUS, "authorized_graph_status")
    base.require(graph.get("execution_authorized") is True, "authorized_graph_flag")
    base.require(graph.get("sealed_evaluation_access_count") == 0, "sealed_access")
    base.require(graph.get("prediction_metrics_access_count") == 0, "prediction_metric_access")
    base.require(graph.get("claim_boundary") == base.GRAPH_CLAIM_BOUNDARY, "graph_claim")
    base.require(graph["canonical_inputs"]["deployment_manifest"]["sha256"] == authorized_view_sha, "authorized_view_hash_binding")
    jobs = graph["jobs"]
    counts = Counter(job["kind"] for job in jobs)
    base.require(len(jobs) == 195 and dict(counts) == base.EXPECTED_JOB_COUNTS, "authorized_job_counts")
    gpu = [job for job in jobs if job["kind"].startswith("GPU_")]
    base.require(len(gpu) == 90, "authorized_gpu_count")
    base.require({job["physical_gpu"] for job in gpu} == {2, 4, 5}, "authorized_gpu_allowlist")
    ready = base.load_json(base.READY)
    marginal = ready["artifacts"]["adaptive_marginal_tsv_gz"]["node1_path"]
    pair = ready["artifacts"]["adaptive_pair_tsv_gz"]["node1_path"]
    for job in gpu:
        command = job.get("command")
        base.require(isinstance(command, list) and command, f"authorized_command_missing:{job['job_id']}")
        lane = job["lane"]
        expected = base.EXPECTED_LANE_WEIGHTS[lane]
        base.require(base.argv_weights(command) == expected, f"authorized_lane_weight:{job['job_id']}")
        base.require(job["physical_gpu"] == base.EXPECTED_GPU_MAP[lane], f"authorized_lane_gpu:{job['job_id']}")
        base.require(marginal in command and pair in command, f"adaptive_inputs_missing:{job['job_id']}")
        base.require(command[command.index("--backbone-kind") + 1] == "hf", f"hf_backbone_missing:{job['job_id']}")
        base.require(command[command.index("--fixed-epochs") + 1] == "8", f"epochs_drift:{job['job_id']}")
        base.require(command[command.index("--device") + 1] == "cuda", f"device_drift:{job['job_id']}")
        base.require(command[command.index("--precision") + 1] == "bf16", f"precision_drift:{job['job_id']}")
    return {"job_count": 195, "gpu_job_count": 90, "cpu_job_count": 105, "physical_gpus": [2, 4, 5], "job_counts": dict(sorted(counts.items()))}


def launcher_source(graph_sha: str, runner_sha: str, overlay_sha: str) -> str:
    return f'''#!/usr/bin/env python3
import hashlib, json, subprocess
from pathlib import Path

PACKAGE_ROOT = Path({NODE1_PACKAGE_ROOT!r})
RUNTIME_ROOT = Path({NODE1_RUNTIME_ROOT!r})
GRAPH = PACKAGE_ROOT / "plan" / "job_graph.json"
RUNNER = PACKAGE_ROOT / "src" / "run_strict_nested_crossfit_graph_v1.py"
OVERLAY = PACKAGE_ROOT / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
EXPECTED_GRAPH_SHA = {graph_sha!r}
EXPECTED_RUNNER_SHA = {runner_sha!r}
EXPECTED_OVERLAY_SHA = {overlay_sha!r}
TOKEN = {AUTH_TOKEN!r}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if sha(GRAPH) != EXPECTED_GRAPH_SHA or sha(RUNNER) != EXPECTED_RUNNER_SHA or sha(OVERLAY) != EXPECTED_OVERLAY_SHA:
        raise RuntimeError("authorized_launch_hash_gate")
    graph = json.loads(GRAPH.read_text())
    if graph.get("status") != "READY_EXECUTABLE_POSTCALIBRATION_FREEZE" or graph.get("execution_authorized") is not True:
        raise RuntimeError("authorized_launch_graph_gate")
    jobs = graph.get("jobs", [])
    gpu = [j for j in jobs if j.get("kind", "").startswith("GPU_")]
    if len(jobs) != 195 or len(gpu) != 90 or {{j["physical_gpu"] for j in gpu}} != {{2, 4, 5}}:
        raise RuntimeError("authorized_launch_job_gate")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=False)
    receipt = {{
        "status": "AUTHORIZED_LAUNCH_STARTED",
        "job_graph_sha256": EXPECTED_GRAPH_SHA,
        "job_count": 195,
        "gpu_job_count": 90,
        "physical_gpus": [2, 4, 5],
        "sealed_evaluation_access_count": 0,
    }}
    (RUNTIME_ROOT / "AUTHORIZED_LAUNCH_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\\n")
    command = [
        "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python", str(RUNNER),
        "--job-graph", str(GRAPH), "--execute",
        "--authorization-token", TOKEN,
        "--log-root", str(RUNTIME_ROOT / "logs"),
        "--max-cpu-jobs", "8",
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    (RUNTIME_ROOT / "RUNNER_STDOUT.log").write_text(completed.stdout)
    (RUNTIME_ROOT / "RUNNER_STDERR.log").write_text(completed.stderr)
    terminal = {{"returncode": completed.returncode, "status": "PASS" if completed.returncode == 0 else "FAIL"}}
    (RUNTIME_ROOT / "TERMINAL.json").write_text(json.dumps(terminal, indent=2, sort_keys=True) + "\\n")
    return completed.returncode

if __name__ == "__main__":
    raise SystemExit(main())
'''


def build(dry_root: Path, output_dir: Path) -> dict[str, Any]:
    dry_root = dry_root.resolve()
    output_dir = output_dir.resolve()
    base.require(not output_dir.exists(), f"output_exists:{output_dir}")
    dry_result = dry_auditor.audit(dry_root)
    base.require(dry_result["status"] == "PASS_IMMUTABLE_NON_LAUNCHING_PACKAGE", "dry_package_audit")
    base.validate_inputs()
    try:
        output_dir.mkdir(parents=True)
        shutil.copytree(dry_root / "node1_bundle" / "src", output_dir / "node1_bundle" / "src")
        shutil.copytree(dry_root / "node1_bundle" / "inputs", output_dir / "node1_bundle" / "inputs")
        shutil.copytree(dry_root / "contracts", output_dir / "contracts")

        ready = base.load_json(base.READY)
        base.require(ready["production_authorized"] is False, "base_ready_not_false")
        authorized_view = dict(ready)
        authorized_view["production_authorized"] = True
        authorized_view_path = output_dir / "contracts" / "AUTHORIZED_DEPLOYMENT_VIEW.json"
        write_json(authorized_view_path, authorized_view)
        authorized_view_sha = base.sha256_file(authorized_view_path)

        overlay = {
            "schema_version": "pvrig_v2_4_v2_2_2_strict_nested_explicit_authorization_v1",
            "status": "EXPLICITLY_AUTHORIZED_FOR_STRICT_NESTED_OPEN_DEVELOPMENT_EXECUTION",
            "authorization_scope": "one 195-job strict double whole-parent cross-fit graph",
            "base_ready_manifest_path": str(base.READY),
            "base_ready_manifest_sha256": base.EXPECTED_HASHES[base.READY],
            "base_ready_manifest_production_authorized": False,
            "authorized_deployment_view_sha256": authorized_view_sha,
            "authorized_field_transition": {"production_authorized": {"from": False, "to": True}},
            "authorization_token_sha256": AUTH_TOKEN_SHA,
            "immutable_model_training_split_lane_weight_claim_contracts": True,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "physical_gpu_allowlist": [2, 4, 5],
            "claim_boundary": base.CLAIM_BOUNDARY,
        }
        overlay_path = output_dir / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
        write_json(overlay_path, overlay)

        planner = base.import_planner()
        plan_dir = output_dir / "node1_bundle" / "plan"
        node_inputs = Path(NODE1_PACKAGE_ROOT) / "inputs"
        planner.plan(SimpleNamespace(
            training_tsv=base.TRAINING, outer_manifest=base.OUTER, inner_manifest=base.INNER,
            deployment_manifest=authorized_view_path, contact_formula=base.FORMULA,
            output_dir=plan_dir, runtime_root=NODE1_RUNTIME_ROOT,
            node1_plan_root=str(Path(NODE1_PACKAGE_ROOT) / "plan"),
            planner_node1_path=str(Path(NODE1_PACKAGE_ROOT) / "src" / base.PLANNER.name),
            feature_validator_node1_path=str(Path(NODE1_PACKAGE_ROOT) / "src" / base.VALIDATOR.name),
            stack_fitter_node1_path=str(Path(NODE1_PACKAGE_ROOT) / "src" / base.STACK_FITTER.name),
            inner_manifest_node1_path=str(node_inputs / base.INNER.name),
            outer_manifest_node1_path=str(node_inputs / base.OUTER.name),
            contact_formula_node1_path=str(node_inputs / base.FORMULA.name),
        ))
        graph_path = plan_dir / "job_graph.json"
        graph_sha = base.sha256_file(graph_path)
        graph_summary = validate_authorized_graph(base.load_json(graph_path), authorized_view_sha)
        runner_path = output_dir / "node1_bundle" / "src" / base.RUNNER.name
        launcher_path = output_dir / "node1_bundle" / "src" / "launch_authorized_strict_nested_v1.py"
        launcher_path.write_text(launcher_source(graph_sha, base.sha256_file(runner_path), base.sha256_file(overlay_path)), encoding="utf-8")
        launcher_path.chmod(0o755)

        manifest = {
            "schema_version": "pvrig_v2_4_v2_2_2_strict_nested_authorized_package_v1",
            "status": PACKAGE_STATUS,
            "claim_boundary": base.CLAIM_BOUNDARY,
            "graph_claim_boundary": base.GRAPH_CLAIM_BOUNDARY,
            "launch_authorized": True,
            "training_or_prediction_executed": False,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "source_dry_package": {"path": str(dry_root), "audit": dry_result},
            "base_ready_manifest_sha256": base.EXPECTED_HASHES[base.READY],
            "implementation_freeze_sha256": base.EXPECTED_HASHES[base.FREEZE],
            "authorized_deployment_view_sha256": authorized_view_sha,
            "authorization_overlay_sha256": base.sha256_file(overlay_path),
            "authorization_token_sha256": AUTH_TOKEN_SHA,
            "job_graph": {"relative_path": "node1_bundle/plan/job_graph.json", "sha256": graph_sha, **graph_summary},
            "launcher": {"relative_path": "node1_bundle/src/launch_authorized_strict_nested_v1.py", "sha256": base.sha256_file(launcher_path)},
            "node1_package_root": NODE1_PACKAGE_ROOT,
            "node1_runtime_root": NODE1_RUNTIME_ROOT,
            "lane_contract": {
                lane: {"marginal_weight": weights[0], "pair_weight": weights[1], "physical_gpu": base.EXPECTED_GPU_MAP[lane]}
                for lane, weights in base.EXPECTED_LANE_WEIGHTS.items()
            },
            "primary_stack": {
                "input_columns": ["M2_R8", "neural_R8", "contact_score_R8", "M2_R9", "neural_R9", "contact_score_R9"],
                "parameter_names": ["intercept_R8", "intercept_R9", "beta_M2", "beta_neural", "beta_contact"],
                "parameter_count": 5,
            },
        }
        write_json(output_dir / "PACKAGE_MANIFEST.json", manifest)
        files = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
        with (output_dir / "SHA256SUMS").open("w", encoding="utf-8") as handle:
            for path in files:
                handle.write(f"{base.sha256_file(path)}  {path.relative_to(output_dir)}\n")
        return manifest
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.dry_package_root, args.output_dir)
    print(json.dumps({"status": result["status"], "job_graph_sha256": result["job_graph"]["sha256"], "job_count": result["job_graph"]["job_count"], "node1_package_root": result["node1_package_root"], "node1_runtime_root": result["node1_runtime_root"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
