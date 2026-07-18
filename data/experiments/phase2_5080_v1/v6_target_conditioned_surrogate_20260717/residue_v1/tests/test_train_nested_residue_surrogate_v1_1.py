import csv
import gzip
import hashlib
import importlib.util
import json
import pathlib
import random
import sys
import tempfile
import unittest
from collections import Counter

import numpy as np
import torch


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "train_nested_residue_surrogate_v1_1.py"
spec = importlib.util.spec_from_file_location("residue_v1_1_trainer", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestFrozenInnerProtocol(unittest.TestCase):
    def test_exact_upper_v6_inner_hash_and_five_folds(self):
        parent = "PARENT_X"
        observed = [mod.parent_inner_fold(parent, outer) for outer in range(5)]
        expected = [
            int(hashlib.sha256(f"PVRIG_V6_INNER|outer={outer}|{parent}".encode()).hexdigest(), 16) % 5
            for outer in range(5)
        ]
        self.assertEqual(observed, expected)
        self.assertTrue(all(0 <= value < 5 for value in observed))

    def test_lexicographic_key_and_rounded_median_epoch(self):
        stronger_primary = {"spearman": 0.3, "parent_centered_spearman": -1, "top20_recall": 0, "mae": 1}
        weaker_primary = {"spearman": 0.2, "parent_centered_spearman": 1, "top20_recall": 1, "mae": 0}
        self.assertGreater(mod.selection_key(stronger_primary), mod.selection_key(weaker_primary))
        self.assertEqual(mod.rounded_median_epoch([2, 3, 9]), 3)
        self.assertEqual(mod.rounded_median_epoch([2, 3, 8, 9]), 6)


class TestParentAwareBatchSampler(unittest.TestCase):
    def test_deterministic_exhaustive_and_parent_paired(self):
        parents = [parent for parent in ("P0", "P1", "P2", "P3") for _ in range(4)]
        first = list(mod.ParentAwareBatchSampler(parents, batch_size=4, per_parent=2, seed=1931))
        second = list(mod.ParentAwareBatchSampler(parents, batch_size=4, per_parent=2, seed=1931))
        self.assertEqual(first, second)
        self.assertEqual(sorted(index for batch in first for index in batch), list(range(16)))
        for batch in first:
            counts = Counter(parents[index] for index in batch)
            self.assertTrue(all(value % 2 == 0 for value in counts.values()))


class TestProductionBindings(unittest.TestCase):
    def test_actual_materialized_table_has_exact_126_structure_features(self):
        table = ROOT.parent / "data" / "materialized_v1_1" / "v6_supervised1507.tsv"
        with table.open(encoding="utf-8-sig") as handle:
            fields = next(csv.reader(handle, delimiter="\t"))
        observed = mod.real_structure_feature_names(fields)
        self.assertEqual(len(observed), 126)
        self.assertEqual(len(observed), len(set(observed)))

    def test_contact_receipt_binds_exact_target_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "targets.tsv.gz"
            target.write_bytes(b"contact-target")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            receipt = root / "RUN_RECEIPT.json"
            receipt.write_text(json.dumps({
                "schema_version": "pvrig_v6_residue_dual_contact_targets_v1_receipt",
                "status": "PASS_DUAL_CONTACT_TARGETS_MATERIALIZED",
                "output": {"path": target.name, "sha256": digest},
            }))
            self.assertEqual(mod.validate_contact_receipt(receipt, target), digest)
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(Exception, "contact_receipt_output_sha256_mismatch"):
                mod.validate_contact_receipt(receipt, target)

    def test_rng_roundtrip_restores_python_numpy_and_torch(self):
        random.seed(7)
        np.random.seed(7)
        torch.manual_seed(7)
        state = mod.capture_rng_state()
        expected = (random.random(), float(np.random.rand()), float(torch.rand(1)))
        mod.restore_rng_state(state)
        observed = (random.random(), float(np.random.rand()), float(torch.rand(1)))
        self.assertEqual(expected, observed)

    def test_metrics_reconcile_drops_uncheckpointed_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "metrics.jsonl"
            path.write_text("".join(json.dumps({"epoch": epoch}) + "\n" for epoch in range(4)))
            mod.reconcile_metrics_jsonl(path, start_epoch=3)
            observed = [json.loads(line)["epoch"] for line in path.read_text().splitlines()]
            self.assertEqual(observed, [0, 1, 2])


class TestV11EndToEndResume(unittest.TestCase):
    def write_fixture(self, root):
        training = root / "training.tsv"
        fields = [
            "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
            "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight",
            "feature_0", "feature_1", "feature_2", "feature_3",
        ]
        rows = []
        for outer in range(5):
            for parent_index in range(4):
                parent = f"O{outer}_P{parent_index}"
                for variant in range(2):
                    candidate = f"{parent}_V{variant}"
                    sequence = "ACDEFGHI" if variant == 0 else "ACDEYGHI"
                    feature = outer * 0.2 + parent_index * 0.05 + variant * 0.01
                    r8 = 0.44 + 0.03 * feature
                    r9 = 0.54 - 0.01 * feature
                    rows.append({
                        "candidate_id": candidate, "sequence": sequence,
                        "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                        "parent_framework_cluster": parent, "outer_fold": outer,
                        "R_8X6B": r8, "R_9E6Y": r9, "R_dual_min": min(r8, r9),
                        "sample_weight": 1.0, "feature_0": feature,
                        "feature_1": feature**2, "feature_2": variant, "feature_3": outer,
                    })
        with training.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        contact = root / "contact.tsv.gz"
        contact_fields = sorted(mod.v1.CONTACT_REQUIRED)
        with gzip.open(contact, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=contact_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                for index, aa in enumerate(row["sequence"], start=1):
                    writer.writerow({
                        "candidate_id": row["candidate_id"], "sequence_sha256": row["sequence_sha256"],
                        "parent_framework_cluster": row["parent_framework_cluster"],
                        "vhh_sequence_index": index, "vhh_aa": aa,
                        "contact_target_8x6b": 0.7 if index == 4 else 0.0,
                        "contact_target_9e6y": 0.8 if index == 5 else 0.0,
                        "target_mask_8x6b": 1, "target_mask_9e6y": 1,
                    })
        contact_hash = hashlib.sha256(contact.read_bytes()).hexdigest()
        receipt = root / "RUN_RECEIPT.json"
        receipt.write_text(json.dumps({
            "schema_version": "pvrig_v6_residue_dual_contact_targets_v1_receipt",
            "status": "PASS_DUAL_CONTACT_TARGETS_MATERIALIZED",
            "output": {"path": contact.name, "sha256": contact_hash},
        }))
        return training, contact, receipt

    def test_nested_smoke_has_resumable_state_and_single_outer_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            training, contact, receipt = self.write_fixture(root)
            argv = [
                "--training-tsv", str(training), "--contact-tsv-gz", str(contact),
                "--contact-receipt", str(receipt), "--output-dir", str(root / "run"),
                "--smoke-mode", "--structure-prefix", "feature_", "--structure-dim", "4",
                "--outer-fold", "0", "--ridge-alpha", "1", "--backbone-kind", "tiny",
                "--backbone-mode", "frozen", "--tiny-hidden-size", "8", "--fusion-dim", "8",
                "--max-epochs", "1", "--batch-size", "4", "--per-parent-batch", "2",
                "--gradient-accumulation", "2", "--precision", "fp32", "--device", "cpu",
                "--safe-stop-free-gb", "0", "--checkpoint-min-free-gb", "0",
            ]
            args = mod.parser().parse_args(argv)
            first = mod.train(args)
            self.assertEqual(first["status"], "PASS_OUTER_FOLD_COMPLETE")
            self.assertEqual(first["outer_evaluation_count"], 1)
            self.assertGreaterEqual(len(first["inner_results"]), 2)
            checkpoint = torch.load(root / "run" / "final_refit" / "last.pt", map_location="cpu", weights_only=False)
            self.assertIn("optimizer", checkpoint)
            self.assertIn("scheduler", checkpoint)
            self.assertIn("rng_state", checkpoint)
            self.assertTrue((root / "run" / "final_refit" / "metrics.jsonl").is_file())
            self.assertTrue(all(name.startswith("head.") for name in checkpoint["trainable_state"]))
            seal = json.loads((root / "run" / "OUTER_EVALUATION_SEAL.json").read_text())
            self.assertEqual(seal["status"], "SEALED_COMPLETE_ONE_EVALUATION")
            args.resume = True
            second = mod.train(args)
            self.assertEqual(second, first)
            self.assertEqual(second["outer_evaluation_count"], 1)


if __name__ == "__main__":
    unittest.main()
