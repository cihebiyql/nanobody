#!/usr/bin/env python3
"""Fail-closed V1.3 docking completion and development autorun.

The driver waits for the frozen 30-run completion15 cohort, then executes the
independent selector, native processor, deterministic rebuilds, qualifications,
calibration, and external development release in their preregistered order.
It deliberately has no smoke, regression, formal-release, Gold-label, or
training command.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]

PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
EXPECTED_REMOTE_RUNS = 30
REMOTE_PASS_STATUS = "PASS_4_EMREF_TOP8_READY"
FROZEN_NEW_RUN_MANIFEST_SHA256 = (
    "1a51d482c5d755eeb587d0bbdfab7303327190bd6d54e1ad4ecfd74636fe5151"
)
REMOTE_ROOT = (
    "/data/qlyu/projects/"
    "pvrig_v3_p2_docking_gold_v1_3_dual47_completion15_20260714"
)
FROZEN_CONTROLLER_PID = 4059962
FROZEN_CONTROLLER_PID_SHA256 = (
    "d6bdae94ecac6baab46e1f1d83b360b529bc3a92facc106403378df7465b2028"
)
FROZEN_CONTROLLER_START_TICKS = 664578751
FROZEN_CONTROLLER_PYTHON = "/data/qlyu/anaconda3/envs/haddock3/bin/python"
FROZEN_HADDOCK_BIN = "/data/qlyu/anaconda3/envs/haddock3/bin/haddock3"

STATE_SCHEMA = "pvrig_v1_3_production_autorun_state_v1"
FINAL_PASS = "COMPLETE_DEVELOPMENT_PASS_SMOKE_ELIGIBLE_FORMAL_BLOCKED"
FINAL_FAIL = "COMPLETE_DEVELOPMENT_FAIL_STOPPED"
WAITING = "WAITING_REMOTE_COMPLETION15"
PROBE_ERROR = "WAITING_REMOTE_PROBE_ERROR"
REMOTE_FAILURE = "STOPPED_REMOTE_CONTROLLER_OR_RUN_FAILURE"
STAGE_FAILURE = "STOPPED_LOCAL_STAGE_FAILURE"
DEVELOPMENT_PASS = "PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD"
DEVELOPMENT_FAIL = "FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN"

FALSE_BOUNDARIES = (
    "formal_eligible",
    "docking_gold_release_eligible",
    "training_label_release_eligible",
    "p2_training_ready",
)

SELECTOR_NAME = "recover_phase2_v3_p2_v1_3_dual47_emref_top8.py"
PROCESSOR_NAME = "process_phase2_v3_p2_v1_3_native_top8.py"
PROCESSOR_QUALIFIER_NAME = (
    "validate_phase2_v3_p2_v1_3_native_processor_release.py"
)
CALIBRATOR_NAME = "calibrate_phase2_v3_p2_v1_3_dual_native.py"
DEVELOPMENT_VALIDATOR_NAME = (
    "validate_phase2_v3_p2_v1_3_development_release.py"
)

SELECTOR_AUDIT = "pvrig_v1_3_dual47_emref_top8_recovery_audit.json"
SELECTOR_CSV = "pvrig_v1_3_dual47_emref_top8_selector.csv"
PROCESSOR_AUDIT = "pvrig_v1_3_native_top8_processing_audit.json"
PROCESSOR_METRICS = "pvrig_v1_3_native_top8_continuous_metrics.csv"
PROCESSOR_QUALIFICATION = "pvrig_v1_3_native_processor_qualification.json"
CALIBRATION_AUDIT = "pvrig_v1_3_native_dual_calibration_audit.json"
CALIBRATION_INPUT = "pvrig_v1_3_calibration_release_input.json"
CALIBRATION_RULES = "pvrig_v1_3_native_dual_rules.json"
DEVELOPMENT_RELEASE = "pvrig_v1_3_development_release.json"

CALIBRATION_TABLES = {
    "pvrig_v1_3_native_pose_scores.csv",
    "pvrig_v1_3_native_run_scores.csv",
    "pvrig_v1_3_dual_candidate_scores.csv",
    "pvrig_v1_3_family_lofo.csv",
    "pvrig_v1_3_bootstrap_thresholds.csv",
    "pvrig_v1_3_bootstrap_receptor_anchor_evaluations.csv",
    "pvrig_v1_3_bootstrap_dual_anchor_evaluations.csv",
    "pvrig_v1_3_mutant_paired_deltas.csv",
    "pvrig_v1_3_robustness_grid.csv",
}
CALIBRATION_REPORT = (
    "PVRIG_V3_P2_DOCKING_GOLD_V1_3_NATIVE_DUAL_CALIBRATION_ZH.md"
)


class AutorunError(RuntimeError):
    """Raised when a production autorun contract fails closed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def __call__(self, command: Sequence[str], cwd: Path) -> CommandResult:
        ...


