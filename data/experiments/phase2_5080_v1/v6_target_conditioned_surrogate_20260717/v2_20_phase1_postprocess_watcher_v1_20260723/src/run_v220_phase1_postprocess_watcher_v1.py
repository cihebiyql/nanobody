#!/usr/bin/env python3
"""Fail-closed V2.20 Phase-1 training watcher and frozen postprocessor.

This program waits for the five paired C0/C1 fold terminals, then invokes only
the already-frozen V2.20 pairing, OOF collection, evaluation, and core-gate
CLIs.  A core PASS authorizes Phase-1b ablations only.  It never reads open or
frozen-test data and never changes or injects a Top7500 ranking.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = "pvrig.v220.phase1_postprocess_watcher.v1"
EXPECTED_FOLDS = tuple(range(5))
EXPECTED_ROWS = 9849
EXPECTED_PARENTS = 54
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_723
PASS_CORE_STATUS = "PASS_ADVANCE_TO_PHASE1B_CONTACT_TARGET_ABLATIONS"
FAIL_CORE_STATUS = "FAIL_NO_V220_PHASE1_CORE_PROMOTION"


class PostprocessError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PostprocessError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_regular_snapshot(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise PostprocessError(f"open_failed:{label}:{path}") from error
    try:
        before = os.fstat(descriptor)
        require(
            stat.S_ISREG(before.st_mode) and before.st_size > 0,
            f"invalid_regular_file:{label}:{path}",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 8 * 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        require(identity(before) == identity(after), f"changed_during_read:{label}:{path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_file(path: Path, label: str = "file") -> str:
    return sha256_bytes(read_regular_snapshot(path, label))


def load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    raw = read_regular_snapshot(path, label)
    try:
        value = json.loads(raw)
    except Exception as error:
        raise PostprocessError(f"invalid_json:{label}:{path}") from error
    require(isinstance(value, dict), f"json_object_required:{label}:{path}")
    return value, sha256_bytes(raw)


def atomic_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json_replace(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class FrozenConfig:
    python_bin: Path
    training_root: Path
    teacher: Path
    assignment: Path
    contracts_dir: Path
    v213_runner: Path
    b0_oof: Path
    b0_replay_receipt: Path
    upstream_preregistration: Path
    pairing_cli: Path
    collector_cli: Path
    evaluator_cli: Path
    core_gate_cli: Path
    frozen_bindings: Mapping[str, Mapping[str, str]]


def _path(value: Any, label: str) -> Path:
    require(isinstance(value, str) and value, f"path_invalid:{label}")
    return Path(value)


def load_frozen_config(
    preregistration_path: Path, expected_preregistration_sha256: str
) -> tuple[FrozenConfig, str]:
    require(
        len(expected_preregistration_sha256) == 64,
        "expected_preregistration_sha256_invalid",
    )
    prereg, observed_hash = load_json(preregistration_path, "postprocess_preregistration")
    require(observed_hash == expected_preregistration_sha256, "postprocess_preregistration_hash")
    require(
        prereg.get("status") == "FROZEN_V220_PHASE1_POSTPROCESS_WATCHER_PROTOCOL",
        "postprocess_preregistration_status",
    )
    require(int(prereg.get("bootstrap_replicates", -1)) == BOOTSTRAP_REPLICATES, "bootstrap_replicates")
    require(int(prereg.get("bootstrap_seed", -1)) == BOOTSTRAP_SEED, "bootstrap_seed")
    require(prereg.get("terminal_semantics", {}).get("core_pass_scope") == "PHASE1B_ONLY", "pass_scope")
    paths = prereg.get("paths") or {}
    bindings = prereg.get("frozen_bindings") or {}
    require(isinstance(bindings, dict) and bindings, "frozen_bindings_missing")
    config = FrozenConfig(
        python_bin=_path(paths.get("python_bin"), "python_bin"),
        training_root=_path(paths.get("training_root"), "training_root"),
        teacher=_path(paths.get("teacher"), "teacher"),
        assignment=_path(paths.get("assignment"), "assignment"),
        contracts_dir=_path(paths.get("contracts_dir"), "contracts_dir"),
        v213_runner=_path(paths.get("v213_runner"), "v213_runner"),
        b0_oof=_path(paths.get("b0_oof"), "b0_oof"),
        b0_replay_receipt=_path(paths.get("b0_replay_receipt"), "b0_replay_receipt"),
        upstream_preregistration=_path(paths.get("upstream_preregistration"), "upstream_preregistration"),
        pairing_cli=_path(paths.get("pairing_cli"), "pairing_cli"),
        collector_cli=_path(paths.get("collector_cli"), "collector_cli"),
        evaluator_cli=_path(paths.get("evaluator_cli"), "evaluator_cli"),
        core_gate_cli=_path(paths.get("core_gate_cli"), "core_gate_cli"),
        frozen_bindings=bindings,
    )
    verify_frozen_bindings(config)
    verify_operational_binding_paths(config)
    return config, observed_hash


def verify_frozen_bindings(config: FrozenConfig) -> None:
    for label, binding in sorted(config.frozen_bindings.items()):
        require(isinstance(binding, Mapping), f"binding_invalid:{label}")
        path = _path(binding.get("path"), f"binding:{label}")
        expected = binding.get("sha256")
        require(isinstance(expected, str) and len(expected) == 64, f"binding_sha_invalid:{label}")
        require(sha256_file(path, f"binding:{label}") == expected, f"binding_hash:{label}")


def verify_operational_binding_paths(config: FrozenConfig) -> None:
    """Close every executable/input path to a specifically named binding."""

    expected = {
        "watcher_cli": Path(__file__).resolve(),
        "python_binary": config.python_bin.resolve(),
        "teacher": config.teacher.resolve(),
        "assignment": config.assignment.resolve(),
        "v213_runner": config.v213_runner.resolve(),
        "b0_oof": config.b0_oof.resolve(),
        "b0_replay_receipt": config.b0_replay_receipt.resolve(),
        "upstream_preregistration": config.upstream_preregistration.resolve(),
        "pairing_cli": config.pairing_cli.resolve(),
        "collector_cli": config.collector_cli.resolve(),
        "evaluator_cli": config.evaluator_cli.resolve(),
        "core_gate_cli": config.core_gate_cli.resolve(),
    }
    for fold in EXPECTED_FOLDS:
        expected[f"fold_{fold}_contract"] = (
            config.contracts_dir / f"fold_{fold}_contract.json"
        ).resolve()
    required_evidence_only = {
        "upstream_final_training_freeze",
        "upstream_final_training_launcher",
        "node1_preflight_receipt",
    }
    require(
        set(config.frozen_bindings) == set(expected) | required_evidence_only,
        "frozen_binding_label_closure",
    )
    for label, path in expected.items():
        bound = _path(config.frozen_bindings[label].get("path"), f"binding:{label}")
        require(bound.resolve() == path, f"operational_binding_path:{label}")
    forbidden = (
        "open_development",
        "open-development",
        "frozen_test",
        "frozen-test",
        "test32",
        "sealed",
        "quarantine",
    )
    for label, path in expected.items():
        lowered = str(path).lower()
        require(
            not any(token in lowered for token in forbidden),
            f"forbidden_operational_path:{label}:{path}",
        )


def inspect_pair_terminals(training_root: Path) -> tuple[dict[int, str], list[int]]:
    hashes: dict[int, str] = {}
    missing: list[int] = []
    for fold in EXPECTED_FOLDS:
        path = training_root / f"fold_{fold}_PAIR_TERMINAL.json"
        if not path.exists():
            missing.append(fold)
            continue
        terminal, digest = load_json(path, f"pair_terminal:{fold}")
        require(terminal.get("status") == "PASS_V220_C0_C1_FOLD_PAIR", f"pair_status:{fold}")
        require(int(terminal.get("fold_id", -1)) == fold, f"pair_fold:{fold}")
        require(int(terminal.get("seed", -1)) == 43, f"pair_seed:{fold}")
        results = terminal.get("results") or {}
        require(set(results) == {"C0", "C1"}, f"pair_result_arms:{fold}")
        for arm in ("C0", "C1"):
            item = results[arm]
            expected_result = training_root / arm / f"fold_{fold}" / "RESULT.json"
            require(Path(item.get("result_path", "")).resolve() == expected_result.resolve(), f"pair_result_path:{arm}:{fold}")
            require(sha256_file(expected_result, f"result:{arm}:{fold}") == item.get("result_sha256"), f"pair_result_hash:{arm}:{fold}")
        hashes[fold] = digest
    return hashes, missing


def wait_for_pair_terminals(
    training_root: Path,
    output_dir: Path,
    *,
    poll_seconds: float,
    timeout_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[int, str]:
    require(poll_seconds > 0, "poll_seconds_invalid")
    require(timeout_seconds >= 0, "timeout_seconds_invalid")
    started = time.monotonic()
    while True:
        hashes, missing = inspect_pair_terminals(training_root)
        atomic_json_replace(
            output_dir / "WAITING.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": "WAITING_FOR_FIVE_FOLD_PAIR_TERMINALS" if missing else "FIVE_FOLD_PAIR_TERMINALS_READY",
                "ready_folds": sorted(hashes),
                "missing_folds": missing,
            },
        )
        if not missing:
            require(set(hashes) == set(EXPECTED_FOLDS), "pair_terminal_closure")
            return hashes
        if timeout_seconds and time.monotonic() - started >= timeout_seconds:
            raise PostprocessError(f"pair_terminal_timeout:missing={missing}")
        sleeper(poll_seconds)


def run_command(command: Sequence[str], log_path: Path) -> None:
    require(not log_path.exists(), f"log_exists:{log_path}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8") as handle:
        completed = subprocess.run(
            list(command),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    require(completed.returncode == 0, f"command_failed:rc={completed.returncode}:log={log_path}")


def build_commands(config: FrozenConfig, output_dir: Path) -> list[tuple[str, list[str], Path]]:
    work = output_dir / "evidence"
    c0_dir, c1_dir = work / "C0_OOF", work / "C1_OOF"
    c0_oof = c0_dir / "V220_C0_TRAIN9849_OOF_PREDICTIONS.tsv"
    c1_oof = c1_dir / "V220_C1_TRAIN9849_OOF_PREDICTIONS.tsv"
    pairing = work / "FIVE_FOLD_PAIRING_RECEIPT.json"
    python = str(config.python_bin)
    commands: list[tuple[str, list[str], Path]] = [
        (
            "pairing",
            [python, str(config.pairing_cli), "--c0-root", str(config.training_root / "C0"), "--c1-root", str(config.training_root / "C1"), "--output-json", str(pairing)],
            output_dir / "logs" / "01_pairing.log",
        )
    ]
    for index, (arm, target) in enumerate((("C0", c0_dir), ("C1", c1_dir)), start=2):
        commands.append(
            (
                f"collect_{arm}",
                [python, str(config.collector_cli), "--teacher", str(config.teacher), "--assignment", str(config.assignment), "--contracts-dir", str(config.contracts_dir), "--run-root", str(config.training_root / arm), "--output-dir", str(target), "--arm", arm, "--v213-runner", str(config.v213_runner)],
                output_dir / "logs" / f"0{index}_collect_{arm}.log",
            )
        )
    for index, (arm, source) in enumerate((("C0", c0_oof), ("C1", c1_oof)), start=4):
        commands.append(
            (
                f"evaluate_{arm}",
                [python, str(config.evaluator_cli), "--input", f"{arm}={source}", "--expected-parents", str(EXPECTED_PARENTS), "--output-json", str(work / f"{arm}_EVALUATION.json")],
                output_dir / "logs" / f"0{index}_evaluate_{arm}.log",
            )
        )
    commands.append(
        (
            "core_gate",
            [python, str(config.core_gate_cli), "--b0", str(config.b0_oof), "--c0", str(c0_oof), "--c1", str(c1_oof), "--b0-replay-receipt", str(config.b0_replay_receipt), "--c0-oof-receipt", str(c0_dir / "OOF_RECEIPT.json"), "--c1-oof-receipt", str(c1_dir / "OOF_RECEIPT.json"), "--pairing-receipt", str(pairing), "--evaluator", str(config.evaluator_cli), "--preregistration", str(config.upstream_preregistration), "--output-json", str(work / "PHASE1_CORE_GATE.json"), "--bootstrap-replicates", str(BOOTSTRAP_REPLICATES), "--bootstrap-seed", str(BOOTSTRAP_SEED)],
            output_dir / "logs" / "06_core_gate.log",
        )
    )
    return commands


def verify_pairing(path: Path) -> dict[str, Any]:
    value, _ = load_json(path, "pairing_receipt")
    require(value.get("status") == "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING", "pairing_status")
    folds = value.get("folds") or []
    require({int(item.get("fold_id", -1)) for item in folds} == set(EXPECTED_FOLDS), "pairing_folds")
    return value


def verify_oof(directory: Path, arm: str) -> tuple[Path, dict[str, Any]]:
    prediction = directory / f"V220_{arm}_TRAIN9849_OOF_PREDICTIONS.tsv"
    receipt, _ = load_json(directory / "OOF_RECEIPT.json", f"{arm}_oof_receipt")
    require(receipt.get("status") == f"PASS_V220_{arm}_TRAIN9849_WHOLE_PARENT_OOF", f"{arm}_oof_status")
    counts = receipt.get("counts") or {}
    require((int(counts.get("rows", -1)), int(counts.get("parents", -1)), int(counts.get("folds", -1)), int(counts.get("seed", -1))) == (EXPECTED_ROWS, EXPECTED_PARENTS, 5, 43), f"{arm}_oof_counts")
    access = receipt.get("input_access") or {}
    require(access == {"open_development_rows": 0, "frozen_test_rows": 0}, f"{arm}_oof_access")
    expected_hash = (receipt.get("outputs") or {}).get(prediction.name)
    require(sha256_file(prediction, f"{arm}_oof") == expected_hash, f"{arm}_oof_hash")
    return prediction, receipt


def verify_individual_evaluation(path: Path, arm: str, prediction: Path) -> dict[str, Any]:
    value, _ = load_json(path, f"{arm}_evaluation")
    require(value.get("status") == "PASS_FROZEN_V220_OOF_EVALUATION", f"{arm}_evaluation_status")
    metrics = (value.get("metrics") or {}).get(arm) or {}
    require((int(metrics.get("rows", -1)), int(metrics.get("parents", -1))) == (EXPECTED_ROWS, EXPECTED_PARENTS), f"{arm}_evaluation_counts")
    require((value.get("input_hashes") or {}).get(arm) == sha256_file(prediction, f"{arm}_evaluation_input"), f"{arm}_evaluation_hash")
    require(value.get("input_access") == {"open_development_rows": 0, "frozen_test_rows": 0}, f"{arm}_evaluation_access")
    return value


def verify_core_gate(path: Path) -> dict[str, Any]:
    value, _ = load_json(path, "phase1_core_gate")
    passed = value.get("all_core_gates_pass")
    require(isinstance(passed, bool), "core_gate_boolean")
    expected_status = PASS_CORE_STATUS if passed else FAIL_CORE_STATUS
    require(value.get("status") == expected_status, "core_gate_status_consistency")
    bootstrap = value.get("bootstrap") or {}
    require((int(bootstrap.get("replicates", -1)), int(bootstrap.get("seed", -1)), int(bootstrap.get("parents", -1))) == (BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, EXPECTED_PARENTS), "core_bootstrap_contract")
    require(value.get("input_access") == {"open_development_rows": 0, "frozen_test_rows": 0}, "core_input_access")
    checks = value.get("gate_checks") or {}
    require(len(checks) == 9 and all(isinstance(item, bool) for item in checks.values()), "core_gate_checks")
    require(all(checks.values()) is passed, "core_gate_all_consistency")
    return value


def write_sha256sums(output_dir: Path) -> Path:
    target = output_dir / "SHA256SUMS"
    require(not target.exists(), "sha256sums_exists")
    files = sorted(
        path
        for root in (output_dir / "evidence", output_dir / "logs")
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    require(files, "no_postprocess_evidence")
    with target.open("x", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256_file(path, 'postprocess_artifact')}  {path.relative_to(output_dir)}\n")
    return target


def execute_postprocess(
    config: FrozenConfig,
    output_dir: Path,
    pair_terminal_hashes: Mapping[int, str],
    *,
    executor: Callable[[Sequence[str], Path], None] = run_command,
) -> dict[str, Any]:
    for stage, command, log in build_commands(config, output_dir):
        verify_frozen_bindings(config)
        verify_operational_binding_paths(config)
        atomic_json_replace(
            output_dir / "RUNNING.json",
            {"schema_version": SCHEMA_VERSION, "status": "RUNNING_FROZEN_POSTPROCESS_STAGE", "stage": stage},
        )
        executor(command, log)

    work = output_dir / "evidence"
    verify_pairing(work / "FIVE_FOLD_PAIRING_RECEIPT.json")
    c0_path, _ = verify_oof(work / "C0_OOF", "C0")
    c1_path, _ = verify_oof(work / "C1_OOF", "C1")
    c0_eval = verify_individual_evaluation(work / "C0_EVALUATION.json", "C0", c0_path)
    c1_eval = verify_individual_evaluation(work / "C1_EVALUATION.json", "C1", c1_path)
    core = verify_core_gate(work / "PHASE1_CORE_GATE.json")
    current_hashes, missing = inspect_pair_terminals(config.training_root)
    require(not missing and current_hashes == dict(pair_terminal_hashes), "pair_terminals_changed_after_wait")
    verify_frozen_bindings(config)
    verify_operational_binding_paths(config)
    sums = write_sha256sums(output_dir)
    common = {
        "schema_version": SCHEMA_VERSION,
        "claim_boundary": "Strict train9849 whole-parent OOF computational Docking-geometry surrogate evidence only; not binding, Kd, experimental blocking, Docking Gold, Top7500 ranking, or production promotion.",
        "pair_terminal_sha256": {str(key): value for key, value in sorted(pair_terminal_hashes.items())},
        "C0_metrics": c0_eval["metrics"]["C0"],
        "C1_metrics": c1_eval["metrics"]["C1"],
        "core_gate_sha256": sha256_file(work / "PHASE1_CORE_GATE.json", "core_gate"),
        "sha256sums_sha256": sha256_file(sums, "sha256sums"),
        "top7500_injected": False,
        "production_promoted": False,
    }
    if core["all_core_gates_pass"]:
        terminal = {
            **common,
            "status": "PASS_V220_PHASE1B_AUTHORIZED_BY_FROZEN_CORE_GATE_ONLY",
            "authorization_scope": "PHASE1B_ABLATIONS_ONLY",
        }
        atomic_json_new(output_dir / "PHASE1B_AUTHORIZED_TERMINAL.json", terminal)
    else:
        terminal = {
            **common,
            "status": FAIL_CORE_STATUS,
            "authorization_scope": "NONE",
        }
        atomic_json_new(output_dir / "CORE_GATE_FAILED_TERMINAL.json", terminal)
    return terminal


def run(
    preregistration_path: Path,
    expected_preregistration_sha256: str,
    output_dir: Path,
    *,
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    require(not output_dir.exists(), f"output_dir_exists:{output_dir}")
    output_dir.mkdir(parents=True)
    stage = "LOAD_FROZEN_CONFIG"
    try:
        config, prereg_hash = load_frozen_config(
            preregistration_path, expected_preregistration_sha256
        )
        atomic_json_new(
            output_dir / "STARTED.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": "STARTED_V220_PHASE1_FAIL_CLOSED_POSTPROCESS_WATCHER",
                "postprocess_preregistration_sha256": prereg_hash,
            },
        )
        stage = "WAIT_FOR_FIVE_FOLD_PAIR_TERMINALS"
        terminals = wait_for_pair_terminals(
            config.training_root,
            output_dir,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        stage = "EXECUTE_FROZEN_POSTPROCESS"
        return execute_postprocess(config, output_dir, terminals)
    except Exception as error:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_V220_PHASE1_POSTPROCESS_NO_PASS_PUBLISHED",
            "stage": stage,
            "error_type": type(error).__name__,
            "error": str(error),
            "phase1b_authorized": False,
            "top7500_injected": False,
            "production_promoted": False,
        }
        if not (output_dir / "FAILED.json").exists():
            atomic_json_new(output_dir / "FAILED.json", failure)
        raise


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--postprocess-preregistration", type=Path, required=True)
    value.add_argument("--expected-postprocess-preregistration-sha256", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--poll-seconds", type=float, default=60.0)
    value.add_argument("--timeout-seconds", type=float, default=0.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = run(
        args.postprocess_preregistration,
        args.expected_postprocess_preregistration_sha256,
        args.output_dir,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({"status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
