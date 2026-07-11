#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_phase2_v2_3 import seq_hash  # noqa: E402
from train_phase2_v2_4 import (  # noqa: E402
    Config,
    CrossContactNetV24,
    RankingGroupDataset,
    collate_rank_groups,
    listwise_group_ranking_loss,
    load_v23_warmstart,
    random_ranking_baselines,
    typed_pairwise_margin_loss,
)


class FakeCache:
    def __init__(self, dim: int):
        self.dim = dim

    def get(self, sequence: str, max_len: int) -> torch.Tensor:
        return torch.ones((min(len(sequence), max_len), self.dim), dtype=torch.float32)


class FakeCDR:
    def has_cdr3(self, sequence: str) -> bool:
        return not sequence.startswith("X")

    def get(self, sequence: str, max_len: int) -> torch.Tensor:
        length = min(len(sequence), max_len)
        values = [0] * length
        if length:
            values[-1] = 3
        return torch.tensor(values, dtype=torch.long)


class TrainPhase2V24Tests(unittest.TestCase):
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

    def test_enhanced_pair_head_shapes_and_keeps_contact_head_detached(self) -> None:
        torch.manual_seed(2)
        cfg = self.tiny_config()
        model = CrossContactNetV24(cfg)
        vhh = torch.randn(2, 7, cfg.esm_dim)
        antigen = torch.randn(2, 9, cfg.esm_dim)
        cdr = torch.tensor([[0, 1, 1, 0, 2, 3, 0], [0, 1, 0, 2, 2, 3, 3]])

        logits = model.pair_logits(vhh, cdr, antigen)
        self.assertEqual(tuple(logits.shape), (2,))
        logits.sum().backward()

        for module in (model.q, model.k, model.contact_bias_v, model.contact_bias_a):
            for parameter in module.parameters():
                self.assertTrue(parameter.grad is None or torch.count_nonzero(parameter.grad) == 0)
        self.assertTrue(any(p.grad is not None and torch.count_nonzero(p.grad) > 0 for p in model.pair_rank_head.parameters()))

    def test_listwise_loss_rewards_positive_above_all_negatives_and_is_finite(self) -> None:
        owners = torch.tensor([0, 0, 1, 1], dtype=torch.long)
        weights = torch.tensor([0.5, 1.25, 1.0, 1.25])
        good = listwise_group_ranking_loss(
            torch.tensor([4.0, 3.0]), torch.tensor([0.0, -1.0, 0.0, -2.0]), owners, weights, 0.5
        )
        bad = listwise_group_ranking_loss(
            torch.tensor([0.0, -1.0]), torch.tensor([4.0, 3.0, 2.0, 1.0]), owners, weights, 0.5
        )
        extreme = listwise_group_ranking_loss(
            torch.tensor([1000.0, -1000.0]), torch.tensor([-1000.0, 1000.0]), torch.tensor([0, 1]), torch.ones(2), 0.2
        )
        self.assertLess(float(good), float(bad))
        self.assertTrue(torch.isfinite(extreme))

    def test_typed_margin_loss_uses_owner_margin_and_weight(self) -> None:
        pos = torch.tensor([2.0, 1.0])
        neg = torch.tensor([0.0, 0.5, 2.0])
        owners = torch.tensor([0, 0, 1])
        margins = torch.tensor([0.15, 0.35, 0.35])
        weights = torch.tensor([0.5, 1.25, 1.25])
        loss = typed_pairwise_margin_loss(pos, neg, owners, margins, weights)
        self.assertTrue(torch.isfinite(loss))
        self.assertGreater(float(loss), 0.0)

    def test_group_dataset_keeps_complete_groups_and_drops_unresolved_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.csv"
            rows = [
                ["g1", "train", "p1", "p1", "observed_cognate_positive", "positive_anchor", "AAAA", "CCCC", 1, "cognate", "observed", 1, 0, "yes"],
                ["g1", "train", "p1", "n1", "constructed_contrastive_candidate", "N1_easy_cross_antigen", "AAAA", "DDDD", 0, "constructed", "constructed_preference_not_verified_nonbinder", 0.5, 0.15, "no"],
                ["g1", "train", "p1", "n2", "constructed_contrastive_candidate", "N3_framework_similar_hard_vhh", "XAAA", "CCCC", 0, "constructed", "constructed_preference_not_verified_nonbinder", 1.25, 0.35, "no"],
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["ranking_group_id", "split", "positive_pair_id", "candidate_pair_id", "candidate_role", "negative_type", "vhh_seq", "antigen_seq", "preference_label", "label_source", "proxy_label_policy", "ranking_weight", "ranking_margin", "ordinary_bce_eligible"])
                writer.writerows(rows)
            ds = RankingGroupDataset(path, "train", self.tiny_config(), FakeCache(8), FakeCDR())
            self.assertEqual(len(ds), 1)
            self.assertEqual(ds.excluded_unresolved_cdr_rows, 1)
            batch = collate_rank_groups([ds[0]])
            self.assertEqual(tuple(batch["pos_vhh"].shape), (1, 4, 8))
            self.assertEqual(tuple(batch["neg_vhh"].shape), (1, 4, 8))
            self.assertEqual(batch["neg_owner"].tolist(), [0])

    def test_random_group_baseline_is_exact(self) -> None:
        baseline = random_ranking_baselines([4, 4, 2])
        self.assertAlmostEqual(baseline["ranking_hit_at_1"], (0.25 + 0.25 + 0.5) / 3.0)
        self.assertAlmostEqual(baseline["ranking_hard_negative_win_rate"], 0.5)
        self.assertGreater(baseline["ranking_mrr"], baseline["ranking_hit_at_1"])

    def test_v23_warmstart_loads_shared_backbone_and_skips_old_pair_head(self) -> None:
        cfg = self.tiny_config()
        model = CrossContactNetV24(cfg)
        state = {name: torch.full_like(value, 0.25) for name, value in model.state_dict().items() if not name.startswith("pair_")}
        state["pair.0.weight"] = torch.ones((1, 1))
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "v23.pt"
            torch.save({"model": state}, checkpoint)
            result = load_v23_warmstart(model, checkpoint)
        self.assertGreater(result["loaded_keys"], 0)
        self.assertIn("pair.0.weight", result["skipped_source_keys"])
        self.assertTrue(torch.allclose(model.esm_project.weight, torch.full_like(model.esm_project.weight, 0.25)))


if __name__ == "__main__":
    unittest.main()
