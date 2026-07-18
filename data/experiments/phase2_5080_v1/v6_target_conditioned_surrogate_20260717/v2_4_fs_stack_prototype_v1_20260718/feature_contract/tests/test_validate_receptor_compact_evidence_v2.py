#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "validate_receptor_compact_evidence_v2.py"
FORMULA_PATH = ROOT.parent / "contact_contract" / "contact_score_formula_v1.json"
SCHEMA_PATH = ROOT / "schema" / "receptor_compact_evidence_schema_v2.json"
CANONICAL_SPLIT_ROOT = ROOT.parent / "split_contract" / "prepared" / "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4"
SPEC = importlib.util.spec_from_file_location("validate_receptor_compact_evidence_v2", MODULE_PATH)
assert SPEC and SPEC.loader
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def digest(parents):
    return evidence.canonical_parent_set_sha256(parents)


class Fixture:
    def __init__(self, root: Path, role: str, shared_checkpoint: bool = True):
        self.root = root
        self.role = role
        self.parents = ["PB", "PC"]
        self.train_digest = digest(self.parents)
        self.score_digest = digest(["PA"])
        self.split_path = root / ("inner.tsv" if role == evidence.INNER_OOF_BASE_FEATURE else "outer.tsv")
        def base_stub(candidate, parent, base_role, inner_fold):
            stub = {column: "x" for column in evidence.BASE_COLUMNS}
            stub.update({
                "schema_version": evidence.BASE_ROW_SCHEMA_VERSION,
                "evidence_role": base_role,
                "candidate_id": candidate,
                "teacher_source": "V4D",
                "parent_framework_cluster": parent,
                "outer_fold": "0",
                "inner_fold": inner_fold,
                "split_train_parent_set_sha256": self.train_digest,
                "split_score_parent_set_sha256": self.score_digest,
            })
            return stub
        self.base_feature_path = root / "outer_base.tsv"
        with self.base_feature_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=evidence.BASE_COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow(base_stub("C1", "PA", evidence.OUTER_TEST_BASE_FEATURE, "NONE"))
        self.fit_inner_path = root / "fit_inner_oof.tsv"
        with self.fit_inner_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=evidence.BASE_COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow(base_stub("FIT_B", "PB", evidence.INNER_OOF_BASE_FEATURE, "1"))
            writer.writerow(base_stub("FIT_C", "PC", evidence.INNER_OOF_BASE_FEATURE, "2"))
        if role == evidence.INNER_OOF_BASE_FEATURE:
            self.split_level = "inner"
            self.split_row = {
                "split_level": "inner", "outer_fold": "0", "inner_fold": "2",
                "candidate_id": "C1", "teacher_source": "V4D",
                "parent_framework_cluster": "PA", "candidate_role": "score",
                "train_parent_set_sha256": self.train_digest,
                "score_parent_set_sha256": self.score_digest,
            }
        else:
            self.split_level = "outer"
            self.split_row = {
                "split_level": "outer", "outer_fold": "0",
                "candidate_id": "C1", "teacher_source": "V4D",
                "parent_framework_cluster": "PA", "candidate_role": "score",
                "train_parent_set_sha256": self.train_digest,
                "score_parent_set_sha256": self.score_digest,
            }
        with self.split_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.split_row), delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerow(self.split_row)

        m2_receipt = sha("m2")
        neural_receipt = sha("shared" if shared_checkpoint else "neural")
        contact_receipt = neural_receipt if shared_checkpoint else sha("contact")
        neural_path = str((root / "neural.ckpt").resolve())
        contact_path = neural_path if shared_checkpoint else str((root / "contact.ckpt").resolve())
        inner_fold = "2" if role == evidence.INNER_OOF_BASE_FEATURE else "NONE"
        component = lambda path: {
            "outer_fold": "0", "inner_fold": inner_fold, "artifact_path": path,
            "training_parent_framework_clusters": self.parents,
            "training_parent_set_sha256": self.train_digest,
        }
        meta_receipt = sha("meta")
        self.provenance = {
            "schema_version": evidence.PROVENANCE_SCHEMA_VERSION,
            "m2_components": {m2_receipt: component(str((root / "m2.json").resolve()))},
            "neural_components": {neural_receipt: component(neural_path)},
            "contact_components": {contact_receipt: component(contact_path)},
            "meta_models": {meta_receipt: {
                "outer_fold": "0", "inner_fold": "NONE",
                "artifact_path": str((root / "meta.json").resolve()),
                "training_parent_framework_clusters": self.parents,
                "training_parent_set_sha256": self.train_digest,
                "fit_inner_oof_evidence_path": str(self.fit_inner_path.resolve()),
                "fit_inner_oof_evidence_sha256": evidence.sha256_file(self.fit_inner_path),
                "fit_inner_oof_parent_framework_clusters": self.parents,
                "fit_inner_oof_parent_set_sha256": self.train_digest,
                "scaling_fit_parent_framework_clusters": self.parents,
                "scaling_fit_parent_set_sha256": self.train_digest,
                "scaling_contract": evidence.STACK_SCALING_CONTRACT,
                "fixed_ridge_alpha": evidence.STACK_RIDGE_ALPHA,
                "fixed_condition_number_ceiling": evidence.STACK_CONDITION_NUMBER_CEILING,
                "parameter_count": 5,
                "shared_nonnegative_slopes": True,
            }},
        }
        common = {
            "candidate_id": "C1", "teacher_source": "V4D",
            "parent_framework_cluster": "PA", "outer_fold": "0",
            "R_8X6B": "0.6", "R_9E6Y": "0.4", "R_dual_min": "0.4",
            "split_manifest_path": str(self.split_path.resolve()),
            "split_manifest_sha256": evidence.sha256_file(self.split_path),
            "split_train_parent_set_sha256": self.train_digest,
            "split_score_parent_set_sha256": self.score_digest,
        }
        if role in evidence.BASE_ROLES:
            self.row = {
                "schema_version": evidence.BASE_ROW_SCHEMA_VERSION,
                "evidence_role": role, **common, "inner_fold": inner_fold,
                "M2_R8": "0.55", "neural_R8": "0.52", "contact_score_R8": "0.3",
                "M2_R9": "0.45", "neural_R9": "0.48", "contact_score_R9": "0.2",
                "M2_training_parent_set_sha256": self.train_digest,
                "M2_component_receipt_sha256": m2_receipt,
                "M2_artifact_path": self.provenance["m2_components"][m2_receipt]["artifact_path"],
                "neural_training_parent_set_sha256": self.train_digest,
                "neural_component_receipt_sha256": neural_receipt,
                "neural_checkpoint_path": neural_path,
                "contact_training_parent_set_sha256": self.train_digest,
                "contact_component_receipt_sha256": contact_receipt,
                "contact_checkpoint_path": contact_path,
                "contact_formula_receipt_sha256": evidence.sha256_file(FORMULA_PATH),
                "contact_formula_artifact_path": str(FORMULA_PATH.resolve()),
            }
        else:
            self.row = {
                "schema_version": evidence.META_ROW_SCHEMA_VERSION,
                "evidence_role": role, **common,
                "prediction_R8": "0.5", "prediction_R9": "0.35",
                "prediction_R_dual_min": "0.35",
                "outer_base_feature_evidence_path": str(self.base_feature_path.resolve()),
                "outer_base_feature_evidence_sha256": evidence.sha256_file(self.base_feature_path),
                "fit_inner_oof_evidence_path": str(self.fit_inner_path.resolve()),
                "fit_inner_oof_evidence_sha256": evidence.sha256_file(self.fit_inner_path),
                "fit_inner_oof_parent_set_sha256": self.train_digest,
                "scaling_fit_parent_set_sha256": self.train_digest,
                "meta_training_parent_set_sha256": self.train_digest,
                "meta_model_receipt_sha256": meta_receipt,
                "meta_model_artifact_path": self.provenance["meta_models"][meta_receipt]["artifact_path"],
            }

    def validate(self):
        evidence.validate_row_values([self.row], self.role)
        return evidence.validate_against_split_and_provenance(
            [self.row], self.role, [self.split_row], self.split_level,
            self.split_path, self.provenance, FORMULA_PATH,
            enforce_canonical_split_sha=False,
        )


