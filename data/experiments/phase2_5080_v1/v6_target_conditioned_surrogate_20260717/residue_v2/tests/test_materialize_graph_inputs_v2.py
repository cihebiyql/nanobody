import csv
import hashlib
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_residue_graph_cache_v2 as graph_mod
import materialize_graph_inputs_v2 as mod


THREE = {value: key for key, value in graph_mod.THREE_TO_ONE.items()}


def pdb_payload(sequence):
    lines = []
    serial = 1
    for number, aa in enumerate(sequence, start=1):
        ca_x = 3.8 * (number - 1)
        for atom, delta, local_y in (("N", -1.2, 0.45), ("CA", 0.0, 0.0), ("C", 1.3, 0.25)):
            x, y, z = ca_x + delta, 0.4 * (number % 2) + local_y, 0.2 * number
            lines.append(
                f"ATOM  {serial:5d} {atom:>4s} {THREE[aa]:>3s} A{number:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{85.0:6.2f}          {atom[0]:>2s}\n"
            )
            serial += 1
    return ("".join(lines) + "END\n").encode()


def write_tsv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class TestMaterializeGraphInputsV2(unittest.TestCase):
    def fixture(self, root):
        sequence_d = "ACDEFGHIKLMN"
        sequence_h = "PQRSTVWYACDE"
        records = []
        for candidate, sequence, parent, source in (
            ("D1", sequence_d, "PD", mod.SOURCE_V4D),
            ("H1", sequence_h, "PH", mod.SOURCE_V4H),
        ):
            payload = pdb_payload(sequence)
            records.append({
                "candidate_id": candidate,
                "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "parent_framework_cluster": parent,
                "teacher_source": source,
                "monomer_sha256": hashlib.sha256(payload).hexdigest(),
                "cdr1": sequence[1:3], "cdr2": sequence[4:6], "cdr3": sequence[7:10],
            })
        training = root / "training.tsv"
        write_tsv(training, list(records[0]), records)

        v4h_root = root / "v4h"
        (v4h_root / "pdb_bundle_v1").mkdir(parents=True)
        h_payload = pdb_payload(sequence_h)
        (v4h_root / "pdb_bundle_v1" / "H1.pdb").write_bytes(h_payload)
        v4h_manifest = v4h_root / "manifest.tsv"
        v4h_fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
            "monomer_relative_path", "monomer_sha256", "source_chain", "claim_boundary",
        ]
        write_tsv(v4h_manifest, v4h_fields, [{
            "candidate_id": "H1", "sequence": sequence_h,
            "sequence_sha256": hashlib.sha256(sequence_h.encode()).hexdigest(),
            "parent_framework_cluster": "PH", "monomer_relative_path": "pdb_bundle_v1/H1.pdb",
            "monomer_sha256": hashlib.sha256(h_payload).hexdigest(), "source_chain": "A",
            "claim_boundary": "Label-free VHH monomer; no Docking Gold.",
        }])

        v4d_archive = root / "v4d.tar.gz"
        d_payload = pdb_payload(sequence_d)
        manifest_rows = [{
            "candidate_id": "D1", "sequence_sha256": hashlib.sha256(sequence_d.encode()).hexdigest(),
            "model_split": "OPEN_TRAIN", "parent_framework_cluster": "PD",
            "bundle_relative_path": "outputs/monomers/D1.pdb",
            "monomer_sha256": hashlib.sha256(d_payload).hexdigest(), "monomer_source_chain": "A",
            "claim_boundary": "Label-free frozen VHH monomer; no Docking Gold.",
        }, {
            "candidate_id": "DEV1", "sequence_sha256": "0" * 64,
            "model_split": "OPEN_DEVELOPMENT", "parent_framework_cluster": "PDEV",
            "bundle_relative_path": "outputs/monomers/DEV1.pdb", "monomer_sha256": "0" * 64,
            "monomer_source_chain": "A", "claim_boundary": "Label-free; no Docking Gold.",
        }]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(manifest_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest_rows)
        with tarfile.open(v4d_archive, "w:gz") as archive:
            for name, payload in (
                (mod.V4D_MANIFEST_MEMBER, buffer.getvalue().encode()),
                ("outputs/monomers/D1.pdb", d_payload),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return training, v4d_archive, v4h_manifest, v4h_root

    def test_unique_ordered_cdr_substrings(self):
        regions, ranges = mod.derive_cdr_region_indices("ACDEFGHIKLMN", "CD", "FG", "IKL")
        self.assertEqual(ranges, {"cdr1_range": "2-3", "cdr2_range": "5-6", "cdr3_range": "8-10"})
        self.assertEqual(regions[1:3], [1, 1])
        self.assertEqual(regions[4:6], [2, 2])
        self.assertEqual(regions[7:10], [3, 3, 3])
        with self.assertRaisesRegex(mod.GraphInputMaterializationError, "not_unique"):
            mod.derive_cdr_region_indices("ACACDEFG", "AC", "DE", "FG")

    def test_dry_run_closes_sources_parents_sequences_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, archive, manifest, v4h_root = self.fixture(root)
            output = root / "must_not_exist"
            receipt = mod.materialize_supervised_graph_inputs(
                training_table=training, v4d_archive=archive, v4h_manifest=manifest,
                v4h_structure_root=v4h_root, output_dir=output, dry_run=True,
                expected_source_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
                expected_parent_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
            )
            self.assertEqual(receipt["status"], "PASS_DRY_RUN_SUPERVISED_GRAPH_INPUTS")
            self.assertEqual(receipt["counts"]["candidates"], 2)
            self.assertEqual(receipt["sealed_boundary"]["open_development_candidates_emitted"], 0)
            self.assertFalse(output.exists())

    def test_formal_cache_has_exact_candidate_and_hash_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, archive, manifest, v4h_root = self.fixture(root)
            output = root / "cache"
            receipt = mod.materialize_supervised_graph_inputs(
                training_table=training, v4d_archive=archive, v4h_manifest=manifest,
                v4h_structure_root=v4h_root, output_dir=output, dry_run=False,
                expected_source_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
                expected_parent_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
            )
            arrays, graph_rows, _ = graph_mod.load_graph_cache(output)
            self.assertEqual(receipt["status"], "PASS_SUPERVISED_GRAPH_INPUTS_MATERIALIZED")
            self.assertEqual({row["entity_id"] for row in graph_rows}, {"D1", "H1"})
            with (output / mod.CLOSURE_NAME).open(newline="", encoding="utf-8") as handle:
                closure = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual({row["candidate_id"] for row in closure}, {"D1", "H1"})
            self.assertNotIn("teacher_source", arrays)
            self.assertNotIn("teacher_source", graph_rows[0])
            self.assertTrue((output / mod.SHA256SUMS_NAME).is_file())
            on_disk = json.loads((output / mod.MATERIALIZATION_RECEIPT).read_text())
            self.assertEqual(on_disk["outputs"], receipt["outputs"])

    def test_parent_or_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, archive, manifest, v4h_root = self.fixture(root)
            with manifest.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            rows[0]["parent_framework_cluster"] = "WRONG"
            write_tsv(manifest, list(rows[0]), rows)
            output = root / "cache"
            with self.assertRaisesRegex(mod.GraphInputMaterializationError, "v4h_parent_mismatch"):
                mod.materialize_supervised_graph_inputs(
                    training_table=training, v4d_archive=archive, v4h_manifest=manifest,
                    v4h_structure_root=v4h_root, output_dir=output, dry_run=False,
                    expected_source_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
                    expected_parent_counts={mod.SOURCE_V4D: 1, mod.SOURCE_V4H: 1},
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
