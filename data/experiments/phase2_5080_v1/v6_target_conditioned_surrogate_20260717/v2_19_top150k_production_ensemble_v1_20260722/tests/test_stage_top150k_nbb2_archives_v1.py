import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import stage_top150k_nbb2_archives_v1 as mod


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


ONE_TO_THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY",
    "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU", "M": "MET", "N": "ASN",
    "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER", "T": "THR", "V": "VAL",
    "W": "TRP", "Y": "TYR",
}


def pdb_payload(sequence: str, offset: float = 0.0, chain: str = "A") -> bytes:
    lines = []
    serial = 1
    for residue_number, aa in enumerate(sequence, start=1):
        residue = ONE_TO_THREE[aa]
        ca_x = offset + 3.8 * (residue_number - 1)
        for atom, xyz in (
            ("N", (ca_x - 1.2, 0.45, 0.10)),
            ("CA", (ca_x, 0.25 * (residue_number % 2), 0.05 * residue_number)),
            ("C", (ca_x + 1.3, 0.20, -0.15)),
        ):
            element = atom[0]
            lines.append(
                f"ATOM  {serial:5d} {atom:>4s} {residue:>3s} {chain:1s}{residue_number:4d}    "
                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{1.0:6.2f}{85.0:6.2f}          {element:>2s}\n"
            )
            serial += 1
    lines.append("END\n")
    return "".join(lines).encode("ascii")


def add_regular(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(payload))


