#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


MODULE_PATH = Path(__file__).with_name("freeze_phase2_v4_d_contact_feature_schema.py")
SPEC = importlib.util.spec_from_file_location("freeze_phase2_v4_d_contact_feature_schema", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_fixture(root: Path, *, rows: int = 10) -> tuple[Path, Path, Path]:
    feature_path = root / "features.csv"
    audit_path = root / "features.audit.json"
    receipt_path = root / "features.receipt.json"
    frame_rows = []
    for index in range(rows):
        value = index / 10.0
        frame_rows.append(
            {
                "candidate_id": f"c{index}",
                "seed43_signal": value,
                "seed53_signal": value + 0.01,
                "seed67_signal": value - 0.01,
                "signal_seed_mean": value,
                "signal_seed_std": 0.01,
            }
        )
    pd.DataFrame(frame_rows).to_csv(feature_path, index=False)
    audit = {
        "status": "PASS",
        "output_sha256": MOD.sha256_file(feature_path),
        "feature_schema_version": MOD.EXPECTED_FEATURE_SCHEMA_VERSION,
        "checkpoints": [{"seed": seed} for seed in (43, 53, 67)],
        "feature_names": ["signal"],
        "feature_policy": {
            "diagnostic_only_length_confounded_features": sorted(
                MOD.LENGTH_CONFOUNDED_FEATURES
            )
        },
        "label_free_contract": {
            "docking_label_inputs_read": 0,
            "v4d_job_state_read": 0,
            "v4d_raw_results_read": 0,
        },
    }
    audit_path.write_text(json.dumps(audit) + "\n")
    receipt = {
        "status": "PASS",
        "schema_version": "synthetic_feature_receipt_v1",
        "feature_schema_version": MOD.EXPECTED_FEATURE_SCHEMA_VERSION,
        "output_sha256": MOD.sha256_file(feature_path),
        "audit_sha256": MOD.sha256_file(audit_path),
        "output_row_count": rows,
        "input_snapshot_content_closure_sha256": "synthetic",
    }
    receipt_path.write_text(json.dumps(receipt) + "\n")
    return feature_path, audit_path, receipt_path


class FreezeContactFeatureSchemaTest(unittest.TestCase):
    def test_stability_gate_selects_reproducible_between_candidate_signal(self) -> None:
        rows = []
        for index in range(12):
            stable = index / 10.0
            rows.append(
                {
                    "candidate_id": f"c{index}",
                    "seed43_stable": stable,
                    "seed53_stable": stable + 0.01,
                    "seed67_stable": stable - 0.01,
                    "stable_seed_mean": stable,
                    "stable_seed_std": 0.01,
                    "seed43_unstable": stable,
                    "seed53_unstable": -stable,
                    "seed67_unstable": (index % 3) / 10.0,
                    "unstable_seed_mean": 0.0,
                    "unstable_seed_std": 1.0,
                }
            )
        result = MOD.feature_stability(pd.DataFrame(rows), (43, 53, 67), ("stable", "unstable"))
        selected = {row["feature"]: row["selected"] for row in result}
        self.assertTrue(selected["stable"])
        self.assertFalse(selected["unstable"])

    def test_length_confounded_mass_is_diagnostic_only(self) -> None:
        rows = []
        feature = "contact_cdr3_hotspot_mass_length_confounded_diagnostic"
        for index in range(12):
            value = float(index)
            rows.append(
                {
                    f"seed43_{feature}": value,
                    f"seed53_{feature}": value + 0.01,
                    f"seed67_{feature}": value - 0.01,
                    f"{feature}_seed_mean": value,
                    f"{feature}_seed_std": 0.01,
                }
            )
        result = MOD.feature_stability(pd.DataFrame(rows), (43, 53, 67), (feature,))[0]
        self.assertTrue(result["cross_seed_stable"])
        self.assertTrue(result["length_confounded"])
        self.assertFalse(result["selected"])

    def test_pipeline_writes_test_only_hash_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feature_path, audit_path, receipt_path = write_fixture(root)
            output_path = root / "schema.json"
            result = MOD.run(
                feature_path,
                audit_path,
                receipt_path,
                output_path,
                enforce_production_hashes=False,
                expected_rows=10,
            )
            self.assertEqual(result["status"], "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA")
            self.assertEqual(result["selected_features"], ["signal"])
            self.assertTrue(output_path.with_suffix(".receipt.json").is_file())

    def test_old_schema_and_tampered_receipt_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feature_path, audit_path, receipt_path = write_fixture(root)
            audit = json.loads(audit_path.read_text())
            audit["feature_schema_version"] = "superseded_v2"
            audit_path.write_text(json.dumps(audit) + "\n")
            with self.assertRaisesRegex(MOD.FeatureSchemaError, "schema_version_mismatch"):
                MOD.validate_inputs(
                    feature_path,
                    audit_path,
                    receipt_path,
                    enforce_production_hashes=False,
                    expected_rows=10,
                )

            feature_path, audit_path, receipt_path = write_fixture(root)
            receipt = json.loads(receipt_path.read_text())
            receipt["audit_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt) + "\n")
            with self.assertRaisesRegex(MOD.FeatureSchemaError, "receipt_closure_mismatch"):
                MOD.validate_inputs(
                    feature_path,
                    audit_path,
                    receipt_path,
                    enforce_production_hashes=False,
                    expected_rows=10,
                )

    def test_consumed_bytes_remain_bound_if_input_paths_change_mid_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feature_path, audit_path, receipt_path = write_fixture(root)
            output_path = root / "schema.json"
            expected = {
                "feature_csv": MOD.sha256_file(feature_path),
                "feature_audit": MOD.sha256_file(audit_path),
                "feature_release_receipt": MOD.sha256_file(receipt_path),
            }
            original = MOD.feature_stability

            def mutate_after_parse(frame, seeds, features):
                result = original(frame, seeds, features)
                feature_path.write_text("candidate_id\ntampered\n")
                audit_path.write_text("{}\n")
                receipt_path.write_text("{}\n")
                return result

            with mock.patch.object(MOD, "feature_stability", side_effect=mutate_after_parse):
                result = MOD.run(
                    feature_path,
                    audit_path,
                    receipt_path,
                    output_path,
                    enforce_production_hashes=False,
                    expected_rows=10,
                )
            self.assertEqual(
                {key: value["sha256"] for key, value in result["inputs"].items()},
                expected,
            )

    def test_real_v3_release_replays_when_available(self) -> None:
        root = MODULE_PATH.parents[1]
        feature_path = root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv"
        audit_path = root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json"
        receipt_path = root / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json"
        if not all(path.is_file() for path in (feature_path, audit_path, receipt_path)):
            self.skipTest("production V3 feature release is not present")
        frame, audit, _receipt, seeds, features, _snapshots = MOD.validate_inputs(
            feature_path,
            audit_path,
            receipt_path,
            enforce_production_hashes=True,
            expected_rows=MOD.EXPECTED_ROWS,
        )
        self.assertEqual(len(frame), MOD.EXPECTED_ROWS)
        self.assertEqual(seeds, (43, 53, 67))
        self.assertEqual(audit["feature_schema_version"], MOD.EXPECTED_FEATURE_SCHEMA_VERSION)
        self.assertNotIn("contact_cdr3_hotspot_mass", features)


if __name__ == "__main__":
    unittest.main()
