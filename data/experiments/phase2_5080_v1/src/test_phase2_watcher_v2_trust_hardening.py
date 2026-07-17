#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import phase2_v4_d_surrogate_watcher_helper_v2 as helper
from test_monitor_phase2_v4_d_surrogate_training_v2 import Fixture, HELPER, SCRIPT


EXP = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def anchor_payload(files: dict[str, Path]) -> dict[str, object]:
    return {
        "schema_version": helper.TRUST_ANCHOR_SCHEMA_VERSION,
        "status": "FROZEN_BEFORE_OPEN258_TEACHER_AND_SURROGATE_TRAINING",
        "anchor_kind": helper.TRUST_ANCHOR_KIND,
        "files": {
            role: {
                "path": str(path.resolve()),
                "size": path.stat().st_size,
                "sha256": sha(path),
            }
            for role, path in sorted(files.items())
        },
        "file_count": len(files),
        "claim_boundary": "fixture",
    }


def write_anchor(path: Path, files: dict[str, Path]) -> str:
    path.write_text(
        json.dumps(anchor_payload(files), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return sha(path)


def fixture_trust_files(fixture: Fixture) -> dict[str, Path]:
    files = {
        "v2_watcher": SCRIPT,
        "v2_helper": HELPER,
        "base_trainer": fixture.base_stub,
        "embedding_trainer": fixture.embedding_stub,
        "contact_trainer": fixture.contact_stub,
        "split_manifest": fixture.split,
        "contact_schema": fixture.schema,
        "contact_schema_receipt": fixture.schema_receipt,
        "contact_features": fixture.features,
        "contact_feature_audit": fixture.feature_audit,
        "contact_feature_receipt": fixture.feature_receipt,
        "contact_feature_verification": fixture.feature_verification,
        "embedding_manifest": fixture.embedding_manifest,
        "embedding_summary": fixture.embedding_summary,
        "embedding_sequence_manifest": fixture.embedding_sequence_manifest,
    }
    for index in range(7):
        if index == 0:
            path = fixture.shards / "shard_00000.pt"
        else:
            path = fixture.exp / f"trust_only_shard_{index:05d}.pt"
            path.write_bytes(f"trust shard {index}\n".encode("ascii"))
        files[f"embedding_shard_{index:05d}"] = path
    return files


class WatcherV2TrustHardeningTests(unittest.TestCase):
    def test_real_production_anchor_and_launcher_are_closed(self) -> None:
        anchor = EXP / "audits/phase2_v4_d_surrogate_training_v2_implementation_trust_anchor.json"
        launcher = EXP / "src/launch_phase2_v4_d_surrogate_training_v2.sh"
        result = helper.validate_trust_anchor(anchor, sha(anchor))
        self.assertEqual(result["file_count"], len(helper.REQUIRED_TRUST_ROLES))
        self.assertIn(result["anchor_sha256"], launcher.read_text())

    def test_real_production_embedding_lock_catches_the_historical_typo(self) -> None:
        embedding = EXP / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
        result = helper.validate_embedding_bundle(
            embedding / "meanpool_embeddings/embedding_manifest_v3.csv",
            embedding / "meanpool_embeddings/embedding_summary_v3.json",
            embedding / "sequence_manifest_v3.csv",
            embedding / "meanpool_embeddings/shards",
            helper.PRODUCTION_LOCKS,
        )
        self.assertEqual(len(result["hashes"]["embedding_shards"]), 7)
        self.assertEqual(
            helper.PRODUCTION_LOCKS["embedding_shards"]["shard_00001.pt"],
            "3b08d1b685904bfad4855b377541b3c9477a3082e7b017a53b7b5ca2396732f1",
        )

    def test_anchor_trainer_helper_anchor_and_symlink_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files: dict[str, Path] = {}
            for index, role in enumerate(sorted(helper.REQUIRED_TRUST_ROLES)):
                path = root / f"{index:02d}_{role}.bin"
                path.write_text(f"{role}\n", encoding="utf-8")
                files[role] = path
            anchor = root / "anchor.json"
            expected = write_anchor(anchor, files)
            self.assertEqual(
                helper.validate_trust_anchor(anchor, expected)["file_count"],
                len(helper.REQUIRED_TRUST_ROLES),
            )

            files["base_trainer"].write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(
                helper.WatcherError, "trust_anchor_(size|file_hash)_mismatch:base_trainer"
            ):
                helper.validate_trust_anchor(anchor, expected)

            write_anchor(anchor, files)
            expected = sha(anchor)
            target = files["v2_helper"]
            payload = target.read_bytes()
            target.unlink()
            replacement = root / "replacement_helper.bin"
            replacement.write_bytes(payload)
            target.symlink_to(replacement)
            with self.assertRaisesRegex(
                helper.WatcherError, "(symlink_forbidden|trust_anchor_path_not_canonical)"
            ):
                helper.validate_trust_anchor(anchor, expected)

            target.unlink()
            target.write_bytes(payload)
            expected = write_anchor(anchor, files)
            anchor.write_text(anchor.read_text() + " ", encoding="utf-8")
            with self.assertRaisesRegex(helper.WatcherError, "trust_anchor_hash_mismatch"):
                helper.validate_trust_anchor(anchor, expected)

    def test_production_path_override_is_rejected_before_any_training(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "BASE_TRAINER": "/tmp/forbidden-v4d-trainer.py",
                "V4D_V2_EXPECTED_TRUST_ANCHOR_SHA": "0" * 64,
                "ONCE": "1",
            }
        )
        result = subprocess.run(
            [str(SCRIPT)], text=True, capture_output=True, env=environment
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("production path override forbidden: BASE_TRAINER", result.stderr)

    def test_stage_between_drift_is_detected_before_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            anchor = fixture.exp / "trust_anchor.json"
            anchor_hash = write_anchor(anchor, fixture_trust_files(fixture))
            environment = fixture.env(contact=True)
            environment.update(
                {
                    "V4D_V2_TRUST_ANCHOR": str(anchor),
                    "V4D_V2_EXPECTED_TRUST_ANCHOR_SHA": anchor_hash,
                    "STUB_SLEEP_STAGE": "base",
                    "STUB_SLEEP_SECONDS": "1.5",
                }
            )
            process = subprocess.Popen(
                [str(SCRIPT)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if fixture.order.exists() and "base" in fixture.order.read_text():
                    break
                time.sleep(0.05)
            else:
                process.kill()
                self.fail("base fixture stage did not start")
            fixture.base_stub.write_text(
                fixture.base_stub.read_text(encoding="utf-8") + "\n# drift\n",
                encoding="utf-8",
            )
            _stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 2, stderr)
            state = fixture.state()
            self.assertEqual(state["status"], "FAILED_IMPLEMENTATION_TRUST")
            self.assertEqual(fixture.order.read_text().splitlines(), ["base"])


if __name__ == "__main__":
    unittest.main()
