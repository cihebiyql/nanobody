import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


MODULE_PATH = Path(__file__).with_name("score_phase2_v4_h_research1320_sequence_surrogate_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_sequence_scorer", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SequenceScorerTests(unittest.TestCase):
    def fixture(self, root: Path, *, sequence_alpha: float = 1000.0):
        candidates = root / "candidates.tsv"
        candidate_rows = []
        sequences = ["A" * 100, "C" * 100, "D" * 100]
        hashes = [hashlib.sha256(value.encode("ascii")).hexdigest() for value in sequences]
        with candidates.open("w", newline="") as handle:
            fields = ["candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, (sequence, sequence_hash) in enumerate(zip(sequences, hashes)):
                row = {
                    "candidate_id": f"C{index}", "sequence": sequence, "sequence_sha256": sequence_hash,
                    "parent_framework_cluster": f"P{index}", "target_patch_id": "A", "design_mode": "H3",
                }
                writer.writerow(row)
                candidate_rows.append(row)
        order = sorted(range(3), key=lambda index: hashes[index])
        sorted_hashes = [hashes[index] for index in order]
        sequence_manifest = root / "sequence_manifest.csv"
        with sequence_manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sequence_sha256", "sequence", "sequence_length", "roles"], lineterminator="\n")
            writer.writeheader()
            for index in order:
                writer.writerow({"sequence_sha256": hashes[index], "sequence": sequences[index], "sequence_length":100, "roles":"vhh"})
        embedding_manifest = root / "embedding_manifest.csv"
        summary_config = {"backend":"real", "vhhbert_dim":768, "esm2_dim":320, "physchem_dim":27}
        embedding_config_sha = module.sha256_text(json.dumps(summary_config, separators=(",", ":"), sort_keys=True))
        with embedding_manifest.open("w", newline="") as handle:
            fields = ["sequence_sha256", "sequence_length", "roles", "shard_path", "shard_index", "esm2_dim", "vhhbert_dim", "physchem_dim", "config_sha256"]
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for position, index in enumerate(order):
                writer.writerow({
                    "sequence_sha256": hashes[index], "sequence_length":100, "roles":"vhh", "shard_path":"shard.pt",
                    "shard_index":position, "esm2_dim":320, "vhhbert_dim":768, "physchem_dim":27,
                    "config_sha256":embedding_config_sha,
                })
        shard = root / "shard.pt"
        vhhbert = torch.zeros((3, 768), dtype=torch.float32)
        esm2 = torch.zeros((3, 320), dtype=torch.float32)
        physchem = torch.zeros((3, 27), dtype=torch.float32)
        for position in range(3):
            vhhbert[position, 0] = float(position)
        shard_config = module.sha256_text(json.dumps(
            {"config":summary_config, "sequence_sha256":sorted_hashes}, separators=(",", ":"), sort_keys=True
        ))
        torch.save({
            "schema_version":"x", "config_sha256":shard_config, "sequence_sha256":sorted_hashes,
            "vhhbert":vhhbert, "esm2":esm2, "physchem":physchem,
            "vhhbert_available":torch.ones(3, dtype=torch.bool),
        }, shard)
        summary = root / "summary.json"
        summary.write_text(json.dumps({
            "sequence_count":3, "vhh_sequence_count":3, "antigen_sequence_count":0,
            "device":"cuda", "cuda_device_name":"NVIDIA GeForce RTX 5080",
            "config":summary_config, "config_sha256":embedding_config_sha,
            "sequence_manifest_sha256":sha(sequence_manifest), "embedding_manifest_sha256":sha(embedding_manifest),
        }))
        config = root / "config.json"
        config.write_text(json.dumps({
            "fit_rows":226, "primary_target":"R_dual_min", "open_development_target_values_accessed":0,
            "V4_F_test32_labels_accessed":0, "feature_dimensions":{"sequence":1115},
            "full_train_hyperparameters":{"sequence_alpha":sequence_alpha},
        }))
        fits = root / "fits.npz"
        coefficient = np.zeros(1115); coefficient[0] = 1.0
        np.savez(fits,
            M1_sequence__intercept=np.asarray([0.5]), M1_sequence__coefficient=coefficient,
            M1_sequence__center=np.zeros(1115), M1_sequence__scale=np.ones(1115),
        )
        return candidates, sequence_manifest, embedding_manifest, summary, shard, config, fits, embedding_config_sha

    def run_score(self, root: Path, *, sequence_alpha: float = 1000.0):
        paths = self.fixture(root, sequence_alpha=sequence_alpha)
        candidates, sequence_manifest, embedding_manifest, summary, shard, config, fits, embedding_config_sha = paths
        result = module.score(
            candidates, sequence_manifest, embedding_manifest, summary, shard, config, fits, root / "out",
            expected_candidate_sha256=sha(candidates),
            expected_sequence_manifest_sha256=sha(sequence_manifest),
            expected_embedding_manifest_sha256=sha(embedding_manifest),
            expected_embedding_summary_sha256=sha(summary),
            expected_embedding_shard_sha256=sha(shard),
            expected_embedding_config_sha256=embedding_config_sha,
            expected_config_sha256=sha(config), expected_fit_sha256=sha(fits), expected_rows=3,
        )
        return result

    def test_scores_sequence_model_in_embedding_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_score(root)
            self.assertEqual(result["row_count"], 3)
            with (root / "out/v4h_research1320_sequence_surrogate_ranking_v1.tsv").open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([float(row["predicted_R_dual_min_sequence_only"]) for row in rows], [2.5, 1.5, 0.5])
            self.assertEqual(result["V4_H_geometry_labels_accessed"], 0)

    def test_rejects_unfrozen_sequence_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(module.ScoringError, "sequence_alpha_invalid"):
                self.run_score(Path(directory), sequence_alpha=100.0)

    def test_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            candidates, sequence_manifest, embedding_manifest, summary, shard, config, fits, embedding_config_sha = paths
            with self.assertRaisesRegex(module.ScoringError, "candidate_table_hash_mismatch"):
                module.score(
                    candidates, sequence_manifest, embedding_manifest, summary, shard, config, fits, root / "out",
                    expected_candidate_sha256="0" * 64,
                    expected_sequence_manifest_sha256=sha(sequence_manifest),
                    expected_embedding_manifest_sha256=sha(embedding_manifest),
                    expected_embedding_summary_sha256=sha(summary),
                    expected_embedding_shard_sha256=sha(shard),
                    expected_embedding_config_sha256=embedding_config_sha,
                    expected_config_sha256=sha(config), expected_fit_sha256=sha(fits), expected_rows=3,
                )


if __name__ == "__main__":
    unittest.main()
