#!/usr/bin/env python3
from __future__ import annotations

import sys
import argparse
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_phase2_v3_formal import evaluate, merge_labels  # noqa: E402
from prepare_phase2_v3_embeddings import prepare_embeddings  # noqa: E402
from train_phase2_v3_binding_prior import TrainConfig, train  # noqa: E402


class Phase2V3FormalTests(unittest.TestCase):
    def test_label_join_requires_exact_ids_and_preserves_block(self) -> None:
        blinded = pd.DataFrame(
            [
                {"sample_id": "a", "formal_block": "external_hTNFa"},
                {"sample_id": "b", "formal_block": "external_hTNFa"},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.csv"
            pd.DataFrame(
                [
                    {"sample_id": "a", "formal_block": "external_hTNFa", "label": 1, "sealed_status": "SEALED_LABELS"},
                    {"sample_id": "b", "formal_block": "external_hTNFa", "label": 0, "sealed_status": "SEALED_LABELS"},
                ]
            ).to_csv(path, index=False)
            merged = merge_labels(blinded, path)
            self.assertEqual(merged["label"].tolist(), [1, 0])
            bad = Path(tmp) / "bad.csv"
            pd.DataFrame(
                [{"sample_id": "a", "formal_block": "other", "label": 1, "sealed_status": "SEALED_LABELS"}]
            ).to_csv(bad, index=False)
            with self.assertRaises(ValueError):
                merge_labels(blinded, bad)

    def test_synthetic_one_shot_formal_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequences = []
            for index, aa in enumerate("ACDEFGHIKL"):
                sequences.append(
                    {"sequence_sha256": f"v{index}", "sequence": "QVQL" + aa * 96, "sequence_length": 100, "roles": "vhh"}
                )
            for index, aa in enumerate("MNP"):
                sequences.append(
                    {"sequence_sha256": f"t{index}", "sequence": aa * 40, "sequence_length": 40, "roles": "antigen"}
                )
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
                    shard_size=8,
                    max_esm_residues=100,
                    chunk_overlap=0,
                    hash_vhhbert_dim=6,
                    hash_esm2_dim=4,
                )
            )
            development = []
            sample = 0
            for split, vhh_ids in (("train", range(4)), ("dev", range(4, 6))):
                for target in range(2):
                    for vhh in vhh_ids:
                        development.append(
                            {
                                "sample_id": f"d{sample}",
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
            pd.DataFrame(development).to_csv(root / "records.csv", index=False)
            formal = []
            labels = []
            for index, vhh in enumerate(range(6, 10)):
                sample_id = f"f{index}"
                formal.append(
                    {
                        "sample_id": sample_id,
                        "formal_block": "external_hTNFa",
                        "target_id": "target2",
                        "sequence_sha256": f"v{vhh}",
                        "target_sequence_sha256": "t2",
                        "sealed_status": "SEALED_LABELS",
                    }
                )
                labels.append(
                    {
                        "sample_id": sample_id,
                        "formal_block": "external_hTNFa",
                        "label": int(index % 2 == 0),
                        "sealed_status": "SEALED_LABELS",
                    }
                )
            pd.DataFrame(formal).to_csv(root / "formal.csv", index=False)
            pd.DataFrame(labels).to_csv(root / "labels.csv", index=False)
            prereg = {
                "seeds": [43],
                "eligible_baselines": ["prevalence", "frozen_esm2_cosine", "vhh_only", "esm2_pair"],
                "gate": {"bootstrap_replicates": 20},
            }
            (root / "prereg.json").write_text(json.dumps(prereg), encoding="utf-8")
            (root / "test.json").write_text("{}", encoding="utf-8")
            (root / "config.json").write_text(json.dumps({"primary_formal_block": "external_hTNFa"}), encoding="utf-8")
            trained = train(
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
            args = argparse.Namespace(
                run_dir=Path(trained["run_dir"]),
                formal_labels=root / "labels.csv",
                device="cpu",
                batch_size=8,
            )
            result = evaluate(args)
            self.assertEqual(result["formal_unseal_status"], "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE")
            with self.assertRaises(RuntimeError):
                evaluate(args)


if __name__ == "__main__":
    unittest.main()
