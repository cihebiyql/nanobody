#!/usr/bin/env python3
"""Fixture-only tests for the Node1 Residue V2 deployment launcher."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import node1_residue_v2_four_lane_v1 as mod


TRAINER_ARGUMENTS = {
    "structure_prefixes": ["seq_", "igfold_", "tnp_"],
    "structure_dim": 126,
    "ridge_alpha": 10.0,
    "graph_hidden_dim": 128,
    "dropout": 0.25,
    "residual_scale": 0.02,
    "huber_delta": 0.03,
    "dual_weight": 1.0,
    "receptor_weight": 0.35,
    "lane_contact_weights": {
        "A_DOMAIN": {"marginal_contact_weight": 0.01, "pair_contact_weight": 0.005},
        "B_VHH3D": {"marginal_contact_weight": 0.0025, "pair_contact_weight": 0.00125},
        "C_PATCH": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
        "D_FULL_PAIR": {"marginal_contact_weight": 0.000625, "pair_contact_weight": 0.0003125},
    },
    "contact_positive_class_fraction": 0.5,
    "contact_balance_epsilon": 1e-8,
    "component_gradient_telemetry_batches": 1,
    "ranking_weight": 0.0001,
    "ranking_minimum_delta": 0.02,
    "ranking_temperature": 0.03,
    "residual_l2_weight": 0.05,
    "gradient_accumulation": 2,
    "head_learning_rate": 0.0001,
    "weight_decay": 0.02,
    "gradient_clip": 1.0,
    "evaluation_batch_size": 16,
    "precision": "bf16",
    "seed": 43,
    "maximum_epochs": 8,
}


def write(path: pathlib.Path, data: bytes | str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


class Fixture:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.projects = root / "projects"
        self.projects.mkdir()
        self.runtime = self.projects / "runtime"
        self.bundle = root / "bundle"
        self.python = write(root / "env/bin/python", "#!/bin/sh\nexit 0\n")
        self.python.chmod(self.python.stat().st_mode | stat.S_IXUSR)
        self.artifact_paths: dict[str, pathlib.Path] = {}
        for label in sorted(mod.MATRIX_STATIC_ARTIFACTS):
            if label == "esm2_650m_model_identity":
                path = self.bundle / "model/model.safetensors"
            elif label in {"vhh_graph_cache_npz", "vhh_graph_manifest", "vhh_graph_cache_receipt"}:
                names = {
                    "vhh_graph_cache_npz": "graph_cache_v2.npz",
                    "vhh_graph_manifest": "graph_manifest_v2.tsv",
                    "vhh_graph_cache_receipt": "graph_cache_receipt_v2.json",
                }
                path = self.bundle / "graphs" / names[label]
            else:
                path = self.bundle / f"{label}.fixture"
            payload = b"fixture:" + label.encode("ascii")
            if label == "preregistration":
                payload = json.dumps({
                    "promotion_gates": {
                        "positive_status": "PROMOTE_RESIDUE_V2_OVER_M2",
                        "negative_status": "DO_NOT_PROMOTE_RESIDUE_V2",
                    }
                }).encode()
            write(path, payload)
            self.artifact_paths[label] = path
        artifacts: dict[str, dict[str, object]] = {
            label: {
                "phase": "pre_freeze_binding",
                "path": str(path),
                "sha256": mod.sha256_file(path),
            }
            for label, path in self.artifact_paths.items()
        }
        artifacts[mod.POST_ARTIFACT] = {
            "phase": "post_augmentation_binding",
            "path": str(self.runtime / "cache/pvrig_graphs/esm2_650m_v2"),
            "sha256": None,
            "closure_required": True,
        }
        for label, relative in mod.LOCAL_TRANSITIVE_RUNTIME_PATHS.items():
            write(self.bundle / relative, self.artifact_paths[label].read_bytes())
        implementation: dict[str, dict[str, object]] = {}
        for _label, relative in mod.IMPLEMENTATION_RUNTIME_PATHS.items():
            content = f"implementation:{relative}\n"
            if relative == "PREREGISTRATION_V2.json":
                content = json.dumps({
                    "promotion_gates": {
                        "positive_status": "PROMOTE_RESIDUE_V2_OVER_M2",
                        "negative_status": "DO_NOT_PROMOTE_RESIDUE_V2",
                    }
                }) + "\n"
            path = write(self.bundle / "residue_v2" / relative, content)
            implementation[relative] = {"path": str(path), "sha256": mod.sha256_file(path), "size_bytes": path.stat().st_size}
        numerical_path = write(
            self.bundle / "residue_v2" / mod.NUMERICAL_AMENDMENT_RELATIVE,
            json.dumps({"status": "fixture_v2_3_technical_supersession"}, sort_keys=True) + "\n",
        )
        implementation[mod.NUMERICAL_AMENDMENT_RELATIVE] = {
            "path": str(numerical_path),
            "sha256": mod.sha256_file(numerical_path),
            "size_bytes": numerical_path.stat().st_size,
        }
        self.freeze_payload = {
            "schema_version": "fixture_residue_v2_freeze",
            "mode": "production",
            "status": "PASS_RESIDUE_V2_IMPLEMENTATION_FROZEN_FOR_NODE1_SMOKE",
            "production_training_started": False,
            "pending": [],
            "formal_artifacts": artifacts,
            "contact_loss_governance": {
                "status": "PASS_CONTACT_LOSS_AMENDMENT_V2_2_BOUND",
                "lane_weights": TRAINER_ARGUMENTS["lane_contact_weights"],
                "prediction_metrics_used": False,
                "v4_f_test32_access_count": 0,
            },
            "implementation_files": implementation,
            "implementation_tree_sha256": mod.canonical_json_sha({
                relative: record["sha256"] for relative, record in implementation.items()
            }),
            "technical_supersession": mod.EXPECTED_TECHNICAL_SUPERSESSION,
            "numerical_stability_amendment": {
                "path": str(numerical_path),
                "sha256": mod.sha256_file(numerical_path),
                "size_bytes": numerical_path.stat().st_size,
            },
            "post_augmentation_contract": {"required_before_smoke_or_production": True},
            "sealed_test32_exclusion": {
                "path_access_count": 0,
                "training_use_forbidden": True,
            },
            "node1_deployment": {
                "remote_root": str(self.runtime),
                "python": str(self.python),
                "min_free_gib": 200,
                "augmentation_gpu": mod.AUGMENTATION_GPU,
                "lane_gpu_map": mod.LANE_GPU,
                "forbidden_gpus": list(mod.FORBIDDEN_GPUS),
                "reserved_gpus": list(mod.RESERVED_GPUS),
                "cpu_threads_per_process": mod.CPU_THREADS_PER_PROCESS,
                "bundle_root": str(self.bundle),
                "trainer_arguments": TRAINER_ARGUMENTS,
            },
        }
        self.freeze = write(
            self.bundle / mod.FREEZE_NAME,
            json.dumps(self.freeze_payload, indent=2, sort_keys=True) + "\n",
        )

    def context(self) -> mod.FreezeContext:
        return mod.load_freeze(self.freeze, expected_root=self.runtime, expected_python=self.python)

    def materialize_augmented(self, context: mod.FreezeContext) -> dict[str, str]:
        output_root = self.runtime / "cache/pvrig_graphs/esm2_650m_v2"
        artifact = write(output_root / "by_sha256/pending/target_graphs_esm2_650m_v2.pt", b"tensor-only-fixture")
        artifact_sha = mod.sha256_file(artifact)
        final_dir = output_root / "by_sha256" / artifact_sha
        final_dir.mkdir(parents=True)
        final_artifact = final_dir / artifact.name
        artifact.replace(final_artifact)
        artifact.parent.rmdir()
        receipt = {
            "schema_version": "pvrig_v6_target_graphs_esm2_650m_v2",
            "status": "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED",
            "input_hashes": {
                "base_target_pt": context.artifacts["base_target_pt"].sha256,
                "target_manifest": context.artifacts["base_target_manifest"].sha256,
                "base_target_receipt": context.artifacts["base_target_receipt"].sha256,
                "model_identity_file": context.artifacts["esm2_650m_model_identity"].sha256,
            },
            "implementation_sha256": context.artifacts["augment_target_script"].sha256,
            "inference": {
                "dtype": "bfloat16",
                "stored_dtype": "float32",
                "augmented_feature_dim": 1310,
                "network_access": "disabled",
            },
            "output": {"sha256": artifact_sha},
            "sealed_boundary": {
                "teacher_source_is_model_feature": False,
                "candidate_docking_pose_files_opened": 0,
            },
        }
        receipt_path = write(
            final_dir / "target_graphs_esm2_650m_v2.receipt.json",
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        )
        current = {
            "schema_version": "pvrig_v6_target_graphs_esm2_650m_v2",
            "artifact_sha256": artifact_sha,
            "artifact_relative_path": str(final_artifact.relative_to(output_root)),
            "receipt_relative_path": str(receipt_path.relative_to(output_root)),
            "receipt_sha256": mod.sha256_file(receipt_path),
        }
        write(output_root / "CURRENT.json", json.dumps(current, indent=2, sort_keys=True) + "\n")
        return {"artifact_path": str(final_artifact), "receipt_path": str(receipt_path)}


class DeploymentUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(pathlib.Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_freeze_drives_all_exact_hashes_and_rejects_tamper(self) -> None:
        context = self.fixture.context()
        observed = mod.validate_static_artifacts(context)
        self.assertTrue(mod.STATIC_ARTIFACTS <= set(observed))
        self.assertIn("implementation::src/train_nested_residue_surrogate_v2.py", observed)
        (self.fixture.bundle / "residue_v2/src/train_nested_residue_surrogate_v2.py").write_bytes(b"tampered")
        with self.assertRaisesRegex(mod.DeploymentError, "artifact_sha_mismatch:implementation::src/train_nested"):
            mod.validate_static_artifacts(context)

    def test_local_transitive_imports_are_bound_to_frozen_v1_hashes(self) -> None:
        context = self.fixture.context()
        observed = mod.validate_static_artifacts(context)
        label = "local_transitive::residue_v1_base_trainer"
        self.assertEqual(observed[label], context.artifacts["residue_v1_base_trainer"].sha256)
        (self.fixture.bundle / mod.LOCAL_TRANSITIVE_RUNTIME_PATHS["residue_v1_base_trainer"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(mod.DeploymentError, "artifact_sha_mismatch:local_transitive::residue_v1_base_trainer"):
            mod.validate_static_artifacts(context)

    def test_freeze_rejects_gpu_policy_and_sealed_artifact(self) -> None:
        payload = json.loads(json.dumps(self.fixture.freeze_payload))
        payload["node1_deployment"]["lane_gpu_map"]["A_DOMAIN"] = 0
        self.fixture.freeze.write_text(json.dumps(payload))
        with self.assertRaisesRegex(mod.DeploymentError, "lane_gpu_map_not_frozen"):
            self.fixture.context()
        payload = json.loads(json.dumps(self.fixture.freeze_payload))
        artifact = pathlib.Path(self.temporary.name) / "V4_F/test32/file"
        payload["formal_artifacts"]["augment_target_script"]["path"] = str(artifact)
        self.fixture.freeze.write_text(json.dumps(payload))
        with self.assertRaisesRegex(mod.DeploymentError, "sealed_or_test32_artifact_forbidden"):
            self.fixture.context()

    def test_freeze_rejects_missing_or_tampered_v2_3_numerical_amendment(self) -> None:
        payload = json.loads(json.dumps(self.fixture.freeze_payload))
        payload.pop("numerical_stability_amendment")
        self.fixture.freeze.write_text(json.dumps(payload))
        with self.assertRaisesRegex(mod.DeploymentError, "numerical_stability_amendment_missing"):
            self.fixture.context()

        payload = json.loads(json.dumps(self.fixture.freeze_payload))
        payload["numerical_stability_amendment"]["sha256"] = "0" * 64
        self.fixture.freeze.write_text(json.dumps(payload))
        with self.assertRaisesRegex(mod.DeploymentError, "numerical_stability_amendment_sha_mismatch"):
            self.fixture.context()

    def test_fresh_root_gate_rejects_existing_symlink_and_low_space(self) -> None:
        enough = lambda _: SimpleNamespace(free=201 * 1024 ** 3)
        self.assertEqual(mod.validate_fresh_root(self.fixture.runtime, disk_usage=enough), 201)
        low = lambda _: SimpleNamespace(free=199 * 1024 ** 3)
        with self.assertRaisesRegex(mod.DeploymentError, "free_space_below_200GiB"):
            mod.validate_fresh_root(self.fixture.runtime, disk_usage=low)
        self.fixture.runtime.symlink_to(self.fixture.bundle, target_is_directory=True)
        with self.assertRaisesRegex(mod.DeploymentError, "runtime_root_must_not_exist"):
            mod.validate_fresh_root(self.fixture.runtime, disk_usage=enough)

    def test_gpu_inventory_never_assigns_gpu0(self) -> None:
        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, stdout="".join(f"{index}, 18, 0\n" for index in range(8)), stderr="")
        self.assertEqual(mod.validate_gpu_inventory(runner), list(range(8)))
        def missing(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, stdout="".join(f"{index}, 18, 0\n" for index in range(5)), stderr="")
        with self.assertRaisesRegex(mod.DeploymentError, "required_gpu_missing"):
            mod.validate_gpu_inventory(missing)
        def busy(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, stdout="".join(
                f"{index}, {1200 if index == 5 else 18}, 0\n" for index in range(8)
            ), stderr="")
        with self.assertRaisesRegex(mod.DeploymentError, "required_gpu_not_idle:5"):
            mod.validate_gpu_inventory(busy)

    def test_logged_process_has_exact_cpu8_cap_and_rejects_forbidden_gpu(self) -> None:
        observed = {}
        def fake_run(command, **kwargs):
            observed.update(kwargs["env"])
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(mod._run_logged(["true"], gpu=1, log_path=pathlib.Path(self.temporary.name) / "run.log"), 0)
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            self.assertEqual(observed[name], "8")
        for gpu in mod.FORBIDDEN_GPUS:
            with self.assertRaisesRegex(mod.DeploymentError, "forbidden_gpu_execution"):
                mod._run_logged(["true"], gpu=gpu, log_path=pathlib.Path(self.temporary.name) / "forbidden.log")

    def test_augmentation_closure_is_content_addressed_and_exact(self) -> None:
        context = self.fixture.context()
        self.fixture.runtime.mkdir()
        self.fixture.materialize_augmented(context)
        closure = mod.validate_augmented_target(context)
        self.assertEqual(len(closure["artifact_sha256"]), 64)
        self.assertIn(f"by_sha256/{closure['artifact_sha256']}", closure["artifact_path"])
        observed = mod.validate_static_artifacts(context)
        with mock.patch.object(mod, "REMOTE_ROOT", self.fixture.runtime):
            path = mod.write_input_closure(context, closure, observed)
            self.assertEqual(mod.validate_input_closure(context, observed)["augmented_target_graph"], closure)
        pathlib.Path(closure["artifact_path"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(mod.DeploymentError, "augmented_target_current_hash_mismatch"):
            mod.validate_augmented_target(context)

    def test_commands_use_full1507_smoke_then_frozen_production_and_lane_inputs(self) -> None:
        context = self.fixture.context()
        closure = {"augmented_target_graph": {"artifact_path": "/aug/target.pt", "receipt_path": "/aug/receipt.json"}}
        with mock.patch.object(mod, "FIXED_PYTHON", self.fixture.python):
            for lane, physical_gpu in mod.LANE_GPU.items():
                smoke = mod.trainer_command(
                    context, closure, lane=lane, fold=0,
                    output_dir=self.fixture.runtime / f"smoke/{lane}", smoke=True,
                )
                production = mod.trainer_command(
                    context, closure, lane=lane, fold=4,
                    output_dir=self.fixture.runtime / f"prod/{lane}", smoke=False,
                )
                self.assertEqual(physical_gpu, {"A_DOMAIN": 1, "B_VHH3D": 2, "C_PATCH": 4, "D_FULL_PAIR": 5}[lane])
                self.assertIn("--smoke-mode", smoke)
                self.assertEqual(smoke[smoke.index("--max-epochs") + 1], "1")
                self.assertNotIn("--smoke-mode", production)
                self.assertNotIn("--contact-loss-amendment", smoke)
                self.assertEqual(
                    production[production.index("--contact-loss-amendment") + 1],
                    str(context.artifacts["contact_loss_amendment_v2_2"].path),
                )
                weights = TRAINER_ARGUMENTS["lane_contact_weights"][lane]
                self.assertEqual(float(production[production.index("--marginal-contact-weight") + 1]), weights["marginal_contact_weight"])
                self.assertEqual(float(production[production.index("--pair-contact-weight") + 1]), weights["pair_contact_weight"])
                self.assertEqual(production[production.index("--max-epochs") + 1], "8")
                self.assertEqual(smoke[smoke.index("--training-tsv") + 1], str(context.artifacts["training_tsv"].path))
                self.assertNotIn("test32", " ".join(smoke).lower())
                if lane == "A_DOMAIN":
                    self.assertNotIn("--graph-cache-dir", smoke)
                if lane == "D_FULL_PAIR":
                    self.assertIn("--pair-contact-tsv-gz", smoke)

    def test_resume_requires_hash_closed_pass_terminal(self) -> None:
        context = self.fixture.context()
        with mock.patch.object(mod, "FIXED_PYTHON", self.fixture.python), mock.patch.object(mod, "REMOTE_ROOT", self.fixture.runtime):
            output = self.fixture.runtime / "runtime/A_DOMAIN/production/fold_0/output"
            output.mkdir(parents=True)
            artifact_hashes = {}
            for name in ("contract.json", "head_final.pt", "outer_test_predictions.tsv"):
                path = write(output / name, f"{name}\n")
                artifact_hashes[name] = mod.sha256_file(path)
            result = {"status": "PASS_OUTER_FOLD_COMPLETE", "lane": "A_DOMAIN", "outer_fold": 0, "artifacts": artifact_hashes}
            result_path = write(output / "RESULT.json", json.dumps(result, sort_keys=True) + "\n")
            closure = {"augmented_target_graph": {"artifact_path": "/aug.pt", "receipt_path": "/aug.json"}}
            command = mod.trainer_command(context, closure, lane="A_DOMAIN", fold=0, output_dir=output, smoke=False)
            closure_sha = "c" * 64
            evidence = {"result_path": str(result_path), "result_sha256": mod.sha256_file(result_path)}
            terminal = mod.terminal_payload(
                status="PASS_FOLD_COMPLETE", context=context, closure_sha=closure_sha,
                lane="A_DOMAIN", fold=0, command=command, return_code=0, evidence=evidence,
            )
            terminal_path = write(output.parent / mod.TERMINAL_NAME, json.dumps(terminal))
            self.assertTrue(mod.validate_reusable_terminal(
                terminal_path, context=context, closure_sha=closure_sha, lane="A_DOMAIN",
                fold=0, command=command, output_dir=output,
            ))
            write(output / "head_final.pt", b"tampered")
            with self.assertRaisesRegex(mod.DeploymentError, "trainer_artifact_hash_mismatch"):
                mod.validate_reusable_terminal(
                    terminal_path, context=context, closure_sha=closure_sha, lane="A_DOMAIN",
                    fold=0, command=command, output_dir=output,
                )

    def test_dry_run_plan_has_exact_4x5_matrix_and_no_mutation(self) -> None:
        context = self.fixture.context()
        with mock.patch.object(mod, "FIXED_PYTHON", self.fixture.python), mock.patch.object(mod, "REMOTE_ROOT", self.fixture.runtime):
            plan = mod.dry_run_plan(context)
        self.assertEqual(plan["status"], "PASS_DRY_RUN_PLAN_NO_MUTATION")
        self.assertEqual(set(plan["smoke"]), set(mod.LANE_GPU))
        self.assertEqual(sum(len(row["commands"]) for row in plan["production"].values()), 20)
        self.assertEqual(plan["collectors_after_all_20_folds"], list(mod.LANE_GPU))
        self.assertFalse(self.fixture.runtime.exists())
        self.assertFalse(plan["v4_f_test32_synced_or_opened"])
        serialized = json.dumps({"smoke": plan["smoke"], "production": plan["production"]}).lower()
        self.assertNotIn("test32", serialized)
        self.assertNotIn("v4_f", serialized)

    def test_fixture_end_to_end_uses_augmentation_then_four_smokes_then_twenty_folds_then_collectors(self) -> None:
        context = self.fixture.context()
        observed = mod.validate_static_artifacts(context)
        calls: list[tuple[str, str]] = []
        lock = threading.Lock()

        def fake_run(command, *, gpu, log_path):
            with lock:
                if str(context.artifacts["augment_target_script"].path) in command:
                    calls.append(("augmentation", str(gpu)))
                    self.fixture.materialize_augmented(context)
                    return 0
                if str(context.artifacts["trainer"].path) in command:
                    lane = command[command.index("--lane") + 1]
                    fold = int(command[command.index("--outer-fold") + 1])
                    stage = "smoke" if "--smoke-mode" in command else "production"
                    calls.append((stage, f"{lane}:{fold}:{gpu}"))
                    output = pathlib.Path(command[command.index("--output-dir") + 1])
                    output.mkdir(parents=True)
                    hashes = {}
                    for name in ("contract.json", "head_final.pt", "outer_test_predictions.tsv"):
                        path = write(output / name, f"{lane}:{fold}:{name}\n")
                        hashes[name] = mod.sha256_file(path)
                    write(output / "RESULT.json", json.dumps({
                        "status": "PASS_OUTER_FOLD_COMPLETE", "lane": lane,
                        "outer_fold": fold, "artifacts": hashes,
                    }, sort_keys=True) + "\n")
                    return 0
                if str(context.artifacts["collector"].path) in command:
                    self.assertEqual(sum(stage == "production" for stage, _ in calls), 20)
                    output = pathlib.Path(command[command.index("--output-dir") + 1])
                    output.mkdir(parents=True)
                    write(output / "OOF_PROMOTION_REPORT.json", json.dumps({"status": "DO_NOT_PROMOTE_RESIDUE_V2"}) + "\n")
                    calls.append(("collector", str(gpu)))
                    return 0
            raise AssertionError(command)

        with (
            mock.patch.object(mod, "REMOTE_ROOT", self.fixture.runtime),
            mock.patch.object(mod, "FIXED_PYTHON", self.fixture.python),
            mock.patch.object(mod, "validate_fresh_root", return_value=999),
            mock.patch.object(mod, "validate_gpu_inventory", return_value=list(range(8))),
            mock.patch.object(mod, "_run_logged", side_effect=fake_run),
        ):
            terminal = mod.run_pipeline(context, resume=False)
        self.assertEqual(terminal["status"], "PASS_ALL_FOUR_LANES_20_FOLDS_AND_COLLECTORS")
        self.assertEqual(sum(stage == "augmentation" for stage, _ in calls), 1)
        self.assertEqual(sum(stage == "smoke" for stage, _ in calls), 4)
        self.assertEqual(sum(stage == "production" for stage, _ in calls), 20)
        self.assertEqual(sum(stage == "collector" for stage, _ in calls), 4)
        self.assertEqual(observed, terminal.get("static_artifact_sha256", observed))


if __name__ == "__main__":
    unittest.main()
