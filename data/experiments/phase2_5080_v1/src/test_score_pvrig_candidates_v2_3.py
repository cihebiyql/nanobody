#!/usr/bin/env python3
"""Unit tests for the Phase 2 V2.3 PVRIG candidate ranking scorer."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_pvrig_candidates_v2_3 import (  # noqa: E402
    BOUNDARY_NOTE,
    SCHEMA_VERSION,
    load_model_from_checkpoint,
    parse_args,
    run_scoring,
    split_exclusions,
)
from train_phase2_v2_3 import CDRMaskStore, Config, CrossContactNetV23, ESM2Cache, seq_hash  # noqa: E402


class ScorePvrigCandidatesV23Tests(unittest.TestCase):
    def tiny_config(self) -> Config:
        return Config(
            root=".",
            out_root="experiments/phase2_5080_v1",
            esm2_cache_manifest="cache/manifest.csv",
            cdr_mask_csv="cdr_masks.csv",
            d_model=16,
            esm_dim=8,
            contact_dim=8,
            layers=1,
            cross_layers=1,
            heads=2,
            dropout=0.0,
            max_vhh_len=12,
            max_antigen_len=14,
        )

    def write_cache(self, root: Path, seqs: list[str], cfg: Config) -> Path:
        cache_dir = root / "cache"
        cache_dir.mkdir()
        shard = {}
        rows = []
        for idx, seq in enumerate(seqs):
            digest = seq_hash(seq)
            shard[digest] = torch.full((len(seq), cfg.esm_dim), float(idx + 1), dtype=torch.float32)
            rows.append(
                {
                    "sequence_sha256": digest,
                    "sequence_length": len(seq),
                    "cached_length": len(seq),
                    "truncation_policy": "none",
                    "shard_path": "shard_00000.pt",
                    "shard_key": digest,
                }
            )
        torch.save(shard, cache_dir / "shard_00000.pt")
        manifest = cache_dir / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return manifest

    def write_masks(self, root: Path, vhh_seq: str) -> Path:
        mask = [0, 1, 1, 0, 2, 2, 0, 3, 3]
        path = root / "cdr_masks.csv"
        pd.DataFrame(
            [
                {
                    "sequence_hash": seq_hash(vhh_seq),
                    "vhh_seq": vhh_seq,
                    "vhh_len": len(vhh_seq),
                    "cdr_mask_json": json.dumps(mask),
                    "status": "ok",
                }
            ]
        ).to_csv(path, index=False)
        return path

    def write_checkpoint(self, root: Path, cfg: Config) -> Path:
        torch.manual_seed(7)
        model = CrossContactNetV23(cfg)
        path = root / "checkpoint.pt"
        torch.save({"model": model.state_dict(), "cfg": cfg.__dict__, "epoch": 2, "best_score": 1.25}, path)
        return path

    def write_scoring_inputs(self, root: Path, vhh_seq: str, target_seq: str) -> tuple[Path, Path, Path, Path]:
        candidate_table = root / "mvp_candidates.csv"
        pd.DataFrame(
            [
                {"candidate_id": "cand_keep", "vhh_seq": vhh_seq, "candidate_role": "new_candidate", "source_leakage_label": ""},
                {"candidate_id": "cand_leak", "vhh_seq": vhh_seq, "candidate_role": "known_pvrig_blocking_positive_control_not_ranked", "source_leakage_label": "EXACT_KNOWN_POSITIVE"},
            ]
        ).to_csv(candidate_table, index=False)
        top = root / "top50.csv"
        pd.DataFrame([{"candidate_id": "cand_keep"}, {"candidate_id": "cand_leak"}]).to_csv(top, index=False)
        fasta = root / "target.fasta"
        fasta.write_text(f">pvrig_proxy\n{target_seq}\n", encoding="utf-8")
        output = root / "scores.csv"
        return candidate_table, top, fasta, output

    def test_cache_lookup_and_cdr_mask_store_use_sequence_hashes(self) -> None:
        cfg = self.tiny_config()
        vhh_seq = "ACDEFGHIK"
        target_seq = "LMNPQRST"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = self.write_cache(root, [vhh_seq, target_seq], cfg)
            mask_path = self.write_masks(root, vhh_seq)

            cache = ESM2Cache(manifest, cfg.esm_dim)
            masks = CDRMaskStore(mask_path)

            self.assertTrue(cache.has(vhh_seq))
            self.assertTrue(cache.has(target_seq))
            self.assertEqual(tuple(cache.get(vhh_seq, cfg.max_vhh_len).shape), (len(vhh_seq), cfg.esm_dim))
            self.assertEqual(masks.get(vhh_seq, cfg.max_vhh_len).tolist()[-2:], [3, 3])

    def test_known_positive_and_leakage_rows_are_excluded_before_ranking(self) -> None:
        df = pd.DataFrame(
            [
                {"candidate_id": "keep", "candidate_role": "new_candidate", "source_leakage_label": ""},
                {"candidate_id": "exact", "candidate_role": "new_candidate", "source_leakage_label": "EXACT_KNOWN_POSITIVE"},
                {"candidate_id": "role", "candidate_role": "mutant_or_leakage_control_not_ranked", "source_leakage_label": ""},
            ]
        )
        kept, excluded = split_exclusions(df)
        self.assertEqual(kept["candidate_id"].tolist(), ["keep"])
        self.assertEqual(set(excluded["candidate_id"]), {"exact", "role"})
        self.assertIn("exclusion_reason", excluded.columns)

    def test_checkpoint_smoke_loads_model_from_checkpoint_config(self) -> None:
        cfg = self.tiny_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            checkpoint = self.write_checkpoint(root, cfg)
            model, loaded_cfg, ckpt = load_model_from_checkpoint(checkpoint, None, torch.device("cpu"))
            self.assertIsInstance(model, CrossContactNetV23)
            self.assertEqual(loaded_cfg.esm_dim, cfg.esm_dim)
            self.assertEqual(int(ckpt["epoch"]), 2)

    def test_run_scoring_writes_schema_masks_exclusions_and_boundary(self) -> None:
        cfg = self.tiny_config()
        vhh_seq = "ACDEFGHIK"
        target_seq = "LMNPQRST"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = self.write_cache(root, [vhh_seq, target_seq], cfg)
            masks = self.write_masks(root, vhh_seq)
            checkpoint = self.write_checkpoint(root, cfg)
            candidate_table, top, fasta, output = self.write_scoring_inputs(root, vhh_seq, target_seq)

            args = parse_args(
                [
                    "--root",
                    str(root),
                    "--checkpoint",
                    str(checkpoint),
                    "--config",
                    "",
                    "--v2-2-top50",
                    str(top),
                    "--candidate-table",
                    str(candidate_table),
                    "--target-fasta",
                    str(fasta),
                    "--esm2-cache-manifest",
                    str(manifest),
                    "--cdr-mask-csv",
                    str(masks),
                    "--output",
                    str(output),
                    "--batch-size",
                    "2",
                    "--device",
                    "cpu",
                ]
            )
            result = run_scoring(args)
            scored = pd.read_csv(output)
            metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
            excluded = pd.read_csv(output.with_suffix(".excluded.csv"))

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored.loc[0, "schema_version"], SCHEMA_VERSION)
            self.assertEqual(scored.loc[0, "phase2_v2_3_boundary_note"], BOUNDARY_NOTE)
            self.assertIn("phase2_v2_3_pair_ranking_logit", scored.columns)
            self.assertIn("phase2_v2_3_sigmoid_pair_ranking_ai_prior", scored.columns)
            self.assertIn("phase2_v2_3_contact_hotspot_ai_prior_json", scored.columns)
            self.assertTrue(all("blocker_probability" not in col for col in scored.columns))
            self.assertEqual(metadata["ranked_candidates"], 1)
            self.assertEqual(metadata["excluded_candidates"], 1)
            self.assertEqual(excluded.loc[0, "candidate_id"], "cand_leak")
            hotspot = json.loads(scored.loc[0, "phase2_v2_3_contact_hotspot_ai_prior_json"])
            self.assertIn("top_pairs", hotspot)
            self.assertTrue(hotspot["top_pairs"])


if __name__ == "__main__":
    unittest.main()
