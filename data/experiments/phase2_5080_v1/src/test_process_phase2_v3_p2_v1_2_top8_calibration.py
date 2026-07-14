#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "process_phase2_v3_p2_v1_2_top8_calibration.py"
)
SPEC = importlib.util.spec_from_file_location("process_p2_v1_2_top8", MODULE_PATH)
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


def shift(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return point[0] + 12.0, point[1] - 8.0, point[2] + 4.0


def transform_9e6y(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return -point[1] + 5.0, point[0] - 2.0, point[2] + 7.0


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


class CalibrationFixture:
    def __init__(self, root: Path, poses_per_case: int = 2) -> None:
        self.root = root
        self.poses_per_case = poses_per_case
        self.positive_manifest = root / "inputs/positives.csv"
        self.mutant_manifest = root / "inputs/mutants.csv"
        self.selector_impl = root / "tools/selector.py"
        self.selector_csv = root / "inputs/selector.csv"
        self.hotspots = root / "inputs/hotspots.csv"
        self.reconciliation = root / "inputs/reconciliation.csv"
        self.reference_8x6b = root / "references/8X6B.pdb"
        self.reference_9e6y = root / "references/9E6Y.pdb"
        self.source_io = root / "poses/4_emref/io.json"
        self.source_poses: list[Path] = []
        self._write_case_manifests()
        self._write_hotspots_and_reconciliation()
        self._write_references()
        self._write_selector()

    def _write_case_manifests(self) -> None:
        positive_fields = [
            "recommended_order",
            "calibration_name",
            "family",
            "validation_role",
            "sequence_type",
            "cdr1_range",
            "cdr2_range",
            "cdr3_range",
            "usage_boundary",
        ]
        write_csv(
            self.positive_manifest,
            positive_fields,
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
                    "usage_boundary": "test_calibration_only",
                }
            ],
        )
        mutant_fields = [
            "panel_order",
            "mutant_name",
            "family",
            "intended_role",
            "control_type",
            "cdr1_range",
            "cdr2_range",
            "cdr3_range",
        ]
        write_csv(self.mutant_manifest, mutant_fields, [])

    def _write_hotspots_and_reconciliation(self) -> None:
        hotspot_rows = []
        reconciliation_rows = []
        for index in range(1, 24):
            hotspot_rows.append(
                {
                    "hotspot_id": f"H{index:02d}",
                    "hotspot_class": "core_hotspot",
                    "priority_weight": "1.0",
                    "pdb_8x6b_ref": f"B:{index}A",
                    "pdb_9e6y_ref": f"A:{100 + index}A",
                }
            )
            uniprot = 1000 + index
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
        lines_8x6b: list[str] = []
        lines_9e6y: list[str] = []
        serial = 1
        for index in range(1, 24):
            point = base_point(index)
            lines_8x6b.append(pdb_line(serial, "CA", "ALA", "B", index, point))
            lines_9e6y.append(
                pdb_line(
                    serial,
                    "CA",
                    "ALA",
                    "A",
                    100 + index,
                    transform_9e6y(point),
                )
            )
            serial += 1
        vhh_point = (
            base_point(1)[0],
            base_point(1)[1],
            base_point(1)[2] + 3.0,
        )
        lines_8x6b.extend(
            [
                pdb_line(serial, "CA", "GLY", "A", 200, vhh_point),
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
        lines_9e6y.extend(
            [
                pdb_line(
                    serial,
                    "CA",
                    "GLY",
                    "D",
                    200,
                    transform_9e6y(vhh_point),
                ),
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
                    element="C",
                ),
            ]
        )
        self.reference_8x6b.parent.mkdir(parents=True, exist_ok=True)
        self.reference_8x6b.write_text("\n".join(lines_8x6b + ["END"]) + "\n")
        self.reference_9e6y.write_text("\n".join(lines_9e6y + ["END"]) + "\n")

    def _raw_pose_bytes(self, pose_index: int) -> bytes:
        lines: list[str] = []
        serial = 1
        for index in range(1, 24):
            lines.append(
                pdb_line(serial, "CA", "ALA", "B", index, shift(base_point(index)))
            )
            serial += 1
        vhh_origin = base_point(1)
        for residue, z_offset in ((1, 2.8), (2, 3.2), (3, 3.6)):
            point = shift(
                (
                    vhh_origin[0] + 0.1 * pose_index,
                    vhh_origin[1],
                    vhh_origin[2] + z_offset,
                )
            )
            lines.append(pdb_line(serial, "CA", "GLY", "A", residue, point))
            serial += 1
        return ("\n".join(lines + ["END"]) + "\n").encode("ascii")

    def _write_selector(self) -> None:
        self.selector_impl.parent.mkdir(parents=True, exist_ok=True)
        self.selector_impl.write_text("# frozen synthetic selector\n", encoding="utf-8")
        self.source_io.parent.mkdir(parents=True, exist_ok=True)
        self.source_io.write_text('{"output": []}\n', encoding="utf-8")
        with self.positive_manifest.open(newline="", encoding="utf-8") as handle:
            positive_row = next(csv.DictReader(handle))
        manifest_hash = MOD.sha256_file(self.positive_manifest)
        manifest_row_hash = MOD.sha256_json(positive_row)
        selector_impl_hash = MOD.sha256_file(self.selector_impl)
        source_io_hash = MOD.sha256_file(self.source_io)
        rows: list[dict[str, str]] = []
        for index in range(1, self.poses_per_case + 1):
            coordinates = self._raw_pose_bytes(index)
            path = self.source_io.parent / f"emref_{index}.pdb.gz"
            path.write_bytes(gzip.compress(coordinates, mtime=0))
            self.source_poses.append(path)
            vhh_inventory = pose_inventory("A", 3, 3)
            pvrig_inventory = pose_inventory("B", 23, 23)
            source_payload = path.read_bytes()
            row: dict[str, object] = {
                "schema_version": "phase2_v3_p2_v1_2_emref_topk_selection_v1",
                "protocol_id": MOD.PROTOCOL_ID,
                "source_protocol": MOD.POSE_SOURCE_PROTOCOL,
                "source_stage": "4_emref",
                "run_id": "run_case_01",
                "case_id": "case_01",
                "candidate_id": "case_01",
                "family": "F1",
                "role": "positive_anchor",
                "canonical_rank": index,
                "source_output_index": index - 1,
                "source_output_file": f"emref_{index}.pdb",
                "source_score": f"{-10.0 - index:.17g}",
                "source_seed": 900 + index,
                "source_pose_relpath": path.relative_to(self.root).as_posix(),
                "source_pose_format": "pdb.gz",
                "source_pose_sha256": MOD.sha256_bytes(source_payload),
                "source_pose_bytes": len(source_payload),
                "compressed_source_sha256": MOD.sha256_bytes(source_payload),
                "compressed_source_bytes": len(source_payload),
                "decompressed_coordinate_sha256": MOD.sha256_bytes(coordinates),
                "decompressed_coordinate_bytes": len(coordinates),
                "vhh_chain_id": "A",
                "vhh_atom_count": 3,
                "vhh_residue_count": 3,
                "vhh_chain_inventory_json": MOD.canonical_json(vhh_inventory),
                "pvrig_chain_id": "B",
                "pvrig_atom_count": 23,
                "pvrig_residue_count": 23,
                "pvrig_chain_inventory_json": MOD.canonical_json(pvrig_inventory),
                "source_io_relpath": self.source_io.relative_to(self.root).as_posix(),
                "source_io_sha256": source_io_hash,
                "source_manifest_relpath": self.positive_manifest.relative_to(
                    self.root
                ).as_posix(),
                "source_manifest_sha256": manifest_hash,
                "source_manifest_row_sha256": manifest_row_hash,
                "selector_implementation_relpath": self.selector_impl.relative_to(
                    self.root
                ).as_posix(),
                "selector_implementation_sha256": selector_impl_hash,
                "reuse_role": "development_only",
                "formal_eligible": "false",
                "selection_row_sha256": "",
            }
            normalized = {key: str(value) for key, value in row.items()}
            normalized["selection_row_sha256"] = MOD.row_sha256(
                normalized, "selection_row_sha256"
            )
            rows.append(normalized)
        write_csv(self.selector_csv, list(rows[0]), rows)

    @property
    def expected_reference_inventories(self) -> dict[str, dict[str, object]]:
        return {
            "8x6b": {
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
            "9e6y": {
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
            selector_audit=None,
            positive_manifest=self.positive_manifest,
            mutant_manifest=self.mutant_manifest,
            aligner=MOD.DEFAULT_ALIGNER,
            pose_scorer=MOD.DEFAULT_POSE_SCORER,
            region_scorer=MOD.DEFAULT_REGION_SCORER,
            scoring_helper=MOD.DEFAULT_SCORING_HELPER,
            hotspots=self.hotspots,
            reconciliation=self.reconciliation,
            references={
                "8x6b": self.reference_8x6b,
                "9e6y": self.reference_9e6y,
            },
            expected_reference_inventories=self.expected_reference_inventories,
            outdir=outdir,
            workspace_root=self.root,
            contract=MOD.DatasetContract(
                positive_cases=1,
                mutant_cases=0,
                poses_per_case=self.poses_per_case,
            ),
            jobs=1,
            emit_contact_jsonl=True,
        )


class V12Top8CalibrationTests(unittest.TestCase):
    def test_default_cardinality_and_output_headers_are_exact(self) -> None:
        contract = MOD.DatasetContract()
        self.assertEqual(contract.case_count, 47)
        self.assertEqual(contract.materialization_rows, 376)
        self.assertEqual(contract.metric_rows, 752)
        self.assertEqual(len(MOD.MATERIALIZATION_FIELDS), len(set(MOD.MATERIALIZATION_FIELDS)))
        self.assertEqual(len(MOD.METRICS_FIELDS), len(set(MOD.METRICS_FIELDS)))
        self.assertEqual(MOD.METRICS_FIELDS.count("schema_version"), 1)

    def test_alignment_remap_cardinality_determinism_and_no_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = CalibrationFixture(Path(temporary))
            outdir = fixture.root / "output"
            audit_first = MOD.build_package(fixture.config(outdir))
            first_bytes = {
                path.relative_to(outdir).as_posix(): path.read_bytes()
                for path in outdir.rglob("*")
                if path.is_file()
            }
            audit_second = MOD.build_package(fixture.config(outdir))
            second_bytes = {
                path.relative_to(outdir).as_posix(): path.read_bytes()
                for path in outdir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(audit_first, audit_second)

            material = read_csv(outdir / MOD.MATERIALIZATION_MANIFEST_NAME)
            metrics = read_csv(outdir / MOD.CONTINUOUS_METRICS_NAME)
            contacts = (outdir / MOD.RESIDUE_CONTACTS_NAME).read_text().splitlines()
            self.assertEqual(len(material), 2)
            self.assertEqual(len(metrics), 4)
            self.assertEqual(len(contacts), 4)
            self.assertEqual({row["baseline"] for row in metrics}, {"8x6b", "9e6y"})
            self.assertEqual({row["alignment_pair_count"] for row in metrics}, {"23"})
            self.assertEqual({row["hotspot_count"] for row in metrics}, {"23"})
            self.assertEqual(
                {row["source_docking_receptor"] for row in metrics}, {"8x6b"}
            )
            self.assertEqual(
                {row["dual_receptor_r_gold_freeze_eligible"] for row in metrics},
                {"false"},
            )
            self.assertFalse(audit_first["formal_eligible"])
            self.assertFalse(audit_first["threshold_freeze_eligible"])
            self.assertFalse(audit_first["pose_rule_threshold_freeze_eligible"])
            self.assertFalse(audit_first["dual_receptor_r_gold_freeze_eligible"])
            serialized = json.dumps(audit_first, sort_keys=True)
            for forbidden in ("geometry_tier", "blocker_class", "classification"):
                self.assertNotIn(forbidden, serialized)
            for field_name in (*MOD.MATERIALIZATION_FIELDS, *MOD.METRICS_FIELDS):
                self.assertFalse(MOD.is_forbidden_output_field(field_name), field_name)

            aligned_9e6y = outdir / material[0]["aligned_pose_9e6y_relpath"]
            residue_numbers = {
                int(line[22:26])
                for line in aligned_9e6y.read_text().splitlines()
                if line.startswith(("ATOM  ", "HETATM")) and line[21] == "B"
            }
            self.assertEqual(residue_numbers, set(range(101, 124)))
            self.assertEqual(material[0]["remap_remapped_receptor_residues_9e6y"], "23")
            self.assertEqual(material[0]["remap_unmapped_receptor_residues_9e6y"], "0")

    def test_wrong_hotspot_count_inventory_and_source_hash_fail_closed(self) -> None:
        scenarios = ("hotspot_count", "inventory", "source_hash")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                fixture = CalibrationFixture(Path(temporary))
                config = fixture.config(fixture.root / "output")
                if scenario == "hotspot_count":
                    rows = read_csv(fixture.hotspots)[:-1]
                    write_csv(fixture.hotspots, list(rows[0]), rows)
                elif scenario == "inventory":
                    inventories = fixture.expected_reference_inventories
                    inventories["8x6b"]["protein_atom_heavy_atom_count"] = 999
                    config = MOD.BuildConfig(
                        **{
                            **config.__dict__,
                            "expected_reference_inventories": inventories,
                        }
                    )
                else:
                    fixture.source_poses[0].write_bytes(b"drift")
                with self.assertRaises(MOD.ContractError):
                    MOD.build_package(config)
                self.assertFalse(config.outdir.exists())


if __name__ == "__main__":
    unittest.main()
