#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_phase2_v3_embeddings import (  # noqa: E402
    chunk_sequence,
    deterministic_hash_embedding,
    length_aware_batches,
    prepare_embeddings,
)


class Phase2V3EmbeddingTests(unittest.TestCase):
    def args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            sequence_manifest=root / "sequences.csv",
            output_dir=root / "embeddings",
            backend="hash",
            device="cpu",
            vhhbert_model_path=root / "vhhbert",
            esm2_model_path=root / "esm2",
            vhhbert_state_path=root / "state.pt",
            safetensors_package_dir=root / "missing",
            vhhbert_batch_size=2,
            esm_batch_size=2,
            shard_size=2,
            max_esm_residues=10,
            chunk_overlap=0,
            hash_vhhbert_dim=6,
            hash_esm2_dim=4,
        )

    def test_chunking_is_deterministic_and_complete_without_overlap(self) -> None:
        chunks = chunk_sequence("ABCDEFGHIJKLM", 5, 0)
        self.assertEqual(chunks, ["ABCDE", "FGHIJ", "KLM"])
        self.assertEqual("".join(chunks), "ABCDEFGHIJKLM")

    def test_hash_embedding_is_deterministic(self) -> None:
        left = deterministic_hash_embedding("AAAA", 7, "x")
        right = deterministic_hash_embedding("AAAA", 7, "x")
        other = deterministic_hash_embedding("AAAC", 7, "x")
        self.assertTrue(torch.equal(left, right))
        self.assertFalse(torch.equal(left, other))

    def test_length_aware_batches_isolate_long_antigens(self) -> None:
        batches = length_aware_batches([120] * 300 + [400] * 40 + [1000] * 5, 256)
        self.assertTrue(all(len(batch) <= 256 for batch in batches if max(batch) < 300))
        long_batches = [batch for batch in batches if any(index >= 340 for index in batch)]
        self.assertTrue(all(len(batch) <= 2 for batch in long_batches))

    def test_hash_cache_resumes_and_masks_antigen_vhhbert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(
                [
                    {"sequence_sha256": "a", "sequence": "QVQL" + "A" * 96, "sequence_length": 100, "roles": "vhh"},
                    {"sequence_sha256": "b", "sequence": "C" * 30, "sequence_length": 30, "roles": "antigen"},
                    {"sequence_sha256": "c", "sequence": "D" * 30, "sequence_length": 30, "roles": "antigen"},
                ]
            ).to_csv(root / "sequences.csv", index=False)
            args = self.args(root)
            first = prepare_embeddings(args)
            second = prepare_embeddings(args)
            self.assertEqual(first["created_shards"], 2)
            self.assertEqual(second["reused_shards"], 2)
            manifest = pd.read_csv(root / "embeddings/embedding_manifest_v3.csv")
            row = manifest.loc[manifest["sequence_sha256"] == "b"].iloc[0]
            shard = torch.load(row["shard_path"], map_location="cpu", weights_only=False)
            index = int(row["shard_index"])
            self.assertFalse(bool(shard["vhhbert_available"][index]))
            self.assertEqual(float(shard["vhhbert"][index].abs().sum()), 0.0)


if __name__ == "__main__":
    unittest.main()
