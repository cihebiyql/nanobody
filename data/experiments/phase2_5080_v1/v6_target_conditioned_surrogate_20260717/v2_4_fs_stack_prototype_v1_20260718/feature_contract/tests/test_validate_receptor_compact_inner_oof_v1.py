#!/usr/bin/env python3

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "validate_receptor_compact_inner_oof_v1.py"
SCHEMA_PATH = ROOT / "schema" / "receptor_compact_inner_oof_schema_v1.json"
SPEC = importlib.util.spec_from_file_location(
    "validate_receptor_compact_inner_oof_v1", MODULE_PATH
)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def parent_digest(parents: list[str]) -> str:
    return contract.canonical_parent_set_sha256(parents)


def make_bundle():
    base_sha = sha("base")
    scaler_sha = sha("scaler")
    meta_sha = sha("meta")
    base_parents = ["PB", "PC"]
    scaler_parents = ["PB", "PC"]
    meta_parents = ["PB", "PC", "PD"]
    row = {
        "schema_version": contract.ROW_SCHEMA_VERSION,
        "evidence_role": contract.EVIDENCE_ROLE,
        "candidate_id": "CAND_A",
        "teacher_source": "V4D",
        "parent_framework_cluster": "PA",
        "outer_fold": "0",
        "inner_fold": "2",
        "R_8X6B": "0.63",
        "R_9E6Y": "0.41",
        "R_dual_min": "0.41",
        "M2_R8": "0.61",
        "neural_R8": "0.58",
        "contact_score_R8": "0.27",
        "M2_R9": "0.44",
        "neural_R9": "0.49",
        "contact_score_R9": "0.19",
        "base_training_parent_set_sha256": parent_digest(base_parents),
        "base_model_receipt_sha256": base_sha,
        "base_model_artifact_path": "/data1/qlyu/v2_4/base/fold0_inner2/model.json",
        "scaler_fit_parent_set_sha256": parent_digest(scaler_parents),
        "scaler_receipt_sha256": scaler_sha,
        "scaler_artifact_path": "/data1/qlyu/v2_4/scaler/fold0_inner2/scaler.json",
        "meta_fit_parent_set_sha256": parent_digest(meta_parents),
        "meta_fit_receipt_sha256": meta_sha,
        "meta_fit_artifact_path": "/data1/qlyu/v2_4/meta/fold0_inner2/model.json",
    }
    provenance = {
        "schema_version": contract.PROVENANCE_SCHEMA_VERSION,
        "base_models": {
            base_sha: {
                "outer_fold": "0",
                "inner_fold": "2",
                "artifact_path": row["base_model_artifact_path"],
                "training_parent_framework_clusters": base_parents,
                "training_parent_set_sha256": parent_digest(base_parents),
            }
        },
        "scalers": {
            scaler_sha: {
                "outer_fold": "0",
                "inner_fold": "2",
                "artifact_path": row["scaler_artifact_path"],
                "fit_parent_framework_clusters": scaler_parents,
                "fit_parent_set_sha256": parent_digest(scaler_parents),
            }
        },
        "meta_fits": {
            meta_sha: {
                "outer_fold": "0",
                "inner_fold": "2",
                "artifact_path": row["meta_fit_artifact_path"],
                "fit_parent_framework_clusters": meta_parents,
                "fit_parent_set_sha256": parent_digest(meta_parents),
            }
        },
    }
    return row, provenance


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames=None):
    names = fieldnames or list(contract.EXACT_COLUMNS)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=names, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


