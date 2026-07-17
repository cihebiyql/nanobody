#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("monitor_phase2_v4_d_surrogate_training_v2.sh")
HELPER = Path(__file__).with_name("phase2_v4_d_surrogate_watcher_helper_v2.py")
TRAIN = "OPEN_TRAIN"
DEV = "OPEN_DEVELOPMENT"
TEST = "PROSPECTIVE_COMPUTATIONAL_TEST"
SELECTED = [f"stable_feature_{index:02d}" for index in range(12)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_table(path: Path, rows: list[dict[str, str]], delimiter: str = "\t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter=delimiter, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def candidate(index: int, split: str) -> dict[str, str]:
    sequence = "ACDEFGHIKLMNPQRSTVWY" + "A" * index
    return {
        "candidate_id": f"C{index}",
        "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        "sequence": sequence,
        "parent_id": f"P{index}",
        "parent_framework_cluster": f"CL{index}",
        "original_formal_split": "train",
        "model_split": split,
        "design_method": "fixture",
        "design_mode": "H3",
        "target_patch_id": "A",
        "cdr1": "ACD",
        "cdr2": "EFG",
        "cdr3": "HIKL",
        "cdr3_length": "4",
        "new_dual_docking_label_policy": "fixture",
        "claim_boundary": "fixture",
    }


STUB_TEMPLATE = r'''#!/usr/bin/env python3
import argparse, csv, hashlib, json, os, time
from pathlib import Path

STAGE = __STAGE__
p = argparse.ArgumentParser()
p.add_argument("--teacher")
p.add_argument("--teacher-audit")
p.add_argument("--release-receipt")
p.add_argument("--split-manifest")
p.add_argument("--embedding-manifest")
p.add_argument("--embedding-summary")
p.add_argument("--sequence-manifest")
p.add_argument("--contact-receipt")
p.add_argument("--contact-schema")
p.add_argument("--out-dir", required=True)
args, _ = p.parse_known_args()
out = Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
order = Path(os.environ["STUB_ORDER_LOG"])
with order.open("a", encoding="utf-8") as handle: handle.write(STAGE + "\n")
if os.environ.get("STUB_SLEEP_STAGE") == STAGE:
    time.sleep(float(os.environ.get("STUB_SLEEP_SECONDS", "1")))
def dump(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
prospective = {"split":"PROSPECTIVE_COMPUTATIONAL_TEST","manifest_rows":1,"labels_read":False,"label_files_opened":0,"used_for_training_or_selection":False}
if STAGE == "base":
    names = ["frozen_open_model_config.json","frozen_open_model_artifact.json","open_development_predictions.tsv","open_development_summary.json"]
    receipt_name = "frozen_open_artifact_sha256_receipt.json"
    receipt_status = "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE"
    summary_name = names[-1]
elif STAGE == "embedding":
    names = ["frozen_embedding_model_config.json","frozen_embedding_model_artifact.json","open_development_embedding_predictions.tsv","frozen_prospective_test_predictions.tsv","open_development_embedding_summary.json"]
    receipt_name = "frozen_embedding_artifact_sha256_receipt.json"
    receipt_status = "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE"
    summary_name = names[-1]
else:
    names = ["contact_fusion_open_model_config.json","contact_fusion_open_model_artifact.json","contact_fusion_open_development_predictions.tsv","contact_fusion_open_development_summary.json"]
    receipt_name = "contact_fusion_frozen_artifact_sha256_receipt.json"
    receipt_status = "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE"
    summary_name = names[-1]
for name in names:
    path = out / name
    if name == summary_name:
        dump(path, {"status":"FIXTURE_OPEN_GATES_RECORDED","prospective_test":prospective})
    elif name == "frozen_prospective_test_predictions.tsv":
        path.write_text("candidate_id\tmodel_split\tprediction_fixture\nT1\tPROSPECTIVE_COMPUTATIONAL_TEST\t0.5\n")
    elif name.endswith(".tsv"):
        path.write_text("candidate_id\tmodel_split\ttarget_R_dual_min\nD1\tOPEN_DEVELOPMENT\t0.5\n")
    else:
        dump(path, {"status":"FIXTURE","prospective_test_labels_read":False})
input_paths = [Path(value).resolve() for value in (
    args.teacher, args.teacher_audit, args.release_receipt, args.split_manifest,
    args.embedding_manifest, args.embedding_summary, args.sequence_manifest,
    args.contact_receipt, args.contact_schema,
) if value]
if args.contact_schema:
    input_paths.append(Path(args.contact_schema).resolve().with_suffix(".receipt.json"))
input_paths.append(Path(__file__).resolve())
dump(out / receipt_name, {
    "status": receipt_status,
    "prospective_test_labels_read": False,
    "inputs": {str(path): digest(path) for path in input_paths},
    "outputs": {str((out / name).resolve()): digest(out / name) for name in names},
})
'''


class Fixture:
    def __init__(self, root: Path) -> None:
        self.exp = root / "exp"
        self.exp.mkdir()
        self.delivery = self.exp / "delivery"
        self.split = self.exp / "split.tsv"
        self.teacher = self.delivery / "v4d_open_teacher.tsv"
        self.teacher_audit = self.delivery / "v4d_open_teacher.tsv.audit.json"
        self.release_receipt = self.delivery / "open_teacher_postprocess_receipt.json"
        self.schema = self.exp / "feature_schema.json"
        self.schema_receipt = self.exp / "feature_schema.receipt.json"
        self.features = self.exp / "features.csv"
        self.feature_audit = self.exp / "features.audit.json"
        self.feature_receipt = self.exp / "features.receipt.json"
        self.feature_verification = self.exp / "features.verification.json"
        self.embedding_manifest = self.exp / "embedding_manifest.csv"
        self.embedding_summary = self.exp / "embedding_summary.json"
        self.embedding_sequence_manifest = self.exp / "embedding_sequences.csv"
        self.shards = self.exp / "shards"
        self.shards.mkdir()
        self.order = self.exp / "order.log"
        self.base_stub = self._stub("base")
        self.embedding_stub = self._stub("embedding")
        self.contact_stub = self._stub("contact")
        self._inputs()

    def _stub(self, stage: str) -> Path:
        path = self.exp / f"stub_{stage}.py"
        path.write_text(STUB_TEMPLATE.replace("__STAGE__", repr(stage)), encoding="utf-8")
        return path

    def _inputs(self) -> None:
        split_rows = [candidate(1, TRAIN), candidate(2, TRAIN), candidate(3, DEV), candidate(4, TEST)]
        write_table(self.split, split_rows)
        teacher_rows = []
        for index, row in enumerate(split_rows[:3]):
            teacher_rows.append({**row, "R_dual_min": str(0.1 * (index + 1)), "generic_binding_prior": "0.5"})
        write_table(self.teacher, teacher_rows)
        closure = "c" * 64
        write_json(
            self.teacher_audit,
            {
                "status": "PASS_V4_D_OPEN_CONTINUOUS_TEACHER_RELEASE",
                "release": "open_train_and_open_development_only",
                "row_count": 3,
                "sealed_data_boundary": {
                    "model_split": TEST,
                    "raw_job_results_opened": 0,
                    "sealed_metrics_used_for_teacher_or_ranking": False,
                },
                "inputs": {
                    "split_manifest_sha256": sha(self.split),
                    "raw_aggregate_closure": {
                        "status": "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
                        "job_count": 18,
                        "closure_sha256": closure,
                    },
                },
            },
        )
        write_json(
            self.release_receipt,
            {
                "status": "PASS_OPEN258_TEACHER_READY_TEST32_SEALED",
                "row_count": 3,
                "teacher_sha256": sha(self.teacher),
                "teacher_audit_sha256": sha(self.teacher_audit),
                "sealed_test_raw_job_results_opened": 0,
                "sealed_metrics_used_for_teacher_or_ranking": False,
                "raw_aggregate_closure_sha256": closure,
            },
        )

        feature_rows = [
            {"candidate_id": f"C{index}", "schema_version": "pvrig_candidate_v2_3_label_free_residue_contact_features_v3", "paratope_mean_seed_mean": "0.1"}
            for index in range(1, 5)
        ]
        write_table(self.features, feature_rows, ",")
        write_json(
            self.feature_audit,
            {
                "status": "PASS",
                "label_free_contract": {"docking_label_inputs_read": 0, "v4d_raw_results_read": 0},
            },
        )
        write_json(
            self.feature_receipt,
            {
                "status": "PASS",
                "schema_version": "pvrig_candidate_v2_3_label_free_residue_contact_release_receipt_v1",
                "feature_schema_version": "pvrig_candidate_v2_3_label_free_residue_contact_features_v3",
                "output": str(self.features.resolve()),
                "output_sha256": sha(self.features),
                "output_row_count": 4,
                "audit": str(self.feature_audit.resolve()),
                "audit_sha256": sha(self.feature_audit),
            },
        )
        write_json(
            self.feature_verification,
            {
                "status": "PASS",
                "schema_version": "pvrig_candidate_v2_3_label_free_residue_contact_release_verification_v1",
                "feature_schema_version": "pvrig_candidate_v2_3_label_free_residue_contact_features_v3",
                "receipt_sha256": sha(self.feature_receipt),
                "output_sha256": sha(self.features),
                "audit_sha256": sha(self.feature_audit),
                "row_count": 4,
            },
        )
        write_json(
            self.schema,
            {
                "schema_version": "phase2_v4_d_contact_feature_schema_v2",
                "status": "PASS_FROZEN_LABEL_FREE_CONTACT_FEATURE_SCHEMA",
                "selected_feature_count": 12,
                "selected_features": SELECTED,
            },
        )
        write_json(
            self.schema_receipt,
            {
                "schema_version": "phase2_v4_d_contact_feature_schema_receipt_v2",
                "status": "PASS_COMPLETE_HASH_CLOSURE",
                "schema_file_sha256": sha(self.schema),
                "feature_csv_sha256": sha(self.features),
                "feature_audit_sha256": sha(self.feature_audit),
                "feature_release_receipt_sha256": sha(self.feature_receipt),
            },
        )

        self.embedding_manifest.write_text("sequence_sha256,shard_path\na,shard_00000.pt\n")
        self.embedding_sequence_manifest.write_text("sequence_sha256,sequence,roles\na,ACD,vhh\n")
        (self.shards / "shard_00000.pt").write_bytes(b"fixture shard")
        config_hash = "e" * 64
        write_json(
            self.embedding_summary,
            {
                "schema_version": "phase2_v3_embedding_summary_v1",
                "embedding_manifest_sha256": sha(self.embedding_manifest),
                "sequence_manifest_sha256": sha(self.embedding_sequence_manifest),
                "config_sha256": config_hash,
                "sequence_count": 1,
            },
        )
        self.locks = self.exp / "locks.json"
        write_json(
            self.locks,
            {
                "split_manifest_sha256": sha(self.split),
                "feature_schema_sha256": sha(self.schema),
                "feature_schema_receipt_sha256": sha(self.schema_receipt),
                "contact_feature_csv_sha256": sha(self.features),
                "contact_feature_audit_sha256": sha(self.feature_audit),
                "contact_feature_receipt_sha256": sha(self.feature_receipt),
                "embedding_manifest_sha256": sha(self.embedding_manifest),
                "embedding_summary_sha256": sha(self.embedding_summary),
                "embedding_sequence_manifest_sha256": sha(self.embedding_sequence_manifest),
                "embedding_config_sha256": config_hash,
                "embedding_shards": {"shard_00000.pt": sha(self.shards / "shard_00000.pt")},
                "split_counts": {TRAIN: 2, DEV: 1, TEST: 1},
                "open_teacher_count": 3,
                "contact_feature_count": 4,
                "embedding_sequence_count": 1,
                "raw_open_job_count": 18,
            },
        )

    def env(self, contact: bool = True) -> dict[str, str]:
        return {
            **os.environ,
            "PVRIG_EXP_DIR": str(self.exp),
            "PYTHON": sys.executable,
            "ONCE": "1",
            "POLL_SECONDS": "1",
            "MAX_WAIT_SECONDS": "10",
            "TRAIN_TIMEOUT_SECONDS": "10",
            "WATCHER_HELPER": str(HELPER),
            "BASE_TRAINER": str(self.base_stub),
            "EMBEDDING_TRAINER": str(self.embedding_stub),
            "CONTACT_TRAINER": str(self.contact_stub if contact else self.exp / "missing_contact.py"),
            "V4D_OPEN_TEACHER": str(self.teacher),
            "V4D_OPEN_TEACHER_AUDIT": str(self.teacher_audit),
            "V4D_OPEN_RELEASE_RECEIPT": str(self.release_receipt),
            "V4D_SPLIT_MANIFEST": str(self.split),
            "V4D_FEATURE_SCHEMA": str(self.schema),
            "V4D_FEATURE_SCHEMA_RECEIPT": str(self.schema_receipt),
            "V4D_CONTACT_FEATURES": str(self.features),
            "V4D_CONTACT_FEATURE_AUDIT": str(self.feature_audit),
            "V4D_CONTACT_FEATURE_RECEIPT": str(self.feature_receipt),
            "V4D_CONTACT_FEATURE_VERIFICATION": str(self.feature_verification),
            "V4D_EMBEDDING_MANIFEST": str(self.embedding_manifest),
            "V4D_EMBEDDING_SUMMARY": str(self.embedding_summary),
            "V4D_EMBEDDING_SEQUENCE_MANIFEST": str(self.embedding_sequence_manifest),
            "V4D_EMBEDDING_SHARD_DIR": str(self.shards),
            "V4D_TEST_ONLY_HASH_LOCKS": str(self.locks),
            "PVRIG_V4D_WATCHER_TEST_ONLY": "1",
            "STUB_ORDER_LOG": str(self.order),
        }

    def run(self, contact: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT)], env=self.env(contact), text=True, capture_output=True)

    def state(self) -> dict[str, object]:
        path = self.exp / "status/pvrig_v4_d_surrogate_training_v2/status.json"
        return json.loads(path.read_text())


