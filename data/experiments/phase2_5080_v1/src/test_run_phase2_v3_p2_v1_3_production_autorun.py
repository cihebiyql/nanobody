#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import Sequence
from unittest import mock

from experiments.phase2_5080_v1.src import (
    run_phase2_v3_p2_v1_3_production_autorun as autorun,
)


def boundaries(*, include_p2: bool = True) -> dict[str, bool]:
    value = {
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
    }
    if include_p2:
        value["p2_training_ready"] = False
    return value


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: int) -> None:
    path.write_text("value\n" + "\n".join(str(index) for index in range(rows)) + "\n", encoding="utf-8")


def publish(root: Path, release_id: str, builder) -> Path:
    release = root / "releases" / release_id
    release.mkdir(parents=True, exist_ok=True)
    builder(release)
    root.mkdir(parents=True, exist_ok=True)
    current = root / "current"
    current.unlink(missing_ok=True)
    current.symlink_to(Path("releases") / release_id, target_is_directory=True)
    return release


class FixturePublisher:
    def __init__(self, layout: autorun.Layout, development_pass: bool = True) -> None:
        self.layout = layout
        self.development_pass = development_pass

    def selector(self, release_id: str = "selector-fixture") -> None:
        def build(release: Path) -> None:
            table = release / autorun.SELECTOR_CSV
            write_csv(table, 752)
            write_json(
                release / autorun.SELECTOR_AUDIT,
                {
                    "schema_version": (
                        "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v3"
                    ),
                    "status": "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED",
                    **boundaries(),
                    "protocol_id": autorun.PROTOCOL_ID,
                    "selection_backfill": False,
                    "docking_launched": False,
                    "scoring_performed": False,
                    "remote_local_hash_chain_equal": True,
                    "counts": {
                        "manifest_runs": 94,
                        "selected_runs": 94,
                        "selected_poses": 752,
                        "cases": 47,
                    },
                    "run_counts_by_receptor": {"8X6B": 47, "9E6Y": 47},
                    "pose_counts_by_receptor": {"8X6B": 376, "9E6Y": 376},
                    "run_counts_by_source_mode": {
                        "REUSE_OLD_PILOT64_MAIN": 64,
                        "NEW_DUAL_DOCKING_COMPLETION": 30,
                    },
                    "pose_counts_by_source_mode": {
                        "REUSE_OLD_PILOT64_MAIN": 512,
                        "NEW_DUAL_DOCKING_COMPLETION": 240,
                    },
                    "inputs": {
                        "execution_release_manifest": {
                            "sha256": (
                                "4a0f1a63ef3dc16220beb9d821db71e500d4e512195e7f19a3e112d1d7a2db21"
                            )
                        }
                    },
                    "source_inventories": {
                        name: {
                            "remote_local_hash_chain_equal": True,
                            "remote_file_hash_chain": "a" * 64,
                            "local_file_hash_chain": "a" * 64,
                        }
                        for name in (
                            "REUSE_OLD_PILOT64_MAIN",
                            "NEW_DUAL_DOCKING_COMPLETION",
                        )
                    },
                    "identity_gate_summary": {
                        "pose_count": 752,
                        "vhh_normalized_atom_identity_exact_count": 752,
                        "pvrig_raw_atom_identity_exact_count": 752,
                        "monomer_vhh_heavy_hetatm_identity_count_total": 0,
                        "receptor_pvrig_heavy_hetatm_identity_count_total": 0,
                        "pose_vhh_heavy_hetatm_identity_count_total": 0,
                        "pose_pvrig_heavy_hetatm_identity_count_total": 0,
                        "heavy_hetatm_zero_gate_pass_count": 752,
                        "coordinate_or_score_modified": False,
                    },
                    "pre_migration_completion_hashes": {
                        "required": dict(
                            sorted(autorun.FROZEN_PRE_MIGRATION_COMPLETIONS.items())
                        ),
                        "all_exact": True,
                    },
                    "selector": {
                        "sha256": autorun.sha256_file(
                            autorun.SCRIPT_DIR / autorun.SELECTOR_NAME
                        )
                    },
                    "output_csv": {
                        "sha256": autorun.sha256_file(table),
                        "rows": 752,
                    },
                },
            )

        publish(self.layout.selector, release_id, build)

    def processor(self, root: Path) -> None:
        def build(release: Path) -> None:
            metrics = release / autorun.PROCESSOR_METRICS
            write_csv(metrics, 752)
            write_json(
                release / autorun.PROCESSOR_AUDIT,
                {
                    "status": "BUILT_PENDING_DEVELOPMENT_RELEASE",
                    **boundaries(),
                    "primary_native_metric_eligible": False,
                    "observed_contract": {
                        "case_count": 47,
                        "run_count": 94,
                        "metric_rows": 752,
                        "contact_records": 752,
                        "aligned_pose_files": 752,
                    },
                    "output_sha256": {
                        "continuous_metrics": {"sha256": autorun.sha256_file(metrics)}
                    },
                },
            )

        publish(root, "native-fixture", build)

    def qualification(self) -> None:
        def build(release: Path) -> None:
            write_json(
                release / autorun.PROCESSOR_QUALIFICATION,
                {
                    "status": "QUALIFIED_NATIVE_PROCESSOR_INPUT",
                    **boundaries(),
                    "calibration_input_eligible": True,
                    "determinism": {
                        "independent_publication_count": 2,
                        "full_inventory_equal": True,
                        "core_output_hashes_equal": True,
                    },
                },
            )

        publish(self.layout.processor_qualification, "qualification-fixture", build)

    def calibration(self, root: Path) -> None:
        release_id = "calc-fixture"

        def build(release: Path) -> None:
            for name in autorun.CALIBRATION_TABLES:
                write_csv(release / name, 1)
            (release / autorun.CALIBRATION_REPORT).write_text("fixture\n", encoding="utf-8")
            write_json(
                release / autorun.CALIBRATION_RULES,
                {
                    "status": "CALCULATED_PENDING_RELEASE_VALIDATION",
                    **boundaries(),
                    "development_smoke_eligible": False,
                },
            )
            write_json(
                release / autorun.CALIBRATION_AUDIT,
                {
                    "status": "CALCULATED_PENDING_RELEASE_VALIDATION",
                    **boundaries(),
                    "development_smoke_eligible": False,
                    "computed_gate_outcome": (
                        "COMPUTED_GATES_SATISFIED"
                        if self.development_pass
                        else "COMPUTED_GATES_NOT_SATISFIED"
                    ),
                    "central_outputs": {
                        "pose_rows": 752,
                        "native_run_rows": 94,
                        "dual_candidate_rows": 47,
                    },
                },
            )
            write_json(
                release / autorun.CALIBRATION_INPUT,
                {
                    "status": "PENDING_EXTERNAL_RELEASE_VALIDATION",
                    "release_id": release_id,
                    **boundaries(),
                    "development_smoke_eligible": False,
                    "calibration_audit": {
                        "sha256": autorun.sha256_file(release / autorun.CALIBRATION_AUDIT)
                    },
                },
            )

        publish(root, release_id, build)

    def development(self) -> None:
        status = autorun.DEVELOPMENT_PASS if self.development_pass else autorun.DEVELOPMENT_FAIL

        def build(release: Path) -> None:
            write_json(
                release / autorun.DEVELOPMENT_RELEASE,
                {
                    "status": status,
                    **boundaries(),
                    "development_smoke_eligible": self.development_pass,
                    "training_state": "P2_TRAINING_BLOCKED",
                    "anchor_readiness": {
                        "new_eligible_independent_family_count": 0,
                        "unconditional_formal_veto": True,
                    },
                },
            )

        publish(self.layout.development_release, "development-fixture", build)


