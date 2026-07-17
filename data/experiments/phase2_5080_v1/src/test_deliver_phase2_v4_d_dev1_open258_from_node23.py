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


DELIVERY_PATH = Path(__file__).with_name("deliver_phase2_v4_d_dev1_open258_from_node23.py")
BUILDER_PATH = Path(__file__).with_name("prepare_phase2_v4_d_dev1_open258.py")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable_to_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MOD = load(DELIVERY_PATH, "deliver_phase2_v4_d_dev1_open258_from_node23")
BUILDER = load(BUILDER_PATH, "prepare_phase2_v4_d_dev1_open258_for_delivery_test")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows() -> list[dict[str, object]]:
    output = []
    for index in range(258):
        sequence = "QVQLVESGGGLVQAGGSLRLSCAASG" + chr(65 + index % 20) + f"{index:03d}"
        output.append(
            {
                "candidate_id": f"candidate-{index:03d}",
                "model_split": "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT",
                "parent_framework_cluster": f"parent-{index % 12:02d}",
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                "sequence": sequence,
                "design_method": "RFantibody",
                "design_mode": "H3",
                "target_patch_id": "A_CENTER",
                "cdr1": "AAA",
                "cdr2": "BBB",
                "cdr3": "CCC",
                "generic_binding_prior": 0.5,
                "R_dual_min": 0.2,
                "source_evaluator_status": "FAIL",
                "source_failed_gate": MOD.SOURCE_FAILED_GATE,
                "formal_v4_f_unlock_eligible": False,
                "claim_boundary": BUILDER.CLAIM_BOUNDARY,
            }
        )
    return output


def freeze(
    builder_sha: str,
    *,
    delivery_sha: str | None = None,
    launch_authorized: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "phase2_v4_d_dev1_open258_implementation_freeze_candidate_v1",
        "status": (
            "FROZEN_FOR_DEV1_REMOTE_EXECUTION"
            if launch_authorized
            else "CANDIDATE_FREEZE_BEFORE_REMOTE_OR_LABEL_ACCESS"
        ),
        "test32_raw_job_files_opened": 0,
        "remote_execution_started": False,
        "remote_execution_authorized": launch_authorized,
        "formal_v4_f_unlock_eligible": False,
        "files": {
            "builder": {"sha256": builder_sha},
            "delivery": {"sha256": delivery_sha or digest(DELIVERY_PATH)},
        },
    }


def source_inputs(
    split_sha256: str,
    prior_sha256: str,
    open_ids: list[str],
    sealed_ids: list[str],
) -> dict[str, object]:
    return {
        "split_manifest_sha256": split_sha256,
        "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
        "job_results_sha256_binding_only": MOD.EXPECTED_JOB_RESULTS_SHA256,
        "pose_scores_sha256_binding_only": MOD.EXPECTED_POSE_SCORES_SHA256,
        "source_evaluator_sha256": MOD.EXPECTED_EVALUATOR_SHA256,
        "protocol_core_lock_file_sha256": MOD.EXPECTED_PROTOCOL_CORE_LOCK_FILE_SHA256,
        "protocol_lock_file_sha256": MOD.EXPECTED_PROTOCOL_LOCK_FILE_SHA256,
        "stability_spec_file_sha256": MOD.EXPECTED_STABILITY_SPEC_FILE_SHA256,
        "evaluator_protocol_core_payload_sha256": MOD.EXPECTED_EVALUATOR_PROTOCOL_CORE_PAYLOAD_SHA256,
        "evaluator_protocol_lock_payload_sha256": MOD.EXPECTED_EVALUATOR_PROTOCOL_LOCK_PAYLOAD_SHA256,
        "v1_formula_helper_sha256": MOD.EXPECTED_V1_FORMULA_HELPER_SHA256,
        "generic_prior_sha256": prior_sha256,
        "open_candidate_id_sha256": MOD.canonical_id_hash(open_ids),
        "sealed_forbidden_candidate_id_sha256": MOD.canonical_id_hash(sealed_ids),
        "raw_test32_job_files_opened": 0,
        "test32_metric_values_read": 0,
        "test32_label_rows_emitted": 0,
        "full_aggregate_value_rows_parsed": 0,
    }


