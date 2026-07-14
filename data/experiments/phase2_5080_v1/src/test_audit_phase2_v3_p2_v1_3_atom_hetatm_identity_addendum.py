from __future__ import annotations

import unittest
from pathlib import Path

from experiments.phase2_5080_v1.src import (
    audit_phase2_v3_p2_v1_3_atom_hetatm_identity_addendum as mod,
)


def atom_payload(atoms: set[tuple[str, str, str, str, str, str]]) -> dict[str, object]:
    residues = {atom[:3] for atom in atoms}
    terminal = sorted(residues)[-1]
    terminal_oxt = {atom for atom in atoms if atom[:3] == terminal and atom[3] == "OXT"}
    return {
        "atom_set": atoms,
        "residue_set": residues,
        "terminal_residue": terminal,
        "terminal_oxt_set": terminal_oxt,
        "non_terminal_oxt_set": {
            atom for atom in atoms if atom[3] == "OXT" and atom[:3] != terminal
        },
        "atom_count": len(atoms),
        "residue_count": len(residues),
        "atom_identity_sha256": mod.sha256_bytes(
            mod.canonical_json(sorted(atoms)).encode()
        ),
        "residue_identity_sha256": mod.sha256_bytes(
            mod.canonical_json(sorted(residues)).encode()
        ),
    }


def pdb_line(
    record: str,
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    residue: int,
    element: str,
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:^4} {resname:>3} {chain}{residue:4d}    "
        f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00          {element:>2}  "
    )


def pdb_bytes(*lines: str) -> bytes:
    return ("\n".join((*lines, "END")) + "\n").encode("ascii")


class AtomIdentityDifferenceTests(unittest.TestCase):
    def test_terminal_oxt_presence_is_the_only_normalized_atom_difference(self) -> None:
        ca = ("127", "", "SER", "CA", "", "C")
        oxt = ("127", "", "SER", "OXT", "", "O")
        comparison = mod.compare_identity(atom_payload({ca, oxt}), atom_payload({ca}))
        self.assertTrue(comparison["residue_identity_exact"])
        self.assertFalse(comparison["atom_identity_exact"])
        self.assertTrue(comparison["terminal_oxt_normalized_atom_identity_exact"])
        self.assertTrue(comparison["all_atom_differences_are_terminal_oxt"])
        self.assertEqual(comparison["non_oxt_missing_atoms"], [])

    def test_any_other_atom_or_residue_difference_fails_closed(self) -> None:
        ca = ("127", "", "SER", "CA", "", "C")
        cb = ("127", "", "SER", "CB", "", "C")
        non_oxt = mod.compare_identity(atom_payload({ca, cb}), atom_payload({ca}))
        self.assertFalse(non_oxt["terminal_oxt_normalized_atom_identity_exact"])
        self.assertFalse(non_oxt["all_atom_differences_are_terminal_oxt"])
        self.assertEqual(len(non_oxt["non_oxt_missing_atoms"]), 1)

        other_residue = ("126", "", "GLY", "CA", "", "C")
        residue = mod.compare_identity(
            atom_payload({ca, other_residue}), atom_payload({ca})
        )
        self.assertFalse(residue["residue_identity_exact"])
        self.assertFalse(residue["all_atom_differences_are_terminal_oxt"])


