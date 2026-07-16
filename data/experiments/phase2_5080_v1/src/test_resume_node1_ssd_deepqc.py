#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("resume_node1_ssd_deepqc.py")
if not MODULE_PATH.is_file():
    MODULE_PATH = Path(__file__).with_name("resume_ssd_deepqc.py")
SPEC = importlib.util.spec_from_file_location("resume_node1_ssd_deepqc", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RecoveryStaticTests(unittest.TestCase):
    def test_embedded_adversarial_self_test(self):
        self.assertEqual(MODULE.self_test(), 0)

    def test_no_process_signal_api(self):
        text = MODULE_PATH.read_text()
        self.assertNotIn("os.kill", text)
        self.assertNotIn("SIGCONT", text)

    def test_terminal_status_cannot_be_complete(self):
        with self.assertRaises(ValueError):
            MODULE.set_status("COMPLETE", "bad", "bad")

    def test_nfs_syncback_is_fail_closed(self):
        with self.assertRaises(RuntimeError):
            MODULE.refuse_nfs_syncback()

    def test_publication_uses_single_captured_payload_after_source_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.bin"
            source.write_bytes(b"captured")
            captured = MODULE.capture_publication_payloads([source])
            source.write_bytes(b"mutated-after-capture")
            destination = root / "destination"
            destination.mkdir()
            row = captured[0]
            MODULE.exclusive_write_bytes(
                destination / row["destination_relative_name"],
                row["captured_bytes"],
            )
            manifest_row = {key: row[key] for key in ("source", "destination_relative_name", "bytes", "sha256")}
            MODULE.verify_publication_destinations(destination, [manifest_row])
            self.assertEqual(
                (destination / row["destination_relative_name"]).read_bytes(),
                b"captured",
            )

    def test_publication_detects_destination_corruption_before_receipt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.bin"
            source.write_bytes(b"captured")
            row = MODULE.capture_publication_payloads([source])[0]
            destination = root / "destination"
            destination.mkdir()
            output = destination / row["destination_relative_name"]
            output.write_bytes(row["captured_bytes"])
            output.write_bytes(b"corrupt")
            manifest_row = {key: row[key] for key in ("source", "destination_relative_name", "bytes", "sha256")}
            with self.assertRaises(RuntimeError):
                MODULE.verify_publication_destinations(destination, [manifest_row])


if __name__ == "__main__":
    unittest.main()
