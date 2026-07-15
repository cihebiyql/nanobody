#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "process_phase2_v3_p2_v1_3_native_top8.py"
)
if str(MODULE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("process_p2_v1_3_native_top8", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pdb_line(
    serial: int,
    atom: str,
    resname: str,
    chain: str,
    resseq: int,
    xyz: tuple[float, float, float],
    *,
    record: str = "ATOM",
    element: str = "C",
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom:>4} {resname:>3} {chain}{resseq:4d}    "
        f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 20.00          "
        f"{element:>2}  "
    )


def base_point(index: int) -> tuple[float, float, float]:
    return (
        float((index % 5) * 2),
        float(((index // 5) % 5) * 1.7),
        float(((index * 7) % 11) * 0.6),
    )


def native_9e6y(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return -point[1] + 5.0, point[0] - 2.0, point[2] + 7.0


def translate(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return point[0] + 12.0, point[1] - 8.0, point[2] + 4.0


def pose_inventory(chain: str, atom_count: int, residue_count: int) -> dict[str, object]:
    return {
        "chain": chain,
        "selection_rule": "heavy ATOM and HETATM records retained for pose protein chains",
        "parsed_atom_and_hetatm_count": atom_count,
        "selected_heavy_atom_count": atom_count,
        "selected_residue_count": residue_count,
        "atom_heavy_atom_count": atom_count,
        "atom_residue_count": residue_count,
        "hetatm_heavy_atom_count": 0,
        "hetatm_residue_count": 0,
        "excluded_hydrogen_or_deuterium_count": 0,
        "altloc_heavy_atom_count": 0,
        "altloc_labels": [],
    }


class NativeFixture:
    def __init__(self, root: Path, poses_per_run: int = 2) -> None:
        self.root = root
        self.poses_per_run = poses_per_run
        self.positive_manifest = root / "inputs/positives.csv"
        self.mutant_manifest = root / "inputs/mutants.csv"
        self.preregistration = root / "inputs/preregistration.json"
        self.selector_impl = root / "tools/selector.py"
        self.selector_helper = root / "tools/helper.py"
        self.selector_release_id = "V13_SYNTHETIC_RELEASE_001"
        self.selector_publication_root = root / "selector_publication"
        self.selector_release_dir = (
            self.selector_publication_root / "releases" / self.selector_release_id
        )
        self.selector_csv = self.selector_release_dir / "selector.csv"
        self.selector_audit = self.selector_release_dir / "selector_audit.json"
        self.execution_release_manifest = root / "inputs/execution_release.json"
        self.case_manifest = root / "inputs/case_manifest.csv"
        self.run_manifest = root / "inputs/run_manifest.csv"
        self.protocol_manifest = root / "inputs/protocol_manifest.csv"
        self.identity_amendment = self.selector_release_dir / "identity_amendment.json"
        self.hotspots = root / "inputs/hotspots.csv"
        self.reconciliation = root / "inputs/reconciliation.csv"
        self.references = {
            "8X6B": root / "references/8X6B.pdb",
            "9E6Y": root / "references/9E6Y.pdb",
        }
        self.source_poses: list[Path] = []
        self.coordinate_paths: list[Path] = []
        self._write_manifests()
        self._write_preregistration()
        self._write_hotspots_and_reconciliation()
        self._write_references()
        self._write_selector_and_audit()

    def _write_manifests(self) -> None:
        write_csv(
            self.positive_manifest,
            [
                "recommended_order",
                "calibration_name",
                "family",
                "validation_role",
                "sequence_type",
                "cdr1_range",
                "cdr2_range",
                "cdr3_range",
                "usage_boundary",
            ],
            [
                {
                    "recommended_order": 1,
                    "calibration_name": "case_01",
                    "family": "F1",
                    "validation_role": "positive_anchor",
                    "sequence_type": "synthetic_test",
                    "cdr1_range": "1-1",
                    "cdr2_range": "2-2",
                    "cdr3_range": "3-3",
                    "usage_boundary": "synthetic_development_only",
                }
            ],
        )
        write_csv(
            self.mutant_manifest,
            [
                "panel_order",
                "mutant_name",
                "family",
                "intended_role",
                "control_type",
                "cdr1_range",
                "cdr2_range",
                "cdr3_range",
            ],
            [],
        )

    def _write_preregistration(self) -> None:
        MOD.write_json(
            self.preregistration,
            {
                "protocol_id": MOD.PROTOCOL_ID,
                "status": "PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION",
                "training_state": "P2_TRAINING_BLOCKED",
                "primary_processing": {
                    "native_only": True,
                    "expected_native_pose_count": 2 * self.poses_per_run,
                },
                "eligibility": {
                    "formal_eligible": False,
                    "p2_training_ready": False,
                    "training_label_release_eligible": False,
                    "docking_gold_release_eligible": False,
                },
            },
        )

    def _write_hotspots_and_reconciliation(self) -> None:
        hotspot_rows: list[dict[str, object]] = []
        reconciliation_rows: list[dict[str, object]] = []
        for index in range(1, 24):
            uniprot = 1000 + index
            hotspot_rows.append(
                {
                    "hotspot_id": f"H{index:02d}",
                    "hotspot_class": "core_hotspot",
                    "priority_weight": "1.0",
                    "uniprot_position": uniprot,
                    "pdb_8x6b_ref": f"B:{index}A",
                    "pdb_9e6y_ref": f"A:{100 + index}A",
                }
            )
            reconciliation_rows.extend(
                [
                    {
                        "pdb_id": "8X6B",
                        "pvrig_chain": "B",
                        "pdb_resseq": index,
                        "pdb_icode": "",
                        "uniprot_position": uniprot,
                    },
                    {
                        "pdb_id": "9E6Y",
                        "pvrig_chain": "A",
                        "pdb_resseq": 100 + index,
                        "pdb_icode": "",
                        "uniprot_position": uniprot,
                    },
                ]
            )
        write_csv(
            self.hotspots,
            [
                "hotspot_id",
                "hotspot_class",
                "priority_weight",
                "uniprot_position",
                "pdb_8x6b_ref",
                "pdb_9e6y_ref",
            ],
            hotspot_rows,
        )
        write_csv(
            self.reconciliation,
            [
                "pdb_id",
                "pvrig_chain",
                "pdb_resseq",
                "pdb_icode",
                "uniprot_position",
            ],
            reconciliation_rows,
        )

    def _write_references(self) -> None:
        lines_8: list[str] = []
        lines_9: list[str] = []
        serial = 1
        for index in range(1, 24):
            point = base_point(index)
            lines_8.append(pdb_line(serial, "CA", "ALA", "B", index, point))
            lines_9.append(
                pdb_line(
                    serial,
                    "CA",
                    "ALA",
                    "A",
                    100 + index,
                    native_9e6y(point),
                )
            )
            serial += 1
        pvrig_origin = base_point(1)
        pvrl2_8 = (pvrig_origin[0], pvrig_origin[1], pvrig_origin[2] + 3.0)
        pvrl2_9 = native_9e6y(pvrl2_8)
        lines_8.extend(
            [
                pdb_line(serial, "CA", "GLY", "A", 200, pvrl2_8),
                pdb_line(
                    serial + 1,
                    "O",
                    "HOH",
                    "A",
                    300,
                    (50.0, 50.0, 50.0),
                    record="HETATM",
                    element="O",
                ),
            ]
        )
        lines_9.extend(
            [
                pdb_line(serial, "CA", "GLY", "D", 200, pvrl2_9),
                pdb_line(
                    serial + 1,
                    "O",
                    "HOH",
                    "D",
                    300,
                    (50.0, 50.0, 50.0),
                    record="HETATM",
                    element="O",
                ),
                pdb_line(
                    serial + 2,
                    "C1",
                    "EDO",
                    "D",
                    301,
                    (55.0, 50.0, 50.0),
                    record="HETATM",
                ),
            ]
        )
        self.references["8X6B"].parent.mkdir(parents=True, exist_ok=True)
        self.references["8X6B"].write_text("\n".join(lines_8 + ["END"]) + "\n")
        self.references["9E6Y"].write_text("\n".join(lines_9 + ["END"]) + "\n")

    def _pose_bytes(self, receptor: str, pose_index: int) -> bytes:
        lines: list[str] = []
        serial = 1
        for index in range(1, 24):
            if receptor == "8X6B":
                number = index
                point = base_point(index)
            else:
                number = 100 + index
                point = native_9e6y(base_point(index))
            lines.append(pdb_line(serial, "CA", "ALA", "B", number, translate(point)))
            serial += 1
        origin = base_point(1) if receptor == "8X6B" else native_9e6y(base_point(1))
        for residue, z_offset in ((1, 2.8), (2, 3.2), (3, 3.6)):
            point = translate(
                (
                    origin[0] + pose_index * 0.02,
                    origin[1],
                    origin[2] + z_offset,
                )
            )
            lines.append(pdb_line(serial, "CA", "GLY", "A", residue, point))
            serial += 1
        return ("\n".join(lines + ["END"]) + "\n").encode("ascii")

    def _write_selector_and_audit(self) -> None:
        self.selector_impl.parent.mkdir(parents=True, exist_ok=True)
        self.selector_impl.write_text("# synthetic selector\n", encoding="utf-8")
        self.selector_helper.write_text("# synthetic helper\n", encoding="utf-8")
        self.selector_release_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            MOD.selector_contract.DEFAULT_IDENTITY_NORMALIZATION_AMENDMENT,
            self.identity_amendment,
        )
        amendment = MOD.selector_contract.load_identity_normalization_amendment()
        with self.positive_manifest.open(newline="", encoding="utf-8") as handle:
            teacher_row = next(csv.DictReader(handle))
        teacher_row_hash = MOD.sha256_json(teacher_row)
        sequence_hash = MOD.sha256_bytes(b"sequence")
        write_csv(self.case_manifest, ["case_id", "candidate_id"], [{"case_id": "case_01", "candidate_id": "case_01"}])
        write_csv(self.protocol_manifest, ["protocol_id"], [{"protocol_id": MOD.SELECTOR_PROTOCOL_ID}])

        run_rows: list[dict[str, str]] = []
        run_assets: dict[str, dict[str, object]] = {}
        common_monomer = self.selector_release_dir / "assets/common_monomer.pdb"
        for receptor in MOD.RECEPTORS:
            run_id = f"V13CAL_001__{receptor}__main"
            run_dir = self.selector_release_dir / "assets" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            pose_records: list[dict[str, object]] = []
            for native_rank in range(1, self.poses_per_run + 1):
                coordinates = self._pose_bytes(receptor, native_rank)
                coordinate_path = run_dir / f"rank_{native_rank:02d}.pdb"
                coordinate_path.parent.mkdir(parents=True, exist_ok=True)
                coordinate_path.write_bytes(coordinates)
                source_path = run_dir / f"rank_{native_rank:02d}.pdb.gz"
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(gzip.compress(coordinates, mtime=0))
                self.coordinate_paths.append(coordinate_path)
                self.source_poses.append(source_path)
                pose_records.append(
                    {
                        "rank": native_rank,
                        "coordinates": coordinates,
                        "coordinate_path": coordinate_path,
                        "source_path": source_path,
                        "score": -20.0 + native_rank,
                        "seed": 900 + native_rank,
                    }
                )

            first_coordinates = pose_records[0]["coordinates"]
            assert isinstance(first_coordinates, bytes)
            monomer = common_monomer
            receptor_path = run_dir / "receptor.pdb"
            if not monomer.exists():
                monomer.write_text(
                    "\n".join(
                        line
                        for line in first_coordinates.decode("ascii").splitlines()
                        if line.startswith("ATOM  ") and line[21] == "A"
                    )
                    + "\nEND\n"
                )
            receptor_path.write_text(
                "\n".join(
                    line
                    for line in first_coordinates.decode("ascii").splitlines()
                    if line.startswith("ATOM  ") and line[21] == "B"
                )
                + "\nEND\n"
            )
            restraint = run_dir / "restraint.tbl"
            restraint.write_text("assign (segid A) (segid B) 2.0 2.0 0.0\n")
            hotspot = run_dir / "hotspots.txt"
            hotspot.write_text(
                "\n".join(
                    str(MOD.core.parse_pdb_residue_ref(item["mobile_ref"])[1])
                    for item in MOD.build_native_alignment_pair_rows(self.hotspots, receptor)
                )
                + "\n"
            )
            params = run_dir / "params.cfg"
            params.write_text("[emref]\niniseed = 917\ntolerance = 20\n")
            io_path = run_dir / "io.json"
            MOD.write_json(
                io_path,
                {
                    "output": [
                        {
                            "file_name": Path(record["source_path"]).name,
                            "score": record["score"],
                            "seed": record["seed"],
                        }
                        for record in pose_records
                    ]
                    + [
                        {
                            "file_name": f"unused_{index:02d}.pdb.gz",
                            "score": -1.0 + index,
                            "seed": 1000 + index,
                        }
                        for index in range(self.poses_per_run, 8)
                    ]
                },
            )
            rigidbody_seed = 917 if receptor == "8X6B" else 20917
            config_path = run_dir / "run.cfg"
            config_path.write_text(
                f"# Protocol: {MOD.SELECTOR_PROTOCOL_ID}\n"
                f'run_dir = "run_{run_id}"\nmode = "local"\nncores = 4\n'
                f'molecules = ["{monomer.name}", "{receptor_path.name}"]\n'
                "[topoaa]\niniseed = 917\n"
                f"[rigidbody]\nambig_fname = \"{restraint.name}\"\niniseed = {rigidbody_seed}\ntolerance = 5\nsampling = 40\n"
                "[seletop]\nselect = 10\n[flexref]\ntolerance = 20\n"
                f'ambig_fname = "{restraint.name}"\n[emref]\ntolerance = 20\nambig_fname = "{restraint.name}"\n'
            )
            completion = run_dir / "completion.json"
            MOD.write_json(
                completion,
                {
                    "protocol_id": MOD.SELECTOR_PROTOCOL_ID,
                    "run_id": run_id,
                    "case_id": "case_01",
                    "candidate_id": "case_01",
                    "receptor_id": receptor,
                    "status": "PASS_4_EMREF_TOP8_READY",
                    "exit_code": 0,
                    "config_sha256": MOD.sha256_file(config_path),
                    "monomer_sha256": MOD.sha256_file(monomer),
                    "receptor_sha256": MOD.sha256_file(receptor_path),
                    "fixed_top8_selection_performed": False,
                    "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill",
                    "formal_eligible": False,
                    "training_label_release_eligible": False,
                    "docking_gold_release_eligible": False,
                    "stage_output_counts": {
                        "topoaa": 2,
                        "rigidbody": 40,
                        "seletop": 10,
                        "flexref": 8,
                        "emref": 8,
                    },
                    "stage_output_requirements": {
                        "topoaa": {"operator": "eq", "value": 2},
                        "rigidbody": {"operator": "ge", "value": 38},
                        "seletop": {"operator": "eq", "value": 10},
                        "flexref": {"operator": "ge", "value": 8},
                        "emref": {"operator": "ge", "value": 8},
                    },
                },
            )
            run_row: dict[str, str] = {
                "run_id": run_id,
                "case_id": "case_01",
                "candidate_id": "case_01",
                "family": "F1",
                "receptor_id": receptor,
                "execution_mode": MOD.NEW_SOURCE_MODE,
                "sequence_sha256": sequence_hash,
                "teacher_manifest_relpath": self.positive_manifest.relative_to(self.root).as_posix(),
                "teacher_manifest_sha256": MOD.sha256_file(self.positive_manifest),
                "teacher_manifest_row_sha256": teacher_row_hash,
                "cdr1_range": "1-1",
                "cdr2_range": "2-2",
                "cdr3_range": "3-3",
                "config_sha256": MOD.sha256_file(config_path),
                "monomer_sha256": MOD.sha256_file(monomer),
                "receptor_sha256": MOD.sha256_file(receptor_path),
                "restraint_sha256": MOD.sha256_file(restraint),
                "hotspot_sha256": MOD.sha256_file(hotspot),
                "run_manifest_row_sha256": "",
            }
            run_row["run_manifest_row_sha256"] = MOD.row_sha256(
                run_row, "run_manifest_row_sha256"
            )
            run_rows.append(run_row)
            run_assets[receptor] = {
                "run_id": run_id,
                "run_row": run_row,
                "pose_records": pose_records,
                "config": config_path,
                "completion": completion,
                "monomer": monomer,
                "receptor": receptor_path,
                "restraint": restraint,
                "hotspot": hotspot,
                "params": params,
                "io": io_path,
                "rigidbody_seed": rigidbody_seed,
            }

        write_csv(self.run_manifest, list(run_rows[0]), run_rows)
        execution_artifacts = []
        for path in (self.preregistration, self.case_manifest, self.run_manifest, self.protocol_manifest):
            execution_artifacts.append(
                {
                    "path": str(path.resolve()),
                    "sha256": MOD.sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
        MOD.write_json(
            self.execution_release_manifest,
            {
                "schema_version": "phase2_v3_p2_v1_3_docking_execution_release_v1",
                "status": "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE",
                "artifacts": execution_artifacts,
            },
        )

        rows: list[dict[str, str]] = []
        for receptor in MOD.RECEPTORS:
            assets = run_assets[receptor]
            run_id = str(assets["run_id"])
            monomer = Path(assets["monomer"])
            receptor_path = Path(assets["receptor"])
            monomer_identity = MOD.selector_contract.atom_heavy_identity_signature(monomer.read_bytes(), "A", monomer)
            receptor_identity = MOD.selector_contract.atom_heavy_identity_signature(receptor_path.read_bytes(), "B", receptor_path)
            for record in assets["pose_records"]:
                native_rank = int(record["rank"])
                coordinates = record["coordinates"]
                coordinate_path = Path(record["coordinate_path"])
                source_path = Path(record["source_path"])
                assert isinstance(coordinates, bytes)
                source_payload = source_path.read_bytes()
                pose_vhh = MOD.selector_contract.atom_heavy_identity_signature(coordinates, "A", coordinate_path)
                pose_pvrig = MOD.selector_contract.atom_heavy_identity_signature(coordinates, "B", coordinate_path)
                vhh_gate = MOD.selector_contract.require_identity_match(monomer_identity, pose_vhh, "synthetic VHH", "A", amendment)
                pvrig_gate = MOD.selector_contract.require_identity_match(receptor_identity, pose_pvrig, "synthetic PVRIG", "B", amendment)
                row: dict[str, object] = {
                    field: "" for field in MOD.SELECTOR_REQUIRED_FIELDS
                }
                row.update(
                    {
                        "schema_version": MOD.SELECTOR_SCHEMA,
                        "protocol_id": MOD.SELECTOR_PROTOCOL_ID,
                        "source_protocol_id": MOD.SELECTOR_PROTOCOL_ID,
                        "source_protocol": MOD.POSE_SOURCE_PROTOCOL,
                        "source_stage": "4_emref",
                        "source_mode": MOD.NEW_SOURCE_MODE,
                        "run_id": run_id,
                        "source_run_id": run_id,
                        "case_id": "case_01",
                        "candidate_id": "case_01",
                        "family": "F1",
                        "anchor_class": "known_positive",
                        "sequence_sha256": sequence_hash,
                        "teacher_manifest_relpath": self.positive_manifest.relative_to(
                            self.root
                        ).as_posix(),
                        "teacher_manifest_sha256": MOD.sha256_file(
                            self.positive_manifest
                        ),
                        "teacher_manifest_row_sha256": teacher_row_hash,
                        "generation_receptor": receptor,
                        "receptor_id": receptor,
                        "topoaa_iniseed": 917,
                        "rigidbody_iniseed": assets["rigidbody_seed"],
                        "rigidbody_seed_start": int(assets["rigidbody_seed"]) + 1,
                        "rigidbody_seed_end": int(assets["rigidbody_seed"]) + 40,
                        "cdr1_range": "1-1",
                        "cdr2_range": "2-2",
                        "cdr3_range": "3-3",
                        "native_rank": native_rank,
                        "canonical_rank": native_rank,
                        "source_output_index": native_rank - 1,
                        "source_output_file": source_path.name,
                        "source_score": record["score"],
                        "source_seed": record["seed"],
                        "source_pose_relpath": source_path.relative_to(self.root).as_posix(),
                        "materialized_coordinate_relpath": coordinate_path.relative_to(
                            self.root
                        ).as_posix(),
                        "source_pose_format": "pdb.gz",
                        "source_pose_sha256": MOD.sha256_bytes(source_payload),
                        "source_pose_bytes": len(source_payload),
                        "compressed_source_sha256": MOD.sha256_bytes(source_payload),
                        "compressed_source_bytes": len(source_payload),
                        "decompressed_coordinate_sha256": MOD.sha256_bytes(coordinates),
                        "decompressed_coordinate_bytes": len(coordinates),
                        "materialized_coordinate_sha256": MOD.sha256_bytes(coordinates),
                        "materialized_coordinate_bytes": len(coordinates),
                        "vhh_chain_id": "A",
                        "vhh_atom_count": 3,
                        "vhh_residue_count": 3,
                        "vhh_chain_inventory_json": MOD.canonical_json(
                            pose_inventory("A", 3, 3)
                        ),
                        "pvrig_chain_id": "B",
                        "pvrig_atom_count": 23,
                        "pvrig_residue_count": 23,
                        "pvrig_chain_inventory_json": MOD.canonical_json(
                            pose_inventory("B", 23, 23)
                        ),
                        "monomer_atom_identity_sha256": monomer_identity["atom_identity_sha256"],
                        "monomer_residue_identity_sha256": monomer_identity["residue_identity_sha256"],
                        "pose_vhh_atom_identity_sha256": pose_vhh["atom_identity_sha256"],
                        "pose_vhh_residue_identity_sha256": pose_vhh["residue_identity_sha256"],
                        "receptor_atom_identity_sha256": receptor_identity["atom_identity_sha256"],
                        "receptor_residue_identity_sha256": receptor_identity["residue_identity_sha256"],
                        "pose_pvrig_atom_identity_sha256": pose_pvrig["atom_identity_sha256"],
                        "pose_pvrig_residue_identity_sha256": pose_pvrig["residue_identity_sha256"],
                        "vhh_identity_gate_rule_id": vhh_gate["rule_id"],
                        "vhh_raw_atom_identity_exact": str(vhh_gate["raw_atom_identity_exact"]).lower(),
                        "vhh_terminal_oxt_normalization_applied": str(vhh_gate["terminal_oxt_normalization_applied"]).lower(),
                        "vhh_normalized_atom_identity_exact": str(vhh_gate["normalized_atom_identity_exact"]).lower(),
                        "pvrig_raw_atom_identity_exact": str(pvrig_gate["raw_atom_identity_exact"]).lower(),
                        "identity_normalization_amendment_relpath": self.identity_amendment.relative_to(self.root).as_posix(),
                        "identity_normalization_amendment_sha256": MOD.sha256_file(self.identity_amendment),
                        "completion_status": "PASS_4_EMREF_TOP8_READY",
                        "completion_exit_code": 0,
                        "source_final_stage_ignored": "false",
                        "config_relpath": Path(assets["config"]).relative_to(self.root).as_posix(),
                        "completion_relpath": Path(assets["completion"]).relative_to(self.root).as_posix(),
                        "monomer_relpath": monomer.relative_to(self.root).as_posix(),
                        "remote_monomer_relpath": monomer.name,
                        "receptor_relpath": receptor_path.relative_to(self.root).as_posix(),
                        "remote_receptor_relpath": receptor_path.name,
                        "restraint_relpath": Path(assets["restraint"]).relative_to(self.root).as_posix(),
                        "remote_restraint_relpath": Path(assets["restraint"]).name,
                        "hotspot_relpath": Path(assets["hotspot"]).relative_to(self.root).as_posix(),
                        "source_params_relpath": Path(assets["params"]).relative_to(self.root).as_posix(),
                        "source_io_relpath": Path(assets["io"]).relative_to(self.root).as_posix(),
                        "config_sha256": MOD.sha256_file(Path(assets["config"])),
                        "completion_sha256": MOD.sha256_file(Path(assets["completion"])),
                        "monomer_sha256": MOD.sha256_file(monomer),
                        "receptor_sha256": MOD.sha256_file(receptor_path),
                        "restraint_sha256": MOD.sha256_file(Path(assets["restraint"])),
                        "hotspot_sha256": MOD.sha256_file(Path(assets["hotspot"])),
                        "source_params_sha256": MOD.sha256_file(Path(assets["params"])),
                        "source_io_sha256": MOD.sha256_file(Path(assets["io"])),
                        "run_manifest_relpath": self.run_manifest.relative_to(self.root).as_posix(),
                        "run_manifest_sha256": MOD.sha256_file(self.run_manifest),
                        "run_manifest_row_sha256": assets["run_row"]["run_manifest_row_sha256"],
                        "execution_release_manifest_relpath": (
                            self.execution_release_manifest.relative_to(self.root).as_posix()
                        ),
                        "execution_release_manifest_sha256": MOD.sha256_file(
                            self.execution_release_manifest
                        ),
                        "publication_release_id": self.selector_release_id,
                        "remote_inventory_request_sha256": MOD.sha256_bytes(b"request"),
                        "remote_file_hash_chain": MOD.sha256_bytes(b"files"),
                        "local_file_hash_chain": MOD.sha256_bytes(b"files"),
                        "selector_implementation_relpath": self.selector_impl.relative_to(
                            self.root
                        ).as_posix(),
                        "selector_implementation_sha256": MOD.sha256_file(
                            self.selector_impl
                        ),
                        "selector_helper_relpath": self.selector_helper.relative_to(
                            self.root
                        ).as_posix(),
                        "selector_helper_sha256": MOD.sha256_file(self.selector_helper),
                        "formal_eligible": "false",
                        "training_label_release_eligible": "false",
                        "docking_gold_release_eligible": "false",
                        "p2_training_ready": "false",
                        "selection_row_sha256": "",
                    }
                )
                normalized = {key: str(value) for key, value in row.items()}
                normalized["selection_row_sha256"] = MOD.row_sha256(
                    normalized, "selection_row_sha256"
                )
                rows.append(normalized)
        # The selector's frozen CSV order is not the processor's sort order.
        rows.reverse()
        fields = sorted(MOD.SELECTOR_REQUIRED_FIELDS - {"selection_row_sha256"}) + [
            "selection_row_sha256"
        ]
        write_csv(self.selector_csv, fields, rows)
        MOD.write_json(
            self.selector_audit,
            {
                "schema_version": MOD.SELECTOR_AUDIT_SCHEMA,
                "status": MOD.SELECTOR_AUDIT_STATUS,
                "protocol_id": MOD.SELECTOR_PROTOCOL_ID,
                "formal_eligible": False,
                "training_label_release_eligible": False,
                "docking_gold_release_eligible": False,
                "p2_training_ready": False,
                "remote_local_hash_chain_equal": True,
                "source_protocol": MOD.POSE_SOURCE_PROTOCOL,
                "k": self.poses_per_run,
                "selection_backfill": False,
                "scoring_performed": False,
                "counts": {
                    "manifest_runs": 2,
                    "selected_runs": 2,
                    "selected_poses": 2 * self.poses_per_run,
                    "cases": 1,
                },
                "run_counts_by_receptor": {"8X6B": 1, "9E6Y": 1},
                "pose_counts_by_receptor": {
                    "8X6B": self.poses_per_run,
                    "9E6Y": self.poses_per_run,
                },
                "inputs": {
                    "execution_release_manifest": {
                        "relpath": self.execution_release_manifest.relative_to(
                            self.root
                        ).as_posix(),
                        "sha256": MOD.sha256_file(self.execution_release_manifest),
                    }
                },
                "publication": {
                    "release_id": self.selector_release_id,
                    "release_relpath": self.selector_release_dir.relative_to(self.root).as_posix(),
                },
                "output_csv": {
                    "relpath": self.selector_csv.relative_to(self.root).as_posix(),
                    "sha256": MOD.sha256_file(self.selector_csv),
                    "rows": len(rows),
                    "selection_row_hash_chain": MOD.sha256_bytes(
                        "\n".join(row["selection_row_sha256"] for row in rows).encode(
                            "ascii"
                        )
                    ),
                },
            },
        )
        current = self.selector_publication_root / "current"
        current.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(self.selector_release_dir, current.parent), current, target_is_directory=True)

    @property
    def expected_reference_inventories(self) -> dict[str, dict[str, object]]:
        return {
            "8X6B": {
                "chain": "A",
                "parsed_atom_and_hetatm_count": 2,
                "protein_atom_heavy_atom_count": 1,
                "protein_atom_residue_count": 1,
                "selected_protein_heavy_atom_count": 1,
                "selected_protein_residue_count": 1,
                "excluded_hetatm_heavy_atom_count": 1,
                "excluded_hetatm_residue_count": 1,
                "excluded_hoh_heavy_atom_count": 1,
                "excluded_hoh_residue_count": 1,
                "excluded_edo_heavy_atom_count": 0,
                "excluded_edo_residue_count": 0,
                "excluded_other_hetatm_heavy_atom_count": 0,
                "excluded_other_hetatm_residue_count": 0,
                "atom_altloc_heavy_atom_count": 0,
                "atom_altloc_labels": [],
            },
            "9E6Y": {
                "chain": "D",
                "parsed_atom_and_hetatm_count": 3,
                "protein_atom_heavy_atom_count": 1,
                "protein_atom_residue_count": 1,
                "selected_protein_heavy_atom_count": 1,
                "selected_protein_residue_count": 1,
                "excluded_hetatm_heavy_atom_count": 2,
                "excluded_hetatm_residue_count": 2,
                "excluded_hoh_heavy_atom_count": 1,
                "excluded_hoh_residue_count": 1,
                "excluded_edo_heavy_atom_count": 1,
                "excluded_edo_residue_count": 1,
                "excluded_other_hetatm_heavy_atom_count": 0,
                "excluded_other_hetatm_residue_count": 0,
                "atom_altloc_heavy_atom_count": 0,
                "atom_altloc_labels": [],
            },
        }

    def config(self, outdir: Path) -> MOD.BuildConfig:
        return MOD.BuildConfig(
            selector_csv=self.selector_csv,
            selector_audit=self.selector_audit,
            selector_implementation=self.selector_impl,
            preregistration=self.preregistration,
            positive_manifest=self.positive_manifest,
            mutant_manifest=self.mutant_manifest,
            aligner=MOD.DEFAULT_ALIGNER,
            pose_scorer=MOD.DEFAULT_POSE_SCORER,
            region_scorer=MOD.DEFAULT_REGION_SCORER,
            scoring_helper=MOD.DEFAULT_SCORING_HELPER,
            hotspots=self.hotspots,
            reconciliation=self.reconciliation,
            references=self.references,
            expected_reference_inventories=self.expected_reference_inventories,
            outdir=outdir,
            workspace_root=self.root,
            contract=MOD.DatasetContract(
                positive_cases=1,
                mutant_cases=0,
                receptors=("8X6B", "9E6Y"),
                poses_per_run=self.poses_per_run,
                reuse_run_count=None,
                new_run_count=None,
            ),
            jobs=1,
        )


class V13NativeTop8Tests(unittest.TestCase):
    def test_default_47x2x8_closure_and_exact_headers(self) -> None:
        contract = MOD.DatasetContract()
        self.assertEqual(contract.case_count, 47)
        self.assertEqual(contract.run_count, 94)
        self.assertEqual(contract.pose_count, 752)
        rows = [
            {
                "candidate_id": f"case_{case:02d}",
                "generation_receptor": receptor,
                "native_rank": str(rank),
            }
            for case in range(47)
            for receptor in ("8X6B", "9E6Y")
            for rank in range(1, 9)
        ]
        counts = MOD.validate_native_key_closure(rows, contract)
        self.assertEqual(counts, Counter({"8X6B": 376, "9E6Y": 376}))
        self.assertEqual(len(MOD.MATERIALIZATION_FIELDS), len(set(MOD.MATERIALIZATION_FIELDS)))
        self.assertEqual(len(MOD.METRICS_FIELDS), len(set(MOD.METRICS_FIELDS)))
        for field in (*MOD.MATERIALIZATION_FIELDS, *MOD.METRICS_FIELDS):
            self.assertFalse(MOD.is_forbidden_output_field(field), field)

    def test_native_only_alignment_direct_9e6y_numbering_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            outdir = fixture.root / "output"
            first_audit = MOD.build_package(fixture.config(outdir))
            published = outdir / "current"
            first_files = {
                path.relative_to(published).as_posix(): path.read_bytes()
                for path in published.rglob("*")
                if path.is_file()
            }
            second_audit = MOD.build_package(fixture.config(outdir))
            second_files = {
                path.relative_to(published).as_posix(): path.read_bytes()
                for path in published.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_audit, second_audit)
            self.assertEqual(first_files, second_files)

            material = read_csv(published / MOD.MATERIALIZATION_MANIFEST_NAME)
            metrics = read_csv(published / MOD.CONTINUOUS_METRICS_NAME)
            contacts = [
                json.loads(line)
                for line in (published / MOD.RESIDUE_CONTACTS_NAME).read_text().splitlines()
            ]
            self.assertEqual(len(material), 4)
            self.assertEqual(len(metrics), 4)
            self.assertEqual(len(contacts), 4)
            self.assertEqual(
                Counter(row["generation_receptor"] for row in metrics),
                Counter({"8X6B": 2, "9E6Y": 2}),
            )
            self.assertEqual(
                {
                    (row["candidate_id"], row["generation_receptor"], row["native_rank"])
                    for row in metrics
                },
                {
                    ("case_01", receptor, str(rank))
                    for receptor in MOD.RECEPTORS
                    for rank in range(1, 3)
                },
            )
            from experiments.phase2_5080_v1.src import (
                calibrate_phase2_v3_p2_v1_3_dual_native as calibrator,
            )

            downstream = calibrator.validate_metrics_rows(
                list(metrics[0]),
                metrics,
                {"case_01": {"family": "F1"}},
                {},
                calibrator.CalibrationContract(
                    case_count=1,
                    positive_case_count=1,
                    positive_family_count=1,
                    control_case_count=0,
                    mutant_delta_count=0,
                    receptors_per_case=2,
                    ranks_per_run=2,
                ),
            )
            self.assertEqual(downstream["metric_rows"], 4)
            self.assertTrue(downstream["atom_only_reference_inventory_gate_passed"])
            self.assertNotIn("baseline", metrics[0])
            self.assertNotIn("paired_rank", metrics[0])
            self.assertEqual(
                {row["native_hotspot_ref_column"] for row in metrics if row["generation_receptor"] == "9E6Y"},
                {"pdb_9e6y_ref"},
            )
            native_map_9 = read_csv(
                published / first_audit["output_sha256"]["alignment_maps"]["9E6Y"]["relpath"]
            )
            self.assertEqual(native_map_9[0], {"mobile_ref": "B:101A", "reference_ref": "A:101A"})
            self.assertEqual(native_map_9[-1], {"mobile_ref": "B:123A", "reference_ref": "A:123A"})
            aligned_9 = published / next(
                row["aligned_pose_relpath"]
                for row in material
                if row["generation_receptor"] == "9E6Y"
            )
            residue_numbers = {
                int(line[22:26])
                for line in aligned_9.read_text().splitlines()
                if line.startswith("ATOM  ") and line[21] == "B"
            }
            self.assertEqual(residue_numbers, set(range(101, 124)))
            self.assertEqual(
                first_audit["observed_contract"]["rows_by_generation_receptor"],
                {"8X6B": 2, "9E6Y": 2},
            )
            self.assertEqual(first_audit["status"], MOD.PROCESSOR_PENDING_STATUS)
            self.assertFalse(first_audit["primary_native_metric_eligible"])
            self.assertFalse(first_audit["formal_eligible"])
            self.assertFalse(first_audit["training_label_release_eligible"])
            self.assertFalse(first_audit["docking_gold_release_eligible"])
            self.assertFalse(first_audit["p2_training_ready"])
            self.assertFalse(first_audit["development_release_state"]["validated"])
            self.assertEqual(
                first_audit["reference_inventory_observed"]["9E6Y"]
                ["excluded_hetatm_heavy_atom_count"],
                2,
            )
            for row in metrics:
                self.assertEqual(row["formal_eligible"], "false")
                self.assertGreater(float(row["hotspot_weight_fraction"]), 0.0)
                self.assertTrue(row["metrics_row_sha256"])
            serialized_outputs = json.dumps(
                {"material": material, "metrics": metrics, "contacts": contacts},
                sort_keys=True,
            ).lower()
            for forbidden in ("geometry_class", "native_class", "dual_tier", "r_gold"):
                self.assertNotIn(forbidden, serialized_outputs)

            self.assertTrue(published.is_symlink())
            self.assertTrue((outdir / "releases" / first_audit["publication_contract"]["release_id"]).is_dir())

    def test_fail_closed_source_hash_atom_inventory_and_conditional_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            config = fixture.config(fixture.root / "bad_hash_output")
            fixture.source_poses[0].write_bytes(b"drift")
            with self.assertRaises(MOD.ContractError):
                MOD.build_package(config)
            self.assertFalse((config.outdir / "current").exists())

        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            inventories = fixture.expected_reference_inventories
            inventories["9E6Y"]["excluded_hetatm_heavy_atom_count"] = 999
            base = fixture.config(fixture.root / "bad_inventory_output")
            config = MOD.BuildConfig(
                **{**base.__dict__, "expected_reference_inventories": inventories}
            )
            with self.assertRaises(MOD.ContractError):
                MOD.build_package(config)
            self.assertFalse((config.outdir / "current").exists())

        regions = {
            region: {
                "occluding_atom_contact_count": 0,
                "occluding_residue_pair_count": 0,
                "vhh_residue_count": 0,
                "pvrl2_residue_count": 0,
                "min_distance_a": None,
            }
            for region in MOD.REGIONS
        }
        MOD.validate_nullable_region_min_distances({"regions": regions}, "valid")
        regions["CDR2"]["occluding_residue_pair_count"] = 1
        with self.assertRaises(MOD.ContractError):
            MOD.validate_nullable_region_min_distances({"regions": regions}, "invalid")

    def test_selector_p2_training_boundary_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            with fixture.selector_csv.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fields = list(reader.fieldnames or [])
                rows = list(reader)
            rows[0]["p2_training_ready"] = "true"
            rows[0]["selection_row_sha256"] = MOD.row_sha256(
                rows[0], "selection_row_sha256"
            )
            write_csv(fixture.selector_csv, fields, rows)

            audit = json.loads(fixture.selector_audit.read_text(encoding="utf-8"))
            audit["output_csv"]["sha256"] = MOD.sha256_file(fixture.selector_csv)
            audit["output_csv"]["selection_row_hash_chain"] = MOD.sha256_bytes(
                "\n".join(row["selection_row_sha256"] for row in rows).encode(
                    "ascii"
                )
            )
            MOD.write_json(fixture.selector_audit, audit)

            config = fixture.config(fixture.root / "p2_boundary_output")
            with self.assertRaisesRegex(MOD.ContractError, "p2_training_ready"):
                MOD.build_package(config)
            self.assertFalse((config.outdir / "current").exists())

    def test_legacy_manifest_accepts_only_explicit_external_row_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "legacy_run_manifest.csv"
            row = {"run_id": "LEGACY_001", "value": "frozen"}
            write_csv(manifest, list(row), [row])
            file_hash = MOD.sha256_file(manifest)
            row_hash = MOD.row_sha256(row, "run_manifest_row_sha256")

            with self.assertRaisesRegex(MOD.ContractError, "lacks run/hash fields"):
                MOD.load_bound_csv_row(
                    manifest,
                    file_hash,
                    row_hash,
                    "run_manifest_row_sha256",
                    row["run_id"],
                    {},
                )

            observed = MOD.load_bound_csv_row(
                manifest,
                file_hash,
                row_hash,
                "run_manifest_row_sha256",
                row["run_id"],
                {},
                allow_external_row_hash=True,
            )
            self.assertEqual(observed["run_manifest_row_sha256"], row_hash)

            with self.assertRaisesRegex(MOD.ContractError, "row binding mismatch"):
                MOD.load_bound_csv_row(
                    manifest,
                    file_hash,
                    "0" * 64,
                    "run_manifest_row_sha256",
                    row["run_id"],
                    {},
                    allow_external_row_hash=True,
                )

    def test_reuse_stage_ledger_allows_only_nonrequired_extra_counts(self) -> None:
        required = {
            "topoaa": 2,
            "rigidbody": 40,
            "seletop": 10,
            "flexref": 10,
            "emref": 10,
        }
        completion = {"stage_output_counts": {**required, "final": 10}}
        MOD.validate_reuse_stage_count_ledger(
            completion, MOD.canonical_json(required), "LEGACY_001"
        )

        changed = {"stage_output_counts": {**required, "emref": 9, "final": 10}}
        with self.assertRaisesRegex(MOD.ContractError, "stage-count ledger drift"):
            MOD.validate_reuse_stage_count_ledger(
                changed, MOD.canonical_json(required), "LEGACY_001"
            )

        incomplete = dict(required)
        incomplete.pop("flexref")
        with self.assertRaisesRegex(MOD.ContractError, "stage-count ledger drift"):
            MOD.validate_reuse_stage_count_ledger(
                completion, MOD.canonical_json(incomplete), "LEGACY_001"
            )

    def test_pending_builder_cannot_self_qualify_and_pointer_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            audit = MOD.build_package(fixture.config(fixture.root / "publication"))
            self.assertEqual(audit["status"], MOD.PROCESSOR_PENDING_STATUS)
            self.assertFalse(audit["primary_native_metric_eligible"])
            self.assertFalse(audit["development_release_state"]["validated"])

            publication = fixture.root / "pointer_test"
            old_release = publication / "releases/old"
            new_release = publication / "releases/new"
            for release in (old_release, new_release):
                release.mkdir(parents=True)
                (release / MOD.AUDIT_NAME).write_text("{}\n")
            current = publication / "current"
            MOD.promote_current_symlink(old_release, current)
            staging = fixture.root / "staging_new"
            shutil.copytree(new_release, staging)

            def fail_pointer(_release: Path, _current: Path) -> None:
                raise RuntimeError("injected pointer failure")

            with self.assertRaises(RuntimeError):
                MOD.promote_versioned_release(
                    staging,
                    publication / "releases/new2",
                    current,
                    pointer_promoter=fail_pointer,
                )
            self.assertEqual(current.resolve(), old_release.resolve())
            self.assertFalse((publication / "releases/new2").exists())


if __name__ == "__main__":
    unittest.main()
