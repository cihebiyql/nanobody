import csv
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import torch


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_residue_graph_cache_v2 as graph_mod
import build_target_graph_cache_v2 as mod


THREE = {value: key for key, value in graph_mod.THREE_TO_ONE.items()}


def atom_line(serial, atom, aa, chain, number, x, y, z):
    return (
        f"ATOM  {serial:5d} {atom:>4s} {THREE[aa]:>3s} {chain}{number:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{25.0:6.2f}          {atom[0]:>2s}\n"
    )


def public_structure(sequence, target_chain, ligand_chain):
    lines = ["HEADER    TEST PUBLIC STRUCTURE\n"]
    serial = 1
    for number, aa in enumerate(sequence, start=1):
        ca_x = 3.7 * (number - 1)
        for atom, dx, dy, dz in (
            ("N", -1.2, 0.4, 0.1), ("CA", 0.0, 0.0, 0.0),
            ("C", 1.3, 0.25, -0.1), ("O", 1.8, 0.8, -0.15),
        ):
            lines.append(atom_line(serial, atom, aa, target_chain, number, ca_x + dx, dy + 0.2 * number, dz))
            serial += 1
    # A ligand chain is present in the public source and must be discarded.
    for atom, dx in (("N", 0.0), ("CA", 1.0), ("C", 2.0)):
        lines.append(atom_line(serial, atom, "A", ligand_chain, 1, dx, 20.0, 0.0))
        serial += 1
    return "".join(lines) + "END\n"


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class TestTargetGraphCacheV2(unittest.TestCase):
    def fixture(self, root):
        sequence = "ACDEG"
        (root / "8X6B.pdb").write_text(public_structure(sequence, "B", "A"), encoding="utf-8")
        (root / "9E6Y.pdb").write_text(public_structure(sequence, "A", "D"), encoding="utf-8")
        numbering = []
        for pdb_id, chain in (("8X6B", "B"), ("9E6Y", "A")):
            for number, aa in enumerate(sequence, start=1):
                numbering.append({
                    "pdb_id": pdb_id, "pvrig_chain": chain, "pdb_resseq": number,
                    "pdb_icode": "", "pdb_aa": aa, "uniprot_position": 40 + number,
                })
        write_csv(
            root / "PVRIG_numbering_reconciliation.csv",
            ["pdb_id", "pvrig_chain", "pdb_resseq", "pdb_icode", "pdb_aa", "uniprot_position"],
            numbering,
        )
        interface_fields = ["pdb_id", "pvrig_chain", "pvrig_resseq", "pvrig_icode", "pvrig_aa"]
        write_csv(root / "PVRIG_interface_residues_8X6B.csv", interface_fields, [
            {"pdb_id": "8X6B", "pvrig_chain": "B", "pvrig_resseq": 2, "pvrig_icode": "", "pvrig_aa": "C"},
            {"pdb_id": "8X6B", "pvrig_chain": "B", "pvrig_resseq": 4, "pvrig_icode": "", "pvrig_aa": "E"},
        ])
        write_csv(root / "PVRIG_interface_residues_9E6Y.csv", interface_fields, [
            {"pdb_id": "9E6Y", "pvrig_chain": "A", "pvrig_resseq": 2, "pvrig_icode": "", "pvrig_aa": "C"},
            {"pdb_id": "9E6Y", "pvrig_chain": "A", "pvrig_resseq": 4, "pvrig_icode": "", "pvrig_aa": "E"},
        ])
        hotspot_fields = ["hotspot_id", "priority_weight", "pdb_8x6b_ref", "pdb_9e6y_ref"]
        write_csv(root / "PVRIG_hotspot_set_v1.csv", hotspot_fields, [
            {"hotspot_id": "h2", "priority_weight": "1.0", "pdb_8x6b_ref": "B:2C", "pdb_9e6y_ref": "A:2C"},
            {"hotspot_id": "h4", "priority_weight": "0.7", "pdb_8x6b_ref": "B:4E", "pdb_9e6y_ref": "A:4E"},
        ])

    def test_extracts_only_target_chain_and_builds_model_ready_graphs(self):
        with tempfile.TemporaryDirectory() as temporary:
            structures = pathlib.Path(temporary) / "structures"
            structures.mkdir()
            self.fixture(structures)
            output = pathlib.Path(temporary) / "target_cache"
            receipt = mod.materialize_target_graphs(
                structures_root=structures, output_dir=output, dry_run=False,
                expected_source_hashes=False,
            )
            self.assertEqual(receipt["status"], "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED")
            self.assertEqual(receipt["node_feature_dim"], len(mod.NODE_FEATURE_NAMES))
            graphs = mod.load_target_graph_cache(output)
            self.assertEqual(set(graphs), {"8x6b", "9e6y"})
            for receptor, graph in graphs.items():
                self.assertEqual(graph["node_features"].shape, (5, 30))
                self.assertEqual(int(graph["interface_mask"].sum()), 2)
                self.assertEqual(int(graph["hotspot_mask"].sum()), 2)
                self.assertEqual(graph["edge_features"].shape[1], 26)
            torch_graphs = torch.load(output / mod.TORCH_NAME, map_location="cpu", weights_only=True)
            self.assertEqual(set(torch_graphs), {"8x6b", "9e6y"})
            self.assertEqual(
                set(torch_graphs["8x6b"]),
                {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"},
            )
            self.assertNotIn("teacher_source", torch_graphs)
            extracted = (output / mod.TARGET_ROOT_NAME / "pvrig_8x6b_chain_b.pdb").read_text()
            self.assertNotIn(" A   1", extracted)
            self.assertTrue(all(line[21:22] == "B" for line in extracted.splitlines() if line.startswith("ATOM")))

    def test_dry_run_writes_nothing_and_reports_sealed_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            structures = pathlib.Path(temporary) / "structures"
            structures.mkdir()
            self.fixture(structures)
            output = pathlib.Path(temporary) / "must_not_exist"
            receipt = mod.materialize_target_graphs(
                structures_root=structures, output_dir=output, dry_run=True,
                expected_source_hashes=False,
            )
            self.assertEqual(receipt["status"], "PASS_DRY_RUN_FIXED_TARGET_GRAPHS")
            self.assertEqual(receipt["sealed_boundary"]["candidate_docking_pose_files_opened"], 0)
            self.assertFalse(output.exists())

    def test_interface_aa_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            structures = pathlib.Path(temporary) / "structures"
            structures.mkdir()
            self.fixture(structures)
            path = structures / "PVRIG_interface_residues_8X6B.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["pvrig_aa"] = "W"
            write_csv(path, list(rows[0]), rows)
            with self.assertRaisesRegex(mod.TargetGraphError, "interface_aa_mismatch"):
                mod.materialize_target_graphs(
                    structures_root=structures,
                    output_dir=pathlib.Path(temporary) / "cache",
                    dry_run=True,
                    expected_source_hashes=False,
                )


if __name__ == "__main__":
    unittest.main()