class RoleSeparatedEvidenceTests(unittest.TestCase):
    def test_machine_schema_matches_role_constants(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual(
            tuple(schema["roles"][evidence.INNER_OOF_BASE_FEATURE]["exact_columns"]),
            evidence.BASE_COLUMNS,
        )
        self.assertEqual(
            tuple(schema["roles"][evidence.OUTER_TEST_META_PREDICTION]["exact_columns"]),
            evidence.META_COLUMNS,
        )
        self.assertEqual(
            schema["stack_numeric_contract"]["scaling_contract"],
            evidence.STACK_SCALING_CONTRACT,
        )
        self.assertEqual(
            schema["canonical_split"]["inner_manifest_sha256"],
            evidence.CANONICAL_INNER_SPLIT_SHA256,
        )

    def test_current_v2_4_label_split_manifests_are_canonical(self):
        outer_rows, outer_level = evidence.read_split_manifest(
            CANONICAL_SPLIT_ROOT / "outer_development_manifest.tsv"
        )
        inner_rows, inner_level = evidence.read_split_manifest(
            CANONICAL_SPLIT_ROOT / "inner_nested_oof_manifest.tsv"
        )
        self.assertEqual((outer_level, len(outer_rows)), ("outer", 7535))
        self.assertEqual((inner_level, len(inner_rows)), ("inner", 30140))

    def test_roles_are_mutually_separated_and_base_has_no_meta_receipt(self):
        self.assertNotIn("meta_model_receipt_sha256", evidence.BASE_COLUMNS)
        self.assertNotIn("M2_R8", evidence.META_COLUMNS)
        self.assertIn("meta_model_receipt_sha256", evidence.META_COLUMNS)

    def test_inner_oof_base_feature_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE)
            self.assertEqual(fixture.validate()["status"], "PASS_ROLE_SEPARATED_COMPONENT_CONTRACT")

    def test_outer_test_base_feature_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_BASE_FEATURE)
            self.assertEqual(fixture.validate()["split_level"], "outer")

    def test_outer_test_meta_prediction_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            report = fixture.validate()
            self.assertTrue(report["meta_receipt_required"])
            self.assertEqual(report["compact_feature_count"], 0)

    def test_neural_contact_shared_checkpoint_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE, shared_checkpoint=True)
            self.assertEqual(
                fixture.row["neural_component_receipt_sha256"],
                fixture.row["contact_component_receipt_sha256"],
            )
            fixture.validate()

    def test_each_component_training_parent_set_must_match_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE)
            fixture.row["M2_training_parent_set_sha256"] = digest(["PB"])
            with self.assertRaisesRegex(evidence.EvidenceContractError, "component_training_parents_not_split_train:M2"):
                fixture.validate()

    def test_component_in_sample_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE)
            receipt = fixture.row["M2_component_receipt_sha256"]
            block = fixture.provenance["m2_components"][receipt]
            parents = ["PA", "PB", "PC"]
            block["training_parent_framework_clusters"] = parents
            block["training_parent_set_sha256"] = digest(parents)
            fixture.row["M2_training_parent_set_sha256"] = digest(parents)
            fixture.split_row["train_parent_set_sha256"] = digest(parents)
            fixture.row["split_train_parent_set_sha256"] = digest(parents)
            with self.assertRaisesRegex(evidence.EvidenceContractError, "in_sample_component_parent:M2"):
                fixture.validate()

    def test_contact_formula_receipt_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_BASE_FEATURE)
            fixture.row["contact_formula_receipt_sha256"] = "0" * 64
            with self.assertRaisesRegex(evidence.EvidenceContractError, "contact_formula_row_receipt_mismatch"):
                fixture.validate()

    def test_outer_meta_base_feature_hash_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            fixture.row["outer_base_feature_evidence_sha256"] = "0" * 64
            with self.assertRaisesRegex(evidence.EvidenceContractError, "outer_base_feature_evidence_hash_mismatch"):
                fixture.validate()

    def test_meta_receipt_binds_inner_oof_evidence_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            receipt = fixture.row["meta_model_receipt_sha256"]
            fixture.provenance["meta_models"][receipt]["fit_inner_oof_evidence_sha256"] = "0" * 64
            with self.assertRaisesRegex(evidence.EvidenceContractError, "meta_fit_inner_oof_hash_mismatch"):
                fixture.validate()

    def test_meta_inner_oof_parent_closure_must_equal_outer_train(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            receipt = fixture.row["meta_model_receipt_sha256"]
            block = fixture.provenance["meta_models"][receipt]
            block["fit_inner_oof_parent_framework_clusters"] = ["PB"]
            block["fit_inner_oof_parent_set_sha256"] = digest(["PB"])
            fixture.row["fit_inner_oof_parent_set_sha256"] = digest(["PB"])
            with self.assertRaisesRegex(evidence.EvidenceContractError, "meta_fit_inner_oof_parent_closure_mismatch"):
                fixture.validate()

    def test_meta_numeric_contract_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            receipt = fixture.row["meta_model_receipt_sha256"]
            fixture.provenance["meta_models"][receipt]["fixed_ridge_alpha"] = 0.01
            with self.assertRaisesRegex(evidence.EvidenceContractError, "meta_numeric_contract_mismatch"):
                fixture.validate()

    def test_meta_prediction_dual_must_be_exact_min(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.OUTER_TEST_META_PREDICTION)
            fixture.row["prediction_R_dual_min"] = "0.3500000000000001"
            with self.assertRaisesRegex(evidence.EvidenceContractError, "not_exact_min:prediction"):
                evidence.validate_row_values([fixture.row], fixture.role)

    def test_v1_schema_is_not_accepted_as_v2(self):
        self.assertNotEqual(
            "pvrig_v2_4_receptor_compact_inner_oof_row_v1",
            evidence.BASE_ROW_SCHEMA_VERSION,
        )

    def test_v4f_component_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE)
            receipt = fixture.row["M2_component_receipt_sha256"]
            fixture.provenance["m2_components"][receipt]["artifact_path"] = "/data1/qlyu/pvrig_v4_f/model.json"
            with self.assertRaisesRegex(evidence.EvidenceContractError, "forbidden_v4f_path"):
                fixture.validate()

    def test_noncanonical_split_sha_is_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp), evidence.INNER_OOF_BASE_FEATURE)
            with self.assertRaisesRegex(evidence.EvidenceContractError, "noncanonical_split_manifest_sha"):
                evidence.validate_against_split_and_provenance(
                    [fixture.row], fixture.role, [fixture.split_row], fixture.split_level,
                    fixture.split_path, fixture.provenance, FORMULA_PATH,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
