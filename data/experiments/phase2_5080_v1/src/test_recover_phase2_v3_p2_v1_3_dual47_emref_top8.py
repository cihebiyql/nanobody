#!/usr/bin/env python3
from __future__ import annotations

import csv
import copy
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).with_name("recover_phase2_v3_p2_v1_3_dual47_emref_top8.py")
SPEC = importlib.util.spec_from_file_location("recover_p2_v1_3_dual47_emref", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, chain: str, residue: int, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C  "
    )


def hetatm_line(
    serial: int,
    chain: str,
    residue: int,
    atom_name: str = "ZN",
    resname: str = "ZN",
    element: str = "ZN",
) -> str:
    return (
        f"HETATM{serial:5d} {atom_name:^4} {resname:>3} {chain}{residue:4d}    "
        f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00          {element:>2}  "
    )


def with_pdb_record(coordinates: bytes, record: str) -> bytes:
    lines = coordinates.decode("ascii").splitlines()
    lines.insert(lines.index("END"), record)
    return ("\n".join(lines) + "\n").encode("ascii")


def inject_pdb_record(path: Path, record: str) -> None:
    path.write_bytes(with_pdb_record(path.read_bytes(), record))


def pdb_bytes(chains: str, offset: float = 0.0) -> bytes:
    lines = [atom_line(index, chain, 1, offset + index) for index, chain in enumerate(chains, 1)]
    return ("\n".join(lines + ["END"]) + "\n").encode("ascii")