def subprocess_runner(command: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class Layout:
    data_root: Path = DATA_ROOT

    @property
    def exp_dir(self) -> Path:
        return self.data_root / "experiments/phase2_5080_v1"

    @property
    def src(self) -> Path:
        return self.exp_dir / "src"

    @property
    def runs(self) -> Path:
        return self.exp_dir / "runs/pvrig_v3_p2"

    @property
    def selector(self) -> Path:
        return self.runs / "docking_gold_v1_3_dual47_top8_recovery"

    @property
    def processor_primary(self) -> Path:
        return self.runs / "docking_gold_v1_3_native_processing"

    @property
    def processor_rebuild(self) -> Path:
        return self.runs / "docking_gold_v1_3_native_processing_rebuild"

    @property
    def processor_qualification(self) -> Path:
        return self.runs / "docking_gold_v1_3_native_processor_qualification"

    @property
    def calibration_primary(self) -> Path:
        return self.runs / "docking_gold_v1_3_native_dual_calibration"

    @property
    def calibration_rebuild(self) -> Path:
        return self.runs / "docking_gold_v1_3_native_dual_calibration_rebuild"

    @property
    def development_release(self) -> Path:
        return self.runs / "docking_gold_v1_3_development_release"

    @property
    def default_state(self) -> Path:
        return self.exp_dir / "logs/pvrig_v1_3_production_autorun_state.json"

    @property
    def default_log(self) -> Path:
        return self.exp_dir / "logs/pvrig_v1_3_production_autorun.jsonl"


@dataclass(frozen=True)
class Config:
    layout: Layout = field(default_factory=Layout)
    ssh_executable: str = "ssh.exe"
    host: str = "node1"
    python: str = sys.executable
    poll_seconds: float = 60.0
    once: bool = False
    dry_run: bool = False
    state_file: Path | None = None
    log_file: Path | None = None

    @property
    def state_path(self) -> Path:
        return (self.state_file or self.layout.default_state).resolve()

    @property
    def log_path(self) -> Path:
        return (self.log_file or self.layout.default_log).resolve()


@dataclass(frozen=True)
class RemoteSnapshot:
    status: str
    manifest_count: int
    completion_count: int
    pass_count: int
    failure_count: int
    missing_count: int
    invalid_count: int
    controller_alive: bool
    manifest_sha256: str = ""
    controller_pid: int | None = None
    controller_start_ticks: int | None = None
    controller_pid_file_valid: bool = False
    controller_identity_valid: bool = False
    controller_argv_sha256: str = ""
    failures: tuple[str, ...] = ()

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "RemoteSnapshot":
        required = {
            "status",
            "manifest_count",
            "completion_count",
            "pass_count",
            "failure_count",
            "missing_count",
            "invalid_count",
            "controller_alive",
            "manifest_sha256",
            "controller_pid",
            "controller_start_ticks",
            "controller_pid_file_valid",
            "controller_identity_valid",
            "controller_argv_sha256",
        }
        if not required.issubset(payload):
            raise AutorunError("Remote snapshot lacks required fields")
        snapshot = cls(
            status=str(payload["status"]),
            manifest_count=int(payload["manifest_count"]),
            completion_count=int(payload["completion_count"]),
            pass_count=int(payload["pass_count"]),
            failure_count=int(payload["failure_count"]),
            missing_count=int(payload["missing_count"]),
            invalid_count=int(payload["invalid_count"]),
            controller_alive=payload["controller_alive"] is True,
            manifest_sha256=str(payload["manifest_sha256"]),
            controller_pid=(
                int(payload["controller_pid"])
                if payload["controller_pid"] is not None
                else None
            ),
            controller_start_ticks=(
                int(payload["controller_start_ticks"])
                if payload["controller_start_ticks"] is not None
                else None
            ),
            controller_pid_file_valid=payload["controller_pid_file_valid"] is True,
            controller_identity_valid=payload["controller_identity_valid"] is True,
            controller_argv_sha256=str(payload["controller_argv_sha256"]),
            failures=tuple(str(value) for value in payload.get("failures", [])),
        )
        # Explicit remote failures are terminal evidence even when the frozen
        # manifest could not be read and therefore has zero observed rows.
        if snapshot.status == "FAILURE":
            return snapshot
        if snapshot.manifest_count != EXPECTED_REMOTE_RUNS:
            raise AutorunError("Remote frozen manifest is not exactly 30 runs")
        if snapshot.manifest_sha256 != FROZEN_NEW_RUN_MANIFEST_SHA256:
            raise AutorunError("Remote frozen manifest SHA256 mismatch")
        if snapshot.status == "READY":
            if (
                snapshot.completion_count != EXPECTED_REMOTE_RUNS
                or snapshot.pass_count != EXPECTED_REMOTE_RUNS
                or snapshot.failure_count
                or snapshot.missing_count
                or snapshot.invalid_count
            ):
                raise AutorunError("Remote READY snapshot lacks exact 30/30 closure")
        elif snapshot.status == "WAITING":
            if (
                not snapshot.controller_alive
                or not snapshot.controller_pid_file_valid
                or not snapshot.controller_identity_valid
                or snapshot.controller_pid != FROZEN_CONTROLLER_PID
                or snapshot.controller_start_ticks != FROZEN_CONTROLLER_START_TICKS
                or snapshot.failure_count
                or snapshot.invalid_count
            ):
                raise AutorunError("Remote WAITING snapshot is not controller-safe")
        elif snapshot.status != "FAILURE":
            raise AutorunError(f"Unknown remote snapshot status: {snapshot.status}")
        return snapshot

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifest_count": self.manifest_count,
            "completion_count": self.completion_count,
            "pass_count": self.pass_count,
            "failure_count": self.failure_count,
            "missing_count": self.missing_count,
            "invalid_count": self.invalid_count,
            "controller_alive": self.controller_alive,
            "manifest_sha256": self.manifest_sha256,
            "controller_pid": self.controller_pid,
            "controller_start_ticks": self.controller_start_ticks,
            "controller_pid_file_valid": self.controller_pid_file_valid,
            "controller_identity_valid": self.controller_identity_valid,
            "controller_argv_sha256": self.controller_argv_sha256,
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]
    release_root: Path
    marker: str
    validator: Callable[[Path], dict[str, Any]]
    upstreams: tuple["Upstream", ...] = ()


