#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTRACT = load("deployment_contract_v1", "deployment_contract_v1.py")
PREPARE = load("prepare_node1_bundle_v1", "prepare_node1_bundle_v1.py")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class PrepareNode1BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.handoff = self.root / "handoff"
        (self.handoff / "manifests").mkdir(parents=True)
        fields = [
            "job_id", "priority", "entity_type", "entity_id", "conformation", "seed",
            "sequence_sha256", "monomer_sha256", "protocol_core_sha256", "cfg_hash",
            "job_hash", "docking_stage",
        ]
        rows = []
        priority = 0
        for index in range(8):
            entity = f"c{index}"
            for conformation in ("8x6b", "9e6y"):
                priority += 1
                rows.append({
                    "job_id": f"{entity}_{conformation}", "priority": str(priority),
                    "entity_type": "candidate", "entity_id": entity,
                    "conformation": conformation, "seed": "917",
                    "sequence_sha256": digest(f"seq-{entity}"),
                    "monomer_sha256": digest(f"pdb-{entity}"),
                    "protocol_core_sha256": CONTRACT.PROTOCOL_CORE,
                    "cfg_hash": CONTRACT.CFG_HASHES[conformation],
                    "job_hash": digest(f"job-{entity}-{conformation}"),
                    "docking_stage": CONTRACT.DOCKING_STAGE,
                })
        self.manifest = self.handoff / "manifests/docking_jobs.tsv"
        CONTRACT.write_tsv(self.manifest, fields, rows)
        receipt = {
            "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
            "package_version": CONTRACT.HANDOFF_PACKAGE_VERSION,
            "production": True,
            "docking_started": False,
            "overlap1280_reuse_authorized": False,
            "counts": {"candidates": 8, "jobs": 16},
            "protocol": {
                "seed": 917, "conformations": ["8x6b", "9e6y"],
                "protocol_core_sha256": CONTRACT.PROTOCOL_CORE,
                "cfg_hashes": CONTRACT.CFG_HASHES,
            },
            "outputs": {
                "job_manifest": {
                    "path": "manifests/docking_jobs.tsv",
                    "sha256": CONTRACT.sha256_file(self.manifest),
                }
            },
        }
        (self.handoff / "HANDOFF_RECEIPT.json").write_text(
            json.dumps(receipt, sort_keys=True) + "\n"
        )
        with (self.handoff / "SHA256SUMS").open("w") as handle:
            for relative in ("HANDOFF_RECEIPT.json", "manifests/docking_jobs.tsv"):
                handle.write(f"{CONTRACT.sha256_file(self.handoff / relative)}  {relative}\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_end_to_end_synthetic_seal(self) -> None:
        output = self.root / "sealed"
        got = PREPARE.prepare(
            self.handoff, output, "2026-07-23T00:00:00Z",
            expected_candidates=8, expected_jobs=16, shard_count=8,
        )
        self.assertEqual(got["status"], "SEALED_FOR_BXCPU_UPLOAD_NOT_SUBMITTED")
        self.assertEqual(got["shard_sizes"], [2] * 8)
        self.assertFalse(got["docking_started"])
        self.assertFalse(got["overlap1280_reuse_authorized"])
        self.assertEqual(len(list((output / "manifests/shards_recommended_8").glob("shard_*.tsv"))), 8)
        self.assertTrue((output / "DEPLOYMENT_SHA256SUMS").is_file())

    def test_unlisted_input_file_fails_closed(self) -> None:
        (self.handoff / "unlisted.txt").write_text("not hash bound\n")
        with self.assertRaisesRegex(ValueError, "file-set mismatch"):
            PREPARE.prepare(
                self.handoff, self.root / "bad", "2026-07-23T00:00:00Z",
                expected_candidates=8, expected_jobs=16, shard_count=8,
            )


if __name__ == "__main__":
    unittest.main()
