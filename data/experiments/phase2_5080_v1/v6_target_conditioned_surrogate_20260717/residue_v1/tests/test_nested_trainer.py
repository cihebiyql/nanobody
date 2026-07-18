import argparse
import csv
import gzip
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import torch


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import train_nested_residue_surrogate as mod


class TestCrossFitM2(unittest.TestCase):
    def test_held_inner_labels_do_not_change_their_own_predictions(self):
        parents = [f"P{index:02d}" for index in range(18) for _ in range(2)]
        structure = np.column_stack((np.linspace(-2, 2, len(parents)), np.sin(np.arange(len(parents)))))
        targets = np.column_stack((0.5 + 0.02 * structure[:, 0], 0.52 - 0.01 * structure[:, 1], 0.49 + 0.01 * structure[:, 0]))
        arrays = {"parents": parents, "structure": structure, "targets": targets.copy(), "weights": np.ones(len(parents))}
        indices = np.arange(len(parents))
        original, counts = mod.crossfit_m2(indices, arrays, outer_fold=2, inner_folds=3, alpha=1.0)
        assignments = np.asarray([mod.parent_inner_fold(parent, 2, 3) for parent in parents])
        held_fold = sorted(counts)[0]
        held = assignments == held_fold
        changed = dict(arrays)
        changed["targets"] = arrays["targets"].copy()
        changed["targets"][held] += 100.0
        perturbed, _ = mod.crossfit_m2(indices, changed, outer_fold=2, inner_folds=3, alpha=1.0)
        np.testing.assert_array_equal(original[held], perturbed[held])
        self.assertFalse(np.array_equal(original[~held], perturbed[~held]))


class TestNestedCpuSmoke(unittest.TestCase):
    def write_tables(self, root: pathlib.Path):
        training = root / "training.tsv"
        fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
            "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight",
            "feature_0", "feature_1", "feature_2", "feature_3",
        ]
        rows = []
        for fold in range(5):
            for parent_index in range(5):
                parent = f"OUTER{fold}_P{parent_index}"
                for variant in range(2):
                    candidate = f"{parent}_V{variant}"
                    sequence = "ACDEFGHIK" if variant == 0 else "ACDEYGHIK"
                    f0 = fold * 0.2 + parent_index * 0.1 + variant * 0.03
                    r8 = 0.46 + 0.02 * f0
                    r9 = 0.52 - 0.01 * f0
                    rows.append({
                        "candidate_id": candidate, "sequence": sequence,
                        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                        "parent_framework_cluster": parent, "outer_fold": fold,
                        "R_8X6B": r8, "R_9E6Y": r9, "R_dual_min": min(r8, r9),
                        "sample_weight": 1.0, "feature_0": f0, "feature_1": f0**2,
                        "feature_2": variant, "feature_3": fold,
                    })
        with training.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        contact = root / "contact.tsv.gz"
        contact_fields = sorted(mod.CONTACT_REQUIRED)
        with gzip.open(contact, "wt", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=contact_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                for index, aa in enumerate(row["sequence"], start=1):
                    writer.writerow({
                        "candidate_id": row["candidate_id"],
                        "sequence_sha256": row["sequence_sha256"],
                        "parent_framework_cluster": row["parent_framework_cluster"],
                        "vhh_sequence_index": index, "vhh_aa": aa,
                        "contact_target_8x6b": 0.8 if index in (4, 5) else 0.0,
                        "contact_target_9e6y": 0.7 if index in (5, 6) else 0.0,
                        "target_mask_8x6b": 1, "target_mask_9e6y": 1,
                    })
        return training, contact

    def test_one_outer_fold_produces_adapter_only_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, contact = self.write_tables(root)
            args = argparse.Namespace(
                training_tsv=training, contact_tsv_gz=contact, output_dir=root / "run",
                expected_training_sha256=None, expected_contact_sha256=None, smoke_mode=True,
                structure_prefix=["feature_"], structure_dim=4, outer_fold="0",
                inner_folds=3, inner_validation_fold=0, ridge_alpha=1.0,
                backbone_kind="tiny", backbone_mode="frozen", model_path=None,
                model_identity_file=None, expected_model_sha256=None, trust_remote_code=False,
                lora_r=2, lora_alpha=4, lora_dropout=0.0, lora_target_modules="query,value",
                tiny_hidden_size=8, fusion_dim=8, dropout=0.0, residual_scale=0.1,
                end_to_end_contact_pooling=False, dual_weight=1.0, receptor_weight=0.2,
                contact_weight=0.2, ranking_weight=0.1, residual_weight=0.05,
                huber_delta=0.03, ranking_minimum_delta=0.001, ranking_temperature=0.02,
                max_epochs=1, batch_size=8, learning_rate=1e-3, weight_decay=0.0,
                gradient_clip=1.0, seed=7, device="cpu", minimum_free_gb=0.0,
            )
            summary = mod.train(args)
            self.assertEqual(summary["status"], "PASS_NESTED_RESIDUE_TRAINING_COMPLETE")
            fold = root / "run" / "outer_fold_0"
            checkpoint = torch.load(fold / "adapter_head.pt", map_location="cpu", weights_only=False)
            self.assertTrue(checkpoint["trainable_state"])
            self.assertTrue(all(name.startswith("head.") for name in checkpoint["trainable_state"]))
            result = json.loads((fold / "RESULT.json").read_text())
            self.assertEqual(result["status"], "PASS_OUTER_FOLD_COMPLETE")
            self.assertTrue((fold / "m2_outer_train_fit.npz").is_file())


if __name__ == "__main__":
    unittest.main()

