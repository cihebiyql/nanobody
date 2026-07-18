import csv
import hashlib
import pathlib
import sys
import tempfile
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_residue_graph_cache_v2 as mod


ONE_TO_THREE = {value: key for key, value in mod.THREE_TO_ONE.items()}


def pdb_atom(serial, atom, residue, chain, number, xyz, confidence=85.0):
    element = atom[0]
    return (
        f"ATOM  {serial:5d} {atom:>4s} {ONE_TO_THREE[residue]:>3s} {chain:1s}"
        f"{number:4d}    {xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
        f"{1.0:6.2f}{confidence:6.2f}          {element:>2s}\n"
    )


def write_monomer(path, sequence="ACDE", chain="A", transform=None, second_chain=False):
    lines = []
    serial = 1
    for index, residue in enumerate(sequence, start=1):
        ca = np.array([3.8 * (index - 1), 0.5 * ((index - 1) % 2), 0.25 * (index - 1)])
        atoms = {
            "N": ca + np.array([-1.25, 0.45, 0.1]),
            "CA": ca,
            "C": ca + np.array([1.35, 0.25, -0.15]),
        }
        for atom, xyz in atoms.items():
            if transform is not None:
                rotation, translation = transform
                xyz = rotation @ xyz + translation
            lines.append(pdb_atom(serial, atom, residue, chain, index, xyz, 80.0 + index))
            serial += 1
    if second_chain:
        for atom, xyz in {
            "N": np.array([0.0, 10.0, 0.0]),
            "CA": np.array([1.0, 10.0, 0.0]),
            "C": np.array([2.0, 10.0, 0.0]),
        }.items():
            lines.append(pdb_atom(serial, atom, "A", "B", 1, xyz))
            serial += 1
    path.write_text("".join(lines) + "END\n", encoding="utf-8")