@dataclass(frozen=True)
class Upstream:
    name: str
    release_root: Path
    marker: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AutorunError(f"Invalid JSON artifact: {path}") from error
    if not isinstance(payload, dict):
        raise AutorunError(f"JSON artifact is not an object: {path}")
    return payload


def csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def require_false(payload: Mapping[str, Any], fields: Sequence[str]) -> None:
    failures = [name for name in fields if payload.get(name) is not False]
    if failures:
        raise AutorunError(f"Eligibility boundary is not false: {failures}")


def validate_selector(release: Path) -> dict[str, Any]:
    audit = read_json(release / SELECTOR_AUDIT)
    if audit.get("status") != "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED":
        raise AutorunError("Selector audit status mismatch")
    require_false(audit, FALSE_BOUNDARIES[:3])
    counts = audit.get("counts", {})
    if not isinstance(counts, dict) or (
        counts.get("manifest_runs") != 94
        or counts.get("selected_runs") != 94
        or counts.get("selected_poses") != 752
        or counts.get("cases") != 47
    ):
        raise AutorunError("Selector 47/94/752 closure failed")
    selector = release / SELECTOR_CSV
    if csv_rows(selector) != 752:
        raise AutorunError("Selector CSV does not contain 752 poses")
    binding = audit.get("output_csv", {})
    if not isinstance(binding, dict) or binding.get("sha256") != sha256_file(selector):
        raise AutorunError("Selector CSV hash binding failed")
    return {"status": audit["status"], "rows": 752}


def validate_processor(release: Path) -> dict[str, Any]:
    audit = read_json(release / PROCESSOR_AUDIT)
    if audit.get("status") != "BUILT_PENDING_DEVELOPMENT_RELEASE":
        raise AutorunError("Processor audit status mismatch")
    require_false(audit, FALSE_BOUNDARIES)
    if audit.get("primary_native_metric_eligible") is not False:
        raise AutorunError("Processor self-authorized native metrics")
    observed = audit.get("observed_contract", {})
    if not isinstance(observed, dict) or (
        observed.get("case_count") != 47
        or observed.get("run_count") != 94
        or observed.get("metric_rows") != 752
        or observed.get("contact_records") != 752
        or observed.get("aligned_pose_files") != 752
    ):
        raise AutorunError("Processor 47/94/752 closure failed")
    metrics = release / PROCESSOR_METRICS
    if csv_rows(metrics) != 752:
        raise AutorunError("Processor metrics do not contain 752 rows")
    binding = audit.get("output_sha256", {}).get("continuous_metrics", {})
    if not isinstance(binding, dict) or binding.get("sha256") != sha256_file(metrics):
        raise AutorunError("Processor metrics hash binding failed")
    return {"status": audit["status"], "rows": 752}


def validate_processor_qualification(release: Path) -> dict[str, Any]:
    payload = read_json(release / PROCESSOR_QUALIFICATION)
    if payload.get("status") != "QUALIFIED_NATIVE_PROCESSOR_INPUT":
        raise AutorunError("Processor qualification status mismatch")
    require_false(payload, FALSE_BOUNDARIES)
    determinism = payload.get("determinism", {})
    if (
        payload.get("calibration_input_eligible") is not True
        or not isinstance(determinism, dict)
        or determinism.get("independent_publication_count") != 2
        or determinism.get("full_inventory_equal") is not True
        or determinism.get("core_output_hashes_equal") is not True
    ):
        raise AutorunError("Processor independent qualification failed")
    return {"status": payload["status"]}


def validate_calibration(release: Path) -> dict[str, Any]:
    expected = {
        CALIBRATION_AUDIT,
        CALIBRATION_INPUT,
        CALIBRATION_RULES,
        CALIBRATION_REPORT,
        *CALIBRATION_TABLES,
    }
    observed = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file()
    }
    if observed != expected:
        raise AutorunError("Calibration immutable 13-file inventory mismatch")
    audit = read_json(release / CALIBRATION_AUDIT)
    release_input = read_json(release / CALIBRATION_INPUT)
    rules = read_json(release / CALIBRATION_RULES)
    for payload in (audit, release_input, rules):
        require_false(payload, FALSE_BOUNDARIES)
        if payload.get("development_smoke_eligible") is not False:
            raise AutorunError("Calibrator self-authorized development smoke")
    if audit.get("status") != "CALCULATED_PENDING_RELEASE_VALIDATION":
        raise AutorunError("Calibration audit status mismatch")
    if release_input.get("status") != "PENDING_EXTERNAL_RELEASE_VALIDATION":
        raise AutorunError("Calibration release-input status mismatch")
    if rules.get("status") != "CALCULATED_PENDING_RELEASE_VALIDATION":
        raise AutorunError("Calibration rules status mismatch")
    if release_input.get("release_id") != release.resolve().name:
        raise AutorunError("Calibration release identity mismatch")
    audit_binding = release_input.get("calibration_audit", {})
    if not isinstance(audit_binding, dict) or audit_binding.get("sha256") != sha256_file(
        release / CALIBRATION_AUDIT
    ):
        raise AutorunError("Calibration audit binding failed")
    central = audit.get("central_outputs", {})
    if not isinstance(central, dict) or (
        central.get("pose_rows") != 752
        or central.get("native_run_rows") != 94
        or central.get("dual_candidate_rows") != 47
    ):
        raise AutorunError("Calibration 47/94/752 closure failed")
    outcome = audit.get("computed_gate_outcome")
    if outcome not in {"COMPUTED_GATES_SATISFIED", "COMPUTED_GATES_NOT_SATISFIED"}:
        raise AutorunError("Calibration computed-gate outcome is invalid")
    return {"status": audit["status"], "computed_gate_outcome": outcome}


