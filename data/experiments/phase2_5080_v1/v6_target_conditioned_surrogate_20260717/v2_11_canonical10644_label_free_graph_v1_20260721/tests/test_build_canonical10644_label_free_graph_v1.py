from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/build_canonical10644_label_free_graph_v1.py"
GRAPH_BUILDER = ROOT.parents[0] / "residue_v2/src/build_residue_graph_cache_v2.py"


def import_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MOD = import_module("canonical10644_label_free_graph_v1", SOURCE)


THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
    "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
    "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
    "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    names = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_monomer(path: Path, sequence: str, chain: str = "A") -> None:
    lines: list[str] = []
    serial = 1
    for index, aa in enumerate(sequence, start=1):
        ca_x = 3.8 * (index - 1)
        atoms = {
            "N": (ca_x - 1.2, 0.4, 0.1),
            "CA": (ca_x, 0.0, 0.0),
            "C": (ca_x + 1.3, 0.3, -0.1),
        }
        for atom, xyz in atoms.items():
            lines.append(
                f"ATOM  {serial:5d} {atom:>4s} {THREE[aa]:>3s} {chain}{index:4d}    "
                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{1.0:6.2f}{90.0:6.2f}          {atom[0]:>2s}\n"
            )
            serial += 1
    path.write_text("".join(lines) + "END\n", encoding="utf-8")


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.monomers = root / "monomers"
        self.monomers.mkdir()
        self.target = root / "fixed_target"
        self.target.mkdir()
        self.teacher = root / "canonical.tsv"
        self.structures = root / "structure_manifest.tsv"
        self.contract = root / "INPUT_CONTRACT.json"
        self.output = root / "prepared"
        self.candidates = [
            ("candidate_a", "ACDEFGHIKLMN", "CD", "FG", "KL"),
            ("candidate_b", "QRSTVWYACDEF", "RS", "VW", "AC"),
        ]
        self.structure_rows: list[dict[str, str]] = []
        self.write_inputs()

    def write_inputs(self) -> None:
        teacher_rows = []
        self.structure_rows = []
        for candidate_id, sequence, cdr1, cdr2, cdr3 in self.candidates:
            digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            pdb = self.monomers / f"{candidate_id}.pdb"
            write_monomer(pdb, sequence)
            teacher_rows.append({
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "sequence": sequence,
                "cdr1": cdr1,
                "cdr2": cdr2,
                "cdr3": cdr3,
                "R_8X6B": "0.5",
                "R_9E6Y": "0.4",
                "teacher_source": "AUDIT_ONLY",
            })
            self.structure_rows.append({
                "candidate_id": candidate_id,
                "sequence_sha256": digest,
                "frozen_monomer_path": pdb.name,
                "source_chain": "A",
                "sha256": sha256(pdb),
                "size_bytes": str(pdb.stat().st_size),
            })
        write_tsv(self.teacher, teacher_rows)
        write_tsv(self.structures, self.structure_rows)

        artifact_hashes: dict[str, str] = {}
        for name, payload in (
            ("target_graph_cache_v2.npz", b"fixture-npz"),
            ("target_graph_manifest_v2.tsv", b"receptor\tnodes\n8x6b\t1\n9e6y\t1\n"),
            ("target_graphs_v2.pt", b"fixture-pt"),
        ):
            path = self.target / name
            path.write_bytes(payload)
            artifact_hashes[name] = sha256(path)
        target_receipt = {
            "status": MOD.EXPECTED_TARGET_STATUS,
            "outputs": artifact_hashes,
            "sealed_boundary": {
                "candidate_docking_pose_files_opened": 0,
                "teacher_source_is_model_feature": False,
                "absolute_coordinates_are_node_features": False,
            },
        }
        receipt_path = self.target / "target_graph_receipt_v2.json"
        receipt_path.write_text(json.dumps(target_receipt, sort_keys=True), encoding="utf-8")
        contract = {
            "schema_version": MOD.CONTRACT_SCHEMA,
            "status": "FROZEN_PRE_MATERIALIZATION",
            "implicit_materialization_authorized": False,
            "expected_rows": len(self.candidates),
            "canonical_candidates": {"path": str(self.teacher), "sha256": sha256(self.teacher)},
            "graph_builder": {"path": str(GRAPH_BUILDER), "sha256": sha256(GRAPH_BUILDER)},
            "fixed_target_graph": {
                "receipt_path": str(receipt_path),
                "receipt_sha256": sha256(receipt_path),
                "artifacts": {
                    name: {"path": str(self.target / name), "sha256": digest}
                    for name, digest in artifact_hashes.items()
                },
            },
        }
        self.contract.write_text(json.dumps(contract, sort_keys=True), encoding="utf-8")

    def prepare(self):
        return MOD.prepare_bundle(
            contract_path=self.contract,
            structure_manifest_path=self.structures,
            expected_structure_manifest_sha256=sha256(self.structures),
            output_dir=self.output,
        )


