#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import gzip
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("recover_phase2_v3_p2_v1_2_pilot64_emref_top8.py")
SPEC = importlib.util.spec_from_file_location("recover_p2_v1_2_pilot64_emref", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, chain: str, residue: int, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C  "
    )


def pdb_bytes(chains: str, offset: float = 0.0) -> bytes:
    lines = []
    for serial, chain in enumerate(chains, start=1):
        lines.append(atom_line(serial, chain, serial, offset + serial))
    return ("\n".join(lines + ["END"]) + "\n").encode("ascii")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.remote = root / "remote"
        self.remote.mkdir()
        self.manifest = root / "run_manifest.csv"
        self.failed_audit = root / "failed_audit.json"
        self.outdir = root / "selected"
        self.audit = root / "audit.json"
        self.output = root / "selector.csv"
        self.sync_requests: list[dict[str, object]] = []
        self.rows: list[dict[str, str]] = []
        self.failed_ids: list[str] = []
        self._build()

    def _asset(self, relpath: str, payload: bytes) -> tuple[str, str]:
        path = self.remote / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return relpath, MOD.sha256_file(path)

    def _make_run(
        self,
        run_id: str,
        pilot_rank: int,
        source_count: int,
        failed: bool,
    ) -> dict[str, str]:
        match = MOD.RUN_ID_RE.fullmatch(run_id)
        assert match
        receptor, role = match.groups()
        pilot_id = run_id.split("__", 1)[0]
        seed = MOD.SEED_BY_RECEPTOR_ROLE[(receptor, role)]
        monomer_rel, monomer_sha = self._asset(
            f"monomers/{pilot_id}_vhh_chainA.pdb", pdb_bytes("A")
        )
        receptor_rel, receptor_sha = self._asset(
            f"receptors/pvrig_{receptor.lower()}_chainB.pdb", pdb_bytes("B")
        )
        restraint_rel, restraint_sha = self._asset(
            f"restraints/{run_id}.tbl", f"! {run_id}\n".encode("ascii")
        )
        hotspot_rel, hotspot_sha = self._asset(
            f"hotspots/hotspot_residues_{receptor.lower()}.txt", b"92 95 98 100\n"
        )
        config_rel = f"runs/{run_id}/{run_id}.cfg"
        config_payload = (
            f"# Protocol: {MOD.SOURCE_PROTOCOL_ID}\n"
            f'run_dir = "run_{run_id}"\n'
            f"[topoaa]\niniseed = 917\n[rigidbody]\niniseed = {seed}\n"
        ).encode("ascii")
        _, config_sha = self._asset(config_rel, config_payload)
        run_dir = f"runs/{run_id}/run_{run_id}"
        stage = f"{run_dir}/4_emref"
        self._asset(
            f"{stage}/params.cfg",
            b"[emref]\niniseed = 917\ntolerance = 20\n",
        )
        outputs = []
        for index in range(source_count):
            file_name = f"emref_{index + 1}.pdb"
            score = [3.0, -2.0, -2.0, 1.0, 0.0, 2.0, 4.0, 5.0, 6.0, 7.0][index]
            coordinates = pdb_bytes("AB", float(index))
            if index == 1:
                self._asset(f"{stage}/{file_name}.gz", gzip.compress(coordinates, mtime=0))
            else:
                self._asset(f"{stage}/{file_name}", coordinates)
            outputs.append({"file_name": file_name, "score": score, "seed": seed + index + 1})
        self._asset(f"{stage}/io.json", json.dumps({"output": outputs}, sort_keys=True).encode("utf-8"))
        completion_rel = f"runs/{run_id}/{run_id}.complete.json"
        completion = {
            "schema_version": "phase2_v3_p2_pilot64_run_completion_v1_1",
            "protocol_id": MOD.SOURCE_PROTOCOL_ID,
            "run_id": run_id,
            "pilot_id": pilot_id,
            "source_candidate_id": f"source_{pilot_id}",
            "receptor_id": receptor,
            "seed_role": role,
            "iniseed": seed,
            "config_sha256": config_sha,
            "monomer_sha256": monomer_sha,
            "receptor_sha256": receptor_sha,
            "per_candidate_failure_tolerance_override": False,
            "tolerance_relaxed": False,
            "exit_code": 0,
            "status": "FAIL_DOCKING_OUTPUT_INCOMPLETE" if failed else "PASS_DOCKING_OUTPUT_COMPLETE",
            "stage_output_counts": {"emref": source_count, "final": 4 if failed else 8},
        }
        self._asset(
            completion_rel,
            (json.dumps(completion, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        return {
            "schema_version": "phase2_v3_p2_pilot64_run_manifest_v1_1",
            "protocol_id": MOD.SOURCE_PROTOCOL_ID,
            "run_id": run_id,
            "pilot_rank": str(pilot_rank),
            "pilot_id": pilot_id,
            "source_cohort": "fixture_failed" if failed else "fixture_smoke",
            "source_candidate_id": f"source_{pilot_id}",
            "receptor_id": receptor,
            "seed_role": role,
            "iniseed": str(seed),
            "topoaa_iniseed": "917",
            "rigidbody_iniseed": str(seed),
            "rigidbody_seed_start": str(seed + 1),
            "rigidbody_seed_end": str(seed + 40),
            "replicate_seed_required": "true",
            "config_relpath": config_rel,
            "config_sha256": config_sha,
            "run_workspace_relpath": f"runs/{run_id}",
            "run_dir_relpath": run_dir,
            "completion_relpath": completion_rel,
            "log_relpath": f"runs/{run_id}/{run_id}.log",
            "monomer_relpath": monomer_rel,
            "monomer_sha256": monomer_sha,
            "receptor_relpath": receptor_rel,
            "receptor_sha256": receptor_sha,
            "restraint_relpath": restraint_rel,
            "restraint_sha256": restraint_sha,
            "hotspot_relpath": hotspot_rel,
            "hotspot_sha256": hotspot_sha,
            "cdr1_range": "26-35",
            "cdr2_range": "53-59",
            "cdr3_range": "98-112",
            "expected_min_poses": "8",
            "expected_min_clusters": "2",
            "ncores": "4",
            "rigidbody_tolerance": "5",
            "rigidbody_sampling": "40",
            "seletop_select": "10",
            "flexref_tolerance": "20",
            "emref_tolerance": "20",
            "clustfcc_min_population": "1",
            "seletopclusts_top_models": "4",
            "per_candidate_failure_tolerance_override": "false",
            "tolerance_relaxed": "false",
            "haddock3_version_contract": "2025.11.0",
            "claim_boundary": "fixture",
        }

    def _build(self) -> None:
        rank = 0
        smoke_ids = [
            f"{pilot}__{receptor}__{role}"
            for pilot in MOD.SMOKE_PILOTS
            for receptor in MOD.RECEPTORS
            for role in MOD.SEED_ROLES
        ]
        for index, run_id in enumerate(smoke_ids):
            rank += 1
            self.rows.append(self._make_run(run_id, rank, 8 if index == 0 else 10, False))
        for pilot_number in range(100, 113):
            for receptor in MOD.RECEPTORS:
                for role in MOD.SEED_ROLES:
                    run_id = f"P2PILOT_{pilot_number:03d}__{receptor}__{role}"
                    self.failed_ids.append(run_id)
        assert len(self.failed_ids) == 52
        for index, run_id in enumerate(self.failed_ids):
            rank += 1
            self.rows.append(self._make_run(run_id, rank, 9 if index < 2 else 10, True))
        write_csv(self.manifest, self.rows)
        self.failed_audit.write_text(
            json.dumps(
                {
                    "schema_version": "phase2_v3_p2_docking_gold_audit_v1_1",
                    "protocol_id": MOD.SOURCE_PROTOCOL_ID,
                    "status": "FAIL_DOCKING_GOLD_NOT_VALIDATED",
                    "failed_receptor_runs": [
                        {"run_id": run_id, "reasons": "fixture final-stage failure"}
                        for run_id in self.failed_ids
                    ],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def runner(
        self,
        request: dict[str, object],
        outdir: Path,
        _ssh_executable: str,
        _host: str,
        _remote_root: str,
    ) -> None:
        self.sync_requests.append(request)
        relpaths = MOD.expand_request_file_relpaths(self.remote, request)
        for relpath in relpaths:
            source = self.remote / relpath
            destination = outdir / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        inventory = MOD.file_inventory(self.remote, relpaths)
        payload = {
            "schema_version": "phase2_v3_p2_v1_2_remote_file_inventory_v1",
            "request_sha256": request["request_sha256"],
            **inventory,
        }
        inventory_path = outdir / str(request["inventory_relpath"])
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        inventory_path.write_text(MOD.canonical_json(payload) + "\n", encoding="utf-8")

    def build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "manifest_path": self.manifest,
            "failed_audit_path": self.failed_audit,
            "outdir": self.outdir,
            "audit_path": self.audit,
            "output_csv": self.output,
            "cohort": "smoke8",
            "remote_root": str(self.remote),
            "workspace_root": Path("/"),
            "sync_runner": self.runner,
        }
        arguments.update(overrides)
        return MOD.build(**arguments)


class Pilot64EmrefRecoveryTests(unittest.TestCase):
    def test_smoke8_exact_counts_order_hashes_and_inventory_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            first = fixture.build()
            first_csv = fixture.output.read_bytes()
            second = fixture.build(inventory_only=True)
            rows = read_csv(fixture.output)

            self.assertEqual(first["counts"]["selected_runs"], 8)
            self.assertEqual(first["counts"]["source_poses"], 78)
            self.assertEqual(first["counts"]["selected_poses"], 64)
            self.assertEqual(first["expected_counts"], MOD.EXPECTED_COHORTS["smoke8"])
            self.assertEqual(first["remote_inventory"]["file_hash_chain"], first["local_inventory"]["file_hash_chain"])
            self.assertTrue(first["remote_local_hash_chain_equal"])
            self.assertEqual(first_csv, fixture.output.read_bytes())
            self.assertEqual(second["counts"], first["counts"])

            run_rows = [row for row in rows if row["run_id"] == "P2PILOT_001__8X6B__main"]
            self.assertEqual([int(row["canonical_rank"]) for row in run_rows], list(range(1, 9)))
            self.assertEqual(
                [int(row["source_output_index"]) for row in run_rows],
                [1, 2, 4, 3, 5, 0, 6, 7],
            )
            self.assertEqual(run_rows[0]["source_pose_format"], "pdb.gz")
            self.assertNotEqual(run_rows[0]["source_pose_sha256"], run_rows[0]["decompressed_coordinate_sha256"])
            self.assertEqual(run_rows[0]["source_docking_receptor"], "8x6b")
            self.assertEqual(run_rows[0]["candidate_id"], "P2PILOT_001")
            self.assertEqual(run_rows[0]["role"], "main")
            self.assertEqual(run_rows[0]["execution_mode"], MOD.EXECUTION_MODE)
            self.assertEqual(run_rows[0]["formal_eligible"], "false")
            self.assertEqual(run_rows[0]["selection_row_sha256"], MOD.row_sha256(run_rows[0], "selection_row_sha256"))
            requested = fixture.sync_requests[0]["required_relpaths"]
            self.assertFalse(any("6_seletopclusts" in path for path in requested))

    def test_failed52_exact_failed_audit_selection_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            audit = fixture.build(cohort="failed52")
            rows = read_csv(fixture.output)
            self.assertEqual(audit["counts"]["selected_runs"], 52)
            self.assertEqual(audit["counts"]["source_poses"], 518)
            self.assertEqual(audit["counts"]["selected_poses"], 416)
            self.assertEqual({row["run_id"] for row in rows}, set(fixture.failed_ids))
            self.assertEqual({row["completion_status"] for row in rows}, {"FAIL_DOCKING_OUTPUT_INCOMPLETE"})

    def test_explicit_runs_are_exact_repeatable_and_unknown_or_duplicate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            wanted = [
                "P2PILOT_001__9E6Y__main",
                "P2PILOT_033__8X6B__replicate",
            ]
            audit = fixture.build(cohort=None, explicit_run_ids=wanted)
            self.assertEqual(audit["selection_cohort"], "explicit")
            self.assertEqual(audit["counts"]["selected_runs"], 2)
            self.assertEqual({row["run_id"] for row in read_csv(fixture.output)}, set(wanted))
            for invalid in ([wanted[0], wanted[0]], ["P2PILOT_999__8X6B__main"]):
                with self.assertRaises(MOD.RecoveryError):
                    fixture.build(cohort=None, explicit_run_ids=invalid)

    def test_missing_pose_chain_and_manifest_hash_mismatch_fail_closed(self) -> None:
        scenarios = ("missing_pose", "missing_chain", "hash_mismatch")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                run_id = "P2PILOT_001__8X6B__main"
                stage = fixture.remote / f"runs/{run_id}/run_{run_id}/4_emref"
                if scenario == "missing_pose":
                    (stage / "emref_1.pdb").unlink()
                elif scenario == "missing_chain":
                    (stage / "emref_1.pdb").write_bytes(pdb_bytes("A"))
                else:
                    row = next(item for item in fixture.rows if item["run_id"] == run_id)
                    (fixture.remote / row["config_relpath"]).write_text("changed\n", encoding="ascii")
                with self.assertRaises(MOD.RecoveryError):
                    fixture.build()
                self.assertFalse(fixture.output.exists())
                self.assertFalse(fixture.audit.exists())

    def test_path_traversal_and_malicious_tar_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root)
            rows = read_csv(fixture.manifest)
            rows[0]["config_relpath"] = "../escape.cfg"
            write_csv(fixture.manifest, rows)
            with self.assertRaisesRegex(MOD.RecoveryError, "Unsafe"):
                fixture.build()

            request = MOD.build_sync_request([fixture.rows[0]], str(fixture.remote))
            archive_path = root / "malicious.tar"
            with tarfile.open(archive_path, "w") as archive:
                payload = b"escape"
                info = tarfile.TarInfo("../escape")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(MOD.RecoveryError):
                MOD.safe_extract_archive(archive_path, root / "extract", request)

    def test_ssh_invocation_is_an_argument_list_and_cli_selection_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            manifest = MOD.read_manifest(fixture.manifest)
            _payload, _hash, failed = MOD.read_failed_audit(
                fixture.failed_audit, {row["run_id"] for row in manifest.rows}
            )
            _label, selected, _expected = MOD.select_rows(manifest, failed, "smoke8", None)
            request = MOD.build_sync_request(selected, str(fixture.remote))
            command = MOD.ssh_command_args("ssh.exe", "node1", request)
            self.assertEqual(command[:2], ["ssh.exe", "node1"])
            self.assertEqual(len(command), 3)
            self.assertIn("python3", command[2])
            with self.assertRaises(MOD.RecoveryError):
                MOD.select_rows(manifest, failed, "smoke8", [selected[0]["run_id"]])

    def test_remote_archive_program_round_trips_a_local_fixture_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            row = next(
                item for item in fixture.rows if item["run_id"] == "P2PILOT_001__8X6B__main"
            )
            request = MOD.build_sync_request([row], str(fixture.remote))
            encoded = base64.urlsafe_b64encode(MOD.canonical_json(request).encode("utf-8")).decode("ascii")
            archive_path = Path(temporary) / "remote.tar"
            with archive_path.open("wb") as handle:
                completed = subprocess.run(
                    [sys.executable, "-c", MOD.REMOTE_ARCHIVE_PY, encoded],
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            destination = Path(temporary) / "roundtrip"
            remote = MOD.safe_extract_archive(archive_path, destination, request)
            persisted, local = MOD.load_and_verify_inventory(destination, request)
            self.assertEqual(remote["file_hash_chain"], persisted["file_hash_chain"])
            self.assertEqual(persisted["file_hash_chain"], local["file_hash_chain"])


if __name__ == "__main__":
    unittest.main()