class Fixture:
    fields = (
        "candidate_id", "sequence", "sequence_sha256", "parent_cluster",
        "cdr1_after", "cdr2_after", "cdr3_after", "nbb2_nbb2_archive_path",
        "nbb2_nbb2_archive_member", "nbb2_nbb2_archive_sha256",
        "nbb2_pdb_sha256", "nbb2_pdb_bytes", "forbidden_geometry_label",
    )

    def __init__(self, root: pathlib.Path, *, members=("node/a.pdb", "node/b.pdb", "node/c.pdb")):
        self.root = root
        self.source = root / "source.tsv.gz"
        self.pdb_root = root / "staged_pdbs"
        self.output = root / "metadata"
        sequences = ("AAACCCDDDEEE", "GGGHHHIIIKKK", "LLLMMMNNNPPP")
        self.payloads = [pdb_payload(sequence, index * 10.0) for index, sequence in enumerate(sequences)]
        self.archives = [root / "archive_0.tar.gz", root / "archive_1.tar.gz"]
        with tarfile.open(self.archives[0], "w:gz") as archive:
            add_regular(archive, members[0], self.payloads[0])
            add_regular(archive, members[1], self.payloads[1])
        with tarfile.open(self.archives[1], "w:gz") as archive:
            add_regular(archive, members[2], self.payloads[2])
        self.rows = []
        cdrs = (("AAA", "CCC", "DDD"), ("GGG", "HHH", "III"), ("LLL", "MMM", "NNN"))
        for index in range(3):
            archive_index = 0 if index < 2 else 1
            payload = self.payloads[index]
            sequence = sequences[index]
            self.rows.append({
                "candidate_id": f"candidate_{index}",
                "sequence": sequence,
                "sequence_sha256": digest(sequence.encode("ascii")),
                "parent_cluster": f"parent_{index % 2}",
                "cdr1_after": cdrs[index][0],
                "cdr2_after": cdrs[index][1],
                "cdr3_after": cdrs[index][2],
                "nbb2_nbb2_archive_path": str(self.archives[archive_index]),
                "nbb2_nbb2_archive_member": members[index],
                "nbb2_nbb2_archive_sha256": mod.sha256_file(self.archives[archive_index]),
                "nbb2_pdb_sha256": digest(payload),
                "nbb2_pdb_bytes": str(len(payload)),
                "forbidden_geometry_label": "SHOULD_NOT_BE_PROJECTED",
            })
        self.write()

    def write(self, fields=None):
        fields = tuple(fields or self.fields)
        with gzip.open(self.source, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows([{field: row.get(field, "") for field in fields} for row in self.rows])

    def run(self, **kwargs):
        return mod.materialize(
            self.source, self.pdb_root, self.output,
            expected_rows=3, workers=kwargs.pop("workers", 2),
            require_expected_archive_sha256=kwargs.pop("require_expected_archive_sha256", True),
            **kwargs,
        )


class TestStageTop150kNbb2ArchivesV1(unittest.TestCase):
    def test_real_nbb2_chain_h_is_accepted_and_preserved(self):
        payload = pdb_payload("ACDEFGHIKLMNPQRSTVWY" * 4, chain="H")
        self.assertEqual(mod.validate_label_free_pdb(payload, "chain_h"), "H")

    def test_parallel_materialization_emits_m2_graph_and_hash_closed_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            result = fixture.run(workers=2)
            self.assertEqual(result["status"], mod.READY_STATUS)
            self.assertEqual(result["extracted"], 3)
            receipt = json.loads((fixture.output / mod.RECEIPT_NAME).read_text())
            self.assertEqual(receipt["counts"]["archive_hash_computations"], 2)
            self.assertEqual(receipt["counts"]["archives_matched_expected_sha256"], 2)
            self.assertEqual(receipt["invariants"]["geometry_label_columns_read"], 0)
            self.assertNotIn("forbidden_geometry_label", receipt["inputs"]["projected_columns"])
            with (fixture.output / mod.M2_MANIFEST_NAME).open(newline="") as handle:
                m2 = list(csv.DictReader(handle, delimiter="\t"))
            with (fixture.output / mod.GRAPH_MANIFEST_NAME).open(newline="") as handle:
                graph = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(m2), len(graph), 3)
            self.assertTrue(all(row["schema_version"] == mod.M2_SCHEMA_VERSION for row in m2))
            self.assertEqual(graph[0]["cdr1_range"], "1-3")
            self.assertEqual(graph[0]["cdr2_range"], "4-6")
            self.assertEqual(graph[0]["cdr3_range"], "7-9")
            self.assertFalse(pathlib.Path(graph[0]["monomer_relative_path"]).is_absolute())
            for name, expected in receipt["outputs"].items():
                self.assertEqual(mod.sha256_file(fixture.output / name), expected)

    def test_graph_manifest_is_consumed_by_existing_residue_graph_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.run(workers=1)
            builder_path = ROOT.parent / "residue_v2" / "src" / "build_residue_graph_cache_v2.py"
            specification = importlib.util.spec_from_file_location("top150k_graph_builder_fixture", builder_path)
            builder = importlib.util.module_from_spec(specification)
            sys.modules[specification.name] = builder
            specification.loader.exec_module(builder)
            cache_dir = fixture.root / "graph_cache"
            receipt = builder.build_cache_from_manifest(
                fixture.output / mod.GRAPH_MANIFEST_NAME,
                fixture.pdb_root,
                cache_dir,
                expected_entities=3,
            )
            self.assertEqual(receipt["counts"]["entities"], 3)
            self.assertEqual(receipt["status"], "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE")

    def test_resume_accepts_only_exact_existing_pdb_and_final_delivery_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            asset_sha = fixture.rows[0]["sequence_sha256"]
            destination = fixture.pdb_root / asset_sha[:2] / "candidate_0.pdb"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(fixture.payloads[0])
            result = fixture.run(workers=1)
            self.assertEqual(result["resumed"], 1)
            self.assertEqual(result["extracted"], 2)
            replay = fixture.run(workers=1)
            self.assertEqual(replay["status"], "PASS_EXISTING_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING")

    def test_resume_after_metadata_publication_before_receipt_verifies_partial_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.run(workers=1)
            (fixture.output / mod.RECEIPT_NAME).unlink()
            replay = fixture.run(workers=1)
            self.assertEqual(replay["status"], mod.READY_STATUS)
            receipt = json.loads((fixture.output / mod.RECEIPT_NAME).read_text())
            self.assertEqual(
                set(receipt["publication_states"].values()), {"VERIFIED_EXISTING"}
            )
            self.assertEqual(receipt["counts"]["pdbs_resumed_this_attempt"], 3)

    def test_resume_rejects_corrupt_existing_pdb(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            asset_sha = fixture.rows[0]["sequence_sha256"]
            destination = fixture.pdb_root / asset_sha[:2] / "candidate_0.pdb"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"x" * len(fixture.payloads[0]))
            with self.assertRaisesRegex(mod.StagingError, "staged_pdb_sha256_mismatch"):
                fixture.run(workers=1)

    def test_archive_digest_mismatch_fails_closed_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.rows[0]["nbb2_nbb2_archive_sha256"] = "0" * 64
            fixture.rows[1]["nbb2_nbb2_archive_sha256"] = "0" * 64
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "archive_sha256_mismatch"):
                fixture.run(workers=1)
            self.assertFalse((fixture.output / mod.RECEIPT_NAME).exists())

    def test_member_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary), members=("../escape.pdb", "node/b.pdb", "node/c.pdb"))
            with self.assertRaisesRegex(mod.StagingError, "archive_member_unsafe"):
                fixture.run(workers=1)

    def test_tar_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            fixture = Fixture(root)
            archive = root / "symlink.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                link = tarfile.TarInfo("node/link.pdb")
                link.type = tarfile.SYMTYPE
                link.linkname = "target.pdb"
                link.size = 0
                handle.addfile(link)
            fixture.rows = [fixture.rows[0]]
            fixture.rows[0].update({
                "nbb2_nbb2_archive_path": str(archive),
                "nbb2_nbb2_archive_member": "node/link.pdb",
                "nbb2_nbb2_archive_sha256": mod.sha256_file(archive),
                "nbb2_pdb_bytes": "1",
                "nbb2_pdb_sha256": digest(b"x"),
            })
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "archive_member_not_regular"):
                mod.materialize(
                    fixture.source, fixture.pdb_root, fixture.output,
                    expected_rows=1, workers=1, require_expected_archive_sha256=True,
                )

    def test_member_byte_and_sha_contracts_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.rows[0]["nbb2_pdb_bytes"] = str(len(fixture.payloads[0]) + 1)
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "archive_member_bytes_mismatch"):
                fixture.run(workers=1)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.rows[0]["nbb2_pdb_sha256"] = "f" * 64
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "archive_member_sha256_mismatch"):
                fixture.run(workers=1)

    def test_missing_expected_archive_digest_requires_explicit_observed_only_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fields = tuple(field for field in fixture.fields if field != "nbb2_nbb2_archive_sha256")
            fixture.write(fields)
            with self.assertRaisesRegex(mod.StagingError, "archive_expected_sha256_missing"):
                fixture.run(workers=1, require_expected_archive_sha256=True)
            result = fixture.run(workers=1, require_expected_archive_sha256=False)
            self.assertEqual(result["status"], mod.READY_STATUS)
            receipt = json.loads((fixture.output / mod.RECEIPT_NAME).read_text())
            self.assertEqual(receipt["counts"]["archives_observed_without_upstream_expected"], 2)

    def test_external_archive_digest_table_closes_manifest_without_inline_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fields = tuple(field for field in fixture.fields if field != "nbb2_nbb2_archive_sha256")
            fixture.write(fields)
            digest_table = fixture.root / "archive_digests.tsv"
            with digest_table.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("archive_path", "archive_sha256"), delimiter="\t")
                writer.writeheader()
                for archive in fixture.archives:
                    writer.writerow({"archive_path": str(archive), "archive_sha256": mod.sha256_file(archive)})
            result = fixture.run(
                workers=1,
                require_expected_archive_sha256=True,
                archive_digest_tsv=digest_table,
            )
            self.assertEqual(result["archives"], 2)

    def test_duplicate_candidate_and_sequence_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.rows[1]["candidate_id"] = fixture.rows[0]["candidate_id"]
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "duplicate_candidate_id"):
                fixture.run(workers=1)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            fixture.rows[1]["sequence"] = fixture.rows[0]["sequence"]
            fixture.rows[1]["sequence_sha256"] = fixture.rows[0]["sequence_sha256"]
            fixture.rows[1]["cdr1_after"] = fixture.rows[0]["cdr1_after"]
            fixture.rows[1]["cdr2_after"] = fixture.rows[0]["cdr2_after"]
            fixture.rows[1]["cdr3_after"] = fixture.rows[0]["cdr3_after"]
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "duplicate_sequence_sha256"):
                fixture.run(workers=1)

    def test_source_and_archive_symlinks_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            source_link = fixture.root / "source_link.tsv.gz"
            source_link.symlink_to(fixture.source)
            with self.assertRaisesRegex(mod.StagingError, "not_regular_file:source_tsv_gz"):
                mod.materialize(source_link, fixture.pdb_root, fixture.output, expected_rows=3, workers=1)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(pathlib.Path(temporary))
            archive_link = fixture.root / "archive_link.tar.gz"
            archive_link.symlink_to(fixture.archives[0])
            fixture.rows[0]["nbb2_nbb2_archive_path"] = str(archive_link)
            fixture.write()
            with self.assertRaisesRegex(mod.StagingError, "not_regular_file:archive"):
                fixture.run(workers=1)


if __name__ == "__main__":
    unittest.main()
