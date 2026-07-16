import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).with_name("reconcile_node1_ssd_deepqc_three_state_tnp_igfold100_v3.py")
SPEC = importlib.util.spec_from_file_location("reconcile_v3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

VALIDATOR_SCRIPT = Path(__file__).with_name("validate_pvrig_deepqc_three_state_delivery.py")
VALIDATOR_SPEC = importlib.util.spec_from_file_location("three_state_validator", VALIDATOR_SCRIPT)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
sys.modules[VALIDATOR_SPEC.name] = VALIDATOR
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


def pdb_bytes(residues: int) -> bytes:
    rows = []
    for index in range(1, residues + 1):
        rows.append(
            f"ATOM  {index:5d}  CA  ALA H{index:4d}    "
            f"{index:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C\n"
        )
    return "".join(rows).encode()


class ReconciliationTests(unittest.TestCase):
    def test_classify_preserves_exact_hard_fail_set(self):
        rows = [
            {"id": "a", "L1_numbering_integrity": "PASS", "L2_vhh_features": "PASS"},
            {"id": "b", "L1_numbering_integrity": "PASS", "L2_vhh_features": "FAIL"},
            {"id": "c", "L1_numbering_integrity": "PASS", "L2_vhh_features": "PASS"},
        ]
        eligible, hard = MODULE.classify_qc_rows(rows, {"a", "b", "c"}, {"b"}, 2)
        self.assertEqual(eligible, {"a", "c"})
        self.assertEqual(hard, {"b"})
        with self.assertRaises(RuntimeError):
            MODULE.classify_qc_rows(rows, {"a", "b", "c"}, {"c"}, 2)

    def test_real_layout_distinguishes_valid_payload_from_preregistered_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = MODULE.Paths(base=root / "base", root=root / "project")
            result = paths.root / "runs_ssd_resume/tnp_00/layer3_tnp/a/TNP_Results_SingleSeqEntry_a.json"
            null_result = paths.root / "runs_ssd_resume/tnp_01/layer3_tnp/b/TNP_Results_SingleSeqEntry_b.json"
            result.parent.mkdir(parents=True)
            null_result.parent.mkdir(parents=True)
            payload = {
                "a": {
                    "name": "a", "Total CDR Length": 30, "CDR3 Length": 12,
                    "CDR3 Compactness": 1.2, "PSH": 1, "PPC": 2, "PNC": 3,
                    "Flags": {key: False for key in MODULE.REQUIRED_TNP_FLAGS},
                }
            }
            result.write_text(json.dumps(payload))
            null_result.write_text(json.dumps({"b": None}))
            valid, null = MODULE.scan_initial_tnp_outputs(
                paths, {"a": "AAAA", "b": "BBBB"}, {"a", "b"}, {"b"}, 1
            )
            self.assertEqual(set(valid), {"a"})
            self.assertEqual(set(null), {"b"})
            payload["a"]["name"] = "wrong"
            result.write_text(json.dumps(payload))
            with self.assertRaises(RuntimeError):
                MODULE.scan_initial_tnp_outputs(
                    paths, {"a": "AAAA", "b": "BBBB"}, {"a", "b"}, {"b"}, 1
                )

    def test_unregistered_null_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = MODULE.Paths(base=root / "base", root=root / "project")
            result = paths.root / "runs_ssd_resume/tnp_00/layer3_tnp/a/TNP_Results_SingleSeqEntry_a.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"a": None}))
            with self.assertRaises(RuntimeError):
                MODULE.scan_initial_tnp_outputs(paths, {"a": "AAAA"}, {"a"}, set(), 0)

    def test_structure_triplet_requires_sequence_exit_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta, pdb, log = root / "x.fasta", root / "x.pdb", root / "x.log"
            fasta.write_text(">x\nAAAAAAAAAA\n")
            pdb.write_bytes(pdb_bytes(10))
            log.write_text("$ igfold-predict x.fasta -o x.pdb --models 1\n[exit_code] 0\n")
            row = MODULE.validate_structure_triplet("x", "AAAAAAAAAA", fasta, pdb, log)
            self.assertEqual(row["ca_count"], 10)
            pdb.write_bytes(pdb_bytes(8))
            with self.assertRaises(RuntimeError):
                MODULE.validate_structure_triplet("x", "AAAAAAAAAA", fasta, pdb, log)

    def test_publication_is_exact_content_addressed_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = MODULE.Paths(base=root / "base", root=root / "project")
            source_a, source_b = root / "a.txt", root / "b.txt"
            source_a.write_text("alpha\n")
            source_b.write_text("beta\n")
            audit = {"status": "PASS", "created_at": "frozen"}
            real_link = os.link
            linked_names = []
            def recorded_link(source, destination):
                linked_names.append(Path(destination).name)
                return real_link(source, destination)
            with mock.patch.object(MODULE.os, "link", side_effect=recorded_link):
                delivery = MODULE.publish(paths, [source_a, source_b], audit)
            publication = MODULE.verify_publication(delivery)
            self.assertEqual(publication["payload_count"], 2)
            self.assertEqual(delivery.stat().st_mode & 0o222, 0)
            self.assertEqual(linked_names[-1], "SSD_DELIVERY_PUBLICATION.json")
            self.assertEqual(MODULE.publish(paths, [source_a, source_b], audit), delivery)

    def test_exact_85_7_8_partition_and_no_numeric_imputation(self):
        rows = []
        for index in range(85):
            rows.append({
                "id": f"valid_{index}", "tnp_supervision_state": "VALID_TNP",
                "tnp_PSH": "1.0", "tnp_PPC": "2.0", "tnp_PNC": "3.0",
                **{field: "GREEN" for field in VALIDATOR.TNP_FLAG_FIELDS},
            })
        for index in range(7):
            rows.append({
                "id": f"numbering_{index}", "tnp_supervision_state": "TNP_NUMBERING_HARD_FAIL_NA",
                "tnp_result_json_sha256": "a" * 64,
                **{field: "" for field in (*VALIDATOR.TNP_NUMERIC_FIELDS, *VALIDATOR.TNP_FLAG_FIELDS)},
            })
        for index in range(8):
            rows.append({
                "id": f"upstream_{index}", "tnp_supervision_state": "UPSTREAM_L2_HARD_FAIL_NA",
                "tnp_result_json_sha256": "",
                **{field: "" for field in (*VALIDATOR.TNP_NUMERIC_FIELDS, *VALIDATOR.TNP_FLAG_FIELDS)},
            })
        self.assertEqual(VALIDATOR.validate_tnp_rows(rows), VALIDATOR.EXPECTED_STATES)
        rows[85]["tnp_PSH"] = "0"
        with self.assertRaises(ValueError):
            VALIDATOR.validate_tnp_rows(rows)

    def test_v4g_waiter_receipt_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = MODULE.Paths(base=root / "base", root=root / "project")
            source = root / "payload.txt"
            source.write_text("payload\n")
            delivery = MODULE.publish(paths, [source], {"status": "PASS"})
            publication = MODULE.read_json(delivery / "SSD_DELIVERY_PUBLICATION.json")
            publication_sha = MODULE.sha256_file(delivery / "SSD_DELIVERY_PUBLICATION.json")
            recovery = root / "recovery.json"
            switch = root / "switch.json"
            recovery.write_bytes(MODULE.json_bytes({
                "status": "PASS_SSD_DELIVERY_READY_AWAITING_WATCHER_PATH_SWITCH",
                "nfs_syncback_performed": False,
                "ssd_content_addressed_delivery": str(delivery),
                "ssd_publication_receipt_sha256": publication_sha,
            }))
            switch.write_bytes(MODULE.json_bytes({
                "schema_version": "pvrig_node1_ssd_deepqc_path_switch_v1",
                "status": "PASS_SSD_DEEPQC_DELIVERY_PATH_SWITCHED",
                "active_delivery_path": str(delivery),
                "content_id": publication["content_id"],
                "publication_receipt_sha256": publication_sha,
            }))
            result = MODULE.validate_v4g_gate_receipts(recovery, switch)
            self.assertEqual(result["status"], "READY")
            bad = MODULE.read_json(switch)
            bad["content_id"] = "wrong"
            switch.write_bytes(MODULE.json_bytes(bad))
            with self.assertRaises(RuntimeError):
                MODULE.validate_v4g_gate_receipts(recovery, switch)

    def test_immutable_write_refuses_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            MODULE.write_or_verify(path, b"one\n")
            MODULE.write_or_verify(path, b"one\n")
            with self.assertRaises(RuntimeError):
                MODULE.write_or_verify(path, b"two\n")


if __name__ == "__main__":
    unittest.main()