def monomer_pdb_bytes() -> bytes:
    ca = atom_line(1, "A", 1, 1.0)
    oxt = (
        f"ATOM  {2:5d} OXT  ALA A{1:4d}    "
        f"{2.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           O  "
    )
    return ("\n".join([ca, oxt, "END"]) + "\n").encode("ascii")


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
        self.workspace = root / "workspace"
        self.package = self.workspace / "data/v1_3_package"
        self.old_package = self.workspace / "data/old_package"
        self.remote_old = root / "remote_old"
        self.remote_new = root / "remote_new"
        self.outdir = self.workspace / "data/recovered"
        self.audit = self.workspace / "data/audit.json"
        self.output = self.outdir / "current" / MOD.OUTPUT_CSV_NAME
        self.audit = self.outdir / "current" / MOD.AUDIT_NAME
        self.run_manifest = self.package / "manifests/run_manifest.csv"
        self.reuse_manifest = self.package / "manifests/exact_reuse_manifest.csv"
        self.package_audit = self.package / "package_audit.json"
        self.execution_release = self.workspace / "data/execution_release.json"
        self.execution_release_sha256 = ""
        self.sync_requests: list[tuple[str, dict[str, object]]] = []
        for path in (self.workspace, self.package, self.old_package, self.remote_old, self.remote_new):
            path.mkdir(parents=True, exist_ok=True)
        self._build()

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(Path("/")).as_posix()

    @staticmethod
    def _asset(root: Path, relpath: str, payload: bytes) -> tuple[str, str]:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return relpath, MOD.sha256_file(path)

    @staticmethod
    def _config(protocol: str, run_id: str, receptor: str, old: bool) -> bytes:
        seed = MOD.SEED_BY_RECEPTOR[receptor]
        tail = "\n[clustfcc]\nmin_population = 1\n[seletopclusts]\ntop_models = 4\n" if old else "\n"
        return (
            f"# Protocol: {protocol}\n"
            f'run_dir = "run_{run_id}"\nmode = "local"\nncores = 4\n'
            f"[topoaa]\niniseed = 917\n"
            f"[rigidbody]\niniseed = {seed}\ntolerance = 5\nsampling = 40\n"
            f"[seletop]\nselect = 10\n[flexref]\ntolerance = 20\n"
            f"[emref]\ntolerance = 20\n{tail}"
        ).encode("ascii")

    def _run_assets(
        self,
        remote: Path,
        run_id: str,
        candidate: str,
        receptor: str,
        protocol: str,
        old: bool,
        fail_completion: bool = False,
    ) -> dict[str, str]:
        config_rel, config_sha = self._asset(
            remote, f"runs/{run_id}/{run_id}.cfg", self._config(protocol, run_id, receptor, old)
        )
        monomer_rel, monomer_sha = self._asset(
            remote, f"monomers/{candidate}_vhh_chainA.pdb", monomer_pdb_bytes()
        )
        receptor_rel, receptor_sha = self._asset(
            remote, f"receptors/pvrig_{receptor.lower()}_chainB.pdb", pdb_bytes("B")
        )
        restraint_rel, restraint_sha = self._asset(
            remote, f"restraints/{candidate}__{receptor}.tbl", f"! {run_id}\n".encode("ascii")
        )
        hotspot_rel, hotspot_sha = self._asset(
            remote, f"hotspots/hotspot_residues_{receptor.lower()}.txt", b"92 95 98 100\n"
        )
        run_dir = f"runs/{run_id}/run_{run_id}"
        stage = f"{run_dir}/4_emref"
        params_rel, params_sha = self._asset(
            remote, f"{stage}/params.cfg", b"[emref]\niniseed = 917\ntolerance = 20\n"
        )
        scores = [3.0, -2.0, -2.0, 1.0, 0.0, 2.0, 4.0, 5.0, 6.0, 7.0]
        outputs = []
        for index, score in enumerate(scores):
            name = f"emref_{index + 1}.pdb"
            coordinates = pdb_bytes("AB", float(index))
            stored = f"{stage}/{name}.gz" if index == 1 else f"{stage}/{name}"
            payload = gzip.compress(coordinates, mtime=0) if index == 1 else coordinates
            self._asset(remote, stored, payload)
            outputs.append({"file_name": name, "score": score, "seed": MOD.SEED_BY_RECEPTOR[receptor] + index + 1})
        io_rel, io_sha = self._asset(
            remote, f"{stage}/io.json", json.dumps({"output": outputs}, sort_keys=True).encode("utf-8")
        )
        counts = {"topoaa": 2, "rigidbody": 40, "seletop": 10, "flexref": 10, "emref": 10}
        completion_rel = f"runs/{run_id}/{run_id}.complete.json"
        if old:
            completion = {
                "schema_version": "fixture_old_completion_v1",
                "protocol_id": protocol,
                "run_id": run_id,
                "pilot_id": run_id.split("__", 1)[0],
                "receptor_id": receptor,
                "seed_role": "main",
                "iniseed": MOD.SEED_BY_RECEPTOR[receptor],
                "config_sha256": config_sha,
                "monomer_sha256": monomer_sha,
                "receptor_sha256": receptor_sha,
                "status": "FAIL_DOCKING_OUTPUT_INCOMPLETE" if fail_completion else "PASS_DOCKING_OUTPUT_COMPLETE",
                "exit_code": 0,
                "stage_output_counts": {**counts, "final": 0 if fail_completion else 4},
            }
        else:
            completion = {
                "schema_version": "phase2_v3_p2_v1_3_completion15_run_completion_v1",
                "protocol_id": protocol,
                "run_id": run_id,
                "case_id": candidate,
                "candidate_id": candidate,
                "receptor_id": receptor,
                "status": "PASS_4_EMREF_TOP8_READY",
                "exit_code": 0,
                "stage_output_counts": counts,
                "stage_output_requirements": {
                    stage_name: {"operator": operator, "value": value}
                    for stage_name, (operator, value) in MOD.STAGE_OUTPUT_REQUIREMENTS.items()
                },
                "config_sha256": config_sha,
                "monomer_sha256": monomer_sha,
                "receptor_sha256": receptor_sha,
                "fixed_top8_selection_performed": False,
                "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill",
                "formal_eligible": False,
                "training_label_release_eligible": False,
                "docking_gold_release_eligible": False,
            }
        _, completion_sha = self._asset(
            remote, completion_rel, (json.dumps(completion, sort_keys=True, indent=2) + "\n").encode("utf-8")
        )
        return {
            "config_relpath": config_rel, "config_sha256": config_sha,
            "run_workspace_relpath": f"runs/{run_id}", "run_dir_relpath": run_dir,
            "completion_relpath": completion_rel, "completion_sha256": completion_sha,
            "monomer_relpath": monomer_rel, "monomer_sha256": monomer_sha,
            "receptor_relpath": receptor_rel, "receptor_sha256": receptor_sha,
            "restraint_relpath": restraint_rel, "restraint_sha256": restraint_sha,
            "hotspot_relpath": hotspot_rel, "hotspot_sha256": hotspot_sha,
            "params_relpath": params_rel, "params_sha256": params_sha,
            "io_relpath": io_rel, "io_sha256": io_sha,
            "completion_status": completion["status"],
            "counts_json": MOD.canonical_json(counts),
        }

    def _common_v13_row(self, rank: int, receptor: str, mode: str) -> dict[str, str]:
        run_id = f"V13CAL_{rank:03d}__{receptor}__main"
        candidate = f"CAND_{rank:03d}"
        seed = MOD.SEED_BY_RECEPTOR[receptor]
        return {
            "schema_version": "phase2_v3_p2_v1_3_dual47_run_manifest_v1",
            "protocol_id": MOD.PROTOCOL_ID,
            "run_id": run_id,
            "case_rank": str(rank),
            "case_id": candidate,
            "candidate_id": candidate,
            "family": str((rank - 1) % 5 + 1),
            "anchor_class": "core_direct_blocker" if rank <= 5 else ("same_family_support" if rank <= 11 else "control"),
            "calibration_role": "fixture_calibration_only",
            "sequence_sha256": MOD.sha256_bytes(candidate.encode("ascii")),
            "teacher_manifest_relpath": "data/teacher.csv",
            "teacher_manifest_sha256": "a" * 64,
            "teacher_manifest_row_sha256": "b" * 64,
            "execution_mode": mode,
            "receptor_id": receptor,
            "seed_role": "main",
            "topoaa_iniseed": "917",
            "rigidbody_iniseed": str(seed),
            "rigidbody_seed_start": str(seed + 1),
            "rigidbody_seed_end": str(seed + 40),
            "ncores": "4",
            "rigidbody_sampling": "40",
            "rigidbody_tolerance": "5",
            "seletop_select": "10",
            "flexref_tolerance": "20",
            "emref_tolerance": "20",
            "cdr1_range": "26-35",
            "cdr2_range": "53-59",
            "cdr3_range": "98-112",
            "config_relpath": "",
            "config_sha256": "",
            "run_workspace_relpath": "",
            "run_dir_relpath": "",
            "completion_relpath": "",
            "log_relpath": "",
            "monomer_relpath": "",
            "monomer_sha256": "",
            "receptor_relpath": "",
            "receptor_sha256": "",
            "restraint_relpath": "",
            "restraint_sha256": "",
            "hotspot_relpath": "",
            "hotspot_sha256": "",
            "source_run_id": "",
            "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill",
            "formal_eligible": "false",
            "training_label_release_eligible": "false",
            "docking_gold_release_eligible": "false",
            "claim_boundary": "fixture",
            "run_manifest_row_sha256": "",
        }

    def _build(self) -> None:
        old_rows: list[dict[str, str]] = []
        old_assets: dict[str, dict[str, str]] = {}
        for rank in range(1, 33):
            pilot = f"P2PILOT_{rank:03d}"
            candidate = f"CAND_{rank:03d}"
            for receptor in MOD.EXPECTED_BY_RECEPTOR:
                run_id = f"{pilot}__{receptor}__main"
                assets = self._run_assets(
                    self.remote_old, run_id, pilot, receptor, MOD.OLD_PROTOCOL_ID, True,
                    fail_completion=(rank == 1 and receptor == "8X6B"),
                )
                old_assets[run_id] = assets
                seed = MOD.SEED_BY_RECEPTOR[receptor]
                old_rows.append({
                    "schema_version": "fixture_old_run_manifest_v1",
                    "protocol_id": MOD.OLD_PROTOCOL_ID,
                    "run_id": run_id,
                    "pilot_rank": str(rank),
                    "pilot_id": pilot,
                    "source_cohort": "fixture",
                    "source_candidate_id": candidate,
                    "receptor_id": receptor,
                    "seed_role": "main",
                    "iniseed": str(seed),
                    "topoaa_iniseed": "917",
                    "rigidbody_iniseed": str(seed),
                    "rigidbody_seed_start": str(seed + 1),
                    "rigidbody_seed_end": str(seed + 40),
                    "config_relpath": assets["config_relpath"],
                    "config_sha256": assets["config_sha256"],
                    "run_workspace_relpath": assets["run_workspace_relpath"],
                    "run_dir_relpath": assets["run_dir_relpath"],
                    "completion_relpath": assets["completion_relpath"],
                    "monomer_relpath": assets["monomer_relpath"],
                    "monomer_sha256": assets["monomer_sha256"],
                    "receptor_relpath": assets["receptor_relpath"],
                    "receptor_sha256": assets["receptor_sha256"],
                    "restraint_relpath": assets["restraint_relpath"],
                    "restraint_sha256": assets["restraint_sha256"],
                    "hotspot_relpath": assets["hotspot_relpath"],
                    "hotspot_sha256": assets["hotspot_sha256"],
                    "cdr1_range": "26-35", "cdr2_range": "53-59", "cdr3_range": "98-112",
                    "ncores": "4", "rigidbody_sampling": "40", "rigidbody_tolerance": "5",
                    "seletop_select": "10", "flexref_tolerance": "20", "emref_tolerance": "20",
                })
        old_manifest = self.old_package / "manifests/run_manifest.csv"
        write_csv(old_manifest, old_rows)
        controller = self.old_package / "scripts/controller.py"
        controller.parent.mkdir(parents=True, exist_ok=True)
        controller.write_text("# fixture controller\n", encoding="ascii")
        old_audit = self.old_package / "package_audit.json"
        old_audit.write_text(json.dumps({
            "protocol_id": MOD.OLD_PROTOCOL_ID,
            "run_manifest_sha256": MOD.sha256_file(old_manifest),
            "controller_sha256": MOD.sha256_file(controller),
        }, sort_keys=True) + "\n", encoding="utf-8")

        run_rows: list[dict[str, str]] = []
        reuse_rows: list[dict[str, str]] = []
        for rank in range(1, 48):
            candidate = f"CAND_{rank:03d}"
            mode = MOD.REUSE_MODE if rank <= 32 else MOD.NEW_MODE
            for receptor in MOD.EXPECTED_BY_RECEPTOR:
                row = self._common_v13_row(rank, receptor, mode)
                if mode == MOD.REUSE_MODE:
                    old_run_id = f"P2PILOT_{rank:03d}__{receptor}__main"
                    row["source_run_id"] = old_run_id
                else:
                    assets = self._run_assets(
                        self.remote_new, row["run_id"], candidate, receptor, MOD.PROTOCOL_ID, False
                    )
                    for field in (
                        "config_relpath", "config_sha256", "run_workspace_relpath", "run_dir_relpath",
                        "completion_relpath", "monomer_relpath", "monomer_sha256", "receptor_relpath",
                        "receptor_sha256", "restraint_relpath", "restraint_sha256", "hotspot_relpath",
                        "hotspot_sha256",
                    ):
                        row[field] = assets[field]
                    row["log_relpath"] = f"runs/{row['run_id']}/{row['run_id']}.log"
                row["run_manifest_row_sha256"] = MOD.row_sha256(row, "run_manifest_row_sha256")
                run_rows.append(row)
                if mode == MOD.REUSE_MODE:
                    assets = old_assets[row["source_run_id"]]
                    old_row = next(item for item in old_rows if item["run_id"] == row["source_run_id"])
                    extra = {
                        "source_protocol_id": MOD.OLD_PROTOCOL_ID,
                        "source_old_remote_root": str(self.remote_old),
                        "source_old_package_relpath": self.relative(self.old_package),
                        "source_old_package_audit_sha256": MOD.sha256_file(old_audit),
                        "source_old_controller_relpath": self.relative(controller),
                        "source_old_controller_sha256": MOD.sha256_file(controller),
                        "source_old_run_manifest_relpath": self.relative(old_manifest),
                        "source_old_run_manifest_sha256": MOD.sha256_file(old_manifest),
                        "source_old_run_manifest_row_sha256": MOD.sha256_bytes(MOD.canonical_json(old_row).encode("utf-8")),
                        "source_config_relpath": f"{self.remote_old}/{assets['config_relpath']}",
                        "source_config_sha256": assets["config_sha256"],
                        "source_completion_relpath": self.relative(self.old_package / assets["completion_relpath"]),
                        "source_completion_sha256": assets["completion_sha256"],
                        "source_completion_status": assets["completion_status"],
                        "source_completion_exit_code": "0",
                        "source_stage_output_counts_json": assets["counts_json"],
                        "source_emref_io_relpath": self.relative(self.old_package / assets["io_relpath"]),
                        "source_emref_io_sha256": assets["io_sha256"],
                        "source_emref_output_count": "10",
                        "source_emref_params_relpath": self.relative(self.old_package / assets["params_relpath"]),
                        "source_emref_params_sha256": assets["params_sha256"],
                        "v1_3_emref_gate_status": "PASS_4_EMREF_TOP8_READY",
                        "source_final_stage_ignored": "true",
                        "exact_reuse_run_identity_hash_closed": "true",
                        "source_emref_coordinate_payload_hash_closed": "false",
                        "coordinate_payload_state": "REMOTE_RECOVERY_REQUIRED_BEFORE_SCORING",
                        "reuse_manifest_row_sha256": "",
                    }
                    extended = {**row, **extra}
                    extended["reuse_manifest_row_sha256"] = MOD.row_sha256(extended, "reuse_manifest_row_sha256")
                    reuse_rows.append(extended)
        write_csv(self.run_manifest, run_rows)
        write_csv(self.reuse_manifest, reuse_rows)
        self.package_audit.write_text(json.dumps({
            "schema_version": "fixture_v1_3_package_audit_v1",
            "status": "PASS_V1_3_DUAL47_COMPLETION15_PACKAGE_READY",
            "protocol_id": MOD.PROTOCOL_ID,
            "run_count": 94,
            "reuse_run_count": 64,
            "new_run_count": 30,
            "formal_eligible": False,
            "training_label_release_eligible": False,
            "docking_gold_release_eligible": False,
            "remote_root": str(self.remote_new),
            "old_reuse_binding": {"remote_root": str(self.remote_old)},
            "manifests": {
                "run": {"sha256": MOD.sha256_file(self.run_manifest)},
                "reuse": {"sha256": MOD.sha256_file(self.reuse_manifest)},
            },
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        self._write_execution_release()

    def _write_execution_release(self, **extra: object) -> None:
        artifact_paths = [
            self.package_audit,
            self.run_manifest,
            self.reuse_manifest,
            self.old_package / "package_audit.json",
            self.old_package / "manifests/run_manifest.csv",
            self.old_package / "scripts/controller.py",
        ]
        payload: dict[str, object] = {
            "schema_version": "phase2_v3_p2_v1_3_docking_execution_release_v1",
            "protocol_id": MOD.PROTOCOL_ID,
            "status": "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE",
            "remote_launch_eligible": True,
            "remote_launch_run_count": 30,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "remote_root": str(self.remote_new),
            "package_audit_path": self.relative(self.package_audit),
            "remote_launch_contract": {
                "expected_new_cases": 15,
                "expected_new_runs": 30,
                "fixed_top_k": 8,
                "source_stage": "4_emref",
                "success_status": "PASS_4_EMREF_TOP8_READY",
                "backfill_allowed": False,
            },
            "execution_closure": {
                "candidate_count": 47,
                "new_completion15_run_count": 30,
                "reused_pilot64_main_run_count": 64,
                "run_count_per_receptor": 47,
                "total_main_run_count": 94,
            },
            "artifacts": [
                {
                    "path": self.relative(path),
                    "sha256": MOD.sha256_file(path),
                    "bytes": path.stat().st_size,
                }
                for path in artifact_paths
            ],
            **extra,
        }
        self.execution_release.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        self.execution_release_sha256 = MOD.sha256_file(self.execution_release)

    def runner(
        self,
        request: dict[str, object],
        outdir: Path,
        _ssh_executable: str,
        _host: str,
        remote_root: str,
    ) -> None:
        source = Path(remote_root)
        self.sync_requests.append((remote_root, request))
        relpaths = MOD.recovery_base.expand_request_file_relpaths(source, request)
        for relpath in relpaths:
            destination = outdir / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relpath, destination)
        inventory = MOD.recovery_base.file_inventory(source, relpaths)
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
            "run_manifest_path": self.run_manifest,
            "reuse_manifest_path": self.reuse_manifest,
            "package_audit_path": self.package_audit,
            "execution_release_manifest_path": self.execution_release,
            "outdir": self.outdir,
            "audit_path": self.audit,
            "workspace_root": Path("/"),
            "release_data_root": Path("/"),
            "sync_runner": self.runner,
        }
        arguments.update(overrides)
        with mock.patch.object(
            MOD, "FROZEN_EXECUTION_RELEASE_SHA256", self.execution_release_sha256
        ):
            return MOD.build(**arguments)

    def rewrite_reuse(self, rows: list[dict[str, str]]) -> None:
        for row in rows:
            row["reuse_manifest_row_sha256"] = MOD.row_sha256(row, "reuse_manifest_row_sha256")
        write_csv(self.reuse_manifest, rows)
        audit = json.loads(self.package_audit.read_text(encoding="utf-8"))
        audit["manifests"]["reuse"]["sha256"] = MOD.sha256_file(self.reuse_manifest)
        self.package_audit.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        self._write_execution_release()

    def rewrite_run_lane(self, run_id: str, field: str, value: str) -> None:
        run_rows = read_csv(self.run_manifest)
        target = next(row for row in run_rows if row["run_id"] == run_id)
        target[field] = value
        for row in run_rows:
            row["run_manifest_row_sha256"] = MOD.row_sha256(row, "run_manifest_row_sha256")
        write_csv(self.run_manifest, run_rows)
        run_by_id = {row["run_id"]: row for row in run_rows}
        reuse_rows = read_csv(self.reuse_manifest)
        for row in reuse_rows:
            for key, item in run_by_id[row["run_id"]].items():
                row[key] = item
            row["reuse_manifest_row_sha256"] = MOD.row_sha256(
                row, "reuse_manifest_row_sha256"
            )
        write_csv(self.reuse_manifest, reuse_rows)
        package = json.loads(self.package_audit.read_text(encoding="utf-8"))
        package["manifests"]["run"]["sha256"] = MOD.sha256_file(self.run_manifest)
        package["manifests"]["reuse"]["sha256"] = MOD.sha256_file(self.reuse_manifest)
        self.package_audit.write_text(
            json.dumps(package, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        self._write_execution_release()


class V13Dual47RecoveryTests(unittest.TestCase):
    def test_full_94_run_752_pose_dual_source_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            audit = fixture.build()
            rows = read_csv(fixture.output)
            self.assertEqual(audit["status"], "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED")
            self.assertEqual(audit["counts"]["selected_runs"], 94)
            self.assertEqual(audit["counts"]["selected_poses"], 752)
            self.assertEqual(audit["pose_counts_by_receptor"], {"8X6B": 376, "9E6Y": 376})
            self.assertEqual(audit["pose_counts_by_source_mode"], {
                MOD.REUSE_MODE: 512, MOD.NEW_MODE: 240,
            })
            self.assertTrue(audit["remote_local_hash_chain_equal"])
            self.assertEqual({root for root, _request in fixture.sync_requests}, {
                str(fixture.remote_old), str(fixture.remote_new),
            })
            self.assertFalse(any("6_seletopclusts" in path for _root, request in fixture.sync_requests
                                 for path in request["required_relpaths"]))
            self.assertEqual(len(rows), 752)
            self.assertEqual(Counter(row["generation_receptor"] for row in rows), Counter({"8X6B": 376, "9E6Y": 376}))
            first = [row for row in rows if row["run_id"] == "V13CAL_001__8X6B__main"]
            self.assertEqual([int(row["native_rank"]) for row in first], list(range(1, 9)))
            self.assertEqual([int(row["source_output_index"]) for row in first], [1, 2, 4, 3, 5, 0, 6, 7])
            self.assertEqual({row["completion_status"] for row in first}, {"FAIL_DOCKING_OUTPUT_INCOMPLETE"})
            self.assertEqual({row["source_final_stage_ignored"] for row in first}, {"true"})
            self.assertEqual(first[0]["source_pose_format"], "pdb.gz")
            self.assertNotEqual(first[0]["source_pose_sha256"], first[0]["decompressed_coordinate_sha256"])
            self.assertEqual(first[0]["sequence_sha256"], MOD.sha256_bytes(b"CAND_001"))
            self.assertEqual(first[0]["teacher_manifest_sha256"], "a" * 64)
            self.assertNotEqual(
                first[0]["monomer_atom_identity_sha256"],
                first[0]["pose_vhh_atom_identity_sha256"],
            )
            self.assertEqual(
                first[0]["monomer_residue_identity_sha256"],
                first[0]["pose_vhh_residue_identity_sha256"],
            )
            self.assertEqual(first[0]["vhh_raw_atom_identity_exact"], "false")
            self.assertEqual(first[0]["vhh_terminal_oxt_normalization_applied"], "true")
            self.assertEqual(first[0]["vhh_normalized_atom_identity_exact"], "true")
            self.assertEqual(first[0]["pvrig_raw_atom_identity_exact"], "true")
            self.assertEqual(
                first[0]["schema_version"],
                "phase2_v3_p2_v1_3_dual47_emref_top8_selection_v2",
            )
            self.assertEqual(
                first[0]["identity_normalization_amendment_sha256"],
                MOD.FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_SHA256,
            )
            self.assertEqual(
                {row["identity_normalization_amendment_v2_sha256"] for row in rows},
                {MOD.FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_SHA256},
            )
            self.assertEqual(
                {
                    row["identity_normalization_amendment_v2_validator_sha256"]
                    for row in rows
                },
                {MOD.FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_VALIDATOR_SHA256},
            )
            for field in (
                "monomer_vhh_heavy_hetatm_identity_count",
                "pose_vhh_heavy_hetatm_identity_count",
                "receptor_pvrig_heavy_hetatm_identity_count",
                "pose_pvrig_heavy_hetatm_identity_count",
            ):
                self.assertEqual({row[field] for row in rows}, {"0"})
            for field in (
                "monomer_vhh_heavy_hetatm_zero_gate_pass",
                "pose_vhh_heavy_hetatm_zero_gate_pass",
                "receptor_pvrig_heavy_hetatm_zero_gate_pass",
                "pose_pvrig_heavy_hetatm_zero_gate_pass",
                "vhh_heavy_hetatm_raw_identity_exact",
                "pvrig_heavy_hetatm_raw_identity_exact",
                "heavy_hetatm_zero_gate_pass",
            ):
                self.assertEqual({row[field] for row in rows}, {"true"})
            self.assertEqual(
                {row["heavy_hetatm_zero_gate_rule_id"] for row in rows},
                {"CHAIN_A_B_ZERO_HEAVY_HETATM_V1"},
            )
            self.assertEqual(
                first[0]["receptor_residue_identity_sha256"],
                first[0]["pose_pvrig_residue_identity_sha256"],
            )
            self.assertEqual(
                audit["schema_version"],
                "phase2_v3_p2_v1_3_dual47_emref_top8_recovery_audit_v2",
            )
            self.assertEqual(
                audit["inputs"]["atom_hetatm_identity_amendment_v2"]["sha256"],
                MOD.FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_SHA256,
            )
            self.assertEqual(
                audit["inputs"]["atom_hetatm_identity_amendment_v2"][
                    "validator_sha256"
                ],
                MOD.FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_VALIDATOR_SHA256,
            )
            identity_summary = audit["identity_gate_summary"]
            self.assertEqual(
                identity_summary["monomer_vhh_heavy_hetatm_identity_count_total"], 0
            )
            self.assertEqual(
                identity_summary["receptor_pvrig_heavy_hetatm_identity_count_total"],
                0,
            )
            self.assertEqual(
                identity_summary["pose_vhh_heavy_hetatm_identity_count_total"], 0
            )
            self.assertEqual(
                identity_summary["pose_pvrig_heavy_hetatm_identity_count_total"], 0
            )
            self.assertEqual(
                identity_summary["monomer_vhh_heavy_hetatm_zero_gate_pass_count"],
                94,
            )
            self.assertEqual(
                identity_summary["receptor_pvrig_heavy_hetatm_zero_gate_pass_count"],
                94,
            )
            self.assertEqual(
                identity_summary["pose_vhh_heavy_hetatm_zero_gate_pass_count"], 752
            )
            self.assertEqual(
                identity_summary["pose_pvrig_heavy_hetatm_zero_gate_pass_count"],
                752,
            )
            self.assertEqual(
                identity_summary["vhh_heavy_hetatm_raw_identity_exact_count"], 752
            )
            self.assertEqual(
                identity_summary["pvrig_heavy_hetatm_raw_identity_exact_count"], 752
            )
            self.assertEqual(identity_summary["heavy_hetatm_zero_gate_pass_count"], 752)
            self.assertFalse(identity_summary["coordinate_or_score_modified"])
            self.assertEqual(
                [row["source_score"] for row in first],
                ["-2", "-2", "0", "1", "2", "3", "4", "5"],
            )
            for row in (first[0], rows[-1]):
                materialized = Path("/") / row["materialized_coordinate_relpath"]
                source = Path("/") / row["source_pose_relpath"]
                self.assertTrue(materialized.is_file())
                self.assertEqual(MOD.sha256_file(materialized), row["materialized_coordinate_sha256"])
                self.assertEqual(
                    MOD.recovery_base.read_coordinate_bytes(source),
                    materialized.read_bytes(),
                )
                self.assertEqual(
                    MOD.sha256_bytes(materialized.read_bytes()),
                    row["decompressed_coordinate_sha256"],
                )
                self.assertEqual(row["selection_row_sha256"], MOD.row_sha256(row, "selection_row_sha256"))

    def test_inventory_only_rebuild_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            first = fixture.build()
            first_bytes = fixture.output.read_bytes()
            second = fixture.build(inventory_only=True)
            self.assertEqual(first_bytes, fixture.output.read_bytes())
            self.assertEqual(first["output_csv"]["sha256"], second["output_csv"]["sha256"])
            self.assertEqual(first["publication"]["release_id"], second["publication"]["release_id"])
            self.assertTrue((fixture.outdir / "current").is_symlink())

    def test_old_fail_requires_explicit_final_stage_ignore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            rows = read_csv(fixture.reuse_manifest)
            target = next(row for row in rows if row["run_id"] == "V13CAL_001__8X6B__main")
            target["source_final_stage_ignored"] = "false"
            fixture.rewrite_reuse(rows)
            with self.assertRaisesRegex(MOD.RecoveryError, "final-stage ignore"):
                fixture.build()
            self.assertFalse(fixture.output.exists())

    def test_hash_mismatch_and_under_k_new_run_fail_closed_without_backfill(self) -> None:
        for scenario in ("config_hash", "under_k"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                run_id = "V13CAL_033__8X6B__main"
                row = next(item for item in read_csv(fixture.run_manifest) if item["run_id"] == run_id)
                if scenario == "config_hash":
                    (fixture.remote_new / row["config_relpath"]).write_text("tampered\n", encoding="ascii")
                else:
                    io_path = fixture.remote_new / row["run_dir_relpath"] / "4_emref/io.json"
                    io_payload = json.loads(io_path.read_text(encoding="utf-8"))
                    io_payload["output"] = io_payload["output"][:7]
                    io_path.write_text(json.dumps(io_payload, sort_keys=True), encoding="utf-8")
                    completion_path = fixture.remote_new / row["completion_relpath"]
                    completion = json.loads(completion_path.read_text(encoding="utf-8"))
                    completion["stage_output_counts"]["emref"] = 7
                    completion_path.write_text(json.dumps(completion, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                with self.assertRaises(MOD.RecoveryError):
                    fixture.build()
                self.assertFalse(fixture.output.exists())
                self.assertFalse(fixture.audit.exists())

    def test_cli_uses_frozen_release_and_has_no_remote_root_override(self) -> None:
        args = MOD.parse_args([])
        self.assertEqual(args.execution_release_manifest, MOD.DEFAULT_EXECUTION_RELEASE_MANIFEST)
        self.assertFalse(hasattr(args, "old_remote_root"))
        self.assertFalse(hasattr(args, "new_remote_root"))
        self.assertEqual(args.outdir, MOD.DEFAULT_OUTDIR)
        self.assertIsNone(args.audit)
        self.assertEqual(MOD.DEFAULT_OUTPUT_CSV.parent.name, "current")
        self.assertEqual(MOD.DEFAULT_AUDIT.parent.name, "current")

    def test_execution_release_self_artifacts_and_both_roots_fail_closed(self) -> None:
        scenarios = ("manifest_self", "artifact", "new_root", "old_root")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                if scenario == "manifest_self":
                    payload = json.loads(fixture.execution_release.read_text(encoding="utf-8"))
                    payload["remote_root"] = "/unauthenticated/new-root"
                    fixture.execution_release.write_text(
                        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                    )
                    expected = "release hash mismatch"
                elif scenario == "artifact":
                    fixture.package_audit.write_text("{}\n", encoding="utf-8")
                    expected = "artifact hash/size mismatch"
                elif scenario == "new_root":
                    fixture._write_execution_release(remote_root="/authenticated-but-inconsistent")
                    expected = "new remote roots differ"
                else:
                    package = json.loads(fixture.package_audit.read_text(encoding="utf-8"))
                    package["old_reuse_binding"]["remote_root"] = "/inconsistent-old-root"
                    fixture.package_audit.write_text(
                        json.dumps(package, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                    )
                    fixture._write_execution_release()
                    expected = "old remote roots differ"
                with self.assertRaisesRegex(MOD.RecoveryError, expected):
                    fixture.build()
                self.assertFalse(fixture.output.exists())

    def test_pose_atom_identity_must_match_frozen_monomer_and_receptor(self) -> None:
        for chain in ("A", "B"):
            with self.subTest(chain=chain), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                run_id = "P2PILOT_001__8X6B__main"
                pose = (
                    fixture.remote_old / f"runs/{run_id}/run_{run_id}/4_emref/emref_1.pdb"
                )
                lines = pose.read_text(encoding="ascii").splitlines()
                changed = False
                for index, line in enumerate(lines):
                    if line.startswith("ATOM  ") and line[21:22] == chain:
                        lines[index] = line[:17] + "GLY" + line[20:]
                        changed = True
                        break
                self.assertTrue(changed)
                pose.write_text("\n".join(lines) + "\n", encoding="ascii")
                with self.assertRaisesRegex(MOD.RecoveryError, f"chain {chain} .*identity mismatch"):
                    fixture.build()
                self.assertFalse(fixture.output.exists())

    def test_pose_heavy_hetatm_injection_fails_closed_for_both_chains(self) -> None:
        for chain in ("A", "B"):
            with self.subTest(chain=chain), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                run_id = "P2PILOT_001__8X6B__main"
                pose = (
                    fixture.remote_old
                    / f"runs/{run_id}/run_{run_id}/4_emref/emref_1.pdb"
                )
                inject_pdb_record(pose, hetatm_line(99, chain, 201))
                with self.assertRaisesRegex(
                    MOD.RecoveryError,
                    f"pose chain {chain} heavy HETATM identity count must be zero",
                ):
                    fixture.build()
                self.assertFalse(fixture.output.exists())

    def test_reference_and_hetatm_oxt_injections_fail_closed(self) -> None:
        amendment_v2 = MOD.load_identity_normalization_amendment_v2()
        cases = (
            (
                "A",
                "reference",
                with_pdb_record(monomer_pdb_bytes(), hetatm_line(9, "A", 201)),
                "frozen monomer",
            ),
            (
                "B",
                "reference",
                with_pdb_record(pdb_bytes("B"), hetatm_line(9, "B", 201)),
                "frozen receptor",
            ),
            (
                "A",
                "pose",
                with_pdb_record(
                    pdb_bytes("AB"),
                    hetatm_line(
                        9,
                        "A",
                        1,
                        atom_name="OXT",
                        resname="ALA",
                        element="O",
                    ),
                ),
                "HETATM OXT pose",
            ),
        )
        for chain, role, coordinates, label in cases:
            with self.subTest(chain=chain, role=role, label=label):
                identity = MOD.hetatm_heavy_identity_signature(
                    coordinates, chain, Path(f"{label}.pdb")
                )
                with self.assertRaisesRegex(
                    MOD.RecoveryError,
                    f"chain {chain} heavy HETATM identity count must be zero",
                ):
                    MOD.require_zero_heavy_hetatm(
                        identity, label, chain, role, amendment_v2
                    )

    def test_reference_heavy_hetatm_injection_fails_inside_build(self) -> None:
        for chain, asset_key, label in (
            ("A", "monomer", "frozen monomer"),
            ("B", "receptor", "frozen receptor"),
        ):
            with self.subTest(chain=chain), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary))
                original_verify = MOD.verify_asset_hashes
                injected = False

                def verify_then_inject(
                    source_root: Path, descriptor: object
                ) -> dict[str, Path]:
                    nonlocal injected
                    assets = original_verify(source_root, descriptor)
                    if not injected:
                        inject_pdb_record(
                            assets[asset_key], hetatm_line(99, chain, 201)
                        )
                        injected = True
                    return assets

                with mock.patch.object(
                    MOD, "verify_asset_hashes", side_effect=verify_then_inject
                ):
                    with self.assertRaisesRegex(
                        MOD.RecoveryError,
                        f"{label} chain {chain} heavy HETATM identity count must be zero",
                    ):
                        fixture.build()
                self.assertTrue(injected)
                self.assertFalse(fixture.output.exists())

    def test_dual_lane_metadata_and_monomer_hash_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.rewrite_run_lane(
                "V13CAL_001__9E6Y__main", "candidate_id", "DIFFERENT_CANDIDATE"
            )
            with self.assertRaisesRegex(MOD.RecoveryError, "Dual-lane identity mismatch.*candidate_id"):
                fixture.build()

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            runs, reuse = MOD.load_inputs(fixture.run_manifest, fixture.reuse_manifest)
            old, _binding = MOD.old_manifest_context(reuse, Path("/"))
            descriptors = MOD.source_descriptors(
                runs, reuse, old, str(fixture.remote_old), str(fixture.remote_new)
            )
            changed = []
            for descriptor in descriptors:
                if descriptor.run["run_id"] == "V13CAL_001__9E6Y__main":
                    hashes = dict(descriptor.expected_hashes)
                    hashes["monomer"] = "f" * 64
                    descriptor = replace(descriptor, expected_hashes=hashes)
                changed.append(descriptor)
            with self.assertRaisesRegex(MOD.RecoveryError, "monomer_sha256"):
                MOD.validate_dual_lane_identity(changed)

    def test_top8_coordinate_hash_seed_uniqueness_and_frozen_range(self) -> None:
        run = {
            "run_id": "V13CAL_001__8X6B__main",
            "rigidbody_seed_start": "918",
            "rigidbody_seed_end": "957",
        }
        records = [
            SimpleNamespace(coordinate_sha256=f"{index + 1:064x}", seed=918 + index)
            for index in range(8)
        ]
        MOD.validate_selected_pose_invariants(records, run)
        duplicate_hash = list(records)
        duplicate_hash[7] = SimpleNamespace(
            coordinate_sha256=records[0].coordinate_sha256, seed=records[7].seed
        )
        with self.assertRaisesRegex(MOD.RecoveryError, "coordinate hashes are not unique"):
            MOD.validate_selected_pose_invariants(duplicate_hash, run)
        duplicate_seed = list(records)
        duplicate_seed[7] = SimpleNamespace(
            coordinate_sha256=records[7].coordinate_sha256, seed=records[0].seed
        )
        with self.assertRaisesRegex(MOD.RecoveryError, "pose seeds are not unique"):
            MOD.validate_selected_pose_invariants(duplicate_seed, run)
        out_of_range = list(records)
        out_of_range[7] = SimpleNamespace(
            coordinate_sha256=records[7].coordinate_sha256, seed=958
        )
        with self.assertRaisesRegex(MOD.RecoveryError, "outside frozen receptor-specific range"):
            MOD.validate_selected_pose_invariants(out_of_range, run)

    def test_amendment_is_hard_bound_and_only_terminal_chain_a_oxt_is_normalized(self) -> None:
        amendment = MOD.load_identity_normalization_amendment()
        reference = MOD.atom_heavy_identity_signature(
            monomer_pdb_bytes(), "A", Path("reference.pdb")
        )
        pose = MOD.atom_heavy_identity_signature(
            pdb_bytes("A"), "A", Path("pose.pdb")
        )
        accepted = MOD.require_identity_match(
            reference, pose, "positive chain A", "A", amendment
        )
        self.assertFalse(accepted["raw_atom_identity_exact"])
        self.assertTrue(accepted["terminal_oxt_normalization_applied"])
        self.assertTrue(accepted["normalized_atom_identity_exact"])

        non_oxt = copy.deepcopy(reference)
        non_oxt["atom_identities"].append(("1", "", "ALA", "CB", "", "C"))
        with self.assertRaisesRegex(MOD.RecoveryError, "non-OXT ATOM identity mismatch"):
            MOD.require_identity_match(non_oxt, pose, "non-OXT", "A", amendment)

        non_terminal = copy.deepcopy(reference)
        bad_oxt = ("0", "", "GLY", "OXT", "", "O")
        non_terminal["atom_identities"].append(bad_oxt)
        non_terminal["non_terminal_oxt_identities"] = [bad_oxt]
        with self.assertRaisesRegex(MOD.RecoveryError, "forbidden non-terminal OXT"):
            MOD.require_identity_match(non_terminal, pose, "non-terminal", "A", amendment)

        multiple_oxt = copy.deepcopy(reference)
        alternate_oxt = ("1", "", "ALA", "OXT", "A", "O")
        multiple_oxt["atom_identities"].append(alternate_oxt)
        multiple_oxt["terminal_oxt_identities"].append(alternate_oxt)
        with self.assertRaisesRegex(MOD.RecoveryError, "exceeds terminal-OXT-only"):
            MOD.require_identity_match(multiple_oxt, pose, "multiple OXT", "A", amendment)

        reordered_terminal = copy.deepcopy(pose)
        reordered_terminal["terminal_residue"] = ("999", "", "ALA")
        with self.assertRaisesRegex(MOD.RecoveryError, "terminal residue identity mismatch"):
            MOD.require_identity_match(reference, reordered_terminal, "terminal", "A", amendment)

        receptor = MOD.atom_heavy_identity_signature(pdb_bytes("B"), "B", Path("receptor.pdb"))
        receptor_pose = copy.deepcopy(receptor)
        receptor_oxt = ("1", "", "ALA", "OXT", "", "O")
        receptor_pose["atom_identities"].append(receptor_oxt)
        with self.assertRaisesRegex(MOD.RecoveryError, "chain B raw ATOM identity mismatch"):
            MOD.require_identity_match(receptor, receptor_pose, "receptor", "B", amendment)

        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "amendment.json"
            payload = json.loads(
                MOD.DEFAULT_IDENTITY_NORMALIZATION_AMENDMENT.read_text(encoding="utf-8")
            )
            payload["normalization_rule"]["allowed_atom_name"] = "O"
            tampered.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MOD.RecoveryError, "amendment hash mismatch"):
                MOD.load_identity_normalization_amendment(tampered)

    def test_amendment_v2_and_validator_are_hard_bound(self) -> None:
        amendment_v2 = MOD.load_identity_normalization_amendment_v2()
        self.assertEqual(
            amendment_v2["heavy_hetatm_rule"]["rule_id"],
            "CHAIN_A_B_ZERO_HEAVY_HETATM_V1",
        )
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "amendment_v2.json"
            payload = json.loads(
                MOD.DEFAULT_IDENTITY_NORMALIZATION_AMENDMENT_V2.read_text(
                    encoding="utf-8"
                )
            )
            payload["heavy_hetatm_rule"]["any_heavy_hetatm_identity"] = "allow"
            tampered.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                MOD.RecoveryError, "amendment v2 hash mismatch"
            ):
                MOD.load_identity_normalization_amendment_v2(tampered)
        with mock.patch.object(
            MOD,
            "FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_VALIDATOR_SHA256",
            "0" * 64,
        ):
            with self.assertRaisesRegex(MOD.RecoveryError, "validator hash mismatch"):
                MOD.load_identity_normalization_amendment_v2()

    def test_publication_release_id_binds_amendment_v2_and_validator(self) -> None:
        kwargs = {
            "execution_release_sha256": "1" * 64,
            "run_manifest_sha256": "2" * 64,
            "reuse_manifest_sha256": "3" * 64,
            "selector_sha256": "4" * 64,
            "selector_helper_sha256": "5" * 64,
        }
        baseline = MOD.publication_release_id(**kwargs)
        with mock.patch.object(
            MOD, "FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_SHA256", "6" * 64
        ):
            self.assertNotEqual(baseline, MOD.publication_release_id(**kwargs))
        with mock.patch.object(
            MOD,
            "FROZEN_IDENTITY_NORMALIZATION_AMENDMENT_V2_VALIDATOR_SHA256",
            "7" * 64,
        ):
            self.assertNotEqual(baseline, MOD.publication_release_id(**kwargs))

    def test_versioned_publication_pointer_failure_rolls_back_everything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            first = fixture.build()
            current = fixture.outdir / "current"
            previous_release = current.resolve()
            previous_csv = fixture.output.read_bytes()
            previous_audit = fixture.audit.read_bytes()
            fixture._write_execution_release(revision_note="authenticated second publication")

            def fail_promotion(_release: Path, _current: Path) -> None:
                raise RuntimeError("injected pointer failure")

            with self.assertRaisesRegex(RuntimeError, "injected pointer failure"):
                fixture.build(inventory_only=True, pointer_promoter=fail_promotion)
            self.assertEqual(current.resolve(), previous_release)
            self.assertEqual(fixture.output.read_bytes(), previous_csv)
            self.assertEqual(fixture.audit.read_bytes(), previous_audit)
            self.assertEqual(len(list((fixture.outdir / "releases").iterdir())), 1)
            self.assertEqual(first["publication"]["release_id"], previous_release.name)
            self.assertFalse(any(fixture.outdir.glob(".*.staging.*")))


if __name__ == "__main__":
    unittest.main()
