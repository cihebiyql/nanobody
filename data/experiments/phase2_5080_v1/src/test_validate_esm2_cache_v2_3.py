#!/usr/bin/env python3
"""Unit tests for the exhaustive V2.3 frozen ESM2 cache validator."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_esm2_cache_v2_3 import validate_cache  # noqa: E402


class ValidateEsm2CacheV23Tests(unittest.TestCase):
    def _write_cache(self, root: Path, tensor: torch.Tensor, *, policy: str = "none") -> Path:
        digest = "a" * 64
        torch.save({digest: tensor}, root / "shard_00000.pt")
        manifest = root / "manifest.csv"
        manifest.write_text(
            "model_path,model_sha256,sequence_sha256,sequence_length,cached_length,truncation_policy,chain_type,shard_path,shard_key\n"
            f"/model,modelhash,{digest},{tensor.shape[0]},{tensor.shape[0]},{policy},vhh,shard_00000.pt,{digest}\n",
            encoding="utf-8",
        )
        return manifest

    def test_valid_cache_checks_every_tensor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._write_cache(Path(tmpdir), torch.ones((4, 3), dtype=torch.float16))
            summary = validate_cache(manifest, expected_dim=3)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["manifest_rows"], 1)
            self.assertEqual(summary["validated_tensor_keys"], 1)
            self.assertEqual(summary["dtype_counts"], {"torch.float16": 1})

    def test_shape_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._write_cache(Path(tmpdir), torch.ones((4, 2)))
            with self.assertRaisesRegex(ValueError, "tensor shape"):
                validate_cache(manifest, expected_dim=3)

    def test_invalid_truncation_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._write_cache(Path(tmpdir), torch.ones((4, 3)), policy="prefix_4")
            with self.assertRaisesRegex(ValueError, "truncation_policy"):
                validate_cache(manifest, expected_dim=3)

    def test_duplicate_sequence_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = self._write_cache(root, torch.ones((4, 3)))
            line = manifest.read_text(encoding="utf-8").splitlines()[1]
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate sequence_sha256"):
                validate_cache(manifest, expected_dim=3)


if __name__ == "__main__":
    unittest.main()