def validate_development(release: Path) -> dict[str, Any]:
    payload = read_json(release / DEVELOPMENT_RELEASE)
    require_false(payload, FALSE_BOUNDARIES)
    if payload.get("training_state") != "P2_TRAINING_BLOCKED":
        raise AutorunError("Development release changed P2 training boundary")
    status = payload.get("status")
    smoke = payload.get("development_smoke_eligible")
    if (status, smoke) not in {
        (DEVELOPMENT_PASS, True),
        (DEVELOPMENT_FAIL, False),
    }:
        raise AutorunError("Development decision/status mismatch")
    anchor = payload.get("anchor_readiness", {})
    if not isinstance(anchor, dict) or (
        anchor.get("new_eligible_independent_family_count") != 0
        or anchor.get("unconditional_formal_veto") is not True
    ):
        raise AutorunError("Development release lost the formal anchor veto")
    return {"status": status, "development_smoke_eligible": smoke}


def release_inventory(root: Path, marker: str) -> dict[str, Any]:
    current = root / "current"
    if not current.is_symlink():
        raise AutorunError(f"Current pointer is not an immutable symlink: {current}")
    target_text = os.readlink(current)
    if os.path.isabs(target_text):
        raise AutorunError(f"Current pointer must use a relative target: {current}")
    release = current.resolve(strict=True)
    releases = (root / "releases").resolve()
    if release.parent != releases or not (release / marker).is_file():
        raise AutorunError(f"Current pointer escapes or lacks marker: {current}")
    members = sorted(release.rglob("*"))
    internal_symlinks = [
        path.relative_to(release).as_posix() for path in members if path.is_symlink()
    ]
    if internal_symlinks:
        raise AutorunError(
            f"Immutable release contains internal symlinks: {internal_symlinks}"
        )
    files = {
        path.relative_to(release).as_posix(): sha256_file(path)
        for path in members
        if path.is_file()
    }
    if not files:
        raise AutorunError(f"Immutable release is empty: {release}")
    return {
        "root": root.resolve().as_posix(),
        "current_target": target_text,
        "current_resolved": release.as_posix(),
        "release_id": release.name,
        "file_count": len(files),
        "files": files,
        "inventory_sha256": sha256_bytes(canonical_json(files).encode("utf-8")),
    }


