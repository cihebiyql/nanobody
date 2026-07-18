import json
import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import build_prefreeze_manifest_v2 as builder
from . import materialize_postcalibration_freeze_v1 as historical_materializer
from . import materialize_postcalibration_freeze_v2 as materializer_v2
from . import node1_v2_4_outer_development_launcher_v2 as launcher_v2
from . import run_open_only_prestep_calibration_v2 as calibration_v2


REPO = Path(__file__).resolve().parents[5]


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_trainer_table(path: Path, *, pair: bool) -> None:
    common = ["schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source"]
    fields = common + (
        [
            "receptor", "vhh_sequence_index", "vhh_aa", "pvrig_node_index",
            "pvrig_uniprot_position", "pvrig_aa", "contact_target", "contact_variance",
            "contact_uncertainty_weight", "target_mask",
        ]
        if pair else [
            "vhh_sequence_index", "vhh_aa", "contact_target_8x6b", "contact_target_9e6y",
            "contact_variance_8x6b", "contact_variance_9e6y",
            "contact_uncertainty_weight_8x6b", "contact_uncertainty_weight_9e6y",
            "target_mask_8x6b", "target_mask_9e6y",
        ]
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for index in range(1507):
            source = "V4D_OPEN_MULTI_SEED" if index < 226 else "V4H_ADAPTIVE_SEED_RANKING"
            row = {
                "schema_version": "pvrig_v2_4_adaptive_trainer_table_v1",
                "candidate_id": f"C{index:04d}", "sequence_sha256": f"{index:064x}",
                "parent_framework_cluster": f"P{index % 31:02d}", "teacher_source": source,
                "vhh_sequence_index": 0, "vhh_aa": "A",
            }
            if pair:
                row.update({
                    "receptor": "8x6b", "pvrig_node_index": 0,
                    "pvrig_uniprot_position": 1, "pvrig_aa": "A", "contact_target": 0.0,
                    "contact_variance": 0.0, "contact_uncertainty_weight": 1.0, "target_mask": 1,
                })
            else:
                row.update({
                    "contact_target_8x6b": 0.0, "contact_target_9e6y": 0.0,
                    "contact_variance_8x6b": 0.0, "contact_variance_9e6y": 0.0,
                    "contact_uncertainty_weight_8x6b": 1.0, "contact_uncertainty_weight_9e6y": 1.0,
                    "target_mask_8x6b": 1, "target_mask_9e6y": 1,
                })
            writer.writerow(row)


class AdaptiveFixture:
    def __init__(self, root: Path, *, marginal_name: str = "dual_adaptive_marginal.tsv.gz") -> None:
        self.root = root
        self.source = root / "v4h_adaptive_RUN_RECEIPT.json"
        self.v4d_source = root / "v4d_adaptive_source_RUN_RECEIPT.json"
        self.marginal = root / marginal_name
        self.pair = root / "dual_adaptive_pair.tsv.gz"
        self.marginal_receipt = root / "adaptive_marginal_receipt.json"
        self.pair_receipt = root / "adaptive_pair_receipt.json"
        self.contract = root / "adaptive_input_contract.json"
        write_trainer_table(self.marginal, pair=False)
        write_trainer_table(self.pair, pair=True)
        source_payload = {
            "schema_version": builder.SOURCE_RECEIPT_SCHEMA,
            "status": builder.SOURCE_RECEIPT_STATUS,
            "candidate_rows": 1320,
            "valid_candidate_rows": 1281,
            "technical_incomplete_candidate_rows": 39,
            "selected_paired_job_rows": 3536,
            "source_mutation_operations": 0,
            "contract_sha256": "3" * 64,
            "reconciliation_receipt_sha256": "4" * 64,
            "implementation_sha256": "5" * 64,
            "pair_rows": 100,
            "residue_rows": 200,
            "output_hashes": {
                "v4h_adaptive_residue_pair_contact_teacher.tsv.gz": "1" * 64,
                "v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz": "2" * 64,
            },
        }
        write_json(self.source, source_payload)
        source_sha = builder.sha256_file(self.source)
        write_json(self.v4d_source, {
            "schema_version": builder.V4D_RECEIPT_SCHEMA,
            "status": builder.V4D_RECEIPT_STATUS,
            "counts": {"teacher_candidates": 226, "zero_imputed_failed_seeds": 0},
            "source": {"source_mutation_operations": 0},
        })
        v4d_source_sha = builder.sha256_file(self.v4d_source)
        for lane, path, table, schema, status in (
            ("marginal", self.marginal_receipt, self.marginal, builder.MARGINAL_RECEIPT_SCHEMA, builder.MARGINAL_RECEIPT_STATUS),
            ("pair", self.pair_receipt, self.pair, builder.PAIR_RECEIPT_SCHEMA, builder.PAIR_RECEIPT_STATUS),
        ):
            write_json(path, {
                "schema_version": schema,
                "status": status,
                "teacher_generation": builder.ADAPTIVE_TEACHER_GENERATION,
                "training_tsv_sha256": builder.TRAINING_TSV_SHA,
                "v4h_adaptive_source_receipt_sha256": source_sha,
                "v4d_source_receipt_sha256": v4d_source_sha,
                "v4h_adaptive_raw_pair_teacher_sha256": "1" * 64,
                "v4h_adaptive_raw_marginal_teacher_sha256": "2" * 64,
                "output": {"sha256": builder.sha256_file(table)},
                "candidate_rows": 1507,
                "v4d_candidate_rows": 226,
                "v4h_valid_candidate_rows": 1281,
                "v4h_technical_incomplete_excluded": 39,
                "legacy_stage1_rows": 0,
                "lane": lane,
            })
        files = {
            "v4h_adaptive_source_receipt": self.source,
            "v4d_source_receipt": self.v4d_source,
            "adaptive_marginal_tsv_gz": self.marginal,
            "adaptive_marginal_receipt": self.marginal_receipt,
            "adaptive_pair_tsv_gz": self.pair,
            "adaptive_pair_receipt": self.pair_receipt,
        }
        contract_payload = {
            "schema_version": builder.ADAPTIVE_CONTRACT_SCHEMA,
            "status": builder.ADAPTIVE_CONTRACT_STATUS,
            "teacher_generation": builder.ADAPTIVE_TEACHER_GENERATION,
            "legacy_stage1_inputs_forbidden": True,
            "training_tsv_sha256": builder.TRAINING_TSV_SHA,
            "expected_counts": builder.EXPECTED_COUNTS,
            "v4h_source_provenance": {
                "contract_sha256": "3" * 64,
                "reconciliation_receipt_sha256": "4" * 64,
                "implementation_sha256": "5" * 64,
            },
            "artifacts": {
                label: {"sha256": builder.sha256_file(path), "size_bytes": path.stat().st_size}
                for label, path in files.items()
            },
        }
        write_json(self.contract, contract_payload)

    def validate(self):
        return builder.validate_adaptive_inputs(
            input_contract_path=self.contract,
            expected_input_contract_sha256=builder.sha256_file(self.contract),
            source_receipt_path=self.source,
            v4d_source_receipt_path=self.v4d_source,
            marginal_table_path=self.marginal,
            marginal_receipt_path=self.marginal_receipt,
            pair_table_path=self.pair,
            pair_receipt_path=self.pair_receipt,
        )


class V2AdaptiveMigrationTests(unittest.TestCase):
    def test_v1_materializer_is_immutable_and_v2_is_distinct(self) -> None:
        self.assertEqual(builder.sha256_file(Path(historical_materializer.__file__)), builder.POSTCAL_V1_HISTORICAL_SHA)
        historical_test = Path(historical_materializer.__file__).with_name("test_materialize_postcalibration_freeze_v1.py")
        self.assertEqual(builder.sha256_file(historical_test), builder.POSTCAL_TEST_V1_HISTORICAL_SHA)
        self.assertNotEqual(builder.sha256_file(Path(materializer_v2.__file__)), builder.POSTCAL_V1_HISTORICAL_SHA)
        self.assertEqual(materializer_v2.MANIFEST_SCHEMA, builder.MANIFEST_SCHEMA)

    def test_adaptive_receipt_closure_and_full_manifest_materialization(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO) as tmp:
            root = Path(tmp)
            fixture = AdaptiveFixture(root)
            adaptive = fixture.validate()
            self.assertEqual(adaptive["status"], builder.ADAPTIVE_CONTRACT_STATUS)
            output = root / "V2_4_NODE1_PREFREEZE_MANIFEST_V2.json"
            result = builder.run(
                repo=REPO, output=output, input_contract=fixture.contract,
                expected_input_contract_sha256=builder.sha256_file(fixture.contract),
                source_receipt=fixture.source, marginal_table=fixture.marginal,
                v4d_source_receipt=fixture.v4d_source,
                marginal_receipt=fixture.marginal_receipt, pair_table=fixture.pair,
                pair_receipt=fixture.pair_receipt,
            )
            self.assertTrue(result["status"].startswith("PASS_V2_ADAPTIVE"))
            manifest = json.loads(output.read_text())
            self.assertEqual(manifest["schema_version"], builder.MANIFEST_SCHEMA)
            self.assertEqual(manifest["status"], builder.MANIFEST_STATUS)
            self.assertEqual(manifest["calibration_contract"]["fixed_grid"], [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0])
            self.assertEqual(manifest["trainer"]["calibration_artifact_label"], "calibration_trainer")
            self.assertEqual(manifest["calibration_contract"]["target_median_gradient_fraction_band"], [0.05, 0.15])
            self.assertEqual(manifest["calibration_contract"]["maximum_per_batch_gradient_fraction"], 0.30)
            batch_selection = manifest["calibration_contract"]["batch_selection"]
            self.assertEqual(len(batch_selection["batch_records"]), 8)
            self.assertEqual(
                [record["batch_offset"] for record in batch_selection["batch_records"]],
                [0, 22, 44, 67, 89, 112, 134, 157],
            )
            self.assertEqual(
                len({candidate for record in batch_selection["batch_records"] for candidate in record["candidate_ids"]}),
                64,
            )
            self.assertEqual(manifest["calibration_contract"]["calibration_runtime_root"], builder.CALIBRATION_RUNTIME)
            self.assertEqual(manifest["artifacts"]["v23_freeze"]["node1_path"], f"{builder.V23_BUNDLE}/residue_v2/IMPLEMENTATION_FREEZE_V2.json")
            self.assertNotIn("dual_marginal_tsv_gz", manifest["artifacts"])
            self.assertNotIn("dual_pair_tsv_gz", manifest["artifacts"])
            self.assertEqual(manifest["artifacts"]["postcalibration_materializer"]["sha256"], builder.sha256_file(Path(materializer_v2.__file__)))
            self.assertEqual(launcher_v2.load_manifest(output, allow_pending_calibration=True)["manifest_generation"], "V2_ADAPTIVE_MULTI_SEED")
            dry = launcher_v2.dry_run_plan(output)
            self.assertEqual(dry["status"], "PASS_V2_ADAPTIVE_PREFREEZE_DRY_RUN_BLOCKED_PENDING_CALIBRATION")
            self.assertEqual(dry["outer_development_command_count"], 0)
            calibration_dry = calibration_v2.dry_run(output)
            self.assertEqual(calibration_dry["status"], "PASS_V2_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION_DRY_RUN_NO_MUTATION")
            self.assertIn("{adaptive_marginal_tsv_gz}", manifest["trainer"]["argv_template"])

    def test_old_stage1_table_is_rejected_even_if_contract_binds_its_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AdaptiveFixture(Path(tmp), marginal_name="v4h_stage1_contact_teacher.tsv.gz")
            with self.assertRaisesRegex(builder.ManifestV2Error, "legacy_stage1_input_forbidden"):
                fixture.validate()

    def test_adaptive_receipt_source_closure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = AdaptiveFixture(Path(tmp))
            receipt = json.loads(fixture.marginal_receipt.read_text())
            receipt["v4h_adaptive_source_receipt_sha256"] = "0" * 64
            write_json(fixture.marginal_receipt, receipt)
            contract = json.loads(fixture.contract.read_text())
            contract["artifacts"]["adaptive_marginal_receipt"] = {
                "sha256": builder.sha256_file(fixture.marginal_receipt),
                "size_bytes": fixture.marginal_receipt.stat().st_size,
            }
            write_json(fixture.contract, contract)
            with self.assertRaisesRegex(builder.ManifestV2Error, "adaptive_marginal_source_receipt_sha"):
                fixture.validate()

    def test_runtime_presence_blocks_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            with mock.patch.object(builder, "RUNTIME", str(runtime)):
                with self.assertRaisesRegex(builder.ManifestV2Error, "runtime_must_be_absent"):
                    builder.compose_payload({}, {
                        "status": builder.ADAPTIVE_CONTRACT_STATUS,
                        "teacher_generation": builder.ADAPTIVE_TEACHER_GENERATION,
                    })

    def test_calibration_runtime_presence_blocks_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calibration = Path(tmp) / "calibration"
            calibration.mkdir()
            with mock.patch.object(builder, "CALIBRATION_RUNTIME", str(calibration)):
                with self.assertRaisesRegex(builder.ManifestV2Error, "calibration_runtime_must_be_absent"):
                    builder.compose_payload({}, {
                        "status": builder.ADAPTIVE_CONTRACT_STATUS,
                        "teacher_generation": builder.ADAPTIVE_TEACHER_GENERATION,
                    })

    def test_missing_inputs_report_blocked_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = builder.input_preflight({"adaptive_pair_table": Path(tmp) / "missing.tsv.gz"})
            self.assertEqual(status["status"], "BLOCKED_INPUT_ADAPTIVE_ARTIFACTS_NOT_MATERIALIZED")
            self.assertFalse(status["production_authorized"])

    def test_v2_calibration_receipt_binds_adaptive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}")
            batch_records = []
            for batch_index in range(8):
                candidate_ids = [f"B{batch_index:02d}_C{candidate_index:02d}" for candidate_index in range(8)]
                batch_records.append({
                    "batch_id": f"B{batch_index:02d}_OFFSET_{batch_index:04d}",
                    "batch_offset": batch_index,
                    "forward_seed": 1_000_046 + batch_index,
                    "candidate_ids": candidate_ids,
                    "candidate_ids_sha256": builder.canonical_candidate_ids_sha256(candidate_ids),
                    "candidate_count": 8,
                    "teacher_source_counts": {"V4H_ADAPTIVE_SEED_RANKING": 8},
                    "contact_tier_counts": {"C": 8},
                    "parent_framework_clusters": [f"P{batch_index:02d}"],
                })
            manifest = {
                "claim_boundary": "computational only",
                "artifacts": {
                    "trainer": {"sha256": "a" * 64},
                    "calibration_trainer": {"sha256": "f" * 64},
                    "calibration_runner": {"sha256": "b" * 64},
                },
                "adaptive_supervision": {
                    "input_contract_sha256": "c" * 64,
                    "source_receipt_sha256": "d" * 64,
                    "v4d_source_receipt_sha256": "e" * 64,
                    "teacher_generation": builder.ADAPTIVE_TEACHER_GENERATION,
                },
                "calibration_contract": {
                    "fixed_grid": [0.25, 0.5], "pair_to_marginal_ratio": 0.5,
                    "target_median_gradient_fraction_band": [0.05, 0.15],
                    "maximum_per_batch_gradient_fraction": 0.30,
                    "batch_selection": {"contract_sha256": "9" * 64, "batch_records": batch_records},
                    "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
                },
            }
            observations = {}
            for lane in calibration_v2.CALIBRATION_LANES:
                path = root / f"{lane}.json"
                payload = {
                    "schema_version": calibration_v2.OBSERVATION_SCHEMA,
                    "status": calibration_v2.OBSERVATION_STATUS,
                    "lane": lane, "open_only": True, "optimizer_constructed": False,
                    "optimizer_steps_before_observation": 0, "outer_metrics_access_count": 0,
                    "prediction_metrics_access_count": 0, "v4_f_test32_access_count": 0,
                    "fixed_grid": [0.25, 0.5], "pair_to_marginal_ratio": 0.5,
                    "target_median_gradient_fraction_band": [0.05, 0.15],
                    "maximum_per_batch_gradient_fraction": 0.30,
                    "selection_rule": calibration_v2.OBSERVATION_SELECTION_RULE,
                    "calibration_batch_count": 8,
                    "calibration_batch_offsets": list(range(8)),
                    "calibration_batch_provenance": batch_records,
                    "selected_contact_weights": {"marginal": 0.5, "pair": 0.0 if lane.startswith("C_") else 0.25},
                    "observations": [
                        {
                            "marginal_weight": marginal,
                            "pair_weight": 0.0 if lane.startswith("C_") else marginal * 0.5,
                            "per_batch": [
                                {
                                    "batch_id": record["batch_id"],
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
                                for record in batch_records
                            ],
                            "median_contact_gradient_fraction": fraction,
                            "maximum_contact_gradient_fraction": fraction,
                            "eligible": eligible,
                        }
                        for marginal, fraction, eligible in ((0.25, 0.03, False), (0.5, 0.08, True))
                    ],
                }
                write_json(path, payload)
                observations[lane] = (path, payload, lane)
            receipt = calibration_v2.aggregate_receipt(manifest_path, manifest, observations)
            self.assertEqual(receipt["schema_version"], calibration_v2.CALIBRATION_SCHEMA)
            self.assertEqual(receipt["calibration_trainer_sha256"], "f" * 64)
            self.assertEqual(receipt["calibration_batch_count"], 8)
            self.assertEqual(receipt["adaptive_input_contract_sha256"], "c" * 64)
            self.assertEqual(receipt["adaptive_source_receipt_sha256"], "d" * 64)
            self.assertEqual(receipt["adaptive_v4d_source_receipt_sha256"], "e" * 64)


if __name__ == "__main__":
    unittest.main()
