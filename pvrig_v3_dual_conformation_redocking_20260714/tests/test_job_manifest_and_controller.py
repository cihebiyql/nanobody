#!/usr/bin/env python3
"""Regression tests for frozen jobs, real AIR/config rendering, and retries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_docking_jobs import render_cfg_from_job, render_restraints_from_job  # noqa: E402
from common import read_tsv, sha256_file, write_tsv  # noqa: E402
from run_controller import load_limit  # noqa: E402
from orchestrate_smoke_then_full import verify_smoke  # noqa: E402
import run_job as run_job_module  # noqa: E402


CORE_HASH = "a" * 64
MONOMER = (
    "ATOM      1  N   ALA H  26      11.104  13.207   7.120  1.00 20.00           N  \n"
    "ATOM      2  CA  ALA H  26      12.104  13.207   7.120  1.00 20.00           C  \n"
    "ATOM      3  N   SER H  51      13.104  13.207   7.120  1.00 20.00           N  \n"
    "ATOM      4  CA  SER H  51      14.104  13.207   7.120  1.00 20.00           C  \n"
    "ATOM      5  N   TYR H  96      15.104  13.207   7.120  1.00 20.00           N  \n"
    "ATOM      6  CA  TYR H  96      16.104  13.207   7.120  1.00 20.00           C  \n"
    "END\n"
)


class JobManifestControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        for rel in ("config", "inputs/source", "inputs/normalized", "inputs/control_monomers", "inputs/candidate_monomers", "manifests", "reports", "status/jobs", "logs", "scripts"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "config/protocol_spec.json", self.root / "config/protocol_spec.json")
        shutil.copyfile(REPO / "inputs/source/PVRIG_hotspot_set_v1.csv", self.root / "inputs/source/PVRIG_hotspot_set_v1.csv")
        for name in (
            "interface_hotspots_uniprot.tsv",
            "8x6b_pvrig_receptor.pdb",
            "9e6y_pvrig_receptor.pdb",
            "8x6b_TL_reference.pdb",
            "9e6y_TL_reference.pdb",
        ):
            shutil.copyfile(REPO / "inputs/normalized" / name, self.root / "inputs/normalized" / name)
        shutil.copyfile(REPO / "reports/reference_normalization_summary.json", self.root / "reports/reference_normalization_summary.json")
        (self.root / "PROTOCOL_CORE_LOCK.json").write_text(
            json.dumps({"status": "CORE_LOCKED", "protocol_core_sha256": CORE_HASH}), encoding="utf-8"
        )
        self.env = dict(os.environ, PVRIG_PROJECT_ROOT=str(self.root), PYTHONPATH=str(SCRIPTS))
        self.seed_controls_and_candidates()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def run_script(self, script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / script), *args],
            cwd=REPO,
            env=env or self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def seed_controls_and_candidates(self) -> None:
        controls = []
        for index in range(1, 48):
            control_id = "CTRL_PATENT_001_case02_pos_01_PVRIG-151_HR151" if index == 1 else f"CTRL_{index:03d}"
            rel = Path("inputs/control_monomers") / f"{control_id}.pdb"
            (self.root / rel).write_text(MONOMER, encoding="utf-8")
            controls.append(
                {
                    "control_id": control_id,
                    "frozen_monomer_path": str(rel),
                    "sha256": sha256_file(self.root / rel),
                    "source_chain": "H",
                    "control_class": "positive_control" if index < 12 else "destructive_alanine",
                    "expected_behavior": "KNOWN_POSITIVE" if index < 12 else "DISRUPTIVE_CONTROL",
                    "sequence": "",
                    "cdr1_range": "26-26",
                    "cdr2_range": "51-51",
                    "cdr3_range": "96-96",
                }
            )
        write_tsv(self.root / "inputs/calibration_controls_47.tsv", controls, list(controls[0]))
        candidates = []
        candidate_monomers = []
        for index in range(1, 129):
            sequence = "A" * 25 + "C" + "A" * 24 + "D" + "A" * 44 + "E" + "A" * 20
            candidate_id = "PVRIG_RFAb_v2_P2_qkg_L_bb006_mpn00" if index == 1 else f"CAND_{index:03d}"
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "cdr1": "C",
                    "cdr2": "D",
                    "cdr3": "E",
                }
            )
            rel = Path("inputs/candidate_monomers") / f"{candidate_id}.pdb"
            candidate_pdb = "".join(
                (line[:21] + "A" + line[22:] if line.startswith("ATOM  ") else line)
                for line in MONOMER.splitlines(True)
            )
            (self.root / rel).write_text(candidate_pdb, encoding="utf-8")
            candidate_monomers.append(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "frozen_monomer_path": str(rel),
                    "source_chain": "A",
                    "sha256": sha256_file(self.root / rel),
                }
            )
        write_tsv(self.root / "inputs/candidates_128.tsv", candidates, list(candidates[0]))
        write_tsv(
            self.root / "inputs/candidate_monomers_manifest.tsv",
            candidate_monomers,
            list(candidate_monomers[0]),
        )

    def test_build_jobs_freezes_1050_unique_rows(self) -> None:
        process = self.run_script("build_docking_jobs.py")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        rows = read_tsv(self.root / "manifests/docking_jobs.tsv")
        self.assertEqual(len(rows), 1050)
        self.assertEqual(len({row["job_id"] for row in rows}), 1050)
        self.assertTrue(all(row["protocol_core_sha256"] == CORE_HASH for row in rows))
        self.assertEqual(sum(row["entity_type"] == "control" for row in rows[:282]), 282)
        self.assertEqual(sum(row["entity_type"] == "candidate" for row in rows[282:]), 768)

    def test_cfg_and_air_use_explicit_seed_normalized_chains_and_holdout_exclusion(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        row = read_tsv(self.root / "manifests/docking_jobs.tsv")[0]
        cfg = render_cfg_from_job(row)
        air = render_restraints_from_job(row)
        self.assertEqual(cfg.count("iniseed = 917"), 4)
        self.assertIn('ambig_fname = "data/air.tbl"', cfg)
        self.assertIn('"data/vhh_chainA.pdb"', cfg)
        self.assertIn('"data/pvrig_chainT.pdb"', cfg)
        self.assertIn("(resi 71 and segid T)", air)
        self.assertNotIn("(resi 72 and segid T)", air)
        self.assertIn("(resi 26 and segid A)", air)
        self.assertEqual(hashlib.sha256(cfg.encode()).hexdigest(), row["cfg_hash"])
        self.assertEqual(hashlib.sha256(air.encode()).hexdigest(), row["restraint_hash"])

    def test_controller_load_policy_boundaries(self) -> None:
        self.assertEqual(load_limit(62), 0)
        self.assertEqual(load_limit(56), 1)
        self.assertEqual(load_limit(48), 2)
        self.assertEqual(load_limit(47.99), 4)

    def test_run_job_produces_complete_native_cross_evidence_and_skips_success(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        job_id = read_tsv(self.root / "manifests/docking_jobs.tsv")[0]["job_id"]
        fake = self.root / "fake_haddock.py"
        fake.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "out=Path('haddock_run/6_seletopclusts'); out.mkdir(parents=True)\n"
            "text=Path('data/vhh_chainA.pdb').read_text().replace('END\\n','')+Path('data/pvrig_chainT.pdb').read_text()\n"
            "(out/'cluster_1_model_1.pdb').write_text(text)\n"
            "json.dump({'input':[{'file_name':'cluster_1_model_1.pdb','score':-12.5,'unw_energies':{'air':3.2}}]},open(out/'io.json','w'))\n",
            encoding="utf-8",
        )
        env = {
            **self.env,
            "PVRIG_HADDOCK_CMD": f"{sys.executable} {fake}",
            "PVRIG_SCORE_POSE": str(REPO / "scripts/score_pose.py"),
        }
        first = self.run_script("run_job.py", job_id, env=env)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        state = json.loads((self.root / "status/jobs" / f"{job_id}.json").read_text())
        self.assertEqual(state["status"], "SUCCESS")
        result = json.loads((self.root / state["evidence"]).read_text())
        self.assertEqual(result["selected_model_count"], 1)
        self.assertEqual({item["reference_id"] for item in result["pose_scores"][0]["scores"]}, {"8x6b", "9e6y"})
        second = self.run_script("run_job.py", job_id, env=env)
        self.assertEqual(second.returncode, 0)
        self.assertIn("skip successful job", second.stdout)

    def test_run_job_can_execute_in_local_scratch_and_publish_shared_run(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        job_id = read_tsv(self.root / "manifests/docking_jobs.tsv")[0]["job_id"]
        fake = self.root / "fake_haddock_scratch.py"
        fake.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "out=Path('haddock_run/6_seletopclusts'); out.mkdir(parents=True)\n"
            "text=Path('data/vhh_chainA.pdb').read_text().replace('END\\n','')+Path('data/pvrig_chainT.pdb').read_text()\n"
            "(out/'cluster_1_model_1.pdb').write_text(text)\n"
            "json.dump({'input':[{'file_name':'cluster_1_model_1.pdb','score':-12.5,'unw_energies':{'air':3.2}}]},open(out/'io.json','w'))\n",
            encoding="utf-8",
        )
        scratch = self.root / "node_local_scratch"
        env = {
            **self.env,
            "PVRIG_HADDOCK_CMD": f"{sys.executable} {fake}",
            "PVRIG_SCORE_POSE": str(REPO / "scripts/score_pose.py"),
            "PVRIG_LOCAL_SCRATCH_ROOT": str(scratch),
        }
        process = self.run_script("run_job.py", job_id, env=env)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        shared_run = self.root / "runs" / job_id
        self.assertTrue((shared_run / "haddock_run/6_seletopclusts/cluster_1_model_1.pdb").is_file())
        self.assertTrue((shared_run / "SCRATCH_PROVENANCE.json").is_file())
        result = json.loads((self.root / "results" / job_id / "job_result.json").read_text())
        self.assertTrue(all(path.startswith(f"runs/{job_id}/") for path in result["selected_models"]))
        self.assertFalse((scratch / job_id).exists())

    def test_failed_scratch_attempt_is_archived_before_retry(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        job_id = read_tsv(self.root / "manifests/docking_jobs.tsv")[0]["job_id"]
        fake = self.root / "fake_haddock_retry.py"
        fake.write_text(
            "from pathlib import Path\n"
            "Path('failure_marker.txt').write_text('preserve me')\n"
            "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        scratch = self.root / "node_local_scratch"
        env = {
            **self.env,
            "PVRIG_HADDOCK_CMD": f"{sys.executable} {fake}",
            "PVRIG_SCORE_POSE": str(REPO / "scripts/score_pose.py"),
            "PVRIG_LOCAL_SCRATCH_ROOT": str(scratch),
        }
        first = self.run_script("run_job.py", job_id, env=env)
        self.assertEqual(first.returncode, 1)
        self.assertTrue((scratch / job_id / "failure_marker.txt").is_file())
        fake.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "out=Path('haddock_run/6_seletopclusts'); out.mkdir(parents=True)\n"
            "text=Path('data/vhh_chainA.pdb').read_text().replace('END\\n','')+Path('data/pvrig_chainT.pdb').read_text()\n"
            "(out/'cluster_1_model_1.pdb').write_text(text)\n"
            "json.dump({'input':[{'file_name':'cluster_1_model_1.pdb','score':-12.5,'unw_energies':{'air':3.2}}]},open(out/'io.json','w'))\n",
            encoding="utf-8",
        )
        second = self.run_script("run_job.py", job_id, env=env)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        archived = list((self.root / "failed_attempts" / job_id).glob("attempt_1_*/scratch_run/failure_marker.txt"))
        self.assertEqual(len(archived), 1)

    def test_invalid_job_id_is_rejected_before_any_scratch_path_operation(self) -> None:
        victim = self.root / "victim"
        victim.mkdir()
        marker = victim / "keep.txt"
        marker.write_text("do not delete", encoding="utf-8")
        env = {**self.env, "PVRIG_LOCAL_SCRATCH_ROOT": str(self.root / "scratch")}
        process = self.run_script("run_job.py", "../victim", env=env)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("invalid job_id", process.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "do not delete")

    def test_scratch_cleanup_error_does_not_rollback_success(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        job_id = read_tsv(self.root / "manifests/docking_jobs.tsv")[0]["job_id"]
        fake = self.root / "fake_haddock_cleanup.py"
        fake.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "out=Path('haddock_run/6_seletopclusts'); out.mkdir(parents=True)\n"
            "text=Path('data/vhh_chainA.pdb').read_text().replace('END\\n','')+Path('data/pvrig_chainT.pdb').read_text()\n"
            "(out/'cluster_1_model_1.pdb').write_text(text)\n"
            "json.dump({'input':[{'file_name':'cluster_1_model_1.pdb','score':-12.5,'unw_energies':{'air':3.2}}]},open(out/'io.json','w'))\n",
            encoding="utf-8",
        )
        env = {
            **self.env,
            "PVRIG_HADDOCK_CMD": f"{sys.executable} {fake}",
            "PVRIG_SCORE_POSE": str(REPO / "scripts/score_pose.py"),
            "PVRIG_LOCAL_SCRATCH_ROOT": str(self.root / "node_local_scratch"),
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            run_job_module, "cleanup_local_scratch", side_effect=RuntimeError("cleanup failed")
        ):
            code = run_job_module.execute(job_id, 2)
        self.assertEqual(code, 0)
        state = json.loads((self.root / "status/jobs" / f"{job_id}.json").read_text())
        self.assertEqual(state["status"], "SUCCESS")

    def test_launcher_defaults_to_node_local_scratch_with_filesystem_preflight(self) -> None:
        capture = self.root / "ssh_command.txt"
        fake_ssh = self.root / "fake_ssh.sh"
        fake_ssh.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" > "{capture}"\n', encoding="utf-8")
        fake_ssh.chmod(0o755)
        env = {**os.environ, "SSH_BIN": str(fake_ssh), "REMOTE_HOST": "node23"}
        process = subprocess.run(
            ["bash", str(REPO / "scripts/launch_node1.sh"), "full"],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        command = capture.read_text(encoding="utf-8")
        self.assertIn("PVRIG_LOCAL_SCRATCH_ROOT='/tmp/pvrig_v3_haddock'", command)
        self.assertIn("stat -f -c %T", command)

    def test_smoke_verifier_requires_hash_selected_model_and_both_references(self) -> None:
        self.assertEqual(self.run_script("build_docking_jobs.py").returncode, 0)
        (self.root / "PROTOCOL_LOCK.json").write_text(
            json.dumps({"status": "LOCKED", "protocol_core_sha256": CORE_HASH, "protocol_lock_sha256": "b" * 64}),
            encoding="utf-8",
        )
        rows = read_tsv(self.root / "manifests/smoke_jobs.tsv")
        for row in rows:
            evidence_rel = Path("results") / row["job_id"] / "job_result.json"
            evidence = self.root / evidence_rel
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(
                json.dumps(
                    {
                        "job_hash": row["job_hash"],
                        "protocol_core_sha256": CORE_HASH,
                        "selected_model_count": 1,
                        "pose_scores": [{"scores": [{"reference_id": "8x6b"}, {"reference_id": "9e6y"}]}],
                    }
                ),
                encoding="utf-8",
            )
            state = self.root / "status/jobs" / f"{row['job_id']}.json"
            state.write_text(json.dumps({"status": "SUCCESS", "evidence": str(evidence_rel)}), encoding="utf-8")
        self.assertEqual(verify_smoke(self.root)["status"], "PASS")
        first = rows[0]
        bad = self.root / "results" / first["job_id"] / "job_result.json"
        payload = json.loads(bad.read_text())
        payload["pose_scores"][0]["scores"] = [{"reference_id": "8x6b"}]
        bad.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(verify_smoke(self.root)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
