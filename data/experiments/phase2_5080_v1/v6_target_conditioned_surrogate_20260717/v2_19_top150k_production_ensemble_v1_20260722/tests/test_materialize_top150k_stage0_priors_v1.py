from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage0", ROOT / "src/materialize_top150k_stage0_priors_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class Stage0Tests(unittest.TestCase):
    def make_input(self, root: Path, rows: int = 5) -> Path:
        fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_id", "parent_cluster",
            "cdr1_after", "cdr2_after", "cdr3_after", "generator", "design_mode",
            "target_patch_assignment", "deepnano_binding_prior", "nanobind_binding_prior",
            "mean_self_probability", "AbNatiV VHH Score", "production_proxy_score",
            "binding_consensus_weak_prior", "prestructure_multimetric_score", "nbb2_status",
            "tnp_status", "tnp_review_tier", "tnp_red_flag_count", "tnp_amber_flag_count",
            "multimetric_hard_gate", "nbb2_pdb_sha256", "nbb2_nbb2_archive_path",
            "nbb2_nbb2_archive_member",
        ]
        path = root / "input.tsv.gz"
        with gzip.open(path, "wt", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(rows):
                sequence = "ACDEFGHIKLMNPQRSTVWY" + "A" * index
                value = (index + 1) / rows
                writer.writerow({
                    "candidate_id": f"c{index}", "sequence": sequence,
                    "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                    "parent_id": "p", "parent_cluster": f"p{index%2}",
                    "cdr1_after": "ACD", "cdr2_after": "EFG", "cdr3_after": "HIK",
                    "generator": "g", "design_mode": "m", "target_patch_assignment": "t",
                    "deepnano_binding_prior": value, "nanobind_binding_prior": value,
                    "mean_self_probability": value, "AbNatiV VHH Score": value,
                    "production_proxy_score": value, "binding_consensus_weak_prior": value,
                    "prestructure_multimetric_score": value, "nbb2_status": "SUCCESS",
                    "tnp_status": "PASS", "tnp_review_tier": "CLEAR",
                    "tnp_red_flag_count": 0, "tnp_amber_flag_count": 0,
                    "multimetric_hard_gate": "true", "nbb2_pdb_sha256": "f" * 64,
                    "nbb2_nbb2_archive_path": "/archive.tar.gz",
                    "nbb2_nbb2_archive_member": f"x/c{index}.pdb",
                })
        return path

    def test_materializes_deterministic_ranking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.make_input(root)
            args = MODULE.argparse.Namespace(
                input=source, expected_sha256=MODULE.sha256_file(source), output_dir=root/"out",
                expected_rows=5, broad_pool_rows=2,
            )
            receipt = MODULE.run(args)
            self.assertEqual(receipt["status"], "PASS_TOP150K_STAGE0_LABEL_FREE_PRIORS")
            with (root/"out/STAGE0_LABEL_FREE_PRIORS.tsv").open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["candidate_id"], "c4")
            self.assertEqual(sum(row["stage0_broad_pool"] == "true" for row in rows), 2)
            self.assertEqual(json.loads((root/"out/RUN_RECEIPT.json").read_text())["docking_truth_access_count"], 0)

    def test_rejects_sequence_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.make_input(root, 1)
            # Rebuild a corrupted single-row gzip rather than mutating compressed bytes.
            with gzip.open(source, "rt", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t"); rows = list(reader); fields = reader.fieldnames
            rows[0]["sequence_sha256"] = "0" * 64
            with gzip.open(source, "wt", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            args = MODULE.argparse.Namespace(input=source, expected_sha256=MODULE.sha256_file(source),
                output_dir=root/"out", expected_rows=1, broad_pool_rows=1)
            with self.assertRaisesRegex(MODULE.Stage0Error, "sequence_sha256_mismatch"):
                MODULE.run(args)


if __name__ == "__main__":
    unittest.main()