class HeavyHetatmIdentityTests(unittest.TestCase):
    def payload(self, coordinates: bytes, chain: str) -> dict[str, object]:
        return mod.hetatm_heavy_identity_payload(
            coordinates, chain, Path(f"chain_{chain}.pdb")
        )

    def test_zero_hetatm_evidence_is_raw_exact(self) -> None:
        protein_only = pdb_bytes(pdb_line("ATOM", 1, "CA", "ALA", "A", 1, "C"))
        reference = self.payload(protein_only, "A")
        pose = self.payload(protein_only, "A")
        comparison = mod.compare_hetatm_identity(reference, pose)
        self.assertEqual(comparison["reference_count"], 0)
        self.assertEqual(comparison["pose_count"], 0)
        self.assertTrue(comparison["raw_identity_exact"])
        self.assertEqual(comparison["missing_identities"], [])
        self.assertEqual(comparison["extra_identities"], [])

    def test_chain_a_heavy_hetatm_injection_is_detected(self) -> None:
        reference_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "ALA", "A", 1, "C")
        )
        pose_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "ALA", "A", 1, "C"),
            pdb_line("HETATM", 2, "ZN", "ZN", "A", 201, "ZN"),
        )
        comparison = mod.compare_hetatm_identity(
            self.payload(reference_bytes, "A"), self.payload(pose_bytes, "A")
        )
        self.assertFalse(comparison["raw_identity_exact"])
        self.assertEqual(comparison["reference_count"], 0)
        self.assertEqual(comparison["pose_count"], 1)
        self.assertEqual(comparison["extra_identities"][0]["resname"], "ZN")

    def test_chain_b_heavy_hetatm_injection_is_detected(self) -> None:
        reference_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "ALA", "B", 1, "C")
        )
        pose_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "ALA", "B", 1, "C"),
            pdb_line("HETATM", 2, "C1", "EDO", "B", 301, "C"),
        )
        comparison = mod.compare_hetatm_identity(
            self.payload(reference_bytes, "B"), self.payload(pose_bytes, "B")
        )
        self.assertFalse(comparison["raw_identity_exact"])
        self.assertEqual(comparison["pose_count"], 1)
        self.assertEqual(comparison["extra_identities"][0]["resname"], "EDO")

    def test_nonzero_but_raw_exact_hetatm_is_explicit(self) -> None:
        coordinates = pdb_bytes(
            pdb_line("HETATM", 1, "ZN", "ZN", "A", 201, "ZN")
        )
        comparison = mod.compare_hetatm_identity(
            self.payload(coordinates, "A"), self.payload(coordinates, "A")
        )
        self.assertTrue(comparison["raw_identity_exact"])
        self.assertEqual(comparison["reference_count"], 1)
        self.assertEqual(comparison["pose_count"], 1)

    def test_missing_and_extra_hetatm_identities_are_recorded(self) -> None:
        reference_bytes = pdb_bytes(
            pdb_line("HETATM", 1, "ZN", "ZN", "A", 201, "ZN")
        )
        pose_bytes = pdb_bytes(
            pdb_line("HETATM", 1, "MG", "MG", "A", 202, "MG")
        )
        comparison = mod.compare_hetatm_identity(
            self.payload(reference_bytes, "A"), self.payload(pose_bytes, "A")
        )
        self.assertFalse(comparison["raw_identity_exact"])
        self.assertEqual(comparison["missing_identities"][0]["resname"], "ZN")
        self.assertEqual(comparison["extra_identities"][0]["resname"], "MG")

    def test_oxt_named_hetatm_is_not_atom_normalized(self) -> None:
        reference_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "SER", "A", 127, "C")
        )
        pose_bytes = pdb_bytes(
            pdb_line("ATOM", 1, "CA", "SER", "A", 127, "C"),
            pdb_line("HETATM", 2, "OXT", "SER", "A", 127, "O"),
        )
        comparison = mod.compare_hetatm_identity(
            self.payload(reference_bytes, "A"), self.payload(pose_bytes, "A")
        )
        self.assertFalse(comparison["raw_identity_exact"])
        self.assertEqual(comparison["extra_identities"][0]["atom_name"], "OXT")

    def test_nonzero_raw_exact_does_not_satisfy_zero_evidence_gate(self) -> None:
        common = {
            "has_poses": True,
            "exact_reuse_complete": True,
            "boundary_complete": True,
            "total_complete": True,
            "all_residues_exact": True,
            "all_non_oxt_exact": True,
            "all_heavy_hetatm_raw_exact": True,
        }
        self.assertFalse(
            mod.identity_evidence_passes(**common, all_heavy_hetatm_zero=False)
        )
        self.assertTrue(
            mod.identity_evidence_passes(**common, all_heavy_hetatm_zero=True)
        )


if __name__ == "__main__":
    unittest.main()
