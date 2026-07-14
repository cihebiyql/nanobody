from __future__ import annotations

import unittest

from experiments.phase2_5080_v1.src import (
    audit_phase2_v3_p2_v1_3_atom_identity_differences as mod,
)


def payload(atoms: set[tuple[str, str, str, str, str, str]]) -> dict[str, object]:
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
        "atom_identity_sha256": mod.sha256_bytes(mod.canonical_json(sorted(atoms)).encode()),
        "residue_identity_sha256": mod.sha256_bytes(mod.canonical_json(sorted(residues)).encode()),
    }


class AtomIdentityDifferenceAuditTests(unittest.TestCase):
    def test_terminal_oxt_presence_is_the_only_normalized_difference(self) -> None:
        ca = ("127", "", "SER", "CA", "", "C")
        oxt = ("127", "", "SER", "OXT", "", "O")
        comparison = mod.compare_identity(payload({ca, oxt}), payload({ca}))
        self.assertTrue(comparison["residue_identity_exact"])
        self.assertFalse(comparison["atom_identity_exact"])
        self.assertTrue(comparison["terminal_oxt_normalized_atom_identity_exact"])
        self.assertTrue(comparison["all_atom_differences_are_terminal_oxt"])
        self.assertEqual(comparison["non_oxt_missing_atoms"], [])

    def test_any_other_atom_or_residue_difference_fails_closed(self) -> None:
        ca = ("127", "", "SER", "CA", "", "C")
        cb = ("127", "", "SER", "CB", "", "C")
        non_oxt = mod.compare_identity(payload({ca, cb}), payload({ca}))
        self.assertFalse(non_oxt["terminal_oxt_normalized_atom_identity_exact"])
        self.assertFalse(non_oxt["all_atom_differences_are_terminal_oxt"])
        self.assertEqual(len(non_oxt["non_oxt_missing_atoms"]), 1)

        other_residue = ("126", "", "GLY", "CA", "", "C")
        residue = mod.compare_identity(payload({ca, other_residue}), payload({ca}))
        self.assertFalse(residue["residue_identity_exact"])
        self.assertFalse(residue["all_atom_differences_are_terminal_oxt"])


if __name__ == "__main__":
    unittest.main()
