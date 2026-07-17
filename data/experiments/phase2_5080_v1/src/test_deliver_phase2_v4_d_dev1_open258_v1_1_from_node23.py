#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


DELIVERY_PATH = Path(__file__).with_name("deliver_phase2_v4_d_dev1_open258_v1_1_from_node23.py")
BUILDER_PATH = Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258_v1_1.py")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable_to_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MOD = load(DELIVERY_PATH, "deliver_phase2_v4_d_dev1_open258_v1_1_from_node23")
BUILDER = load(BUILDER_PATH, "prepare_phase2_v4_d_dev1_open258_v1_1_for_delivery_test")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_split_row(index: int, *, sealed: bool = False) -> dict[str, str]:
    candidate_id = (
        f"sealed-{index:03d}"
        if sealed
        else MOD.FROZEN_FAILED_CANDIDATE_ID if index == 0 else f"candidate-{index:03d}"
    )
    sequence = "QVQLVESGGGLVQAGGSLRLSCAASG" + chr(65 + index % 20) + "A" * (5 + index % 3)
    model_split = MOD.SEALED_SPLIT if sealed else "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT"
    return {
        "candidate_id": candidate_id,
        "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        "sequence": sequence,
        "parent_id": f"parent-{index % 12:02d}",
        "parent_framework_cluster": f"cluster-{index % 12:02d}",
        "original_formal_split": "train",
        "model_split": model_split,
        "design_method": "RFantibody_RFdiffusion_ProteinMPNN",
        "design_mode": "H3",
        "target_patch_id": "A_CENTER",
        "cdr1": "AAA",
        "cdr2": "BBB",
        "cdr3": "CCCC",
        "cdr3_length": "4",
        "new_dual_docking_label_policy": "independent_dual_docking",
        "claim_boundary": "frozen_split_sequence_and_provenance_only",
    }


def rows() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for index in range(258):
        split = make_split_row(index)
        n8, n9 = ((2, 3) if index == 0 else (3, 3))
        r8 = round(0.2 + (index % 7) * 0.01, 9)
        r9 = round(0.3 + (index % 5) * 0.01, 9)
        gap = round(abs(r8 - r9), 9)
        sd8, sd9 = 0.01, 0.02
        missing = round((6 - n8 - n9) / 6.0, 9)
        values: dict[str, object] = {
            "schema_version": MOD.TEACHER_ROW_SCHEMA_VERSION,
            **split,
            "R_8X6B": r8,
            "R_9E6Y": r9,
            "R_dual_mean": round((r8 + r9) / 2.0, 9),
            "R_dual_min": round(min(r8, r9), 9),
            "R_dual_gap": gap,
            "seed_sd_8X6B": sd8,
            "seed_sd_9E6Y": sd9,
            "successful_seed_count_8X6B": n8,
            "successful_seed_count_9E6Y": n9,
            "native_cross_support_agreement_mean": 0.5,
            "model_pair_consensus_fraction_mean": 0.4,
            "model_strict_a_fraction_mean": 0.3,
            "model_count_reliability_mean": 0.8,
            "agreement_reliability_mean": 0.7,
            "hotspot_overlap_median_8X6B": 12.0,
            "anchor_overlap_median_8X6B": 5.0,
            "holdout_overlap_median_8X6B": 4.0,
            "total_occlusion_median_8X6B": 300.0,
            "cdr3_occlusion_median_8X6B": 60.0,
            "cdr3_fraction_median_8X6B": 0.2,
            "vhh_pvrig_clash_residue_pairs_median_8X6B": 1.0,
            "vhh_pvrl2_clash_residue_pairs_median_8X6B": 1.0,
            "overlay_rmsd_a_median_8X6B": 0.5,
            "hotspot_overlap_median_9E6Y": 11.0,
            "anchor_overlap_median_9E6Y": 4.0,
            "holdout_overlap_median_9E6Y": 3.0,
            "total_occlusion_median_9E6Y": 250.0,
            "cdr3_occlusion_median_9E6Y": 50.0,
            "cdr3_fraction_median_9E6Y": 0.2,
            "vhh_pvrig_clash_residue_pairs_median_9E6Y": 1.0,
            "vhh_pvrl2_clash_residue_pairs_median_9E6Y": 1.0,
            "overlay_rmsd_a_median_9E6Y": 0.5,
            "missing_seed_fraction": missing,
            "teacher_uncertainty": round(max(sd8, sd9) + gap + 0.1 * missing, 9),
            "generic_binding_prior": 0.5,
            "generic_binding_model_uncertainty": 0.1,
            "dev_release_track": MOD.TRACK_ID,
            "development_only": True,
            "source_evaluator_status": "FAIL",
            "source_failed_gate": MOD.SOURCE_FAILED_GATE,
            "formal_v4_f_unlock_eligible": False,
        }
        values["claim_boundary"] = MOD.CLAIM_BOUNDARY
        output.append({field: values[field] for field in MOD.EXPECTED_TEACHER_HEADER})
    return output