def snapshot(
    status: str,
    *,
    completion: int,
    passed: int,
    failure: int = 0,
    invalid: int = 0,
    alive: bool,
    failures: Sequence[str] = (),
    manifest_count: int = 30,
    manifest_sha256: str = autorun.FROZEN_NEW_RUN_MANIFEST_SHA256,
    observed_hostname: str = "fixture-node",
    observed_boot_id: str = "",
    controller_pid: int = autorun.FROZEN_CONTROLLER_PID,
    controller_start_ticks: int = autorun.FROZEN_CONTROLLER_START_TICKS,
) -> autorun.CommandResult:
    payload = {
        "status": status,
        "manifest_count": manifest_count,
        "completion_count": completion,
        "pass_count": passed,
        "failure_count": failure,
        "missing_count": 30 - completion,
        "invalid_count": invalid,
        "controller_alive": alive,
        "manifest_sha256": manifest_sha256,
        "controller_pid": controller_pid if alive else None,
        "controller_start_ticks": (
            controller_start_ticks if alive else None
        ),
        "controller_pid_file_valid": alive,
        "controller_identity_valid": alive,
        "controller_argv_sha256": "a" * 64 if alive else "",
        "observed_hostname": observed_hostname,
        "observed_boot_id": observed_boot_id,
        "host_identity_valid": True,
        "matching_controller_count": 1 if alive else 0,
        "matching_controller_pids": [controller_pid] if alive else [],
        "frozen_completion_hashes_valid": True,
        "observed_frozen_completion_sha256": dict(
            autorun.FROZEN_PRE_MIGRATION_COMPLETIONS
        ),
        "handoff_phase_hashes_valid": True,
        "observed_handoff_phase_sha256": dict(
            autorun.FROZEN_MIGRATION_PHASE_ARTIFACTS
        ),
        "failures": list(failures),
    }
    return autorun.CommandResult(0, json.dumps(payload) + "\n", "")


def retired_source_snapshot(*, count: int = 0) -> autorun.CommandResult:
    payload = {
        "status": (
            "PASS_RETIRED_SOURCE_ZERO_CONTROLLERS"
            if count == 0
            else "FAIL_RETIRED_SOURCE_GUARD"
        ),
        "observed_hostname": "node1",
        "observed_boot_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "matching_controller_count": count,
        "matching_controller_pids": list(range(9000, 9000 + count)),
    }
    return autorun.CommandResult(0, json.dumps(payload) + "\n", "")


def migration_run_ids() -> list[str]:
    completed = {
        "V13CAL_012__8X6B__main",
        "V13CAL_012__9E6Y__main",
        "V13CAL_047__8X6B__main",
        "V13CAL_047__9E6Y__main",
    }
    with frozen_manifest_path().open(newline="", encoding="utf-8-sig") as handle:
        return [
            row["run_id"]
            for row in csv.DictReader(handle)
            if row["run_id"] not in completed
        ]