class CanonicalLabelFreeGraphTests(unittest.TestCase):
    def test_prepare_and_small_fixture_materialization_close_all_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            prepare = fixture.prepare()
            self.assertEqual(prepare["counts"]["exact_candidate_sequence_monomer_triplets"], 2)
            self.assertEqual(prepare["access_audit"]["contact_teacher_files_opened"], 0)
            self.assertFalse(prepare["materialization"]["performed"])
            with (fixture.output / MOD.PREPARED_MANIFEST).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(list(rows[0]), list(MOD.OUTPUT_FIELDS))
            for forbidden in ("teacher_source", "R_8X6B", "contact", "pose", "docking"):
                self.assertNotIn(forbidden, rows[0])
            wrapper = MOD.materialize_prepared_bundle(
                contract_path=fixture.contract,
                prepared_dir=fixture.output,
                pdb_root=fixture.monomers,
                explicit_authorization=True,
            )
            self.assertEqual(wrapper["status"], "PASS_CANONICAL10644_LABEL_FREE_GRAPH_MATERIALIZED")
            self.assertEqual(wrapper["counts"]["graph_entities"], 2)
            self.assertEqual(wrapper["access_audit"]["candidate_docking_pose_files_opened"], 0)
            graph_receipt = json.loads((fixture.output / MOD.GRAPH_CACHE_DIR / "graph_cache_receipt_v2.json").read_text())
            self.assertEqual(graph_receipt["input_manifest_sha256"], sha256(fixture.output / MOD.PREPARED_MANIFEST))

    def test_structure_manifest_sha256_is_required_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            with self.assertRaisesRegex(MOD.CanonicalGraphError, "structure_manifest_sha256_mismatch"):
                MOD.prepare_bundle(
                    contract_path=fixture.contract,
                    structure_manifest_path=fixture.structures,
                    expected_structure_manifest_sha256="0" * 64,
                    output_dir=fixture.output,
                )
            self.assertFalse(fixture.output.exists())

    def test_candidate_sequence_join_mismatch_fails_before_pdb_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.structure_rows[0]["sequence_sha256"] = "f" * 64
            write_tsv(fixture.structures, fixture.structure_rows)
            with self.assertRaisesRegex(MOD.CanonicalGraphError, "candidate_structure_sequence_mismatch:candidate_a"):
                fixture.prepare()
            self.assertFalse(fixture.output.exists())

    def test_contact_pose_or_teacher_columns_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            for row in fixture.structure_rows:
                row["contact_teacher_path"] = "forbidden.tsv.gz"
            write_tsv(fixture.structures, fixture.structure_rows)
            with self.assertRaisesRegex(MOD.CanonicalGraphError, "structure_manifest_unapproved_fields"):
                fixture.prepare()
            self.assertFalse(fixture.output.exists())

    def test_docking_pose_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.structure_rows[0]["frozen_monomer_path"] = "docking_pose/candidate_a.pdb"
            write_tsv(fixture.structures, fixture.structure_rows)
            with self.assertRaisesRegex(MOD.CanonicalGraphError, "monomer_path_forbidden_token:candidate_a"):
                fixture.prepare()
            self.assertFalse(fixture.output.exists())

    def test_actual_monomer_hash_is_rechecked_only_at_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.structure_rows[0]["sha256"] = "e" * 64
            write_tsv(fixture.structures, fixture.structure_rows)
            fixture.prepare()
            with self.assertRaisesRegex(RuntimeError, "monomer_sha256_mismatch"):
                MOD.materialize_prepared_bundle(
                    contract_path=fixture.contract,
                    prepared_dir=fixture.output,
                    pdb_root=fixture.monomers,
                    explicit_authorization=True,
                )

    def test_materialization_requires_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.prepare()
            with self.assertRaisesRegex(MOD.CanonicalGraphError, "explicit_authorization_required"):
                MOD.materialize_prepared_bundle(
                    contract_path=fixture.contract,
                    prepared_dir=fixture.output,
                    pdb_root=fixture.monomers,
                    explicit_authorization=False,
                )


if __name__ == "__main__":
    unittest.main()
