#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class FinalReleaseIntegrityTests(unittest.TestCase):
    def test_validator_rejects_metric_candidate_metadata_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidates.tsv.gz"
            metric = root / "multimetric.tsv.gz"
            fields = [
                "candidate_id", "sequence", "sequence_sha256", "route_id",
                "max_positive_cdr_identity",
            ]
            sequences = ["A" * 100, "C" * 100]
            rows = [
                {
                    "candidate_id": f"C{i}",
                    "sequence": sequence,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "route_id": "conservative_cdr_redesign",
                    "max_positive_cdr_identity": "0.1",
                }
                for i, sequence in enumerate(sequences)
            ]
            write_tsv_gz(candidate, fields, rows)
            metric_fields = fields + [
                "prefilter_anarci_qc_status", "nbb2_status", "tnp_status",
            ]
            bad_rows = [dict(row) for row in rows]
            bad_rows[0]["sequence"] = sequences[1]
            for row in bad_rows:
                row.update({
                    "prefilter_anarci_qc_status": "PASS",
                    "nbb2_status": "SUCCESS",
                    "tnp_status": "PASS",
                })
            write_tsv_gz(metric, metric_fields, bad_rows)
            freeze = root / "FREEZE_RECEIPT.json"
            freeze.write_text(json.dumps({
                "status": "PASS", "records": 2,
                "outputs": {candidate.name: sha(candidate)},
            }))
            ready = root / "READY.json"
            ready.write_text(json.dumps({
                "status": "PASS", "records": 2, "sha256": sha(metric),
                "schema_fields": metric_fields,
                "schema_sha256": hashlib.sha256("\t".join(metric_fields).encode()).hexdigest(),
            }))
            result = subprocess.run([
                "python3", str(SCRIPTS / "validate_final_1m_release.py"),
                "--candidates", str(candidate), "--multimetric", str(metric),
                "--freeze-receipt", str(freeze), "--release-ready", str(ready),
                "--output", str(root / "validation.json"), "--expected", "2",
            ], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertRegex(result.stderr + result.stdout, r"metadata|sequence|closure|mismatch")
            good_rows = [dict(row) for row in rows]
            for row in good_rows:
                row.update({
                    "prefilter_anarci_qc_status": "PASS",
                    "nbb2_status": "SUCCESS",
                    "tnp_status": "PASS",
                })
            write_tsv_gz(metric, metric_fields, good_rows)
            ready.write_text(json.dumps({
                "status": "PASS", "records": 2, "sha256": sha(metric),
                "schema_fields": metric_fields,
                "schema_sha256": hashlib.sha256("\t".join(metric_fields).encode()).hexdigest(),
            }))
            good = subprocess.run([
                "python3", str(SCRIPTS / "validate_final_1m_release.py"),
                "--candidates", str(candidate), "--multimetric", str(metric),
                "--freeze-receipt", str(freeze), "--release-ready", str(ready),
                "--output", str(root / "validation.json"), "--expected", "2",
            ], text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)


class PurgeAcknowledgementTests(unittest.TestCase):
    def test_purge_rejects_legacy_unbound_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "campaign"
            status = campaign / "status"
            archives = campaign / "archives_101"
            results = campaign / "results_101"
            (campaign / "aggregated_101").mkdir(parents=True)
            (campaign / "tnp_aggregated_202").mkdir(parents=True)
            status.mkdir(parents=True)
            archives.mkdir()
            results.mkdir()
            (status / "CHAIN_COMPLETE").write_text("done\n")
            (campaign / "aggregated_101" / "COMPLETE.json").write_text("{}\n")
            (campaign / "tnp_aggregated_202" / "READY.json").write_text("{}\n")
            archive = archives / "node_000.tar.gz"
            archive.write_bytes(b"archive")
            digest = sha(archive)
            (archives / "node_000.sha256").write_text(f"{digest}  node_000.tar.gz\n")
            (archives / "node_000.READY.json").write_text("{}\n")
            ack = status / "NODE1_DURABLE_ACK"
            ack.write_text("deadbeef  /data/qlyu/projects/wrong\n")
            result = subprocess.run([
                "python3", str(SCRIPTS / "purge_bxcpu_nbb2_after_durable_sync.py"),
                "--campaign", str(campaign), "--nbb2-job-id", "101",
                "--tnp-job-id", "202", "--expected-shards", "1",
                "--durable-node1-root", "/data/qlyu/projects/expected",
                "--durable-ack", str(ack),
                "--node1-manifest-sha256", "a" * 64,
                "--revalidation-marker-sha256", "b" * 64,
            ], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(results.exists())
            self.assertTrue(archives.exists())

    def test_purge_accepts_bound_ack_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = (Path(tmp) / "campaign").resolve()
            status = campaign / "status"
            archives = campaign / "archives_101"
            results = campaign / "results_101"
            (campaign / "aggregated_101").mkdir(parents=True)
            (campaign / "tnp_aggregated_202").mkdir(parents=True)
            status.mkdir(parents=True)
            archives.mkdir()
            results.mkdir()
            (status / "CHAIN_COMPLETE").write_text("done\n")
            (campaign / "aggregated_101" / "COMPLETE.json").write_text("{}\n")
            (campaign / "tnp_aggregated_202" / "READY.json").write_text("{}\n")
            archive = archives / "node_000.tar.gz"
            archive.write_bytes(b"archive")
            digest = sha(archive)
            (archives / "node_000.sha256").write_text(f"{digest}  node_000.tar.gz\n")
            (archives / "node_000.READY.json").write_text("{}\n")
            ack = status / "NODE1_DURABLE_ACK.json"
            ack.write_text(json.dumps({
                "status": "DURABLE_NODE1_REVALIDATED",
                "campaign": str(campaign),
                "durable_node1_root": "/data/qlyu/projects/expected",
                "nbb2_job_id": "101", "tnp_job_id": "202", "expected_shards": 1,
                "node1_manifest_sha256": "a" * 64,
                "revalidation_marker_sha256": "b" * 64,
                "created_at_epoch": 1.0,
            }))
            command = [
                "python3", str(SCRIPTS / "purge_bxcpu_nbb2_after_durable_sync.py"),
                "--campaign", str(campaign), "--nbb2-job-id", "101",
                "--tnp-job-id", "202", "--expected-shards", "1",
                "--durable-node1-root", "/data/qlyu/projects/expected",
                "--durable-ack", str(ack),
                "--node1-manifest-sha256", "a" * 64,
                "--revalidation-marker-sha256", "b" * 64,
            ]
            first = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertFalse(results.exists())
            self.assertFalse(archives.exists())
            second = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)

    def test_purge_recovers_after_deletion_before_final_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = (Path(tmp) / "campaign").resolve()
            status = campaign / "status"
            (campaign / "aggregated_101").mkdir(parents=True)
            (campaign / "tnp_aggregated_202").mkdir(parents=True)
            status.mkdir(parents=True)
            (status / "CHAIN_COMPLETE").write_text("done\n")
            (campaign / "aggregated_101" / "COMPLETE.json").write_text("{}\n")
            (campaign / "tnp_aggregated_202" / "READY.json").write_text("{}\n")
            ack = status / "NODE1_DURABLE_ACK.json"
            ack_payload = {
                "status": "DURABLE_NODE1_REVALIDATED", "campaign": str(campaign),
                "durable_node1_root": "/data/qlyu/projects/expected",
                "nbb2_job_id": "101", "tnp_job_id": "202", "expected_shards": 1,
                "node1_manifest_sha256": "a" * 64,
                "revalidation_marker_sha256": "b" * 64, "created_at_epoch": 1.0,
            }
            ack.write_text(json.dumps(ack_payload))
            partial = status / "REMOTE_PURGE_RECEIPT.json.partial"
            partial.write_text(json.dumps({
                "status": "PURGE_VALIDATED", "campaign": str(campaign),
                "durable_node1_root": "/data/qlyu/projects/expected",
                "nbb2_job_id": "101", "tnp_job_id": "202", "expected_shards": 1,
                "node1_manifest_sha256": "a" * 64,
                "revalidation_marker_sha256": "b" * 64,
                "durable_ack_sha256": sha(ack), "archives": [],
            }))
            command = [
                "python3", str(SCRIPTS / "purge_bxcpu_nbb2_after_durable_sync.py"),
                "--campaign", str(campaign), "--nbb2-job-id", "101",
                "--tnp-job-id", "202", "--expected-shards", "1",
                "--durable-node1-root", "/data/qlyu/projects/expected",
                "--durable-ack", str(ack),
                "--node1-manifest-sha256", "a" * 64,
                "--revalidation-marker-sha256", "b" * 64,
            ]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((status / "REMOTE_PURGE_RECEIPT.json").read_text())
            self.assertEqual(receipt["status"], "PURGED_AFTER_DURABLE_NODE1_ACK")
            self.assertTrue(receipt["recovered_from_partial_receipt"])
            self.assertFalse(partial.exists())


class CampaignInputGateTests(unittest.TestCase):
    def test_gate_validates_ready_hash_and_fasta_tsv_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.tsv.gz"
            sequence = "ACDEFGHIKLMNPQRSTVWY" * 5
            rows = [{
                "candidate_id": "C1", "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            }]
            write_tsv_gz(selection, list(rows[0]), rows)
            shard_dir = root / "input"
            shard_dir.mkdir()
            (shard_dir / "task_000.fasta").write_text(f">C1\n{sequence}\n")
            (shard_dir / "MANIFEST.json").write_text(json.dumps({"records": 1, "shards": 1}))
            source_fasta = root / "source.fasta.gz"
            with gzip.open(source_fasta, "wt") as handle:
                handle.write(f">C1\n{sequence}\n")
            ready = root / "READY.json"
            ready.write_text(json.dumps({
                "status": "READY", "records": 1,
                "selection_sha256": sha(selection),
                "fasta_sha256": sha(source_fasta),
            }))
            command = [
                "python3", str(SCRIPTS / "validate_nbb2_campaign_input.py"),
                "--ready", str(ready), "--selection", str(selection),
                "--source-fasta", str(source_fasta),
                "--shard-dir", str(shard_dir), "--expected", "1", "--shards", "1",
            ]
            good = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            payload = json.loads(ready.read_text())
            payload["selection_sha256"] = "0" * 64
            ready.write_text(json.dumps(payload))
            bad = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(bad.returncode, 0)


class DynamicInvalidUnionTests(unittest.TestCase):
    def test_observed_technical_failures_extend_deterministic_invalid_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.tsv.gz"
            candidate_rows = [
                {"candidate_id": f"C{i}", "route_id": "conservative_cdr_redesign", "sequence": chr(65 + i) * 100}
                for i in range(3)
            ]
            write_tsv_gz(candidates, list(candidate_rows[0]), candidate_rows)
            base = root / "base.tsv.gz"
            write_tsv_gz(base, ["candidate_id", "route_id"], [
                {"candidate_id": "C0", "route_id": "conservative_cdr_redesign"},
            ])
            nbb2 = root / "nbb2.tsv.gz"
            write_tsv_gz(nbb2, ["candidate_id", "status", "failure_reason"], [
                {"candidate_id": "C0", "status": "TECHNICAL_NA", "failure_reason": "deterministic"},
                {"candidate_id": "C1", "status": "TECHNICAL_NA", "failure_reason": "openmm"},
                {"candidate_id": "C2", "status": "SUCCESS", "failure_reason": ""},
            ])
            tnp = root / "tnp.tsv.gz"
            write_tsv_gz(tnp, ["candidate_id", "status", "failure_reason"], [
                {"candidate_id": "C0", "status": "TECHNICAL_NA", "failure_reason": "no pdb"},
                {"candidate_id": "C1", "status": "PASS", "failure_reason": ""},
                {"candidate_id": "C2", "status": "PASS", "failure_reason": ""},
            ])
            output = root / "invalid.tsv.gz"
            receipt = root / "READY.json"
            result = subprocess.run([
                "python3", str(SCRIPTS / "build_cpu700k_dynamic_invalid.py"),
                "--candidates", str(candidates), "--base-invalid", str(base),
                "--nbb2", str(nbb2), "--tnp", str(tnp),
                "--output", str(output), "--receipt", str(receipt), "--expected", "3",
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(receipt.read_text())
            self.assertEqual(payload["base_incompatible_records"], 1)
            self.assertEqual(payload["observed_nbb2_failure_records"], 2)
            self.assertEqual(payload["invalid_union_records"], 2)


if __name__ == "__main__":
    unittest.main()
