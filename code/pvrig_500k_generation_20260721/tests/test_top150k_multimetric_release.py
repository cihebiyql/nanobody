from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ARCHIVE = load_module("aggregate_archived_nbb2_manifests", "scripts/aggregate_archived_nbb2_manifests.py")
BUILD = load_module("build_fixed_pose_top150k_multimetric_release", "scripts/build_fixed_pose_top150k_multimetric_release.py")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ArchiveManifestTests(unittest.TestCase):
    def test_collect_archive_adds_durable_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wave_00" / "archives_123"
            root.mkdir(parents=True)
            archive = root / "node_000.tar.gz"
            fields = [
                "candidate_id", "sequence_sha256", "pdb_relative_path", "pdb_sha256",
                "pdb_sequence_match", "worker_id", "status",
            ]
            payload = io.StringIO()
            writer = csv.DictWriter(payload, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow({
                "candidate_id": "C1", "sequence_sha256": "a" * 64,
                "pdb_relative_path": "C1.pdb", "pdb_sha256": "b" * 64,
                "pdb_sequence_match": "true", "worker_id": "0", "status": "SUCCESS",
            })
            data = payload.getvalue().encode()
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("node_000/raw/worker_00/manifest.tsv")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            (root / "node_000.sha256").write_text(f"{'c' * 64}  node_000.tar.gz\n")

            output_fields, rows = ARCHIVE.collect_archive(archive)
            self.assertIn("nbb2_archive_member", output_fields)
            self.assertEqual(rows[0]["nbb2_wave"], "wave_00")
            self.assertEqual(rows[0]["nbb2_archive_member"], "node_000/raw/worker_00/C1.pdb")
            self.assertEqual(rows[0]["nbb2_archive_sha256"], "c" * 64)


class MultimetricReleaseTests(unittest.TestCase):
    def build_fixture(self, root: Path, mismatch: bool = False) -> tuple[Path, Path, Path, Path]:
        sequence_hash = hashlib.sha256(b"SEQ").hexdigest()
        selection = root / "selection.tsv.gz"
        structure = root / "structure.tsv.gz"
        tnp = root / "tnp.tsv.gz"
        output = root / "output"
        write_tsv(selection, ["candidate_id", "sequence_sha256", "parent_cluster", "prestructure_hard_gate"], [{
            "candidate_id": "C1", "sequence_sha256": sequence_hash,
            "parent_cluster": "P1", "prestructure_hard_gate": "True",
        }])
        write_tsv(structure, ["candidate_id", "sequence_sha256", "status", "pdb_sequence_match", "pdb_sha256"], [{
            "candidate_id": "C1", "sequence_sha256": "f" * 64 if mismatch else sequence_hash,
            "status": "SUCCESS", "pdb_sequence_match": "true", "pdb_sha256": "e" * 64,
        }])
        write_tsv(tnp, [
            "candidate_id", "status", "cdr3_compactness", "psh", "ppc", "pnc",
            "red_flag_count", "amber_flag_count",
        ], [{
            "candidate_id": "C1", "status": "PASS", "cdr3_compactness": "1.2",
            "psh": "100", "ppc": "0.1", "pnc": "0.2",
            "red_flag_count": "1", "amber_flag_count": "2",
        }])
        return selection, structure, tnp, output

    def test_builds_release_without_inventing_surrogate_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            selection, structure, tnp, output = self.build_fixture(Path(tmp))
            argv = [
                "build", "--selection", str(selection), "--structure", str(structure),
                "--tnp", str(tnp), "--output-dir", str(output), "--expected", "1",
            ]
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(BUILD.main(), 0)
            receipt = json.loads((output / "READY.json").read_text())
            self.assertEqual(receipt["status"], "READY_PENDING_DOCKING_SURROGATE")
            self.assertEqual(receipt["tnp_review_tier_counts"], {"REVIEW": 1})
            with gzip.open(output / "fixed_pose_top150k_multimetric.tsv.gz", "rt", newline="") as handle:
                row = next(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(row["surrogate_prediction_status"], "PENDING_MODEL_READY")
            self.assertEqual(
                row["multimetric_model_coverage"],
                "sequence_descriptors;DeepNano;NanoBind;Sapiens;AbNatiV;ANARCI;NBB2;TNP;"
                "DockingSurrogate=PENDING_MODEL_READY",
            )
            self.assertNotIn("predicted_Rdual", row)

    def test_rejects_sequence_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            selection, structure, tnp, output = self.build_fixture(Path(tmp), mismatch=True)
            argv = [
                "build", "--selection", str(selection), "--structure", str(structure),
                "--tnp", str(tnp), "--output-dir", str(output), "--expected", "1",
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(ValueError, "sequence SHA256 mismatch"):
                    BUILD.main()


if __name__ == "__main__":
    unittest.main()