def write_migration_receipt(path: Path) -> dict[str, object]:
    evidence = path.parent / "evidence"
    evidence.mkdir(exist_ok=True)
    preregistration = evidence / "preregistration.json"
    write_json(
        preregistration,
        {
            "schema_version": "pvrig_v1_3_controller_migration_preregistration_v1",
            "status": "PREREGISTERED_NODE1_TO_NODE23_SINGLE_WRITER_HANDOFF",
        },
    )
    predecessor = evidence / "predecessor.json"
    write_json(
        predecessor,
        {
            "schema_version": "pvrig_v1_3_production_autorun_state_v1",
            "status": autorun.WAITING,
            "protocol_id": autorun.PROTOCOL_ID,
            "remote_root": autorun.REMOTE_ROOT,
            **boundaries(),
            "stages": {},
            "remote_snapshot": {
                "completion_count": 4,
                "pass_count": 4,
                "failure_count": 0,
                "invalid_count": 0,
            },
        },
    )
    run_ids = migration_run_ids()
    pid = 765432
    argv = [
        autorun.FROZEN_CONTROLLER_PYTHON,
        "scripts/run_v1_3_completion15.py",
        "--root",
        autorun.REMOTE_ROOT,
        "--haddock-bin",
        autorun.FROZEN_HADDOCK_BIN,
        "--max-workers",
        "5",
        "--max-load1",
        "50",
        "--load-poll-seconds",
        "30",
    ]
    for run_id in run_ids:
        argv.extend(("--run-id", run_id))
    argv_bytes = b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
    payload: dict[str, object] = {
        "schema_version": autorun.MIGRATION_RECEIPT_SCHEMA,
        "status": autorun.MIGRATION_RECEIPT_STATUS,
        "protocol_id": autorun.PROTOCOL_ID,
        "remote_root": autorun.REMOTE_ROOT,
        "migration_generation": 2,
        **boundaries(),
        "claim_boundary": (
            "execution migration only; no binding, affinity, experimental blocking, "
            "Formal Gold, or training-label claim"
        ),
        "migration_preregistration": {
            "path": preregistration.relative_to(path.parent).as_posix(),
            "sha256": autorun.sha256_file(preregistration),
        },
        "predecessor_autorun_state": {
            "path": predecessor.relative_to(path.parent).as_posix(),
            "sha256": autorun.sha256_file(predecessor),
            "schema_version": "pvrig_v1_3_production_autorun_state_v1",
            "status": autorun.WAITING,
        },
        "single_writer_handoff": {
            "old_controller_stopped": True,
            "old_children_zero_after_sigstop": True,
            "old_descendants_zero_after_sigstop": True,
            "no_controller_overlap": True,
            "combined_active_controller_count": 1,
        },
        "frozen_contract": {
            "manifest_sha256": autorun.FROZEN_NEW_RUN_MANIFEST_SHA256,
            "controller_script_sha256": autorun.FROZEN_CONTROLLER_SCRIPT_SHA256,
            "python_sha256": autorun.FROZEN_CONTROLLER_PYTHON_SHA256,
            "haddock_sha256": autorun.FROZEN_HADDOCK_SHA256,
            "max_workers": 5,
            "max_load1": 50,
            "load_poll_seconds": 30,
        },
        "pre_handoff_completion_ledger": {
            "count": 4,
            "files": dict(sorted(autorun.FROZEN_PRE_MIGRATION_COMPLETIONS.items())),
        },
        "post_handoff_completion_ledger": {
            "count": 4,
            "files": dict(sorted(autorun.FROZEN_PRE_MIGRATION_COMPLETIONS.items())),
        },
        "remaining_run_ledger": {
            "count": 26,
            "run_ids": run_ids,
            "run_ids_sha256": autorun.FROZEN_NODE23_REMAINING_RUN_IDS_SHA256,
        },
        "target_controller": {
            "host": "node23",
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "pid": pid,
            "pid_file_sha256": autorun.sha256_bytes(f"{pid}\n".encode("ascii")),
            "start_ticks": 123456789,
            "python": autorun.FROZEN_CONTROLLER_PYTHON,
            "haddock_bin": autorun.FROZEN_HADDOCK_BIN,
            "argv": argv,
            "argv_bytes_sha256": autorun.sha256_bytes(argv_bytes),
            "cwd": autorun.REMOTE_ROOT,
            "executable": "/data/qlyu/anaconda3/envs/haddock3/bin/python3.11",
        },
        "source_controller": {
            "host": "node1",
            "boot_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "pid": autorun.FROZEN_CONTROLLER_PID,
            "pid_file_sha256": autorun.FROZEN_CONTROLLER_PID_SHA256,
            "start_ticks": autorun.FROZEN_CONTROLLER_START_TICKS,
            "argv": list(autorun.legacy_controller_contract("node1").argv),
            "cwd": autorun.REMOTE_ROOT,
            "executable": "/data/qlyu/anaconda3/envs/haddock3/bin/python3.11",
            "retired": True,
        },
        "source_probe": {
            "host": "node1",
            "boot_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "active_controller_count": 0,
        },
        "target_probe": {
            "host": "node23",
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "active_controller_count": 1,
        },
        "shared_handoff_phase_artifacts": {
            "phase_old_frozen.json": {
                "sha256": autorun.FROZEN_MIGRATION_PHASE_ARTIFACTS[
                    "phase_old_frozen.json"
                ],
                "status": "OLD_CONTROLLER_FROZEN_ZERO_CHILDREN",
            },
            "phase_old_retired.json": {
                "sha256": autorun.FROZEN_MIGRATION_PHASE_ARTIFACTS[
                    "phase_old_retired.json"
                ],
                "status": "OLD_CONTROLLER_RETIRED_NO_ROLLBACK",
            },
            "phase_new_active.json": {
                "sha256": autorun.FROZEN_MIGRATION_PHASE_ARTIFACTS[
                    "phase_new_active.json"
                ],
                "status": "NEW_NODE23_CONTROLLER_ACTIVE_FILTERED_26",
            },
        },
    }
    write_json(path, payload)
    return payload


def frozen_manifest_path() -> Path:
    return (
        autorun.EXP_DIR
        / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_completion15_package/"
        "manifests/new_run_manifest.csv"
    )


def create_fake_controller(remote_root: Path, proc_root: Path) -> None:
    (remote_root / "controller_full.pid").write_text(
        f"{autorun.FROZEN_CONTROLLER_PID}\n", encoding="ascii"
    )
    proc = proc_root / str(autorun.FROZEN_CONTROLLER_PID)
    proc.mkdir(parents=True, exist_ok=True)
    argv = [
        autorun.FROZEN_CONTROLLER_PYTHON,
        "scripts/run_v1_3_completion15.py",
        "--root",
        remote_root.resolve().as_posix(),
        "--haddock-bin",
        autorun.FROZEN_HADDOCK_BIN,
        "--max-workers",
        "5",
        "--max-load1",
        "50",
        "--load-poll-seconds",
        "30",
    ]
    (proc / "cmdline").write_bytes(
        b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
    )
    stat_fields = ["S", *("0" for _ in range(18)), str(autorun.FROZEN_CONTROLLER_START_TICKS)]
    (proc / "stat").write_text(
        f"{autorun.FROZEN_CONTROLLER_PID} (python) "
        + " ".join(stat_fields)
        + "\n",
        encoding="ascii",
    )
    (proc / "cwd").symlink_to(remote_root.resolve(), target_is_directory=True)
    (proc / "exe").symlink_to(autorun.FROZEN_CONTROLLER_PYTHON)


def create_remote_probe_fixture(base: Path) -> tuple[Path, Path]:
    remote_root = base / "remote"
    proc_root = base / "proc"
    (remote_root / "manifests").mkdir(parents=True)
    (remote_root / "runs").mkdir()
    proc_root.mkdir()
    shutil.copyfile(
        frozen_manifest_path(), remote_root / "manifests/new_run_manifest.csv"
    )
    create_fake_controller(remote_root, proc_root)
    return remote_root, proc_root


