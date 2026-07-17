#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
POLICY = HERE / "waiter_v3_policy.py"
if not POLICY.is_file():
    POLICY = HERE.parent / "scripts/waiter_v3_policy.py"
spec = importlib.util.spec_from_file_location("waiter_v3_policy", POLICY)
policy = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WaiterV3SecurityTests(unittest.TestCase):
    def make_locked_package(self, root: Path) -> tuple[Path, dict]:
        for directory in ("scripts", "manifests", "inputs/candidate_monomers"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "scripts/run_controller.py").write_text("controller\n")
        (root / "scripts/run_job.py").write_text("run_job\n")
        candidates = [f"C{i:02d}" for i in range(12)]
        (root / "inputs/candidates_12.tsv").write_text(
            "candidate_id\n" + "".join(f"{candidate}\n" for candidate in candidates)
        )
        (root / "inputs/candidate_monomers_manifest.tsv").write_text(
            "candidate_id\tpath\n" + "".join(
                f"{candidate}\tinputs/candidate_monomers/{candidate}.pdb\n" for candidate in candidates
            )
        )
        pdbs = []
        for candidate in candidates:
            path = root / f"inputs/candidate_monomers/{candidate}.pdb"
            path.write_text(f"ATOM {candidate}\n")
            pdbs.append(path)
        manifest = root / "manifests/docking_jobs.tsv"
        fields = ["job_id", "entity_type", "entity_id", "conformation", "seed", "monomer_source"]
        with manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for candidate in candidates:
                for receptor in sorted(policy.EXPECTED_RECEPTORS):
                    for seed in sorted(policy.EXPECTED_SEEDS):
                        writer.writerow({
                            "job_id": f"{candidate}_{receptor}_{seed}",
                            "entity_type": "candidate",
                            "entity_id": candidate,
                            "conformation": receptor,
                            "seed": seed,
                            "monomer_source": f"inputs/candidate_monomers/{candidate}.pdb",
                        })
        locked_files = [
            root / "scripts/run_controller.py",
            root / "scripts/run_job.py",
            manifest,
            root / "inputs/candidates_12.tsv",
            root / "inputs/candidate_monomers_manifest.tsv",
            *pdbs,
        ]
        entries = [{
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        } for path in locked_files]
        payload = {
            "status": "LOCKED_ACQUISITION_ONLY_72_JOBS",
            "candidate_count": 12,
            "job_count": 72,
            "files": entries,
            "job_manifest_sha256": sha(manifest),
            "candidate_manifest_sha256": sha(root / "inputs/candidates_12.tsv"),
            "monomer_manifest_sha256": sha(root / "inputs/candidate_monomers_manifest.tsv"),
        }
        lock = root / "ACQUISITION_PROTOCOL_LOCK.json"
        lock.write_text(json.dumps(payload, sort_keys=True) + "\n")
        return lock, payload

    def verify(self, root: Path, lock: Path) -> dict:
        return policy.verify_protocol_lock(root, lock, sha(lock))

    def test_complete_lock_closure_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock, _ = self.make_locked_package(root)
            result = self.verify(root, lock)
            self.assertEqual(result["status"], "PASS_COMPLETE_ACQUISITION_LOCK_CLOSURE")
            self.assertEqual(result["candidate_pdb_count"], 12)
            self.assertEqual(result["job_count"], 72)

    def test_controller_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); lock, _ = self.make_locked_package(root)
            (root / "scripts/run_controller.py").write_text("tampered\n")
            with self.assertRaisesRegex(policy.GateError, "locked_file_(size|sha)_mismatch"):
                self.verify(root, lock)

    def test_manifest_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); lock, _ = self.make_locked_package(root)
            with (root / "manifests/docking_jobs.tsv").open("a") as handle:
                handle.write("tamper\n")
            with self.assertRaisesRegex(policy.GateError, "locked_file_(size|sha)_mismatch"):
                self.verify(root, lock)

    def test_candidate_pdb_tamper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); lock, _ = self.make_locked_package(root)
            (root / "inputs/candidate_monomers/C00.pdb").write_text("tamper\n")
            with self.assertRaisesRegex(policy.GateError, "locked_file_(size|sha)_mismatch"):
                self.verify(root, lock)

    def test_anchor_tamper_fails_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchor.json"
            path.write_text("{}\n"); expected = sha(path)
            path.write_text('{"tampered":true}\n')
            with self.assertRaisesRegex(policy.GateError, "sha256_mismatch:anchor"):
                policy.verify_expected_artifact(path, expected, "anchor")

    def test_environment_override_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"; source.mkdir()
            teacher = root / "teacher"; teacher.mkdir()
            python = root / "python"; python.write_text("python")
            python.chmod(0o755)
            anchor = {"runtime_identity": {
                "package_root_requested": str(root), "package_root_resolved": str(root.resolve()),
                "source_v4d_requested": str(source), "source_v4d_resolved": str(source.resolve()),
                "open_teacher_requested": str(teacher), "open_teacher_resolved": str(teacher.resolve()),
                "python_requested": str(python), "python_resolved": str(python.resolve()),
                "python_resolved_sha256": sha(python), "max_load1": 16, "poll_seconds": 300,
                "path": "/usr/bin:/bin", "forbidden_environment": [],
            }}
            env = {
                "PVRIG_V4G12_ROOT": str(root), "PVRIG_V4D_SOURCE": str(root / "wrong"),
                "PVRIG_V4D_OPEN_TEACHER_ROOT": str(teacher), "PVRIG_V4G12_PYTHON": str(python),
                "PVRIG_V4G12_MAX_LOAD1": "16", "PVRIG_V4G12_POLL_SECONDS": "300",
                "PVRIG_PROJECT_ROOT": str(root), "PATH": "/usr/bin:/bin",
            }
            with self.assertRaisesRegex(policy.GateError, "runtime_override_drift:source_v4d"):
                policy.verify_runtime_identity(anchor, env)

    def test_absolute_and_traversal_paths_fail(self) -> None:
        for bad in ("/etc/passwd", "../escape", "scripts/../escape", "./file"):
            with self.subTest(bad=bad), self.assertRaises(policy.GateError):
                policy.canonical_relative_path(bad)

    def test_symlink_locked_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); lock, payload = self.make_locked_package(root)
            target = root / "real.pdb"; target.write_text("ATOM C00\n")
            path = root / "inputs/candidate_monomers/C00.pdb"
            path.unlink(); path.symlink_to(target)
            # Preserve the lock's original size/hash to prove symlink rejection occurs first.
            with self.assertRaisesRegex(policy.GateError, "locked_path_symlink_rejected"):
                policy.verify_protocol_lock(root, lock, sha(lock))

    def test_final_waiter_and_launcher_contain_immutable_constants(self) -> None:
        waiter = HERE / "wait_for_v4d_open_teacher_then_run_v3.py"
        launcher = HERE / "launch_waiter_v3.sh"
        if not waiter.is_file(): waiter = HERE.parent / "scripts/wait_for_v4d_open_teacher_then_run_v3.py"
        if not launcher.is_file(): launcher = HERE.parent / "scripts/launch_waiter_v3.sh"
        self.assertTrue(waiter.is_file())
        self.assertTrue(launcher.is_file())
        waiter_text = waiter.read_text()
        launcher_text = launcher.read_text()
        for token in (
            "EXPECTED_V2_ANCHOR_SHA256", "EXPECTED_V2_FREEZE_SHA256",
            "EXPECTED_V3_ANCHOR_SHA256", "EXPECTED_V3_POLICY_FREEZE_SHA256",
        ):
            self.assertIn(token, waiter_text)
        for token in ("EXPECTED_WAITER_V3_SHA256", "EXPECTED_V3_IMPLEMENTATION_FREEZE_SHA256"):
            self.assertIn(token, launcher_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
