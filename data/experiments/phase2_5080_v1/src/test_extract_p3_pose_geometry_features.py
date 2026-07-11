#!/usr/bin/env python3
"""Synthetic-PDB tests for Phase 3 optional pose geometry extraction."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_p3_pose_geometry_features import extract_features


def atom_line(serial: int, atom: str, resname: str, chain: str, resseq: int, x: float, y: float, z: float, element: str = "C") -> str:
    return f"ATOM  {serial:5d} {atom:<4s} {resname:>3s} {chain:1s}{resseq:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {element:>2s}\n"


class P3PoseGeometryTests(unittest.TestCase):
    def test_missing_pose_row_remains_explicit_without_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.csv"
            mapping = root / "mapping.csv"
            out = root / "features.csv"
            manifest.write_text(
                "candidate_id,pose_id,target_baseline,pose_path,vhh_chain,target_chain,pose_status,qc_status,cdr3_seq,calibration_role,leakage_role\n"
                "cand0,pose0,baseline,,A,T,no_pose_supplied,not_applicable_no_pose,CDR,candidate,none\n",
                encoding="utf-8",
            )
            mapping.write_text("full_position_1based,model_position_1based,target_weight\n71,33,2.0\n", encoding="utf-8")
            summary = extract_features(manifest, mapping, out)
            self.assertEqual(summary["ok_rows"], 0)
            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["geometry_status"], "no_pose")
            self.assertEqual(row["heavy_atom_interface_contacts_le_4p5A"], "")
            self.assertIn("not fabricated", row["geometry_notes"])

    def test_synthetic_pdb_contacts_hotspots_clashes_and_cdr3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdb = root / "pose.pdb"
            manifest = root / "manifest.csv"
            mapping = root / "mapping.csv"
            out = root / "features.csv"
            pdb.write_text(
                atom_line(1, "CA", "CYS", "A", 1, 0.0, 0.0, 0.0)
                + atom_line(2, "CA", "ASP", "A", 2, 10.0, 0.0, 0.0)
                + atom_line(3, "CA", "ARG", "A", 3, 20.0, 0.0, 0.0)
                + atom_line(4, "CA", "GLY", "T", 71, 3.0, 0.0, 0.0)
                + atom_line(5, "CA", "SER", "T", 72, 10.5, 0.0, 0.0)
                + atom_line(6, "CA", "TYR", "T", 73, 20.0, 0.0, 2.5)
                + "END\n",
                encoding="utf-8",
            )
            manifest.write_text(
                "candidate_id,pose_id,target_baseline,pose_path,vhh_chain,target_chain,target_residue_numbering,pose_status,qc_status,vhh_seq,cdr3_seq,calibration_role,leakage_role\n"
                f"cand1,pose1,baseline,{pdb},A,T,full_uniprot_1based,pose_supplied,pass,CDR,CDR,candidate,none\n",
                encoding="utf-8",
            )
            mapping.write_text(
                "full_position_1based,model_position_1based,target_weight\n"
                "71,33,2.0\n72,34,0.0\n73,35,1.5\n",
                encoding="utf-8",
            )

            summary = extract_features(manifest, mapping, out)
            self.assertEqual(summary["ok_rows"], 1)
            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["geometry_status"], "ok")
            self.assertEqual(row["heavy_atom_interface_contacts_le_4p5A"], "3")
            self.assertEqual(row["heavy_atom_clashes_lt_2p0A"], "1")
            self.assertEqual(row["minimum_heavy_atom_distance_A"], "0.500")
            self.assertEqual(row["hotspot_contact_count"], "2")
            self.assertEqual(row["hotspot_weighted_contacts"], "3.500")
            self.assertEqual(row["cdr3_contacts"], "3")
            self.assertEqual(json.loads(row["target_interface_full_positions_json"]), [71, 72, 73])
            self.assertEqual(json.loads(row["hotspot_positions_json"]), [71, 73])
            self.assertIn("A:CYS1", json.loads(row["vhh_interface_residues_json"]))
            self.assertIn("T:TYR73", json.loads(row["target_interface_residues_json"]))


if __name__ == "__main__":
    unittest.main()
