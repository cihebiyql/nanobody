#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load("full10644_builder", ROOT / "src/build_full10644_structure_manifest_v1.py")
materializer = load("full10644_m2", ROOT / "src/materialize_full10644_m2_features_v1.py")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sequence_for(index: int) -> str:
    tail = "ACDE"[index]
    return "A" * 9 + "CDE" + "A" * 17 + "FGH" + "A" * 27 + "KLMN" + "A" * 37 + tail


def write_pdb(path: Path, residues: int = 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for residue in range(1, residues + 1):
        x = residue * 1.35
        y = (residue % 7) * 0.73
        z = (residue % 11) * 0.41
        lines.append(
            f"ATOM  {residue:5d}  CA  ALA A{residue:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00{90.0 + residue % 5:6.2f}           C\n"
        )
    path.write_text("".join(lines), encoding="ascii")


class Full10644StructureM2Tests(unittest.TestCase):
    def make_inputs(self, root: Path):
        teacher_rows = []
        assets = []
        for index, lane in enumerate(("v29", "v4i", "v4h", "v4d")):
            candidate = f"CAND_{lane.upper()}"
            sequence = sequence_for(index)
            pdb = root / lane / f"{candidate}.pdb"
            write_pdb(pdb)
            assets.append((lane, candidate, sequence, pdb))
            teacher_rows.append({
                "candidate_id": candidate,
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                "sequence": sequence,
                "parent_framework_cluster": f"C{index + 1:04d}",
                "cdr1": "CDE",
                "cdr2": "FGH",
                "cdr3": "KLMN",
                "teacher_source": f"SOURCE_{lane}",
                "R_8X6B": "INTENTIONALLY_NOT_NUMERIC",
                "R_9E6Y": "INTENTIONALLY_NOT_NUMERIC",
            })
        teacher = root / "teacher.tsv"
        write_tsv(teacher, teacher_rows)
        split = root / "split.json"
        split.write_text(json.dumps({
            "split_id": "unit",
            "train_parents": ["C0001", "C0003"],
            "score_parents": ["C0002", "C0004"],
        }), encoding="utf-8")

        source_args = []
        for lane, candidate, sequence, pdb in assets:
            seq_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            pdb_hash = sha_file(pdb)
            manifest = root / f"{lane}_manifest.tsv"
            if lane == "v29":
                rows = [{
                    "candidate_id": candidate, "sequence_sha256": seq_hash,
                    "monomer_status": "SUCCESS", "pdb_path": str(pdb), "pdb_sha256": pdb_hash,
                }]
            elif lane in {"v4i", "v4h"}:
                rows = [{
                    "candidate_id": candidate, "sequence_sha256": seq_hash,
                    "frozen_monomer_path": pdb.name, "sha256": pdb_hash,
                }]
            else:
                rows = [{
                    "candidate_id": candidate, "sequence_sha256": seq_hash,
                    "bundle_relative_path": pdb.name, "monomer_sha256": pdb_hash,
                    "monomer_source_chain": "A",
                }]
            write_tsv(manifest, rows)
            source_args.append((lane.upper(), lane, manifest, pdb.parent, sha_file(manifest)))
        return teacher, split, source_args

    def test_four_source_closure_and_m2_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            teacher, split, sources = self.make_inputs(root)
            manifest_dir = root / "manifest_output"
            result = builder.build(
                teacher, sha_file(teacher), split, sha_file(split), sources, manifest_dir, 4
            )
            self.assertEqual(result["rows"], 4)
            receipt = json.loads((manifest_dir / "canonical10644_structure_manifest_v1.receipt.json").read_text())
            self.assertEqual(receipt["counts"]["splits"], {"development": 2, "train": 2})
            self.assertEqual(receipt["invariants"]["numeric_geometry_target_columns_accessed"], 0)
            manifest = manifest_dir / "canonical10644_structure_manifest_v1.tsv"
            m2 = materializer.materialize(manifest, sha_file(manifest), manifest_dir, 4, 1)
            self.assertEqual(m2["rows"], 4)
            self.assertEqual(m2["features"], 126)
            with (manifest_dir / "canonical10644_m2_126d_features_v1.tsv").open() as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                rows = list(reader)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len([field for field in reader.fieldnames if "__" in field]), 126)

    def test_cdr_mapping_must_be_unique(self):
        with self.assertRaises(builder.ManifestError):
            builder.unique_cdr_ranges(
                "AAACDEAAACDEAAAFGHAAAKLMNAAA",
                {"cdr1": "CDE", "cdr2": "FGH", "cdr3": "KLMN"},
                "BAD",
            )

    def test_manifest_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            teacher, split, sources = self.make_inputs(root)
            bad = list(sources)
            lane, kind, manifest, asset_root, _ = bad[0]
            bad[0] = (lane, kind, manifest, asset_root, "0" * 64)
            with self.assertRaises(builder.ManifestError):
                builder.build(teacher, sha_file(teacher), split, sha_file(split), bad, root / "out", 4)


if __name__ == "__main__":
    unittest.main()
