#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

import argparse
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2_v3_model import (  # noqa: E402
    BindingPriorModel,
    EmbeddingBank,
    fixed_esm2_cosine,
    within_target_pairwise_loss,
)
from prepare_phase2_v3_embeddings import prepare_embeddings  # noqa: E402
from train_phase2_v3_binding_prior import TrainConfig, train  # noqa: E402


class Phase2V3TrainingTests(unittest.TestCase):
    def bank(self) -> EmbeddingBank:
        return EmbeddingBank(
            index_by_sha256={str(i): i for i in range(5)},
            sequence_sha256=[str(i) for i in range(5)],
            esm2=torch.randn(5, 4),
            vhhbert=torch.randn(5, 6),
            physchem=torch.randn(5, 3),
            config_sha256="test",
        )

    def test_all_variants_produce_one_logit_per_pair(self) -> None:
        bank = self.bank()
        vhh = torch.tensor([0, 1, 2])
        target = torch.tensor([3, 3, 4])
        for variant in ("vhh_only", "esm2_pair", "v3_full"):
            model = BindingPriorModel(variant, 4, 6, 3, 5, 8, 0.0)
            self.assertEqual(tuple(model(bank, vhh, target).shape), (3,))

    def test_pairwise_loss_prefers_positive_above_negative(self) -> None:
        labels = torch.tensor([1.0, 0.0, 1.0, 0.0])
        targets = torch.tensor([0, 0, 1, 1])
        good = within_target_pairwise_loss(torch.tensor([2.0, -2.0, 1.0, -1.0]), labels, targets)
        bad = within_target_pairwise_loss(torch.tensor([-2.0, 2.0, -1.0, 1.0]), labels, targets)
        self.assertLess(float(good), float(bad))

    def test_fixed_cosine_uses_only_esm2(self) -> None:
        bank = self.bank()
        score = fixed_esm2_cosine(bank, torch.tensor([0]), torch.tensor([1]))
        expected = torch.nn.functional.cosine_similarity(bank.esm2[[0]], bank.esm2[[1]])
        self.assertTrue(torch.allclose(score, expected))

    def test_tiny_training_run_freezes_all_variants_and_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequences = []
            for index, aa in enumerate("ACDEFG"):
                sequence = "QVQL" + aa * 96
                sequences.append({"sequence_sha256": f"v{index}", "sequence": sequence, "sequence_length": 100, "roles": "vhh"})
            for index, aa in enumerate("IK"):
                sequences.append({"sequence_sha256": f"t{index}", "sequence": aa * 40, "sequence_length": 40, "roles": "antigen"})
            pd.DataFrame(sequences).to_csv(root / "sequences.csv", index=False)
            prepare_embeddings(
                argparse.Namespace(
                    sequence_manifest=root / "sequences.csv",
                    output_dir=root / "embeddings",
                    backend="hash",
                    device="cpu",
                    vhhbert_model_path=root / "unused",
                    esm2_model_path=root / "unused",
                    vhhbert_state_path=root / "unused.pt",
                    safetensors_package_dir=root / "unused_pkg",
                    vhhbert_batch_size=4,
                    esm_batch_size=4,
                    shard_size=4,
                    max_esm_residues=100,
                    chunk_overlap=0,
                    hash_vhhbert_dim=6,
                    hash_esm2_dim=4,
                )
            )
            rows = []
            sample = 0
            for split, vhh_ids in (("train", range(4)), ("dev", range(4, 6))):
                for target in range(2):
                    for vhh in vhh_ids:
                        rows.append(
                            {
                                "sample_id": f"s{sample}",
                                "split": split,
                                "target_id": f"target{target}",
                                "sequence_sha256": f"v{vhh}",
                                "target_sequence_sha256": f"t{target}",
                                "label": int((vhh + target) % 2 == 0),
                                "sealed_status": "OPEN_DEVELOPMENT",
                                "ground_truth_kind": "real_assay_binary_binding",
                                "allowed_use": "GENERIC_BINDING_PRIOR_ONLY",
                            }
                        )
                        sample += 1
            pd.DataFrame(rows).to_csv(root / "records.csv", index=False)
            (root / "formal.csv").write_text("sample_id\n", encoding="utf-8")
            prereg = {
                "seeds": [43],
                "eligible_baselines": ["prevalence", "frozen_esm2_cosine", "vhh_only", "esm2_pair"],
            }
            for name, payload in (("prereg.json", prereg), ("test.json", {}), ("config.json", {})):
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            summary = train(
                TrainConfig(
                    records_csv=str(root / "records.csv"),
                    formal_blinded_csv=str(root / "formal.csv"),
                    embedding_manifest=str(root / "embeddings/embedding_manifest_v3.csv"),
                    preregistration_json=str(root / "prereg.json"),
                    test_spec_json=str(root / "test.json"),
                    source_config_json=str(root / "config.json"),
                    out_dir=str(root / "runs"),
                    seeds=(43,),
                    epochs=2,
                    batch_size=8,
                    inference_batch_size=8,
                    latent_dim=4,
                    hidden_dim=8,
                    dropout=0.0,
                    early_stopping_patience=2,
                    device="cpu",
                )
            )
            self.assertEqual(set(summary["results"]), {"vhh_only", "esm2_pair", "v3_full", "v3_full_label_shuffle", "v3_full_target_shuffle"})
            self.assertIn(summary["preregistered_baseline_selection"]["selected_baseline"], prereg["eligible_baselines"])
            self.assertEqual(summary["formal_unseal_status"], "SEALED_LABELS_NOT_READ")


if __name__ == "__main__":
    unittest.main()
