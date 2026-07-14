import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_cmd(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True)


def atom_line(serial, name, resname, chain, resseq, x, y, z):
    return (
        f"ATOM  {serial:5d} {name:<4} {resname:>3} {chain}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           {name[0]:>2}\n"
    )


class ReferenceAndScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_cmd(PYTHON, "scripts/prepare_references.py")
        cls.summary = json.loads((ROOT / "reports/reference_normalization_summary.json").read_text())

    def test_reference_outputs_are_standard_atom_only_and_renumbered(self):
        summary = self.summary
        self.assertEqual(summary["hotspots"]["unique_interface_residue_count"], 23)
        self.assertEqual(summary["hotspots"]["air_anchor_count"], 12)
        self.assertEqual(summary["hotspots"]["holdout_count"], 11)
        self.assertEqual(summary["hotspots"]["air_anchor_uniprot_positions"][:4], [71, 74, 82, 87])
        self.assertEqual(summary["hotspots"]["holdout_uniprot_positions"][:4], [72, 81, 83, 90])

        for reference_id in ("8x6b", "9e6y"):
            tl_path = ROOT / summary["references"][reference_id]["outputs"]["tl_reference"]["path"]
            receptor_path = ROOT / summary["references"][reference_id]["outputs"]["receptor_only"]["path"]
            tl_lines = tl_path.read_text().splitlines()
            receptor_lines = receptor_path.read_text().splitlines()
            self.assertTrue(all(not line.startswith("HETATM") for line in tl_lines))
            self.assertTrue(all(line.startswith(("ATOM  ", "TER", "END")) for line in tl_lines))
            self.assertEqual({line[21] for line in receptor_lines if line.startswith("ATOM  ")}, {"T"})
            self.assertEqual({line[21] for line in tl_lines if line.startswith("ATOM  ")}, {"L", "T"})
            t_resseqs = [int(line[22:26]) for line in tl_lines if line.startswith("ATOM  ") and line[21] == "T"]
            self.assertIn(71, t_resseqs)

    def test_score_pose_reads_gzip_scores_contacts_and_haddock_io(self):
        reference_text = (ROOT / "inputs/normalized/8x6b_TL_reference.pdb").read_text()
        t71_ca = None
        l_atom = None
        for line in reference_text.splitlines():
            if line.startswith("ATOM  ") and line[21] == "T" and int(line[22:26]) == 71 and line[12:16].strip() == "CA":
                t71_ca = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            if line.startswith("ATOM  ") and line[21] == "L" and l_atom is None:
                l_atom = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        self.assertIsNotNone(t71_ca)
        self.assertIsNotNone(l_atom)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pose = tmp / "pose.pdb.gz"
            io_json = tmp / "io.json"
            out = tmp / "score.json"
            extra_atoms = [
                atom_line(9001, "CA", "ALA", "H", 100, t71_ca[0] + 1.0, t71_ca[1], t71_ca[2]),
                atom_line(9002, "CB", "ALA", "H", 100, t71_ca[0] + 1.2, t71_ca[1], t71_ca[2]),
                atom_line(9003, "CA", "SER", "H", 30, l_atom[0] + 1.0, l_atom[1], l_atom[2]),
                "HETATM 9004  CA   MSE H  71    %8.3f%8.3f%8.3f  1.00 20.00           C\n"
                % (t71_ca[0] + 0.5, t71_ca[1], t71_ca[2]),
            ]
            with gzip.open(pose, "wt") as handle:
                handle.write(reference_text.replace("END\n", ""))
                handle.writelines(extra_atoms)
                handle.write("END\n")
            io_json.write_text(json.dumps({"score": -12.5, "unw_energies": {"air": 3.25}}))
            run_cmd(PYTHON, "scripts/score_pose.py", str(pose), "--reference", "8x6b", "--io-json", str(io_json), "--out", str(out))
            payload = json.loads(out.read_text())

        self.assertEqual(payload["haddock_io"]["score"], -12.5)
        self.assertEqual(payload["haddock_io"]["unw_energies.air"], 3.25)
        score = payload["scores"][0]
        self.assertEqual(score["overlay"]["common_t_ca_count"], 103)
        self.assertLess(score["overlay"]["t_ca_rmsd_a"], 0.001)
        self.assertIn(71, score["hotspot_overlap"]["full"]["positions"])
        self.assertGreaterEqual(score["hotspot_overlap"]["anchor"]["count"], 1)
        self.assertGreaterEqual(score["vhh_pvrig_contacts"]["pvrig_residue_count"], 1)
        self.assertGreaterEqual(score["vhh_pvrl2_occlusion"]["by_vhh_region_pair_count"]["cdr1"], 1)
        self.assertGreaterEqual(score["vhh_pvrl2_occlusion"]["by_vhh_region_pair_count"]["cdr3"], 0)
        self.assertGreaterEqual(score["clashes_2p5a"]["atom_pair_count"], 1)

    def test_hetatm_vhh_like_records_are_ignored(self):
        reference_text = (ROOT / "inputs/normalized/8x6b_TL_reference.pdb").read_text()
        t71_ca = None
        for line in reference_text.splitlines():
            if line.startswith("ATOM  ") and line[21] == "T" and int(line[22:26]) == 71 and line[12:16].strip() == "CA":
                t71_ca = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                break
        self.assertIsNotNone(t71_ca)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pose = tmp / "pose.pdb"
            out = tmp / "score.json"
            pose.write_text(
                reference_text.replace("END\n", "")
                + atom_line(9101, "CA", "ALA", "H", 100, 999.0, 999.0, 999.0)
                + "HETATM 9102  CA   MSE H 100    %8.3f%8.3f%8.3f  1.00 20.00           C\n"
                % (t71_ca[0] + 0.5, t71_ca[1], t71_ca[2])
                + "END\n"
            )
            run_cmd(PYTHON, "scripts/score_pose.py", str(pose), "--reference", "8x6b", "--out", str(out))
            payload = json.loads(out.read_text())
        self.assertNotIn(71, payload["scores"][0]["hotspot_overlap"]["full"]["positions"])


if __name__ == "__main__":
    unittest.main()
