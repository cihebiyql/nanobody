#!/usr/bin/env python3
"""Wait for closed D/C2 evidence, authorize, run child evaluator, and terminalize."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping


class AuthorizationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorizationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"json_required:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"json_object_required:{path}")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def scan_zero_access(value: Any, context: str) -> None:
    protected = {"v4_f_test32_access_count", "sealed_evaluation_access_count", "prediction_metrics_access_count"}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in protected:
                require(int(item) == 0, f"protected_access_nonzero:{context}:{key}:{item}")
            scan_zero_access(item, context)
    elif isinstance(value, list):
        for item in value: scan_zero_access(item, context)


def verify_autostart_freeze(package_root: Path, freeze_path: Path) -> dict[str, str]:
    freeze = read_json(freeze_path)
    require(freeze["status"] == "FROZEN_EXPLICIT_AUTHORIZATION_AUTOSTART_V1", "autostart_freeze_status")
    observed = {}
    for relative, expected in freeze["artifact_hashes"].items():
        path = package_root / relative
        value = sha256_file(path)
        require(value == expected, f"autostart_freeze_hash:{relative}:{value}:{expected}")
        observed[relative] = value
    return observed


def verify_bound_execution(
    intent: Mapping[str, Any], manifest_path: Path, adapter_freeze_path: Path,
    contract_path: Path, evaluator_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bindings = {
        "bound_execution_manifest_sha256": manifest_path,
        "bound_execution_adapter_freeze_sha256": adapter_freeze_path,
        "bound_execution_contract_sha256": contract_path,
        "bound_formal_evaluator_sha256": evaluator_path,
    }
    for field, path in bindings.items():
        require(sha256_file(path) == intent[field], f"intent_binding:{field}")
    manifest = read_json(manifest_path)
    contract = read_json(contract_path)
    require(manifest["status"] == "FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY", "manifest_status")
    require(manifest["execution_authorized"] is False, "manifest_mutated_authorized")
    require(manifest["formal_evaluator_launch_allowed"] is False, "manifest_mutated_launch")
    require(manifest["contract"]["sha256"] == intent["bound_execution_contract_sha256"], "manifest_contract_binding")
    for name, specification in manifest["code"].items():
        path = Path(specification["node1_path"])
        require(sha256_file(path) == specification["sha256"], f"manifest_code_binding:{name}")
    require(contract["status"] == "FROZEN_DESIGN_UNAUTHORIZED_DO_NOT_EVALUATE", "contract_status")
    require(contract["authorization"]["required_token_sha256"] == intent["authorization_token_sha256"], "contract_token_binding")
    return manifest, contract


def validate_input_closure(
    closure_path: Path, intent: Mapping[str, Any], contract: Mapping[str, Any],
    runtime_root: Path, input_root: Path,
) -> tuple[dict[str, Any], str]:
    before = sha256_file(closure_path)
    closure = read_json(closure_path)
    after = sha256_file(closure_path)
    require(before == after, "input_closure_changed_during_read")
    scan_zero_access(closure, "input_closure")
    require(closure["status"] == intent["required_input_closure_status"], "input_closure_status")
    require(closure["execution_authorized"] is False, "closure_mutated_authorized")
    require(closure["formal_evaluator_launched"] is False, "closure_evaluator_already_launched")
    require(closure["performance_evaluation_performed"] is False, "closure_performance_already_evaluated")
    require(closure["contract_sha256"] == intent["bound_execution_contract_sha256"], "closure_contract_hash")
    require(int(closure["expected_job_count"]) == int(intent["required_job_result_closure"]), "closure_expected_jobs")
    require(int(closure["closed_job_result_count"]) == int(intent["required_job_result_closure"]), "closure_closed_jobs")
    require(closure["all_lane_graph_result_hash_closure"] is True, "graph_result_hash_closure")
    require(closure["allowed_lane_read"] == intent["required_allowed_predictor_lane"], "closure_allowed_lane")
    require(int(closure["forbidden_lane_predictor_read_count"]) == int(intent["required_forbidden_lane_predictor_read_count"]), "closure_forbidden_lane")
    for name, specification in contract["canonical_inputs"].items():
        expected = specification["sha256"]
        require(closure["input_hashes"][name] == expected, f"closure_input_hash:{name}")
        require(sha256_file(input_root / specification["filename"]) == expected, f"live_input_hash:{name}")
    upstream = contract["upstream_v2_4_strict"]
    expected_upstream = {
        "job_graph": upstream["job_graph_sha256"],
        "package_manifest": upstream["package_manifest_sha256"],
        "upstream_authorization_overlay": upstream["authorization_overlay_sha256"],
        "launch_receipt": upstream["launch_receipt_sha256"],
    }
    require(closure["upstream_binding_hashes"] == expected_upstream, "closure_upstream_binding")
    c2 = closure["c2_outer_oof_closure"]
    require(int(c2["candidate_count"]) == int(intent["required_candidates"]), "c2_candidate_count")
    require(c2["candidate_scored_exactly_once"] is True, "c2_scored_once")
    require(int(c2["exact_min_violations"]) == 0, "c2_exact_min")
    require(int(c2["v4_f_test32_access_count"]) == 0, "c2_v4f_access")
    require(set(c2["outer_fold_counts"]) == {str(i) for i in range(int(intent["required_outer_folds"]))}, "c2_fold_closure")

    folds = closure["fold_evidence"]
    require(set(folds) == {str(i) for i in range(int(intent["required_outer_folds"]))}, "D_fold_closure")
    checked = {}
    for fold in range(int(intent["required_outer_folds"])):
        root = runtime_root / "evidence" / "D_SPLIT_PAIR" / f"outer_{fold}"
        for role, names in {
            "inner": ("inner_oof_base.tsv", "inner_oof_base.validation.json", "inner_oof_provenance.json"),
            "outer": ("outer_test_base.tsv", "outer_test_base.validation.json", "outer_test_provenance.json"),
        }.items():
            evidence = folds[str(fold)][role]
            require(int(evidence["exact_min_violations"]) == 0, f"D_exact_min:{fold}:{role}")
            observed = {
                "evidence_sha256": sha256_file(root / names[0]),
                "validation_sha256": sha256_file(root / names[1]),
                "provenance_sha256": sha256_file(root / names[2]),
            }
            for field, value in observed.items():
                require(evidence[field] == value, f"D_hash:{fold}:{role}:{field}")
            checked[f"outer_{fold}/{role}"] = observed
    return closure, before


def materialize_overlay(
    path: Path, intent_path: Path, intent: Mapping[str, Any],
    manifest_path: Path, closure_path: Path,
) -> dict[str, Any]:
    value = {
        "schema_version": "pvrig_v2_5_strict_meta_authorization_overlay_v1",
        "status": "EXPLICITLY_AUTHORIZED",
        "execution_authorized": True,
        "execution_manifest_sha256": sha256_file(manifest_path),
        "input_closure_receipt_sha256": sha256_file(closure_path),
        "authorization_token_sha256": intent["authorization_token_sha256"],
        "authorization_intent_sha256": sha256_file(intent_path),
        "v4_f_test32_access_count": 0,
        "claim_boundary": intent["claim_boundary"],
    }
    if path.exists():
        require(read_json(path) == value, "existing_overlay_mismatch")
    else:
        atomic_json(path, value)
    require(sha256_file(path) == hashlib.sha256((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()).hexdigest(), "overlay_materialization_hash")
    return value


def validate_formal_terminal(formal_output: Path, overlay_path: Path) -> dict[str, Any]:
    receipt_path = formal_output / "FORMAL_EXECUTION_RECEIPT.json"
    receipt = read_json(receipt_path)
    scan_zero_access(receipt, "formal_receipt")
    require(receipt["status"] == "PASS_FORMAL_EVALUATION_COMPLETED", "formal_receipt_status")
    require(receipt["execution_authorized"] is True, "formal_receipt_authorization")
    require(receipt["authorization_overlay_sha256"] == sha256_file(overlay_path), "formal_overlay_binding")
    for name, expected in receipt["artifacts"].items():
        require(sha256_file(formal_output / name) == expected, f"formal_artifact_hash:{name}")
    return receipt


def run(args: argparse.Namespace) -> int:
    package_root = Path(args.package_root).resolve()
    output_root = Path(args.output_root).resolve()
    terminal_path = output_root / "TERMINAL.json"
    if terminal_path.exists():
        terminal = read_json(terminal_path)
        return 0 if terminal.get("status") == "PASS" else 1
    intent_path = Path(args.intent).resolve()
    freeze_path = Path(args.freeze).resolve()
    manifest_path = Path(args.manifest).resolve()
    adapter_freeze_path = Path(args.adapter_freeze).resolve()
    contract_path = Path(args.contract).resolve()
    evaluator_path = Path(args.evaluator).resolve()
    closure_path = Path(args.input_closure).resolve()
    runtime_root = Path(args.runtime_root).resolve()
    input_root = Path(args.input_root).resolve()
    runner_path = Path(args.runner).resolve()
    python = Path(args.python).resolve()

    require(sha256_file(freeze_path) == args.expected_freeze_sha256, "autostart_freeze_root_hash")
    verify_autostart_freeze(package_root, freeze_path)
    intent = read_json(intent_path)
    require(intent["status"] == "EXPLICITLY_AUTHORIZED_PENDING_PASS_INPUT_CLOSURE", "intent_status")
    require(intent["execution_authorized"] is True, "intent_authorization")
    token = os.environ.get("PVRIG_V2_5_AUTH_TOKEN", "")
    require(sha256_text(token) == intent["authorization_token_sha256"], "runtime_authorization_token")
    manifest, contract = verify_bound_execution(intent, manifest_path, adapter_freeze_path, contract_path, evaluator_path)
    require(python.is_file(), "python_missing")

    polls = 0
    while True:
        if closure_path.exists():
            closure = read_json(closure_path)
            if closure.get("status") == intent["required_input_closure_status"]:
                break
            require(closure.get("status") == "WAITING_STRICT_V1_2_1_TERMINAL", f"input_closure_terminal_failure:{closure.get('status')}")
        atomic_json(output_root / "WATCHER_STATUS.json", {
            "schema_version": "pvrig_v2_5_formal_autostart_watcher_status_v1",
            "status": "WAITING_PASS_INPUTS_READY_UNAUTHORIZED",
            "poll_count": polls + 1,
            "execution_authorized_by_intent": True,
            "formal_evaluator_launched": False,
            "terminal_written": False,
            "v4_f_test32_access_count": 0,
        })
        polls += 1
        if args.max_polls and polls >= args.max_polls:
            return 3
        time.sleep(args.poll_seconds)

    closure, closure_hash = validate_input_closure(closure_path, intent, contract, runtime_root, input_root)
    authorization_dir = output_root / "authorization"
    overlay_path = authorization_dir / "EXPLICIT_AUTHORIZATION_OVERLAY_V1.json"
    overlay = materialize_overlay(overlay_path, intent_path, intent, manifest_path, closure_path)
    formal_output = output_root / "formal_output"
    require(not formal_output.exists(), "formal_output_preexists")
    child_log = output_root / "FORMAL_EVALUATOR_CHILD.log"
    command = [
        str(python), str(runner_path),
        "--evaluator", str(evaluator_path),
        "--expected-evaluator-sha256", intent["bound_formal_evaluator_sha256"],
        "--execution-manifest", str(manifest_path),
        "--input-closure-receipt", str(closure_path),
        "--authorization-overlay", str(overlay_path),
        "--contract", str(contract_path),
        "--input-root", str(input_root),
        "--runtime-root", str(runtime_root),
        "--output-dir", str(formal_output),
    ]
    child_env = dict(os.environ)
    child_env["PVRIG_V2_5_AUTH_TOKEN"] = token
    os.environ.pop("PVRIG_V2_5_AUTH_TOKEN", None)
    with child_log.open("wb") as log:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=child_env)
        atomic_json(output_root / "WATCHER_STATUS.json", {
            "schema_version": "pvrig_v2_5_formal_autostart_watcher_status_v1",
            "status": "FORMAL_EVALUATOR_CHILD_RUNNING",
            "child_pid": child.pid,
            "formal_evaluator_launched": True,
            "formal_evaluator_terminal": False,
            "input_closure_receipt_sha256": closure_hash,
            "authorization_overlay_sha256": sha256_file(overlay_path),
            "v4_f_test32_access_count": 0,
        })
        returncode = child.wait()
    require(returncode == 0, f"formal_evaluator_child_returncode:{returncode}")
    formal_receipt = validate_formal_terminal(formal_output, overlay_path)
    atomic_json(terminal_path, {
        "schema_version": "pvrig_v2_5_formal_autostart_terminal_v1",
        "status": "PASS",
        "returncode": 0,
        "formal_evaluator_child_returncode": returncode,
        "formal_evaluator_terminal": True,
        "input_closure_receipt_sha256": closure_hash,
        "authorization_overlay_sha256": sha256_file(overlay_path),
        "formal_execution_receipt_sha256": sha256_file(formal_output / "FORMAL_EXECUTION_RECEIPT.json"),
        "formal_artifacts": formal_receipt["artifacts"],
        "v4_f_test32_access_count": 0,
        "claim_boundary": intent["claim_boundary"],
    })
    atomic_json(output_root / "WATCHER_STATUS.json", {
        "schema_version": "pvrig_v2_5_formal_autostart_watcher_status_v1",
        "status": "PASS_FORMAL_EVALUATOR_CHILD_TERMINAL",
        "formal_evaluator_launched": True,
        "formal_evaluator_terminal": True,
        "terminal_sha256": sha256_file(terminal_path),
        "v4_f_test32_access_count": 0,
    })
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--adapter-freeze", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--input-closure", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--runner", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--max-polls", type=int, default=0)
    args = parser.parse_args()
    output_root = Path(args.output_root).resolve()
    try:
        return run(args)
    except Exception as exc:
        atomic_json(output_root / "TERMINAL.json", {
            "schema_version": "pvrig_v2_5_formal_autostart_terminal_v1",
            "status": "FAIL",
            "returncode": 1,
            "formal_evaluator_terminal": True,
            "error": f"{type(exc).__name__}:{exc}",
            "v4_f_test32_access_count": 0,
        })
        atomic_json(output_root / "WATCHER_STATUS.json", {
            "schema_version": "pvrig_v2_5_formal_autostart_watcher_status_v1",
            "status": "FAIL_TERMINAL",
            "terminal_sha256": sha256_file(output_root / "TERMINAL.json"),
            "v4_f_test32_access_count": 0,
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
