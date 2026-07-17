import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("extract_phase2_v4_h_research1320_structure_features_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_features", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pdb(path: Path, count: int = 100) -> None:
    lines = []
    for residue in range(1, count + 1):
        x, y, z = 3.7 * residue, 5.0 * np.sin(residue / 6.0), 4.0 * np.cos(residue / 8.0)
        lines.append(
            f"ATOM  {residue:5d}  CA  GLY A{residue:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00{0.80:6.2f}           C  \n"
        )
    path.write_text("".join(lines) + "END\n", encoding="ascii")


class V4HFeatureTests(unittest.TestCase):
    def fixture(self, root: Path):
        input_root = root / "inputs"
        bundle = input_root / "pdb_bundle_v1"
        bundle.mkdir(parents=True)
        pdb = bundle / "C1.pdb"
        write_pdb(pdb)
        sequence = list("A" * 100)
        for start, fragment in ((9, "CDEFG"), (34, "HIKLMN"), (74, "PQRSTVWY")):
            sequence[start:start + len(fragment)] = fragment
        sequence = "".join(sequence)
        sequence_sha = hashlib.sha256(sequence.encode()).hexdigest()
        input_manifest = input_root / "research1320_structure_inputs_v1.tsv"
        input_fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
            "target_patch_id", "design_mode", "monomer_relative_path", "monomer_sha256", "source_chain",
        ]
        with input_manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=input_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerow({
                "candidate_id":"C1", "sequence":sequence, "sequence_sha256":sequence_sha,
                "parent_framework_cluster":"P1", "target_patch_id":"A_CENTER", "design_mode":"H3",
                "monomer_relative_path":"pdb_bundle_v1/C1.pdb", "monomer_sha256":sha(pdb), "source_chain":"A",
            })
        receipt = {
            "status":"PASS_LABEL_FREE_STRUCTURE_INPUTS_MATERIALIZED",
            "output_manifest_sha256":sha(input_manifest),
            "forbidden_path_channels_opened":{"results":0,"status":0,"pose":0,"test32":0},
        }
        (input_root / "MATERIALIZATION_RECEIPT_V1.json").write_text(json.dumps(receipt))
        candidate = root / "candidates.tsv"
        candidate_fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
            "target_patch_id", "design_mode", "cdr1_after", "cdr2_after", "cdr3_after",
        ]
        with candidate.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=candidate_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerow({
                "candidate_id":"C1", "sequence":sequence, "sequence_sha256":sequence_sha,
                "parent_framework_cluster":"P1", "target_patch_id":"A_CENTER", "design_mode":"H3",
                "cdr1_after":"CDEFG", "cdr2_after":"HIKLMN", "cdr3_after":"PQRSTVWY",
            })
        return input_root, candidate, input_manifest

    def test_unique_ranges_are_one_based(self):
        candidate = {"sequence":"AAAACDEFGAAAAHIKLMNAAAAPQRSTVWY", "cdr1_after":"CDEFG", "cdr2_after":"HIKLMN", "cdr3_after":"PQRSTVWY"}
        self.assertEqual(module.derive_cdr_ranges(candidate), {"CDR1":"5-9", "CDR2":"14-19", "CDR3":"24-31"})

    def test_duplicate_fragment_fails(self):
        with self.assertRaisesRegex(module.FeatureError, "cdr_fragment_not_unique"):
            module.unique_sequence_range("AAACDEFGAAACDEFG", "CDEFG", "CDR1")

    def test_end_to_end_one_row_emits_126_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root, candidate, input_manifest = self.fixture(root)
            output = root / "output"
            result = module.extract(
                input_root, candidate, output,
                expected_input_manifest_sha256=sha(input_manifest),
                expected_candidate_manifest_sha256=sha(candidate), expected_rows=1,
            )
            self.assertEqual(result["row_count"], 1)
            self.assertEqual(result["feature_count"], 126)
            self.assertEqual(result["geometry_label_values_read"], 0)

    def test_manifest_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root, candidate, _input_manifest = self.fixture(root)
            with self.assertRaisesRegex(module.FeatureError, "structure_input_manifest_hash_mismatch"):
                module.extract(input_root, candidate, root / "output", expected_input_manifest_sha256="0" * 64, expected_candidate_manifest_sha256=sha(candidate), expected_rows=1)


if __name__ == "__main__":
    unittest.main()