def remote_probe_script() -> str:
    script = r'''import csv, hashlib, io, json, os, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
proc_root = pathlib.Path(sys.argv[2]) if len(sys.argv) == 3 else pathlib.Path("/proc")
protocol = "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
passed = "PASS_4_EMREF_TOP8_READY"
expected_manifest_sha = "__MANIFEST_SHA__"
expected_pid = __CONTROLLER_PID__
expected_pid_sha = "__CONTROLLER_PID_SHA__"
expected_start_ticks = __CONTROLLER_START_TICKS__
expected_python = "__CONTROLLER_PYTHON__"
expected_haddock = "__HADDOCK_BIN__"

def emit(status, manifest_count=0, completion_count=0, pass_count=0,
         failure_count=0, missing_count=30, invalid_count=0,
         manifest_sha256="", controller_alive=False, controller_pid=None,
         controller_start_ticks=None, controller_pid_file_valid=False,
         controller_identity_valid=False, controller_argv_sha256="", failures=()):
    print(json.dumps({"status":status,"manifest_count":manifest_count,
        "completion_count":completion_count,"pass_count":pass_count,
        "failure_count":failure_count,"missing_count":missing_count,
        "invalid_count":invalid_count,"manifest_sha256":manifest_sha256,
        "controller_alive":controller_alive,"controller_pid":controller_pid,
        "controller_start_ticks":controller_start_ticks,
        "controller_pid_file_valid":controller_pid_file_valid,
        "controller_identity_valid":controller_identity_valid,
        "controller_argv_sha256":controller_argv_sha256,
        "failures":list(failures)}, sort_keys=True))

manifest = root / "manifests/new_run_manifest.csv"
try:
    manifest_bytes = manifest.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    text = manifest_bytes.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
except Exception as error:
    emit("FAILURE", failure_count=1, invalid_count=1,
         failures=["manifest_unreadable_or_malformed:" + str(error)])
    raise SystemExit

manifest_failures = []
required = {"protocol_id", "run_id", "config_sha256", "completion_relpath"}
if not rows or not required.issubset(rows[0]):
    manifest_failures.append("manifest_required_fields_missing")
run_ids = [str(row.get("run_id", "")) for row in rows]
config_hashes = [str(row.get("config_sha256", "")) for row in rows]
if manifest_sha != expected_manifest_sha:
    manifest_failures.append("manifest_sha256_mismatch")
if len(rows) != 30:
    manifest_failures.append("manifest_row_count_not_30")
if len(run_ids) != 30 or len(set(run_ids)) != 30 or any(not value for value in run_ids):
    manifest_failures.append("manifest_run_ids_not_30_unique")
if (len(config_hashes) != 30 or len(set(config_hashes)) != 30
        or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in config_hashes)):
    manifest_failures.append("manifest_config_hashes_not_30_unique_sha256")

root_resolved = root.resolve()
normalized_paths = []
for index, row in enumerate(rows, start=2):
    if row.get("protocol_id") != protocol:
        manifest_failures.append("manifest_protocol_mismatch_row_" + str(index))
    raw = str(row.get("completion_relpath", ""))
    pure = pathlib.PurePosixPath(raw)
    valid = (bool(raw) and "\\" not in raw and not pure.is_absolute()
             and raw == pure.as_posix())
    valid = valid and all(part not in {"", ".", ".."} for part in pure.parts)
    if valid:
        candidate = (root / pathlib.Path(*pure.parts)).resolve(strict=False)
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            valid = False
    if not valid:
        manifest_failures.append("manifest_completion_path_unsafe_row_" + str(index))
    normalized_paths.append(raw)
if len(normalized_paths) != 30 or len(set(normalized_paths)) != 30:
    manifest_failures.append("manifest_completion_paths_not_30_unique")
if manifest_failures:
    emit("FAILURE", manifest_count=len(rows), failure_count=1,
         missing_count=max(0, 30 - len(rows)), invalid_count=len(manifest_failures),
         manifest_sha256=manifest_sha, failures=manifest_failures)
    raise SystemExit

expected_paths = set(normalized_paths)
found_paths = {
    path.relative_to(root).as_posix()
    for path in (root / "runs").glob("*/*.complete.json")
}
failures = []
unexpected = found_paths - expected_paths
if unexpected:
    failures.append("unexpected_completion_files:" + ",".join(sorted(unexpected)))
pass_count = invalid_count = failure_count = completion_count = 0
for row in rows:
    path = root / row["completion_relpath"]
    if not path.is_file():
        continue
    completion_count += 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        valid = (payload.get("protocol_id") == protocol
            and payload.get("run_id") == row["run_id"]
            and payload.get("config_sha256") == row["config_sha256"])
        if not valid:
            invalid_count += 1
            failures.append(row["run_id"] + ":invalid_binding")
        elif payload.get("status") == passed and payload.get("exit_code") == 0:
            pass_count += 1
        else:
            failure_count += 1
            failures.append(row["run_id"] + ":" + str(payload.get("status")))
    except Exception as error:
        invalid_count += 1
        failures.append(row["run_id"] + ":invalid_json:" + str(error))
missing_count = 30 - completion_count

controller_alive = False
controller_pid = None
controller_start_ticks = None
controller_pid_file_valid = False
controller_identity_valid = False
controller_argv_sha256 = ""
ready = (completion_count == 30 and pass_count == 30 and missing_count == 0
         and not unexpected and not invalid_count and not failure_count)
if not ready and not unexpected and not invalid_count and not failure_count:
    pid_file = root / "controller_full.pid"
    try:
        pid_bytes = pid_file.read_bytes()
        controller_pid = int(pid_bytes.decode("ascii").strip())
        controller_pid_file_valid = (
            controller_pid == expected_pid
            and hashlib.sha256(pid_bytes).hexdigest() == expected_pid_sha
        )
    except Exception as error:
        failures.append("controller_pid_file_missing_or_invalid:" + str(error))
    if not controller_pid_file_valid:
        failures.append("controller_pid_file_identity_mismatch")
    else:
        proc = proc_root / str(controller_pid)
        try:
            argv_bytes = (proc / "cmdline").read_bytes()
            argv = [part.decode("utf-8") for part in argv_bytes.split(b"\0") if part]
            controller_argv_sha256 = hashlib.sha256(argv_bytes).hexdigest()
            cwd = pathlib.Path(os.readlink(proc / "cwd")).resolve()
            executable = pathlib.Path(os.readlink(proc / "exe")).resolve().as_posix()
            stat_text = (proc / "stat").read_text(encoding="ascii")
            stat_fields = stat_text.rsplit(")", 1)[1].strip().split()
            controller_start_ticks = int(stat_fields[19])
            expected_argv = [expected_python, "scripts/run_v1_3_completion15.py",
                "--root", root_resolved.as_posix(), "--haddock-bin", expected_haddock,
                "--max-workers", "5", "--max-load1", "50",
                "--load-poll-seconds", "30"]
            controller_identity_valid = (
                argv == expected_argv
                and cwd == root_resolved
                and executable == pathlib.Path(expected_python).resolve().as_posix()
                and controller_start_ticks == expected_start_ticks
            )
            controller_alive = controller_identity_valid
            if not controller_identity_valid:
                failures.append("controller_proc_argv_root_start_identity_mismatch")
        except Exception as error:
            failures.append("controller_proc_missing_or_dead:" + str(error))

if unexpected or invalid_count or failure_count:
    status = "FAILURE"
elif ready:
    status = "READY"
elif controller_alive:
    status = "WAITING"
else:
    status = "FAILURE"
    failures.append("controller_not_alive_with_pending_runs")
emit(status, manifest_count=30, completion_count=completion_count,
     pass_count=pass_count, failure_count=failure_count,
     missing_count=missing_count, invalid_count=invalid_count,
     manifest_sha256=manifest_sha, controller_alive=controller_alive,
     controller_pid=controller_pid, controller_start_ticks=controller_start_ticks,
     controller_pid_file_valid=controller_pid_file_valid,
     controller_identity_valid=controller_identity_valid,
     controller_argv_sha256=controller_argv_sha256, failures=failures)'''
    return (
        script.replace("__MANIFEST_SHA__", FROZEN_NEW_RUN_MANIFEST_SHA256)
        .replace("__CONTROLLER_PID__", str(FROZEN_CONTROLLER_PID))
        .replace("__CONTROLLER_PID_SHA__", FROZEN_CONTROLLER_PID_SHA256)
        .replace("__CONTROLLER_START_TICKS__", str(FROZEN_CONTROLLER_START_TICKS))
        .replace("__CONTROLLER_PYTHON__", FROZEN_CONTROLLER_PYTHON)
        .replace("__HADDOCK_BIN__", FROZEN_HADDOCK_BIN)
    )


