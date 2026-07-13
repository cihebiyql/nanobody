#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = DATA_ROOT.parent / "docking/scripts"
POSE_SCORER_PATH = SCRIPTS_DIR / "score_pvrig_vhh_pose_v1_2.py"
REGION_SCORER_PATH = SCRIPTS_DIR / "score_cdr_region_occlusion_v1_2.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


POSE = load_module("score_pvrig_vhh_pose_v1_2", POSE_SCORER_PATH)
REGION = load_module("score_cdr_region_occlusion_v1_2", REGION_SCORER_PATH)


def pdb_line(
    record: str,
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    residue: int,
    x: float,
    *,
    altloc: str = "",
    element: str = "C",
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:^4}{altloc:1}{resname:>3} {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00          {element:>2}  "
    )


def write_fixture(root: Path, *, protein_near: bool = True) -> tuple[Path, Path, Path]:
    pose = root / "pose.pdb"
    reference = root / "reference.pdb"
    hotspots = root / "hotspots.csv"
    pose.write_text(
        "\n".join(
            [
                # Legal modified residues may use HETATM in a protein pose and must survive.
                pdb_line("HETATM", 1, "CA", "MSE", "B", 10, 0.0),
                pdb_line("HETATM", 2, "CA", "MSE", "A", 100, 4.5),
                pdb_line("ATOM", 3, "H", "ALA", "A", 100, 4.5, element="H"),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    protein_x = 9.0 if protein_near else 30.0
    reference.write_text(
        "\n".join(
            [
                # Both altloc atoms are retained; their residue pair is still unique.
                pdb_line("ATOM", 1, "CA", "ALA", "D", 1, protein_x, altloc="A"),
                pdb_line("ATOM", 2, "CB", "ALA", "D", 1, protein_x, altloc="B"),
                pdb_line("ATOM", 3, "CA", "SER", "D", 2, 30.0),
                pdb_line("HETATM", 4, "O", "HOH", "D", 201, 4.5, element="O"),
                pdb_line("HETATM", 5, "C1", "EDO", "D", 202, 4.5),
                pdb_line("HETATM", 6, "C2", "EDO", "D", 202, 5.0),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hotspots.write_text(
        "hotspot_id,pdb_test_ref,priority_weight\nH1,C:10S,1\n",
        encoding="utf-8",
    )
    return pose, reference, hotspots


class PoseScorerV12Tests(unittest.TestCase):
    def run_json(self, root: Path, name: str = "score.json", *, protein_near: bool = True):
        pose, reference, hotspots = write_fixture(root, protein_near=protein_near)
        output = root / name
        code = POSE.main(
            [
                "--pose-pdb",
                str(pose),
                "--reference-pdb",
                str(reference),
                "--pvrig-chain",
                "B",
                "--vhh-chain",
                "A",
                "--ref-pvrig-chain",
                "C",
                "--ref-pvrl2-chain",
                "D",
                "--hotspots-csv",
                str(hotspots),
                "--hotspot-ref-column",
                "pdb_test_ref",
                "--cdr-ranges",
                "CDR3:100-100",
                "--assume-aligned",
                "--out-json",
                str(output),
            ]
        )
        self.assertEqual(code, 0)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def test_reference_hetatm_is_excluded_but_pose_hetatm_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _output, report = self.run_json(Path(tmp))
        self.assertEqual(report["scoring_semantics_version"], "PVRIG_PVRL2_ATOM_ONLY_V1_2")
        self.assertEqual(report["pvrig_vhh_contact_pair_count"], 1)
        self.assertEqual(report["hotspot_overlap_count"], 1)
        self.assertEqual(report["pvrl2_vhh_occluding_contact_count"], 1)
        self.assertEqual(report["pvrl2_occluded_residue_count"], 1)

        pose_inventory = report["record_inventory"]["pose"]
        self.assertEqual(pose_inventory["pvrig_chain"]["selected_heavy_atom_count"], 1)
        self.assertEqual(pose_inventory["pvrig_chain"]["hetatm_heavy_atom_count"], 1)
        self.assertEqual(pose_inventory["vhh_chain"]["selected_heavy_atom_count"], 1)
        self.assertEqual(pose_inventory["vhh_chain"]["hetatm_heavy_atom_count"], 1)

        ref_inventory = report["record_inventory"]["reference_pvrl2_chain"]
        self.assertEqual(ref_inventory["protein_atom_heavy_atom_count"], 3)
        self.assertEqual(ref_inventory["selected_protein_heavy_atom_count"], 3)
        self.assertEqual(ref_inventory["excluded_hetatm_heavy_atom_count"], 3)
        self.assertEqual(ref_inventory["excluded_hetatm_residue_count"], 2)
        self.assertEqual(ref_inventory["excluded_hoh_heavy_atom_count"], 1)
        self.assertEqual(ref_inventory["excluded_hoh_residue_count"], 1)
        self.assertEqual(ref_inventory["excluded_edo_heavy_atom_count"], 2)
        self.assertEqual(ref_inventory["excluded_edo_residue_count"], 1)
        self.assertEqual(ref_inventory["atom_altloc_heavy_atom_count"], 2)
        self.assertEqual(ref_inventory["atom_altloc_labels"], ["A", "B"])
        self.assertIn("not a calibrated Docking Gold label", report["claim_boundary"])

    def test_json_and_csv_outputs_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, _report = self.run_json(root, "first.json")
            second, _report = self.run_json(root, "second.json")
            self.assertEqual(first.read_bytes(), second.read_bytes())

            pose, reference, hotspots = write_fixture(root)
            outputs = [root / "first.csv", root / "second.csv"]
            for output in outputs:
                self.assertEqual(
                    POSE.main(
                        [
                            "--pose-pdb", str(pose),
                            "--reference-pdb", str(reference),
                            "--pvrig-chain", "B",
                            "--vhh-chain", "A",
                            "--ref-pvrig-chain", "C",
                            "--ref-pvrl2-chain", "D",
                            "--hotspots-csv", str(hotspots),
                            "--hotspot-ref-column", "pdb_test_ref",
                            "--assume-aligned",
                            "--out-csv", str(output),
                        ]
                    ),
                    0,
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with outputs[0].open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["scoring_semantics_version"], "PVRIG_PVRL2_ATOM_ONLY_V1_2")
            self.assertEqual(row["ref_pvrl2_excluded_hetatm_heavy_atom_count"], "3")


class RegionScorerV12Tests(unittest.TestCase):
    def run_json(self, root: Path, name: str = "region.json", *, protein_near: bool = True):
        pose, reference, _hotspots = write_fixture(root, protein_near=protein_near)
        output = root / name
        code = REGION.main(
            [
                "--pose-pdb", str(pose),
                "--reference-pdb", str(reference),
                "--vhh-chain", "A",
                "--ref-pvrl2-chain", "D",
                "--cdr1", "26-35",
                "--cdr2", "53-59",
                "--cdr3", "100-100",
                "--out-json", str(output),
            ]
        )
        self.assertEqual(code, 0)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def test_only_protein_atom_contacts_are_counted_at_4_5_angstrom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _output, report = self.run_json(Path(tmp))
        self.assertEqual(report["total_occluding_atom_contact_count"], 2)
        self.assertEqual(report["total_occluding_residue_pair_count"], 1)
        self.assertEqual(report["regions"]["CDR3"]["occluding_atom_contact_count"], 2)
        self.assertEqual(report["regions"]["CDR3"]["occluding_residue_pair_count"], 1)
        self.assertEqual(
            report["regions"]["CDR3"]["occluding_residue_pair_fraction_of_total"],
            1.0,
        )
        inventory = report["record_inventory"]["reference_pvrl2_chain"]
        self.assertEqual(inventory["excluded_hetatm_heavy_atom_count"], 3)
        self.assertEqual(inventory["atom_altloc_heavy_atom_count"], 2)

    def test_zero_protein_contact_denominator_is_explicit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _output, report = self.run_json(Path(tmp), protein_near=False)
        self.assertEqual(report["total_occluding_atom_contact_count"], 0)
        self.assertEqual(report["total_occluding_residue_pair_count"], 0)
        for region in report["regions"].values():
            self.assertEqual(region["occlusion_fraction_of_total"], 0.0)
            self.assertEqual(region["occluding_residue_pair_fraction_of_total"], 0.0)
        self.assertEqual(
            report["zero_denominator_semantics"],
            "occlusion and residue-pair fractions are 0.0 when their protein-only denominator is zero",
        )

    def test_region_json_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, _report = self.run_json(root, "first.json")
            second, _report = self.run_json(root, "second.json")
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