def execute_remote_probe(
    remote_root: Path,
    proc_root: Path,
    contract: autorun.ControllerContract | None = None,
) -> dict[str, object]:
    if contract is None:
        base = autorun.legacy_controller_contract(os.uname().nodename)
        argv = list(base.argv)
        argv[argv.index("--root") + 1] = remote_root.resolve().as_posix()
        contract = replace(base, argv=tuple(argv))
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            autorun.remote_probe_script(contract),
            str(remote_root),
            str(proc_root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout.splitlines()[-1])


class FakeRunner:
    def __init__(
        self,
        layout: autorun.Layout,
        remote_results: Sequence[autorun.CommandResult],
        *,
        fail_stage: str | None = None,
        development_pass: bool = True,
    ) -> None:
        self.layout = layout
        self.remote_results = list(remote_results)
        self.fail_stage = fail_stage
        self.publisher = FixturePublisher(layout, development_pass)
        self.commands: list[tuple[str, ...]] = []
        self.stage_names: list[str] = []

    def __call__(self, command: Sequence[str], _cwd: Path) -> autorun.CommandResult:
        command = tuple(command)
        self.commands.append(command)
        if command[0].endswith("ssh.exe") or command[0] == "fake-ssh":
            if not self.remote_results:
                raise AssertionError("Unexpected extra remote probe")
            return self.remote_results.pop(0)
        script = Path(command[1]).name
        if script == autorun.SELECTOR_NAME:
            stage = "selector"
            action = self.publisher.selector
        elif script == autorun.PROCESSOR_NAME:
            if "--outdir" in command:
                stage = "processor_rebuild"
                action = lambda: self.publisher.processor(self.layout.processor_rebuild)
            else:
                stage = "processor_primary"
                action = lambda: self.publisher.processor(self.layout.processor_primary)
        elif script == autorun.PROCESSOR_QUALIFIER_NAME:
            stage = "processor_qualification"
            action = self.publisher.qualification
        elif script == autorun.CALIBRATOR_NAME:
            if "--outdir" in command:
                stage = "calibration_rebuild"
                action = lambda: self.publisher.calibration(self.layout.calibration_rebuild)
            else:
                stage = "calibration_primary"
                action = lambda: self.publisher.calibration(self.layout.calibration_primary)
        elif script == autorun.DEVELOPMENT_VALIDATOR_NAME:
            stage = "development_release"
            action = self.publisher.development
        else:
            raise AssertionError(f"Unexpected command: {command}")
        self.stage_names.append(stage)
        if stage == self.fail_stage:
            return autorun.CommandResult(17, "", "fixture failure")
        action()
        return autorun.CommandResult(0, json.dumps({"stage": stage}), "")


class AutorunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.layout = autorun.Layout(self.root)
        self.layout.src.mkdir(parents=True)
        for name in {
            autorun.SELECTOR_NAME,
            autorun.PROCESSOR_NAME,
            autorun.PROCESSOR_QUALIFIER_NAME,
            autorun.CALIBRATOR_NAME,
            autorun.DEVELOPMENT_VALIDATOR_NAME,
        }:
            (self.layout.src / name).write_text(
                f"# fixture implementation: {name}\n", encoding="utf-8"
            )
        self.state = self.root / "state.json"
        self.log = self.root / "events.jsonl"

    def config(self, **updates) -> autorun.Config:
        values = {
            "layout": self.layout,
            "ssh_executable": "fake-ssh",
            "host": "fixture-node",
            "python": "/fixture/python",
            "poll_seconds": 0.01,
            "once": True,
            "state_file": self.state,
            "log_file": self.log,
        }
        values.update(updates)
        return autorun.Config(**values)

    def test_once_waits_without_running_local_stages(self) -> None:
        runner = FakeRunner(
            self.layout,
            [snapshot("WAITING", completion=7, passed=7, alive=True)],
        )
        status = autorun.Autorun(self.config(), runner=runner).run()
        self.assertEqual(status, autorun.WAITING)
        self.assertEqual(runner.stage_names, [])
        self.assertEqual(json.loads(self.state.read_text())["status"], autorun.WAITING)

    def test_controller_death_stops_fail_closed(self) -> None:
        runner = FakeRunner(
            self.layout,
            [
                snapshot(
                    "FAILURE",
                    completion=7,
                    passed=7,
                    alive=False,
                    failures=("controller_not_alive_with_pending_runs",),
                )
            ],
        )
        status = autorun.Autorun(self.config(), runner=runner).run()
        self.assertEqual(status, autorun.REMOTE_FAILURE)
        self.assertEqual(runner.stage_names, [])

    def test_explicit_manifest_failure_precedes_count_gate_and_once_is_nonzero(self) -> None:
        result = snapshot(
            "FAILURE",
            completion=0,
            passed=0,
            failure=1,
            invalid=1,
            alive=False,
            failures=("manifest_unreadable_or_malformed",),
            manifest_count=0,
            manifest_sha256="",
        )
        parsed = autorun.parse_remote_result(result)
        self.assertEqual(parsed.status, "FAILURE")
        self.assertEqual(parsed.manifest_count, 0)

        def fake_subprocess(_command: Sequence[str], _cwd: Path) -> autorun.CommandResult:
            return result

        with mock.patch.object(autorun, "subprocess_runner", fake_subprocess):
            with redirect_stdout(io.StringIO()):
                returncode = autorun.main(
                    [
                        "--once",
                        "--ssh-executable",
                        "fake-ssh",
                        "--state-file",
                        str(self.state),
                        "--log-file",
                        str(self.log),
                    ]
                )
        self.assertEqual(returncode, 2)
        self.assertEqual(
            json.loads(self.state.read_text())["status"], autorun.REMOTE_FAILURE
        )

    def test_remote_probe_requires_frozen_pid_and_exact_proc_identity(self) -> None:
        remote, proc = create_remote_probe_fixture(self.root / "probe-valid")
        valid = execute_remote_probe(remote, proc)
        self.assertEqual(valid["status"], "WAITING")
        self.assertTrue(valid["controller_pid_file_valid"])
        self.assertTrue(valid["controller_identity_valid"])
        self.assertEqual(valid["controller_pid"], autorun.FROZEN_CONTROLLER_PID)
        self.assertEqual(
            valid["controller_start_ticks"], autorun.FROZEN_CONTROLLER_START_TICKS
        )

        for variant in ("missing_pid", "dead_pid", "argv", "cwd", "start"):
            with self.subTest(variant=variant):
                remote, proc = create_remote_probe_fixture(self.root / f"probe-{variant}")
                proc_dir = proc / str(autorun.FROZEN_CONTROLLER_PID)
                if variant == "missing_pid":
                    (remote / "controller_full.pid").unlink()
                elif variant == "dead_pid":
                    shutil.rmtree(proc_dir)
                elif variant == "argv":
                    (proc_dir / "cmdline").write_bytes(b"python\0wrong.py\0")
                elif variant == "cwd":
                    (proc_dir / "cwd").unlink()
                    (proc_dir / "cwd").symlink_to(self.root.resolve(), target_is_directory=True)
                else:
                    stat_fields = ["S", *("0" for _ in range(18)), "1"]
                    (proc_dir / "stat").write_text(
                        f"{autorun.FROZEN_CONTROLLER_PID} (python) "
                        + " ".join(stat_fields)
                        + "\n",
                        encoding="ascii",
                    )
                observed = execute_remote_probe(remote, proc)
                self.assertEqual(observed["status"], "FAILURE")
                self.assertIn(
                    "controller_not_alive_with_pending_runs", observed["failures"]
                )

    def test_remote_probe_rejects_host_and_boot_identity_drift(self) -> None:
        for variant in ("host", "boot"):
            with self.subTest(variant=variant):
                remote, proc = create_remote_probe_fixture(self.root / f"probe-{variant}")
                base = autorun.legacy_controller_contract(os.uname().nodename)
                argv = list(base.argv)
                argv[argv.index("--root") + 1] = remote.resolve().as_posix()
                contract = replace(base, argv=tuple(argv))
                if variant == "host":
                    contract = replace(contract, host="not-this-host")
                else:
                    contract = replace(
                        contract,
                        boot_id="00000000-0000-0000-0000-000000000000",
                    )
                observed = execute_remote_probe(remote, proc, contract)
                self.assertEqual(observed["status"], "FAILURE")
                self.assertIn(
                    "remote_host_or_boot_identity_mismatch", observed["failures"]
                )

    def test_remote_probe_rejects_second_unregistered_controller(self) -> None:
        remote, proc = create_remote_probe_fixture(self.root / "probe-duplicate")
        source = proc / str(autorun.FROZEN_CONTROLLER_PID)
        duplicate = proc / "4059963"
        shutil.copytree(source, duplicate, symlinks=True)
        observed = execute_remote_probe(remote, proc)
        self.assertEqual(observed["status"], "FAILURE")
        self.assertEqual(observed["matching_controller_count"], 2)
        self.assertIn("4059963", ",".join(observed["failures"]))

    def test_remote_probe_rejects_absolute_path_duplicate_controller(self) -> None:
        remote, proc = create_remote_probe_fixture(
            self.root / "probe-absolute-duplicate"
        )
        source = proc / str(autorun.FROZEN_CONTROLLER_PID)
        duplicate = proc / "4059963"
        shutil.copytree(source, duplicate, symlinks=True)
        argv = [
            value.decode("utf-8")
            for value in (duplicate / "cmdline").read_bytes().split(b"\0")
            if value
        ]
        argv[1] = (remote / "scripts/run_v1_3_completion15.py").as_posix()
        (duplicate / "cmdline").write_bytes(
            b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
        )
        observed = execute_remote_probe(remote, proc)
        self.assertEqual(observed["status"], "FAILURE")
        self.assertEqual(observed["matching_controller_count"], 2)
        self.assertIn("4059963", ",".join(observed["failures"]))

    def test_remote_probe_rejects_root_equivalents_and_default_duplicate(self) -> None:
        for variant in ("absolute_alias", "relative", "default"):
            with self.subTest(variant=variant):
                remote, proc = create_remote_probe_fixture(
                    self.root / f"probe-root-{variant}"
                )
                source = proc / str(autorun.FROZEN_CONTROLLER_PID)
                duplicate = proc / "4059963"
                shutil.copytree(source, duplicate, symlinks=True)
                argv = [
                    value.decode("utf-8")
                    for value in (duplicate / "cmdline").read_bytes().split(b"\0")
                    if value
                ]
                root_index = argv.index("--root")
                if variant == "default":
                    del argv[root_index : root_index + 2]
                elif variant == "absolute_alias":
                    root_value = (remote / ".." / remote.name).as_posix()
                    argv[root_index : root_index + 2] = [f"--root={root_value}"]
                else:
                    root_value = "."
                    argv[root_index : root_index + 2] = [f"--root={root_value}"]
                (duplicate / "cmdline").write_bytes(
                    b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
                )
                observed = execute_remote_probe(remote, proc)
                self.assertEqual(observed["status"], "FAILURE")
                self.assertEqual(observed["matching_controller_count"], 2)
                self.assertIn("4059963", ",".join(observed["failures"]))

    def test_remote_probe_recomputes_frozen_completion_hashes(self) -> None:
        remote, proc = create_remote_probe_fixture(self.root / "probe-completion")
        with (remote / "manifests/new_run_manifest.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            row = next(csv.DictReader(handle))
        completion = remote / row["completion_relpath"]
        completion.parent.mkdir(parents=True)
        write_json(
            completion,
            {
                "protocol_id": autorun.PROTOCOL_ID,
                "run_id": row["run_id"],
                "config_sha256": row["config_sha256"],
                "status": autorun.REMOTE_PASS_STATUS,
                "exit_code": 0,
            },
        )
        expected = {
            completion.relative_to(remote).as_posix(): autorun.sha256_file(completion)
        }
        base = autorun.legacy_controller_contract(os.uname().nodename)
        argv = list(base.argv)
        argv[argv.index("--root") + 1] = remote.resolve().as_posix()
        contract = replace(base, argv=tuple(argv), source="migration-test")
        with mock.patch.object(
            autorun, "FROZEN_PRE_MIGRATION_COMPLETIONS", expected
        ):
            valid = execute_remote_probe(remote, proc, contract)
            self.assertEqual(valid["status"], "WAITING")
            self.assertTrue(valid["frozen_completion_hashes_valid"])
            rewritten = json.loads(completion.read_text(encoding="utf-8"))
            rewritten["rewritten_without_semantic_change"] = True
            write_json(completion, rewritten)
            invalid = execute_remote_probe(remote, proc, contract)
        self.assertEqual(invalid["status"], "FAILURE")
        self.assertIn(
            "frozen_completion_receipt_hash_mismatch", invalid["failures"]
        )

    def test_retired_source_guard_rejects_restarted_controller(self) -> None:
        proc = self.root / "retired-proc"
        proc.mkdir()
        contract = replace(
            autorun.legacy_controller_contract(os.uname().nodename),
            retired_host=os.uname().nodename,
            retired_boot_id=Path(
                "/proc/sys/kernel/random/boot_id"
            ).read_text(encoding="ascii").strip(),
        )

        def execute() -> autorun.CommandResult:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    autorun.retired_source_probe_script(contract),
                    str(proc),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            return autorun.CommandResult(
                completed.returncode, completed.stdout, completed.stderr
            )

        self.assertEqual(
            autorun.validate_retired_source_result(execute(), contract)["status"],
            "PASS_RETIRED_SOURCE_ZERO_CONTROLLERS",
        )
        fake = proc / "12345"
        fake.mkdir()
        argv = list(contract.argv)
        (fake / "cmdline").write_bytes(
            b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
        )
        with self.assertRaisesRegex(autorun.AutorunError, "zero matching"):
            autorun.validate_retired_source_result(execute(), contract)

        shutil.rmtree(fake)
        absolute = proc / "12346"
        absolute.mkdir()
        argv = list(contract.argv)
        argv[1] = f"{autorun.REMOTE_ROOT}/scripts/run_v1_3_completion15.py"
        (absolute / "cmdline").write_bytes(
            b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
        )
        with self.assertRaisesRegex(autorun.AutorunError, "zero matching"):
            autorun.validate_retired_source_result(execute(), contract)

        shutil.rmtree(absolute)
        root_equals = proc / "12347"
        root_equals.mkdir()
        argv = list(contract.argv)
        argv[1] = f"{autorun.REMOTE_ROOT}/scripts/run_v1_3_completion15.py"
        root_index = argv.index("--root")
        root_alias = (
            Path(autorun.REMOTE_ROOT) / ".." / Path(autorun.REMOTE_ROOT).name
        ).as_posix()
        argv[root_index : root_index + 2] = [f"--root={root_alias}"]
        (root_equals / "cmdline").write_bytes(
            b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
        )
        with self.assertRaisesRegex(autorun.AutorunError, "zero matching"):
            autorun.validate_retired_source_result(execute(), contract)

        shutil.rmtree(root_equals)
        default_root = proc / "12348"
        default_root.mkdir()
        argv = list(contract.argv)
        argv[1] = f"{autorun.REMOTE_ROOT}/scripts/run_v1_3_completion15.py"
        root_index = argv.index("--root")
        del argv[root_index : root_index + 2]
        (default_root / "cmdline").write_bytes(
            b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
        )
        with self.assertRaisesRegex(autorun.AutorunError, "zero matching"):
            autorun.validate_retired_source_result(execute(), contract)

    def test_migration_receipt_binds_exact_node23_remaining_run_controller(self) -> None:
        receipt = self.root / "migration.json"
        payload = write_migration_receipt(receipt)
        with mock.patch.object(
            autorun,
            "FROZEN_NODE23_MIGRATION_RECEIPT_SHA256",
            autorun.sha256_file(receipt),
        ), mock.patch.object(
            autorun,
            "FROZEN_NODE23_MIGRATION_PREREGISTRATION_SHA256",
            payload["migration_preregistration"]["sha256"],
        ):
            contract = autorun.load_controller_contract(
                receipt, "node23", self.root
            )
        self.assertEqual(contract.host, "node23")
        self.assertEqual(contract.argv.count("--run-id"), 26)
        self.assertEqual(
            list(contract.argv)[-2:], ["--run-id", migration_run_ids()[-1]]
        )
        self.assertRegex(contract.source_sha256, r"^[0-9a-f]{64}$")

    def test_migration_receipt_rejects_host_ledger_and_single_writer_drift(self) -> None:
        mutations = {
            "host": lambda payload: payload["target_controller"].update(host="node25"),
            "run_order": lambda payload: payload["remaining_run_ledger"][
                "run_ids"
            ].reverse(),
            "completion": lambda payload: payload["post_handoff_completion_ledger"][
                "files"
            ].pop(next(iter(autorun.FROZEN_PRE_MIGRATION_COMPLETIONS))),
            "single_writer": lambda payload: payload["single_writer_handoff"].update(
                no_controller_overlap=False
            ),
            "unfiltered": lambda payload: payload["target_controller"].update(
                argv=payload["target_controller"]["argv"][:12]
            ),
            "missing_preregistration": lambda payload: payload.pop(
                "migration_preregistration"
            ),
            "missing_predecessor": lambda payload: payload.pop(
                "predecessor_autorun_state"
            ),
            "missing_source_probe": lambda payload: payload.pop("source_probe"),
            "missing_phase_artifacts": lambda payload: payload.pop(
                "shared_handoff_phase_artifacts"
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                receipt = self.root / f"migration-{name}.json"
                payload = write_migration_receipt(receipt)
                mutation(payload)
                write_json(receipt, payload)
                with mock.patch.object(
                    autorun,
                    "FROZEN_NODE23_MIGRATION_RECEIPT_SHA256",
                    autorun.sha256_file(receipt),
                ), mock.patch.object(
                    autorun,
                    "FROZEN_NODE23_MIGRATION_PREREGISTRATION_SHA256",
                    (
                        payload.get("migration_preregistration", {}).get("sha256")
                        or autorun.sha256_file(
                            self.root / "evidence/preregistration.json"
                        )
                    ),
                ):
                    with self.assertRaises(autorun.AutorunError):
                        autorun.load_controller_contract(
                            receipt, "node23", self.root
                        )

    def test_migration_receipt_hash_is_part_of_state_resume_contract(self) -> None:
        receipt = self.root / "migration-state.json"
        payload = write_migration_receipt(receipt)
        config = self.config(host="node23", controller_receipt=receipt)
        runner = FakeRunner(
            self.layout,
            [
                retired_source_snapshot(),
                snapshot(
                    "WAITING",
                    completion=4,
                    passed=4,
                    alive=True,
                    observed_hostname="node23",
                    observed_boot_id=payload["target_controller"]["boot_id"],
                    controller_pid=payload["target_controller"]["pid"],
                    controller_start_ticks=payload["target_controller"]["start_ticks"],
                )
            ],
        )
        receipt_sha = autorun.sha256_file(receipt)
        prereg_sha = payload["migration_preregistration"]["sha256"]
        with mock.patch.object(
            autorun, "FROZEN_NODE23_MIGRATION_RECEIPT_SHA256", receipt_sha
        ), mock.patch.object(
            autorun,
            "FROZEN_NODE23_MIGRATION_PREREGISTRATION_SHA256",
            prereg_sha,
        ):
            self.assertEqual(
                autorun.Autorun(config, runner=runner).run(), autorun.WAITING
            )
            payload["operator_note"] = "byte drift"
            write_json(receipt, payload)
            with self.assertRaisesRegex(autorun.AutorunError, "receipt SHA256"):
                autorun.Autorun(config, runner=runner)

    def test_remote_probe_rejects_manifest_hash_duplicates_and_unsafe_paths(self) -> None:
        def rewrite(remote: Path, mutation) -> None:
            manifest = remote / "manifests/new_run_manifest.csv"
            with manifest.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fields = list(reader.fieldnames or [])
            mutation(rows)
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

        def symlink_escape(remote: Path) -> None:
            (remote / "escape").symlink_to(self.root.resolve(), target_is_directory=True)
            rewrite(
                remote,
                lambda rows: rows[0].update(completion_relpath="escape/out.json"),
            )

        cases = {
            "hash": (
                lambda remote: (remote / "manifests/new_run_manifest.csv").write_bytes(
                    frozen_manifest_path().read_bytes() + b"\n"
                ),
                "manifest_sha256_mismatch",
            ),
            "duplicate_ids": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[1].update(
                        run_id=rows[0]["run_id"],
                    ),
                ),
                "manifest_run_ids_not_30_unique",
            ),
            "duplicate_configs": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[1].update(
                        config_sha256=rows[0]["config_sha256"],
                    ),
                ),
                "manifest_config_hashes_not_30_unique_sha256",
            ),
            "escape": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[0].update(completion_relpath="../escape.json"),
                ),
                "manifest_completion_path_unsafe_row_2",
            ),
            "absolute": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[0].update(completion_relpath="/tmp/escape.json"),
                ),
                "manifest_completion_path_unsafe_row_2",
            ),
            "duplicate_path": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[1].update(
                        completion_relpath=rows[0]["completion_relpath"]
                    ),
                ),
                "manifest_completion_paths_not_30_unique",
            ),
            "non_normalized": (
                lambda remote: rewrite(
                    remote,
                    lambda rows: rows[0].update(
                        completion_relpath="runs//not-normalized.complete.json"
                    ),
                ),
                "manifest_completion_path_unsafe_row_2",
            ),
            "symlink_escape": (
                symlink_escape,
                "manifest_completion_path_unsafe_row_2",
            ),
        }
        for name, (mutation, expected_failure) in cases.items():
            with self.subTest(name=name):
                remote, proc = create_remote_probe_fixture(self.root / f"manifest-{name}")
                mutation(remote)
                payload = execute_remote_probe(remote, proc)
                self.assertEqual(payload["status"], "FAILURE")
                self.assertIn(expected_failure, payload["failures"])

        remote, proc = create_remote_probe_fixture(self.root / "manifest-missing")
        (remote / "manifests/new_run_manifest.csv").unlink()
        missing = execute_remote_probe(remote, proc)
        self.assertEqual(missing["status"], "FAILURE")
        self.assertTrue(
            any(value.startswith("manifest_unreadable_or_malformed:") for value in missing["failures"])
        )

        remote, proc = create_remote_probe_fixture(self.root / "manifest-malformed")
        (remote / "manifests/new_run_manifest.csv").write_bytes(b"\xff\xfe\x00")
        malformed = execute_remote_probe(remote, proc)
        self.assertEqual(malformed["status"], "FAILURE")
        self.assertTrue(
            any(
                value.startswith("manifest_unreadable_or_malformed:")
                for value in malformed["failures"]
            )
        )

    def test_stage_failure_stops_before_downstream(self) -> None:
        runner = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            fail_stage="processor_primary",
        )
        status = autorun.Autorun(self.config(), runner=runner).run()
        self.assertEqual(status, autorun.STAGE_FAILURE)
        self.assertEqual(runner.stage_names, ["selector", "processor_primary"])
        state = json.loads(self.state.read_text())
        self.assertEqual(state["failed_stage"], "processor_primary")
        self.assertEqual(state["stages"]["processor_primary"]["returncode"], 17)

    def test_resume_reuses_only_hash_validated_immutable_stage(self) -> None:
        first = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            fail_stage="processor_primary",
        )
        self.assertEqual(
            autorun.Autorun(self.config(), runner=first).run(), autorun.STAGE_FAILURE
        )
        second = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            fail_stage="processor_primary",
        )
        self.assertEqual(
            autorun.Autorun(self.config(), runner=second).run(), autorun.STAGE_FAILURE
        )
        self.assertEqual(second.stage_names, ["processor_primary"])
        receipt = json.loads(self.state.read_text())["stages"]["selector"]
        self.assertEqual(receipt["status"], "REUSED")
        self.assertEqual(receipt["artifacts"]["file_count"], 2)

        (self.layout.selector / "current" / autorun.SELECTOR_CSV).write_text(
            "tampered\n", encoding="utf-8"
        )
        third = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            fail_stage="processor_primary",
        )
        self.assertEqual(
            autorun.Autorun(self.config(), runner=third).run(), autorun.STAGE_FAILURE
        )
        self.assertEqual(third.stage_names, ["selector", "processor_primary"])

    def test_full_pass_uses_exact_current_wiring_and_no_downstream_commands(self) -> None:
        runner = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            development_pass=True,
        )
        status = autorun.Autorun(self.config(), runner=runner).run()
        self.assertEqual(status, autorun.FINAL_PASS)
        self.assertEqual(
            runner.stage_names,
            [
                "selector",
                "processor_primary",
                "processor_rebuild",
                "processor_qualification",
                "calibration_primary",
                "calibration_rebuild",
                "development_release",
            ],
        )
        stages = autorun.build_stages(self.config())
        self.assertEqual(runner.commands[1:], [stage.command for stage in stages])
        qualifier = stages[3].command
        self.assertEqual(
            qualifier[qualifier.index("--primary-audit") + 1],
            str(self.layout.processor_primary / "current" / autorun.PROCESSOR_AUDIT),
        )
        self.assertEqual(
            qualifier[qualifier.index("--rebuild-audit") + 1],
            str(self.layout.processor_rebuild / "current" / autorun.PROCESSOR_AUDIT),
        )
        release = stages[-1].command
        self.assertEqual(
            release[release.index("--primary-release-input") + 1],
            str(self.layout.calibration_primary / "current" / autorun.CALIBRATION_INPUT),
        )
        self.assertEqual(
            release[release.index("--rebuild-release-input") + 1],
            str(self.layout.calibration_rebuild / "current" / autorun.CALIBRATION_INPUT),
        )
        invoked_scripts = {Path(command[1]).name for command in runner.commands[1:]}
        self.assertEqual(
            invoked_scripts,
            {
                autorun.SELECTOR_NAME,
                autorun.PROCESSOR_NAME,
                autorun.PROCESSOR_QUALIFIER_NAME,
                autorun.CALIBRATOR_NAME,
                autorun.DEVELOPMENT_VALIDATOR_NAME,
            },
        )
        self.assertFalse(any("smoke" in item.lower() for command in runner.commands for item in command))
        self.assertFalse(any("regression" in item.lower() for command in runner.commands for item in command))
        state = json.loads(self.state.read_text())
        self.assertFalse(state["formal_eligible"])
        self.assertFalse(state["docking_gold_release_eligible"])
        self.assertFalse(state["training_label_release_eligible"])
        self.assertFalse(state["p2_training_ready"])
        for receipt in state["stages"].values():
            self.assertEqual(receipt["returncode"], 0)
            self.assertRegex(receipt["artifacts"]["inventory_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            set(state["stages"]["development_release"]["upstreams"]),
            {
                "selector",
                "processor_primary",
                "processor_qualification",
                "calibration_primary",
                "calibration_rebuild",
            },
        )
        for binding in state["stages"]["development_release"]["upstreams"].values():
            self.assertEqual(
                set(binding),
                {
                    "root",
                    "current_target",
                    "current_resolved",
                    "release_id",
                    "file_count",
                    "inventory_sha256",
                },
            )

    def test_valid_selector_republication_invalidates_all_descendants(self) -> None:
        first = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            development_pass=True,
        )
        self.assertEqual(
            autorun.Autorun(self.config(), runner=first).run(), autorun.FINAL_PASS
        )
        FixturePublisher(self.layout, True).selector("selector-republished")
        second = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            development_pass=True,
        )
        self.assertEqual(
            autorun.Autorun(self.config(), runner=second).run(), autorun.FINAL_PASS
        )
        self.assertEqual(
            second.stage_names,
            [
                "selector",
                "processor_primary",
                "processor_rebuild",
                "processor_qualification",
                "calibration_primary",
                "calibration_rebuild",
                "development_release",
            ],
        )

    def test_release_inventory_rejects_internal_symlinks(self) -> None:
        FixturePublisher(self.layout).selector()
        release = (self.layout.selector / "current").resolve()
        (release / "internal-link").symlink_to(autorun.SELECTOR_CSV)
        with self.assertRaisesRegex(autorun.AutorunError, "internal symlinks"):
            autorun.release_inventory(self.layout.selector, autorun.SELECTOR_AUDIT)

    def test_selector_validator_rejects_p2_boundary_and_semantic_drift(self) -> None:
        for field, value in (
            ("p2_training_ready", True),
            ("selection_backfill", True),
            ("remote_local_hash_chain_equal", False),
        ):
            with self.subTest(field=field):
                root = self.root / f"selector-{field}"
                layout = autorun.Layout(root)
                layout.src.mkdir(parents=True)
                (layout.src / autorun.SELECTOR_NAME).write_text(
                    "# selector fixture\n", encoding="utf-8"
                )
                FixturePublisher(layout).selector()
                audit_path = layout.selector / "current" / autorun.SELECTOR_AUDIT
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                audit[field] = value
                write_json(audit_path, audit)
                with self.assertRaises(autorun.AutorunError):
                    autorun.validate_selector(layout.selector / "current")

    def test_development_gate_fail_is_valid_terminal_stop(self) -> None:
        runner = FakeRunner(
            self.layout,
            [snapshot("READY", completion=30, passed=30, alive=False)],
            development_pass=False,
        )
        status = autorun.Autorun(self.config(), runner=runner).run()
        self.assertEqual(status, autorun.FINAL_FAIL)
        state = json.loads(self.state.read_text())
        self.assertFalse(state["development_smoke_eligible"])
        self.assertTrue(state["formal_blocked_by_anchor_panel"])

    def test_dry_run_has_no_side_effects_and_exposes_full_command_plan(self) -> None:
        config = self.config(dry_run=True)

        def forbidden_runner(_command: Sequence[str], _cwd: Path) -> autorun.CommandResult:
            raise AssertionError("dry-run executed a command")

        with redirect_stdout(io.StringIO()) as output:
            status = autorun.Autorun(config, runner=forbidden_runner).run()
        self.assertEqual(status, "DRY_RUN_ONLY")
        self.assertIn('"automatic_smoke_or_formal_commands": false', output.getvalue())
        self.assertFalse(self.state.exists())
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