def write_references(root: Path, teacher_rows: list[dict[str, object]]) -> tuple[Path, Path, list[str], list[str]]:
    split = root / "frozen_split.tsv"
    prior = root / "generic_prior.csv"
    split_rows: list[dict[str, str]] = []
    for row in teacher_rows:
        split_rows.append({
            "candidate_id": str(row["candidate_id"]),
            "model_split": str(row["model_split"]),
            "sequence_sha256": str(row["sequence_sha256"]),
            "sequence": str(row["sequence"]),
        })
    sealed_ids: list[str] = []
    for index in range(32):
        candidate_id = f"sealed-{index:03d}"
        sequence = "QVQLVESGGGLVQAGGSLRLSCAASGT" + f"{index:03d}"
        sealed_ids.append(candidate_id)
        split_rows.append({
            "candidate_id": candidate_id,
            "model_split": MOD.SEALED_SPLIT,
            "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
            "sequence": sequence,
        })
    with split.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["candidate_id", "model_split", "sequence_sha256", "sequence"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(split_rows)
    with prior.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BUILDER.GENERIC_PRIOR_FIELDS, lineterminator="\n")
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
    return split, prior, [str(row["candidate_id"]) for row in teacher_rows], sealed_ids


def build_release(
    root: Path,
    *,
    builder_sha: str = "a" * 64,
) -> tuple[Path, dict[str, object], Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    teacher_rows = rows()
    split, prior, open_ids, sealed_ids = write_references(root, teacher_rows)
    release = root / "release"
    BUILDER.create_release_artifacts(
        release,
        teacher_rows,
        source_inputs=source_inputs(digest(split), digest(prior), open_ids, sealed_ids),
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

    def test_resigned_audit_rejects_every_frozen_input_hash_drift(self) -> None:
        frozen_hash_fields = (
            "split_manifest_sha256",
            "job_manifest_sha256",
            "job_results_sha256_binding_only",
            "pose_scores_sha256_binding_only",
            "source_evaluator_sha256",
            "protocol_core_lock_file_sha256",
            "protocol_lock_file_sha256",
            "stability_spec_file_sha256",
            "evaluator_protocol_core_payload_sha256",
            "evaluator_protocol_lock_payload_sha256",
            "v1_formula_helper_sha256",
            "generic_prior_sha256",
            "open_candidate_id_sha256",
            "sealed_forbidden_candidate_id_sha256",
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

    def test_different_current_dev1_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            delivery.mkdir()
            (delivery / "by_sha256").mkdir()
            os.symlink("by_sha256/" + "1" * 64, delivery / "current_dev1")
            extracted, contract, split, prior = build_release(root / "payload")
            bundle = validate_release(extracted, contract, split, prior)
            with self.assertRaisesRegex(MOD.DeliveryError, "different_existing_current_dev1_refused"):
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
            os.symlink("by_sha256/" + "1" * 64, delivery / "current_dev1")

            class FakeRemote:
                def read_file(self, remote_path: Path, *, max_bytes: int) -> bytes:
                    if str(remote_path).endswith(MOD.REMOTE_STATUS):
                        return json.dumps({"status": MOD.REMOTE_READY_STATUS}).encode("utf-8")
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
            with self.assertRaisesRegex(MOD.DeliveryError, "different_existing_current_dev1_refused"):
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
        self.assertEqual(MOD.REMOTE_ARCHIVE, f"release/{MOD.ARCHIVE_BASENAME}")
        self.assertEqual(MOD.REMOTE_ARCHIVE_SHA, f"release/{MOD.ARCHIVE_SHA_BASENAME}")
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


if __name__ == "__main__":
    unittest.main()
