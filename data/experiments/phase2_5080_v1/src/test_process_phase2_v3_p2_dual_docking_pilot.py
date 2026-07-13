#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("process_phase2_v3_p2_dual_docking_pilot.py")
SPEC = importlib.util.spec_from_file_location("p2_dual_postprocess", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, chain: str, residue: int, x: float = 0.0) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C  "
    )


class DualDockingPostprocessTests(unittest.TestCase):
    def test_alignment_pair_maps_use_pose_chain_b_and_23_unique_hotspots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for source in MOD.RECEPTORS:
                for target in MOD.RECEPTORS:
                    path = Path(tmp) / f"{source}_{target}.csv"
                    self.assertEqual(MOD.write_alignment_pair_map(source, target, path), 23)
                    rows = MOD.read_csv(path)
                    self.assertEqual(len(rows), 23)
                    self.assertEqual(len({row["mobile_ref"] for row in rows}), 23)
                    self.assertTrue(all(row["mobile_ref"].startswith("B:") for row in rows))
                    target_chain = str(MOD.RECEPTORS[target]["pvrig_chain"])
                    self.assertTrue(all(row["reference_ref"].startswith(f"{target_chain}:") for row in rows))

    def test_cross_conformer_number_map_contains_all_common_uniprot_residues(self) -> None:
        reconciliation = MOD.parse_reconciliation()
        common = set(reconciliation["8X6B"]) & set(reconciliation["9E6Y"])
        self.assertGreaterEqual(len(common), 100)
        self.assertEqual(len(MOD.residue_number_map("8x6b", "9e6y")), len(common))
        self.assertEqual(len(MOD.residue_number_map("9e6y", "8x6b")), len(common))

    def test_remap_changes_only_receptor_residue_ids(self) -> None:
        mapping = MOD.residue_number_map("8x6b", "9e6y")
        (source_number, source_icode), (target_number, target_icode) = next(iter(mapping.items()))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdb"
            destination = Path(tmp) / "destination.pdb"
            source.write_text(
                "\n".join(
                    [
                        atom_line(1, "A", 7, 1.0),
                        atom_line(2, "B", source_number, 2.0),
                        atom_line(3, "B", 999, 3.0),
                        "TER",
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            evidence = MOD.remap_pose_receptor_numbering(
                source, destination, "8x6b", "9e6y"
            )
            lines = destination.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0][21], "A")
            self.assertEqual(int(lines[0][22:26]), 7)
            self.assertEqual(lines[1][21], "B")
            self.assertEqual(int(lines[1][22:26]), target_number)
            self.assertEqual(lines[1][26].strip(), target_icode)
            self.assertLess(int(lines[2][22:26]), 0)
            self.assertEqual(evidence["observed_receptor_residues"], 2)
            self.assertEqual(evidence["remapped_receptor_residues"], 1)
            self.assertEqual(evidence["unmapped_receptor_residues"], 1)


if __name__ == "__main__":
    unittest.main()
