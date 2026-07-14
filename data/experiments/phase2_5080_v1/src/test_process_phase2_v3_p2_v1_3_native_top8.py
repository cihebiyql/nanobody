#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
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
        self.selector_csv = root / "inputs/selector.csv"
        self.selector_audit = root / "inputs/selector_audit.json"
        self.release_manifest = root / "inputs/absent_release.json"
        self.execution_release_manifest = root / "inputs/execution_release.json"
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
        MOD.write_json(
            self.execution_release_manifest,
            {"status": "FROZEN_SYNTHETIC_EXECUTION_RELEASE"},
        )
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
        rows: list[dict[str, str]] = []
        fixed_hashes = {
            name: MOD.sha256_bytes(name.encode("ascii"))
            for name in (
                "sequence",
                "monomer",
                "monomer_atom",
                "monomer_residue",
                "pose_vhh_atom",
                "pose_vhh_residue",
            )
        }
        for receptor in MOD.RECEPTORS:
            run_id = f"V13CAL_001__{receptor}__main"
            for native_rank in range(1, self.poses_per_run + 1):
                coordinates = self._pose_bytes(receptor, native_rank)
                coordinate_path = self.root / "materialized" / run_id / f"rank_{native_rank:02d}.pdb"
                coordinate_path.parent.mkdir(parents=True, exist_ok=True)
                coordinate_path.write_bytes(coordinates)
                source_path = self.root / "sources" / run_id / f"rank_{native_rank:02d}.pdb.gz"
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(gzip.compress(coordinates, mtime=0))
                self.coordinate_paths.append(coordinate_path)
                self.source_poses.append(source_path)
                source_payload = source_path.read_bytes()
                row: dict[str, object] = {
                    field: "" for field in MOD.SELECTOR_REQUIRED_FIELDS
                }
                row.update(
                    {
                        "schema_version": MOD.SELECTOR_SCHEMA,
                        "protocol_id": MOD.SELECTOR_PROTOCOL_ID,
                        "source_protocol": MOD.POSE_SOURCE_PROTOCOL,
                        "source_stage": "4_emref",
                        "source_mode": "SYNTHETIC",
                        "run_id": run_id,
                        "source_run_id": f"source_{run_id}",
                        "case_id": "case_01",
                        "candidate_id": "case_01",
                        "family": "F1",
                        "anchor_class": "known_positive",
                        "sequence_sha256": fixed_hashes["sequence"],
                        "teacher_manifest_relpath": self.positive_manifest.relative_to(
                            self.root
                        ).as_posix(),
                        "teacher_manifest_sha256": MOD.sha256_file(
                            self.positive_manifest
                        ),
                        "teacher_manifest_row_sha256": MOD.sha256_bytes(
                            b"synthetic_teacher_row"
                        ),
                        "generation_receptor": receptor,
                        "receptor_id": receptor,
                        "cdr1_range": "1-1",
                        "cdr2_range": "2-2",
                        "cdr3_range": "3-3",
                        "native_rank": native_rank,
                        "canonical_rank": native_rank,
                        "source_output_index": native_rank - 1,
                        "source_output_file": source_path.name,
                        "source_score": -10.0 - native_rank,
                        "source_seed": 900 + native_rank,
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
                        "monomer_atom_identity_sha256": fixed_hashes["monomer_atom"],
                        "monomer_residue_identity_sha256": fixed_hashes[
                            "monomer_residue"
                        ],
                        "pose_vhh_atom_identity_sha256": fixed_hashes["pose_vhh_atom"],
                        "pose_vhh_residue_identity_sha256": fixed_hashes[
                            "pose_vhh_residue"
                        ],
                        "receptor_atom_identity_sha256": MOD.sha256_bytes(
                            f"{receptor}_atom".encode("ascii")
                        ),
                        "receptor_residue_identity_sha256": MOD.sha256_bytes(
                            f"{receptor}_residue".encode("ascii")
                        ),
                        "pose_pvrig_atom_identity_sha256": MOD.sha256_bytes(
                            f"{receptor}_atom".encode("ascii")
                        ),
                        "pose_pvrig_residue_identity_sha256": MOD.sha256_bytes(
                            f"{receptor}_residue".encode("ascii")
                        ),
                        "completion_status": "FAIL_DOCKING_OUTPUT_INCOMPLETE",
                        "completion_exit_code": 0,
                        "config_sha256": MOD.sha256_bytes(f"{run_id}_config".encode()),
                        "monomer_sha256": fixed_hashes["monomer"],
                        "receptor_sha256": MOD.sha256_bytes(receptor.encode()),
                        "restraint_sha256": MOD.sha256_bytes(f"{receptor}_tbl".encode()),
                        "hotspot_sha256": MOD.sha256_file(self.hotspots),
                        "source_params_sha256": MOD.sha256_bytes(b"params"),
                        "source_io_sha256": MOD.sha256_bytes(f"{run_id}_io".encode()),
                        "run_manifest_sha256": MOD.sha256_bytes(b"run_manifest"),
                        "run_manifest_row_sha256": MOD.sha256_bytes(run_id.encode()),
                        "execution_release_manifest_relpath": (
                            self.execution_release_manifest.relative_to(self.root).as_posix()
                        ),
                        "execution_release_manifest_sha256": MOD.sha256_file(
                            self.execution_release_manifest
                        ),
                        "publication_release_id": "V13_SYNTHETIC_RELEASE_001",
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
                "publication": {"release_id": "V13_SYNTHETIC_RELEASE_001"},
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
            release_manifest=self.release_manifest,
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
            first_files = {
                path.relative_to(outdir).as_posix(): path.read_bytes()
                for path in outdir.rglob("*")
                if path.is_file()
            }
            second_audit = MOD.build_package(fixture.config(outdir))
            second_files = {
                path.relative_to(outdir).as_posix(): path.read_bytes()
                for path in outdir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_audit, second_audit)
            self.assertEqual(first_files, second_files)

            material = read_csv(outdir / MOD.MATERIALIZATION_MANIFEST_NAME)
            metrics = read_csv(outdir / MOD.CONTINUOUS_METRICS_NAME)
            contacts = [
                json.loads(line)
                for line in (outdir / MOD.RESIDUE_CONTACTS_NAME).read_text().splitlines()
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
                outdir / first_audit["output_sha256"]["alignment_maps"]["9E6Y"]["relpath"]
            )
            self.assertEqual(native_map_9[0], {"mobile_ref": "B:101A", "reference_ref": "A:101A"})
            self.assertEqual(native_map_9[-1], {"mobile_ref": "B:123A", "reference_ref": "A:123A"})
            aligned_9 = outdir / next(
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
            self.assertTrue(first_audit["primary_native_metric_eligible"])
            self.assertFalse(first_audit["formal_eligible"])
            self.assertFalse(first_audit["training_label_release_eligible"])
            self.assertFalse(first_audit["docking_gold_release_eligible"])
            self.assertFalse(
                first_audit["development_release_manifest_check"]["validated"]
            )
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

            stale = outdir / "aligned_poses/stale/rank_99.pdb"
            stale.parent.mkdir(parents=True)
            stale.write_text("STALE\n")
            MOD.build_package(fixture.config(outdir))
            self.assertFalse(stale.exists())

    def test_fail_closed_source_hash_atom_inventory_and_conditional_null(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = NativeFixture(Path(temporary))
            config = fixture.config(fixture.root / "bad_hash_output")
            fixture.source_poses[0].write_bytes(b"drift")
            with self.assertRaises(MOD.ContractError):
                MOD.build_package(config)
            self.assertFalse(config.outdir.exists())

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
            self.assertFalse(config.outdir.exists())

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

    def test_release_component_hash_binding_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.json"
            component = {
                "schema_version": "pvrig_v1_3_native_processor_release_component_v1",
                "protocol_id": MOD.PROTOCOL_ID,
                "artifacts": {"processor": {"path": "x", "sha256": "1" * 64}},
            }
            MOD.write_json(path, {"native_processor_release": component})
            self.assertTrue(MOD.validate_release_manifest(path, component)["validated"])
            drifted = json.loads(json.dumps(component))
            drifted["artifacts"]["processor"]["sha256"] = "0" * 64
            self.assertFalse(MOD.validate_release_manifest(path, drifted)["validated"])


if __name__ == "__main__":
    unittest.main()
