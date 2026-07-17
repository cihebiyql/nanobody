#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "materialize_phase2_v4_h_research1320_structure_inputs_v1.py"

spec = importlib.util.spec_from_file_location("v4h_structure_materializer_subject", SUBJECT)
if spec is None or spec.loader is None:
    raise RuntimeError("unable_to_load_subject")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Fixture:
    def __init__(self, directory: str, count: int = 3):
        self.root = Path(directory)
        self.source = self.root / "source"
        self.portable = self.root / "portable"
        self.monomers = self.portable / "monomers"
        self.output_parent = self.root / "outputs"
        self.output = self.output_parent / m.EXPECTED_OUTPUT_BASENAME
        self.source.mkdir()
        self.monomers.mkdir(parents=True)
        self.output_parent.mkdir()
        base_sequences = (
            "ACDEFGHIKLMNPQRSTVWY",
            "CDEFGHIKLMNPQRSTVWYA",
            "DEFGHIKLMNPQRSTVWYAC",
            "EFGHIKLMNPQRSTVWYACD",
        )
        self.candidates: list[dict[str, str]] = []
        self.monomer_rows: list[dict[str, str]] = []
        for index in range(count):
            candidate_id = f"V4H_SYN_{index:03d}"
            sequence = base_sequences[index]
            sequence_sha = sha256(sequence.encode("ascii"))
            self.candidates.append(
                {
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "sequence_sha256": sequence_sha,
                    "sequence_length": str(len(sequence)),
                    "parent_id": f"PARENT_{index:03d}",
                    "parent_framework_cluster": f"C{index:04d}",
                    "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[index % 3],
                    "design_mode": ("H3", "H1H3")[index % 2],
                    "research_pool_state": "RESEARCH_READY",
                    "monomer_structure_eligible": "true",
                    "sequence_repaired": "false",
                    "claim_boundary": "synthetic label-free fixture",
                }
            )
            pdb_raw = (
                f"ATOM      1  CA  ALA A   1      {index + 1:6.3f}   0.000   0.000\nEND\n"
            ).encode("ascii")
            pdb_path = self.monomers / f"{candidate_id}.pdb"
            pdb_path.write_bytes(pdb_raw)
            self.monomer_rows.append(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": sequence_sha,
                    "frozen_monomer_path": f"monomers/{candidate_id}.pdb",
                    "source_chain": "A",
                    "sha256": sha256(pdb_raw),
                    "size_bytes": str(len(pdb_raw)),
                    "claim_boundary": "synthetic label-free fixture",
                }
            )
        self.candidate_manifest = self.source / "candidates.tsv"
        self.monomer_manifest = self.portable / "monomer_manifest.tsv"
        self.write_inputs()

    def write_inputs(self, *, reverse_monomers: bool = False) -> None:
        write_tsv(self.candidate_manifest, self.candidates)
        rows = list(reversed(self.monomer_rows)) if reverse_monomers else self.monomer_rows
        write_tsv(self.monomer_manifest, rows)

    def run(self):
        return m.materialize(
            candidate_manifest=self.candidate_manifest,
            monomer_manifest=self.monomer_manifest,
            monomers_root=self.monomers,
            output_root=self.output,
            expected_candidate_manifest_sha256=sha256(self.candidate_manifest.read_bytes()),
            expected_monomer_manifest_sha256=sha256(self.monomer_manifest.read_bytes()),
            expected_count=len(self.candidates),
            expected_output_basename=m.EXPECTED_OUTPUT_BASENAME,
        )


