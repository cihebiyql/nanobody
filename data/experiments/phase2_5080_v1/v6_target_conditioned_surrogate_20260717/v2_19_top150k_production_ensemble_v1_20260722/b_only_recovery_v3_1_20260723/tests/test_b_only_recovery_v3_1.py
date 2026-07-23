from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
TOP = ROOT.parent
PROFILE_SOURCE = ROOT / "src/run_profiled_v211_b4_inference_v3_1.py"
VALIDATOR_SOURCE = ROOT / "src/validate_top150k_b_only_recovery_v3_1.py"
BASE_INFER_SOURCE = TOP / "src/infer_clean_attention_checkpoint_ensemble_v1.py"
BASE_TEST_SOURCE = TOP / "tests/test_infer_clean_attention_checkpoint_ensemble_v1.py"
MODEL_SOURCE = TOP.parent / "v2_5_ortho_contact_pose_stack_v1_20260718/model/residue_model_v2_5_ortho.py"


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROFILE = import_module("top150k_b31_profile", PROFILE_SOURCE)
VALIDATOR = import_module("top150k_b31_validator", VALIDATOR_SOURCE)
BASE_INFER = import_module("top150k_b31_base_infer", BASE_INFER_SOURCE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ProfileFixture:
    def __init__(self, root: Path):
        self.root = root
        self.checkpoints: list[Path] = []
        self.results: list[Path] = []
        self.seeds = (43, 917, 1931, 3253)
        self.config = {"enable_contact_evidence": False, "width": 3}
        for index, seed in enumerate(self.seeds):
            checkpoint = root / f"seed{seed}.pt"
            payload = {
                "schema_version": PROFILE.CHECKPOINT_SCHEMA,
                "lane": PROFILE.LANE,
                "backbone_identity_sha256": PROFILE.BACKBONE_SHA256,
                "seed": seed,
                "split_id": PROFILE.SPLIT_ID,
                "head_config": dict(self.config),
                "head_state_dict": {"weight": torch.arange(6, dtype=torch.float32).reshape(2, 3) + index},
            }
            torch.save(payload, checkpoint)
            result = root / f"seed{seed}.RESULT.json"
            write_json(result, self.result_payload(seed, sha(checkpoint)))
            self.checkpoints.append(checkpoint)
            self.results.append(result)
        checkpoint_payload = torch.load(self.checkpoints[0], map_location="cpu", weights_only=True)
        signature, tensors, parameters = PROFILE.state_signature(checkpoint_payload["head_state_dict"])
        self.profile = PROFILE.B4Profile(
            profile_id="synthetic_b4_profile",
            seeds=tuple(
                PROFILE.SeedProfile(seed, sha(checkpoint), sha(result))
                for seed, checkpoint, result in zip(self.seeds, self.checkpoints, self.results)
            ),
            head_config_sha256=PROFILE.canonical_sha256(self.config),
            state_signature_sha256=signature,
            tensor_count=tensors,
            parameter_count=parameters,
        )

    @staticmethod
    def result_payload(seed: int, checkpoint_sha: str) -> dict:
        return {
            "schema_version": PROFILE.CHECKPOINT_SCHEMA,
            "status": "PASS_FULL10644_CLEAN_ATTENTION_FIXED_EPOCH_TRAINING",
            "lane": PROFILE.LANE,
            "seed": seed,
            "backbone_identity_sha256": PROFILE.BACKBONE_SHA256,
            "split": {"split_id": PROFILE.SPLIT_ID},
            "frozen_test_access_count": 0,
            "exact_min_inference": True,
            "outputs": {"clean_attention_head_final.pt": checkpoint_sha},
            "input_bindings": dict(PROFILE.EXPECTED_INPUT_BINDINGS),
            "neural_input_firewall": {
                "m2_input_count": 0, "c2_input_count": 0, "contact_input_count": 0,
                "candidate_docking_pose_input_count": 0, "candidate_id_input_count": 0,
                "parent_id_input_count": 0,
            },
            "training": {"optimizer_parameter_roles": {"contact": {"parameter_values": 0}}},
        }

    def rebuild_profile(self) -> None:
        self.profile = replace(
            self.profile,
            seeds=tuple(
                PROFILE.SeedProfile(seed, sha(checkpoint), sha(result))
                for seed, checkpoint, result in zip(self.seeds, self.checkpoints, self.results)
            ),
        )


class TerminalFixture:
    def __init__(self, root: Path):
        self.root = root
        self.expected_rows = 3
        self.manifest = root / "manifest.tsv"
        self.graph = root / "graph.json"
        self.graph_cache = root / "graph_cache_v2.npz"
        self.graph_manifest = root / "graph_manifest_v2.tsv"
        self.l1_output = root / "l1.tsv"
        self.l1_receipt = root / "l1.json"
        self.b_output = root / "b.tsv"
        self.b_receipt = root / "b.json"
        self.profile_receipt = root / "profile.json"
        self.failed_log = root / "failed.log"
        self.preflight_receipt = root / "preflight.json"
        self.rows = [
            {"candidate_id": f"c{i}", "sequence_sha256": f"s{i}", "sequence": "ACDE", "parent_framework_cluster": f"p{i}"}
            for i in range(3)
        ]
        write_tsv(self.manifest, list(VALIDATOR.COMPACT_FIELDS), self.rows)
        self.graph_cache.write_bytes(b"synthetic graph cache\n")
        self.graph_manifest.write_text("candidate_id\n" + "\n".join(row["candidate_id"] for row in self.rows) + "\n", encoding="utf-8")
        write_json(self.graph, {
            "status": VALIDATOR.GRAPH_STATUS, "counts": {"entities": 3},
            "forbidden_model_features": ["teacher_source", "candidate_docking_pose", "absolute_coordinate_mlp_input"],
            "outputs": {
                "graph_cache_v2.npz": sha(self.graph_cache),
                "graph_manifest_v2.tsv": sha(self.graph_manifest),
            },
        })
        self.write_predictions(self.l1_output, 5)
        self.write_predictions(self.b_output, 4)
        write_json(self.l1_receipt, self.inference_receipt(self.l1_output, 5, None))
        b_checkpoints = [
            {"seed": seed, "sha256": digest, "schema_version": VALIDATOR.EXPECTED_SCHEMA,
             "split_id": VALIDATOR.EXPECTED_SPLIT, "variant": "BASE"}
            for seed, digest in zip(VALIDATOR.EXPECTED_B_SEEDS, VALIDATOR.EXPECTED_B_HASHES)
        ]
        write_json(self.b_receipt, self.inference_receipt(self.b_output, 4, b_checkpoints))
        write_json(self.profile_receipt, {
            "status": VALIDATOR.PROFILE_STATUS, "profile_id": VALIDATOR.PROFILE_ID,
            "checkpoint_schema": VALIDATOR.EXPECTED_SCHEMA, "split_id": VALIDATOR.EXPECTED_SPLIT,
            "checkpoints": [
                {"seed": seed, "checkpoint": {"sha256": digest}}
                for seed, digest in zip(VALIDATOR.EXPECTED_B_SEEDS, VALIDATOR.EXPECTED_B_HASHES)
            ],
        })
        self.failed_log.write_text(
            "ProductionInferenceError: checkpoint_schema_invalid:"
            "pvrig_v2_11_full10644_clean_attention_runner_v1\n", encoding="utf-8"
        )
        write_json(self.preflight_receipt, self.preflight())

    def write_predictions(self, path: Path, checkpoints: int, *, nonfinite: bool = False, identity_drift: bool = False, exact_drift: bool = False) -> None:
        fields = list(VALIDATOR.COMPACT_FIELDS)
        for index in range(checkpoints):
            fields += [f"checkpoint_{index:03d}_R_8X6B", f"checkpoint_{index:03d}_R_9E6Y", f"checkpoint_{index:03d}_R_dual_min"]
        fields += [
            "ensemble_R_8X6B_mean", "ensemble_R_8X6B_std", "ensemble_R_9E6Y_mean",
            "ensemble_R_9E6Y_std", "ensemble_R_dual_mean", "ensemble_R_dual_std",
            "ensemble_exact_min_of_receptor_means", "ensemble_receptor_gap_abs",
            "ensemble_checkpoint_rank_std", "ensemble_conservative_R_dual_score",
            "ensemble_R_dual_mean_rank", "ensemble_conservative_rank",
            "ensemble_conservative_top_fraction", "ensemble_checkpoint_count", "claim_boundary",
        ]
        output = []
        for item, source in enumerate(self.rows):
            row = dict(source)
            if identity_drift and item == 1:
                row["sequence_sha256"] = "drift"
            for index in range(checkpoints):
                r8, r9 = 0.30 + item*0.01 + index*0.001, 0.20 + item*0.01 + index*0.001
                row[f"checkpoint_{index:03d}_R_8X6B"] = str(r8)
                row[f"checkpoint_{index:03d}_R_9E6Y"] = str(r9)
                row[f"checkpoint_{index:03d}_R_dual_min"] = str(r9 + (0.01 if exact_drift and item == 0 and index == 0 else 0.0))
            r8_mean, r9_mean = 0.31 + item*0.01, 0.21 + item*0.01
            row.update({
                "ensemble_R_8X6B_mean": "nan" if nonfinite and item == 0 else str(r8_mean),
                "ensemble_R_8X6B_std": "0.01", "ensemble_R_9E6Y_mean": str(r9_mean),
                "ensemble_R_9E6Y_std": "0.01", "ensemble_R_dual_mean": str(r9_mean),
                "ensemble_R_dual_std": "0.01", "ensemble_exact_min_of_receptor_means": str(r9_mean),
                "ensemble_receptor_gap_abs": str(abs(r8_mean-r9_mean)),
                "ensemble_checkpoint_rank_std": "0.0", "ensemble_conservative_R_dual_score": str(r9_mean-0.01),
                "ensemble_R_dual_mean_rank": str(item+1), "ensemble_conservative_rank": str(item+1),
                "ensemble_conservative_top_fraction": str(item/2), "ensemble_checkpoint_count": str(checkpoints),
                "claim_boundary": "computational geometry only",
            })
            output.append(row)
        write_tsv(path, fields, output)

    def inference_receipt(self, output: Path, checkpoints: int, bound_checkpoints: list[dict] | None) -> dict:
        inputs = {"manifest": {"sha256": sha(self.manifest)}}
        if bound_checkpoints is not None:
            inputs["checkpoints"] = bound_checkpoints
        return {
            "status": VALIDATOR.INFERENCE_STATUS,
            "counts": {"rows": 3, "checkpoints": checkpoints},
            "input_firewall": {
                "teacher_fields_read": 0, "truth_fields_read": 0, "docking_pose_files_opened": 0,
                "contact_supervision_fields_read": 0, "candidate_id_model_input_count": 0,
                "parent_id_model_input_count": 0,
            },
            "inference": {
                "batch_size": 64, "backbone_forward_batches": 1, "head_forward_batches": checkpoints,
                "shared_backbone_once_per_batch": True, "exact_min_inference": True,
                "exact_min_max_abs_error": 0.0,
            },
            "outputs": {VALIDATOR.PREDICTION_NAME: sha(output)},
            "input_bindings": inputs,
        }

    def preflight(self) -> dict:
        return VALIDATOR.build_preflight(
            manifest=self.manifest, graph_receipt=self.graph, l1_output=self.l1_output,
            l1_receipt=self.l1_receipt, failed_b_log=self.failed_log, expected_rows=3,
        )

    def terminal(self) -> dict:
        return VALIDATOR.build_terminal(
            manifest=self.manifest, graph_receipt=self.graph, l1_output=self.l1_output,
            l1_receipt=self.l1_receipt, b_output=self.b_output, b_receipt=self.b_receipt,
            profile_receipt=self.profile_receipt, preflight_receipt=self.preflight_receipt,
            failed_b_log=self.failed_log, expected_rows=3,
        )


class ExactProfileTests(unittest.TestCase):
    def test_01_exact_profile_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary))
            receipt = PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)
            self.assertEqual(receipt["status"], PROFILE.STATUS)
            self.assertEqual([item["seed"] for item in receipt["checkpoints"]], list(fixture.seeds))

    def test_02_unsupported_schema_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[0]
            payload = torch.load(path, weights_only=True); payload["schema_version"] = "unsupported"; torch.save(payload, path)
            fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_schema_invalid"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_03_wrong_checkpoint_hash_fails_before_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary))
            wrong = replace(fixture.profile.seeds[0], checkpoint_sha256="0"*64)
            profile = replace(fixture.profile, seeds=(wrong, *fixture.profile.seeds[1:]))
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_sha256_mismatch"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, profile)

    def test_04_wrong_seed_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[1]
            payload = torch.load(path, weights_only=True); payload["seed"] = 43; torch.save(payload, path); fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_seed_invalid"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_05_wrong_split_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[2]
            payload = torch.load(path, weights_only=True); payload["split_id"] = "leaky"; torch.save(payload, path); fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_split_invalid"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_06_config_drift_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[0]
            payload = torch.load(path, weights_only=True); payload["head_config"]["width"] = 4; torch.save(payload, path); fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_config_sha256_mismatch"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_07_state_signature_drift_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[0]
            payload = torch.load(path, weights_only=True); payload["head_state_dict"]["weight"] = torch.zeros(3, 3); torch.save(payload, path); fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_state_signature_mismatch"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_08_backbone_lane_and_contact_are_fail_closed(self):
        mutations = (("backbone_identity_sha256", "bad", "checkpoint_backbone_invalid"), ("lane", "bad", "checkpoint_lane_invalid"))
        for key, value, error in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[0]
                payload = torch.load(path, weights_only=True); payload[key] = value; torch.save(payload, path); fixture.rebuild_profile()
                with self.assertRaisesRegex(PROFILE.ProfileValidationError, error):
                    PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.checkpoints[0]
            payload = torch.load(path, weights_only=True); payload["head_config"]["enable_contact_evidence"] = True; torch.save(payload, path); fixture.rebuild_profile()
            profile = replace(fixture.profile, head_config_sha256=PROFILE.canonical_sha256(payload["head_config"]))
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "checkpoint_contact_enabled"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, profile)

    def test_09_result_provenance_and_frozen_access_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary)); path = fixture.results[0]
            payload = json.loads(path.read_text()); payload["frozen_test_access_count"] = 1; write_json(path, payload); fixture.rebuild_profile()
            with self.assertRaisesRegex(PROFILE.ProfileValidationError, "result_frozen_test_access"):
                PROFILE.validate_exact_profile(fixture.checkpoints, fixture.results, fixture.profile)

    def test_10_production_config_and_state_signature_constants_are_reproducible(self):
        model = import_module("top150k_b31_model_contract", MODEL_SOURCE)
        config = model.ResidueV25OrthoConfig.for_lane(
            PROFILE.LANE, backbone_hidden_size=1280, target_node_dim=30, edge_feature_dim=26,
            graph_hidden_dim=128, dropout=0.25, enable_contact_evidence=False,
            contact_encoder_gradient="detached",
        )
        self.assertEqual(PROFILE.canonical_sha256(config.__dict__), PROFILE.HEAD_CONFIG_SHA256)
        signature, tensors, parameters = PROFILE.state_signature(model.OrthogonalTargetHead(config).state_dict())
        self.assertEqual((signature, tensors, parameters), (PROFILE.STATE_SIGNATURE_SHA256, 130, 1_102_764))

    def test_11_schema_extension_is_scoped_and_restored(self):
        class FakeBase:
            ACCEPTED_CHECKPOINT_SCHEMAS = {"old"}
            @staticmethod
            def infer(args):
                self.assertIn(PROFILE.CHECKPOINT_SCHEMA, FakeBase.ACCEPTED_CHECKPOINT_SCHEMAS)
                return {"ok": True}
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProfileFixture(Path(temporary))
            receipt = Path(temporary) / "profile_receipt.json"
            args = argparse.Namespace(checkpoint=fixture.checkpoints)
            self.assertEqual(PROFILE.infer_profiled(FakeBase, args, fixture.results, receipt, fixture.profile), {"ok": True})
            self.assertEqual(FakeBase.ACCEPTED_CHECKPOINT_SCHEMAS, {"old"})

    def test_12_v211_schema_only_change_preserves_tiny_predictions(self):
        fixture_module = import_module("top150k_b31_old_fixture", BASE_TEST_SOURCE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = fixture_module.ProductionFixture.create(root / "fixture")
            checkpoints = []
            for index, seed in enumerate((43, 917, 1931, 3253)):
                payload = torch.load(fixture.checkpoint1, map_location="cpu", weights_only=True)
                payload["seed"] = seed; payload["split_id"] = "tiny_b4_split"
                key = "scalar_head.4.bias"; payload["head_state_dict"][key] = payload["head_state_dict"][key] + index*0.001
                path = root / f"old_{seed}.pt"; torch.save(payload, path); checkpoints.append(path)
            old_args = fixture.args(); old_args.checkpoint = checkpoints; old_args.output_dir = root / "old_output"
            torch.manual_seed(12345)
            BASE_INFER.infer(old_args)
            results = []
            for seed, checkpoint in zip((43, 917, 1931, 3253), checkpoints):
                payload = torch.load(checkpoint, weights_only=True); payload["schema_version"] = PROFILE.CHECKPOINT_SCHEMA; torch.save(payload, checkpoint)
                result = root / f"result_{seed}.json"
                value = ProfileFixture.result_payload(seed, sha(checkpoint)); value["backbone_identity_sha256"] = "tiny_synthetic"
                value["split"]["split_id"] = "tiny_b4_split"; write_json(result, value); results.append(result)
            first = torch.load(checkpoints[0], weights_only=True)
            signature, tensors, parameters = PROFILE.state_signature(first["head_state_dict"])
            profile = PROFILE.B4Profile(
                profile_id="tiny_equivalence", seeds=tuple(PROFILE.SeedProfile(s, sha(c), sha(r)) for s,c,r in zip((43,917,1931,3253),checkpoints,results)),
                split_id="tiny_b4_split", backbone_sha256="tiny_synthetic",
                head_config_sha256=PROFILE.canonical_sha256(first["head_config"]),
                state_signature_sha256=signature, tensor_count=tensors, parameter_count=parameters,
            )
            new_args = fixture.args(); new_args.checkpoint = checkpoints; new_args.output_dir = root / "new_output"
            torch.manual_seed(12345)
            PROFILE.infer_profiled(BASE_INFER, new_args, results, root / "profile_receipt.json", profile)
            self.assertEqual((old_args.output_dir / BASE_INFER.OUTPUT_NAME).read_bytes(), (new_args.output_dir / BASE_INFER.OUTPUT_NAME).read_bytes())


class RecoveryTerminalTests(unittest.TestCase):
    def test_13_valid_terminal_closes_all_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); terminal = fixture.terminal()
            self.assertEqual(terminal["status"], VALIDATOR.TERMINAL_STATUS)
            self.assertTrue(terminal["L1"]["reused_without_recomputation"])

    def test_14_nonfinite_b_output_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); fixture.write_predictions(fixture.b_output, 4, nonfinite=True)
            receipt = json.loads(fixture.b_receipt.read_text()); receipt["outputs"][VALIDATOR.PREDICTION_NAME] = sha(fixture.b_output); write_json(fixture.b_receipt, receipt)
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "prediction_nonfinite"):
                fixture.terminal()

    def test_15_candidate_sequence_order_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); fixture.write_predictions(fixture.b_output, 4, identity_drift=True)
            receipt = json.loads(fixture.b_receipt.read_text()); receipt["outputs"][VALIDATOR.PREDICTION_NAME] = sha(fixture.b_output); write_json(fixture.b_receipt, receipt)
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "prediction_identity_or_order_mismatch"):
                fixture.terminal()

    def test_16_exact_min_violation_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); fixture.write_predictions(fixture.b_output, 4, exact_drift=True)
            receipt = json.loads(fixture.b_receipt.read_text()); receipt["outputs"][VALIDATOR.PREDICTION_NAME] = sha(fixture.b_output); write_json(fixture.b_receipt, receipt)
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "checkpoint_exact_min_row"):
                fixture.terminal()

    def test_17_checkpoint_hash_or_seed_drift_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); receipt = json.loads(fixture.b_receipt.read_text())
            receipt["input_bindings"]["checkpoints"][0]["seed"] = 99; write_json(fixture.b_receipt, receipt)
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "b_receipt_seed_set_or_order"):
                fixture.terminal()

    def test_18_preflight_input_mutation_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); fixture.failed_log.write_text(fixture.failed_log.read_text()+"changed\n")
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "preflight_inputs_changed"):
                fixture.terminal()

    def test_19_old_failure_reason_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary)); fixture.failed_log.write_text("other failure\n")
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "failed_b_log_reason_mismatch"):
                fixture.preflight()

    def test_20_atomic_publication_refuses_existing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "terminal.json"; target.write_text("existing")
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "publication_target_exists"):
                VALIDATOR.atomic_json(target, {"status": "PASS"})

    def test_21_graph_cache_mutation_after_preflight_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary))
            fixture.graph_cache.write_bytes(b"mutated graph cache\n")
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "graph_cache_receipt_hash_mismatch"):
                fixture.terminal()

    def test_22_graph_manifest_mutation_after_preflight_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TerminalFixture(Path(temporary))
            fixture.graph_manifest.write_text("mutated\n", encoding="utf-8")
            with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "graph_manifest_receipt_hash_mismatch"):
                fixture.terminal()

    def test_23_extra_truth_or_numeric_column_fails_exact_header(self):
        for extra in ("R_dual_min_truth", "unexpected_numeric_score"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                fixture = TerminalFixture(Path(temporary))
                with fixture.b_output.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle, delimiter="\t")
                    fields = list(reader.fieldnames or ())
                    rows = list(reader)
                for row in rows:
                    row[extra] = "0.5"
                write_tsv(fixture.b_output, [*fields, extra], rows)
                receipt = json.loads(fixture.b_receipt.read_text())
                receipt["outputs"][VALIDATOR.PREDICTION_NAME] = sha(fixture.b_output)
                write_json(fixture.b_receipt, receipt)
                with self.assertRaisesRegex(VALIDATOR.RecoveryValidationError, "prediction_header_not_exact_profile"):
                    fixture.terminal()


if __name__ == "__main__":
    unittest.main()
