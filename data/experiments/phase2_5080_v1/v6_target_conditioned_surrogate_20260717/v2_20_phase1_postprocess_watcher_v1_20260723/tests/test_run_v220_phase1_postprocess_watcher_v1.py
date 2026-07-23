from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watcher = load(
    ROOT / "src" / "run_v220_phase1_postprocess_watcher_v1.py",
    "v220_phase1_postprocess_watcher_test",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PostprocessWatcherTests(unittest.TestCase):
    def make_training(self, root: Path, *, folds=range(5)) -> dict[int, str]:
        hashes = {}
        for fold in folds:
            results = {}
            for arm in ("C0", "C1"):
                result_path = root / arm / f"fold_{fold}" / "RESULT.json"
                write_json(result_path, {"arm": arm, "fold_id": fold})
                results[arm] = {
                    "result_path": str(result_path),
                    "result_sha256": sha(result_path),
                }
            terminal_path = root / f"fold_{fold}_PAIR_TERMINAL.json"
            write_json(
                terminal_path,
                {
                    "status": "PASS_V220_C0_C1_FOLD_PAIR",
                    "fold_id": fold,
                    "seed": 43,
                    "results": results,
                },
            )
            hashes[fold] = sha(terminal_path)
        return hashes

    def make_config(self, root: Path) -> object:
        inputs = root / "inputs"
        inputs.mkdir()
        files = {}
        for label in (
            "teacher",
            "assignment",
            "v213_runner",
            "b0_oof",
            "b0_replay_receipt",
            "upstream_preregistration",
            "pairing_cli",
            "collector_cli",
            "evaluator_cli",
            "core_gate_cli",
            "upstream_final_training_freeze",
            "upstream_final_training_launcher",
            "node1_preflight_receipt",
        ):
            path = inputs / label
            path.write_text(label + "\n")
            files[label] = path
        contracts = inputs / "contracts"
        contracts.mkdir()
        for fold in range(5):
            path = contracts / f"fold_{fold}_contract.json"
            path.write_text(f"fold{fold}\n")
            files[f"fold_{fold}_contract"] = path
        files["watcher_cli"] = Path(watcher.__file__).resolve()
        files["python_binary"] = Path(sys.executable).resolve()
        bindings = {
            label: {"path": str(path), "sha256": sha(path)}
            for label, path in files.items()
        }
        return watcher.FrozenConfig(
            python_bin=Path(sys.executable),
            training_root=root / "training",
            teacher=files["teacher"],
            assignment=files["assignment"],
            contracts_dir=contracts,
            v213_runner=files["v213_runner"],
            b0_oof=files["b0_oof"],
            b0_replay_receipt=files["b0_replay_receipt"],
            upstream_preregistration=files["upstream_preregistration"],
            pairing_cli=files["pairing_cli"],
            collector_cli=files["collector_cli"],
            evaluator_cli=files["evaluator_cli"],
            core_gate_cli=files["core_gate_cli"],
            frozen_bindings=bindings,
        )

    def fake_executor(self, *, core_pass: bool):
        def execute(command, log_path):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("ok\n")
            if log_path.name == "01_pairing.log":
                output = Path(command[command.index("--output-json") + 1])
                write_json(
                    output,
                    {
                        "status": "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING",
                        "folds": [{"fold_id": fold} for fold in range(5)],
                    },
                )
            elif "collect" in log_path.name:
                arm = command[command.index("--arm") + 1]
                output = Path(command[command.index("--output-dir") + 1])
                prediction = output / f"V220_{arm}_TRAIN9849_OOF_PREDICTIONS.tsv"
                prediction.parent.mkdir(parents=True, exist_ok=True)
                prediction.write_text("candidate_id\nexample\n")
                write_json(
                    output / "OOF_RECEIPT.json",
                    {
                        "status": f"PASS_V220_{arm}_TRAIN9849_WHOLE_PARENT_OOF",
                        "counts": {"rows": 9849, "parents": 54, "folds": 5, "seed": 43},
                        "input_access": {
                            "open_development_rows": 0,
                            "frozen_test_rows": 0,
                        },
                        "outputs": {prediction.name: sha(prediction)},
                    },
                )
                (output / "SHA256SUMS").write_text("collector\n")
            elif "evaluate" in log_path.name:
                named = command[command.index("--input") + 1]
                arm, source = named.split("=", 1)
                output = Path(command[command.index("--output-json") + 1])
                write_json(
                    output,
                    {
                        "status": "PASS_FROZEN_V220_OOF_EVALUATION",
                        "metrics": {arm: {"rows": 9849, "parents": 54}},
                        "input_hashes": {arm: sha(Path(source))},
                        "input_access": {
                            "open_development_rows": 0,
                            "frozen_test_rows": 0,
                        },
                    },
                )
            elif log_path.name == "06_core_gate.log":
                output = Path(command[command.index("--output-json") + 1])
                checks = {f"gate_{index}": core_pass for index in range(9)}
                write_json(
                    output,
                    {
                        "status": watcher.PASS_CORE_STATUS
                        if core_pass
                        else watcher.FAIL_CORE_STATUS,
                        "all_core_gates_pass": core_pass,
                        "bootstrap": {
                            "replicates": 10000,
                            "seed": 20260723,
                            "parents": 54,
                        },
                        "gate_checks": checks,
                        "input_access": {
                            "open_development_rows": 0,
                            "frozen_test_rows": 0,
                        },
                    },
                )
            else:
                raise AssertionError(log_path)

        return execute

    def test_missing_pair_terminals_are_waited_not_treated_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            training = Path(temporary) / "training"
            self.make_training(training, folds=(0, 2))
            hashes, missing = watcher.inspect_pair_terminals(training)
            self.assertEqual(set(hashes), {0, 2})
            self.assertEqual(missing, [1, 3, 4])

    def test_bad_existing_pair_terminal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            training = Path(temporary) / "training"
            self.make_training(training, folds=(0,))
            terminal = training / "fold_0_PAIR_TERMINAL.json"
            value = json.loads(terminal.read_text())
            value["status"] = "FAILED"
            write_json(terminal, value)
            with self.assertRaises(watcher.PostprocessError):
                watcher.inspect_pair_terminals(training)

    def test_commands_are_exactly_pair_collect_collect_evaluate_evaluate_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            commands = watcher.build_commands(config, root / "output")
            self.assertEqual(
                [stage for stage, _, _ in commands],
                ["pairing", "collect_C0", "collect_C1", "evaluate_C0", "evaluate_C1", "core_gate"],
            )
            gate = commands[-1][1]
            self.assertIn("10000", gate)
            self.assertIn("20260723", gate)
            self.assertNotIn("top7500", " ".join(gate).lower())

    def test_operational_path_must_match_its_named_frozen_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            wrong = root / "wrong_evaluator.py"
            wrong.write_text("wrong\n")
            with self.assertRaisesRegex(
                watcher.PostprocessError, "operational_binding_path:evaluator_cli"
            ):
                watcher.verify_operational_binding_paths(
                    replace(config, evaluator_cli=wrong)
                )

    def test_frozen_preregistration_loads_only_exact_bound_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            prereg = root / "prereg.json"
            write_json(
                prereg,
                {
                    "status": "FROZEN_V220_PHASE1_POSTPROCESS_WATCHER_PROTOCOL",
                    "bootstrap_replicates": 10000,
                    "bootstrap_seed": 20260723,
                    "terminal_semantics": {"core_pass_scope": "PHASE1B_ONLY"},
                    "paths": {
                        "python_bin": str(config.python_bin),
                        "training_root": str(config.training_root),
                        "teacher": str(config.teacher),
                        "assignment": str(config.assignment),
                        "contracts_dir": str(config.contracts_dir),
                        "v213_runner": str(config.v213_runner),
                        "b0_oof": str(config.b0_oof),
                        "b0_replay_receipt": str(config.b0_replay_receipt),
                        "upstream_preregistration": str(
                            config.upstream_preregistration
                        ),
                        "pairing_cli": str(config.pairing_cli),
                        "collector_cli": str(config.collector_cli),
                        "evaluator_cli": str(config.evaluator_cli),
                        "core_gate_cli": str(config.core_gate_cli),
                    },
                    "frozen_bindings": config.frozen_bindings,
                },
            )
            loaded, digest = watcher.load_frozen_config(prereg, sha(prereg))
            self.assertEqual(digest, sha(prereg))
            self.assertEqual(loaded.training_root, config.training_root)

    def test_core_gate_status_boolean_must_be_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gate.json"
            write_json(
                path,
                {
                    "status": watcher.PASS_CORE_STATUS,
                    "all_core_gates_pass": False,
                    "bootstrap": {"replicates": 10000, "seed": 20260723, "parents": 54},
                    "gate_checks": {f"g{x}": False for x in range(9)},
                    "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
                },
            )
            with self.assertRaises(watcher.PostprocessError):
                watcher.verify_core_gate(path)

    def test_core_pass_publishes_phase1b_only_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            hashes = self.make_training(config.training_root)
            output = root / "output"
            output.mkdir()
            result = watcher.execute_postprocess(
                config,
                output,
                hashes,
                executor=self.fake_executor(core_pass=True),
            )
            self.assertEqual(
                result["status"],
                "PASS_V220_PHASE1B_AUTHORIZED_BY_FROZEN_CORE_GATE_ONLY",
            )
            self.assertEqual(result["authorization_scope"], "PHASE1B_ABLATIONS_ONLY")
            self.assertFalse(result["top7500_injected"])
            self.assertTrue((output / "PHASE1B_AUTHORIZED_TERMINAL.json").is_file())
            self.assertFalse((output / "CORE_GATE_FAILED_TERMINAL.json").exists())

    def test_core_fail_never_publishes_pass_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            hashes = self.make_training(config.training_root)
            output = root / "output"
            output.mkdir()
            result = watcher.execute_postprocess(
                config,
                output,
                hashes,
                executor=self.fake_executor(core_pass=False),
            )
            self.assertEqual(result["status"], watcher.FAIL_CORE_STATUS)
            self.assertEqual(result["authorization_scope"], "NONE")
            self.assertFalse((output / "PHASE1B_AUTHORIZED_TERMINAL.json").exists())
            self.assertTrue((output / "CORE_GATE_FAILED_TERMINAL.json").is_file())

    def test_changed_pair_terminal_after_wait_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self.make_config(root)
            hashes = self.make_training(config.training_root)
            hashes[0] = "0" * 64
            output = root / "output"
            output.mkdir()
            with self.assertRaisesRegex(watcher.PostprocessError, "pair_terminals_changed"):
                watcher.execute_postprocess(
                    config,
                    output,
                    hashes,
                    executor=self.fake_executor(core_pass=True),
                )
            self.assertFalse((output / "PHASE1B_AUTHORIZED_TERMINAL.json").exists())

    def test_preregistration_failure_writes_only_failure_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prereg = root / "bad.json"
            write_json(prereg, {"status": "NOT_FROZEN"})
            output = root / "output"
            with self.assertRaises(watcher.PostprocessError):
                watcher.run(
                    prereg,
                    sha(prereg),
                    output,
                    poll_seconds=0.01,
                    timeout_seconds=0.01,
                )
            failure = json.loads((output / "FAILED.json").read_text())
            self.assertEqual(
                failure["status"],
                "FAILED_V220_PHASE1_POSTPROCESS_NO_PASS_PUBLISHED",
            )
            self.assertFalse((output / "PHASE1B_AUTHORIZED_TERMINAL.json").exists())


if __name__ == "__main__":
    unittest.main()