def freeze(
    builder_sha: str,
    *,
    delivery_sha: str | None = None,
    launch_authorized: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "phase2_v4_d_dev1_open258_v1_1_implementation_freeze_candidate_v3",
        "status": (
            "FROZEN_FOR_DEV1_V1_1_REMOTE_EXECUTION"
            if launch_authorized
            else "CANDIDATE_FREEZE_V1_1_BEFORE_REMOTE_OR_RAW_ACCESS"
        ),
        "test32_raw_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "remote_execution_started": False,
        "remote_execution_authorized": launch_authorized,
        "formal_v4_f_unlock_eligible": False,
        "final_submission_authority": False,
        "source_evaluator_status": "FAIL",
        "source_evaluator_unlockable": False,
        "single_terminal_failure_fallback": {
            "job_id": MOD.FROZEN_FAILED_JOB_ID,
            "job_hash": MOD.FROZEN_FAILED_JOB_HASH,
            "state": MOD.FROZEN_FAILED_JOB_STATE,
            "count": 1,
            "raw_success_count": MOD.EXPECTED_RAW_SUCCESS_JOBS,
            "aggregate_terminal_rows_parsed": 1,
            "aggregate_metric_fields_parsed": 0,
            "pose_scores_exact_job_rows": 0,
        },
        "files": {
            "builder": {"sha256": builder_sha},
            "delivery": {"sha256": delivery_sha or digest(DELIVERY_PATH)},
        },
    }


def source_inputs(split_sha256: str, prior_sha256: str) -> dict[str, object]:
    return {
        "split_manifest_sha256": split_sha256,
        "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256_binding_only": MOD.EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256_binding_only": MOD.EXPECTED_POSE_SCORES_SHA256,
        "source_evaluator_sha256": MOD.EXPECTED_EVALUATOR_SHA256,
        "generic_prior_sha256": prior_sha256,
        "v1_failure_receipt_sha256": MOD.EXPECTED_V1_FAILURE_RECEIPT_SHA256,
        "v1_builder_sha256": MOD.EXPECTED_V1_BUILDER_SHA256,
        "v1_formula_helper_sha256": MOD.EXPECTED_V1_FORMULA_HELPER_SHA256,
        "fallback_evidence_sha256": MOD.EXPECTED_FALLBACK_EVIDENCE_SHA256,
        "raw_job_result_count": MOD.EXPECTED_RAW_SUCCESS_JOBS,
        "aggregate_terminal_rows_parsed": 1,
        "aggregate_metric_fields_parsed": 0,
        "pose_scores_exact_failed_job_row_count": 0,
        "raw_test32_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "combined_result_count": MOD.EXPECTED_OPEN_JOBS,
        "raw_result_sha256_chain": "d" * 64,
        "raw_binding_count": MOD.EXPECTED_RAW_SUCCESS_JOBS,
    }


