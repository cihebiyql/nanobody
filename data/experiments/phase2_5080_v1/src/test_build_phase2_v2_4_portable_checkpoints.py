#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_4_portable_checkpoints import CHECKPOINT_SCHEMA, build_portable_set, file_sha256


class BuildPhase2V24PortableCheckpointsTests(unittest.TestCase):
    def test_portable_set_preserves_model_state_and_selects_best_validation_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = {}
            for seed, score in ((43, 1.0), (53, 2.0), (67, 1.5)):
                source = root / f"run_seed{seed}.pt"
                torch.save({
                    "schema_version": CHECKPOINT_SCHEMA,
                    "cfg": {"seed": seed, "root": "/tmp/runtime", "esm2_cache_manifest": "/tmp/cache/manifest.csv"},
                    "model": {"weight": torch.tensor([seed, score])},
                    "warmstart": {"status": "loaded", "source": f"/tmp/v2_3_seed{seed}.pt"},
                    "epoch": 1,
                    "best_score": score,
                }, source)
                sources[seed] = source
            output_dir = root / "checkpoints"
            canonical = output_dir / "phase2_v2_4_best_checkpoint.pt"
            result = build_portable_set(sources, output_dir, canonical, root / "audit.json")

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["canonical_seed"], 53)
            self.assertTrue(result["canonical_matches_selected_portable_sha256"])
            self.assertEqual(file_sha256(canonical), file_sha256(output_dir / "phase2_v2_4_strict_seed53_best_checkpoint.pt"))
            payload = torch.load(output_dir / "phase2_v2_4_strict_seed43_best_checkpoint.pt", map_location="cpu", weights_only=False)
            self.assertEqual(payload["cfg"]["root"], ".")
            self.assertNotIn("/tmp", payload["cfg"]["esm2_cache_manifest"])
            self.assertTrue(payload["portability"]["model_state_unchanged"])


if __name__ == "__main__":
    unittest.main()