class SurrogateTrainingWatcherTests(unittest.TestCase):
    def test_missing_teacher_waits_without_running_trainers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.teacher.unlink()
            result = fixture.run()
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(fixture.state()["status"], "WAITING_OPEN_TEACHER")
            self.assertFalse(fixture.order.exists())

    def test_invalid_receipt_fails_closed_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            receipt = json.loads(fixture.release_receipt.read_text())
            receipt["sealed_test_raw_job_results_opened"] = 1
            write_json(fixture.release_receipt, receipt)
            result = fixture.run()
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(fixture.state()["status"], "FAILED_INPUT_VALIDATION")
            self.assertFalse(fixture.order.exists())

    def test_missing_contact_trainer_is_explicit_wait_after_base_and_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = fixture.run(contact=False)
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(fixture.state()["status"], "WAITING_CONTACT_TRAINER")
            self.assertEqual(fixture.order.read_text().splitlines(), ["base", "embedding"])

    def test_missing_v3_verification_is_explicit_contact_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.feature_verification.unlink()
            result = fixture.run(contact=True)
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(fixture.state()["status"], "WAITING_CONTACT_TRAINER")
            self.assertEqual(fixture.order.read_text().splitlines(), ["base", "embedding"])

    def test_invalid_v3_verification_fails_instead_of_false_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            verification = json.loads(fixture.feature_verification.read_text())
            verification["status"] = "FAIL"
            write_json(fixture.feature_verification, verification)
            result = fixture.run(contact=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(fixture.state()["status"], "FAILED_CONTACT_INPUT_VALIDATION")
            self.assertEqual(fixture.order.read_text().splitlines(), ["base", "embedding"])

    def test_recovery_runs_contact_only_and_completion_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            self.assertEqual(fixture.run(contact=False).returncode, 4)
            first = fixture.run(contact=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                fixture.order.read_text().splitlines(), ["base", "embedding", "contact"]
            )
            state = fixture.state()
            self.assertEqual(state["status"], "COMPLETE_V4_D_SURROGATE_TRAINING_TEST32_SEALED")
            self.assertFalse(state["prospective_test_labels_read"])
            second = fixture.run(contact=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                fixture.order.read_text().splitlines(), ["base", "embedding", "contact"]
            )

    def test_frozen_hash_change_fails_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.split.write_text(fixture.split.read_text() + "\n")
            result = fixture.run()
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(fixture.state()["status"], "FAILED_INPUT_VALIDATION")
            self.assertFalse(fixture.order.exists())


if __name__ == "__main__":
    unittest.main()
