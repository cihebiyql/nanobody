import csv
import importlib.util
import json
import pathlib
import tempfile
import unittest

import torch


DEPLOY = pathlib.Path(__file__).parents[1]
HELPER = DEPLOY / "validate_residue_v1_5_smoke_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("checkpoint_audit", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TestSmokeCheckpointAudit(unittest.TestCase):
    def make_case(self, final_keys, last_keys):
        temporary = tempfile.TemporaryDirectory()
        root = pathlib.Path(temporary.name)
        (root / "selection").mkdir()
        torch.save(
            {"trainable_state": {key: torch.zeros(1) for key in final_keys}},
            root / "adapter_head_final.pt",
        )
        torch.save(
            {"trainable_state": {key: torch.zeros(1) for key in last_keys}},
            root / "selection" / "last.pt",
        )
        gpu = root / "gpu_memory_mib.csv"
        with gpu.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp_utc", "memory_used_mib"])
            writer.writerow(["2026-07-18T00:00:00Z", "1234"])
            writer.writerow(["2026-07-18T00:00:02Z", "4321"])
        return temporary, root, gpu

    def test_frozen_head_only_passes_and_records_resources(self):
        temporary, root, gpu = self.make_case(
            ["head.projection.weight", "head.output.bias"],
            ["head.projection.weight"],
        )
        self.addCleanup(temporary.cleanup)
        result = MODULE.audit_checkpoints(root, "frozen", gpu)
        self.assertEqual(result["status"], "PASS_ADAPTER_ONLY_CHECKPOINT_AUDIT")
        self.assertEqual(result["checkpoint_count"], 2)
        self.assertGreater(result["checkpoint_total_bytes"], 0)
        self.assertEqual(result["lora_key_count"], 0)
        self.assertEqual(result["base_or_unexpected_key_count"], 0)
        self.assertEqual(result["peak_gpu_memory_mib"], 4321)

    def test_frozen_rejects_lora_or_base_parameter(self):
        cases = [
            ["head.a", "backbone.model.layer.lora_A.default.weight"],
            ["head.a", "backbone.model.layer.weight"],
        ]
        for keys in cases:
            with self.subTest(keys=keys):
                temporary, root, gpu = self.make_case(keys, ["head.a"])
                try:
                    with self.assertRaises(MODULE.CheckpointAuditError):
                        MODULE.audit_checkpoints(root, "frozen", gpu)
                finally:
                    temporary.cleanup()

    def test_lora_requires_head_and_lora_in_every_checkpoint(self):
        good = ["head.a", "backbone.model.layer.lora_A.default.weight"]
        temporary, root, gpu = self.make_case(good, good)
        self.addCleanup(temporary.cleanup)
        result = MODULE.audit_checkpoints(root, "lora", gpu)
        self.assertEqual(result["lora_key_count"], 2)
        self.assertEqual(result["base_or_unexpected_key_count"], 0)

        temporary_bad, root_bad, gpu_bad = self.make_case(["head.a"], good)
        try:
            with self.assertRaisesRegex(MODULE.CheckpointAuditError, "missing_lora"):
                MODULE.audit_checkpoints(root_bad, "lora", gpu_bad)
        finally:
            temporary_bad.cleanup()

    def test_lora_rejects_base_parameter_and_missing_gpu_samples(self):
        bad = [
            "head.a",
            "backbone.model.layer.lora_A.default.weight",
            "backbone.model.layer.weight",
        ]
        temporary, root, gpu = self.make_case(bad, bad)
        try:
            with self.assertRaisesRegex(MODULE.CheckpointAuditError, "base_or_unexpected"):
                MODULE.audit_checkpoints(root, "lora", gpu)
        finally:
            temporary.cleanup()

        good = ["head.a"]
        temporary_empty, root_empty, gpu_empty = self.make_case(good, good)
        try:
            gpu_empty.write_text("timestamp_utc,memory_used_mib\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CheckpointAuditError, "no_samples"):
                MODULE.audit_checkpoints(root_empty, "frozen", gpu_empty)
        finally:
            temporary_empty.cleanup()


if __name__ == "__main__":
    unittest.main()
