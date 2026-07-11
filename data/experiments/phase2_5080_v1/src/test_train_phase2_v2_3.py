#!/usr/bin/env python3
"""Synthetic CPU tests for Phase 2 V2.3 training components."""
from __future__ import annotations

import csv
import json
import random
import tempfile
import unittest
from pathlib import Path
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_phase2_v2_3 import (  # noqa: E402
    Config,
    CDRMaskStore,
    CrossContactNetV23,
    ESM2Cache,
    PairDataset,
    RankingTripletDataset,
    observed_positive_bce,
    pairwise_ranking_loss,
    ranking_metrics,
    restore_resume_best_checkpoint,
    sample_contact_indices,
    seq_hash,
    validate_pair_labels,
)


class TrainPhase2V23Tests(unittest.TestCase):
    def tiny_config(self) -> Config:
        return Config(
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

    def test_model_shapes_from_cached_esm_and_cdr_types(self) -> None:
        torch.manual_seed(1)
        cfg = self.tiny_config()
        model = CrossContactNetV23(cfg).cpu()
        vhh = torch.randn(2, 7, cfg.esm_dim)
        antigen = torch.randn(2, 9, cfg.esm_dim)
        cdr = torch.tensor([[0, 1, 1, 0, 2, 3, 0], [0, 1, 0, 2, 2, 3, 3]], dtype=torch.long)

        hv, ha, v_mask, a_mask = model.encode(vhh, cdr, antigen)
        paratope, epitope = model.site_logits(hv, ha)
        contacts = model.contact_logits(hv, ha)
        pair = model.pair_logits_from_encoded(hv, ha, v_mask, a_mask, cdr)

        self.assertEqual(tuple(hv.shape), (2, 7, cfg.d_model))
        self.assertEqual(tuple(ha.shape), (2, 9, cfg.d_model))
        self.assertEqual(tuple(paratope.shape), (2, 7))
        self.assertEqual(tuple(epitope.shape), (2, 9))
        self.assertEqual(tuple(contacts.shape), (2, 7, 9))
        self.assertEqual(tuple(pair.shape), (2,))

    def test_observed_label_masking_excludes_constructed_rows_from_bce(self) -> None:
        logits = torch.tensor([0.0, -10.0, 10.0], requires_grad=True)
        labels = torch.tensor([1.0, 0.0, 0.0])
        mask = torch.tensor([True, False, False])

        loss = observed_positive_bce(logits, labels, mask)
        self.assertAlmostEqual(float(loss.detach()), float(torch.nn.functional.binary_cross_entropy_with_logits(logits[:1], torch.ones(1)).detach()), places=6)
        loss.backward()
        self.assertNotEqual(float(logits.grad[0]), 0.0)
        self.assertEqual(float(logits.grad[1]), 0.0)
        self.assertEqual(float(logits.grad[2]), 0.0)

        with self.assertRaises(ValueError):
            validate_pair_labels([
                {"pair_id": "constructed_neg", "binding_label": 0, "label_state": "constructed_negative", "ordinary_bce_eligible": "yes"}
            ])

    def test_ranking_loss_direction_rewards_positive_above_negative(self) -> None:
        good = pairwise_ranking_loss(torch.tensor([2.0, 3.0]), torch.tensor([0.0, 1.0]), margin=0.25)
        bad = pairwise_ranking_loss(torch.tensor([0.0, 1.0]), torch.tensor([2.0, 3.0]), margin=0.25)
        self.assertLess(float(good), float(bad))

    def test_ranking_metrics_report_mrr_hits_ndcg_and_hard_win_rate(self) -> None:
        groups = {
            "g1": [(0.9, 1, "positive"), (0.2, 0, "N2_same_family_hard_antigen"), (0.1, 0, "N1_easy")],
            "g2": [(0.4, 1, "positive"), (0.8, 0, "N2_same_family_hard_antigen"), (0.1, 0, "N1_easy")],
        }
        metrics = ranking_metrics(groups)

        self.assertAlmostEqual(metrics["ranking_mrr"], (1.0 + 0.5) / 2.0)
        self.assertAlmostEqual(metrics["ranking_hit_at_1"], 0.5)
        self.assertAlmostEqual(metrics["ranking_hit_at_5"], 1.0)
        self.assertAlmostEqual(metrics["ranking_hit_at_10"], 1.0)
        self.assertGreater(metrics["ranking_ndcg_at_10"], 0.0)
        self.assertAlmostEqual(metrics["ranking_hard_negative_win_rate"], 0.5)

    def test_esm_cache_accepts_prefix_cached_length_policy(self) -> None:
        full_seq = "ACDEFGHI"
        digest = seq_hash(full_seq)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            torch.save({digest: torch.ones((5, 8), dtype=torch.float16)}, root / "shard_00000.pt")
            with (root / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["sequence_sha256", "sequence_length", "cached_length", "truncation_policy", "shard_path", "shard_key"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "sequence_sha256": digest,
                        "sequence_length": 8,
                        "cached_length": 5,
                        "truncation_policy": "explicit_prefix_1024",
                        "shard_path": "shard_00000.pt",
                        "shard_key": digest,
                    }
                )

            cache = ESM2Cache(root / "manifest.csv", expected_dim=8)
            tensor = cache.get(full_seq, max_len=7)
            self.assertEqual(tuple(tensor.shape), (5, 8))

    def test_ranking_proxy_does_not_update_contact_head(self) -> None:
        torch.manual_seed(7)
        cfg = self.tiny_config()
        model = CrossContactNetV23(cfg).cpu()
        vhh = torch.randn(2, 7, cfg.esm_dim)
        antigen = torch.randn(2, 9, cfg.esm_dim)
        cdr = torch.tensor([[0, 1, 1, 0, 2, 3, 0], [0, 1, 0, 2, 2, 3, 3]], dtype=torch.long)

        model.pair_logits(vhh, cdr, antigen).sum().backward()

        for module in (model.q, model.k, model.contact_bias_v, model.contact_bias_a):
            for parameter in module.parameters():
                self.assertTrue(parameter.grad is None or torch.count_nonzero(parameter.grad) == 0)

    def test_contact_eval_sampling_can_be_reproduced(self) -> None:
        cfg = self.tiny_config()
        cfg.contact_pos_sample = 2
        cfg.contact_neg_sample = 3
        batch = {
            "pos": [[(0, i) for i in range(8)]],
            "neg": [[(1, i) for i in range(10)]],
        }
        first = sample_contact_indices(batch, cfg, torch.device("cpu"), random.Random(19))
        second = sample_contact_indices(batch, cfg, torch.device("cpu"), random.Random(19))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(first, second)))

    def test_unresolved_cdr_rows_are_excluded_from_pair_tasks(self) -> None:
        good = "ACDE"
        bad = "FGHI"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cdr_path = root / "cdr.csv"
            with cdr_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sequence_hash", "vhh_len", "cdr_mask_json", "status"])
                writer.writeheader()
                writer.writerow({"sequence_hash": seq_hash(good), "vhh_len": 4, "cdr_mask_json": json.dumps([0, 1, 3, 0]), "status": "exact_annotation"})
                writer.writerow({"sequence_hash": seq_hash(bad), "vhh_len": 4, "cdr_mask_json": json.dumps([0, 0, 0, 0]), "status": "unresolved"})
            pair_path = root / "pair.csv"
            pair_path.write_text(
                "split,pair_id,vhh_seq,antigen_seq,label_state,ordinary_bce_eligible,binding_label,contrastive_target\n"
                f"train,p1,{good},AAAA,observed_positive,yes,1,1\n"
                f"train,p2,{bad},AAAA,unlabeled_contrastive,no,,0\n",
                encoding="utf-8",
            )
            rank_path = root / "rank.csv"
            rank_path.write_text(
                "split,ranking_group_id,negative_type,positive_pair_id,negative_pair_id,positive_vhh_seq,positive_antigen_seq,negative_vhh_seq,negative_antigen_seq\n"
                f"train,g1,N1,p1,p2,{good},AAAA,{bad},AAAA\n",
                encoding="utf-8",
            )
            cdrs = CDRMaskStore(cdr_path)
            cfg = self.tiny_config()
            pair = PairDataset(pair_path, "train", cfg, object(), cdrs)  # type: ignore[arg-type]
            rank = RankingTripletDataset(rank_path, "train", cfg, object(), cdrs)  # type: ignore[arg-type]
            self.assertEqual(len(pair), 1)
            self.assertEqual(pair.excluded_unresolved_cdr_rows, 1)
            self.assertEqual(len(rank), 0)
            self.assertEqual(rank.excluded_unresolved_cdr_rows, 1)

    def test_resume_restores_prior_best_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            resume = old / "last_checkpoint.pt"
            sibling_best = old / "best_checkpoint.pt"
            resume_ckpt = {"model": {"weight": torch.tensor([1.0])}, "best_score": 1.0}
            best_ckpt = {"model": {"weight": torch.tensor([2.0])}, "best_score": 2.0}
            torch.save(resume_ckpt, resume)
            torch.save(best_ckpt, sibling_best)

            restored, source = restore_resume_best_checkpoint(resume, resume_ckpt, new / "best_checkpoint.pt", torch.device("cpu"))

            self.assertEqual(source, sibling_best.resolve())
            self.assertEqual(float(restored["best_score"]), 2.0)
            copied = torch.load(new / "best_checkpoint.pt", map_location="cpu", weights_only=False)
            self.assertEqual(float(copied["model"]["weight"][0]), 2.0)


if __name__ == "__main__":
    unittest.main()
