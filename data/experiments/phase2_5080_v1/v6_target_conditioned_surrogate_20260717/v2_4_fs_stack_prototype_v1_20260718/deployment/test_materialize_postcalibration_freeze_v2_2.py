import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from . import materialize_postcalibration_freeze_v2_2 as mod
from . import node1_v2_4_outer_development_launcher_v2_2 as launcher


FORMULA = {
    "formula_version": mod.FORMULA_VERSION,
    "receptors": ["R8", "R9"],
    "inputs_per_receptor": ["hotspot_contact_mass", "interface_specificity"],
    "weights": mod.FORMULA_WEIGHTS,
    "intercept": 0.0,
    "clipping": False,
    "label_access": False,
    "outer_result_tuning": False,
}


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact(path: Path) -> dict:
    return {
        "source_path": str(path),
        "node1_path": str(path),
        "sha256": mod.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "validation_mode": "LOCAL_SOURCE_AND_NODE1",
    }


class PostCalibrationFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.runtime = self.root / "production_runtime"
        self.calibration_root = self.root / "calibration_runtime"
        self.calibration_root.mkdir()
        self.prefreeze = self.bundle / "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2.json"
        self.receipt = self.bundle / "CALIBRATION_RECEIPT.json"
        self.ready = self.bundle / "V2_4_NODE1_READY_MANIFEST_V2_2.json"
        self.freeze = self.bundle / "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2.json"

        files = {}
        for label in (
            "trainer", "calibration_trainer", "calibration_runner", "outer_split_0",
            "vhh_graph_cache_npz", "bundle_materializer", "v2_2_supersession_audit",
        ):
            path = self.bundle / "inputs" / f"{label}.dat"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((label + "\n").encode())
            files[label] = artifact(path)
        files["deployment_launcher"] = artifact(Path(launcher.__file__).resolve())
        files["postcalibration_materializer"] = artifact(Path(mod.__file__).resolve())
        for label in (
            "adaptive_input_contract", "v4h_adaptive_source_receipt",
            "v4d_source_receipt",
            "adaptive_marginal_tsv_gz", "adaptive_marginal_receipt",
            "adaptive_pair_tsv_gz", "adaptive_pair_receipt",
        ):
            path = self.bundle / "inputs" / f"{label}.dat"
            path.write_bytes((label + "\n").encode())
            files[label] = artifact(path)
        formula_path = self.bundle / "inputs" / "contact_formula.json"
        write_json(formula_path, FORMULA)
        files["contact_formula"] = artifact(formula_path)

        self.batch_records = []
        for batch_index in range(8):
            candidate_ids = [f"B{batch_index:02d}_C{candidate_index:02d}" for candidate_index in range(8)]
            candidate_digest = hashlib.sha256(
                "".join(f"{candidate_id}\n" for candidate_id in candidate_ids).encode("utf-8")
            ).hexdigest()
            self.batch_records.append({
                "batch_id": f"B{batch_index:02d}_OFFSET_{batch_index:04d}",
                "batch_offset": batch_index,
                "forward_seed": 1_000_046 + batch_index,
                "candidate_ids": candidate_ids,
                "candidate_ids_sha256": candidate_digest,
                "candidate_count": 8,
                "teacher_source_counts": {"V4H_ADAPTIVE_SEED_RANKING": 8},
                "contact_tier_counts": {"C": 8},
                "parent_framework_clusters": [f"P{batch_index:02d}"],
            })

        self.manifest = {
            "schema_version": mod.MANIFEST_SCHEMA,
            "manifest_generation": "V2_2_ADAPTIVE_MULTI_SEED_CLAIM_ALIGNED",
            "status": mod.PENDING_STATUS,
            "production_authorized": False,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "claim_boundary": mod.CLAIM_BOUNDARY,
            "bundle_root": str(self.bundle),
            "runtime_root": str(self.runtime),
            "python": mod.NODE1_PYTHON,
            "runtime_must_remain_absent_until_implementation_freeze": True,
            "resources": {
                "lane_gpu_map": mod.LANE_GPU,
                "cpu_threads_per_process": 8,
                "thread_environment": mod.THREAD_ENVIRONMENT,
            },
            "execution": {
                "phase_order": mod.PHASE_ORDER,
                "outer_folds": [0, 1, 2, 3, 4],
                "lanes_concurrent": 4,
                "folds_sequential_within_lane": True,
                "tiny_smoke_must_pass_all_lanes": True,
                "automatic_smoke_to_outer_transition": False,
            },
            "adaptive_supervision": {
                "status": mod.ADAPTIVE_INPUT_STATUS,
                "teacher_generation": mod.ADAPTIVE_TEACHER_GENERATION,
                "legacy_stage1_inputs_forbidden": True,
                "input_contract_artifact_label": "adaptive_input_contract",
                "source_receipt_artifact_label": "v4h_adaptive_source_receipt",
                "input_contract_sha256": files["adaptive_input_contract"]["sha256"],
                "source_receipt_sha256": files["v4h_adaptive_source_receipt"]["sha256"],
                "v4d_source_receipt_sha256": files["v4d_source_receipt"]["sha256"],
            },
            "technical_supersession": {
                "version": mod.SUPERSESSION_VERSION,
                "scope": "claim-boundary emission and exact validation only",
                "numeric_method_changes": 0,
                "v2_1_selected_contact_weights": mod.EXPECTED_CONTACT_WEIGHTS,
            },
            "artifacts": files,
            "trainer": {
                "artifact_label": "trainer",
                "calibration_artifact_label": "calibration_trainer",
                "argv_template": [
                    "{python}", "{trainer}", "--lane", "{lane}", "--output-dir", "{output_dir}",
                    "--split-manifest", "{split_manifest}", "--graph-cache-dir", "{vhh_graph_dir}",
                    "--contact-tsv-gz", "{adaptive_marginal_tsv_gz}",
                    "--pair-contact-tsv-gz", "{adaptive_pair_tsv_gz}",
                    "--contact-formula-json", "{contact_formula}",
                ],
                "tiny_smoke_extra_argv": ["--tiny-e2e"],
                "outer_development_extra_argv": None,
                "lane_outer_extra_argv": None,
                "required_result_file": "RESULT.json",
                "frozen_noncalibration_parameters": {
                    "fixed_epochs": 8,
                    "graph_hidden_dim": 128,
                    "dropout": 0.25,
                    "batch_size": 8,
                    "precision": "bf16",
                },
            },
            "calibration_contract": {
                "binding_status": "PENDING_V2_2_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION",
                "receipt_artifact_label": None,
                "calibration_runtime_root": str(self.calibration_root),
                "calibration_receipt_node1_path": str(self.receipt),
                "open_only": True,
                "optimizer_steps_before_observation": 0,
                "outer_metrics_access_count": 0,
                "prediction_metrics_access_count": 0,
                "fixed_grid": [0.5, 1.0, 1.5, 2.0],
                "pair_to_marginal_ratio": 0.5,
                "target_median_gradient_fraction_band": [0.05, 0.15],
                "maximum_per_batch_gradient_fraction": 0.30,
                "selection_rule": mod.MANIFEST_SELECTION_RULE,
                "batch_selection": {
                    "selection_algorithm": "evenly_spaced_complete_batches_after_python_random_seed_shuffle_v1",
                    "seed": 43,
                    "batch_size": 8,
                    "batch_records": self.batch_records,
                    "contract_sha256": "9" * 64,
                },
                "frozen_lane_contact_weights": None,
                "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
            },
            "pending": ["CALIBRATION_RECEIPT.json", "frozen_lane_contact_weights", "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2.json"],
        }
        write_json(self.prefreeze, self.manifest)
        self._write_calibration_evidence()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _observation(self, lane: str) -> dict:
        ratio = self.manifest["calibration_contract"]["pair_to_marginal_ratio"]
        rows = []
        fractions = (
            [0.02, 0.04, 0.08, 0.10]
            if lane == "C_SPLIT_MARGINAL"
            else [0.03, 0.08, 0.12, 0.16]
        )
        for marginal, fraction in zip(self.manifest["calibration_contract"]["fixed_grid"], fractions):
            rows.append({
                "marginal_weight": marginal,
                "pair_weight": 0.0 if lane == "C_SPLIT_MARGINAL" else marginal * ratio,
                "per_batch": [
                    {
                        "batch_id": record["batch_id"],
                        "batch_offset": record["batch_offset"],
                        "candidate_ids_sha256": record["candidate_ids_sha256"],
                        "scalar_gradient_l2_norm": 1.0 - fraction,
                        "contact_gradient_l2_norm": fraction,
                        "contact_gradient_fraction": fraction,
                        "scalar_contact_cosine": 0.0,
                        "gradient_groups": {
                            group: {
                                "parameter_tensor_count": 1,
                                "scalar_gradient_l2_norm": 1.0 - fraction,
                                "contact_gradient_l2_norm": fraction,
                                "scalar_contact_cosine": 0.0,
                            }
                            for group in (
                                "shared_encoder", "pair_factors",
                                "attention_contact_terminals", "scalar_head",
                            )
                        },
                    }
                    for record in self.batch_records
                ],
                "median_contact_gradient_fraction": fraction,
                "maximum_contact_gradient_fraction": fraction,
                "eligible": 0.05 <= fraction <= 0.15 and fraction <= 0.30,
            })
        return {
            "schema_version": mod.OBSERVATION_SCHEMA,
            "status": mod.OBSERVATION_STATUS,
            "lane": lane,
            "open_only": True,
            "optimizer_constructed": False,
            "optimizer_steps_before_observation": 0,
            "outer_metrics_access_count": 0,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
            "fixed_grid": self.manifest["calibration_contract"]["fixed_grid"],
            "pair_to_marginal_ratio": ratio,
            "target_median_gradient_fraction_band": self.manifest["calibration_contract"]["target_median_gradient_fraction_band"],
            "maximum_per_batch_gradient_fraction": self.manifest["calibration_contract"]["maximum_per_batch_gradient_fraction"],
            "selection_rule": mod.OBSERVATION_SELECTION_RULE,
            "calibration_batch_count": 8,
            "calibration_batch_offsets": list(range(8)),
            "calibration_batch_provenance": self.batch_records,
            "selected_contact_weights": {
                "marginal": 1.5 if lane == "C_SPLIT_MARGINAL" else 1.0,
                "pair": 0.0 if lane == "C_SPLIT_MARGINAL" else 0.5,
            },
            "observations": rows,
            "observed_training_batch_candidate_ids": [f"{lane}_candidate"],
            "split": {"outer_fold": 0, "open_only": True, "v4_f_test32_access_count": 0, "fixed_epochs": 8},
            "technical_supersession_version": mod.SUPERSESSION_VERSION,
            "claim_boundary": self.manifest["claim_boundary"],
        }

    def _write_calibration_evidence(self) -> None:
        lane_records = {}
        weights = {
            "A_VHH_ONLY": {"marginal": 0.0, "pair": 0.0},
            "B_TARGET_NO_CONTACT": {"marginal": 0.0, "pair": 0.0},
        }
        for lane in mod.CONTACT_LANES:
            path = self.calibration_root / lane / "CALIBRATION_OBSERVATION.json"
            payload = self._observation(lane)
            write_json(path, payload)
            selected = payload["selected_contact_weights"]
            weights[lane] = selected
            command = mod.calibration_command(self.manifest, lane, path.parent)
            lane_records[lane] = {
                "path": str(path),
                "sha256": mod.sha256_file(path),
                "command_sha256": mod.command_sha256(command),
                "selected_contact_weights": selected,
            }
        receipt = {
            "schema_version": mod.CALIBRATION_SCHEMA,
            "status": mod.CALIBRATION_STATUS,
            "manifest_sha256": mod.sha256_file(self.prefreeze),
            "trainer_sha256": self.manifest["artifacts"]["trainer"]["sha256"],
            "calibration_trainer_sha256": self.manifest["artifacts"]["calibration_trainer"]["sha256"],
            "calibration_runner_sha256": self.manifest["artifacts"]["calibration_runner"]["sha256"],
            "open_only": True,
            "optimizer_constructed_before_observation": False,
            "optimizer_steps_before_observation": 0,
            "outer_metrics_access_count": 0,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
            "fixed_grid": self.manifest["calibration_contract"]["fixed_grid"],
            "pair_to_marginal_ratio": self.manifest["calibration_contract"]["pair_to_marginal_ratio"],
            "target_median_gradient_fraction_band": self.manifest["calibration_contract"]["target_median_gradient_fraction_band"],
            "maximum_per_batch_gradient_fraction": self.manifest["calibration_contract"]["maximum_per_batch_gradient_fraction"],
            "calibration_batch_count": 8,
            "calibration_batch_contract_sha256": self.manifest["calibration_contract"]["batch_selection"]["contract_sha256"],
            "selection_rule": mod.RECEIPT_SELECTION_RULE,
            "technical_supersession_version": mod.SUPERSESSION_VERSION,
            "v2_1_selected_weight_equivalence_required": mod.EXPECTED_CONTACT_WEIGHTS,
            "frozen_lane_contact_weights": weights,
            "attention_temperatures": self.manifest["calibration_contract"]["attention_temperatures"],
            "adaptive_input_contract_sha256": self.manifest["adaptive_supervision"]["input_contract_sha256"],
            "adaptive_source_receipt_sha256": self.manifest["adaptive_supervision"]["source_receipt_sha256"],
            "adaptive_v4d_source_receipt_sha256": self.manifest["adaptive_supervision"]["v4d_source_receipt_sha256"],
            "adaptive_teacher_generation": mod.ADAPTIVE_TEACHER_GENERATION,
            "lane_observations": lane_records,
            "implementation_freeze_created": False,
            "production_runtime_created": False,
            "claim_boundary": self.manifest["claim_boundary"],
        }
        write_json(self.receipt, receipt)

    def run_materializer(self, alias: Path | None = None):
        return mod.materialize(
            prefreeze_manifest_path=self.prefreeze,
            calibration_receipt_path=self.receipt,
            ready_manifest_path=self.ready,
            freeze_path=self.freeze,
            test_only_contact_formula_alias=alias,
        )

    def rewrite_receipt(self, mutate) -> None:
        payload = json.loads(self.receipt.read_text())
        mutate(payload)
        write_json(self.receipt, payload)

    def rewrite_observation(self, lane: str, mutate, refresh_receipt_hash: bool = True) -> None:
        path = self.calibration_root / lane / "CALIBRATION_OBSERVATION.json"
        payload = json.loads(path.read_text())
        mutate(payload)
        write_json(path, payload)
        if refresh_receipt_hash:
            receipt = json.loads(self.receipt.read_text())
            receipt["lane_observations"][lane]["sha256"] = mod.sha256_file(path)
            write_json(self.receipt, receipt)

    def test_materializes_ready_manifest_and_freeze_with_test_only_alias(self) -> None:
        alias = self.bundle / "contact_contract" / "contact_score_formula_v1.json"
        alias.parent.mkdir()
        alias.write_bytes(Path(self.manifest["artifacts"]["contact_formula"]["node1_path"]).read_bytes())
        result = self.run_materializer(alias)
        self.assertEqual(result["status"], mod.FREEZE_STATUS)
        self.assertFalse(result["production_runtime_created"])
        self.assertFalse(self.runtime.exists())

        ready = json.loads(self.ready.read_text())
        freeze = json.loads(self.freeze.read_text())
        self.assertEqual(ready["status"], mod.READY_STATUS)
        self.assertEqual(ready["calibration_contract"]["frozen_lane_contact_weights"]["D_SPLIT_PAIR"], {"marginal": 1.0, "pair": 0.5})
        self.assertEqual(ready["trainer"]["lane_outer_extra_argv"]["C_SPLIT_MARGINAL"], ["--marginal-weight", "1.5", "--pair-weight", "0.0"])
        self.assertEqual(float(ready["trainer"]["lane_outer_extra_argv"]["D_SPLIT_PAIR"][1]), 1.0)
        self.assertEqual(freeze["manifest_sha256"], mod.sha256_file(self.ready))
        self.assertEqual(freeze["formal_artifact_sha256"], {label: record["sha256"] for label, record in sorted(ready["artifacts"].items())})
        self.assertEqual(freeze["test_only_artifact_aliases"][0]["production_input"], False)
        self.assertNotIn(str(alias), "\0".join(ready["trainer"]["argv_template"]))
        self.assertEqual(freeze["sealed_evaluation_access_count"], 0)
        self.assertEqual(launcher.validate_freeze(self.ready, self.freeze)["status"], launcher.FREEZE_STATUS)

    def test_rejects_optimizer_constructed_observation(self) -> None:
        self.rewrite_observation("C_SPLIT_MARGINAL", lambda payload: payload.__setitem__("optimizer_constructed", True))
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "observation_optimizer_constructed"):
            self.run_materializer()

    def test_rejects_v2_1_base_claim_boundary_observation(self) -> None:
        base_claim = (
            "Open-only computational surrogate of independent 8X6B/9E6Y Docking geometry; "
            "not binding probability, affinity, experimental blocking, Docking Gold, or submission evidence."
        )
        self.rewrite_observation(
            "C_SPLIT_MARGINAL", lambda payload: payload.__setitem__("claim_boundary", base_claim),
        )
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "observation_claim_boundary"):
            self.run_materializer()

    def test_rejects_receipt_manifest_hash_mismatch(self) -> None:
        self.rewrite_receipt(lambda payload: payload.__setitem__("manifest_sha256", "0" * 64))
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "receipt_manifest_sha256"):
            self.run_materializer()

    def test_rejects_calibration_command_hash_that_does_not_bind_formula(self) -> None:
        def mutate(payload):
            payload["lane_observations"]["D_SPLIT_PAIR"]["command_sha256"] = "0" * 64
        self.rewrite_receipt(mutate)
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "observation_command_sha256"):
            self.run_materializer()

    def test_rejects_not_smallest_eligible_grid_selection(self) -> None:
        def mutate(payload):
            row = payload["observations"][0]
            for batch in row["per_batch"]:
                batch["scalar_gradient_l2_norm"] = 0.9
                batch["contact_gradient_l2_norm"] = 0.1
                batch["contact_gradient_fraction"] = 0.1
            row["median_contact_gradient_fraction"] = 0.1
            row["maximum_contact_gradient_fraction"] = 0.1
            row["eligible"] = True
        self.rewrite_observation("C_SPLIT_MARGINAL", mutate)
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "selection_not_smallest_eligible"):
            self.run_materializer()

    def test_rejects_production_runtime_preexistence(self) -> None:
        self.runtime.mkdir()
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "production_runtime_exists_before_freeze"):
            self.run_materializer()

    def test_rejects_formula_semantic_tamper_even_if_manifest_hash_is_updated(self) -> None:
        formula_path = Path(self.manifest["artifacts"]["contact_formula"]["node1_path"])
        formula = json.loads(formula_path.read_text())
        formula["weights"]["hotspot_contact_mass"] = 0.75
        write_json(formula_path, formula)
        self.manifest["artifacts"]["contact_formula"] = artifact(formula_path)
        write_json(self.prefreeze, self.manifest)
        self._write_calibration_evidence()
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "contact_formula_weights"):
            self.run_materializer()

    def test_rejects_test_alias_with_different_hash(self) -> None:
        alias = self.bundle / "contact_contract" / "contact_score_formula_v1.json"
        alias.parent.mkdir()
        alias.write_text("different\n")
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "test_alias_formula_sha256"):
            self.run_materializer(alias)

    def test_outputs_are_immutable_no_overwrite(self) -> None:
        self.ready.write_text("occupied\n")
        with self.assertRaisesRegex(mod.FreezeMaterializationError, "ready_manifest_exists"):
            self.run_materializer()
        self.assertFalse(self.freeze.exists())


if __name__ == "__main__":
    unittest.main()