class StructureMaterializerTests(unittest.TestCase):
    def test_valid_materialization_is_exact_atomic_and_label_free(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            fixture.write_inputs(reverse_monomers=True)
            receipt = fixture.run()
            self.assertEqual(receipt["status"], "PASS_LABEL_FREE_STRUCTURE_INPUTS_MATERIALIZED")
            self.assertEqual(receipt["candidate_count"], 3)
            self.assertEqual(receipt["pdb_count"], 3)
            self.assertEqual(receipt["join_key"], ["candidate_id", "sequence_sha256"])
            self.assertTrue(fixture.output.is_dir())
            output_rows = read_tsv(fixture.output / m.OUTPUT_MANIFEST_NAME)
            self.assertEqual(
                [row["candidate_id"] for row in output_rows],
                [row["candidate_id"] for row in fixture.candidates],
            )
            self.assertEqual(
                [row["parent_framework_cluster"] for row in output_rows],
                [row["parent_framework_cluster"] for row in fixture.candidates],
            )
            for row in output_rows:
                pdb = fixture.output / row["monomer_relative_path"]
                self.assertTrue(pdb.is_file())
                self.assertEqual(sha256(pdb.read_bytes()), row["monomer_sha256"])
                self.assertEqual(pdb.stat().st_size, int(row["monomer_size_bytes"]))
                self.assertEqual(row["source_chain"], "A")
            disk_receipt = json.loads((fixture.output / m.RECEIPT_NAME).read_text())
            self.assertEqual(disk_receipt, receipt)
            self.assertEqual(
                disk_receipt["forbidden_path_channels_opened"],
                {"results": 0, "status": 0, "pose": 0, "test32": 0},
            )
            checksums = {}
            for line in (fixture.output / m.SHA256SUMS_NAME).read_text().splitlines():
                digest, relative = line.split("  ", 1)
                checksums[relative] = digest
                self.assertEqual(sha256((fixture.output / relative).read_bytes()), digest)
            self.assertEqual(len(checksums), 5)
            self.assertFalse(any(fixture.output.parent.glob(f".{fixture.output.name}.staging.*")))

    def test_composite_key_mismatch_fails_without_publication(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            fixture.monomer_rows[0]["sequence_sha256"] = "f" * 64
            fixture.write_inputs()
            with self.assertRaisesRegex(m.MaterializationError, "composite_key_closure_failed"):
                fixture.run()
            self.assertFalse(os.path.lexists(fixture.output))

    def test_candidate_count_closure_is_exact(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            with self.assertRaisesRegex(m.MaterializationError, "candidate_count_mismatch"):
                m.materialize(
                    candidate_manifest=fixture.candidate_manifest,
                    monomer_manifest=fixture.monomer_manifest,
                    monomers_root=fixture.monomers,
                    output_root=fixture.output,
                    expected_candidate_manifest_sha256=sha256(fixture.candidate_manifest.read_bytes()),
                    expected_monomer_manifest_sha256=sha256(fixture.monomer_manifest.read_bytes()),
                    expected_count=4,
                    expected_output_basename=m.EXPECTED_OUTPUT_BASENAME,
                )
            self.assertFalse(fixture.output.exists())

    def test_candidate_sequence_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            fixture.candidates[0]["sequence_sha256"] = "e" * 64
            fixture.write_inputs()
            with self.assertRaisesRegex(m.MaterializationError, "candidate_sequence_sha_mismatch"):
                fixture.run()
            self.assertFalse(fixture.output.exists())

    def test_candidate_and_monomer_duplicates_fail(self):
        for lane in ("candidate", "monomer"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                if lane == "candidate":
                    fixture.candidates[1]["candidate_id"] = fixture.candidates[0]["candidate_id"]
                else:
                    fixture.monomer_rows[1]["candidate_id"] = fixture.monomer_rows[0]["candidate_id"]
                fixture.write_inputs()
                with self.assertRaisesRegex(m.MaterializationError, "duplicate"):
                    fixture.run()
                self.assertFalse(fixture.output.exists())

    def test_pdb_hash_and_size_mismatch_fail_atomically(self):
        for lane in ("sha256", "size"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                if lane == "sha256":
                    fixture.monomer_rows[1]["sha256"] = "d" * 64
                else:
                    fixture.monomer_rows[1]["size_bytes"] = "999"
                fixture.write_inputs()
                with self.assertRaisesRegex(m.MaterializationError, "monomer_pdb_(sha256|size)_mismatch"):
                    fixture.run()
                self.assertFalse(os.path.lexists(fixture.output))
                self.assertFalse(any(fixture.output.parent.glob(f".{fixture.output.name}.staging.*")))

    def test_pdb_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            candidate_id = fixture.candidates[0]["candidate_id"]
            pdb = fixture.monomers / f"{candidate_id}.pdb"
            target = fixture.root / "external.pdb"
            pdb.replace(target)
            pdb.symlink_to(target)
            with self.assertRaisesRegex(m.MaterializationError, "symlink_component_rejected"):
                fixture.run()
            self.assertFalse(fixture.output.exists())

    def test_manifest_and_monomers_root_symlinks_are_rejected(self):
        for lane in ("candidate_manifest", "monomer_manifest", "monomers_root"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                candidate_manifest = fixture.candidate_manifest
                monomer_manifest = fixture.monomer_manifest
                monomers_root = fixture.monomers
                selected = {
                    "candidate_manifest": candidate_manifest,
                    "monomer_manifest": monomer_manifest,
                    "monomers_root": monomers_root,
                }[lane]
                target = selected.with_name(selected.name + ".target")
                selected.replace(target)
                selected.symlink_to(target, target_is_directory=target.is_dir())
                with self.assertRaisesRegex(m.MaterializationError, "symlink_component_rejected"):
                    m.materialize(
                        candidate_manifest=candidate_manifest,
                        monomer_manifest=monomer_manifest,
                        monomers_root=monomers_root,
                        output_root=fixture.output,
                        expected_candidate_manifest_sha256=(
                            sha256(target.read_bytes()) if lane == "candidate_manifest" else sha256(candidate_manifest.read_bytes())
                        ),
                        expected_monomer_manifest_sha256=(
                            sha256(target.read_bytes()) if lane == "monomer_manifest" else sha256(monomer_manifest.read_bytes())
                        ),
                        expected_count=3,
                        expected_output_basename=m.EXPECTED_OUTPUT_BASENAME,
                    )
                self.assertFalse(fixture.output.exists())

    def test_source_chain_and_frozen_path_contract_are_exact(self):
        cases = (
            ("source_chain", "B", "source_chain_invalid"),
            ("frozen_monomer_path", "monomers/../escape.pdb", "path_contract_invalid"),
            ("frozen_monomer_path", "monomers//V4H_SYN_000.pdb", "path_contract_invalid"),
            ("frozen_monomer_path", "results/V4H_SYN_000.pdb", "path_contract_invalid"),
        )
        for field, value, message in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                fixture.monomer_rows[0][field] = value
                fixture.write_inputs()
                with self.assertRaisesRegex(m.MaterializationError, message):
                    fixture.run()
                self.assertFalse(fixture.output.exists())

    def test_forbidden_argument_path_components_are_rejected(self):
        for token in m.FORBIDDEN_PATH_TOKENS:
            with self.subTest(token=token), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                bad_dir = fixture.root / token
                bad_dir.mkdir()
                bad_manifest = bad_dir / "monomer_manifest.tsv"
                shutil.copyfile(fixture.monomer_manifest, bad_manifest)
                with self.assertRaisesRegex(m.MaterializationError, "forbidden_path_component"):
                    m.materialize(
                        candidate_manifest=fixture.candidate_manifest,
                        monomer_manifest=bad_manifest,
                        monomers_root=fixture.monomers,
                        output_root=fixture.output,
                        expected_candidate_manifest_sha256=sha256(fixture.candidate_manifest.read_bytes()),
                        expected_monomer_manifest_sha256=sha256(bad_manifest.read_bytes()),
                        expected_count=3,
                        expected_output_basename=m.EXPECTED_OUTPUT_BASENAME,
                    )
                self.assertFalse(fixture.output.exists())

    def test_forbidden_manifest_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            for row in fixture.monomer_rows:
                row["pose_score"] = "0"
            fixture.write_inputs()
            with self.assertRaisesRegex(m.MaterializationError, "forbidden_column"):
                fixture.run()
            self.assertFalse(fixture.output.exists())

    def test_input_manifest_hashes_are_mandatory(self):
        for lane in ("candidate", "monomer"):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as td:
                fixture = Fixture(td)
                kwargs = {
                    "candidate_manifest": fixture.candidate_manifest,
                    "monomer_manifest": fixture.monomer_manifest,
                    "monomers_root": fixture.monomers,
                    "output_root": fixture.output,
                    "expected_candidate_manifest_sha256": sha256(fixture.candidate_manifest.read_bytes()),
                    "expected_monomer_manifest_sha256": sha256(fixture.monomer_manifest.read_bytes()),
                    "expected_count": 3,
                    "expected_output_basename": m.EXPECTED_OUTPUT_BASENAME,
                }
                kwargs[f"expected_{lane}_manifest_sha256"] = "0" * 64
                with self.assertRaisesRegex(m.MaterializationError, f"{lane}_manifest_sha256_mismatch"):
                    m.materialize(**kwargs)
                self.assertFalse(fixture.output.exists())

    def test_preexisting_output_is_never_modified(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            fixture.output.mkdir()
            sentinel = fixture.output / "sentinel"
            sentinel.write_text("unchanged\n")
            with self.assertRaisesRegex(m.MaterializationError, "output_root_preexists"):
                fixture.run()
            self.assertEqual(sentinel.read_text(), "unchanged\n")

    def test_output_basename_is_version_locked(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Fixture(td)
            fixture.output = fixture.output_parent / "unversioned"
            with self.assertRaisesRegex(m.MaterializationError, "output_basename_invalid"):
                fixture.run()
            self.assertFalse(fixture.output.exists())

    def test_production_constants_and_source_surface_are_frozen(self):
        self.assertEqual(m.EXPECTED_COUNT, 1320)
        self.assertEqual(
            m.EXPECTED_CANDIDATE_MANIFEST_SHA256,
            "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551",
        )
        self.assertEqual(
            m.EXPECTED_MONOMER_MANIFEST_SHA256,
            "e74b32d53d7a1fb2719d8b7e01b60bb2855553794607f011e14e0f5399fa8137",
        )
        self.assertEqual(m.CANONICAL_CANDIDATE_MANIFEST.name, "research_ready1320.tsv")
        source = SUBJECT.read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)))
        for forbidden in ("subprocess", "ssh.exe", "os.walk", ".glob(", ".rglob("):
            self.assertNotIn(forbidden, source)
        args = m.parse_args(
            [
                "--monomer-manifest",
                "/safe/monomer_manifest.tsv",
                "--monomers-root",
                "/safe/monomers",
                "--output-root",
                f"/safe/{m.EXPECTED_OUTPUT_BASENAME}",
            ]
        )
        self.assertEqual(args.monomer_manifest, Path("/safe/monomer_manifest.tsv"))


if __name__ == "__main__":
    unittest.main()
