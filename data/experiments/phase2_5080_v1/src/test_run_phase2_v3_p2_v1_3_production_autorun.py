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
                    "status": "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED",
                    **boundaries(include_p2=False),
                    "counts": {
                        "manifest_runs": 94,
                        "selected_runs": 94,
                        "selected_poses": 752,
                        "cases": 47,
                    },
                    "output_csv": {"sha256": autorun.sha256_file(table)},
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
        "controller_pid": autorun.FROZEN_CONTROLLER_PID if alive else None,
        "controller_start_ticks": (
            autorun.FROZEN_CONTROLLER_START_TICKS if alive else None
        ),
        "controller_pid_file_valid": alive,
        "controller_identity_valid": alive,
        "controller_argv_sha256": "a" * 64 if alive else "",
        "observed_hostname": "fixture-node",
        "observed_boot_id": "",
        "host_identity_valid": True,
        "failures": list(failures),
    }
    return autorun.CommandResult(0, json.dumps(payload) + "\n", "")


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


def execute_remote_probe(remote_root: Path, proc_root: Path) -> dict[str, object]:
    base = autorun.legacy_controller_contract(os.uname().nodename)
    argv = list(base.argv)
    argv[argv.index("--root") + 1] = remote_root.resolve().as_posix()
    contract = autorun.ControllerContract(
        host=base.host,
        boot_id=base.boot_id,
        pid=base.pid,
        pid_file_sha256=base.pid_file_sha256,
        start_ticks=base.start_ticks,
        python=base.python,
        haddock_bin=base.haddock_bin,
        argv=tuple(argv),
        source=base.source,
    )
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