def remote_command(config: Config) -> tuple[str, ...]:
    command = "python3 -c {} {}".format(
        shlex.quote(remote_probe_script()), shlex.quote(REMOTE_ROOT)
    )
    return (config.ssh_executable, config.host, command)


def parse_remote_result(result: CommandResult) -> RemoteSnapshot:
    if result.returncode != 0:
        raise AutorunError(
            f"Remote probe exited {result.returncode}: {result.stderr.strip()}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AutorunError("Remote probe returned no JSON")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise AutorunError("Remote probe returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise AutorunError("Remote probe JSON is not an object")
    return RemoteSnapshot.parse(payload)


def build_stages(config: Config) -> tuple[Stage, ...]:
    layout = config.layout
    python = config.python
    src = layout.src
    processor_primary_audit = layout.processor_primary / "current" / PROCESSOR_AUDIT
    processor_rebuild_audit = layout.processor_rebuild / "current" / PROCESSOR_AUDIT
    calibration_primary_input = layout.calibration_primary / "current" / CALIBRATION_INPUT
    calibration_rebuild_input = layout.calibration_rebuild / "current" / CALIBRATION_INPUT
    selector_upstream = Upstream("selector", layout.selector, SELECTOR_AUDIT)
    processor_primary_upstream = Upstream(
        "processor_primary", layout.processor_primary, PROCESSOR_AUDIT
    )
    processor_rebuild_upstream = Upstream(
        "processor_rebuild", layout.processor_rebuild, PROCESSOR_AUDIT
    )
    qualification_upstream = Upstream(
        "processor_qualification",
        layout.processor_qualification,
        PROCESSOR_QUALIFICATION,
    )
    calibration_primary_upstream = Upstream(
        "calibration_primary", layout.calibration_primary, CALIBRATION_AUDIT
    )
    calibration_rebuild_upstream = Upstream(
        "calibration_rebuild", layout.calibration_rebuild, CALIBRATION_AUDIT
    )
    return (
        Stage(
            "selector",
            (
                python,
                str(src / SELECTOR_NAME),
                "--ssh-executable",
                config.ssh_executable,
                "--host",
                config.host,
            ),
            layout.selector,
            SELECTOR_AUDIT,
            validate_selector,
        ),
        Stage(
            "processor_primary",
            (python, str(src / PROCESSOR_NAME)),
            layout.processor_primary,
            PROCESSOR_AUDIT,
            validate_processor,
            (selector_upstream,),
        ),
        Stage(
            "processor_rebuild",
            (
                python,
                str(src / PROCESSOR_NAME),
                "--outdir",
                str(layout.processor_rebuild),
            ),
            layout.processor_rebuild,
            PROCESSOR_AUDIT,
            validate_processor,
            (selector_upstream,),
        ),
        Stage(
            "processor_qualification",
            (
                python,
                str(src / PROCESSOR_QUALIFIER_NAME),
                "--primary-audit",
                str(processor_primary_audit),
                "--rebuild-audit",
                str(processor_rebuild_audit),
            ),
            layout.processor_qualification,
            PROCESSOR_QUALIFICATION,
            validate_processor_qualification,
            (
                selector_upstream,
                processor_primary_upstream,
                processor_rebuild_upstream,
            ),
        ),
        Stage(
            "calibration_primary",
            (python, str(src / CALIBRATOR_NAME)),
            layout.calibration_primary,
            CALIBRATION_AUDIT,
            validate_calibration,
            (
                selector_upstream,
                processor_primary_upstream,
                qualification_upstream,
            ),
        ),
        Stage(
            "calibration_rebuild",
            (
                python,
                str(src / CALIBRATOR_NAME),
                "--outdir",
                str(layout.calibration_rebuild),
            ),
            layout.calibration_rebuild,
            CALIBRATION_AUDIT,
            validate_calibration,
            (
                selector_upstream,
                processor_primary_upstream,
                qualification_upstream,
            ),
        ),
        Stage(
            "development_release",
            (
                python,
                str(src / DEVELOPMENT_VALIDATOR_NAME),
                "--primary-release-input",
                str(calibration_primary_input),
                "--rebuild-release-input",
                str(calibration_rebuild_input),
            ),
            layout.development_release,
            DEVELOPMENT_RELEASE,
            validate_development,
            (
                selector_upstream,
                processor_primary_upstream,
                qualification_upstream,
                calibration_primary_upstream,
                calibration_rebuild_upstream,
            ),
        ),
    )


class Autorun:
    def __init__(
        self,
        config: Config,
        *,
        runner: Runner | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.runner = runner or subprocess_runner
        self.sleeper = sleeper
        self.state = self._load_state()

    def _new_state(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA,
            "status": "INITIALIZED",
            "protocol_id": PROTOCOL_ID,
            "remote_root": REMOTE_ROOT,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "stages": {},
            "updated_at_utc": utc_now(),
        }

    def _load_state(self) -> dict[str, Any]:
        path = self.config.state_path
        if not path.exists():
            return self._new_state()
        payload = read_json(path)
        if (
            payload.get("schema_version") != STATE_SCHEMA
            or payload.get("protocol_id") != PROTOCOL_ID
            or payload.get("remote_root") != REMOTE_ROOT
        ):
            raise AutorunError("Existing autorun state contract mismatch")
        require_false(payload, FALSE_BOUNDARIES)
        if not isinstance(payload.get("stages"), dict):
            raise AutorunError("Existing autorun stage ledger is invalid")
        return payload

    def _save(self) -> None:
        self.state["updated_at_utc"] = utc_now()
        self.state["formal_eligible"] = False
        self.state["docking_gold_release_eligible"] = False
        self.state["training_label_release_eligible"] = False
        self.state["p2_training_ready"] = False
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _log(self, event: str, **payload: Any) -> None:
        path = self.config.log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": STATE_SCHEMA,
            "at_utc": utc_now(),
            "event": event,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _probe(self) -> RemoteSnapshot:
        command = remote_command(self.config)
        result = self.runner(command, self.config.layout.data_root)
        self._log(
            "remote_probe_command",
            command=list(command),
            returncode=result.returncode,
            stdout_sha256=sha256_bytes(result.stdout.encode("utf-8")),
            stderr_sha256=sha256_bytes(result.stderr.encode("utf-8")),
        )
        return parse_remote_result(result)

    def _record_status(self, status: str, **extra: Any) -> None:
        self.state["status"] = status
        if status not in {PROBE_ERROR, REMOTE_FAILURE, STAGE_FAILURE}:
            for field_name in (
                "remote_probe_error",
                "failed_stage",
                "failure_reason",
            ):
                self.state.pop(field_name, None)
        self.state.update(extra)
        self._save()
        self._log("status", status=status, **extra)

    @staticmethod
    def _command_hash(command: Sequence[str]) -> str:
        return sha256_bytes(canonical_json(list(command)).encode("utf-8"))

    @staticmethod
    def _implementation_hash(stage: Stage) -> str:
        implementation = Path(stage.command[1])
        if not implementation.is_file():
            raise AutorunError(
                f"Stage implementation is missing: {implementation}"
            )
        return sha256_file(implementation)

    @staticmethod
    def _upstream_bindings(stage: Stage) -> dict[str, dict[str, Any]]:
        bindings: dict[str, dict[str, Any]] = {}
        for upstream in stage.upstreams:
            inventory = release_inventory(upstream.release_root, upstream.marker)
            bindings[upstream.name] = {
                "root": inventory["root"],
                "current_target": inventory["current_target"],
                "current_resolved": inventory["current_resolved"],
                "release_id": inventory["release_id"],
                "file_count": inventory["file_count"],
                "inventory_sha256": inventory["inventory_sha256"],
            }
        return bindings

    def _receipt_valid(self, stage: Stage) -> bool:
        receipt = self.state["stages"].get(stage.name)
        if not isinstance(receipt, dict) or receipt.get("status") not in {
            "COMPLETED",
            "REUSED",
        }:
            return False
        if receipt.get("command_sha256") != self._command_hash(stage.command):
            return False
        try:
            implementation_sha256 = self._implementation_hash(stage)
        except AutorunError:
            return False
        if receipt.get("implementation_sha256") != implementation_sha256:
            return False
        expected_upstreams = receipt.get("upstreams")
        if not isinstance(expected_upstreams, dict):
            return False
        expected = receipt.get("artifacts")
        if not isinstance(expected, dict):
            return False
        try:
            if self._upstream_bindings(stage) != expected_upstreams:
                return False
            current = release_inventory(stage.release_root, stage.marker)
            if current != expected:
                return False
            stage.validator(stage.release_root / "current")
        except (AutorunError, OSError, ValueError):
            return False
        return True

    def _execute_stage(self, stage: Stage, *, force: bool = False) -> bool:
        if not force and self._receipt_valid(stage):
            receipt = dict(self.state["stages"][stage.name])
            receipt["status"] = "REUSED"
            receipt["reused_at_utc"] = utc_now()
            self.state["stages"][stage.name] = receipt
            self._save()
            self._log(
                "stage_reused",
                stage=stage.name,
                command=list(stage.command),
                upstreams=receipt["upstreams"],
                artifacts=receipt["artifacts"],
            )
            return True

        started = utc_now()
        self.state["active_stage"] = stage.name
        self._save()
        self._log(
            "stage_started",
            stage=stage.name,
            command=list(stage.command),
            forced_by_upstream_invalidation=force,
        )
        try:
            implementation_sha256 = self._implementation_hash(stage)
            upstreams_before = self._upstream_bindings(stage)
        except (AutorunError, OSError, ValueError) as error:
            receipt = {
                "status": "FAILED_IMPLEMENTATION_OR_UPSTREAM_VALIDATION",
                "command": list(stage.command),
                "command_sha256": self._command_hash(stage.command),
                "error": str(error),
                "started_at_utc": started,
                "finished_at_utc": utc_now(),
            }
            self.state["stages"][stage.name] = receipt
            self.state.pop("active_stage", None)
            self._record_status(
                STAGE_FAILURE,
                failed_stage=stage.name,
                failure_reason=str(error),
            )
            self._log("stage_failed", stage=stage.name, **receipt)
            return False
        result = self.runner(stage.command, self.config.layout.data_root)
        command_evidence = {
            "command": list(stage.command),
            "command_sha256": self._command_hash(stage.command),
            "implementation_sha256": implementation_sha256,
            "upstreams": upstreams_before,
            "returncode": result.returncode,
            "stdout_sha256": sha256_bytes(result.stdout.encode("utf-8")),
            "stderr_sha256": sha256_bytes(result.stderr.encode("utf-8")),
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
        }
        if result.returncode != 0:
            receipt = {"status": "FAILED_COMMAND", **command_evidence}
            self.state["stages"][stage.name] = receipt
            self.state.pop("active_stage", None)
            self._record_status(
                STAGE_FAILURE,
                failed_stage=stage.name,
                failure_reason=f"command return code {result.returncode}",
            )
            self._log("stage_failed", stage=stage.name, **receipt)
            return False
        try:
            upstreams_after = self._upstream_bindings(stage)
            if upstreams_after != upstreams_before:
                raise AutorunError(
                    "Direct upstream immutable release changed during stage execution"
                )
            semantics = stage.validator(stage.release_root / "current")
            artifacts = release_inventory(stage.release_root, stage.marker)
        except (AutorunError, OSError, ValueError) as error:
            receipt = {
                "status": "FAILED_ARTIFACT_VALIDATION",
                **command_evidence,
                "error": str(error),
            }
            self.state["stages"][stage.name] = receipt
            self.state.pop("active_stage", None)
            self._record_status(
                STAGE_FAILURE,
                failed_stage=stage.name,
                failure_reason=str(error),
            )
            self._log("stage_failed", stage=stage.name, **receipt)
            return False
        receipt = {
            "status": "COMPLETED",
            **command_evidence,
            "semantics": semantics,
            "upstreams": upstreams_after,
            "artifacts": artifacts,
        }
        self.state["stages"][stage.name] = receipt
        self.state.pop("active_stage", None)
        self._save()
        self._log("stage_completed", stage=stage.name, **receipt)
        return True

    def _completed_state_is_reusable(self, stages: Sequence[Stage]) -> bool:
        if self.state.get("status") not in {FINAL_PASS, FINAL_FAIL}:
            return False
        return all(self._receipt_valid(stage) for stage in stages)

    def run(self) -> str:
        stages = build_stages(self.config)
        if self.config.dry_run:
            plan = {
                "status": "DRY_RUN_ONLY",
                "remote_command": list(remote_command(self.config)),
                "stages": [
                    {"name": stage.name, "command": list(stage.command)}
                    for stage in stages
                ],
                "automatic_smoke_or_formal_commands": False,
                "formal_eligible": False,
                "docking_gold_release_eligible": False,
                "training_label_release_eligible": False,
                "p2_training_ready": False,
            }
            print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
            return "DRY_RUN_ONLY"
        if self._completed_state_is_reusable(stages):
            self._log("completed_state_reused", status=self.state["status"])
            return str(self.state["status"])

        while True:
            try:
                snapshot = self._probe()
            except AutorunError as error:
                self._record_status(PROBE_ERROR, remote_probe_error=str(error))
                if self.config.once:
                    return PROBE_ERROR
                self.sleeper(self.config.poll_seconds)
                continue
            self.state["remote_snapshot"] = snapshot.as_dict()
            self._save()
            self._log("remote_snapshot", snapshot=snapshot.as_dict())
            if snapshot.status == "FAILURE":
                self._record_status(
                    REMOTE_FAILURE,
                    failure_reason=";".join(snapshot.failures) or "remote failure",
                )
                return REMOTE_FAILURE
            if snapshot.status == "READY":
                self._record_status("REMOTE_COMPLETION15_READY")
                break
            self._record_status(WAITING)
            if self.config.once:
                return WAITING
            self.sleeper(self.config.poll_seconds)

        force_descendants = False
        for stage in stages:
            if force_descendants or not self._receipt_valid(stage):
                force_descendants = True
            if not self._execute_stage(stage, force=force_descendants):
                return STAGE_FAILURE

        development = stages[-1].validator(
            stages[-1].release_root / "current"
        )
        if development["status"] == DEVELOPMENT_PASS:
            final = FINAL_PASS
        elif development["status"] == DEVELOPMENT_FAIL:
            final = FINAL_FAIL
        else:  # pragma: no cover - guarded by validate_development
            raise AutorunError("Unreachable development decision")
        self._record_status(
            final,
            development_status=development["status"],
            development_smoke_eligible=development["development_smoke_eligible"],
            formal_blocked_by_anchor_panel=True,
            automatic_smoke_or_formal_commands=False,
        )
        return final


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.handle.close()
            raise AutorunError(f"Another autorun holds {self.path}") from error
        return self

    def __exit__(self, *_args: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--ssh-executable", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--log-file", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.poll_seconds <= 0:
        print("ERROR: --poll-seconds must be positive", file=sys.stderr)
        return 2
    config = Config(
        ssh_executable=args.ssh_executable,
        host=args.host,
        python=args.python,
        poll_seconds=args.poll_seconds,
        once=args.once,
        dry_run=args.dry_run,
        state_file=args.state_file,
        log_file=args.log_file,
    )
    try:
        if config.dry_run:
            status = Autorun(config).run()
        else:
            with FileLock(config.state_path.with_suffix(config.state_path.suffix + ".lock")):
                status = Autorun(config).run()
    except (AutorunError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL_AUTORUN", "error": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": status,
                "state_file": config.state_path.as_posix(),
                "log_file": config.log_path.as_posix(),
                "formal_eligible": False,
                "docking_gold_release_eligible": False,
                "training_label_release_eligible": False,
                "p2_training_ready": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if status in {REMOTE_FAILURE, STAGE_FAILURE} else 0


if __name__ == "__main__":
    raise SystemExit(main())