def write_references(root: Path, teacher_rows: list[dict[str, object]]) -> tuple[Path, Path]:
    split = root / "frozen_split.tsv"
    prior = root / "generic_prior.csv"
    split_rows: list[dict[str, str]] = []
    for index, _row in enumerate(teacher_rows):
        split_rows.append(make_split_row(index))
    for index in range(32):
        split_rows.append(make_split_row(index, sealed=True))
    with split.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MOD.FROZEN_SPLIT_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(split_rows)
    with prior.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOD.EXPECTED_GENERIC_PRIOR_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in split_rows:
            writer.writerow({
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "generic_binding_prior": "0.5",
                "model_uncertainty": "0.1",
                "model_disagreement": "0.01",
                "generic_binding_prior_seed_43": "0.4",
                "generic_binding_prior_seed_53": "0.5",
                "generic_binding_prior_seed_67": "0.6",
                "generic_binding_model": "label_free_fixture",
                "generic_binding_train_summary_sha256": "a" * 64,
                "target_sequence_sha256": "b" * 64,
                "model_claim_boundary": "label_free_generic_prior_only",
            })
    return split, prior


def build_release(
    root: Path,
    *,
    builder_sha: str = "a" * 64,
) -> tuple[Path, dict[str, object], Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    teacher_rows = rows()
    split, prior = write_references(root, teacher_rows)
    release = root / "release"
    BUILDER.create_release_artifacts(
        release,
        teacher_rows,
        source_inputs=source_inputs(digest(split), digest(prior)),
        builder_sha256=builder_sha,
        prereg_sha256=MOD.EXPECTED_PREREG_SHA256,
    )
    return release, freeze(builder_sha), split, prior


def validate_release(
    release: Path,
    contract: dict[str, object],
    split: Path,
    prior: Path,
) -> dict[str, object]:
    return MOD.validate_release_outputs(
        release,
        contract,
        split_manifest=split,
        generic_prior=prior,
        expected_split_sha256=digest(split),
        expected_generic_prior_sha256=digest(prior),
    )


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def resign(release: Path, *, refresh_teacher_audit: bool = True) -> None:
    outputs = release / "outputs"
    audit = outputs / MOD.AUDIT_BASENAME
    source = outputs / MOD.SOURCE_RECEIPT_BASENAME
    teacher = outputs / MOD.OUTPUT_BASENAME
    with teacher.open(newline="", encoding="utf-8-sig") as handle:
        header = list(csv.DictReader(handle, delimiter="\t").fieldnames or ())
    if refresh_teacher_audit:
        audit_payload = json.loads(audit.read_text())
        audit_payload["output"]["exact_header"] = header
        audit_payload["output"]["sha256"] = digest(teacher)
        write_json(audit, audit_payload)
    receipt_path = outputs / MOD.RELEASE_RECEIPT_BASENAME
    receipt = json.loads(receipt_path.read_text())
    receipt["teacher_sha256"] = digest(outputs / MOD.OUTPUT_BASENAME)
    receipt["teacher_audit_sha256"] = digest(audit)
    receipt["source_failure_receipt_sha256"] = digest(source)
    write_json(receipt_path, receipt)
    checksum = outputs / MOD.CHECKSUM_BASENAME
    checksum.write_text(
        "".join(
            f"{digest(outputs / name)}  outputs/{name}\n"
            for name in (
                MOD.OUTPUT_BASENAME,
                MOD.AUDIT_BASENAME,
                MOD.SOURCE_RECEIPT_BASENAME,
                MOD.RELEASE_RECEIPT_BASENAME,
            )
        )
    )


class Dev1DeliveryTest(unittest.TestCase):
    def test_versioned_delivery_contract_matches_v1_1_builder_constants(self) -> None:
        self.assertEqual(MOD.AUDIT_STATUS, BUILDER.AUDIT_STATUS)
        self.assertEqual(MOD.RELEASE_NAME, BUILDER.RELEASE_NAME)
        self.assertEqual(MOD.REMOTE_READY_STATUS, BUILDER.REMOTE_READY_STATUS)
        self.assertEqual(MOD.CLAIM_BOUNDARY, BUILDER.CLAIM_BOUNDARY)
        self.assertEqual(MOD.OUTPUT_BASENAME, BUILDER.OUTPUT_BASENAME)
        self.assertEqual(MOD.AUDIT_BASENAME, BUILDER.AUDIT_BASENAME)
        self.assertEqual(MOD.SOURCE_RECEIPT_BASENAME, BUILDER.SOURCE_RECEIPT_BASENAME)
        self.assertEqual(MOD.RELEASE_RECEIPT_BASENAME, BUILDER.RELEASE_RECEIPT_BASENAME)
        self.assertEqual(MOD.ARCHIVE_BASENAME, BUILDER.ARCHIVE_BASENAME)

    def test_valid_bundle_is_dev_only_and_contains_no_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            result = validate_release(release, contract, split, prior)
            self.assertEqual(result["test32_raw_open"], 0)
            self.assertFalse(result["formal_v4_f_unlock_eligible"])
            self.assertNotIn("EVALUATOR_STABLE.json", {p.name for p in (release / "outputs").iterdir()})

    def test_offline_archive_validation_uses_candidate_freeze_without_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, contract, split, prior = build_release(root)
            freeze_path = root / "freeze.json"
            write_json(freeze_path, contract)
            result = MOD.verify_offline_archive(
                release / BUILDER.ARCHIVE_BASENAME,
                freeze_path,
                split_manifest=split,
                generic_prior=prior,
                expected_split_sha256=digest(split),
                expected_generic_prior_sha256=digest(prior),
            )
            self.assertTrue(result["offline_only"])
            self.assertEqual(result["row_count"], 258)

    def test_source_evaluator_pass_is_rejected_even_if_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            source_path = release / "outputs" / MOD.SOURCE_RECEIPT_BASENAME
            source = json.loads(source_path.read_text())
            source["source_evaluator"]["status"] = "PASS"
            write_json(source_path, source)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "evaluator_state_invalid"):
                validate_release(release, contract, split, prior)

    def test_test32_counter_nonzero_is_rejected_even_if_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            audit_path = release / "outputs" / MOD.AUDIT_BASENAME
            audit = json.loads(audit_path.read_text())
            audit["sealed_data_boundary"]["raw_test32_job_files_opened"] = 1
            write_json(audit_path, audit)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "raw_test32_job_files_opened_nonzero"):
                validate_release(release, contract, split, prior)

    def test_formal_v4f_unlock_is_rejected_even_if_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            receipt_path = release / "outputs" / MOD.RELEASE_RECEIPT_BASENAME
            receipt = json.loads(receipt_path.read_text())
            receipt["formal_v4_f_unlock_eligible"] = True
            write_json(receipt_path, receipt)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "formal_v4f_unlock_true"):
                validate_release(release, contract, split, prior)

    def test_header_drift_is_rejected_even_if_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            audit_path = release / "outputs" / MOD.AUDIT_BASENAME
            audit = json.loads(audit_path.read_text())
            audit["output"]["exact_header"] = audit["output"]["exact_header"][:-1]
            write_json(audit_path, audit)
            resign(release, refresh_teacher_audit=False)
            with self.assertRaisesRegex(MOD.DeliveryError, "header_mismatch"):
                validate_release(release, contract, split, prior)

    def test_launch_and_candidate_freezes_require_exact_remote_authorization_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = freeze("a" * 64)
            candidate["remote_execution_authorized"] = True
            candidate_path = root / "candidate.json"
            write_json(candidate_path, candidate)
            with self.assertRaisesRegex(MOD.DeliveryError, "authorization_mismatch"):
                MOD.load_freeze(candidate_path, launch_authorized=False)
            launch = freeze("a" * 64, launch_authorized=True)
            launch["remote_execution_authorized"] = False
            launch_path = root / "launch.json"
            write_json(launch_path, launch)
            with self.assertRaisesRegex(MOD.DeliveryError, "authorization_mismatch"):
                MOD.load_freeze(launch_path, launch_authorized=True)

    def test_resigned_fully_substituted_teacher_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            teacher = release / "outputs" / MOD.OUTPUT_BASENAME
            with teacher.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                header = list(reader.fieldnames or ())
                payload = list(reader)
            for index, row in enumerate(payload):
                sequence = f"EVILSUBSTITUTION{index:03d}"
                row["candidate_id"] = f"evil-{index:03d}"
                row["sequence"] = sequence
                row["sequence_sha256"] = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            with teacher.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(payload)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "candidate_not_in_frozen_open_split"):
                validate_release(release, contract, split, prior)

    def test_resigned_teacher_generic_prior_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            teacher = release / "outputs" / MOD.OUTPUT_BASENAME
            with teacher.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                header = list(reader.fieldnames or ())
                payload = list(reader)
            payload[0]["generic_binding_prior"] = "0.9"
            with teacher.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(payload)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "teacher_generic_prior_mismatch"):
                validate_release(release, contract, split, prior)

    def test_resigned_teacher_prior_uncertainty_and_split_provenance_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            teacher = release / "outputs" / MOD.OUTPUT_BASENAME
            with teacher.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                header = list(reader.fieldnames or ())
                baseline = list(reader)
            for field, value, message in (
                ("generic_binding_model_uncertainty", "0.9", "teacher_generic_prior_uncertainty_mismatch"),
                ("cdr3", "EVIL", "teacher_frozen_split_field_mismatch"),
            ):
                with self.subTest(field=field):
                    payload = json.loads(json.dumps(baseline))
                    payload[0][field] = value
                    with teacher.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
                        writer.writeheader()
                        writer.writerows(payload)
                    resign(release)
                    with self.assertRaisesRegex(MOD.DeliveryError, message):
                        validate_release(release, contract, split, prior)

    def test_resigned_geometry_formula_and_seed_recovery_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            teacher = release / "outputs" / MOD.OUTPUT_BASENAME
            with teacher.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                header = list(reader.fieldnames or ())
                baseline = list(reader)
            for field, value, message in (
                ("R_dual_min", "0.99", "teacher_dual_min_formula_mismatch"),
                ("successful_seed_count_8X6B", "2", "teacher_successful_seed_total_invalid"),
            ):
                with self.subTest(field=field):
                    payload = json.loads(json.dumps(baseline))
                    target = 1 if field.startswith("successful") else 0
                    payload[target][field] = value
                    if field.startswith("successful"):
                        payload[target]["missing_seed_fraction"] = "0.166666667"
                        gap = float(payload[target]["R_dual_gap"])
                        payload[target]["teacher_uncertainty"] = str(round(0.02 + gap + 0.1 / 6.0, 9))
                    with teacher.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
                        writer.writeheader()
                        writer.writerows(payload)
                    resign(release)
                    with self.assertRaisesRegex(MOD.DeliveryError, message):
                        validate_release(release, contract, split, prior)

    def test_resigned_audit_rejects_every_frozen_input_hash_drift(self) -> None:
        frozen_hash_fields = (
            "split_manifest_sha256",
            "job_manifest_sha256",
            "job_results_sha256_binding_only",
            "pose_scores_sha256_binding_only",
            "source_evaluator_sha256",
            "generic_prior_sha256",
            "v1_failure_receipt_sha256",
            "v1_builder_sha256",
            "v1_formula_helper_sha256",
            "fallback_evidence_sha256",
        )
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            audit_path = release / "outputs" / MOD.AUDIT_BASENAME
            baseline = json.loads(audit_path.read_text())
            for field in frozen_hash_fields:
                with self.subTest(field=field):
                    altered = json.loads(json.dumps(baseline))
                    altered["inputs"][field] = "0" * 64
                    write_json(audit_path, altered)
                    resign(release)
                    with self.assertRaisesRegex(MOD.DeliveryError, f"audit_input_hash_mismatch:{field}"):
                        validate_release(release, contract, split, prior)
            write_json(audit_path, baseline)
            resign(release)

    def test_resigned_recovery_count_or_metric_access_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            audit_path = release / "outputs" / MOD.AUDIT_BASENAME
            baseline = json.loads(audit_path.read_text())
            mutations = (
                ("single_terminal_failure_recovery", "raw_job_result_count", 1546, "audit_terminal_recovery_mismatch"),
                ("inputs", "aggregate_metric_fields_parsed", 1, "audit_input_hash_mismatch"),
                ("inputs", "raw_binding_count", 1546, "audit_input_hash_mismatch"),
                ("inputs", "raw_test32_job_files_opened", 1, "audit_input_hash_mismatch"),
            )
            for section, field, value, message in mutations:
                with self.subTest(section=section, field=field):
                    altered = json.loads(json.dumps(baseline))
                    altered[section][field] = value
                    write_json(audit_path, altered)
                    resign(release)
                    with self.assertRaisesRegex(MOD.DeliveryError, message):
                        validate_release(release, contract, split, prior)

    def test_resigned_final_submission_authority_true_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            audit_path = release / "outputs" / MOD.AUDIT_BASENAME
            audit = json.loads(audit_path.read_text())
            audit["non_authority"]["final_submission_authority"] = True
            write_json(audit_path, audit)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "final_submission_authority_true"):
                validate_release(release, contract, split, prior)
        with tempfile.TemporaryDirectory() as directory:
            release, contract, split, prior = build_release(Path(directory))
            receipt_path = release / "outputs" / MOD.RELEASE_RECEIPT_BASENAME
            receipt = json.loads(receipt_path.read_text())
            receipt["final_submission_authority"] = True
            write_json(receipt_path, receipt)
            resign(release)
            with self.assertRaisesRegex(MOD.DeliveryError, "release_receipt_field_set_invalid"):
                validate_release(release, contract, split, prior)

    def test_archive_symlink_and_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, _, _, _ = build_release(root)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name in sorted(MOD.EXPECTED_ARCHIVE_MEMBERS):
                    if name == f"outputs/{MOD.OUTPUT_BASENAME}":
                        info = tarfile.TarInfo(name)
                        info.type = tarfile.SYMTYPE
                        info.linkname = f"outputs/{MOD.AUDIT_BASENAME}"
                        bundle.addfile(info)
                    else:
                        bundle.add(release / name, arcname=name, recursive=False)
            with self.assertRaisesRegex(MOD.DeliveryError, "archive_member_not_regular"):
                MOD.extract_validated_archive(archive, root / "extracted")
            traversal = root / "traversal.tar.gz"
            with tarfile.open(traversal, "w:gz") as bundle:
                for name in sorted(MOD.EXPECTED_ARCHIVE_MEMBERS):
                    bundle.add(release / name, arcname=name, recursive=False)
                info = tarfile.TarInfo("../escape")
                info.size = 1
                bundle.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(MOD.DeliveryError, "member_set_mismatch"):
                MOD.extract_validated_archive(traversal, root / "extracted2")
            self.assertFalse((root / "escape").exists())

    def test_candidate_freeze_cannot_authorize_remote_watch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freeze.json"
            write_json(path, freeze("a" * 64))
            with self.assertRaisesRegex(MOD.DeliveryError, "candidate_freeze_cannot_authorize_remote_access"):
                MOD.main(["--watch", "--production", "--freeze", str(path)])

    def test_different_current_dev1_v1_1_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            delivery.mkdir()
            (delivery / "by_sha256").mkdir()
            os.symlink("by_sha256/" + "1" * 64, delivery / "current_dev1_v1_1")
            extracted, contract, split, prior = build_release(root / "payload")
            bundle = validate_release(extracted, contract, split, prior)
            with self.assertRaisesRegex(MOD.DeliveryError, "different_existing_current_dev1_v1_1_refused"):
                MOD.publish_content_addressed(
                    delivery,
                    extracted,
                    "2" * 64,
                    {
                        "freeze": contract,
                        "bundle": bundle,
                        "split_manifest": split,
                        "generic_prior": prior,
                        "expected_split_sha256": digest(split),
                        "expected_generic_prior_sha256": digest(prior),
                    },
                )
            self.assertFalse((delivery / "by_sha256" / ("2" * 64)).exists())
            self.assertTrue(extracted.exists())

    def test_remote_attempt_cleans_archive_and_extracted_after_current_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release, contract, split, prior = build_release(root / "payload")
            archive = release / BUILDER.ARCHIVE_BASENAME
            checksum = digest(archive)
            delivery = root / "delivery"
            delivery.mkdir()
            (delivery / "by_sha256").mkdir()
            os.symlink("by_sha256/" + "1" * 64, delivery / "current_dev1_v1_1")

            class FakeRemote:
                def read_file(self, remote_path: Path, *, max_bytes: int) -> bytes:
                    if str(remote_path).endswith(MOD.REMOTE_STATUS):
                        return json.dumps({
                            "status": MOD.REMOTE_READY_STATUS,
                            "formal_v4_f_unlock_eligible": False,
                            "test32_raw_job_files_opened": 0,
                            "test32_metric_values_read": 0,
                        }).encode("utf-8")
                    if str(remote_path).endswith(MOD.REMOTE_ARCHIVE_SHA):
                        return f"{checksum}  {MOD.ARCHIVE_BASENAME}\n".encode("ascii")
                    raise AssertionError(f"unexpected_remote_read:{remote_path}")

                def stream_file(self, remote_path: Path, destination: Path, *, max_bytes: int) -> int:
                    self.assert_archive_path = remote_path
                    shutil.copyfile(archive, destination)
                    return destination.stat().st_size

            config = MOD.Config(
                delivery_root=delivery,
                ssh_exe=Path("ssh"),
                remote_host="node23",
                remote_root=Path("/remote/dev1"),
                poll_seconds=0.0,
                production=True,
                freeze_path=root / "freeze.json",
            )
            with self.assertRaisesRegex(MOD.DeliveryError, "different_existing_current_dev1_v1_1_refused"):
                MOD.one_remote_attempt(
                    config,
                    FakeRemote(),
                    contract,
                    split_manifest=split,
                    generic_prior=prior,
                    expected_split_sha256=digest(split),
                    expected_generic_prior_sha256=digest(prior),
                )
            staging = delivery / "staging"
            self.assertTrue(staging.is_dir())
            self.assertEqual(list(staging.iterdir()), [])
            self.assertFalse((delivery / "by_sha256" / checksum).exists())

    def test_remote_archive_path_and_checksum_name_match_node23_layout(self) -> None:
        self.assertEqual(MOD.REMOTE_ARCHIVE, f"release_v1_1/{MOD.ARCHIVE_BASENAME}")
        self.assertEqual(MOD.REMOTE_ARCHIVE_SHA, f"release_v1_1/{MOD.ARCHIVE_SHA_BASENAME}")
        expected = "a" * 64
        self.assertEqual(
            MOD.parse_remote_archive_checksum(f"{expected}  {MOD.ARCHIVE_BASENAME}\n".encode("ascii")),
            expected,
        )
        with self.assertRaisesRegex(MOD.DeliveryError, "remote_archive_checksum_invalid"):
            MOD.parse_remote_archive_checksum(
                f"{expected}  {MOD.REMOTE_ARCHIVE}\n".encode("ascii")
            )

    def test_source_has_no_formal_paths_or_python_assert(self) -> None:
        source = DELIVERY_PATH.read_text()
        self.assertNotRegex(source, r"(?m)^\s*assert\s")
        self.assertNotIn("status/pvrig_v4_d_surrogate_training_v3", source)
        self.assertNotIn("predictions/pvrig_v4_f_surrogate_predictions_v1", source)
        self.assertNotIn("deliver_phase2_v4_d_dev1_open258_from_node23", source)


if __name__ == "__main__":
    unittest.main()
