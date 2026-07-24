#!/usr/bin/env python3
"""Synthetic and static tests for the standalone bxcpu runtime slice."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_module("runtime_contract", "runtime_contract.py")
compact = load_module("compact_run_evidence", "compact_run_evidence.py")
prune = load_module("prune_bxcpu_payload", "prune_bxcpu_payload.py")
sync = load_module("sync_top5000_results_incremental", "sync_top5000_results_incremental.py")


class RuntimeContractSyntheticTests(unittest.TestCase):
    def test_exact_40k_manifest_and_eight_5k_shards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = pathlib.Path(temporary) / "project"
            manifest = project / "manifests/docking_jobs.tsv"
            shard_dir = project / "manifests/shards_recommended_8"
            shard_dir.mkdir(parents=True)
            header = "job_id\tentity_id\tseed\tconformation\n"
            shard_handles = [
                (shard_dir / f"shard_{index:02d}.tsv").open("w")
                for index in range(8)
            ]
            try:
                for handle in shard_handles:
                    handle.write(header)
                with manifest.open("w") as master:
                    master.write(header)
                    job_index = 0
                    for candidate_index in range(5000):
                        candidate = f"candidate_{candidate_index:05d}"
                        for seed in (917, 1931, 42, 3047):
                            for conformation in ("8x6b", "9e6y"):
                                job_id = f"job_{job_index:05d}"
                                line = (
                                    f"{job_id}\t{candidate}\t{seed}\t{conformation}\n"
                                )
                                master.write(line)
                                shard_handles[job_index % 8].write(line)
                                job_index += 1
            finally:
                for handle in shard_handles:
                    handle.close()

            receipt = project / "HANDOFF_RECEIPT.json"
            receipt.write_text(
                json.dumps(
                    {
                        "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
                        "counts": {"candidates": 5000, "jobs": 40000},
                        "protocol": {"seeds": [917, 1931, 42, 3047]},
                        "docking_started": False,
                    }
                )
                + "\n"
            )
            cfg_lock = project / "config/FOUR_SEED_CFG_LOCK.json"
            cfg_lock.parent.mkdir(parents=True)
            cfg_lock.write_text(
                json.dumps(
                    {
                        "status": "LOCKED",
                        "seeds": [917, 1931, 42, 3047],
                        "conformations": ["8x6b", "9e6y"],
                        "cfg_payloads": {
                            str(seed): {
                                conformation: {"ncores": 4}
                                for conformation in ("8x6b", "9e6y")
                            }
                            for seed in (917, 1931, 42, 3047)
                        },
                    }
                )
                + "\n"
            )
            summary = contract.validate_project(
                project,
                "manifests/docking_jobs.tsv",
                contract.sha256(manifest),
                "HANDOFF_RECEIPT.json",
                contract.sha256(receipt),
                "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
                "manifests/shards_recommended_8",
            )
            self.assertEqual(summary["candidates"], 5000)
            self.assertEqual(summary["jobs"], 40000)
            self.assertEqual(summary["shards"], 8)
            self.assertEqual(len(summary["shard_sha256"]), 8)

    def test_ready_binds_archive_manifest_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            archive = root / "bundle.tar"
            manifest = root / "manifest.tsv"
            receipt = root / "receipt.json"
            archive.write_bytes(b"archive")
            manifest.write_bytes(b"manifest")
            receipt.write_bytes(b"receipt")
            ready = root / "READY.json"
            payload = {
                "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
                "candidates": 5000,
                "jobs": 40000,
                "shards": 8,
                "job_manifest_sha256": contract.sha256(manifest),
                "handoff_receipt_sha256": contract.sha256(receipt),
            }
            ready.write_text(json.dumps(payload) + "\n")
            observed = contract.validate_ready(
                ready,
                contract.sha256(ready),
                "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
                contract.sha256(archive),
                contract.sha256(manifest),
                contract.sha256(receipt),
            )
            self.assertEqual(observed["jobs"], 40000)


class EvidenceAndPruneSyntheticTests(unittest.TestCase):
    def make_success_project(
        self, root: pathlib.Path, job_id: str
    ) -> tuple[pathlib.Path, dict]:
        project = root / "project"
        run = project / "runs" / job_id
        selected = f"runs/{job_id}/haddock_run/6_seletopclusts/model_1.pdb"
        required = {
            run / "job.json": "{}\n",
            run / "haddock3.cfg": "ncores = 4\n",
            run / "data/air.tbl": "! restraints\n",
            project / selected: "MODEL 1\nEND\n",
        }
        for path, text in required.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        result = {
            "state": "SUCCESS",
            "job_id": job_id,
            "job_hash": "a" * 64,
            "protocol_core_sha256": "b" * 64,
            "selected_model_count": 1,
            "selected_models": [selected],
            "pose_scores": [{"score": -12.3}],
        }
        result_path = project / "results" / job_id / "job_result.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_text(json.dumps(result) + "\n")
        return project, result

    def test_compact_archive_then_verified_prune_keeps_resume_stub(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            job_id = "job_00001"
            project, result = self.make_success_project(root, job_id)
            publish = root / "publish"
            published_result = publish / "results" / job_id / "job_result.json"
            published_result.parent.mkdir(parents=True)
            published_result.write_text(json.dumps(result) + "\n")
            output = publish / "compressed_queue" / f"{job_id}.tar.gz"
            output.parent.mkdir(parents=True)

            compact.compact_directory(project, job_id, output)
            compact.validate(output, job_id)
            compact.minimize_published_result(output, job_id, result)
            stub = json.loads(published_result.read_text())
            self.assertTrue(stub["full_result_in_compact_archive"])
            self.assertFalse(stub["offloaded_to_node1"])

            status = publish / "status/jobs" / f"{job_id}.json"
            status.parent.mkdir(parents=True)
            status.write_text(
                json.dumps(
                    {
                        "status": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": "a" * 64,
                        "protocol_core_sha256": "b" * 64,
                    }
                )
                + "\n"
            )
            run = publish / "runs" / job_id
            run.mkdir(parents=True)
            (run / "heavy.dat").write_bytes(b"x" * 1024)
            log = publish / "worker_logs" / f"{job_id}.log"
            log.parent.mkdir(parents=True)
            log.write_text("worker log\n")

            payload = prune.prune_jobs(publish, [job_id])
            self.assertEqual(payload["pruned"], [job_id])
            self.assertEqual(payload["errors"], [])
            self.assertTrue(status.is_file())
            self.assertTrue(published_result.is_file())
            self.assertTrue(json.loads(published_result.read_text())["offloaded_to_node1"])
            self.assertFalse(output.exists())
            self.assertFalse(run.exists())
            self.assertFalse(log.exists())

    def test_sync_validation_accepts_compact_success_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            job_id = "job_00002"
            project, result = self.make_success_project(root, job_id)
            payload_root = root / "payload"
            shutil.copytree(project / "results", payload_root / "results")
            compact_path = payload_root / "compressed_queue" / f"{job_id}.tar.gz"
            compact_path.parent.mkdir(parents=True)
            compact.compact_directory(project, job_id, compact_path)
            status_path = payload_root / "status/jobs" / f"{job_id}.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": result["job_hash"],
                        "protocol_core_sha256": result["protocol_core_sha256"],
                    }
                )
                + "\n"
            )
            files = sync.validate_local_job(payload_root, job_id)
            self.assertIn(status_path, files)
            self.assertIn(compact_path, files)

    def test_transport_tar_builds_with_embedded_hash_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            job_id = "job_00003"
            project, result = self.make_success_project(root, job_id)
            payload_root = root / "spool/payload"
            shutil.copytree(project / "results", payload_root / "results")
            compact_path = payload_root / "compressed_queue" / f"{job_id}.tar.gz"
            compact_path.parent.mkdir(parents=True)
            compact.compact_directory(project, job_id, compact_path)
            status_path = payload_root / "status/jobs" / f"{job_id}.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": result["job_hash"],
                        "protocol_core_sha256": result["protocol_core_sha256"],
                    }
                )
                + "\n"
            )
            fetched = root / "spool/state/fetched.tar"
            fetched.parent.mkdir(parents=True)
            fetched.write_bytes(b"already validated fetch")

            old_local_root = sync.LOCAL_ROOT
            old_node1_prepare = sync.node1_prepare
            old_run_retry = sync.run_retry
            sync.LOCAL_ROOT = root / "spool"
            sync.node1_prepare = lambda: None
            sync.run_retry = lambda *args, **kwargs: None
            try:
                verification = sync.relay_and_verify(
                    payload_root, [job_id], fetched
                )
            finally:
                sync.LOCAL_ROOT = old_local_root
                sync.node1_prepare = old_node1_prepare
                sync.run_retry = old_run_retry
            self.assertEqual(
                verification["status"],
                "VERIFIED_ON_NODE1_BEFORE_BXCPU_PRUNE",
            )
            self.assertEqual(len(verification["archive_sha256"]), 64)
            self.assertFalse(fetched.exists())
            events = (
                root / "spool/state/verified_batches.jsonl"
            ).read_text().splitlines()
            self.assertEqual(len(events), 1)


class StaticContractTests(unittest.TestCase):
    def test_submit_dependency_and_worker_layout(self) -> None:
        submit = (ROOT / "submit_top5000_multimodal_4seed_eight_nodes.sh").read_text()
        worker = (ROOT / "bxcpu_top5000_multimodal_4seed_worker.sh").read_text()
        preflight = (ROOT / "preflight_top5000_multimodal_4seed.sh").read_text()
        audit = (ROOT / "audit_top5000_multimodal_4seed.sh").read_text()
        self.assertIn('--dependency="afterok:$preflight"', submit)
        self.assertIn("audit_dependency=afterany", submit)
        self.assertIn("--array=1-8%8", submit)
        self.assertIn("--cpus-per-task=64", submit)
        self.assertIn("NODE_CONCURRENCY", worker)
        self.assertIn("JOB_CPUS=4", worker)
        self.assertIn("JOBS_PER_SHARD=5000", worker)
        self.assertIn(
            "pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724", worker
        )
        self.assertIn("manifests/shards_exact_8", worker)
        self.assertIn("compact_run_evidence.py", worker)
        self.assertIn("PVRIG_LOCAL_SCRATCH_ROOT", worker)
        self.assertIn("check-smoke", preflight)
        self.assertNotIn("\nsbatch --test-only", preflight)
        self.assertIn("accepted_dependency_gated_array_plus_static_8x64_layout", preflight)
        self.assertIn("HADDOCK version is not 2025.11.0", (ROOT / "bxcpu_runtime_common.sh").read_text())
        self.assertIn("pvrig_unpack_runtime", audit)
        self.assertIn('"$LOCAL_ENV/bin/python"', audit)
        self.assertNotIn('PYTHON="${PVRIG_TOP5000_CONTROL_PYTHON:-python3}"', audit)

    def test_sync_defaults_and_hash_before_prune_contract(self) -> None:
        source = (ROOT / "sync_top5000_results_incremental.py").read_text()
        start = (ROOT / "start_top5000_results_sync_sharded.sh").read_text()
        prune_source = (ROOT / "prune_bxcpu_payload.py").read_text()
        self.assertIn('"/data/qlyu/projects/"', source)
        self.assertIn(
            '"pvrig_node1_generated100k_multimodal_top5000_4seed_docking_results_v1_20260724"',
            source,
        )
        self.assertNotIn("/data1/", source)
        self.assertIn('"PVRIG_TOP5000_SYNC_BATCH_SIZE", "60"', source)
        self.assertIn('"PVRIG_TOP5000_SYNC_STABLE_AGE_SECONDS", "90"', source)
        self.assertIn('"PVRIG_TOP5000_SYNC_MAX_SPOOL_GIB_PER_SHARD",\n            "4"', source)
        self.assertIn("sha256sum -c", source)
        self.assertIn('"-e",\n        BXCPU_SSH', source)
        self.assertIn("PVRIG_BXCPU_SSH=%q", start)
        self.assertNotIn("from __future__ import annotations", prune_source)
        self.assertNotIn("dict[str", prune_source)
        self.assertNotIn("list[str", prune_source)
        self.assertLess(
            source.index("verification = relay_and_verify"),
            source.index("newly_pruned = prune_bxcpu_verified_payload(valid_jobs)"),
        )
        self.assertIn('COUNT="${PVRIG_TOP5000_SYNC_SHARDS:-4}"', start)
        self.assertIn('BATCH="${PVRIG_TOP5000_SYNC_BATCH_SIZE:-60}"', start)
        self.assertIn('STABLE="${PVRIG_TOP5000_SYNC_STABLE_AGE_SECONDS:-90}"', start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