class FeatureContractTests(unittest.TestCase):
    def test_machine_readable_schema_matches_validator_constants(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual(schema["schema_version"], contract.ROW_SCHEMA_VERSION)
        self.assertEqual(tuple(schema["exact_tsv_columns"]), contract.EXACT_COLUMNS)
        self.assertEqual(
            tuple(schema["compact_feature_columns"]), contract.COMPACT_FEATURE_COLUMNS
        )
        self.assertEqual(
            schema["provenance_schema_version"], contract.PROVENANCE_SCHEMA_VERSION
        )

    def test_compact_feature_set_is_exactly_six_receptor_specific_columns(self):
        self.assertEqual(
            contract.COMPACT_FEATURE_COLUMNS,
            (
                "M2_R8",
                "neural_R8",
                "contact_score_R8",
                "M2_R9",
                "neural_R9",
                "contact_score_R9",
            ),
        )
        self.assertEqual(len(contract.COMPACT_FEATURE_COLUMNS), 6)

    def test_valid_contract_passes(self):
        row, provenance = make_bundle()
        contract.validate_row_schema([row], contract.EXACT_COLUMNS)
        report = contract.validate_provenance([row], provenance)
        self.assertEqual(report["status"], "PASS_RECEPTOR_COMPACT_INNER_OOF_CONTRACT")
        self.assertEqual(report["compact_feature_count"], 6)

    def test_header_is_strict_and_rejects_extra_feature(self):
        row, _ = make_bundle()
        with self.assertRaisesRegex(contract.ContractValidationError, "exact_header_mismatch"):
            contract.validate_row_schema(
                [dict(row, neural_gap="0.1")],
                (*contract.EXACT_COLUMNS, "neural_gap"),
            )

    def test_legacy_dual_only_input_is_rejected(self):
        legacy_fields = (
            "candidate_id",
            "teacher_source",
            "parent_framework_cluster",
            "outer_fold",
            "R_dual_min",
            "m2_prediction",
            "residue_prediction",
        )
        with self.assertRaisesRegex(contract.ContractValidationError, "exact_header_mismatch"):
            contract.validate_row_schema([dict.fromkeys(legacy_fields, "x")], legacy_fields)

    def test_truth_dual_must_be_bit_exact_minimum(self):
        row, _ = make_bundle()
        row["R_dual_min"] = "0.4100000000000001"
        with self.assertRaisesRegex(contract.ContractValidationError, "truth_dual_not_exact_min"):
            contract.validate_row_schema([row], contract.EXACT_COLUMNS)

    def test_in_sample_base_training_parent_is_rejected(self):
        row, provenance = make_bundle()
        receipt = row["base_model_receipt_sha256"]
        parents = ["PA", "PB", "PC"]
        provenance["base_models"][receipt]["training_parent_framework_clusters"] = parents
        provenance["base_models"][receipt]["training_parent_set_sha256"] = parent_digest(parents)
        row["base_training_parent_set_sha256"] = parent_digest(parents)
        with self.assertRaisesRegex(contract.ContractValidationError, "in_sample_parent:base_model"):
            contract.validate_provenance([row], provenance)

    def test_in_sample_scaler_fit_parent_is_rejected(self):
        row, provenance = make_bundle()
        receipt = row["scaler_receipt_sha256"]
        parents = ["PA", "PB", "PC"]
        provenance["scalers"][receipt]["fit_parent_framework_clusters"] = parents
        provenance["scalers"][receipt]["fit_parent_set_sha256"] = parent_digest(parents)
        row["scaler_fit_parent_set_sha256"] = parent_digest(parents)
        with self.assertRaisesRegex(contract.ContractValidationError, "in_sample_parent:scaler"):
            contract.validate_provenance([row], provenance)

    def test_in_sample_meta_fit_parent_is_rejected(self):
        row, provenance = make_bundle()
        receipt = row["meta_fit_receipt_sha256"]
        parents = ["PA", "PB", "PC"]
        provenance["meta_fits"][receipt]["fit_parent_framework_clusters"] = parents
        provenance["meta_fits"][receipt]["fit_parent_set_sha256"] = parent_digest(parents)
        row["meta_fit_parent_set_sha256"] = parent_digest(parents)
        with self.assertRaisesRegex(contract.ContractValidationError, "in_sample_parent:meta_fit"):
            contract.validate_provenance([row], provenance)

    def test_v4f_row_path_is_rejected(self):
        row, _ = make_bundle()
        row["base_model_artifact_path"] = "/data1/qlyu/pvrig_v4_f/formal/model.json"
        with self.assertRaisesRegex(contract.ContractValidationError, "forbidden_v4f_path"):
            contract.validate_row_schema([row], contract.EXACT_COLUMNS)

    def test_unreferenced_v4f_manifest_path_is_rejected(self):
        row, provenance = make_bundle()
        extra_receipt = sha("unreferenced-v4f")
        provenance["meta_fits"][extra_receipt] = {
            "outer_fold": "0",
            "inner_fold": "3",
            "artifact_path": "/data1/qlyu/pvrig-v4-f/formal/model.json",
            "fit_parent_framework_clusters": ["PB", "PC"],
            "fit_parent_set_sha256": parent_digest(["PB", "PC"]),
        }
        with self.assertRaisesRegex(contract.ContractValidationError, "forbidden_v4f_path"):
            contract.validate_provenance([row], provenance)

    def test_fold_mismatch_is_rejected(self):
        row, provenance = make_bundle()
        receipt = row["scaler_receipt_sha256"]
        provenance["scalers"][receipt]["inner_fold"] = "3"
        with self.assertRaisesRegex(contract.ContractValidationError, "scaler_inner_fold_mismatch"):
            contract.validate_provenance([row], provenance)

    def test_row_digest_mismatch_is_rejected(self):
        row, provenance = make_bundle()
        row["meta_fit_parent_set_sha256"] = "0" * 64
        with self.assertRaisesRegex(contract.ContractValidationError, "meta_fit_row_parent_digest_mismatch"):
            contract.validate_provenance([row], provenance)

    def test_unknown_receipt_is_rejected(self):
        row, provenance = make_bundle()
        row["base_model_receipt_sha256"] = sha("unknown")
        with self.assertRaisesRegex(contract.ContractValidationError, "unknown_base_model_receipt"):
            contract.validate_provenance([row], provenance)

    def test_cli_writes_machine_readable_report(self):
        row, provenance = make_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_path = root / "evidence.tsv"
            provenance_path = root / "provenance.json"
            report_path = root / "report.json"
            write_tsv(evidence_path, [row])
            provenance_path.write_text(json.dumps(provenance, sort_keys=True) + "\n")
            report = contract.run(
                contract.argparse.Namespace(
                    evidence_tsv=str(evidence_path),
                    provenance_json=str(provenance_path),
                    report_json=str(report_path),
                )
            )
            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(json.loads(report_path.read_text())["compact_feature_count"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