class TestResidueGraphCacheV2(unittest.TestCase):
    def test_pdb_graph_uses_n_ca_c_and_is_rigid_invariant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            first = root / "monomer_a.pdb"
            second = root / "monomer_b.pdb"
            theta = 0.7
            rotation = np.array([
                [np.cos(theta), -np.sin(theta), 0.0],
                [np.sin(theta), np.cos(theta), 0.0],
                [0.0, 0.0, 1.0],
            ])
            translation = np.array([13.0, -7.5, 4.25])
            write_monomer(first)
            write_monomer(second, transform=(rotation, translation))
            sequence = "ACDE"
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            graph_a = mod.build_graph_from_pdb(
                entity_id="A", sequence=sequence, sequence_digest=digest,
                monomer_path=first, region_index=[0, 1, 2, 3], expected_chain="A",
            )
            graph_b = mod.build_graph_from_pdb(
                entity_id="B", sequence=sequence, sequence_digest=digest,
                monomer_path=second, region_index=[0, 1, 2, 3], expected_chain="A",
            )
            np.testing.assert_array_equal(graph_a.edge_index, graph_b.edge_index)
            # PDB coordinates are rounded to 0.001 A, so invariant features agree
            # within the corresponding numerical precision.
            np.testing.assert_allclose(graph_a.edge_features, graph_b.edge_features, atol=1.5e-3, rtol=1.5e-3)
            self.assertEqual(graph_a.edge_features.shape[1], mod.GraphBuildConfig().edge_feature_dim)
            self.assertEqual(graph_a.atom_n.shape, (4, 3))
            self.assertEqual(graph_a.local_frames.shape, (4, 3, 3))

    def test_sequence_edges_survive_radius_and_spatial_edges_respect_knn(self):
        coordinates = np.asarray([[0.0, 0.0, 0.0], [20.0, 0.0, 0.0], [20.5, 0.0, 0.0]])
        config = mod.GraphBuildConfig(knn=1, radius_angstrom=1.0)
        edge_index, sequence_flags, spatial_flags = mod.build_edge_index(coordinates, config)
        flags = {
            tuple(edge_index[:, index]): (bool(sequence_flags[index]), bool(spatial_flags[index]))
            for index in range(edge_index.shape[1])
        }
        self.assertIn((0, 1), flags)
        self.assertTrue(flags[(0, 1)][0])
        self.assertFalse(flags[(0, 1)][1])
        self.assertTrue(flags[(1, 2)][0])
        self.assertTrue(flags[(1, 2)][1])

    def test_materialized_cache_has_hash_closure_and_no_source_feature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            pdb = root / "monomer.pdb"
            write_monomer(pdb)
            sequence = "ACDE"
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            graph = mod.build_graph_from_pdb(
                entity_id="candidate", sequence=sequence, sequence_digest=digest,
                monomer_path=pdb, region_index=[0, 1, 2, 3], expected_chain="A",
            )
            receipt = mod.materialize_graph_cache([graph], root / "cache")
            arrays, rows, loaded_receipt = mod.load_graph_cache(root / "cache")
            self.assertEqual(receipt, loaded_receipt)
            self.assertEqual(receipt["status"], "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE")
            self.assertEqual(receipt["counts"]["entities"], 1)
            self.assertNotIn("teacher_source", arrays)
            self.assertNotIn("teacher_source", rows[0])
            self.assertEqual(arrays["node_offsets"].tolist(), [0, 4])
            self.assertEqual(rows[0]["sequence_sha256"], digest)

    def test_manifest_adapter_binds_input_but_drops_audit_only_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            pdb_root = root / "monomers"
            pdb_root.mkdir()
            pdb = pdb_root / "candidate.pdb"
            write_monomer(pdb)
            sequence = "ACDE"
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            manifest = root / "manifest.tsv"
            fields = [
                "candidate_id", "sequence", "sequence_sha256", "monomer_relative_path",
                "monomer_sha256", "source_chain", "region_indices", "teacher_source", "claim_boundary",
            ]
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "candidate", "sequence": sequence, "sequence_sha256": digest,
                    "monomer_relative_path": "candidate.pdb", "monomer_sha256": mod.sha256_file(pdb),
                    "source_chain": "A", "region_indices": "0,1,2,3",
                    "teacher_source": "AUDIT_ONLY_NOT_A_FEATURE",
                    "claim_boundary": "Label-free monomer only; no Docking Gold or Docking result.",
                })
            receipt = mod.build_cache_from_manifest(manifest, pdb_root, root / "cache", expected_entities=1)
            arrays, rows, loaded = mod.load_graph_cache(root / "cache")
            self.assertEqual(receipt["input_manifest_sha256"], mod.sha256_file(manifest))
            self.assertEqual(receipt, loaded)
            self.assertNotIn("teacher_source", arrays)
            self.assertNotIn("teacher_source", rows[0])

    def test_candidate_docking_path_and_multichain_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            forbidden = root / "docking_pose_1.pdb"
            write_monomer(forbidden)
            with self.assertRaisesRegex(mod.GraphCacheError, "docking_or_complex"):
                mod.parse_monomer_backbone(forbidden, expected_sequence="ACDE")
            multichain = root / "monomer.pdb"
            write_monomer(multichain, second_chain=True)
            with self.assertRaisesRegex(mod.GraphCacheError, "multiple_chains"):
                mod.parse_monomer_backbone(multichain, expected_sequence="ACDE")

    def test_sequence_and_monomer_hashes_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            pdb = root / "monomer.pdb"
            write_monomer(pdb)
            with self.assertRaisesRegex(mod.GraphCacheError, "sequence_sha256_mismatch"):
                mod.build_graph_from_pdb(
                    entity_id="candidate", sequence="ACDE", sequence_digest="0" * 64,
                    monomer_path=pdb, region_index=[0, 1, 2, 3], expected_chain="A",
                )
            digest = hashlib.sha256(b"ACDE").hexdigest()
            with self.assertRaisesRegex(mod.GraphCacheError, "monomer_sha256_mismatch"):
                mod.build_graph_from_pdb(
                    entity_id="candidate", sequence="ACDE", sequence_digest=digest,
                    monomer_path=pdb, region_index=[0, 1, 2, 3], expected_chain="A",
                    expected_monomer_sha256="f" * 64,
                )


if __name__ == "__main__":
    unittest.main()
