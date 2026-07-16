#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("audit_pre_shortlist100_igfold_nbb2.py")
SPEC = importlib.util.spec_from_file_location("igfold_nbb2", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


SEQUENCE = "ACDEFGHIKLMN"
CDRS = {"cdr1": "CD", "cdr2": "FG", "cdr3": "IK"}


def pdb_text(points: np.ndarray) -> str:
    lines, serial = [], 1
    for index, (aa, point) in enumerate(zip(SEQUENCE, points), start=1):
        resname = next(key for key, value in MOD.AA3_TO_1.items() if value == aa)
        for atom, offset in (("N", (-0.2, 0.0, 0.0)), ("CA", (0.0, 0.0, 0.0))):
            xyz = point + np.array(offset)
            lines.append(
                f"ATOM  {serial:5d} {atom:<4s} {resname:>3s} A{index:4d}    "
                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 20.00           {atom[0]:>2s}"
            )
            serial += 1
    return "\n".join(lines) + "\nEND\n"


class IgFoldNbb2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.points = np.array([[float(i), float((i * i) % 5), float(i % 3)] for i in range(len(SEQUENCE))])
        self.row = {"candidate_id": "cand", "sequence": SEQUENCE, **CDRS}

    def manifest(self, path: Path, frozen_path: Path | None = None, **extra: str) -> dict[str, str]:
        return {
            "frozen_monomer_path": str(frozen_path or path),
            "source_chain": "A",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sequence_sha256": hashlib.sha256(SEQUENCE.encode()).hexdigest(),
            **extra,
        }

    def test_rigid_transform_is_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            igfold = root / "igfold.pdb"
            monomer = root / "inputs/candidate_monomers/cand.pdb"
            monomer.parent.mkdir(parents=True)
            igfold.write_text(pdb_text(self.points))
            rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
            monomer.write_text(pdb_text(self.points @ rotation + np.array([8.0, -3.0, 2.0])))
            result = MOD.crosscheck_candidate(
                self.row,
                self.manifest(monomer, Path("inputs/candidate_monomers/cand.pdb")),
                igfold,
                root,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["igfold_heavy_atom_count"], str(len(SEQUENCE) * 2))
            self.assertEqual(result["igfold_ca_coverage"], "1.000000")
            self.assertEqual(result["nbb2_ca_coverage"], "1.000000")
            self.assertAlmostEqual(float(result["framework_ca_rmsd"]), 0.0, places=5)
            self.assertAlmostEqual(float(result["cdr3_anchor_distance_delta"]), 0.0, places=5)
            self.assertEqual(result["nbb2_manifest_sha256_verified"], "true")
            self.assertEqual(result["nbb2_sequence_exact"], "true")

    def test_framework_deformation_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            igfold, monomer = root / "igfold.pdb", root / "inputs/candidate_monomers/cand.pdb"
            monomer.parent.mkdir(parents=True)
            igfold.write_text(pdb_text(self.points))
            deformed = self.points.copy()
            deformed[0] += np.array([0.0, 0.0, 3.0])
            monomer.write_text(pdb_text(deformed))
            result = MOD.crosscheck_candidate(
                self.row,
                self.manifest(monomer, Path("inputs/candidate_monomers/cand.pdb")),
                igfold,
                root,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertGreater(float(result["framework_ca_rmsd"]), 0.1)

    def test_existing_absolute_source_monomer_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            igfold = root / "igfold.pdb"
            source = root / "source_nbb2.pdb"
            igfold.write_text(pdb_text(self.points))
            source.write_text(pdb_text(self.points))
            result = MOD.crosscheck_candidate(
                self.row,
                self.manifest(
                    source,
                    Path("missing/frozen.pdb"),
                    source_remote_path=str(source),
                ),
                igfold,
                root,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(Path(result["nbb2_pdb"]), source)

    def test_monomer_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            igfold = root / "igfold.pdb"
            monomer = root / "monomer.pdb"
            igfold.write_text(pdb_text(self.points))
            monomer.write_text(pdb_text(self.points))
            manifest = self.manifest(monomer)
            manifest["sha256"] = "0" * 64
            result = MOD.crosscheck_candidate(self.row, manifest, igfold, root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["failure_reason"], "NBB2_MONOMER_SHA256_MISMATCH")

    def test_terminal_mode_fails_for_missing_igfold_pdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shortlist, manifest = root / "pre_shortlist100.tsv", root / "manifest.tsv"
            ids = [f"cand_{index:03d}" for index in range(100)]
            with shortlist.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_id", "sequence", *CDRS], delimiter="\t")
                writer.writeheader()
                writer.writerows({"candidate_id": candidate_id, "sequence": SEQUENCE, **CDRS} for candidate_id in ids)
            with manifest.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_id", "frozen_monomer_path", "source_chain"], delimiter="\t")
                writer.writeheader()
                writer.writerows({"candidate_id": candidate_id, "frozen_monomer_path": f"inputs/{candidate_id}.pdb", "source_chain": "A"} for candidate_id in ids)
            args = MOD.parse_args(["--pre-shortlist", str(shortlist), "--monomer-manifest", str(manifest), "--monomer-root", str(root), "--igfold-root", str(root / "no_models"), "--outdir", str(root / "reports"), "--terminal"])
            with self.assertRaisesRegex(RuntimeError, "terminal crosscheck failure: 100 of 100"):
                MOD.run(args)
            self.assertTrue((root / "reports/igfold_nbb2_crosscheck.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
